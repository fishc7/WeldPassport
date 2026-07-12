from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.engineering.joint_workflow import (
    ApprovalState,
    BlockScope,
    BlockType,
    DecisionMethod,
    DocumentRole,
    JointStatus,
    LinkStatus,
    PendingReason,
    RevisionRole,
)
from app.engineering.weld_operation_corrections import (
    ApplicationStatus,
    CorrectionLifecycleStatus,
    CorrectionType,
    ImpactLevel,
    OgsReviewStatus as CorrectionOgsReviewStatus,
    SmrApprovalStatus,
    SourceType,
)
from app.engineering.weld_operation_review import (
    OgsReviewStatus,
    ReasonCode,
    WelderConfirmationStatus,
)
from app.engineering.weld_operation_validation import (
    QualificationValidationStatus,
    WpsValidationStatus,
)
from app.engineering.weld_operation_workflow import (
    OperationKind,
    ReweldDecision,
    ReweldReason,
    WeldOperationStatus,
    WeldStage,
)

DocumentType = Literal["ISOMETRIC", "DRAWING", "WELD_MAP", "OTHER"]
EngineeringStatus = Literal["DRAFT", "APPROVED", "CANCELLED", "SUPERSEDED"]

# ── Joint enums (Task 5A ядро + Task 5B жизненный цикл, ADR-010 / ADR-011) ─────
# JointStatus / ApprovalState / PendingReason / DecisionMethod / BlockType /
# BlockScope — единый источник в joint_workflow (канон ADR-011).
GeometryType = Literal["BUTT", "FILLET", "TEE", "LAP", "SLOT", "OTHER"]
WeldJointType = Literal["BW", "SW", "FW", "OTHER"]
ConnectionCode = Literal["C", "U", "T", "N", "P", "OTHER"]
ProductionState = Literal["NOT_STARTED"]
JointSortBy = Literal[
    "created_at", "updated_at", "system_code", "joint_no", "line_id"
]
SortOrder = Literal["asc", "desc"]


