from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering import joint_workflow as jw
from app.engineering import weld_operation_workflow as wow
from app.engineering.models import (
    REQUIRED_WELDING_FIELDS,
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointBlock,
    JointDocumentRevision,
    JointEvent,
    WeldOperation,
)
from app.engineering.repository import EngineeringRepo
from app.engineering.schemas import (
    ApproveOgsCommand,
    ApprovePtoCommand,
    BlockCommand,
    CancelCommand,
    DocumentRevisionCreate,
    EngineeringDocumentCreate,
    EngineeringDocumentListFilters,
    InvalidateLinkCommand,
    JointCreate,
    JointDocumentRevisionCreate,
    JointListFilters,
    JointListResponse,
    JointRead,
    JointUpdate,
    RejectCommand,
    RevokeCommand,
    SetCurrentRevisionCommand,
    SubmitForReviewCommand,
    SupersedeCommand,
    UnblockCommand,
    WeldOperationCancelRequest,
    WeldOperationCompleteRequest,
    WeldOperationCreate,
    WeldOperationListFilters,
    WeldOperationListResponse,
    WeldOperationRead,
    WeldOperationUpdate,
)
from app.hr.repository import HrRepo
from app.projects.repository import ProjectRepo
from app.welding.repository import WeldingRepo
from app.shared.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    RoleDeniedError,
    ValidationError,
    VersionConflictError,
)
from app.shared.permissions import (
    JointScopeContext,
    RoleRequirement,
    check_worker_role,
    worker_role_codes_for_joint,
)

# Владелец инженерных документов и ревизий — ПТО (IP-07). Технический role_code
# существующего backend.
ENGINEERING_OWNER_ROLE = "PTO_ENGINEER"

# Все роли, релевантные жизненному циклу Joint (для расчёта available_actions).
_LIFECYCLE_ROLES = jw.PTO_ROLES | jw.OGS_ROLES | frozenset({jw.AUDITOR_ROLE})

# Типографские дефисы/минус → обычный дефис при нормализации joint_no.
_DASH_CHARS = "‐‑‒–—―−"
_DASH_RE = re.compile(f"[{_DASH_CHARS}]")
_WHITESPACE_RE = re.compile(r"\s+")

# Инженерные поля Joint, редактируемые при создании и PATCH (без служебных и
# защищённых). Единый список для копирования из create-схемы в модель.
_JOINT_ENGINEERING_FIELDS = (
    "dn_1",
    "dn_2",
    "thickness_1",
    "thickness_2",
    "material_id_1",
    "material_id_2",
    "material_text_1",
    "material_text_2",
    "component_type_1",
    "component_type_2",
    "component_item_id_1",
    "component_item_id_2",
    "component_text_1",
    "component_text_2",
    "geometry_type",
    "weld_joint_type",
    "connection_code",
    "required_root_method",
    "required_fill_method",
    "required_cap_method",
    "planned_wps_id",
    "heat_treatment_required",
    "heat_treatment_type",
    "heat_treatment_note",
    "sheet_no",
    "drawing_zone",
    "position_x",
    "position_y",
    "coordinate_system",
    "location_note",
    "document_note",
)

# Единый источник соответствия «колонка снимка → поле Joint» (Task 6). Снимок
# фиксирует идентичность (joint_no + нормализация + line_id) и все инженерные поля
# Task 5A. По этому же mapping поля Joint восстанавливаются из выбранного снимка при
# смене текущей ревизии (обратное отображение snapshot_* → поле Joint). Единый
# источник истины и для создания снимка, и для восстановления.
_SNAPSHOT_JOINT_FIELDS = (
    "joint_no",
    "joint_no_normalized",
    "line_id",
) + _JOINT_ENGINEERING_FIELDS
SNAPSHOT_FIELD_MAP: dict[str, str] = {
    f"snapshot_{field}": field for field in _SNAPSHOT_JOINT_FIELDS
}


