from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CompanyStatus = Literal["active", "inactive"]
ProjectStatus = Literal["draft", "active", "closed"]
ProjectCompanyRole = Literal[
    "CUSTOMER",
    "GENERAL_CONTRACTOR",
    "WELDING_CONTRACTOR",
    "NDT_LAB",
    "INSPECTION",
    "DESIGNER",
]

LineStatus = Literal["draft", "active", "cancelled"]

# Допустимые виды контроля (ADR-009 004-25). Снимок в required_inspection_types.
InspectionType = Literal[
    "VT",
    "RT",
    "UT",
    "PT",
    "MT",
    "HARDNESS",
    "PMI",
    "FERRITE",
]


def _reject_duplicate_inspection_types(value: list[str]) -> list[str]:
    """Дубликаты отклоняются, а не нормализуются молча: требования контроля должны
    быть однозначными (Task 3)."""
    if len(set(value)) != len(value):
        raise ValueError("required_inspection_types содержит повторяющиеся значения")
    return value


# ── Company ───────────────────────────────────────────────────────────────────


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=20)
    status: CompanyStatus = "active"


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    inn: str | None
    status: CompanyStatus
    created_by: int
    created_at: datetime


# ── Project ───────────────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    status: ProjectStatus = "draft"


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    status: ProjectStatus
    created_by: int
    created_at: datetime
    updated_at: datetime


# ── project_companies ─────────────────────────────────────────────────────────


class ProjectCompanyCreate(BaseModel):
    company_id: int = Field(gt=0)
    role_code: ProjectCompanyRole
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> "ProjectCompanyCreate":
        if (
            self.valid_to is not None
            and self.valid_from is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to не может быть раньше valid_from")
        return self


class ProjectCompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: UUID
    company_id: int
    role_code: ProjectCompanyRole
    valid_from: date
    valid_to: date | None


class ProjectListFilters(BaseModel):
    company_id: int | None = None
    role_code: ProjectCompanyRole | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


# ── Line ──────────────────────────────────────────────────────────────────────


class LineCreate(BaseModel):
    line_no: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=255)
    medium: str | None = Field(default=None, max_length=255)
    nominal_dn: Decimal | None = Field(default=None, gt=0)
    class_code: str | None = Field(default=None, max_length=50)
    category_code: str | None = Field(default=None, max_length=50)
    status: LineStatus = "draft"
    required_inspection_types: list[InspectionType] = Field(default_factory=list)

    @field_validator("required_inspection_types")
    @classmethod
    def _no_duplicate_inspection_types(cls, v: list[str]) -> list[str]:
        return _reject_duplicate_inspection_types(v)


class LineUpdate(BaseModel):
    line_no: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=255)
    medium: str | None = Field(default=None, max_length=255)
    nominal_dn: Decimal | None = Field(default=None, gt=0)
    class_code: str | None = Field(default=None, max_length=50)
    category_code: str | None = Field(default=None, max_length=50)
    status: LineStatus | None = None
    required_inspection_types: list[InspectionType] | None = None

    @field_validator("required_inspection_types")
    @classmethod
    def _no_duplicate_inspection_types(
        cls, v: list[str] | None
    ) -> list[str] | None:
        if v is None:
            return v
        return _reject_duplicate_inspection_types(v)


class LineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    line_no: str
    name: str | None
    medium: str | None
    nominal_dn: Decimal | None
    class_code: str | None
    category_code: str | None
    status: LineStatus
    required_inspection_types: list[str]
    created_by: int
    created_at: datetime
    updated_at: datetime
