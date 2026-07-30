"""Pydantic-схемы выполнения метода контроля (Task 9C, блок 9C-6A).

Только схемы (без API). Pydantic v2, `extra="forbid"` на входных моделях; UUID-типы;
`expected_version` в изменяющих командах (optimistic locking). Response-модели
отдельны и читают ORM через `from_attributes` — ORM-классы наружу не выносятся.
Доменные ошибки (`DomainError`) остаются на границе service/API и здесь не создаются.

Actor-разделение (проверено по модели): внутренний исполнитель/регистратор —
`*_by_worker_id` (Integer, server-authenticated actor worker id, в тело запроса не входит); внешние лица
лаборатории — `*_person_id` (UUID `QualityExternalPerson`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.quality.method_execution_workflow import (
    AssignmentComputedState,
    CalculatedCompletion,
    CancellationType,
    ConfirmationMode,
    ControlledObjectType,
    CoordinateSystem,
    CoordinateUnit,
    DeclaredCompletion,
    EngagementType,
    Evaluation,
    ExecutionStatus,
    ParticipantRole,
    RecordState,
    RequiredAction,
    TimePrecision,
)

# ── Общие миксины ──────────────────────────────────────────────────────────────


class _ForbidModel(BaseModel):
    """Вход: неизвестные ключи запрещены (§ требований блока)."""

    model_config = ConfigDict(extra="forbid")


class _ReadModel(BaseModel):
    """Выход: читается из ORM-инстанса, ORM наружу не переносится."""

    model_config = ConfigDict(from_attributes=True)


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("Значение не может быть пустым")
    return value


# ── Создание выполнения (§5) ───────────────────────────────────────────────────


class MethodExecutionCreate(_ForbidModel):
    """Тело создания выполнения. `joint_id`/`project_id` наследуются от назначения
    сервисом (инвариант §5.3) и клиентом не задаются. Лаборатория по умолчанию —
    из назначения."""

    laboratory_company_id: int | None = None
    time_precision: TimePrecision | None = None
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


# ── Команды жизненного цикла (§6, §7) ──────────────────────────────────────────


class VersionedCommand(_ForbidModel):
    """База изменяющей команды: обязательный `expected_version`."""

    expected_version: int


class StartExecutionCommand(VersionedCommand):
    pass


class RecordResultCommand(VersionedCommand):
    pass


class MarkPerformedCommand(VersionedCommand):
    time_precision: TimePrecision = "DATE_ONLY"
    performed_date: date | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ConfirmExecutionCommand(VersionedCommand):
    """Подтверждение выполнения. В блоке 9C поддержана только внутренняя регистрация
    внешнего документа (`EXTERNAL_DOCUMENT_REGISTRATION`)."""

    confirmation_mode: ConfirmationMode = "EXTERNAL_DOCUMENT_REGISTRATION"
    laboratory_evaluation: Evaluation | None = None
    evaluation_override_reason: str | None = None
    declared_completion: DeclaredCompletion | None = None
    completion_override_reason: str | None = None
    external_lab_approver_person_id: UUID | None = None
    external_lab_approval_date: date | None = None
    source_type: str | None = None
    source_reference: str | None = None


class CancelExecutionCommand(VersionedCommand):
    cancellation_type: CancellationType
    cancellation_reason: str

    @field_validator("cancellation_reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _non_empty(value)


class CreateExecutionRevisionCommand(VersionedCommand):
    correction_reason: str

    @field_validator("correction_reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _non_empty(value)


# ── Участники (§9) ─────────────────────────────────────────────────────────────


class ParticipantCreate(_ForbidModel):
    person_id: UUID
    participant_role: ParticipantRole
    engagement_type: EngagementType | None = None
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


class ParticipantRead(_ReadModel):
    id: UUID
    method_execution_id: UUID
    person_id: UUID
    participant_organization_id: int | None
    engagement_type: EngagementType | None
    engagement_basis: str | None
    participant_role: ParticipantRole
    person_certification_id: UUID | None
    person_name_snapshot: str | None
    organization_name_snapshot: str | None
    qualification_level_snapshot: str | None
    certificate_number_snapshot: str | None
    certificate_valid_from_snapshot: date | None
    certificate_valid_until_snapshot: date | None
    certification_scope_snapshot: str | None
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime


# ── Локальные результаты (§10) ─────────────────────────────────────────────────


class ResultItemCreate(_ForbidModel):
    controlled_object_type: ControlledObjectType = "WHOLE_JOINT"
    object_reference: str | None = None
    description: str | None = None
    coordinate_system: CoordinateSystem | None = None
    coordinate_from: Decimal | None = None
    coordinate_to: Decimal | None = None
    coordinate_unit: CoordinateUnit | None = None
    wraps_zero: bool = False
    controlled_volume_value: Decimal | None = None
    controlled_volume_unit: str | None = None
    coverage_percent: Decimal | None = None
    quantity: Decimal | None = None
    indication_description: str | None = None
    indication_coordinate_from: Decimal | None = None
    indication_coordinate_to: Decimal | None = None
    indication_coordinate_unit: str | None = None
    evaluation: Evaluation = "NOT_EVALUATED"
    required_action: RequiredAction | None = None
    laboratory_result_text: str | None = None
    note: str | None = None
    source_page_reference: str | None = None
    source_row_reference: str | None = None
    source_note: str | None = None


class ExcludeResultItemCommand(_ForbidModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _non_empty(value)


class ResultItemRead(_ReadModel):
    id: UUID
    method_execution_id: UUID
    root_result_item_id: UUID
    revision_no: int
    supersedes_result_item_id: UUID | None
    record_state: RecordState
    controlled_object_type: ControlledObjectType
    object_reference: str | None
    description: str | None
    coordinate_system: CoordinateSystem | None
    coordinate_from: Decimal | None
    coordinate_to: Decimal | None
    coordinate_unit: CoordinateUnit | None
    wraps_zero: bool
    controlled_volume_value: Decimal | None
    controlled_volume_unit: str | None
    coverage_percent: Decimal | None
    quantity: Decimal | None
    indication_description: str | None
    indication_coordinate_from: Decimal | None
    indication_coordinate_to: Decimal | None
    indication_coordinate_unit: str | None
    evaluation: Evaluation
    required_action: RequiredAction | None
    laboratory_result_text: str | None
    note: str | None
    source_page_reference: str | None
    source_row_reference: str | None
    source_note: str | None
    excluded_reason: str | None
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime


# ── Стандарты (§14.2) ──────────────────────────────────────────────────────────


class StandardCreate(_ForbidModel):
    standard_document_id: UUID | None = None
    standard_code_snapshot: str | None = None
    standard_title_snapshot: str | None = None
    revision_snapshot: str | None = None


class StandardRead(_ReadModel):
    id: UUID
    method_execution_id: UUID
    standard_document_id: UUID | None
    standard_code_snapshot: str | None
    standard_title_snapshot: str | None
    revision_snapshot: str | None
    created_by_worker_id: int
    created_at: datetime


# ── Внешнее лицо (§9.3) ────────────────────────────────────────────────────────


class ExternalPersonRead(_ReadModel):
    id: UUID
    full_name: str
    organization_company_id: int | None
    external_ref: str | None
    note: str | None
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime


# ── Выполнение: response ───────────────────────────────────────────────────────


class MethodExecutionRead(_ReadModel):
    id: UUID
    inspection_method_assignment_id: UUID
    joint_id: UUID
    project_id: UUID
    laboratory_company_id: int

    root_execution_id: UUID
    revision_no: int
    supersedes_execution_id: UUID | None
    is_current: bool
    correction_reason: str | None

    status: ExecutionStatus
    confirmation_mode: ConfirmationMode | None

    performed_date: date | None
    started_at: datetime | None
    finished_at: datetime | None
    time_precision: TimePrecision | None

    calculated_evaluation: Evaluation | None
    laboratory_evaluation: Evaluation | None
    evaluation_override_reason: str | None
    calculated_completion: CalculatedCompletion | None
    declared_completion: DeclaredCompletion | None
    completion_override_reason: str | None

    calculated_belt_length: Decimal | None
    declared_belt_length: Decimal | None
    belt_length_unit: str | None
    belt_length_override_reason: str | None

    source_type: str | None
    source_reference: str | None
    source_received_at: datetime | None

    procedure_document_id: UUID | None
    procedure_reference_snapshot: str | None
    procedure_revision_snapshot: str | None

    cancellation_type: CancellationType | None
    cancellation_reason: str | None
    cancelled_by_worker_id: int | None
    cancelled_at: datetime | None

    lab_confirmed_by_user_id: int | None
    lab_confirmed_at: datetime | None
    lab_approver_person_id: UUID | None
    external_lab_approver_person_id: UUID | None
    external_lab_approval_date: date | None
    registered_by_worker_id: int | None
    registered_at: datetime | None

    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int


class MethodExecutionListResponse(_ReadModel):
    assignment_id: UUID
    items: list[MethodExecutionRead]


class AssignmentExecutionStateRead(BaseModel):
    """Вычисляемое состояние назначения по текущим выполнениям (§24)."""

    model_config = ConfigDict(from_attributes=False)

    assignment_id: UUID
    state: AssignmentComputedState


class MethodExecutionRevisionListResponse(_ReadModel):
    root_execution_id: UUID
    items: list[MethodExecutionRead] = Field(default_factory=list)
