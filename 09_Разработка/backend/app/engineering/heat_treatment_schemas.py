"""Pydantic-схемы термической обработки (Task 8F).

Команды (`extra="forbid"`) отделены от read-моделей (`from_attributes=True`), как
в остальном модуле engineering. Actor берётся только из server-authenticated actor worker id, поэтому в телах
его нет. Оптимистическая блокировка — необязательный `expected_version` в командах
изменения (как `expected_record_version` у WeldOperation).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.engineering.heat_treatment_workflow import (
    AutoCheckResult,
    BatchReviewResult,
    BatchStatus,
    DeviationOgsDecision,
    DeviationSeverity,
    DeviationStatus,
    DeviationType,
    EvidenceSufficiency,
    JointHeatTreatmentState,
    OperationReason,
    OperationResult,
    OperationStatus,
    ProcedureRevisionStatus,
    RecordStatus,
    RecordType,
)


def _require_non_blank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Значение не может быть пустым")
    return value


# ── Технологическая карта (минимальная ссылочная сущность) ────────────────────


class ProcedureRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    procedure_no: str = Field(min_length=1, max_length=100)
    revision_no: str = Field(min_length=1, max_length=50)
    ht_type: str | None = Field(default=None, max_length=50)
    heating_method: str | None = Field(default=None, max_length=50)
    min_temperature: Decimal | None = None
    max_temperature: Decimal | None = None
    soak_duration_minutes: int | None = Field(default=None, ge=0)
    max_heating_rate: Decimal | None = None
    max_cooling_rate: Decimal | None = None
    tolerances: dict | None = None
    applicable_line_ids: list[UUID] | None = None

    @field_validator("procedure_no", "revision_no")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class ProcedureRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    procedure_no: str
    revision_no: str
    status: ProcedureRevisionStatus
    ht_type: str | None
    heating_method: str | None
    min_temperature: Decimal | None
    max_temperature: Decimal | None
    soak_duration_minutes: int | None
    max_heating_rate: Decimal | None
    max_cooling_rate: Decimal | None
    tolerances: dict | None
    applicable_line_ids: list[UUID] | None
    created_by: int
    created_at: datetime
    approved_by: int | None
    approved_at: datetime | None


# ── Общий цикл термообработки ─────────────────────────────────────────────────


class HeatTreatmentBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    batch_no: str = Field(min_length=1, max_length=100)
    procedure_revision_id: UUID | None = None
    planned_start_at: datetime | None = None
    operator_worker_id: int | None = Field(default=None, gt=0)
    operator_name_text: str | None = Field(default=None, max_length=255)
    equipment_text: str | None = None

    @field_validator("batch_no")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class HeatTreatmentBatchUpdate(BaseModel):
    """PATCH цикла до старта. Фактические параметры допускается вносить в
    IN_PROGRESS/COMPLETED (перед проверкой); правка закрытого цикла запрещена
    сервисом."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, gt=0)

    batch_no: str | None = Field(default=None, min_length=1, max_length=100)
    procedure_revision_id: UUID | None = None
    planned_start_at: datetime | None = None
    operator_worker_id: int | None = Field(default=None, gt=0)
    operator_name_text: str | None = Field(default=None, max_length=255)
    equipment_text: str | None = None

    actual_soak_temperature: Decimal | None = None
    actual_min_temperature: Decimal | None = None
    actual_max_temperature: Decimal | None = None
    actual_soak_duration_minutes: int | None = Field(default=None, ge=0)
    actual_heating_rate: Decimal | None = None
    actual_cooling_rate: Decimal | None = None
    process_comment: str | None = None


class HeatTreatmentBatchPlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, gt=0)


class HeatTreatmentBatchStartCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_started_at: datetime | None = None
    expected_version: int | None = Field(default=None, gt=0)


class HeatTreatmentBatchCompleteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_completed_at: datetime | None = None
    expected_version: int | None = Field(default=None, gt=0)


class HeatTreatmentBatchReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: BatchReviewResult
    comment: str | None = None
    expected_version: int | None = Field(default=None, gt=0)


class HeatTreatmentBatchCloseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, gt=0)


class HeatTreatmentBatchCancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    expected_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class HeatTreatmentBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    batch_no: str
    procedure_revision_id: UUID | None
    status: BatchStatus

    planned_start_at: datetime | None
    actual_started_at: datetime | None
    actual_completed_at: datetime | None

    operator_worker_id: int | None
    operator_name_text: str | None
    equipment_text: str | None

    actual_soak_temperature: Decimal | None
    actual_min_temperature: Decimal | None
    actual_max_temperature: Decimal | None
    actual_soak_duration_minutes: int | None
    actual_heating_rate: Decimal | None
    actual_cooling_rate: Decimal | None
    process_comment: str | None

    procedure_snapshot: dict | None
    auto_check_result: AutoCheckResult
    auto_check_details: dict | None
    auto_check_at: datetime | None

    review_result: BatchReviewResult
    review_comment: str | None
    reviewed_by: int | None
    reviewed_at: datetime | None

    cancelled_reason: str | None
    cancelled_by: int | None
    cancelled_at: datetime | None

    created_by: int
    created_at: datetime
    updated_by: int
    updated_at: datetime
    version: int


class HeatTreatmentBatchListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    procedure_revision_id: UUID | None = None
    status: BatchStatus | None = None
    review_result: BatchReviewResult | None = None
    batch_no: str | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class HeatTreatmentBatchListResponse(BaseModel):
    items: list[HeatTreatmentBatchRead]
    total: int
    limit: int
    offset: int


# ── Операция по соединению ────────────────────────────────────────────────────


class HeatTreatmentOperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    joint_id: UUID
    weld_operation_id: UUID | None = None
    reason: OperationReason = "AFTER_INITIAL_WELD"
    previous_heat_treatment_operation_id: UUID | None = None


class HeatTreatmentOperationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, gt=0)
    reason: OperationReason | None = None
    weld_operation_id: UUID | None = None
    previous_heat_treatment_operation_id: UUID | None = None
    individual_started_at: datetime | None = None
    individual_completed_at: datetime | None = None


class HeatTreatmentOperationExcludeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    expected_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class HeatTreatmentOperationEvaluateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: OperationResult
    evidence_sufficiency: EvidenceSufficiency
    result_comment: str | None = None
    expected_version: int | None = Field(default=None, gt=0)


class HeatTreatmentOperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    joint_id: UUID
    weld_operation_id: UUID | None
    previous_heat_treatment_operation_id: UUID | None
    reason: OperationReason
    status: OperationStatus
    result: OperationResult
    evidence_sufficiency: EvidenceSufficiency
    individual_started_at: datetime | None
    individual_completed_at: datetime | None
    result_comment: str | None
    exclusion_reason: str | None
    evaluated_by: int | None
    evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


# ── Документы ─────────────────────────────────────────────────────────────────


class HeatTreatmentRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: RecordType
    document_no: str | None = Field(default=None, max_length=100)
    document_date: date | None = None
    file_name: str | None = Field(default=None, max_length=255)
    storage_key: str | None = Field(default=None, max_length=500)
    checksum: str | None = Field(default=None, max_length=128)


class HeatTreatmentRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    record_type: RecordType
    document_no: str | None
    document_date: date | None
    file_name: str | None
    storage_key: str | None
    checksum: str | None
    status: RecordStatus
    uploaded_by: int
    uploaded_at: datetime
    verified_by: int | None
    verified_at: datetime | None


# ── Отклонения ────────────────────────────────────────────────────────────────


class HeatTreatmentDeviationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID | None = None
    deviation_type: DeviationType
    description: str = Field(min_length=1)
    planned_value: str | None = Field(default=None, max_length=255)
    actual_value: str | None = Field(default=None, max_length=255)
    severity: DeviationSeverity = "MINOR"

    @field_validator("description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class HeatTreatmentDeviationDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ogs_decision: DeviationOgsDecision
    decision_comment: str | None = None


class HeatTreatmentDeviationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    operation_id: UUID | None
    deviation_type: DeviationType
    description: str
    planned_value: str | None
    actual_value: str | None
    severity: DeviationSeverity
    status: DeviationStatus
    ogs_decision: DeviationOgsDecision | None
    decision_comment: str | None
    created_by: int
    created_at: datetime
    decided_by: int | None
    decided_at: datetime | None


# ── Журнал термообработки (read-only отчётное представление, §25) ─────────────


class HeatTreatmentJournalRow(BaseModel):
    """Одна плоская строка журнала = одна HeatTreatmentOperation (§25)."""

    operation_id: UUID
    batch_id: UUID
    joint_id: UUID
    joint_no: str | None
    line_id: UUID | None
    weld_operation_id: UUID | None
    weld_performed_on: date | None
    batch_no: str
    procedure_no: str | None
    procedure_revision_no: str | None
    ht_type: str | None
    actual_started_at: datetime | None
    actual_completed_at: datetime | None
    actual_soak_temperature: Decimal | None
    actual_soak_duration_minutes: int | None
    chart_document_no: str | None
    operator_worker_id: int | None
    operator_name_text: str | None
    operation_status: OperationStatus
    operation_result: OperationResult
    batch_status: BatchStatus
    batch_review_result: BatchReviewResult


class HeatTreatmentJournalResponse(BaseModel):
    items: list[HeatTreatmentJournalRow]
    total: int
    limit: int
    offset: int


# ── Состояние требования термообработки по Joint (§23) ────────────────────────


class JointHeatTreatmentStateRead(BaseModel):
    joint_id: UUID
    heat_treatment_required: bool
    state: JointHeatTreatmentState
    dependent_steps_ready: bool
    current_operation_id: UUID | None
    current_batch_id: UUID | None
