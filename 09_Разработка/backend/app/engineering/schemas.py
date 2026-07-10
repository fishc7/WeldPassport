from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentType = Literal["ISOMETRIC", "DRAWING", "WELD_MAP", "OTHER"]
EngineeringStatus = Literal["DRAFT", "APPROVED", "CANCELLED", "SUPERSEDED"]


def _require_non_blank(value: str) -> str:
    """Обязательное непустое значение: пробельные строки отклоняются (422)."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("значение не может быть пустым")
    return stripped


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
