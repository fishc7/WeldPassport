from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

EmploymentStatus = Literal["active", "dismissed", "suspended"]


class DepartmentBase(BaseModel):
    company_id: int
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class DepartmentOut(DepartmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class PositionBase(BaseModel):
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True


class PositionCreate(PositionBase):
    pass


class PositionUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class PositionOut(PositionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CompanyRef(BaseModel):
    """Заглушка до появления модуля companies (ADR-001)."""

    id: int


class WorkerBase(BaseModel):
    personnel_number: str | None = Field(default=None, max_length=50)
    last_name: str = Field(min_length=1, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    birth_date: date | None = None
    company_id: int
    department_id: int | None = None
    position_id: int | None = None
    hire_date: date | None = None
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = None


class WorkerCreate(WorkerBase):
    pass


class WorkerUpdate(BaseModel):
    # TODO(ADR-001): ограничить смену company_id правилами модуля организаций.
    company_id: int | None = None
    personnel_number: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    birth_date: date | None = None
    department_id: int | None = None
    position_id: int | None = None
    hire_date: date | None = None
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = None


class WorkerDismiss(BaseModel):
    dismissal_date: date | None = None
    note: str | None = None


class WorkerOut(WorkerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employment_status: EmploymentStatus
    dismissal_date: date | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        return " ".join(parts)


class WorkerCard(WorkerOut):
    department: DepartmentOut | None = None
    position: PositionOut | None = None
    company: CompanyRef


class WorkerListFilters(BaseModel):
    company_id: int | None = None
    department_id: int | None = None
    position_id: int | None = None
    employment_status: EmploymentStatus | None = None
    search: str | None = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("search")
    @classmethod
    def strip_search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