def _require_non_blank(value: str) -> str:
    """Обязательное непустое значение: пробельные строки отклоняются (422)."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("значение не может быть пустым")
    return stripped


def _reject_blank_keep_original(value: str) -> str:
    """Отклоняет пробельные строки (422), но НЕ изменяет исходное значение.

    Для joint_no: обрезка/нормализация хранится отдельно (joint_no_normalized);
    исходное обозначение сохраняется как передано (ADR-010)."""
    if not value.strip():
        raise ValueError("значение не может быть пустым")
    return value


# ── EngineeringDocument ───────────────────────────────────────────────────────


class EngineeringDocumentCreate(BaseModel):
    project_id: UUID
    line_id: UUID | None = None
    document_no: str = Field(min_length=1, max_length=255)
    document_type: DocumentType
    title: str | None = Field(default=None, max_length=255)

    @field_validator("document_no")
    @classmethod
    def _document_no_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class EngineeringDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    line_id: UUID | None
    document_no: str
    document_type: DocumentType
    title: str | None
    status: EngineeringStatus
    created_by: int
    created_at: datetime
    approved_by: int | None
    approved_at: datetime | None


class EngineeringDocumentListFilters(BaseModel):
    project_id: UUID | None = None
    line_id: UUID | None = None
    document_type: DocumentType | None = None
    status: EngineeringStatus | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


# ── DocumentRevision ──────────────────────────────────────────────────────────


class DocumentRevisionCreate(BaseModel):
    revision_code: str = Field(min_length=1, max_length=100)
    issued_at: date | None = None

    @field_validator("revision_code")
    @classmethod
    def _revision_code_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class DocumentRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engineering_document_id: UUID
    revision_code: str
    issued_at: date | None
    status: EngineeringStatus
    created_by: int
    created_at: datetime
    approved_by: int | None
    approved_at: datetime | None


# ── Joint (Task 5A, ADR-010) ──────────────────────────────────────────────────


class _JointEngineeringFields(BaseModel):
    """Общие инженерные поля, редактируемые и при создании, и при PATCH.

    Валидация координат (обязательность coordinate_system) выполняется в
    наследниках, где известен итоговый набор значений.
    """

    dn_1: Decimal | None = Field(default=None, gt=0)
    dn_2: Decimal | None = Field(default=None, gt=0)
    thickness_1: Decimal | None = Field(default=None, gt=0)
    thickness_2: Decimal | None = Field(default=None, gt=0)
    material_id_1: UUID | None = None
    material_id_2: UUID | None = None
    material_text_1: str | None = Field(default=None, max_length=255)
    material_text_2: str | None = Field(default=None, max_length=255)
    component_type_1: str | None = Field(default=None, max_length=50)
    component_type_2: str | None = Field(default=None, max_length=50)
    component_item_id_1: UUID | None = None
    component_item_id_2: UUID | None = None
    component_text_1: str | None = Field(default=None, max_length=255)
    component_text_2: str | None = Field(default=None, max_length=255)
    geometry_type: GeometryType | None = None
    weld_joint_type: WeldJointType | None = None
    connection_code: ConnectionCode | None = None
    required_root_method: str | None = Field(default=None, max_length=50)
    required_fill_method: str | None = Field(default=None, max_length=50)
    required_cap_method: str | None = Field(default=None, max_length=50)
    planned_wps_id: UUID | None = None
    heat_treatment_required: bool = False
    heat_treatment_type: str | None = Field(default=None, max_length=50)
    heat_treatment_note: str | None = None
    sheet_no: str | None = Field(default=None, max_length=50)
    drawing_zone: str | None = Field(default=None, max_length=50)
    position_x: Decimal | None = None
    position_y: Decimal | None = None
    coordinate_system: str | None = Field(default=None, max_length=50)
    location_note: str | None = None
    document_note: str | None = None


class JointCreate(_JointEngineeringFields):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    line_id: UUID
    # Единая ревизия-основание: сервис проставляет origin = current из неё.
    document_revision_id: UUID
    joint_no: str = Field(min_length=1, max_length=100)
    created_by: int = Field(gt=0)

    @field_validator("joint_no")
    @classmethod
    def _joint_no_not_blank(cls, v: str) -> str:
        return _reject_blank_keep_original(v)

    @model_validator(mode="after")
    def _validate_coordinates(self) -> "JointCreate":
        if (
            self.position_x is not None or self.position_y is not None
        ) and self.coordinate_system is None:
            raise ValueError(
                "coordinate_system обязателен при заданных position_x/position_y"
            )
        return self


class JointUpdate(BaseModel):
    """PATCH: только допустимые к изменению поля.

    Защищённые поля (id, project_id, system_code, origin/current revision,
    status, created_by, created_at) в схеме отсутствуют; `extra="forbid"` даёт
    422 при попытке их передать. `expected_version` и `updated_by` обязательны.
    """

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
    updated_by: int = Field(gt=0)

    line_id: UUID | None = None
    joint_no: str | None = Field(default=None, min_length=1, max_length=100)

    dn_1: Decimal | None = Field(default=None, gt=0)
    dn_2: Decimal | None = Field(default=None, gt=0)
    thickness_1: Decimal | None = Field(default=None, gt=0)
    thickness_2: Decimal | None = Field(default=None, gt=0)
    material_id_1: UUID | None = None
    material_id_2: UUID | None = None
    material_text_1: str | None = Field(default=None, max_length=255)
    material_text_2: str | None = Field(default=None, max_length=255)
    component_type_1: str | None = Field(default=None, max_length=50)
    component_type_2: str | None = Field(default=None, max_length=50)
    component_item_id_1: UUID | None = None
    component_item_id_2: UUID | None = None
    component_text_1: str | None = Field(default=None, max_length=255)
    component_text_2: str | None = Field(default=None, max_length=255)
    geometry_type: GeometryType | None = None
    weld_joint_type: WeldJointType | None = None
    connection_code: ConnectionCode | None = None
    required_root_method: str | None = Field(default=None, max_length=50)
    required_fill_method: str | None = Field(default=None, max_length=50)
    required_cap_method: str | None = Field(default=None, max_length=50)
    planned_wps_id: UUID | None = None
    heat_treatment_required: bool | None = None
    heat_treatment_type: str | None = Field(default=None, max_length=50)
    heat_treatment_note: str | None = None
    sheet_no: str | None = Field(default=None, max_length=50)
    drawing_zone: str | None = Field(default=None, max_length=50)
    position_x: Decimal | None = None
    position_y: Decimal | None = None
    coordinate_system: str | None = Field(default=None, max_length=50)
    location_note: str | None = None
    document_note: str | None = None

    @field_validator("joint_no")
    @classmethod
    def _joint_no_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _reject_blank_keep_original(v)


class JointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    line_id: UUID
    origin_document_revision_id: UUID
    current_document_revision_id: UUID
    system_code: str
    joint_no: str
    joint_no_normalized: str
    status: JointStatus

    # Три версии (Task 5B). `version` сохранён как зеркало record_version для
    # обратной совместимости контракта Task 5A.
    version: int
    record_version: int
    approval_version: int
    workflow_version: int

    # Согласования ПТО/ОГС.
    pto_status: ApprovalState
    pto_pending_reason: PendingReason | None
    pto_decision_method: DecisionMethod | None
    pto_approval_version: int | None
    pto_decided_by: int | None
    pto_decided_at: datetime | None
    pto_comment: str | None
    ogs_status: ApprovalState
    ogs_pending_reason: PendingReason | None
    ogs_decision_method: DecisionMethod | None
    ogs_approval_version: int | None
    ogs_decided_by: int | None
    ogs_decided_at: datetime | None
    ogs_comment: str | None

    submitted_by: int | None
    submitted_at: datetime | None
    cancelled_reason: str | None
    cancelled_by: int | None
    cancelled_at: datetime | None
    superseded_by_joint_id: UUID | None
    superseded_by: int | None
    superseded_at: datetime | None

    dn_1: Decimal | None
    dn_2: Decimal | None
    thickness_1: Decimal | None
    thickness_2: Decimal | None
    material_id_1: UUID | None
    material_id_2: UUID | None
    material_text_1: str | None
    material_text_2: str | None
    component_type_1: str | None
    component_type_2: str | None
    component_item_id_1: UUID | None
    component_item_id_2: UUID | None
    component_text_1: str | None
    component_text_2: str | None
    geometry_type: GeometryType | None
    weld_joint_type: WeldJointType | None
    connection_code: ConnectionCode | None
    required_root_method: str | None
    required_fill_method: str | None
    required_cap_method: str | None
    planned_wps_id: UUID | None
    heat_treatment_required: bool
    heat_treatment_type: str | None
    heat_treatment_note: str | None
    sheet_no: str | None
    drawing_zone: str | None
    position_x: Decimal | None
    position_y: Decimal | None
    coordinate_system: str | None
    location_note: str | None
    document_note: str | None

    created_by: int
    updated_by: int
    created_at: datetime
    updated_at: datetime

    # Вычисляемые поля (не колонки БД).
    ready_for_welding: bool
    missing_welding_requirements: list[str]
    production_state: ProductionState
    # Требуется проверка, если хотя бы одна сторона не APPROVED либо Joint ещё в
    # DRAFT/PENDING_REVIEW (§ решения Task 5B плана).
    requires_review: bool
    is_blocked: bool
    # Доступные действия актора (§22-23 ADR-011). Пусто в массовых списках и для
    # аудитора; заполняется на карточке Joint и в ответах команд.
    available_actions: list[str] = Field(default_factory=list)


class JointListFilters(BaseModel):
    project_id: UUID | None = None
    line_id: UUID | None = None
    current_document_revision_id: UUID | None = None
    system_code: str | None = None
    joint_no: str | None = None
    # Служебное: нормализованная форма joint_no, проставляется сервисом для
    # сравнения дублей. В API не принимается напрямую.
    joint_no_normalized: str | None = None
    geometry_type: GeometryType | None = None
    weld_joint_type: WeldJointType | None = None
    ready_for_welding: bool | None = None
    sort_by: JointSortBy = "created_at"
    sort_order: SortOrder = "asc"
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class JointListResponse(BaseModel):
    items: list[JointRead]
    total: int
    limit: int
    offset: int


# ── Команды жизненного цикла (Task 5B, §7-8 ADR-011 / §7-8 задания) ───────────
# Актор (worker_id) берётся ТОЛЬКО из auth-контекста (X-User-Id), не из тела
# (§17 ADR-011). Тело несёт причины/комментарии/ожидаемые версии. Ожидаемые версии
# опциональны: при передаче сверяются и дают 409 с машинным кодом (§16).


def _require_reason(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Причина обязательна и не может быть пустой")
    return stripped


class SubmitForReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workflow_version: int | None = Field(default=None, gt=0)


class ApprovePtoCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = None
    expected_approval_version: int | None = Field(default=None, gt=0)
    expected_workflow_version: int | None = Field(default=None, gt=0)


class ApproveOgsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # AUTOMATIC не применяется по умолчанию; OVERRIDE — только CHIEF_WELDER (§9).
    method: Literal["MANUAL", "AUTOMATIC", "OVERRIDE"] = "MANUAL"
    comment: str | None = None
    expected_approval_version: int | None = Field(default=None, gt=0)
    expected_workflow_version: int | None = Field(default=None, gt=0)


class RejectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    expected_workflow_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class RevokeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    expected_workflow_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class BlockCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_type: BlockType = "MANUAL_HOLD"
    scope: BlockScope = "ALL"
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class UnblockCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    reason: str | None = None


class CancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    expected_workflow_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class SupersedeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successor_joint_id: UUID
    reason: str | None = None
    expected_source_version: int | None = Field(default=None, gt=0)
    expected_successor_version: int | None = Field(default=None, gt=0)


class JointBlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    joint_id: UUID
    block_type: BlockType
    scope: BlockScope
    reason: str
    created_by: int
    created_at: datetime
    released_by: int | None
    released_at: datetime | None
    release_reason: str | None


# ── История связей Joint ↔ DocumentRevision (Task 6) ──────────────────────────
# Актор берётся из auth-контекста (X-User-Id), не из тела. ORIGIN/PRIMARY —
# системные роли (при создании Joint и смене текущей ревизии), пользователем не
# задаются: create-link принимает только пользовательские роли.


class JointDocumentRevisionCreate(BaseModel):
    """Новая связь-снимок текущего состояния Joint с ревизией (не меняет current)."""

    model_config = ConfigDict(extra="forbid")

    document_revision_id: UUID
    # ORIGIN — только системная; PRIMARY назначается лишь через set-current-revision.
    revision_role: Literal["CONFIRMED", "MODIFIED", "REMOVED"] = "MODIFIED"
    document_role: Literal["ADDITIONAL", "EXECUTIVE", "REFERENCE"] = "ADDITIONAL"


class InvalidateLinkCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class SetCurrentRevisionCommand(BaseModel):
    """Сделать выбранную ACTIVE-связь текущей PRIMARY-ревизией Joint."""

    model_config = ConfigDict(extra="forbid")

    link_id: UUID
    # Три версии Task 5B: смена PRIMARY — workflow-переход; восстановление значимых
    # данных может задеть согласования, поэтому проверяется и approval_version.
    expected_record_version: int | None = Field(default=None, gt=0)
    expected_approval_version: int | None = Field(default=None, gt=0)
    expected_workflow_version: int | None = Field(default=None, gt=0)


class JointDocumentRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    joint_id: UUID
    document_revision_id: UUID
    revision_role: RevisionRole
    document_role: DocumentRole
    link_status: LinkStatus

    # Неизменяемый снимок параметров Joint на момент связи (префикс snapshot_
    # явно отделяет историческую копию от текущих полей Joint).
    snapshot_joint_no: str
    snapshot_joint_no_normalized: str
    snapshot_line_id: UUID
    snapshot_dn_1: Decimal | None
    snapshot_dn_2: Decimal | None
    snapshot_thickness_1: Decimal | None
    snapshot_thickness_2: Decimal | None
    snapshot_material_id_1: UUID | None
    snapshot_material_id_2: UUID | None
    snapshot_material_text_1: str | None
    snapshot_material_text_2: str | None
    snapshot_component_type_1: str | None
    snapshot_component_type_2: str | None
    snapshot_component_item_id_1: UUID | None
    snapshot_component_item_id_2: UUID | None
    snapshot_component_text_1: str | None
    snapshot_component_text_2: str | None
    snapshot_geometry_type: GeometryType | None
    snapshot_weld_joint_type: WeldJointType | None
    snapshot_connection_code: ConnectionCode | None
    snapshot_required_root_method: str | None
    snapshot_required_fill_method: str | None
    snapshot_required_cap_method: str | None
    snapshot_planned_wps_id: UUID | None
    snapshot_heat_treatment_required: bool
    snapshot_heat_treatment_type: str | None
    snapshot_heat_treatment_note: str | None
    snapshot_sheet_no: str | None
    snapshot_drawing_zone: str | None
    snapshot_position_x: Decimal | None
    snapshot_position_y: Decimal | None
    snapshot_coordinate_system: str | None
    snapshot_location_note: str | None
    snapshot_document_note: str | None

    created_by: int
    created_at: datetime
    updated_by: int | None
    updated_at: datetime | None
    invalidated_reason: str | None
    invalidated_by: int | None
    invalidated_at: datetime | None


class JointEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    joint_id: UUID
    event_type: str
    actor_worker_id: int
    actor_role_code: str | None
    previous_status: str | None
    new_status: str | None
    previous_pto_status: str | None
    new_pto_status: str | None
    previous_ogs_status: str | None
    new_ogs_status: str | None
    record_version: int
    approval_version: int
    workflow_version: int
    decision_method: str | None
    reason: str | None
    created_at: datetime


# ── Bulk Joint Import (Task 7, ADR-010) ───────────────────────────────────────
# Bulk — альтернативный способ выполнения того же сценария создания Joint. Строки
# содержат только инженерные поля (через общий _JointEngineeringFields, чтобы
# правила не расходились с JointCreate) + обязательный joint_no; общие поля пакета
# (project_id, line_id, document_revision_id, created_by, idempotency_key) — в
# конверте JointBulkCreate. Порядок items значим (влияет на row_index и hash).


class JointBulkItem(_JointEngineeringFields):
    """Одна строка пакета: joint_no + инженерные поля, разрешённые JointCreate.

    Общие поля пакета (project_id/line_id/document_revision_id/created_by/системные/
    workflow/версии/audit) внутри строки запрещены (`extra="forbid"`).
    """

    model_config = ConfigDict(extra="forbid")

    joint_no: str = Field(min_length=1, max_length=100)

    @field_validator("joint_no")
    @classmethod
    def _joint_no_not_blank(cls, v: str) -> str:
        return _reject_blank_keep_original(v)

    @model_validator(mode="after")
    def _validate_coordinates(self) -> "JointBulkItem":
        if (
            self.position_x is not None or self.position_y is not None
        ) and self.coordinate_system is None:
            raise ValueError(
                "coordinate_system обязателен при заданных position_x/position_y"
            )
        return self


class JointBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    line_id: UUID
    document_revision_id: UUID
    created_by: int = Field(gt=0)
    idempotency_key: str
    items: list[JointBulkItem] = Field(min_length=1, max_length=500)

    @field_validator("idempotency_key")
    @classmethod
    def _idempotency_key_trimmed(cls, v: str) -> str:
        """Хранится после trim; после обрезки длина 1..100 (§4 задания)."""
        stripped = v.strip()
        if not (1 <= len(stripped) <= 100):
            raise ValueError(
                "idempotency_key после trim должен содержать от 1 до 100 символов"
            )
        return stripped


class JointBulkResultItem(BaseModel):
    row_index: int
    id: UUID
    system_code: str
    joint_no: str


class JointBulkResponse(BaseModel):
    bulk_request_id: UUID
    project_id: UUID
    line_id: UUID
    document_revision_id: UUID
    created_by: int
    created_count: int
    items: list[JointBulkResultItem]


class JointBulkValidationError(BaseModel):
    """Одна ошибка бизнес-валидации пакета. Для общей ошибки `row_index` опущен в
    сериализованном JSON (не `null`) через `model_dump(exclude_none=True)`."""

    row_index: int | None = None
    field: str
    code: str
    message: str


# ── WeldOperation (Task 8A, ADR-012 / Session 005) ────────────────────────────
# Актор (created_by/updated_by/completed_by/cancelled_by) берётся ТОЛЬКО из
# X-User-Id (§15 задания), не из тела. sequence_no и lifecycle_status назначает
# система: клиент их не передаёт (extra="forbid" даёт 422 при попытке).


def _validate_time_range(started, finished) -> None:
    if started is not None and finished is not None and finished < started:
        raise ValueError("finished_at не может быть раньше started_at")


class WeldOperationCreate(BaseModel):
    """Создание черновика операции. Обязательны joint/этап/способ/дата/ответственный;
    фактический сварщик может быть задан позже, но обязателен для завершения."""

    model_config = ConfigDict(extra="forbid")

    joint_id: UUID
    responsible_worker_id: int = Field(gt=0)
    weld_stage: WeldStage
    welding_method: str = Field(min_length=1, max_length=50)
    performed_on: date

    actual_welder_id: UUID | None = None
    entered_stamp_code: str | None = Field(default=None, max_length=100)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    actual_wps_id: UUID | None = None
    welding_position: str | None = Field(default=None, max_length=50)
    shielding_gas: str | None = Field(default=None, max_length=100)
    back_purge: bool | None = None

    production_area_id: UUID | None = None
    production_area_text: str | None = None
    shift_ref: str | None = Field(default=None, max_length=100)
    shift_assignment_ref: str | None = Field(default=None, max_length=100)
    production_report_ref: str | None = Field(default=None, max_length=100)
    operation_note: str | None = None

    @field_validator("welding_method")
    @classmethod
    def _method_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)

    @model_validator(mode="after")
    def _validate_times(self) -> "WeldOperationCreate":
        _validate_time_range(self.started_at, self.finished_at)
        return self


class WeldOperationUpdate(BaseModel):
    """PATCH черновика: только поля производственного факта. Защищённые поля (id,
    joint_id, sequence_no, lifecycle_status, аудит, версия) отсутствуют — extra=
    "forbid" даёт 422. `expected_record_version` обязателен (optimistic locking)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)

    responsible_worker_id: int | None = Field(default=None, gt=0)
    weld_stage: WeldStage | None = None
    welding_method: str | None = Field(default=None, min_length=1, max_length=50)
    performed_on: date | None = None

    actual_welder_id: UUID | None = None
    entered_stamp_code: str | None = Field(default=None, max_length=100)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    actual_wps_id: UUID | None = None
    welding_position: str | None = Field(default=None, max_length=50)
    shielding_gas: str | None = Field(default=None, max_length=100)
    back_purge: bool | None = None

    production_area_id: UUID | None = None
    production_area_text: str | None = None
    shift_ref: str | None = Field(default=None, max_length=100)
    shift_assignment_ref: str | None = Field(default=None, max_length=100)
    production_report_ref: str | None = Field(default=None, max_length=100)
    operation_note: str | None = None

    @field_validator("welding_method")
    @classmethod
    def _method_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _require_non_blank(v)

    @model_validator(mode="after")
    def _validate_times(self) -> "WeldOperationUpdate":
        _validate_time_range(self.started_at, self.finished_at)
        return self


