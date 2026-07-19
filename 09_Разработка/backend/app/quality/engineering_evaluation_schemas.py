"""Pydantic-схемы ядра EngineeringEvaluation (Task 9D-2D, ADR-021).

Стиль 9A–9D-1: вход с `extra="forbid"` (служебные поля → 422); команды жизненного
цикла несут обязательный `expected_version` (optimistic locking); актор — из
`X-User-Id`, не из тела. Все переходы статуса и правки содержания оформлены командами
(п.5 доменных правил), универсального PATCH статуса нет.

Границы 9D-2 (C01/C04): рекомендация `recommended_disposition` необязывающая, не
меняет `QualityFinding.status` и не создаёт объектов исполнения; классификация/исход/
judgement принадлежат ревизии (C10), nullable в DRAFT, обязательны на `prepare`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.quality.engineering_evaluation_workflow import (
    ConfidenceLevel,
    CriterionResult,
    EvaluationClassification,
    EvaluationOutcome,
    EvaluationStatus,
    ImpactScope,
    RecommendedDisposition,
    Severity,
    SourceRole,
)


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("Значение обязательно и не может быть пустым")
    return value


# ── Создание оценки / ревизии ────────────────────────────────────────────────────


class EvaluationCreateCommand(BaseModel):
    """Создание логической оценки + первой DRAFT-ревизии по finding.

    Тело пустое: контекст (`finding_id`) — из пути, актор — из `X-User-Id`. Номер
    `<CODE>-EE-<SEQUENCE>` выдаётся при создании. `extra="forbid"` — 422 на любые поля.
    """

    model_config = ConfigDict(extra="forbid")


class RevisionCreateCommand(BaseModel):
    """Создание новой DRAFT-ревизии-пересмотра (после FIXED/EFFECTIVE/WITHDRAWN).

    `revision_reason` обязателен (пересмотр обосновывается; со второй ревизии — CHECK).
    Новую ревизию нельзя создать, пока есть незакрытая (DRAFT/PREPARED/PENDING_APPROVAL).
    """

    model_config = ConfigDict(extra="forbid")

    revision_reason: str

    @field_validator("revision_reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _require_non_empty(value)


# ── Правка DRAFT-ревизии (содержание оценки) ──────────────────────────────────────


class RevisionUpdateCommand(BaseModel):
    """PATCH содержания DRAFT-ревизии. Только nullable-поля классификации/исхода/
    judgement (C10); служебные и переходные поля отклоняются (`extra="forbid"`).
    `expected_version` обязателен. Правка вне DRAFT запрещена (сервис)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    evaluation_outcome: EvaluationOutcome | None = None
    classification: EvaluationClassification | None = None
    recommended_disposition: RecommendedDisposition | None = None
    confirmed_severity: Severity | None = None
    impact_scope: ImpactScope | None = None
    rationale: str | None = None
    confidence_level: ConfidenceLevel | None = None
    confidence_note: str | None = None
    residual_risk: str | None = None
    application_conditions: str | None = None
    review_due_at: datetime | None = None
    revision_reason: str | None = None
    supersedes_impact: str | None = None
    required_approval_route: str | None = None


# ── Источники ─────────────────────────────────────────────────────────────────────


class SourceAddCommand(BaseModel):
    """Добавление источника к DRAFT-ревизии. Ревизионный — задаёт `source_revision_id`;
    неревизионный — хэш вычисляется по профилю (`QUALITY_FINDING`/`JOINT`)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    source_role: SourceRole
    source_entity_type: str
    source_entity_id: UUID
    source_revision_id: UUID | None = None
    applicability_note: str | None = None

    @field_validator("source_entity_type")
    @classmethod
    def _type_not_empty(cls, value: str) -> str:
        return _require_non_empty(value)


class SourceReverifyCommand(BaseModel):
    """Явная перепроверка источников DRAFT-ревизии (без автоподмены хэша, §7.3)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


# ── Критерии ──────────────────────────────────────────────────────────────────────


class CriterionAddCommand(BaseModel):
    """Добавление критерия приёмки к DRAFT-ревизии."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    requirement_ref: str
    parameter: str
    comparison_result: CriterionResult
    clause: str | None = None
    actual_value: str | None = None
    actual_num: float | None = None
    allowed_value: str | None = None
    allowed_num_min: float | None = None
    allowed_num_max: float | None = None
    unit: str | None = None
    applicability_comment: str | None = None
    engineer_comment: str | None = None

    @field_validator("requirement_ref", "parameter")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        return _require_non_empty(value)


class CriterionUpdateCommand(BaseModel):
    """Правка критерия DRAFT-ревизии. Все поля опциональны; `expected_version` обязателен."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    requirement_ref: str | None = None
    parameter: str | None = None
    comparison_result: CriterionResult | None = None
    clause: str | None = None
    actual_value: str | None = None
    actual_num: float | None = None
    allowed_value: str | None = None
    allowed_num_min: float | None = None
    allowed_num_max: float | None = None
    unit: str | None = None
    applicability_comment: str | None = None
    engineer_comment: str | None = None