def normalize_joint_no(value: str) -> str:
    """Служебная нормализация номера стыка для сравнения дублей (ADR-010).

    Обрезка по краям → типографские дефисы в `-` → схлопывание внутренних
    пробелов → приведение регистра. Исходное значение при этом не меняется.
    """
    text = value.strip()
    text = _DASH_RE.sub("-", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.upper()


def missing_welding_requirements(joint: Joint) -> list[str]:
    """Незаполненные обязательные инженерные поля (Б-4). Пусто → готов к сварке."""
    return [name for name in REQUIRED_WELDING_FIELDS if getattr(joint, name) is None]


def _requires_review(joint: Joint) -> bool:
    """Требуется проверка, если Joint не в ACTIVE с двумя действующими APPROVED."""
    return (
        joint.status in ("DRAFT", "PENDING_REVIEW")
        or joint.pto_status != "APPROVED"
        or joint.ogs_status != "APPROVED"
    )


def joint_to_read(
    joint: Joint,
    *,
    available_actions: list[str] | None = None,
    is_blocked: bool = False,
) -> JointRead:
    """Собирает ответ с вычисляемыми полями (не колонки БД).

    `version` сохранён как зеркало record_version (обратная совместимость Task 5A).
    """
    missing = missing_welding_requirements(joint)
    columns = {c.name: getattr(joint, c.name) for c in Joint.__table__.columns}
    return JointRead(
        **columns,
        version=joint.record_version,
        ready_for_welding=not missing,
        missing_welding_requirements=missing,
        production_state="NOT_STARTED",
        requires_review=_requires_review(joint),
        is_blocked=is_blocked,
        available_actions=available_actions or [],
    )


# ── Хелперы согласований Joint (Task 5B) ──────────────────────────────────────


class _StatusSnapshot:
    """Снимок статусов Joint до мутации (для before-полей истории)."""

    __slots__ = ("status", "pto_status", "ogs_status")

    def __init__(self, status: str, pto_status: str, ogs_status: str) -> None:
        self.status = status
        self.pto_status = pto_status
        self.ogs_status = ogs_status


def _snapshot(joint: Joint) -> _StatusSnapshot:
    return _StatusSnapshot(joint.status, joint.pto_status, joint.ogs_status)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Соответствие «сторона → префикс колонок» для единообразной работы с ПТО/ОГС.
_SIDE_PREFIX = {"PTO": "pto", "OGS": "ogs"}


def _side_status(joint: Joint, side: str) -> str:
    return getattr(joint, f"{_SIDE_PREFIX[side]}_status")


def _set_side_field(joint: Joint, side: str, field: str, value) -> None:
    setattr(joint, f"{_SIDE_PREFIX[side]}_{field}", value)


def _set_side(
    joint: Joint,
    side: str,
    *,
    status: str,
    pending_reason: str | None,
    decision_method: str | None,
    approval_version: int | None,
    decided_by: int | None,
    decided_at: datetime | None,
    comment: str | None,
) -> None:
    """Единообразно проставляет все поля согласования одной стороны."""
    prefix = _SIDE_PREFIX[side]
    setattr(joint, f"{prefix}_status", status)
    setattr(joint, f"{prefix}_pending_reason", pending_reason)
    setattr(joint, f"{prefix}_decision_method", decision_method)
    setattr(joint, f"{prefix}_approval_version", approval_version)
    setattr(joint, f"{prefix}_decided_by", decided_by)
    setattr(joint, f"{prefix}_decided_at", decided_at)
    setattr(joint, f"{prefix}_comment", comment)


class EngineeringService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # --- права (IP-05, scope GLOBAL / PROJECT / LINE) ---

    def _forbidden(self) -> HTTPException:
        return HTTPException(
            status_code=403,
            detail="Недостаточно прав: требуется роль ПТО (PTO_ENGINEER)",
        )

    def _require_permission(
        self, worker_id: int, project_id: UUID, line_id: UUID | None
    ) -> None:
        """Единая проверка scope для создания и переходов.

        Допустимо: GLOBAL всегда; PROJECT со scope_id == project_id; LINE только
        если сущность привязана к line_id и scope_id == line_id.
        """
        requirements = [
            RoleRequirement(ENGINEERING_OWNER_ROLE, "GLOBAL"),
            RoleRequirement(ENGINEERING_OWNER_ROLE, "PROJECT", str(project_id)),
        ]
        if line_id is not None:
            requirements.append(
                RoleRequirement(ENGINEERING_OWNER_ROLE, "LINE", str(line_id))
            )
        if not any(
            check_worker_role(self._db, worker_id, req) for req in requirements
        ):
            raise self._forbidden()

    # --- консистентность project / line ---

    def _validate_project_and_line(
        self, project_id: UUID, line_id: UUID | None
    ) -> None:
        if self._projects.get_project(project_id) is None:
            raise NotFoundError("Проект", project_id)
        if line_id is not None:
            line = self._projects.get_line(line_id)
            if line is None or line.project_id != project_id:
                raise ValidationError(
                    "line_id не найден или принадлежит другому проекту"
                )

    # --- документы ---

    def get_document(self, document_id: UUID) -> EngineeringDocument:
        document = self._repo.get_document(document_id)
        if document is None:
            raise NotFoundError("Инженерный документ", document_id)
        return document

    def list_documents(
        self, filters: EngineeringDocumentListFilters
    ) -> list[EngineeringDocument]:
        return self._repo.list_documents(filters)

    def create_document(
        self, data: EngineeringDocumentCreate, *, created_by: int
    ) -> EngineeringDocument:
        # Проверка прав до обращения к БД по контексту документа.
        self._require_permission(created_by, data.project_id, data.line_id)
        self._validate_project_and_line(data.project_id, data.line_id)

        document_no = data.document_no.strip()
        if (
            self._repo.get_document_by_project_and_no(data.project_id, document_no)
            is not None
        ):
            raise ConflictError(
                "Документ с таким document_no в проекте уже существует"
            )

        document = EngineeringDocument(
            project_id=data.project_id,
            line_id=data.line_id,
            document_no=document_no,
            document_type=data.document_type,
            title=data.title,
            status="DRAFT",
            created_by=created_by,
        )
        try:
            return self._repo.create_document(document)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Документ с таким document_no в проекте уже существует"
            ) from exc

    # --- переходы документа ---

    def approve_document(
        self, document_id: UUID, *, worker_id: int
    ) -> EngineeringDocument:
        document = self.get_document(document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)
        self._apply_approve(document, worker_id=worker_id)
        return self._repo.save_document(document)

    def cancel_document(
        self, document_id: UUID, *, worker_id: int
    ) -> EngineeringDocument:
        document = self.get_document(document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)
        self._apply_cancel(document)
        return self._repo.save_document(document)

    def supersede_document(
        self, document_id: UUID, *, worker_id: int
    ) -> EngineeringDocument:
        document = self.get_document(document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)
        self._apply_supersede(document)
        return self._repo.save_document(document)

    # --- ревизии ---

    def list_revisions(self, document_id: UUID) -> list[DocumentRevision]:
        self.get_document(document_id)
        return self._repo.list_revisions(document_id)

    def create_revision(
        self, document_id: UUID, data: DocumentRevisionCreate, *, created_by: int
    ) -> DocumentRevision:
        document = self.get_document(document_id)
        # Scope ревизии наследуется от родительского документа.
        self._require_permission(created_by, document.project_id, document.line_id)

        revision_code = data.revision_code.strip()
        if (
            self._repo.get_revision_by_document_and_code(document_id, revision_code)
            is not None
        ):
            raise ConflictError(
                "Ревизия с таким revision_code в документе уже существует"
            )

        revision = DocumentRevision(
            engineering_document_id=document_id,
            revision_code=revision_code,
            issued_at=data.issued_at,
            status="DRAFT",
            created_by=created_by,
        )
        try:
            return self._repo.create_revision(revision)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Ревизия с таким revision_code в документе уже существует"
            ) from exc

    # --- переходы ревизии ---

    def _get_revision(self, revision_id: UUID) -> DocumentRevision:
        revision = self._repo.get_revision(revision_id)
        if revision is None:
            raise NotFoundError("Ревизия документа", revision_id)
        return revision

    def _require_revision_permission(
        self, revision: DocumentRevision, *, worker_id: int
    ) -> None:
        document = self.get_document(revision.engineering_document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)

    def approve_revision(
        self, revision_id: UUID, *, worker_id: int
    ) -> DocumentRevision:
        revision = self._get_revision(revision_id)
        self._require_revision_permission(revision, worker_id=worker_id)
        self._apply_approve(revision, worker_id=worker_id)
        return self._repo.save_revision(revision)

    def cancel_revision(
        self, revision_id: UUID, *, worker_id: int
    ) -> DocumentRevision:
        revision = self._get_revision(revision_id)
        self._require_revision_permission(revision, worker_id=worker_id)
        self._apply_cancel(revision)
        return self._repo.save_revision(revision)

    def supersede_revision(
        self, revision_id: UUID, *, worker_id: int
    ) -> DocumentRevision:
        revision = self._get_revision(revision_id)
        self._require_revision_permission(revision, worker_id=worker_id)
        self._apply_supersede(revision)
        return self._repo.save_revision(revision)

    # --- централизованные правила переходов ---
    #
    # Переход разрешён только из явно допустимых исходных статусов; иначе 409.
    # Правила общие для EngineeringDocument и DocumentRevision (одинаковый набор
    # статусов). Обобщённого update поля status нет — только эти команды.

    @staticmethod
    def _apply_approve(
        entity: EngineeringDocument | DocumentRevision, *, worker_id: int
    ) -> None:
        if entity.status != "DRAFT":
            raise ConflictError(
                f"Утверждение недопустимо из статуса {entity.status}"
            )
        entity.status = "APPROVED"
        entity.approved_by = worker_id
        entity.approved_at = datetime.now(timezone.utc)

    @staticmethod
    def _apply_cancel(entity: EngineeringDocument | DocumentRevision) -> None:
        if entity.status not in ("DRAFT", "APPROVED"):
            raise ConflictError(f"Отмена недопустима из статуса {entity.status}")
        # approved_by/approved_at сохраняются: отмена ранее утверждённой сущности
        # не стирает факт утверждения (история вместо перезаписи).
        entity.status = "CANCELLED"

    @staticmethod
    def _apply_supersede(entity: EngineeringDocument | DocumentRevision) -> None:
        if entity.status != "APPROVED":
            raise ConflictError(f"Замена недопустима из статуса {entity.status}")
        entity.status = "SUPERSEDED"

    # ── Joint (Task 5A, ADR-010) ─────────────────────────────────────────────
    #
    # Роли и scope-фильтрация в Task 5A не проверяются (двойное согласование
    # ПТО/ОГС — Task 5B). Актор (created_by / updated_by) приходит в теле запроса.

    def get_joint(self, joint_id: UUID) -> Joint:
        joint = self._repo.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def _validate_line_and_revision(
        self, project, line_id: UUID, revision_id: UUID
    ) -> DocumentRevision:
        """Проверка иерархии Project → Line / DocumentRevision (Б-3, ADR-010).

        Возвращает ревизию-основание. Несоответствия линии/ревизии проекту —
        422 (консистентно с проверками модуля engineering); отсутствие ревизии —
        404.
        """
        # Линия существует и относится к проекту.
        line = self._projects.get_line(line_id)
        if line is None or line.project_id != project.id:
            raise ValidationError(
                "line_id не найден или принадлежит другому проекту"
            )

        # Ревизия существует.
        revision = self._repo.get_revision(revision_id)
        if revision is None:
            raise NotFoundError("Ревизия документа", revision_id)

        # Документ ревизии существует и относится к тому же проекту.
        document = self._repo.get_document(revision.engineering_document_id)
        if document is None or document.project_id != project.id:
            raise ValidationError(
                "Ревизия принадлежит документу другого проекта"
            )

        # Согласование линии: если у документа задана линия — она обязана
        # совпадать с линией стыка; если line_id документа пуст — линия берётся
        # из стыка. Тип документа-основания не ограничивается ISOMETRIC.
        if document.line_id is not None and document.line_id != line_id:
            raise ValidationError(
                "Линия документа-основания не совпадает с линией стыка"
            )

        # Единое правило источника Joint (архитектурное ревью Task 7): и документ,
        # и ревизия обязаны быть APPROVED. Тот же доменный helper использует bulk.
        if jw.joint_source_status_error(document.status, revision.status) is not None:
            raise DomainError(
                422,
                jw.DOCUMENT_REVISION_NOT_ALLOWED,
                "Создание Joint возможно только из APPROVED документа и ревизии "
                f"(документ: {document.status}, ревизия: {revision.status})",
            )
        return revision

    def _stage_joint(
        self,
        project,
        *,
        line_id: UUID,
        revision_id: UUID,
        joint_no: str,
        engineering_values: dict,
        created_by: int,
    ) -> Joint:
        """Строит Joint и его ORIGIN/PRIMARY-связь истории в текущей транзакции.

        Выдаёт `system_code` (транзакционная последовательность проекта), собирает
        Joint (DRAFT, origin==current, версии=1, согласования — server_default
        NOT_SUBMITTED) и добавляет ORIGIN/PRIMARY-связь со снимком (Task 6, правило
        3). Без commit — переиспользуется одиночным созданием и bulk-импортом, чтобы
        доменная логика (нормализация, номер, снимок) не расходилась.
        """
        sequence = self._repo.next_system_sequence(project.id)
        system_code = f"{project.code}-JNT-{sequence:04d}"
        joint = Joint(
            project_id=project.id,
            line_id=line_id,
            origin_document_revision_id=revision_id,
            current_document_revision_id=revision_id,
            system_code=system_code,
            joint_no=joint_no,
            joint_no_normalized=normalize_joint_no(joint_no),
            status="DRAFT",
            record_version=1,
            approval_version=1,
            workflow_version=1,
            created_by=created_by,
            updated_by=created_by,
            **engineering_values,
        )
        self._repo.add_joint(joint)
        self._repo.add_link(
            self._build_link(
                joint,
                document_revision_id=joint.origin_document_revision_id,
                revision_role="ORIGIN",
                document_role="PRIMARY",
                created_by=created_by,
            )
        )
        return joint

    def create_joint(self, data: JointCreate) -> Joint:
        project = self._projects.get_project(data.project_id)
        if project is None:
            raise NotFoundError("Проект", data.project_id)

        self._validate_line_and_revision(
            project, data.line_id, data.document_revision_id
        )

        normalized = normalize_joint_no(data.joint_no)
        if self._repo.get_joint_by_revision_and_normalized(
            current_document_revision_id=data.document_revision_id,
            joint_no_normalized=normalized,
        ) is not None:
            raise ConflictError(
                "Стык с таким номером в этой ревизии документа уже существует"
            )

        # Сервисная валидация иерархии/дубля выполнена ДО выдачи номера, чтобы
        # неуспех не расходовал последовательность (номера не переиспользуются).
        engineering_values = data.model_dump(include=set(_JOINT_ENGINEERING_FIELDS))
        try:
            joint = self._stage_joint(
                project,
                line_id=data.line_id,
                revision_id=data.document_revision_id,
                joint_no=data.joint_no,
                engineering_values=engineering_values,
                created_by=data.created_by,
            )
            return self._repo.save_joint(joint)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Стык с таким номером в этой ревизии документа уже существует"
            ) from exc

    def list_joints(self, filters: JointListFilters) -> JointListResponse:
        if filters.joint_no is not None:
            filters.joint_no_normalized = normalize_joint_no(filters.joint_no)
        total = self._repo.count_joints(filters)
        items = self._repo.list_joints(filters)
        # is_blocked — одним агрегатным запросом (без N+1). available_actions в
        # массовых списках не считается (§23 ADR-011).
        blocked = self._repo.blocked_joint_ids([joint.id for joint in items])
        return JointListResponse(
            items=[
                joint_to_read(joint, is_blocked=joint.id in blocked)
                for joint in items
            ],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def update_joint(self, joint_id: UUID, data: JointUpdate) -> JointRead:
        """PATCH инженерных/служебных полей.

        DRAFT — как Task 5A: любые редактируемые поля, только record_version.
        PENDING_REVIEW/ACTIVE (Task 5B): изменение идентичности (joint_no/line_id)
        запрещено (SUPERSEDE_REQUIRED); значимое изменение поднимает
        approval_version и выборочно сбрасывает затронутые согласования (§9);
        служебное — только record_version. Терминальный Joint не редактируется.
        """
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)

        # Optimistic locking: expected_version сверяется с record_version.
        if joint.record_version != data.expected_version:
            raise VersionConflictError(
                jw.RECORD_VERSION_CONFLICT,
                expected_version=data.expected_version,
                current_version=joint.record_version,
            )

        changes = data.model_dump(
            exclude_unset=True, exclude={"expected_version", "updated_by"}
        )
        changed_fields = set(changes.keys())

        # Идентичность (joint_no/line_id) вне DRAFT меняется только через замену.
        if joint.status != "DRAFT" and (changed_fields & jw.IDENTITY_FIELDS):
            raise DomainError(
                409,
                jw.SUPERSEDE_REQUIRED,
                "Изменение идентичности Joint (joint_no/line_id) после DRAFT "
                "требует создания нового Joint и замены (SUPERSEDE)",
            )

        # --- вся валидация ДО мутации объекта ---
        if "line_id" in changes and changes["line_id"] != joint.line_id:
            self._revalidate_line_for_current_revision(
                joint.project_id, changes["line_id"], joint.current_document_revision_id
            )

        eff_x = changes.get("position_x", joint.position_x)
        eff_y = changes.get("position_y", joint.position_y)
        eff_cs = changes.get("coordinate_system", joint.coordinate_system)
        if (eff_x is not None or eff_y is not None) and eff_cs is None:
            raise ValidationError(
                "coordinate_system обязателен при заданных position_x/position_y"
            )

        normalized: str | None = None
        if "joint_no" in changes:
            normalized = normalize_joint_no(changes["joint_no"])
            existing = self._repo.get_joint_by_revision_and_normalized(
                current_document_revision_id=joint.current_document_revision_id,
                joint_no_normalized=normalized,
            )
            if existing is not None and existing.id != joint.id:
                raise ConflictError(
                    "Стык с таким номером в этой ревизии документа уже существует"
                )

        before = _snapshot(joint)

        # --- мутация полей ---
        if normalized is not None:
            joint.joint_no_normalized = normalized
        for field, value in changes.items():
            setattr(joint, field, value)
        joint.updated_by = data.updated_by

        # --- версии и выборочный сброс согласований ---
        if joint.status == "DRAFT":
            # DRAFT: согласований ещё нет — только record_version (как Task 5A).
            self._bump_record(joint)
        else:
            significant = changed_fields & jw.SIGNIFICANT_FIELDS
            if significant:
                self._bump_approval(joint)
                self._reset_affected_approvals(
                    joint,
                    jw.affected_sides(significant),
                    actor_worker_id=data.updated_by,
                )
                if joint.status == "ACTIVE":
                    joint.status = "PENDING_REVIEW"
                self._record_event(
                    joint,
                    "SIGNIFICANT_EDIT",
                    actor_worker_id=data.updated_by,
                    actor_role_code=None,
                    before=before,
                    reason=None,
                )
            else:
                # Служебная правка: только record_version, согласования нетронуты.
                self._bump_record(joint)

        try:
            self._repo.save_joint(joint)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Стык с таким номером в этой ревизии документа уже существует"
            ) from exc
        return self._to_read(joint, data.updated_by)

    def _revalidate_line_for_current_revision(
        self, project_id: UUID, line_id: UUID, revision_id: UUID
    ) -> None:
        line = self._projects.get_line(line_id)
        if line is None or line.project_id != project_id:
            raise ValidationError(
                "line_id не найден или принадлежит другому проекту"
            )
        revision = self._repo.get_revision(revision_id)
        # Ревизия существует (стык уже ссылается на неё); проверяем линию документа.
        document = self._repo.get_document(revision.engineering_document_id)
        if document.line_id is not None and document.line_id != line_id:
            raise ValidationError(
                "Линия документа-основания не совпадает с линией стыка"
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Task 5B — жизненный цикл, согласования, блокировки, замена (ADR-011)
    # ══════════════════════════════════════════════════════════════════════════

    # --- версии (§15 ADR-011 / §9 задания) ---

    @staticmethod
    def _bump_record(joint: Joint) -> None:
        joint.record_version += 1

    @staticmethod
    def _bump_approval(joint: Joint) -> None:
        joint.record_version += 1
        joint.approval_version += 1

    @staticmethod
    def _bump_workflow(joint: Joint) -> None:
        joint.record_version += 1
        joint.workflow_version += 1

    @staticmethod
    def _reject_terminal(joint: Joint) -> None:
        if joint.status in jw.TERMINAL_STATUSES:
            raise DomainError(
                409,
                jw.TERMINAL_JOINT,
                f"Joint в терминальном статусе {joint.status}: изменения запрещены",
            )

    # --- scope и роли (§19 ADR-011 / §5 задания) ---

    def _joint_scope_ctx(self, joint: Joint) -> JointScopeContext:
        revision = self._repo.get_revision(joint.current_document_revision_id)
        engineering_document_id = (
            revision.engineering_document_id if revision is not None else None
        )
        company_ids = self._projects.active_company_ids(joint.project_id)
        return JointScopeContext(
            project_id=joint.project_id,
            line_id=joint.line_id,
            engineering_document_id=engineering_document_id,
            company_ids=frozenset(company_ids),
        )

    def _actor_role_codes(self, joint: Joint, worker_id: int) -> frozenset[str]:
        """Все role_code актора, покрывающие Joint по иерархии (для действий)."""
        ctx = self._joint_scope_ctx(joint)
        return frozenset(
            worker_role_codes_for_joint(self._db, worker_id, _LIFECYCLE_ROLES, ctx)
        )

    def _require_document_roles(
        self,
        *,
        document: EngineeringDocument,
        joint: Joint,
        worker_id: int,
        allowed: frozenset[str],
        action: str,
    ) -> None:
        """Проверяет активную роль актора в scope конкретного документа (Task 6, §7).

        Иерархия scope (GLOBAL/PROJECT/LINE/ENGINEERING_DOCUMENT/COMPANY) — как в
        §19 ADR-011, но привязка к переданному EngineeringDocument: при смене
        текущей ревизии права проверяются и на старый, и на новый документ.
        """
        ctx = JointScopeContext(
            project_id=document.project_id,
            line_id=document.line_id if document.line_id is not None else joint.line_id,
            engineering_document_id=document.id,
            company_ids=frozenset(self._projects.active_company_ids(joint.project_id)),
        )
        granted = worker_role_codes_for_joint(self._db, worker_id, allowed, ctx)
        if not granted:
            raise RoleDeniedError(
                jw.ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(allowed)} в scope документа {document.id}",
            )

    def _require_roles(
        self, joint: Joint, worker_id: int, allowed: frozenset[str], action: str
    ) -> str:
        """Проверяет активную роль актора в scope Joint; возвращает матч role_code.

        403 — роли нет или scope не покрывает Joint (§19 ADR-011)."""
        ctx = self._joint_scope_ctx(joint)
        granted = worker_role_codes_for_joint(self._db, worker_id, allowed, ctx)
        if not granted:
            raise RoleDeniedError(
                jw.ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(allowed)} в подходящем scope",
            )
        # Детерминированный выбор для аудита (приоритет по алфавиту).
        return sorted(granted)[0]

    # --- версии-guard'ы команд (§16 ADR-011) ---

    @staticmethod
    def _check_workflow_version(joint: Joint, expected: int | None) -> None:
        if expected is not None and expected != joint.workflow_version:
            raise VersionConflictError(
                jw.WORKFLOW_VERSION_CONFLICT,
                expected_version=expected,
                current_version=joint.workflow_version,
            )

    @staticmethod
    def _check_approval_version(joint: Joint, expected: int | None) -> None:
        if expected is not None and expected != joint.approval_version:
            raise VersionConflictError(
                jw.APPROVAL_VERSION_CONFLICT,
                expected_version=expected,
                current_version=joint.approval_version,
            )

    # --- история (§37 ADR-011) ---

    def _record_event(
        self,
        joint: Joint,
        event_type: str,
        *,
        actor_worker_id: int,
        actor_role_code: str | None,
        before: _StatusSnapshot,
        reason: str | None = None,
        decision_method: str | None = None,
    ) -> None:
        """Пишет неизменяемое событие истории (before → текущее состояние)."""
        self._repo.add_event(
            JointEvent(
                joint_id=joint.id,
                event_type=event_type,
                actor_worker_id=actor_worker_id,
                actor_role_code=actor_role_code,
                previous_status=before.status,
                new_status=joint.status,
                previous_pto_status=before.pto_status,
                new_pto_status=joint.pto_status,
                previous_ogs_status=before.ogs_status,
                new_ogs_status=joint.ogs_status,
                record_version=joint.record_version,
                approval_version=joint.approval_version,
                workflow_version=joint.workflow_version,
                decision_method=decision_method,
                reason=reason,
            )
        )

    # --- блокировки-хелперы ---

    def _has_activation_block(self, joint: Joint) -> bool:
        """Есть активная блокировка, запрещающая активацию (scope APPROVAL/ALL)."""
        return any(
            b.scope in jw.ACTIVATION_BLOCKING_SCOPES
            for b in self._repo.active_blocks(joint.id)
        )

    def _is_blocked(self, joint: Joint) -> bool:
        return bool(self._repo.active_blocks(joint.id))

    # --- автоматическая активация (§11 ADR-011) ---

    def _recompute_activation(
        self, joint: Joint, *, actor_worker_id: int, actor_role_code: str | None
    ) -> None:
        if joint.status != "PENDING_REVIEW":
            return
        if joint.pto_status != "APPROVED" or joint.ogs_status != "APPROVED":
            return
        # Оба решения должны относиться к текущей approval_version (§8 задания).
        if (
            joint.pto_approval_version != joint.approval_version
            or joint.ogs_approval_version != joint.approval_version
        ):
            return
        if self._has_activation_block(joint):
            return
        before = _snapshot(joint)
        joint.status = "ACTIVE"
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "ACTIVATED",
            actor_worker_id=actor_worker_id,
            actor_role_code=actor_role_code,
            before=before,
        )

    def _reset_affected_approvals(
        self, joint: Joint, sides: set[str], *, actor_worker_id: int
    ) -> None:
        """Выборочный сброс согласований (§9 задания, §6/§33/§35 ADR-011).

        Затронутая сторона → PENDING (REVALIDATION) с очисткой решения; незатронутая
        действующая (APPROVED) — перенос на новую approval_version (carry-forward).
        """
        for side in ("PTO", "OGS"):
            before = _snapshot(joint)
            if side in sides:
                if _side_status(joint, side) == "NOT_SUBMITTED":
                    continue
                _set_side(
                    joint,
                    side,
                    status="PENDING",
                    pending_reason="REVALIDATION",
                    decision_method=None,
                    approval_version=None,
                    decided_by=None,
                    decided_at=None,
                    comment=None,
                )
                self._record_event(
                    joint,
                    "APPROVAL_RESET",
                    actor_worker_id=actor_worker_id,
                    actor_role_code=None,
                    before=before,
                )
            elif _side_status(joint, side) == "APPROVED":
                # Незатронутое действующее согласование переносится на новую версию.
                _set_side_field(joint, side, "approval_version", joint.approval_version)
                self._record_event(
                    joint,
                    "APPROVAL_CARRIED_FORWARD",
                    actor_worker_id=actor_worker_id,
                    actor_role_code=None,
                    before=before,
                )

    # --- чтение с контекстом актора ---

    def read_joint(self, joint_id: UUID, actor_worker_id: int) -> JointRead:
        joint = self.get_joint(joint_id)
        return self._to_read(joint, actor_worker_id)

    def _to_read(self, joint: Joint, actor_worker_id: int) -> JointRead:
        roles = self._actor_role_codes(joint, actor_worker_id)
        is_blocked = self._is_blocked(joint)
        actions = jw.compute_available_actions(
            status=joint.status,
            pto_status=joint.pto_status,
            ogs_status=joint.ogs_status,
            has_active_block=is_blocked,
            actor_roles=roles,
        )
        return joint_to_read(joint, available_actions=actions, is_blocked=is_blocked)

    def list_blocks(self, joint_id: UUID) -> list[JointBlock]:
        self.get_joint(joint_id)
        return self._repo.list_blocks(joint_id)

    def list_events(self, joint_id: UUID) -> list[JointEvent]:
        self.get_joint(joint_id)
        return self._repo.list_events(joint_id)

    # --- команды: submit / approvals / reject / revoke ---

    def submit_for_review(
        self, joint_id: UUID, data: SubmitForReviewCommand, *, actor_worker_id: int
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(joint, actor_worker_id, jw.PTO_ROLES, "submit")
        self._check_workflow_version(joint, data.expected_workflow_version)
        before = _snapshot(joint)

        if joint.status == "DRAFT":
            for side in ("PTO", "OGS"):
                _set_side(
                    joint,
                    side,
                    status="PENDING",
                    pending_reason="INITIAL_REVIEW",
                    decision_method=None,
                    approval_version=None,
                    decided_by=None,
                    decided_at=None,
                    comment=None,
                )
            joint.status = "PENDING_REVIEW"
            joint.submitted_by = actor_worker_id
            joint.submitted_at = _now()
            self._bump_workflow(joint)
            self._record_event(
                joint,
                "SUBMITTED_FOR_REVIEW",
                actor_worker_id=actor_worker_id,
                actor_role_code=role,
                before=before,
            )
        elif joint.status == "PENDING_REVIEW":
            reopened = False
            for side in ("PTO", "OGS"):
                if _side_status(joint, side) in ("REJECTED", "REVOKED"):
                    _set_side(
                        joint,
                        side,
                        status="PENDING",
                        pending_reason="REVIEW_REOPENED",
                        decision_method=None,
                        approval_version=None,
                        decided_by=None,
                        decided_at=None,
                        comment=None,
                    )
                    reopened = True
            if not reopened:
                raise DomainError(
                    409,
                    jw.INVALID_TRANSITION,
                    "Joint уже на согласовании; повторная отправка возможна только "
                    "после отклонения или отзыва согласования",
                )
            joint.submitted_by = actor_worker_id
            joint.submitted_at = _now()
            self._bump_workflow(joint)
            self._record_event(
                joint,
                "REVIEW_REOPENED",
                actor_worker_id=actor_worker_id,
                actor_role_code=role,
                before=before,
            )
        else:
            raise DomainError(
                409,
                jw.INVALID_TRANSITION,
                f"Отправка на согласование недопустима из статуса {joint.status}",
            )
        return self._save_and_read(joint, actor_worker_id)

    def approve_pto(
        self, joint_id: UUID, data: ApprovePtoCommand, *, actor_worker_id: int
    ) -> JointRead:
        return self._approve_side(
            joint_id,
            side="PTO",
            allowed=jw.PTO_ROLES,
            method="MANUAL",
            comment=data.comment,
            expected_approval_version=data.expected_approval_version,
            expected_workflow_version=data.expected_workflow_version,
            actor_worker_id=actor_worker_id,
        )

    def approve_ogs(
        self, joint_id: UUID, data: ApproveOgsCommand, *, actor_worker_id: int
    ) -> JointRead:
        return self._approve_side(
            joint_id,
            side="OGS",
            allowed=jw.OGS_ROLES,
            method=data.method,
            comment=data.comment,
            expected_approval_version=data.expected_approval_version,
            expected_workflow_version=data.expected_workflow_version,
            actor_worker_id=actor_worker_id,
        )

    def _approve_side(
        self,
        joint_id: UUID,
        *,
        side: str,
        allowed: frozenset[str],
        method: str,
        comment: str | None,
        expected_approval_version: int | None,
        expected_workflow_version: int | None,
        actor_worker_id: int,
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(joint, actor_worker_id, allowed, f"approve_{side}")

        # OVERRIDE — только CHIEF_WELDER (§9 ADR-011).
        if method == "OVERRIDE":
            override_roles = self._actor_role_codes(joint, actor_worker_id)
            if not (override_roles & jw.OGS_OVERRIDE_ROLES):
                raise RoleDeniedError(
                    jw.ROLE_DENIED,
                    "OVERRIDE согласования доступен только роли CHIEF_WELDER",
                )
            role = "CHIEF_WELDER"

        if joint.status != "PENDING_REVIEW":
            raise DomainError(
                409,
                jw.INVALID_TRANSITION,
                f"Согласование недопустимо из статуса {joint.status}",
            )
        if _side_status(joint, side) != "PENDING":
            raise DomainError(
                409,
                jw.INVALID_APPROVAL_STATE,
                f"Согласование {side} возможно только из состояния PENDING "
                f"(текущее {_side_status(joint, side)}); прямое восстановление "
                "REVOKED/REJECTED запрещено — требуется повторная отправка",
            )
        self._check_approval_version(joint, expected_approval_version)
        self._check_workflow_version(joint, expected_workflow_version)

        before = _snapshot(joint)
        _set_side(
            joint,
            side,
            status="APPROVED",
            pending_reason=None,
            decision_method=method,
            approval_version=joint.approval_version,
            decided_by=actor_worker_id,
            decided_at=_now(),
            comment=comment,
        )
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "PTO_APPROVED" if side == "PTO" else "OGS_APPROVED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            decision_method=method,
        )
        self._recompute_activation(
            joint, actor_worker_id=actor_worker_id, actor_role_code=role
        )
        return self._save_and_read(joint, actor_worker_id)

    def reject_pto(
        self, joint_id: UUID, data: RejectCommand, *, actor_worker_id: int
    ) -> JointRead:
        return self._reject_side(
            joint_id, side="PTO", allowed=jw.PTO_ROLES, data=data,
            actor_worker_id=actor_worker_id,
        )

    def reject_ogs(
        self, joint_id: UUID, data: RejectCommand, *, actor_worker_id: int
    ) -> JointRead:
        return self._reject_side(
            joint_id, side="OGS", allowed=jw.OGS_ROLES, data=data,
            actor_worker_id=actor_worker_id,
        )

    def _reject_side(
        self,
        joint_id: UUID,
        *,
        side: str,
        allowed: frozenset[str],
        data: RejectCommand,
        actor_worker_id: int,
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(joint, actor_worker_id, allowed, f"reject_{side}")
        if joint.status != "PENDING_REVIEW":
            raise DomainError(
                409,
                jw.INVALID_TRANSITION,
                f"Отклонение недопустимо из статуса {joint.status}",
            )
        if _side_status(joint, side) != "PENDING":
            raise DomainError(
                409,
                jw.INVALID_APPROVAL_STATE,
                f"Отклонить можно только согласование в PENDING (текущее "
                f"{_side_status(joint, side)})",
            )
        self._check_workflow_version(joint, data.expected_workflow_version)

        before = _snapshot(joint)
        _set_side(
            joint,
            side,
            status="REJECTED",
            pending_reason=None,
            decision_method="MANUAL",
            approval_version=None,
            decided_by=actor_worker_id,
            decided_at=_now(),
            comment=data.reason,
        )
        # Joint остаётся в PENDING_REVIEW (§5 ADR-011).
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "PTO_REJECTED" if side == "PTO" else "OGS_REJECTED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            reason=data.reason,
            decision_method="MANUAL",
        )
        return self._save_and_read(joint, actor_worker_id)

    def revoke_pto(
        self, joint_id: UUID, data: RevokeCommand, *, actor_worker_id: int
    ) -> JointRead:
        return self._revoke_side(
            joint_id, side="PTO", allowed=jw.PTO_ROLES, data=data,
            actor_worker_id=actor_worker_id,
        )

    def revoke_ogs(
        self, joint_id: UUID, data: RevokeCommand, *, actor_worker_id: int
    ) -> JointRead:
        return self._revoke_side(
            joint_id, side="OGS", allowed=jw.OGS_ROLES, data=data,
            actor_worker_id=actor_worker_id,
        )

    def _revoke_side(
        self,
        joint_id: UUID,
        *,
        side: str,
        allowed: frozenset[str],
        data: RevokeCommand,
        actor_worker_id: int,
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(joint, actor_worker_id, allowed, f"revoke_{side}")
        if _side_status(joint, side) != "APPROVED":
            raise DomainError(
                409,
                jw.INVALID_APPROVAL_STATE,
                f"Отозвать можно только действующее APPROVED (текущее "
                f"{_side_status(joint, side)})",
            )
        self._check_workflow_version(joint, data.expected_workflow_version)

        before = _snapshot(joint)
        _set_side(
            joint,
            side,
            status="REVOKED",
            pending_reason=None,
            decision_method="MANUAL",
            approval_version=None,
            decided_by=actor_worker_id,
            decided_at=_now(),
            comment=data.reason,
        )
        # Если был ACTIVE — выводим из ACTIVE (§8 задания, Приложение A).
        if joint.status == "ACTIVE":
            joint.status = "PENDING_REVIEW"
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "PTO_REVOKED" if side == "PTO" else "OGS_REVOKED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            reason=data.reason,
            decision_method="MANUAL",
        )
        return self._save_and_read(joint, actor_worker_id)

    # --- команды: блокировки ---

    def block(
        self, joint_id: UUID, data: BlockCommand, *, actor_worker_id: int
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(
            joint, actor_worker_id, jw.PTO_ROLES | jw.OGS_ROLES, "block"
        )
        before = _snapshot(joint)
        self._repo.add_block(
            JointBlock(
                joint_id=joint.id,
                block_type=data.block_type,
                scope=data.scope,
                reason=data.reason,
                created_by=actor_worker_id,
            )
        )
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "BLOCKED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            reason=data.reason,
        )
        return self._save_and_read(joint, actor_worker_id)

    def unblock(
        self, joint_id: UUID, data: UnblockCommand, *, actor_worker_id: int
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(
            joint, actor_worker_id, jw.PTO_ROLES | jw.OGS_ROLES, "unblock"
        )
        block = self._repo.get_block(data.block_id)
        if block is None or block.joint_id != joint.id:
            raise NotFoundError("Блокировка", data.block_id)
        if block.released_at is not None:
            raise DomainError(
                409,
                jw.CANNOT_UNBLOCK,
                "Блокировка уже снята",
            )
        before = _snapshot(joint)
        block.released_by = actor_worker_id
        block.released_at = _now()
        block.release_reason = data.reason
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "UNBLOCKED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            reason=data.reason,
        )
        # Снятие блокировки может открыть путь к автоматической активации (§11).
        self._recompute_activation(
            joint, actor_worker_id=actor_worker_id, actor_role_code=role
        )
        return self._save_and_read(joint, actor_worker_id)

    # --- команды: отмена и замена ---

    def cancel(
        self, joint_id: UUID, data: CancelCommand, *, actor_worker_id: int
    ) -> JointRead:
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        role = self._require_roles(joint, actor_worker_id, jw.PTO_ROLES, "cancel")
        if joint.status not in ("DRAFT", "PENDING_REVIEW", "ACTIVE"):
            raise DomainError(
                409,
                jw.CANNOT_CANCEL,
                f"Отмена недопустима из статуса {joint.status}",
            )
        self._check_workflow_version(joint, data.expected_workflow_version)

        before = _snapshot(joint)
        joint.status = "CANCELLED"
        joint.cancelled_reason = data.reason
        joint.cancelled_by = actor_worker_id
        joint.cancelled_at = _now()
        self._bump_workflow(joint)
        self._record_event(
            joint,
            "CANCELLED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            reason=data.reason,
        )
        return self._save_and_read(joint, actor_worker_id)

    def supersede(
        self, joint_id: UUID, data: SupersedeCommand, *, actor_worker_id: int
    ) -> JointRead:
        """Атомарная замена: source → SUPERSEDED со ссылкой на successor (§26-27)."""
        source = self.get_joint(joint_id)
        self._reject_terminal(source)
        if source.status not in ("PENDING_REVIEW", "ACTIVE"):
            raise DomainError(
                409,
                jw.INVALID_TRANSITION,
                "Замена применима к Joint как минимум в PENDING_REVIEW "
                f"(текущий {source.status}); для DRAFT используйте cancel",
            )
        if source.id == data.successor_joint_id:
            raise DomainError(
                409, jw.CANNOT_SUPERSEDE, "Joint не может заменить сам себя"
            )
        successor = self._repo.get_joint(data.successor_joint_id)
        if successor is None:
            raise NotFoundError("Joint-преемник", data.successor_joint_id)

        # Права ПТО на оба Joint (§8 задания).
        role = self._require_roles(source, actor_worker_id, jw.PTO_ROLES, "supersede")
        self._require_roles(successor, actor_worker_id, jw.PTO_ROLES, "supersede")

        if successor.project_id != source.project_id:
            raise DomainError(
                409,
                jw.CANNOT_SUPERSEDE,
                "Преемник должен принадлежать тому же проекту",
            )
        if successor.status in jw.TERMINAL_STATUSES:
            raise DomainError(
                409,
                jw.CANNOT_SUPERSEDE,
                f"Недопустимый преемник в статусе {successor.status}",
            )
        if successor.status != "ACTIVE":
            raise DomainError(
                409,
                jw.CANNOT_SUPERSEDE,
                "Преемник должен пройти полный цикл ПТО/ОГС и быть ACTIVE",
            )

        # Проверка версий обоих Joint (§16 ADR-011).
        if (
            data.expected_source_version is not None
            and data.expected_source_version != source.record_version
        ):
            raise VersionConflictError(
                jw.SOURCE_JOINT_VERSION_CONFLICT,
                expected_version=data.expected_source_version,
                current_version=source.record_version,
            )
        if (
            data.expected_successor_version is not None
            and data.expected_successor_version != successor.record_version
        ):
            raise VersionConflictError(
                jw.SUCCESSOR_JOINT_VERSION_CONFLICT,
                expected_version=data.expected_successor_version,
                current_version=successor.record_version,
            )

        before = _snapshot(source)
        source.status = "SUPERSEDED"
        source.superseded_by_joint_id = successor.id
        source.superseded_by = actor_worker_id
        source.superseded_at = _now()
        # Закрываем активные блокировки исходного Joint (в т.ч. REPLACEMENT_PENDING).
        for active in self._repo.active_blocks(source.id):
            active.released_by = actor_worker_id
            active.released_at = _now()
            active.release_reason = "Замена Joint завершена (SUPERSEDED)"
        self._bump_workflow(source)
        self._record_event(
            source,
            "SUPERSEDED",
            actor_worker_id=actor_worker_id,
            actor_role_code=role,
            before=before,
            reason=data.reason,
        )
        return self._save_and_read(source, actor_worker_id)

    # --- сохранение команды (одна транзакция) ---

    def _save_and_read(self, joint: Joint, actor_worker_id: int) -> JointRead:
        try:
            self._repo.save_joint(joint)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при сохранении команды Joint"
            ) from exc
        return self._to_read(joint, actor_worker_id)

    # ══════════════════════════════════════════════════════════════════════════
    # Task 6 — история связей Joint ↔ DocumentRevision (IMPLEMENTATION_PLAN)
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _snapshot_values(joint: Joint) -> dict:
        """Снимок параметров Joint как словарь snapshot_field → значение (§ Task 6)."""
        return {
            snap_field: getattr(joint, joint_field)
            for snap_field, joint_field in SNAPSHOT_FIELD_MAP.items()
        }

    @staticmethod
    def _restore_from_snapshot(joint: Joint, link: JointDocumentRevision) -> None:
        """Восстанавливает поля Joint из снимка связи (обратное отображение)."""
        for snap_field, joint_field in SNAPSHOT_FIELD_MAP.items():
            setattr(joint, joint_field, getattr(link, snap_field))

    def _build_link(
        self,
        joint: Joint,
        *,
        document_revision_id: UUID,
        revision_role: str,
        document_role: str,
        created_by: int,
        link_status: str = "ACTIVE",
    ) -> JointDocumentRevision:
        return JointDocumentRevision(
            joint_id=joint.id,
            document_revision_id=document_revision_id,
            revision_role=revision_role,
            document_role=document_role,
            link_status=link_status,
            created_by=created_by,
            **self._snapshot_values(joint),
        )

    def _validate_revision_same_project(
        self, joint: Joint, revision_id: UUID
    ) -> DocumentRevision:
        revision = self._repo.get_revision(revision_id)
        if revision is None:
            raise NotFoundError("Ревизия документа", revision_id)
        document = self._repo.get_document(revision.engineering_document_id)
        if document is None or document.project_id != joint.project_id:
            raise ValidationError(
                "Ревизия принадлежит документу другого проекта"
            )
        return revision

    def list_revision_links(
        self,
        joint_id: UUID,
        *,
        link_status: str | None = None,
        document_role: str | None = None,
        revision_role: str | None = None,
    ) -> list[JointDocumentRevision]:
        self.get_joint(joint_id)
        return self._repo.list_links(
            joint_id,
            link_status=link_status,
            document_role=document_role,
            revision_role=revision_role,
        )

    def create_revision_link(
        self,
        joint_id: UUID,
        data: JointDocumentRevisionCreate,
        *,
        actor_worker_id: int,
    ) -> JointDocumentRevision:
        """Новая связь-снимок текущего состояния Joint (не меняет current, правило 4)."""
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        # Создавать связь могут ПТО и ОГС в допустимом scope (Task 6, §5 задания).
        self._require_roles(
            joint,
            actor_worker_id,
            jw.PTO_ROLES | jw.OGS_ROLES,
            "create_revision_link",
        )
        self._validate_revision_same_project(joint, data.document_revision_id)
        link = self._build_link(
            joint,
            document_revision_id=data.document_revision_id,
            revision_role=data.revision_role,
            document_role=data.document_role,
            created_by=actor_worker_id,
        )
        try:
            self._repo.add_link(link)
            return self._repo.save_link(link)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Активная связь с таким номером стыка в этой ревизии уже существует"
            ) from exc

    def invalidate_link(
        self,
        joint_id: UUID,
        link_id: UUID,
        data: InvalidateLinkCommand,
        *,
        actor_worker_id: int,
    ) -> JointDocumentRevision:
        """Аннулирование связи (правила 5-8). Снимок сохраняется в истории."""
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)
        self._require_roles(
            joint, actor_worker_id, jw.PTO_ROLES | jw.OGS_ROLES, "invalidate_link"
        )
        link = self._repo.get_link(link_id)
        if link is None or link.joint_id != joint.id:
            raise NotFoundError("Связь ревизии", link_id)
        if link.link_status == "INVALIDATED":
            # Повторное аннулирование — контролируемый 409 (§6 задания).
            raise DomainError(
                409, jw.LINK_NOT_ACTIVE, "Связь уже аннулирована"
            )
        # Текущую активную PRIMARY нельзя аннулировать до смены текущей ревизии
        # (§6 задания): активная PRIMARY по инварианту соответствует current.
        if link.document_role == "PRIMARY":
            raise DomainError(
                409,
                jw.CANNOT_INVALIDATE_PRIMARY,
                "Текущую PRIMARY-связь нельзя аннулировать до смены текущей ревизии",
            )
        # ORIGIN-связь в Task 6 не аннулируется даже после снятия PRIMARY: она
        # остаётся неизменным основанием истории Joint (§6 задания — безопасный
        # вариант: запрет).
        if link.revision_role == "ORIGIN":
            raise DomainError(
                409,
                jw.CANNOT_INVALIDATE_ORIGIN,
                "ORIGIN-связь нельзя аннулировать: она — неизменное основание истории",
            )
        now = _now()
        link.link_status = "INVALIDATED"
        link.invalidated_reason = data.reason
        link.invalidated_by = actor_worker_id
        link.invalidated_at = now
        # updated_* меняются только при аннулировании (§ Task 6).
        link.updated_by = actor_worker_id
        link.updated_at = now
        return self._repo.save_link(link)

    def set_current_revision(
        self,
        joint_id: UUID,
        data: SetCurrentRevisionCommand,
        *,
        actor_worker_id: int,
    ) -> JointRead:
        """Смена текущей ревизии Joint по выбранной ACTIVE-связи (правила 6,10-15).

        Восстанавливает поля Joint из снимка выбранной связи, назначает её PRIMARY,
        снимает прежнюю PRIMARY без изменения её снимка, проверяет права на старый и
        новый документы и выборочно сбрасывает затронутые согласования (Task 5B).
        """
        joint = self.get_joint(joint_id)
        self._reject_terminal(joint)

        link = self._repo.get_link(data.link_id)
        if link is None or link.joint_id != joint.id:
            raise NotFoundError("Связь ревизии", data.link_id)
        if link.link_status != "ACTIVE":
            raise DomainError(
                409,
                jw.LINK_NOT_ACTIVE,
                "Аннулированную связь нельзя сделать текущей PRIMARY",
            )

        # Права ПТО/ОГС на старый и новый документы по иерархии scope (§7 задания).
        allowed = jw.PTO_ROLES | jw.OGS_ROLES
        new_revision = self._validate_revision_same_project(
            joint, link.document_revision_id
        )
        new_document = self.get_document(new_revision.engineering_document_id)
        self._require_document_roles(
            document=new_document, joint=joint, worker_id=actor_worker_id,
            allowed=allowed, action="set_current_revision(new)",
        )
        old_revision = self._repo.get_revision(joint.current_document_revision_id)
        if old_revision is not None:
            old_document = self._repo.get_document(
                old_revision.engineering_document_id
            )
            if old_document is not None:
                self._require_document_roles(
                    document=old_document, joint=joint, worker_id=actor_worker_id,
                    allowed=allowed, action="set_current_revision(old)",
                )

        # Уже текущая PRIMARY — контролируемый 409 (§7 задания): команда не скрывает
        # ошибку клиента, повторный выбор текущей связи не проходит молча.
        if (
            link.document_role == "PRIMARY"
            and joint.current_document_revision_id == link.document_revision_id
        ):
            raise DomainError(
                409,
                jw.ALREADY_CURRENT_REVISION,
                "Связь уже является текущей PRIMARY-ревизией Joint",
            )

        # Три версии Task 5B (§7-8 задания): проверяем все переданные ожидаемые.
        if (
            data.expected_record_version is not None
            and data.expected_record_version != joint.record_version
        ):
            raise VersionConflictError(
                jw.RECORD_VERSION_CONFLICT,
                expected_version=data.expected_record_version,
                current_version=joint.record_version,
            )
        self._check_approval_version(joint, data.expected_approval_version)
        self._check_workflow_version(joint, data.expected_workflow_version)

        # Затронутые согласования — по фактически изменившимся значимым полям
        # (текущее значение Joint vs его снимок в выбранной связи).
        changed_fields = {
            field
            for field in _JOINT_ENGINEERING_FIELDS
            if getattr(joint, field) != getattr(link, f"snapshot_{field}")
        }
        significant = changed_fields & jw.SIGNIFICANT_FIELDS

        before = _snapshot(joint)

        # Снимаем прежнюю PRIMARY (без изменения её снимка), затем назначаем новую;
        # промежуточный flush исключает временное нарушение уникальности PRIMARY.
        prev_primary = self._repo.active_primary_link(joint.id)
        if prev_primary is not None and prev_primary.id != link.id:
            prev_primary.document_role = "ADDITIONAL"
            self._db.flush()
        link.document_role = "PRIMARY"

        # Смена текущей ревизии и восстановление полей Joint из снимка (§7 задания).
        joint.current_document_revision_id = link.document_revision_id
        self._restore_from_snapshot(joint, link)
        joint.updated_by = actor_worker_id

        # Версии и выборочный сброс согласований (§7 задания, §9/§15 Task 5B).
        # Смена PRIMARY — всегда workflow-переход: record и workflow растут всегда;
        # approval — только при значимом изменении инженерных данных.
        joint.record_version += 1
        joint.workflow_version += 1
        if significant:
            joint.approval_version += 1
            self._reset_affected_approvals(
                joint,
                jw.affected_sides(significant),
                actor_worker_id=actor_worker_id,
            )
            if joint.status == "ACTIVE":
                joint.status = "PENDING_REVIEW"

        self._record_event(
            joint,
            "CURRENT_REVISION_CHANGED",
            actor_worker_id=actor_worker_id,
            actor_role_code=None,
            before=before,
        )
        return self._save_and_read(joint, actor_worker_id)