class WeldOperationCompleteRequest(BaseModel):
    """Завершение операции. Данные заранее записаны через create/PATCH, поэтому
    тело несёт только опциональную ожидаемую версию (optimistic locking)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int | None = Field(default=None, gt=0)


class WeldOperationCancelRequest(BaseModel):
    """Отмена черновика: производственного факта не было. Причина обязательна."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    expected_record_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class WeldOperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    joint_id: UUID
    sequence_no: int
    lifecycle_status: WeldOperationStatus

    weld_stage: WeldStage
    welding_method: str
    performed_on: date
    started_at: datetime | None
    finished_at: datetime | None

    actual_welder_id: UUID | None
    entered_stamp_code: str | None
    profile_stamp_snapshot: str | None
    responsible_worker_id: int

    created_by: int
    created_at: datetime
    updated_by: int
    updated_at: datetime
    completed_by: int | None
    completed_at: datetime | None
    cancelled_by: int | None
    cancelled_at: datetime | None
    cancellation_reason: str | None

    executor_company_id: int | None
    executor_department_id: int | None
    welder_company_id: int | None
    welder_department_id: int | None

    production_area_id: UUID | None
    production_area_text: str | None
    shift_ref: str | None
    shift_assignment_ref: str | None
    production_report_ref: str | None

    actual_wps_id: UUID | None
    welding_position: str | None
    shielding_gas: str | None
    back_purge: bool | None
    operation_note: str | None

    record_version: int

    # ── Автоматическая проверка (Task 8B, §5, §11). Результаты допуска и WPS
    # хранятся раздельно; клиент их не задаёт через create/update/complete. ──────
    qualification_validation_status: QualificationValidationStatus
    qualification_validation_codes: list[str]
    qualification_admission_id: UUID | None
    qualification_snapshot: dict | None

    wps_validation_status: WpsValidationStatus
    wps_validation_codes: list[str]
    wps_validation_snapshot: dict | None

    validation_checked_at: datetime | None
    validation_source_version: int

    # ── Подтверждение сварщика и review ОГС (Task 8C, §4-5, §12). Независимые оси;
    # клиент их не задаёт через create/update/complete — только через команды. ────
    welder_confirmation_status: WelderConfirmationStatus
    welder_confirmation_version: int
    welder_confirmed_at: datetime | None
    welder_confirmed_by: int | None
    welder_confirmation_comment: str | None

    ogs_review_status: OgsReviewStatus
    ogs_review_version: int
    ogs_reviewed_at: datetime | None
    ogs_reviewed_by: int | None
    ogs_review_comment: str | None
    ogs_review_reason_codes: list[str]

    # ── Замена и переварка (Task 8D, §6). Клиент эти поля не задаёт — их выставляют
    # команды корректировки/переварки; трассировка predecessor/successor. ─────────
    supersedes_operation_id: UUID | None
    superseded_by_operation_id: UUID | None
    operation_kind: OperationKind
    reweld_reason: ReweldReason | None
    reweld_decision_comment: str | None
    reweld_decided_by: int | None
    reweld_decided_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def requires_ogs_review(self) -> bool:
        """Read-only признак: требуется ручное решение ОГС (§12). Однозначно
        вычисляется сервером из ogs_review_status; отдельной колонкой не хранится."""
        return self.ogs_review_status == "PENDING"


