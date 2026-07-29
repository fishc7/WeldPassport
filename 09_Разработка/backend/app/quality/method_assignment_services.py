from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.projects.repository import ProjectRepo
from app.quality import inspection_workflow as iw
from app.quality import method_assignment_workflow as maw
from app.quality.models import Inspection, InspectionMethodAssignment
from app.quality.repository import QualityRepo
from app.quality.schemas import (
    CancelMethodAssignmentCommand,
    MethodAssignmentCreate,
    MethodAssignmentListResponse,
    MethodAssignmentRead,
    MethodAssignmentUpdate,
    ReplaceMethodAssignmentCommand,
)
from app.shared.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    RoleDeniedError,
    VersionConflictError,
)
from app.shared.permissions import JointScopeContext, worker_role_codes_for_joint


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MethodAssignmentService:
    """Назначение методов контроля и лаборатории (Task 9B, ADR-015 / Session 007).

    Использует scope/permissions-фреймворк Task 9A: видимость назначения выводится
    из видимости Inspection (через Joint), изменяющие действия требуют ролей
    организации контроля (§15) и, как в Task 9A, исключают COMPANY-scope.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = QualityRepo(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── контекст объектов ─────────────────────────────────────────────────────

    def _require_inspection(self, inspection_id: UUID) -> Inspection:
        inspection = self._repo.get_inspection(inspection_id)
        if inspection is None:
            raise DomainError(
                404, iw.INSPECTION_NOT_FOUND, "Заявка на контроль не найдена"
            )
        return inspection

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def _require_assignment(
        self, assignment_id: UUID
    ) -> InspectionMethodAssignment:
        assignment = self._repo.get_assignment(assignment_id)
        if assignment is None:
            raise DomainError(
                404, maw.ASSIGNMENT_NOT_FOUND, "Назначение метода не найдено"
            )
        return assignment

    # ── scope и права (переиспользуем permissions framework Task 9A) ───────────

    def _joint_scope_ctx(
        self, joint: Joint, *, include_company: bool = True
    ) -> JointScopeContext:
        revision = self._eng.get_revision(joint.current_document_revision_id)
        engineering_document_id = (
            revision.engineering_document_id if revision is not None else None
        )
        company_ids = (
            self._projects.active_company_ids(joint.project_id)
            if include_company
            else set()
        )
        return JointScopeContext(
            project_id=joint.project_id,
            line_id=joint.line_id,
            engineering_document_id=engineering_document_id,
            company_ids=frozenset(company_ids),
        )

    def _granted_roles(
        self,
        joint: Joint,
        worker_id: int,
        allowed: frozenset[str],
        *,
        include_company: bool = True,
    ) -> set[str]:
        ctx = self._joint_scope_ctx(joint, include_company=include_company)
        return set(worker_role_codes_for_joint(self._db, worker_id, allowed, ctx))

    def _require_visible(
        self, joint: Joint, worker_id: int, not_found_code: str
    ) -> None:
        """Скрытый по scope ресурс → 404 (как в Task 9A), а не 403."""
        if not self._granted_roles(joint, worker_id, maw.ASSIGNMENT_READ_ROLES):
            raise DomainError(404, not_found_code, "Ресурс не найден")

    def _require_write(self, joint: Joint, worker_id: int, action: str) -> None:
        # Изменяющие действия: COMPANY-scope исключён (как lifecycle Task 9A §15.2).
        granted = self._granted_roles(
            joint, worker_id, maw.ASSIGNMENT_WRITE_ROLES, include_company=False
        )
        if not granted:
            raise RoleDeniedError(
                maw.ASSIGNMENT_ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(maw.ASSIGNMENT_WRITE_ROLES)} в подходящем scope",
            )

    @staticmethod
    def _check_version(
        assignment: InspectionMethodAssignment, expected: int
    ) -> None:
        if expected != assignment.version:
            raise VersionConflictError(
                maw.ASSIGNMENT_VERSION_CONFLICT,
                expected_version=expected,
                current_version=assignment.version,
            )

    def _validate_laboratory(self, project_id: UUID, company_id: int) -> None:
        """Компания допустима как лаборатория проекта (§7.3)."""
        company = self._projects.get_company(company_id)
        if company is None:
            raise DomainError(
                404,
                maw.ASSIGNMENT_LABORATORY_NOT_FOUND,
                "Организация-лаборатория не найдена",
            )
        if company.status != "active":
            raise DomainError(
                409,
                maw.ASSIGNMENT_LABORATORY_INACTIVE,
                "Организация-лаборатория неактивна",
            )
        link = self._projects.get_active_project_company(
            project_id=project_id,
            company_id=company_id,
            role_code=maw.NDT_LAB_ROLE_CODE,
        )
        if link is None:
            raise DomainError(
                422,
                maw.ASSIGNMENT_COMPANY_NOT_PROJECT_LABORATORY,
                "Организация не является действующей лабораторией НК данного проекта",
            )

    @staticmethod
    def _require_assignable(inspection: Inspection) -> None:
        """Inspection допускает назначение метода: не отменена и не терминальна (§10)."""
        if inspection.status in iw.INSPECTION_TERMINAL_STATUSES:
            raise DomainError(
                409,
                maw.ASSIGNMENT_INSPECTION_NOT_ASSIGNABLE,
                f"Заявка в статусе {inspection.status} не допускает назначение метода",
            )

    # ── чтение / представление ────────────────────────────────────────────────

    def _to_read(
        self,
        assignment: InspectionMethodAssignment,
        company_name: str | None,
    ) -> MethodAssignmentRead:
        read = MethodAssignmentRead.model_validate(assignment)
        read.laboratory_company_name = company_name
        read.is_active = assignment.status == maw.ASSIGNMENT_ASSIGNED
        return read

    def _read_one(
        self, assignment: InspectionMethodAssignment
    ) -> MethodAssignmentRead:
        names = self._repo.company_names([assignment.laboratory_company_id])
        return self._to_read(
            assignment, names.get(assignment.laboratory_company_id)
        )

    def get_assignment(
        self, assignment_id: UUID, *, actor_worker_id: int
    ) -> MethodAssignmentRead:
        assignment = self._require_assignment(assignment_id)
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id, maw.ASSIGNMENT_NOT_FOUND)
        return self._read_one(assignment)

    def list_assignments(
        self,
        inspection_id: UUID,
        *,
        actor_worker_id: int,
        status: str | None = None,
        active_only: bool = False,
    ) -> MethodAssignmentListResponse:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id, iw.INSPECTION_NOT_FOUND)

        items = self._repo.list_assignments(
            inspection_id, status=status, active_only=active_only
        )
        active = self._repo.active_assignments(inspection_id)
        names = self._repo.company_names(
            [a.laboratory_company_id for a in items]
        )
        # Сводка (§14) — всегда по активным назначениям, независимо от фильтра.
        assigned_method_codes = sorted({a.method_code for a in active})
        all_have_lab = all(a.laboratory_company_id is not None for a in active)
        return MethodAssignmentListResponse(
            inspection_id=inspection_id,
            items=[
                self._to_read(a, names.get(a.laboratory_company_id)) for a in items
            ],
            has_method_assignments=bool(active),
            active_method_assignment_count=len(active),
            assigned_method_codes=assigned_method_codes,
            all_assignments_have_laboratory=all_have_lab,
            ready_for_execution=bool(active) and all_have_lab,
        )

    # ── создание (§10) ────────────────────────────────────────────────────────

    def create_assignment(
        self,
        inspection_id: UUID,
        data: MethodAssignmentCreate,
        *,
        actor_worker_id: int,
    ) -> MethodAssignmentRead:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id, iw.INSPECTION_NOT_FOUND)
        self._require_write(joint, actor_worker_id, "create-method-assignment")
        self._require_assignable(inspection)

        # Метод — из закрытого набора (схема-enum уже отсекает неверные значения).
        if not maw.is_valid_method(data.method_code):
            raise DomainError(
                422, maw.ASSIGNMENT_INVALID_METHOD, "Недопустимый метод контроля"
            )
        self._validate_laboratory(inspection.project_id, data.laboratory_company_id)

        # Предварительная проверка дубля (§9); БД-индекс — окончательный барьер (§20).
        if self._repo.find_active_assignment_by_method(
            inspection_id, data.method_code
        ):
            raise DomainError(
                409,
                maw.ASSIGNMENT_DUPLICATE_ACTIVE_METHOD,
                f"Для метода {data.method_code} уже есть активное назначение",
            )

        now = _now()
        assignment = InspectionMethodAssignment(
            inspection_id=inspection_id,
            method_code=data.method_code,
            laboratory_company_id=data.laboratory_company_id,
            status=maw.ASSIGNMENT_ASSIGNED,
            laboratory_note=data.laboratory_note,
            assignment_note=data.assignment_note,
            assigned_by_worker_id=actor_worker_id,
            assigned_at=now,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        try:
            self._repo.add_assignment(assignment)
            self._repo.save_assignment(assignment)
        except IntegrityError as exc:
            self._db.rollback()
            raise self._duplicate_or_conflict(exc) from exc
        return self._read_one(assignment)

    # ── ограниченное обновление примечаний (§11) ──────────────────────────────

    def update_assignment(
        self,
        assignment_id: UUID,
        data: MethodAssignmentUpdate,
        *,
        actor_worker_id: int,
    ) -> MethodAssignmentRead:
        assignment = self._require_assignment(assignment_id)
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id, maw.ASSIGNMENT_NOT_FOUND)
        self._require_write(joint, actor_worker_id, "update-method-assignment")
        if assignment.status != maw.ASSIGNMENT_ASSIGNED:
            raise DomainError(
                409,
                maw.ASSIGNMENT_NOT_ACTIVE,
                f"Изменение недоступно в статусе {assignment.status} "
                "(PATCH только для ASSIGNED)",
            )
        self._check_version(assignment, data.expected_version)

        changes = data.model_dump(
            exclude_unset=True, exclude={"expected_version"}
        )
        if "laboratory_note" in changes:
            assignment.laboratory_note = changes["laboratory_note"]
        if "assignment_note" in changes:
            assignment.assignment_note = changes["assignment_note"]

        assignment.updated_by_worker_id = actor_worker_id
        assignment.version += 1
        self._repo.save_assignment(assignment)
        return self._read_one(assignment)

    # ── отмена (§12) ──────────────────────────────────────────────────────────

    def cancel_assignment(
        self,
        assignment_id: UUID,
        data: CancelMethodAssignmentCommand,
        *,
        actor_worker_id: int,
    ) -> MethodAssignmentRead:
        assignment = self._require_assignment(assignment_id)
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id, maw.ASSIGNMENT_NOT_FOUND)
        self._require_write(joint, actor_worker_id, "cancel-method-assignment")
        self._reject_terminal(assignment)
        self._check_version(assignment, data.expected_version)

        assignment.status = maw.ASSIGNMENT_CANCELLED
        assignment.cancelled_at = _now()
        assignment.cancelled_by_worker_id = actor_worker_id
        assignment.cancellation_reason = data.reason.strip()
        assignment.updated_by_worker_id = actor_worker_id
        assignment.version += 1
        self._repo.save_assignment(assignment)
        return self._read_one(assignment)

    # ── замена (§13) ──────────────────────────────────────────────────────────

    def replace_assignment(
        self,
        assignment_id: UUID,
        data: ReplaceMethodAssignmentCommand,
        *,
        actor_worker_id: int,
    ) -> MethodAssignmentRead:
        old = self._require_assignment(assignment_id)
        inspection = self._require_inspection(old.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id, maw.ASSIGNMENT_NOT_FOUND)
        self._require_write(joint, actor_worker_id, "replace-method-assignment")
        self._reject_terminal(old)
        self._require_assignable(inspection)
        self._check_version(old, data.expected_version)

        new_method = data.method_code or old.method_code
        new_lab = (
            data.laboratory_company_id
            if data.laboratory_company_id is not None
            else old.laboratory_company_id
        )
        # Замена без фактического изменения метода/лаборатории запрещена (§13.8).
        if new_method == old.method_code and new_lab == old.laboratory_company_id:
            raise DomainError(
                409,
                maw.ASSIGNMENT_NO_CHANGE,
                "Замена не содержит изменений метода или лаборатории",
            )

        # Все проверки метода и лаборатории повторяются (§13.6) ДО любых мутаций,
        # поэтому при ошибке старое назначение не изменяется (§13.7).
        if not maw.is_valid_method(new_method):
            raise DomainError(
                422, maw.ASSIGNMENT_INVALID_METHOD, "Недопустимый метод контроля"
            )
        self._validate_laboratory(inspection.project_id, new_lab)
        if new_method != old.method_code and self._repo.find_active_assignment_by_method(
            old.inspection_id, new_method
        ):
            raise DomainError(
                409,
                maw.ASSIGNMENT_DUPLICATE_ACTIVE_METHOD,
                f"Для метода {new_method} уже есть активное назначение",
            )

        # Атомарно: старое → REPLACED (сначала flush, чтобы освободить partial
        # unique index при том же методе), затем создаётся новое ASSIGNED, старому
        # проставляется ссылка на новое. Всё в одной транзакции (§13.2).
        now = _now()
        new_note_lab = (
            data.laboratory_note
            if "laboratory_note" in data.model_fields_set
            else old.laboratory_note
        )
        new_note_assignment = (
            data.assignment_note
            if "assignment_note" in data.model_fields_set
            else old.assignment_note
        )
        try:
            old.status = maw.ASSIGNMENT_REPLACED
            old.updated_by_worker_id = actor_worker_id
            old.version += 1
            self._db.flush()

            new_assignment = InspectionMethodAssignment(
                inspection_id=old.inspection_id,
                method_code=new_method,
                laboratory_company_id=new_lab,
                status=maw.ASSIGNMENT_ASSIGNED,
                laboratory_note=new_note_lab,
                assignment_note=new_note_assignment,
                assigned_by_worker_id=actor_worker_id,
                assigned_at=now,
                created_by_worker_id=actor_worker_id,
                updated_by_worker_id=actor_worker_id,
                version=1,
            )
            self._repo.add_assignment(new_assignment)
            old.replaced_by_assignment_id = new_assignment.id
            self._repo.save_assignment(new_assignment)
        except IntegrityError as exc:
            self._db.rollback()
            raise self._duplicate_or_conflict(exc) from exc
        return self._read_one(new_assignment)

    # ── вспомогательное ───────────────────────────────────────────────────────

    @staticmethod
    def _reject_terminal(assignment: InspectionMethodAssignment) -> None:
        if assignment.status == maw.ASSIGNMENT_CANCELLED:
            raise DomainError(
                409, maw.ASSIGNMENT_ALREADY_CANCELLED, "Назначение уже отменено"
            )
        if assignment.status == maw.ASSIGNMENT_REPLACED:
            raise DomainError(
                409, maw.ASSIGNMENT_ALREADY_REPLACED, "Назначение уже заменено"
            )

    @staticmethod
    def _duplicate_or_conflict(exc: IntegrityError) -> DomainError:
        """Нарушение partial unique index → доменный конфликт дубля (§20)."""
        text = str(getattr(exc, "orig", exc))
        if "uq_quality_ima_active_method" in text:
            return DomainError(
                409,
                maw.ASSIGNMENT_DUPLICATE_ACTIVE_METHOD,
                "Для метода уже есть активное назначение",
            )
        return ConflictError("Нарушение целостности при назначении метода контроля")
