from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

WelderStatus = Literal["active", "inactive", "suspended"]


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