class WeldOperationValidateRequest(BaseModel):
    """Запуск/обновление автоматической проверки DRAFT (§10.3). Тело не требуется;
    опциональный expected_record_version сохраняет optimistic concurrency Task 8A."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int | None = Field(default=None, gt=0)


class WeldOperationListFilters(BaseModel):
    joint_id: UUID | None = None
    project_id: UUID | None = None
    line_id: UUID | None = None
    actual_welder_id: UUID | None = None
    responsible_worker_id: int | None = None
    lifecycle_status: WeldOperationStatus | None = None
    weld_stage: WeldStage | None = None
    welding_method: str | None = None
    qualification_validation_status: QualificationValidationStatus | None = None
    wps_validation_status: WpsValidationStatus | None = None
    welder_confirmation_status: WelderConfirmationStatus | None = None
    ogs_review_status: OgsReviewStatus | None = None
    performed_from: date | None = None
    performed_to: date | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class WeldOperationListResponse(BaseModel):
    items: list[WeldOperationRead]
    total: int
    limit: int
    offset: int


# ── Task 8C: команды подтверждения сварщика и review ОГС ──────────────────────
# Actor берётся только из X-User-Id (§6): actor-поля в теле запрещены. Optimistic
# concurrency разделена по независимым осям (§11): confirmation и review проверяют
# свою версию и производственную record_version.


class WelderConfirmCommand(BaseModel):
    """Подтверждение фактического сварщика мастером/прорабом (§10.1). Comment
    необязателен. Actor-поля в теле запрещены (extra="forbid")."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    expected_confirmation_version: int = Field(gt=0)
    comment: str | None = None


