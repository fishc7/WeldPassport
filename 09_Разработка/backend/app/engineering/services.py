from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import (
    REQUIRED_WELDING_FIELDS,
    DocumentRevision,
    EngineeringDocument,
    Joint,
)
from app.engineering.repository import EngineeringRepo
from app.engineering.schemas import (
    DocumentRevisionCreate,
    EngineeringDocumentCreate,
    EngineeringDocumentListFilters,
    JointCreate,
    JointListFilters,
    JointListResponse,
    JointRead,
    JointUpdate,
)
from app.projects.repository import ProjectRepo
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.permissions import RoleRequirement, check_worker_role

# Владелец инженерных документов и ревизий — ПТО (IP-07). Технический role_code
# существующего backend.
ENGINEERING_OWNER_ROLE = "PTO_ENGINEER"

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


def joint_to_read(joint: Joint) -> JointRead:
    """Собирает ответ с вычисляемыми полями (не колонки БД)."""
    missing = missing_welding_requirements(joint)
    columns = {c.name: getattr(joint, c.name) for c in Joint.__table__.columns}
    return JointRead(
        **columns,
        ready_for_welding=not missing,
        missing_welding_requirements=missing,
        production_state="NOT_STARTED",
    )


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
            version=1,
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
        return JointListResponse(
            items=[joint_to_read(joint) for joint in items],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def update_joint(self, joint_id: UUID, data: JointUpdate) -> Joint:
        joint = self.get_joint(joint_id)

        # В Task 5A редактируется только DRAFT (иные статусы вводятся в 5B).
        if joint.status != "DRAFT":
            raise ConflictError(
                f"Редактирование стыка недопустимо из статуса {joint.status}"
            )
        # Optimistic locking: устаревшая версия → конфликт без перезаписи.
        if joint.version != data.expected_version:
            raise ConflictError(
                "Версия стыка устарела: ожидалась "
                f"{data.expected_version}, актуальная {joint.version}"
            )

        changes = data.model_dump(
            exclude_unset=True, exclude={"expected_version", "updated_by"}
        )

        # --- вся валидация ДО мутации объекта (иначе dirty-состояние сессии при
        #     ошибке) ---

        # Смена линии: повторная проверка согласованности с текущей ревизией.
        if "line_id" in changes and changes["line_id"] != joint.line_id:
            self._revalidate_line_for_current_revision(
                joint.project_id, changes["line_id"], joint.current_document_revision_id
            )

        # Итоговая консистентность координат: считаем эффективные значения из
        # изменений и уже сохранённых, не трогая объект.
        eff_x = changes.get("position_x", joint.position_x)
        eff_y = changes.get("position_y", joint.position_y)
        eff_cs = changes.get("coordinate_system", joint.coordinate_system)
        if (eff_x is not None or eff_y is not None) and eff_cs is None:
            raise ValidationError(
                "coordinate_system обязателен при заданных position_x/position_y"
            )

        # Смена номера: пересчёт нормализованной формы и проверка дубля.
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

        # --- мутация ---
        if normalized is not None:
            joint.joint_no_normalized = normalized
        for field, value in changes.items():
            setattr(joint, field, value)

        joint.updated_by = data.updated_by
        joint.version += 1
        try:
            return self._repo.save_joint(joint)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Стык с таким номером в этой ревизии документа уже существует"
            ) from exc

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