# ── Исключения ────────────────────────────────────────────────────────────────────


class ExceptionAddCommand(BaseModel):
    """Добавление исключения (отступления) к отклонённому критерию DRAFT-ревизии."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    criterion_id: UUID
    basis: str
    justification: str
    residual_risk: str
    conditions: str | None = None
    required_approval_route: str | None = None

    @field_validator("basis", "justification", "residual_risk")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        return _require_non_empty(value)


# ── Команды lifecycle ─────────────────────────────────────────────────────────────


class VersionedCommand(BaseModel):
    """Команда с optimistic locking без дополнительных полей."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


class PrepareCommand(VersionedCommand):
    """DRAFT → PREPARED: проверка комплектности §8 + сверка источников §7.3."""


class FixCommand(VersionedCommand):
    """PREPARED/PENDING_APPROVAL → FIXED: повторная сверка источников; иной актор, чем prepare."""


class SetEffectiveCommand(VersionedCommand):
    """FIXED → EFFECTIVE (+ SUPERSEDED предыдущей действующей)."""


class ReasonCommand(BaseModel):
    """Команда с обязательной причиной (возврат/отзыв)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _require_non_empty(value)


class ReturnCommand(ReasonCommand):
    """PREPARED → DRAFT (возврат на доработку). Причина обязательна; новая ревизия не создаётся."""


class WithdrawCommand(ReasonCommand):
    """→ WITHDRAWN (конечный). Причина обязательна."""


class RequestReviewConfirmationCommand(BaseModel):
    """Инициировать пересмотр действующей оценки без изменения содержания (§7.8)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    proposed_review_due_at: datetime | None = None


class ConfirmReviewCommand(BaseModel):
    """Подтвердить пересмотр (§7.8): вступает новый `review_due_at`; иной актор, чем инициатор."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    review_due_at: datetime


# ── Выход: DTO чтения ─────────────────────────────────────────────────────────────


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision_id: UUID
    source_role: SourceRole
    source_entity_type: str
    source_entity_id: UUID
    source_revision_id: UUID | None
    source_hash: str | None
    hash_schema_version: str | None
    verified_at: datetime | None
    applicability_note: str | None
    created_by_worker_id: int
    created_at: datetime


class CriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision_id: UUID
    requirement_ref: str
    clause: str | None
    parameter: str
    actual_value: str | None
    actual_num: float | None
    allowed_value: str | None
    allowed_num_min: float | None
    allowed_num_max: float | None
    unit: str | None
    comparison_result: CriterionResult
    applicability_comment: str | None
    engineer_comment: str | None
    created_by_worker_id: int
    created_at: datetime


class ExceptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision_id: UUID
    criterion_id: UUID
    basis: str
    justification: str
    residual_risk: str
    conditions: str | None
    required_approval_route: str | None
    is_draft_copy: bool
    created_by_worker_id: int
    created_at: datetime


class RevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    evaluation_id: UUID
    revision_no: int
    previous_revision_id: UUID | None
    status: EvaluationStatus
    evaluation_outcome: EvaluationOutcome | None
    classification: EvaluationClassification | None
    recommended_disposition: RecommendedDisposition | None
    confirmed_severity: Severity | None
    impact_scope: ImpactScope | None
    rationale: str | None
    confidence_level: ConfidenceLevel | None
    confidence_note: str | None
    residual_risk: str | None
    application_conditions: str | None
    review_due_at: datetime | None
    revision_reason: str | None
    supersedes_impact: str | None
    required_approval_route: str | None
    prepared_by_worker_id: int | None
    prepared_at: datetime | None
    fixed_by_worker_id: int | None
    fixed_at: datetime | None
    withdrawn_by_worker_id: int | None
    withdrawn_at: datetime | None
    withdrawal_reason: str | None
    effective_at: datetime | None
    superseded_at: datetime | None
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int


class RevisionDetailRead(RevisionRead):
    """Ревизия с дочерними сущностями (источники/критерии/исключения)."""

    sources: list[SourceRead] = Field(default_factory=list)
    criteria: list[CriterionRead] = Field(default_factory=list)
    exceptions: list[ExceptionRead] = Field(default_factory=list)


class EvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    finding_id: UUID
    system_code: str
    current_revision_id: UUID | None
    effective_revision_id: UUID | None
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int
    revisions: list[RevisionRead] = Field(default_factory=list)


class EvaluationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    evaluation_id: UUID
    revision_id: UUID | None
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_worker_id: int
    actor_role: str | None
    reason: str | None
    metadata: dict | None = Field(default=None, validation_alias="event_metadata")
    correlation_id: UUID | None
    revision_version: int | None
    created_at: datetime