class WelderDisputeCommand(BaseModel):
    """Оспаривание сведений о сварщике (§10.2). Comment обязателен и непустой."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    expected_confirmation_version: int = Field(gt=0)
    comment: str = Field(min_length=1)

    @field_validator("comment")
    @classmethod
    def _comment_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class OgsReviewApproveCommand(BaseModel):
    """Принятие технологического факта ОГС (§10.3). reason_codes могут быть пусты
    при PASS/PASS; при FAIL/INDETERMINATE обязателен код-исключение (проверяет
    сервис). Неизвестные коды отклоняются схемой (§9)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    expected_review_version: int = Field(gt=0)
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    comment: str | None = None


class OgsReviewRejectCommand(BaseModel):
    """Отклонение технологического факта ОГС (§10.4). reason_codes обязателен и
    непуст; comment обязателен и непустой."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    expected_review_version: int = Field(gt=0)
    reason_codes: list[ReasonCode] = Field(min_length=1)
    comment: str = Field(min_length=1)

    @field_validator("comment")
    @classmethod
    def _comment_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class WeldOperationWelderConfirmationRead(BaseModel):
    """Запись истории подтверждения сварщика (§10.5), append-only."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    weld_operation_id: UUID
    decision: WelderConfirmationStatus
    previous_status: WelderConfirmationStatus
    confirmation_version: int
    comment: str | None
    decided_by: int
    decided_at: datetime
    created_at: datetime


