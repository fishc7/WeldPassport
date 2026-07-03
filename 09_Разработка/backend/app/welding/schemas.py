from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

WelderStatus = Literal["active", "inactive", "suspended"]
AdmissionStatus = Literal["draft", "active", "suspended", "expired", "revoked"]


class WelderCreate(BaseModel):
    worker_id: int = Field(gt=0)
    stamp_code: str = Field(min_length=1)
    status: WelderStatus = "active"
    notes: str | None = None


class WelderUpdate(BaseModel):
    stamp_code: str | None = Field(default=None, min_length=1)
    status: WelderStatus | None = None
    notes: str | None = None


class WelderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    worker_id: int
    stamp_code: str
    status: WelderStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


def check_admission_ranges(
    diameter_min: Decimal | None,
    diameter_max: Decimal | None,
    thickness_min: Decimal | None,
    thickness_max: Decimal | None,
    valid_from: date | None,
    valid_until: date | None,
) -> None:
    if diameter_min is not None and diameter_max is not None and diameter_min > diameter_max:
        raise ValueError("diameter_min не может быть больше diameter_max")
    if (
        thickness_min is not None
        and thickness_max is not None
        and thickness_min > thickness_max
    ):
        raise ValueError("thickness_min не может быть больше thickness_max")
    if (
        valid_until is not None
        and valid_from is not None
        and valid_until < valid_from
    ):
        raise ValueError("valid_until не может быть раньше valid_from")


class WelderAdmissionCreate(BaseModel):
    worker_id: int = Field(gt=0)
    stamp_code: str = Field(min_length=1)
    admission_status: AdmissionStatus = "draft"
    welding_methods: list[str] = Field(default_factory=list)
    material_groups: list[str] = Field(default_factory=list)
    diameter_min: Decimal | None = None
    diameter_max: Decimal | None = None
    thickness_min: Decimal | None = None
    thickness_max: Decimal | None = None
    valid_from: date
    valid_until: date | None = None
    basis_document: str | None = None
    notes: str | None = None
    created_by: UUID | None = None

    @model_validator(mode="after")
    def _validate_ranges(self) -> "WelderAdmissionCreate":
        check_admission_ranges(
            self.diameter_min,
            self.diameter_max,
            self.thickness_min,
            self.thickness_max,
            self.valid_from,
            self.valid_until,
        )
        return self


class WelderAdmissionUpdate(BaseModel):
    stamp_code: str | None = Field(default=None, min_length=1)
    admission_status: AdmissionStatus | None = None
    welding_methods: list[str] | None = None
    material_groups: list[str] | None = None
    diameter_min: Decimal | None = None
    diameter_max: Decimal | None = None
    thickness_min: Decimal | None = None
    thickness_max: Decimal | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    basis_document: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_ranges(self) -> "WelderAdmissionUpdate":
        check_admission_ranges(
            self.diameter_min,
            self.diameter_max,
            self.thickness_min,
            self.thickness_max,
            self.valid_from,
            self.valid_until,
        )
        return self


class WelderAdmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    worker_id: int
    stamp_code: str
    admission_status: AdmissionStatus
    welding_methods: list[str]
    material_groups: list[str]
    diameter_min: Decimal | None
    diameter_max: Decimal | None
    thickness_min: Decimal | None
    thickness_max: Decimal | None
    valid_from: date
    valid_until: date | None
    basis_document: str | None
    notes: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
