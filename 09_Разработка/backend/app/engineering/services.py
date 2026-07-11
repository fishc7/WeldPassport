from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering import joint_workflow as jw
from app.engineering.models import (
    REQUIRED_WELDING_FIELDS,
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointBlock,
    JointEvent,
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
    JointCreate,
    JointListFilters,
    JointListResponse,
    JointRead,
    JointUpdate,
    RejectCommand,
    RevokeCommand,
    SubmitForReviewCommand,
    SupersedeCommand,
    UnblockCommand,
)
from app.projects.repository import ProjectRepo
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
        return revision

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
        sequence = self._repo.next_system_sequence(project.id)
        system_code = f"{project.code}-JNT-{sequence:04d}"

        engineering_values = data.model_dump(include=set(_JOINT_ENGINEERING_FIELDS))
        joint = Joint(
            project_id=data.project_id,
            line_id=data.line_id,
            origin_document_revision_id=data.document_revision_id,
            current_document_revision_id=data.document_revision_id,
            system_code=system_code,
            joint_no=data.joint_no,
            joint_no_normalized=normalized,
            status="DRAFT",
            # Три версии стартуют с 1; согласования — NOT_SUBMITTED (server_default).
            record_version=1,
            approval_version=1,
            workflow_version=1,
            created_by=data.created_by,
            updated_by=data.created_by,
            **engineering_values,
        )
        try:
            return self._repo.create_joint(joint)
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
