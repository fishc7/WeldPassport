"""Сервисное ядро выполнения метода контроля (Task 9C, блок 9C-3).

Создание выполнения, жизненный цикл до LAB_CONFIRMED, участники, локальные
результаты, стандарты, расчёты (оценка/полнота) и доменный аудит. Переиспользует
RBAC/scope и validation-паттерны Tasks 9A/9B (JointScopeContext, worker_role_codes_
for_joint, DomainError, optimistic locking). Схемы и API — вне блока (входные данные
передаются service-DTO-датаклассами, не Pydantic).

Поддержанный сценарий подтверждения — EXTERNAL_DOCUMENT_REGISTRATION (внутренний
пользователь ОТК/ОГС/главный сварщик регистрирует внешний лабораторный документ,
§7/§22). Прямой ввод лабораторией (DIRECT_LAB_CONFIRMATION) до полноценной внешней
auth-модели не расширяется. LaboratoryConclusion и редакции выполнения — следующие
блоки.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.projects.repository import ProjectRepo
from app.quality import inspection_workflow as iw
from app.quality import laboratory_conclusion_workflow as lcw
from app.quality import method_execution_workflow as mew
from app.quality.execution_models import (
    MethodExecution,
    MethodExecutionParticipant,
    MethodExecutionResultItem,
    MethodExecutionStandard,
    QualityAuditEvent,
)
from app.quality.execution_repository import ExecutionRepo
from app.quality.method_assignment_workflow import (
    ASSIGNMENT_ASSIGNED,
    NDT_LAB_ROLE_CODE,
)
from app.quality.models import Inspection, InspectionMethodAssignment
from app.quality.repository import QualityRepo
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


# ── Входные DTO (не Pydantic; заполняются вызывающим/тестами/будущим API) ───────


@dataclass
class ExecutionCreateInput:
    laboratory_company_id: int | None = None
    time_precision: str | None = None
    performed_date: date | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    source_type: str | None = None
    source_reference: str | None = None
    procedure_document_id: UUID | None = None
    procedure_reference_snapshot: str | None = None
    procedure_revision_snapshot: str | None = None
    declared_belt_length: Decimal | None = None
    belt_length_unit: str | None = None


@dataclass
class MarkPerformedInput:
    expected_version: int
    time_precision: str = mew.TIME_DATE_ONLY
    performed_date: date | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class ConfirmInput:
    expected_version: int
    confirmation_mode: str = mew.CONFIRM_EXTERNAL_DOCUMENT
    laboratory_evaluation: str | None = None
    evaluation_override_reason: str | None = None
    declared_completion: str | None = None
    completion_override_reason: str | None = None
    external_lab_approver_person_id: UUID | None = None
    external_lab_approval_date: date | None = None
    source_type: str | None = None
    source_reference: str | None = None


@dataclass
class CancelExecutionInput:
    expected_version: int
    cancellation_type: str
    cancellation_reason: str


@dataclass
class ParticipantInput:
    person_id: UUID
    participant_role: str
    engagement_type: str | None = None
    engagement_basis: str | None = None
    participant_organization_id: int | None = None
    person_certification_id: UUID | None = None
    person_name_snapshot: str | None = None
    organization_name_snapshot: str | None = None
    qualification_level_snapshot: str | None = None
    certificate_number_snapshot: str | None = None
    certificate_valid_from_snapshot: date | None = None
    certificate_valid_until_snapshot: date | None = None
    certification_scope_snapshot: str | None = None


@dataclass
class ResultItemInput:
    controlled_object_type: str = mew.OBJ_WHOLE_JOINT
    object_reference: str | None = None
    description: str | None = None
    coordinate_system: str | None = None
    coordinate_from: Decimal | None = None
    coordinate_to: Decimal | None = None
    coordinate_unit: str | None = None
    wraps_zero: bool = False
    controlled_volume_value: Decimal | None = None
    controlled_volume_unit: str | None = None
    coverage_percent: Decimal | None = None
    quantity: Decimal | None = None
    indication_description: str | None = None
    indication_coordinate_from: Decimal | None = None
    indication_coordinate_to: Decimal | None = None
    indication_coordinate_unit: str | None = None
    evaluation: str = mew.EVAL_NOT_EVALUATED
    required_action: str | None = None
    laboratory_result_text: str | None = None
    note: str | None = None
    source_page_reference: str | None = None
    source_row_reference: str | None = None
    source_note: str | None = None


@dataclass
class StandardInput:
    standard_document_id: UUID | None = None
    standard_code_snapshot: str | None = None
    standard_title_snapshot: str | None = None
    revision_snapshot: str | None = None


@dataclass
class _Ctx:
    """Свёртка контекста выполнения: назначение, заявка, стык."""

    execution: MethodExecution
    assignment: InspectionMethodAssignment
    inspection: Inspection
    joint: Joint


# ── Доменный аудит (§23) ───────────────────────────────────────────────────────


class QualityAuditService:
    """Пишет неизменяемые события доменного журнала контроля (§23).

    Событие добавляется в текущую транзакцию (flush, без commit) — коммитит его
    вызывающая команда вместе с основным изменением.
    """

    def __init__(self, repo: ExecutionRepo) -> None:
        self._repo = repo

    def record(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        event_type: str,
        actor_worker_id: int,
        reason: str | None = None,
        changed_fields: dict | None = None,
        previous_values: dict | None = None,
        new_values: dict | None = None,
    ) -> QualityAuditEvent:
        event = QualityAuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_worker_id=actor_worker_id,
            reason=reason,
            changed_fields=changed_fields,
            previous_values=previous_values,
            new_values=new_values,
        )
        return self._repo.add_audit_event(event)


# ── Расчёты выполнения (§11–§13) ───────────────────────────────────────────────


class MethodExecutionCalculationService:
    """Расчёт агрегированной оценки и полноты покрытия выполнения (§11–§13).

    Читает действующие локальные результаты (COMPLETE, не EXCLUDED) и вычисляет
    `calculated_evaluation` (приоритет худшего) и `calculated_completion` (по
    геометрии участков). Не редактируется вручную (§11).
    """

    def __init__(self, repo: ExecutionRepo) -> None:
        self._repo = repo

    def recompute(self, execution: MethodExecution) -> None:
        items = self._repo.effective_result_items(execution.id)
        if not items:
            execution.calculated_evaluation = mew.EVAL_NOT_EVALUATED
            execution.calculated_completion = mew.COMPLETION_NOT_CALCULABLE
            return
        execution.calculated_evaluation = mew.aggregate_evaluation(
            [item.evaluation for item in items]
        )
        execution.calculated_completion = self._completion(execution, items)

    @staticmethod
    def _completion(
        execution: MethodExecution,
        items: list[MethodExecutionResultItem],
    ) -> str:
        # Результат на всё соединение (ВИК) → полное покрытие (§10.1/§12).
        if any(
            item.controlled_object_type == mew.OBJ_WHOLE_JOINT for item in items
        ):
            return mew.COMPLETION_COMPLETE
        belt = execution.declared_belt_length or execution.calculated_belt_length
        if belt is None:
            return mew.COMPLETION_NOT_CALCULABLE
        segments: list[mew.CoverageSegment] = []
        closed = False
        for item in items:
            if item.coordinate_from is None or item.coordinate_to is None:
                return mew.COMPLETION_NOT_CALCULABLE
            segments.append(
                mew.CoverageSegment(
                    start=item.coordinate_from,
                    end=item.coordinate_to,
                    wraps_zero=item.wraps_zero,
                )
            )
            if item.coordinate_system in mew.CLOSED_COORDINATE_SYSTEMS:
                closed = True
        return mew.analyze_coverage(segments, belt, closed=closed)


# ── Основной сервис выполнения ─────────────────────────────────────────────────


class MethodExecutionService:
    """Выполнение метода контроля: создание, lifecycle, участники, стандарты.

    Видимость и права выводятся из Joint (как Task 9B): изменяющие действия требуют
    ролей организации контроля (§22) и исключают COMPANY-scope. Регистрация внешнего
    документа — роли EXTERNAL_REGISTRATION_ROLES (§22, решение 9C-29).
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ExecutionRepo(db)
        self._quality = QualityRepo(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)
        self._audit = QualityAuditService(self._repo)
        self._calc = MethodExecutionCalculationService(self._repo)

    # ── контекст ──────────────────────────────────────────────────────────────

    def _require_assignment(
        self, assignment_id: UUID
    ) -> InspectionMethodAssignment:
        from app.quality import method_assignment_workflow as maw

        assignment = self._quality.get_assignment(assignment_id)
        if assignment is None:
            raise DomainError(
                404, maw.ASSIGNMENT_NOT_FOUND, "Назначение метода не найдено"
            )
        return assignment

    def _require_execution(self, execution_id: UUID) -> MethodExecution:
        execution = self._repo.get_execution(execution_id)
        if execution is None:
            raise DomainError(
                404, mew.EXECUTION_NOT_FOUND, "Выполнение метода не найдено"
            )
        return execution

    def _require_inspection(self, inspection_id: UUID) -> Inspection:
        inspection = self._quality.get_inspection(inspection_id)
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

    def _ctx_for_execution(self, execution: MethodExecution) -> _Ctx:
        assignment = self._require_assignment(
            execution.inspection_method_assignment_id
        )
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        return _Ctx(execution, assignment, inspection, joint)

    # ── scope / права (переиспользуем framework Task 9A/9B) ────────────────────

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

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        if not self._granted_roles(joint, worker_id, mew.EXECUTION_READ_ROLES):
            raise DomainError(404, mew.EXECUTION_NOT_FOUND, "Ресурс не найден")

    def _require_roles(
        self, joint: Joint, worker_id: int, roles: frozenset[str], action: str
    ) -> None:
        granted = self._granted_roles(
            joint, worker_id, roles, include_company=False
        )
        if not granted:
            raise RoleDeniedError(
                mew.EXECUTION_ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(roles)} в подходящем scope",
            )

    def _require_write(self, joint: Joint, worker_id: int, action: str) -> None:
        self._require_roles(joint, worker_id, mew.EXECUTION_WRITE_ROLES, action)

    @staticmethod
    def _check_version(execution: MethodExecution, expected: int) -> None:
        if expected != execution.version:
            raise VersionConflictError(
                mew.EXECUTION_VERSION_CONFLICT,
                expected_version=expected,
                current_version=execution.version,
            )

    @staticmethod
    def _require_editable(execution: MethodExecution) -> None:
        if execution.status == mew.EXEC_LAB_CONFIRMED:
            raise DomainError(
                409,
                mew.EXECUTION_ALREADY_CONFIRMED,
                "Подтверждённое выполнение изменяется только новой редакцией",
            )
        if execution.status in mew.EXECUTION_TERMINAL_STATUSES:
            raise DomainError(
                409,
                mew.EXECUTION_ALREADY_TERMINAL,
                f"Выполнение в статусе {execution.status} не редактируется",
            )

    def _validate_laboratory(self, project_id: UUID, company_id: int) -> None:
        company = self._projects.get_company(company_id)
        if company is None:
            raise DomainError(
                404,
                mew.EXECUTION_LABORATORY_NOT_FOUND,
                "Организация-лаборатория не найдена",
            )
        link = self._projects.get_active_project_company(
            project_id=project_id,
            company_id=company_id,
            role_code=NDT_LAB_ROLE_CODE,
        )
        if link is None:
            raise DomainError(
                422,
                mew.EXECUTION_LABORATORY_NOT_NDT_LAB,
                "Организация не является действующей лабораторией НК проекта",
            )

    # ── чтение ────────────────────────────────────────────────────────────────

    def get_execution(
        self, execution_id: UUID, *, actor_worker_id: int
    ) -> MethodExecution:
        execution = self._require_execution(execution_id)
        ctx = self._ctx_for_execution(execution)
        self._require_visible(ctx.joint, actor_worker_id)
        return execution

    def list_executions(
        self, assignment_id: UUID, *, actor_worker_id: int
    ) -> list[MethodExecution]:
        assignment = self._require_assignment(assignment_id)
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_executions_for_assignment(assignment_id)

    def compute_assignment_state(
        self, assignment_id: UUID, *, actor_worker_id: int
    ) -> str:
        assignment = self._require_assignment(assignment_id)
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        executions = self._repo.current_executions_for_assignment(assignment_id)
        outcomes = [
            mew.ExecutionOutcome(
                status=execution.status,
                evaluation=(
                    execution.laboratory_evaluation
                    or execution.calculated_evaluation
                    or mew.EVAL_NOT_EVALUATED
                ),
                coverage_complete=self._is_coverage_complete(execution),
            )
            for execution in executions
        ]
        return mew.assignment_state(outcomes)

    @staticmethod
    def _is_coverage_complete(execution: MethodExecution) -> bool:
        return mew.COMPLETION_COMPLETE in (
            execution.declared_completion,
            execution.calculated_completion,
        )

    # ── создание (§5, §25) ────────────────────────────────────────────────────

    def create_execution(
        self,
        assignment_id: UUID,
        data: ExecutionCreateInput,
        *,
        actor_worker_id: int,
    ) -> MethodExecution:
        assignment = self._require_assignment(assignment_id)
        inspection = self._require_inspection(assignment.inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_write(joint, actor_worker_id, "create-method-execution")

        if assignment.status != ASSIGNMENT_ASSIGNED:
            raise DomainError(
                409,
                mew.EXECUTION_ASSIGNMENT_NOT_ASSIGNABLE,
                f"Назначение в статусе {assignment.status} не допускает выполнение",
            )

        laboratory_company_id = (
            data.laboratory_company_id
            if data.laboratory_company_id is not None
            else assignment.laboratory_company_id
        )
        self._validate_laboratory(inspection.project_id, laboratory_company_id)

        if data.time_precision is not None:
            self._validate_time(
                data.time_precision,
                data.performed_date,
                data.started_at,
                data.finished_at,
            )

        execution_id = uuid4()
        execution = MethodExecution(
            id=execution_id,
            inspection_method_assignment_id=assignment.id,
            joint_id=inspection.joint_id,  # инвариант §5.3 (не выбирается клиентом)
            project_id=inspection.project_id,
            laboratory_company_id=laboratory_company_id,
            root_execution_id=execution_id,
            revision_no=1,
            is_current=True,
            status=mew.EXEC_DRAFT,
            time_precision=data.time_precision,
            performed_date=data.performed_date,
            started_at=data.started_at,
            finished_at=data.finished_at,
            source_type=data.source_type,
            source_reference=data.source_reference,
            procedure_document_id=data.procedure_document_id,
            procedure_reference_snapshot=data.procedure_reference_snapshot,
            procedure_revision_snapshot=data.procedure_revision_snapshot,
            declared_belt_length=data.declared_belt_length,
            belt_length_unit=data.belt_length_unit,
            calculated_evaluation=mew.EVAL_NOT_EVALUATED,
            calculated_completion=mew.COMPLETION_NOT_CALCULABLE,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        self._repo.add_execution(execution)
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_EXECUTION_CREATED,
            actor_worker_id=actor_worker_id,
        )
        return self._repo.save_execution(execution)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(
        self, execution_id: UUID, expected_version: int, *, actor_worker_id: int
    ) -> MethodExecution:
        execution = self._load_for_write(
            execution_id, actor_worker_id, "start-method-execution"
        )
        self._require_transition(execution, mew.EXEC_IN_PROGRESS)
        self._check_version(execution, expected_version)
        self._set_status(execution, mew.EXEC_IN_PROGRESS, actor_worker_id)
        return self._commit(execution)

    def mark_performed(
        self,
        execution_id: UUID,
        data: MarkPerformedInput,
        *,
        actor_worker_id: int,
    ) -> MethodExecution:
        execution = self._load_for_write(
            execution_id, actor_worker_id, "mark-performed"
        )
        self._require_transition(execution, mew.EXEC_PERFORMED)
        self._check_version(execution, data.expected_version)
        self._validate_time(
            data.time_precision,
            data.performed_date,
            data.started_at,
            data.finished_at,
        )
        execution.time_precision = data.time_precision
        execution.performed_date = data.performed_date
        execution.started_at = data.started_at
        execution.finished_at = data.finished_at
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_TIME_CHANGED,
            actor_worker_id=actor_worker_id,
        )
        self._set_status(execution, mew.EXEC_PERFORMED, actor_worker_id)
        return self._commit(execution)

    def record_result(
        self, execution_id: UUID, expected_version: int, *, actor_worker_id: int
    ) -> MethodExecution:
        execution = self._load_for_write(
            execution_id, actor_worker_id, "record-result"
        )
        self._require_transition(execution, mew.EXEC_RESULT_RECORDED)
        self._check_version(execution, expected_version)

        effective = self._repo.effective_result_items(execution.id)
        if not effective:
            raise DomainError(
                409,
                mew.EXECUTION_NO_RESULT_ITEMS,
                "Нет действующих локальных результатов",
            )
        if any(
            item.record_state == mew.RESULT_DRAFT
            for item in self._repo.list_result_items(execution.id)
        ):
            raise DomainError(
                409,
                mew.EXECUTION_INCOMPLETE_RESULT_ITEMS,
                "Есть незавершённые локальные результаты (record_state=DRAFT)",
            )
        if self._repo.count_lead_inspectors(execution.id) != 1:
            raise DomainError(
                409,
                mew.EXECUTION_NO_LEAD_INSPECTOR,
                "Требуется ровно один LEAD_INSPECTOR",
            )

        self._calc.recompute(execution)
        self._set_status(execution, mew.EXEC_RESULT_RECORDED, actor_worker_id)
        return self._commit(execution)

    def confirm(
        self, execution_id: UUID, data: ConfirmInput, *, actor_worker_id: int
    ) -> MethodExecution:
        execution = self._require_execution(execution_id)
        ctx = self._ctx_for_execution(execution)
        self._require_visible(ctx.joint, actor_worker_id)
        self._require_transition(execution, mew.EXEC_LAB_CONFIRMED)
        self._check_version(execution, data.expected_version)

        if data.confirmation_mode == mew.CONFIRM_DIRECT_LAB:
            raise DomainError(
                422,
                mew.EXECUTION_DIRECT_CONFIRMATION_UNSUPPORTED,
                "Прямое подтверждение лабораторией недоступно в текущем блоке; "
                "используйте EXTERNAL_DOCUMENT_REGISTRATION",
            )
        if data.confirmation_mode != mew.CONFIRM_EXTERNAL_DOCUMENT:
            raise DomainError(
                422,
                mew.EXECUTION_CONFIRMATION_MODE_REQUIRED,
                "Недопустимый режим подтверждения",
            )

        # Регистрация внешнего документа: роли ОТК/ОГС/главный сварщик (§22).
        self._require_roles(
            ctx.joint,
            actor_worker_id,
            mew.EXTERNAL_REGISTRATION_ROLES,
            "register-external-document",
        )

        self._calc.recompute(execution)
        lab_eval = data.laboratory_evaluation or execution.calculated_evaluation
        if (
            lab_eval != execution.calculated_evaluation
            and not (data.evaluation_override_reason or "").strip()
        ):
            raise DomainError(
                422,
                mew.EXECUTION_EVALUATION_OVERRIDE_REASON_REQUIRED,
                "Расхождение расчётной и лабораторной оценки требует обоснования",
            )
        if (
            data.declared_completion is not None
            and data.declared_completion != execution.calculated_completion
            and not (data.completion_override_reason or "").strip()
        ):
            raise DomainError(
                422,
                mew.EXECUTION_COMPLETION_OVERRIDE_REASON_REQUIRED,
                "Расхождение полноты требует обоснования",
            )

        if data.external_lab_approver_person_id is not None:
            self._require_external_person(data.external_lab_approver_person_id)

        execution.confirmation_mode = mew.CONFIRM_EXTERNAL_DOCUMENT
        execution.laboratory_evaluation = lab_eval
        execution.evaluation_override_reason = data.evaluation_override_reason
        execution.declared_completion = data.declared_completion
        execution.completion_override_reason = data.completion_override_reason
        execution.external_lab_approver_person_id = (
            data.external_lab_approver_person_id
        )
        execution.external_lab_approval_date = data.external_lab_approval_date
        execution.registered_by_worker_id = actor_worker_id
        execution.registered_at = _now()
        execution.lab_confirmed_by_user_id = actor_worker_id
        execution.lab_confirmed_at = _now()
        if data.source_type is not None:
            execution.source_type = data.source_type
        if data.source_reference is not None:
            execution.source_reference = data.source_reference

        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_RESULT_CONFIRMED,
            actor_worker_id=actor_worker_id,
            reason=data.evaluation_override_reason,
            changed_fields={
                "confirmation_mode": True,
                "lab_confirmed_by_user_id": True,
                "lab_confirmed_at": True,
                "registered_by_worker_id": True,
                "registered_at": True,
            },
            new_values={
                "confirmation_mode": execution.confirmation_mode,
                "lab_confirmed_by_user_id": execution.lab_confirmed_by_user_id,
                "status": mew.EXEC_LAB_CONFIRMED,
            },
        )
        # Редакция (§18): нетекущая редакция при подтверждении атомарно становится
        # текущей, а прежняя текущая — SUPERSEDED. Прежняя до этого мига не менялась.
        if not execution.is_current:
            self._promote_revision(execution, actor_worker_id)
        self._set_status(execution, mew.EXEC_LAB_CONFIRMED, actor_worker_id)
        try:
            return self._commit(execution)
        except IntegrityError as exc:
            self._db.rollback()
            raise DomainError(
                409,
                mew.EXECUTION_REVISION_CONFLICT,
                "Конкурентное подтверждение редакции: перечитайте и повторите",
            ) from exc

    def _promote_revision(
        self, execution: MethodExecution, actor_worker_id: int
    ) -> None:
        """Атомарно делает редакцию текущей, замещая прежнюю (§18).

        Блокировка прежней текущей строки (FOR UPDATE) сериализует конкурентные
        подтверждения; partial unique index `WHERE is_current` — окончательный
        барьер. Прежняя сбрасывает is_current (flush освобождает индекс) и, если
        была подтверждена, переходит в SUPERSEDED.
        """
        sibling = self._repo.get_current_execution_for_root(
            execution.root_execution_id, exclude_id=execution.id, for_update=True
        )
        if sibling is not None:
            previous_status = sibling.status
            sibling.is_current = False
            if sibling.status == mew.EXEC_LAB_CONFIRMED:
                sibling.status = mew.EXEC_SUPERSEDED
            sibling.updated_by_worker_id = actor_worker_id
            self._db.flush()  # освободить partial unique (is_current) до новой текущей
            self._audit.record(
                entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
                entity_id=sibling.id,
                event_type=mew.AUDIT_EVENT_STATUS_CHANGED,
                actor_worker_id=actor_worker_id,
                previous_values={"status": previous_status, "is_current": True},
                new_values={"status": sibling.status, "is_current": False},
            )
            # §9 блока 9C-5: замещённое выполнение помечает связанные ISSUED-
            # заключения к пересмотру (в той же транзакции продвижения).
            if sibling.status == mew.EXEC_SUPERSEDED:
                self._flag_conclusions_for_review(sibling.id, actor_worker_id)
        execution.is_current = True

    def _flag_conclusions_for_review(
        self, superseded_execution_id: UUID, actor_worker_id: int
    ) -> None:
        affected = self._repo.mark_conclusions_for_execution_review(
            superseded_execution_id,
            lcw.REVIEW_REASON_LINKED_EXECUTION_SUPERSEDED,
        )
        for conclusion in affected:
            self._audit.record(
                entity_type=mew.AUDIT_ENTITY_CONCLUSION,
                entity_id=conclusion.id,
                event_type=mew.AUDIT_EVENT_CONCLUSION_REVIEW_REQUIRED,
                actor_worker_id=actor_worker_id,
                reason=lcw.REVIEW_REASON_LINKED_EXECUTION_SUPERSEDED,
                new_values={
                    "revision_review_required": True,
                    "superseded_execution_id": str(superseded_execution_id),
                },
            )

    def cancel(
        self, execution_id: UUID, data: CancelExecutionInput, *, actor_worker_id: int
    ) -> MethodExecution:
        execution = self._load_for_write(
            execution_id, actor_worker_id, "cancel-method-execution"
        )
        if execution.status not in mew.EXECUTION_CANCELLABLE_STATUSES:
            raise DomainError(
                409,
                mew.EXECUTION_INVALID_TRANSITION,
                f"Отмена недоступна в статусе {execution.status}",
            )
        self._check_version(execution, data.expected_version)
        if data.cancellation_type not in mew.CANCELLATION_TYPES:
            raise DomainError(
                422, mew.EXECUTION_INVALID_TRANSITION, "Недопустимый тип отмены"
            )
        if not (data.cancellation_reason or "").strip():
            raise DomainError(
                422,
                mew.EXECUTION_CANCELLATION_REASON_REQUIRED,
                "Причина отмены обязательна",
            )
        execution.cancellation_type = data.cancellation_type
        execution.cancellation_reason = data.cancellation_reason.strip()
        execution.cancelled_by_worker_id = actor_worker_id
        execution.cancelled_at = _now()
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_EXECUTION_CANCELLED,
            actor_worker_id=actor_worker_id,
            reason=execution.cancellation_reason,
        )
        self._set_status(execution, mew.EXEC_CANCELLED, actor_worker_id)
        return self._commit(execution)

    # ── участники (§9) ────────────────────────────────────────────────────────

    def add_participant(
        self, execution_id: UUID, data: ParticipantInput, *, actor_worker_id: int
    ) -> MethodExecutionParticipant:
        execution = self._load_for_write(
            execution_id, actor_worker_id, "add-participant"
        )
        self._require_editable(execution)
        if data.participant_role not in mew.PARTICIPANT_ROLES:
            raise DomainError(
                422, mew.EXECUTION_ROLE_DENIED, "Недопустимая роль участника"
            )
        if data.engagement_type is not None and (
            data.engagement_type not in mew.ENGAGEMENT_TYPES
        ):
            raise DomainError(
                422, mew.EXECUTION_ROLE_DENIED, "Недопустимая форма привлечения"
            )
        person = self._require_external_person(data.person_id)

        participant = MethodExecutionParticipant(
            method_execution_id=execution.id,
            person_id=person.id,
            participant_organization_id=data.participant_organization_id,
            engagement_type=data.engagement_type,
            engagement_basis=data.engagement_basis,
            participant_role=data.participant_role,
            person_certification_id=data.person_certification_id,
            person_name_snapshot=(
                data.person_name_snapshot or person.full_name
            ),
            organization_name_snapshot=data.organization_name_snapshot,
            qualification_level_snapshot=data.qualification_level_snapshot,
            certificate_number_snapshot=data.certificate_number_snapshot,
            certificate_valid_from_snapshot=data.certificate_valid_from_snapshot,
            certificate_valid_until_snapshot=data.certificate_valid_until_snapshot,
            certification_scope_snapshot=data.certification_scope_snapshot,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
        )
        try:
            self._repo.add_participant(participant)
            self._db.flush()
        except IntegrityError as exc:
            self._db.rollback()
            raise self._participant_conflict(exc) from exc
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_PARTICIPANTS_CHANGED,
            actor_worker_id=actor_worker_id,
        )
        self._db.commit()
        self._db.refresh(participant)
        return participant

    def delete_participant(
        self, participant_id: UUID, *, actor_worker_id: int
    ) -> None:
        participant = self._repo.get_participant(participant_id)
        if participant is None:
            raise DomainError(
                404, mew.PARTICIPANT_NOT_FOUND, "Участник не найден"
            )
        execution = self._require_execution(participant.method_execution_id)
        ctx = self._ctx_for_execution(execution)
        self._require_visible(ctx.joint, actor_worker_id)
        self._require_write(ctx.joint, actor_worker_id, "delete-participant")
        # Физическое удаление — только в незавершённом черновике (§25).
        if execution.status != mew.EXEC_DRAFT:
            raise DomainError(
                409,
                mew.PARTICIPANT_DELETE_NOT_DRAFT,
                "Физическое удаление участника допустимо только в DRAFT",
            )
        self._repo.delete_participant(participant)
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_PARTICIPANTS_CHANGED,
            actor_worker_id=actor_worker_id,
        )
        self._db.commit()

    # ── стандарты (§14.2) ─────────────────────────────────────────────────────

    def add_standard(
        self, execution_id: UUID, data: StandardInput, *, actor_worker_id: int
    ) -> MethodExecutionStandard:
        execution = self._load_for_write(
            execution_id, actor_worker_id, "add-standard"
        )
        self._require_editable(execution)
        standard = MethodExecutionStandard(
            method_execution_id=execution.id,
            standard_document_id=data.standard_document_id,
            standard_code_snapshot=data.standard_code_snapshot,
            standard_title_snapshot=data.standard_title_snapshot,
            revision_snapshot=data.revision_snapshot,
            created_by_worker_id=actor_worker_id,
        )
        self._repo.add_standard(standard)
        self._db.commit()
        self._db.refresh(standard)
        return standard

    # ── внешние лица ──────────────────────────────────────────────────────────

    def _require_external_person(self, person_id: UUID):
        person = self._repo.get_external_person(person_id)
        if person is None:
            raise DomainError(
                404, mew.EXTERNAL_PERSON_NOT_FOUND, "Внешнее лицо не найдено"
            )
        return person

    # ── общие внутренние ──────────────────────────────────────────────────────

    def _load_for_write(
        self, execution_id: UUID, actor_worker_id: int, action: str
    ) -> MethodExecution:
        execution = self._require_execution(execution_id)
        ctx = self._ctx_for_execution(execution)
        self._require_visible(ctx.joint, actor_worker_id)
        self._require_write(ctx.joint, actor_worker_id, action)
        return execution

    @staticmethod
    def _require_transition(execution: MethodExecution, target: str) -> None:
        if not mew.can_transition_execution(execution.status, target):
            raise DomainError(
                409,
                mew.EXECUTION_INVALID_TRANSITION,
                f"Недопустимый переход {execution.status} → {target}",
            )

    def _set_status(
        self, execution: MethodExecution, target: str, actor_worker_id: int
    ) -> None:
        previous = execution.status
        execution.status = target
        execution.updated_by_worker_id = actor_worker_id
        execution.version += 1
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=execution.id,
            event_type=mew.AUDIT_EVENT_STATUS_CHANGED,
            actor_worker_id=actor_worker_id,
            previous_values={"status": previous},
            new_values={"status": target},
        )

    def _commit(self, execution: MethodExecution) -> MethodExecution:
        return self._repo.save_execution(execution)

    @staticmethod
    def _validate_time(
        precision: str,
        performed_date: date | None,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> None:
        if precision not in mew.TIME_PRECISIONS:
            raise DomainError(
                422,
                mew.EXECUTION_PERFORMED_DATE_REQUIRED,
                "Недопустимая точность времени",
            )
        code = mew.check_time_consistency(
            precision,
            performed_date=performed_date,
            started_at=started_at,
            finished_at=finished_at,
        )
        if code is not None:
            message = (
                "Окончание раньше начала"
                if code == mew.EXECUTION_TIME_FINISH_BEFORE_START
                else "Недостаточно данных о времени выполнения"
            )
            raise DomainError(422, code, message)

    @staticmethod
    def _participant_conflict(exc: IntegrityError) -> DomainError:
        text = str(getattr(exc, "orig", exc))
        if "uq_quality_mexec_part_lead" in text:
            return DomainError(
                409,
                mew.EXECUTION_MULTIPLE_LEAD_INSPECTORS,
                "У выполнения уже есть ведущий контролёр (LEAD_INSPECTOR)",
            )
        return ConflictError("Нарушение целостности при добавлении участника")


# ── Сервис локальных результатов (§10) ─────────────────────────────────────────


class MethodExecutionResultService:
    """Локальные результаты выполнения: создание, завершение, исключение (§10).

    Мутации доступны, пока выполнение редактируемо (до LAB_CONFIRMED). После
    завершения/исключения пересчитывает агрегированную оценку и полноту выполнения.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ExecutionRepo(db)
        self._exec = MethodExecutionService(db)
        self._audit = QualityAuditService(self._repo)
        self._calc = MethodExecutionCalculationService(self._repo)

    def _load(self, execution_id: UUID, actor_worker_id: int, action: str):
        execution = self._exec._load_for_write(  # noqa: SLF001 (внутренний повтор)
            execution_id, actor_worker_id, action
        )
        self._exec._require_editable(execution)  # noqa: SLF001
        return execution

    def add_result_item(
        self, execution_id: UUID, data: ResultItemInput, *, actor_worker_id: int
    ) -> MethodExecutionResultItem:
        execution = self._load(execution_id, actor_worker_id, "add-result-item")
        self._validate_result(data)

        item_id = uuid4()
        item = MethodExecutionResultItem(
            id=item_id,
            method_execution_id=execution.id,
            root_result_item_id=item_id,
            revision_no=1,
            record_state=mew.RESULT_DRAFT,
            controlled_object_type=data.controlled_object_type,
            object_reference=data.object_reference,
            description=data.description,
            coordinate_system=data.coordinate_system,
            coordinate_from=data.coordinate_from,
            coordinate_to=data.coordinate_to,
            coordinate_unit=data.coordinate_unit,
            wraps_zero=data.wraps_zero,
            controlled_volume_value=data.controlled_volume_value,
            controlled_volume_unit=data.controlled_volume_unit,
            coverage_percent=data.coverage_percent,
            quantity=data.quantity,
            indication_description=data.indication_description,
            indication_coordinate_from=data.indication_coordinate_from,
            indication_coordinate_to=data.indication_coordinate_to,
            indication_coordinate_unit=data.indication_coordinate_unit,
            evaluation=data.evaluation,
            required_action=data.required_action,
            laboratory_result_text=data.laboratory_result_text,
            note=data.note,
            source_page_reference=data.source_page_reference,
            source_row_reference=data.source_row_reference,
            source_note=data.source_note,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
        )
        try:
            self._repo.add_result_item(item)
            self._db.flush()
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности локального результата"
            ) from exc
        self._db.commit()
        self._db.refresh(item)
        return item

    def complete_result_item(
        self, item_id: UUID, *, actor_worker_id: int
    ) -> MethodExecutionResultItem:
        item, execution = self._load_item(item_id, actor_worker_id, "complete-item")
        if item.record_state == mew.RESULT_EXCLUDED:
            raise DomainError(
                409,
                mew.RESULT_ITEM_ALREADY_EXCLUDED,
                "Исключённый результат нельзя завершить",
            )
        item.record_state = mew.RESULT_COMPLETE
        item.updated_by_worker_id = actor_worker_id
        self._db.flush()  # autoflush=False: пересчёт читает актуальное состояние
        self._calc.recompute(execution)
        self._db.commit()
        self._db.refresh(item)
        return item

    def exclude_result_item(
        self, item_id: UUID, reason: str, *, actor_worker_id: int
    ) -> MethodExecutionResultItem:
        item, execution = self._load_item(item_id, actor_worker_id, "exclude-item")
        if item.record_state == mew.RESULT_EXCLUDED:
            raise DomainError(
                409, mew.RESULT_ITEM_ALREADY_EXCLUDED, "Результат уже исключён"
            )
        if not (reason or "").strip():
            raise DomainError(
                422,
                mew.RESULT_ITEM_EXCLUDE_REASON_REQUIRED,
                "Причина исключения обязательна",
            )
        item.record_state = mew.RESULT_EXCLUDED
        item.excluded_reason = reason.strip()
        item.updated_by_worker_id = actor_worker_id
        self._db.flush()  # autoflush=False: пересчёт читает актуальное состояние
        # §10.3: исключение сопровождается audit-событием и причиной.
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_RESULT_ITEM,
            entity_id=item.id,
            event_type=mew.AUDIT_EVENT_REMOVED_RESULT_ITEM,
            actor_worker_id=actor_worker_id,
            reason=item.excluded_reason,
        )
        self._calc.recompute(execution)
        self._db.commit()
        self._db.refresh(item)
        return item

    def list_result_items(
        self, execution_id: UUID, *, actor_worker_id: int
    ) -> list[MethodExecutionResultItem]:
        execution = self._exec.get_execution(
            execution_id, actor_worker_id=actor_worker_id
        )
        return self._repo.list_result_items(execution.id)

    # ── внутреннее ────────────────────────────────────────────────────────────

    def _load_item(self, item_id: UUID, actor_worker_id: int, action: str):
        item = self._repo.get_result_item(item_id)
        if item is None:
            raise DomainError(
                404, mew.RESULT_ITEM_NOT_FOUND, "Локальный результат не найден"
            )
        execution = self._load(item.method_execution_id, actor_worker_id, action)
        return item, execution

    @staticmethod
    def _validate_result(data: ResultItemInput) -> None:
        if data.controlled_object_type not in mew.CONTROLLED_OBJECT_TYPES:
            raise DomainError(
                422, mew.EXECUTION_INVALID_COORDINATES, "Недопустимый тип объекта"
            )
        if data.evaluation not in mew.EVALUATIONS:
            raise DomainError(
                422, mew.EXECUTION_INVALID_COORDINATES, "Недопустимая оценка"
            )
        if data.wraps_zero:
            if data.coordinate_system is None or not mew.is_wraps_zero_allowed(
                data.coordinate_system
            ):
                raise DomainError(
                    422,
                    mew.EXECUTION_INVALID_WRAPS_ZERO,
                    "wraps_zero допустим только для замкнутой координатной системы",
                )
            if (
                data.coordinate_from is None
                or data.coordinate_to is None
                or data.coordinate_from <= data.coordinate_to
            ):
                raise DomainError(
                    422,
                    mew.EXECUTION_INVALID_COORDINATES,
                    "Замкнутый участок через ноль требует coordinate_from > coordinate_to",
                )
        if (
            data.controlled_object_type == mew.OBJ_OTHER
            and not (data.description or "").strip()
        ):
            raise DomainError(
                422,
                mew.EXECUTION_INVALID_COORDINATES,
                "Тип OTHER требует описания",
            )


# ── Сервис редакций выполнения (§18) ───────────────────────────────────────────


class MethodExecutionRevisionService:
    """Контролируемые редакции подтверждённого выполнения (§18).

    Исправление подтверждённого выполнения — только новой редакцией: полная копия
    выполнения, участников, локальных результатов и стандартов в новую нетекущую
    DRAFT-запись того же `root_execution_id`. Прежняя редакция не изменяется до
    подтверждения новой; при новом LAB_CONFIRMED замещение атомарно (см.
    `MethodExecutionService.confirm`). Конкурентное создание сериализуется
    блокировкой текущей строки, повторная незавершённая редакция запрещена.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ExecutionRepo(db)
        self._exec = MethodExecutionService(db)
        self._audit = QualityAuditService(self._repo)

    def create_revision(
        self,
        execution_id: UUID,
        *,
        correction_reason: str,
        expected_version: int,
        actor_worker_id: int,
    ) -> MethodExecution:
        old = self._exec._require_execution(execution_id)  # noqa: SLF001
        ctx = self._exec._ctx_for_execution(old)  # noqa: SLF001
        self._exec._require_visible(ctx.joint, actor_worker_id)  # noqa: SLF001
        self._exec._require_write(  # noqa: SLF001
            ctx.joint, actor_worker_id, "create-revision"
        )
        if old.status != mew.EXEC_LAB_CONFIRMED:
            raise DomainError(
                409,
                mew.EXECUTION_NOT_CONFIRMED_FOR_REVISION,
                "Редакция создаётся только из подтверждённого выполнения",
            )
        if not old.is_current:
            raise DomainError(
                409,
                mew.EXECUTION_NOT_CURRENT_REVISION,
                "Исправляется только текущая редакция",
            )
        if not (correction_reason or "").strip():
            raise DomainError(
                422,
                mew.EXECUTION_CORRECTION_REASON_REQUIRED,
                "Причина исправления обязательна",
            )
        self._exec._check_version(old, expected_version)  # noqa: SLF001

        # Сериализация конкурентного создания: блокируем текущую строку root, затем
        # проверяем отсутствие уже открытой редакции (§18, защита конкурентности).
        self._repo.get_current_execution_for_root(
            old.root_execution_id, for_update=True
        )
        if self._repo.has_open_revision(
            old.root_execution_id, exclude_id=old.id
        ):
            raise DomainError(
                409,
                mew.EXECUTION_REVISION_IN_PROGRESS,
                "По эпизоду уже есть незавершённая редакция",
            )

        new = self._clone_execution(old, correction_reason.strip(), actor_worker_id)
        self._repo.add_execution(new)
        self._clone_children(old, new, actor_worker_id)
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_METHOD_EXECUTION,
            entity_id=new.id,
            event_type=mew.AUDIT_EVENT_REVISION_CREATED,
            actor_worker_id=actor_worker_id,
            reason=correction_reason.strip(),
            previous_values={
                "supersedes_execution_id": str(old.id),
                "revision_no": old.revision_no,
            },
            new_values={"revision_no": new.revision_no},
        )
        return self._repo.save_execution(new)

    def list_revisions(
        self, execution_id: UUID, *, actor_worker_id: int
    ) -> list[MethodExecution]:
        execution = self._exec._require_execution(execution_id)  # noqa: SLF001
        ctx = self._exec._ctx_for_execution(execution)  # noqa: SLF001
        self._exec._require_visible(ctx.joint, actor_worker_id)  # noqa: SLF001
        return self._repo.list_executions_for_root(execution.root_execution_id)

    # ── копирование ───────────────────────────────────────────────────────────

    @staticmethod
    def _clone_execution(
        old: MethodExecution, correction_reason: str, actor_worker_id: int
    ) -> MethodExecution:
        new_id = uuid4()
        return MethodExecution(
            id=new_id,
            inspection_method_assignment_id=old.inspection_method_assignment_id,
            joint_id=old.joint_id,
            project_id=old.project_id,
            laboratory_company_id=old.laboratory_company_id,
            root_execution_id=old.root_execution_id,
            revision_no=old.revision_no + 1,
            supersedes_execution_id=old.id,
            is_current=False,
            correction_reason=correction_reason,
            status=mew.EXEC_DRAFT,
            # Факты эпизода копируются; оценка/подтверждение/регистрация сбрасываются
            # — новая редакция проходит lifecycle заново.
            time_precision=old.time_precision,
            performed_date=old.performed_date,
            started_at=old.started_at,
            finished_at=old.finished_at,
            source_type=old.source_type,
            source_reference=old.source_reference,
            source_received_at=old.source_received_at,
            procedure_document_id=old.procedure_document_id,
            procedure_reference_snapshot=old.procedure_reference_snapshot,
            procedure_revision_snapshot=old.procedure_revision_snapshot,
            declared_belt_length=old.declared_belt_length,
            calculated_belt_length=old.calculated_belt_length,
            belt_length_unit=old.belt_length_unit,
            calculated_evaluation=mew.EVAL_NOT_EVALUATED,
            calculated_completion=mew.COMPLETION_NOT_CALCULABLE,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )

    def _clone_children(
        self, old: MethodExecution, new: MethodExecution, actor_worker_id: int
    ) -> None:
        for p in self._repo.list_participants(old.id):
            self._repo.add_participant(
                MethodExecutionParticipant(
                    method_execution_id=new.id,
                    person_id=p.person_id,
                    participant_organization_id=p.participant_organization_id,
                    engagement_type=p.engagement_type,
                    engagement_basis=p.engagement_basis,
                    participant_role=p.participant_role,
                    person_certification_id=p.person_certification_id,
                    person_name_snapshot=p.person_name_snapshot,
                    organization_name_snapshot=p.organization_name_snapshot,
                    qualification_level_snapshot=p.qualification_level_snapshot,
                    certificate_number_snapshot=p.certificate_number_snapshot,
                    certificate_valid_from_snapshot=p.certificate_valid_from_snapshot,
                    certificate_valid_until_snapshot=(
                        p.certificate_valid_until_snapshot
                    ),
                    certification_scope_snapshot=p.certification_scope_snapshot,
                    created_by_worker_id=actor_worker_id,
                    updated_by_worker_id=actor_worker_id,
                )
            )
        # Копируются только ДЕЙСТВУЮЩИЕ строки (COMPLETE): EXCLUDED не переносятся
        # (§9C-4A.3 — их история остаётся в предыдущей редакции и QualityAuditEvent).
        # Подтверждённая редакция по инварианту не содержит DRAFT-строк.
        for r in self._repo.effective_result_items(old.id):
            new_item_id = uuid4()
            self._repo.add_result_item(
                MethodExecutionResultItem(
                    id=new_item_id,
                    method_execution_id=new.id,
                    # Межредакционная идентичность (§9C-4A.1 / канон 9C-33):
                    # постоянный корень сохраняется, supersedes указывает на строку
                    # предыдущей редакции, revision_no растёт на 1.
                    root_result_item_id=r.root_result_item_id,
                    revision_no=r.revision_no + 1,
                    supersedes_result_item_id=r.id,
                    record_state=r.record_state,
                    controlled_object_type=r.controlled_object_type,
                    object_reference=r.object_reference,
                    description=r.description,
                    coordinate_system=r.coordinate_system,
                    coordinate_from=r.coordinate_from,
                    coordinate_to=r.coordinate_to,
                    coordinate_unit=r.coordinate_unit,
                    wraps_zero=r.wraps_zero,
                    controlled_volume_value=r.controlled_volume_value,
                    controlled_volume_unit=r.controlled_volume_unit,
                    coverage_percent=r.coverage_percent,
                    quantity=r.quantity,
                    indication_description=r.indication_description,
                    indication_coordinate_from=r.indication_coordinate_from,
                    indication_coordinate_to=r.indication_coordinate_to,
                    indication_coordinate_unit=r.indication_coordinate_unit,
                    evaluation=r.evaluation,
                    required_action=r.required_action,
                    laboratory_result_text=r.laboratory_result_text,
                    note=r.note,
                    source_page_reference=r.source_page_reference,
                    source_row_reference=r.source_row_reference,
                    source_note=r.source_note,
                    excluded_reason=r.excluded_reason,
                    created_by_worker_id=actor_worker_id,
                    updated_by_worker_id=actor_worker_id,
                )
            )
        for s in self._repo.list_standards(old.id):
            self._repo.add_standard(
                MethodExecutionStandard(
                    method_execution_id=new.id,
                    standard_document_id=s.standard_document_id,
                    standard_code_snapshot=s.standard_code_snapshot,
                    standard_title_snapshot=s.standard_title_snapshot,
                    revision_snapshot=s.revision_snapshot,
                    created_by_worker_id=actor_worker_id,
                )
            )
