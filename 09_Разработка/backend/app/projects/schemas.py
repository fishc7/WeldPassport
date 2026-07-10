from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