class WeldOperationOgsReviewRead(BaseModel):
    """Запись истории review ОГС (§10.6), append-only, со снимком validation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    weld_operation_id: UUID
    decision: OgsReviewStatus
    previous_status: OgsReviewStatus
    review_version: int
    qualification_validation_status: QualificationValidationStatus
    qualification_validation_codes: list[str]
    wps_validation_status: WpsValidationStatus
    wps_validation_codes: list[str]
    reason_codes: list[str]
    comment: str | None
    decided_by: int
    decided_at: datetime
    created_at: datetime


# ── Task 8D: корректировки WeldOperation ──────────────────────────────────────
# Actor берётся только из X-User-Id (§18): actor-поля в теле запрещены. Снимки,
# changed_fields, field_changes и impact_level рассчитываются сервером — клиент их
# не передаёт (§8). patch несёт только разрешённые поля производственного факта.


class WeldOperationCorrectionCreate(BaseModel):
    """Создание корректировки завершённой операции (§11). Для CANCEL_FALSE_RECORD
    patch должен отсутствовать или быть пустым; для остальных типов — набор
    разрешённых полей. before/after снимки и diff формирует сервер."""

    model_config = ConfigDict(extra="forbid")

    correction_type: CorrectionType
    reason: str = Field(min_length=1)
    patch: dict | None = None
    expected_source_record_version: int = Field(gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class WeldOperationCorrectionUpdate(BaseModel):
    """PATCH черновика корректировки (§13.3): только для DRAFT. Меняются причина и
    разрешённый patch; сервер заново рассчитывает снимки, diff, impact и
    требования согласования, а прежние решения сбрасываются."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    reason: str | None = Field(default=None, min_length=1)
    patch: dict | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _require_reason(v)


