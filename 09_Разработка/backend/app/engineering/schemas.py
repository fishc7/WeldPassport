from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DocumentType = Literal["ISOMETRIC", "DRAWING", "WELD_MAP", "OTHER"]
EngineeringStatus = Literal["DRAFT", "APPROVED", "CANCELLED", "SUPERSEDED"]

# ── Joint enums (Task 5A, ADR-010) ────────────────────────────────────────────
JointStatus = Literal["DRAFT"]
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
    version: int

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