# ══════════════════════════════════════════════════════════════════════════════
# Task 8A — WeldOperation Core (ADR-012 / Session 005)
# ══════════════════════════════════════════════════════════════════════════════
#
# Минимальное техническое ядро производственного факта сварки. Проверки допуска,
# WPS, review ОГС, подтверждения сварщика, корректировок и импорта НЕ входят
# (Tasks 8B–8E). Актор — только из X-User-Id (§15 задания). sequence_no выдаётся
# системой атомарно; клиент его не задаёт. Завершённая операция неизменяема.

# Поля производственного факта, применяемые из create/PATCH к модели (без служебных).
_WELD_OPERATION_FACT_FIELDS = (
    "weld_stage",
    "welding_method",
    "performed_on",
    "started_at",
    "finished_at",
    "actual_welder_id",
    "entered_stamp_code",
    "responsible_worker_id",
    "actual_wps_id",
    "welding_position",
    "shielding_gas",
    "back_purge",
    "production_area_id",
    "production_area_text",
    "shift_ref",
    "shift_assignment_ref",
    "production_report_ref",
    "operation_note",
)


class WeldOperationService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = EngineeringRepo(db)
        self._projects = ProjectRepo(db)
        self._hr = HrRepo(db)
        self._welding = WeldingRepo(db)

    # --- контекст scope и права (§10, §19 ADR-011) ---

    def _joint_scope_ctx(self, joint: Joint) -> JointScopeContext:
        revision = self._repo.get_revision(joint.current_document_revision_id)
        engineering_document_id = (
            revision.engineering_document_id if revision is not None else None
        )
        company_ids = self._projects.active_company_ids(joint.project_id)
        return JointScopeContext(
            project_id=joint.project_id,
            line_id=joint.line_id,
            engineering_document_id=engineering_document_id,
            company_ids=frozenset(company_ids),
        )

    def _require_actor(
        self, joint: Joint, worker_id: int, action: str
    ) -> None:
        """Актор должен иметь MASTER/FOREMAN (или админ CHIEF_WELDER) в scope Joint."""
        ctx = self._joint_scope_ctx(joint)
        granted = worker_role_codes_for_joint(
            self._db, worker_id, wow.WELD_OPERATION_ACTOR_ROLES, ctx
        )
        if not granted:
            raise RoleDeniedError(
                jw.ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется роль "
                "MASTER или FOREMAN в подходящем scope",
            )

    def _require_responsible(self, joint: Joint, responsible_worker_id: int) -> None:
        """Ответственный — активный MASTER/FOREMAN с доступом к проекту/линии (§10.2)."""
        ctx = self._joint_scope_ctx(joint)
        granted = worker_role_codes_for_joint(
            self._db,
            responsible_worker_id,
            wow.WELD_OPERATION_RESPONSIBLE_ROLES,
            ctx,
        )
        if not granted:
            raise RoleDeniedError(
                jw.ROLE_DENIED,
                "Ответственный должен иметь активную роль MASTER или FOREMAN в "
                "подходящем scope Joint",
            )

    def _resolve_welder(self, welder_id: UUID | None):
        """Профиль сварщика существует, если задан (§11.7). None → 404 не бросаем."""
        if welder_id is None:
            return None
        welder = self._welding.get_welder(welder_id)
        if welder is None:
            raise NotFoundError("Профиль сварщика", welder_id)
        return welder

    def _apply_welder_snapshot(self, op: WeldOperation, welder) -> None:
        """Снимок профильного клейма и организации сварщика (§12). Сравнение с
        введённым клеймом НЕ выполняется (Task 8C)."""
        if welder is None:
            op.profile_stamp_snapshot = None
            op.welder_company_id = None
            op.welder_department_id = None
            return
        op.profile_stamp_snapshot = welder.stamp_code
        worker = self._hr.get_worker(welder.worker_id)
        op.welder_company_id = worker.company_id if worker is not None else None
        op.welder_department_id = (
            worker.department_id if worker is not None else None
        )

    def _apply_executor_snapshot(
        self, op: WeldOperation, responsible_worker_id: int
    ) -> None:
        """Снимок организации-исполнителя по ответственному мастеру/прорабу (§12)."""
        worker = self._hr.get_worker(responsible_worker_id)
        op.executor_company_id = worker.company_id if worker is not None else None
        op.executor_department_id = (
            worker.department_id if worker is not None else None
        )

    # --- чтение ---

    def get_operation(self, operation_id: UUID) -> WeldOperation:
        op = self._repo.get_operation(operation_id)
        if op is None:
            raise NotFoundError("Сварочная операция", operation_id)
        return op

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._repo.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def list_operations(
        self, filters: WeldOperationListFilters
    ) -> WeldOperationListResponse:
        total = self._repo.count_operations(filters)
        items = self._repo.list_operations(filters)
        return WeldOperationListResponse(
            items=[WeldOperationRead.model_validate(op) for op in items],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def list_operations_for_joint(
        self, joint_id: UUID, filters: WeldOperationListFilters
    ) -> WeldOperationListResponse:
        self._require_joint(joint_id)
        filters.joint_id = joint_id
        return self.list_operations(filters)

    # --- создание черновика (§11, §13.1) ---

    def create_operation(
        self, data: WeldOperationCreate, *, actor_worker_id: int
    ) -> WeldOperation:
        joint = self._require_joint(data.joint_id)
        # Joint не в терминальном состоянии — новые производственные события
        # запрещены для CANCELLED/SUPERSEDED (Session 004 раздел 2; §11.2-11.4).
        if joint.status in jw.TERMINAL_STATUSES:
            raise DomainError(
                409,
                wow.JOINT_NOT_PRODUCIBLE,
                f"Joint в статусе {joint.status}: фиксация производственного факта "
                "запрещена",
            )
        self._require_actor(joint, actor_worker_id, "create")
        self._require_responsible(joint, data.responsible_worker_id)
        welder = self._resolve_welder(data.actual_welder_id)

        # Номер выдаётся ПОСЛЕ всех проверок (неуспех не занимает номер). Блокировка
        # строки Joint исключает гонку; UNIQUE(joint_id, sequence_no) — backstop.
        sequence_no = self._repo.next_weld_operation_sequence(joint.id)
        fact = data.model_dump(include=set(_WELD_OPERATION_FACT_FIELDS))
        op = WeldOperation(
            joint_id=joint.id,
            sequence_no=sequence_no,
            lifecycle_status="DRAFT",
            created_by=actor_worker_id,
            updated_by=actor_worker_id,
            record_version=1,
            **fact,
        )
        self._apply_welder_snapshot(op, welder)
        self._apply_executor_snapshot(op, data.responsible_worker_id)
        try:
            self._repo.add_operation(op)
            return self._repo.save_operation(op)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при создании сварочной операции"
            ) from exc

    # --- неизменяемость / статусные guard'ы ---

    def _reject_non_draft(self, op: WeldOperation) -> None:
        """PATCH разрешён только для DRAFT (§13.2, §13.4)."""
        if op.lifecycle_status == "COMPLETED":
            raise DomainError(
                409, wow.WELD_OPERATION_COMPLETED, wow.COMPLETED_IMMUTABLE_MESSAGE
            )
        if op.lifecycle_status == "CANCELLED":
            raise DomainError(
                409,
                wow.WELD_OPERATION_CANCELLED,
                "Отменённая операция неизменяема",
            )

    @staticmethod
    def _check_version(op: WeldOperation, expected: int | None) -> None:
        if expected is not None and expected != op.record_version:
            raise VersionConflictError(
                jw.RECORD_VERSION_CONFLICT,
                expected_version=expected,
                current_version=op.record_version,
            )

    # --- редактирование черновика (§13.2) ---

    def update_operation(
        self, operation_id: UUID, data: WeldOperationUpdate, *, actor_worker_id: int
    ) -> WeldOperation:
        op = self.get_operation(operation_id)
        joint = self._require_joint(op.joint_id)
        self._require_actor(joint, actor_worker_id, "update")
        self._reject_non_draft(op)
        self._check_version(op, data.expected_record_version)

        changes = data.model_dump(
            exclude_unset=True, exclude={"expected_record_version"}
        )

        # --- валидация ДО мутации ---
        welder_sentinel = object()
        new_welder = welder_sentinel
        if "actual_welder_id" in changes:
            new_welder = self._resolve_welder(changes["actual_welder_id"])
        if "responsible_worker_id" in changes:
            self._require_responsible(joint, changes["responsible_worker_id"])
        eff_start = changes.get("started_at", op.started_at)
        eff_finish = changes.get("finished_at", op.finished_at)
        if (
            eff_start is not None
            and eff_finish is not None
            and eff_finish < eff_start
        ):
            raise ValidationError(
                "finished_at не может быть раньше started_at"
            )

        # --- мутация ---
        for field, value in changes.items():
            setattr(op, field, value)
        if new_welder is not welder_sentinel:
            self._apply_welder_snapshot(op, new_welder)
        if "responsible_worker_id" in changes:
            self._apply_executor_snapshot(op, changes["responsible_worker_id"])
        op.updated_by = actor_worker_id
        op.record_version += 1
        try:
            return self._repo.save_operation(op)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при изменении сварочной операции"
            ) from exc

    # --- завершение (§13.3) ---

    def complete_operation(
        self,
        operation_id: UUID,
        data: WeldOperationCompleteRequest,
        *,
        actor_worker_id: int,
    ) -> WeldOperation:
        op = self.get_operation(operation_id)
        joint = self._require_joint(op.joint_id)
        self._require_actor(joint, actor_worker_id, "complete")
        if op.lifecycle_status == "COMPLETED":
            raise DomainError(
                409, wow.WELD_OPERATION_COMPLETED, "Операция уже завершена"
            )
        if op.lifecycle_status == "CANCELLED":
            raise DomainError(
                409,
                wow.WELD_OPERATION_CANCELLED,
                "Отменённую операцию нельзя завершить",
            )
        self._check_version(op, data.expected_record_version)

        # Минимальные структурные условия завершения (§13.3). Task 8A НЕ блокирует
        # завершение из-за допуска/WPS/клейма/подтверждения/ОГС.
        missing = [
            name
            for name in ("actual_welder_id", "responsible_worker_id",
                         "weld_stage", "welding_method", "performed_on")
            if getattr(op, name) is None
        ]
        if missing:
            raise DomainError(
                422,
                wow.WELD_OPERATION_INCOMPLETE,
                "Для завершения обязательны заполненные поля: "
                + ", ".join(missing),
            )

        op.lifecycle_status = "COMPLETED"
        op.completed_by = actor_worker_id
        op.completed_at = _now()
        op.updated_by = actor_worker_id
        op.record_version += 1
        try:
            return self._repo.save_operation(op)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при завершении сварочной операции"
            ) from exc

    # --- отмена черновика (§13.5) ---

    def cancel_operation(
        self,
        operation_id: UUID,
        data: WeldOperationCancelRequest,
        *,
        actor_worker_id: int,
    ) -> WeldOperation:
        op = self.get_operation(operation_id)
        joint = self._require_joint(op.joint_id)
        self._require_actor(joint, actor_worker_id, "cancel")
        if op.lifecycle_status == "COMPLETED":
            # COMPLETED → CANCELLED — Task 8D (отмена ложной завершённой записи).
            raise DomainError(
                409,
                wow.WELD_OPERATION_COMPLETED,
                "Завершённую операцию нельзя отменить: отмена ложного факта — "
                "механизм корректировок (Task 8D)",
            )
        if op.lifecycle_status == "CANCELLED":
            raise DomainError(
                409, wow.WELD_OPERATION_CANCELLED, "Операция уже отменена"
            )
        self._check_version(op, data.expected_record_version)

        op.lifecycle_status = "CANCELLED"
        op.cancelled_by = actor_worker_id
        op.cancelled_at = _now()
        op.cancellation_reason = data.reason
        op.updated_by = actor_worker_id
        op.record_version += 1
        try:
            return self._repo.save_operation(op)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при отмене сварочной операции"
            ) from exc