class CorrectionVersionCommand(BaseModel):
    """Тело команды lifecycle без комментария: только ожидаемая версия (§13.4)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)


class CorrectionCommentCommand(BaseModel):
    """Команда lifecycle с обязательным непустым комментарием (return/reject)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    comment: str = Field(min_length=1)

    @field_validator("comment")
    @classmethod
    def _comment_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class CorrectionOptionalCommentCommand(BaseModel):
    """Команда lifecycle с необязательным комментарием (SMR approve)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    comment: str | None = None


class CorrectionOgsAcceptCommand(BaseModel):
    """Принятие корректировки ОГС (§13.8). Для ACCEPTED_WITH_REMARK комментарий
    обязателен (проверяет сервис)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    decision: Literal["ACCEPTED", "ACCEPTED_WITH_REMARK"] = "ACCEPTED"
    comment: str | None = None


class CorrectionCancelCommand(BaseModel):
    """Отмена корректировки до применения (§13.11). Причина обязательна."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        return _require_reason(v)


class CorrectionApplyCommand(BaseModel):
    """Атомарное применение корректировки (§15). Проверяет обе версии."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    expected_source_record_version: int = Field(gt=0)


class CorrectionRetryApplyCommand(BaseModel):
    """Ручной повтор применения после трёх неуспешных попыток (§15.5)."""

    model_config = ConfigDict(extra="forbid")

    expected_record_version: int = Field(gt=0)
    expected_source_record_version: int = Field(gt=0)


class WeldOperationCorrectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_operation_id: UUID
    replacement_operation_id: UUID | None
    correction_type: CorrectionType
    impact_level: ImpactLevel
    reason: str
    changed_fields: list[str]
    before_snapshot: dict
    after_snapshot: dict | None
    field_changes: dict
    source_type: SourceType
    lifecycle_status: CorrectionLifecycleStatus
    smr_approval_status: SmrApprovalStatus
    ogs_review_status: CorrectionOgsReviewStatus
    application_status: ApplicationStatus
    record_version: int

    created_by: int
    created_at: datetime
    updated_by: int
    updated_at: datetime
    submitted_by: int | None
    submitted_at: datetime | None
    smr_decided_by: int | None
    smr_decided_at: datetime | None
    smr_comment: str | None
    ogs_decided_by: int | None
    ogs_decided_at: datetime | None
    ogs_comment: str | None
    applied_by: int | None
    applied_at: datetime | None
    application_attempts: int
    last_application_error: str | None
    cancelled_by: int | None
    cancelled_at: datetime | None
    cancelled_reason: str | None


# ── Task 8D: полная переварка (reweld) ────────────────────────────────────────


class WeldOperationReweldCreate(BaseModel):
    """Создание черновика полной переварки (§16.2). Причина и комментарий
    обязательны; patch несёт данные новой операции поверх копии исходной."""

    model_config = ConfigDict(extra="forbid")

    reason: ReweldReason
    comment: str = Field(min_length=1)
    patch: dict | None = None
    expected_source_record_version: int = Field(gt=0)

    @field_validator("comment")
    @classmethod
    def _comment_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)


class WeldOperationReweldDecisionCommand(BaseModel):
    """Решение ОГС по переварке (§16.3): APPROVE или REJECT. Комментарий
    обязателен и непуст."""

    model_config = ConfigDict(extra="forbid")

    decision: ReweldDecision
    comment: str = Field(min_length=1)

    @field_validator("comment")
    @classmethod
    def _comment_not_blank(cls, v: str) -> str:
        return _require_non_blank(v)
