"""Pydantic-схемы лабораторного заключения (Task 9C, блок 9C-6A).

Только схемы (без API). Pydantic v2, `extra="forbid"` на входных моделях; UUID-типы;
`expected_version` в изменяющих командах; отдельные response-модели через
`from_attributes`. ORM наружу не выносится; `DomainError` — на границе service/API.

Actor-разделение: внутренние `*_by_worker_id` (Integer, server-authenticated actor worker id, вне тела);
внешние лица лаборатории — `*_person_id` (UUID `QualityExternalPerson`).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.quality.execution_schemas import VersionedCommand, _ForbidModel, _ReadModel
from app.quality.laboratory_conclusion_workflow import (
    AccreditationStatus,
    ConclusionStatus,
)
from app.quality.method_assignment_workflow import InspectionMethodCode


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("Значение не может быть пустым")
    return value


# ── Создание (§2) ──────────────────────────────────────────────────────────────


class ConclusionCreate(_ForbidModel):
    project_id: UUID
    laboratory_company_id: int
    inspection_method_id: InspectionMethodCode
    conclusion_number: str | None = None
    conclusion_year: int | None = None
    request_reference: str | None = None
    request_date: date | None = None
    requesting_company_id: int | None = None
    laboratory_accreditation_id: UUID | None = None
    lab_approver_person_id: UUID | None = None
    issued_by_person_id: UUID | None = None
    external_revision_label: str | None = None
    source_type: str | None = None
    source_reference: str | None = None


# ── Состав (§3) ────────────────────────────────────────────────────────────────


class AddConclusionExecutionCommand(_ForbidModel):
    method_execution_id: UUID


# ── Команды lifecycle (§4) ─────────────────────────────────────────────────────


class PrepareConclusionCommand(VersionedCommand):
    pass


class ApproveConclusionCommand(VersionedCommand):
    lab_approver_person_id: UUID | None = None


class IssueConclusionCommand(VersionedCommand):
    conclusion_number: str | None = None
    conclusion_year: int | None = None
    issued_at: datetime | None = None
    issued_by_person_id: UUID | None = None


class CancelConclusionCommand(VersionedCommand):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _non_empty(value)


class CreateConclusionRevisionCommand(VersionedCommand):
    correction_reason: str
    conclusion_number: str | None = None

    @field_validator("correction_reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        return _non_empty(value)


# ── Response ───────────────────────────────────────────────────────────────────


class ConclusionRead(_ReadModel):
    id: UUID
    project_id: UUID
    laboratory_company_id: int
    inspection_method_id: InspectionMethodCode

    root_conclusion_id: UUID
    revision_no: int
    supersedes_conclusion_id: UUID | None
    is_current: bool
    external_revision_label: str | None
    correction_reason: str | None

    conclusion_number: str | None
    normalized_conclusion_number: str | None
    conclusion_year: int | None
    issued_at: datetime | None

    request_reference: str | None
    request_date: date | None
    requesting_company_id: int | None

    laboratory_accreditation_id: UUID | None
    laboratory_name_snapshot: str | None
    accreditation_number_snapshot: str | None
    accreditation_valid_from_snapshot: date | None
    accreditation_valid_until_snapshot: date | None
    accreditation_scope_snapshot: str | None

    lab_approver_person_id: UUID | None
    issued_by_person_id: UUID | None

    source_type: str | None
    source_reference: str | None
    source_received_at: datetime | None

    status: ConclusionStatus

    lab_approved_by_worker_id: int | None
    lab_approved_at: datetime | None
    registered_by_worker_id: int | None
    registered_at: datetime | None

    cancellation_reason: str | None
    cancelled_by_worker_id: int | None
    cancelled_at: datetime | None

    revision_review_required: bool
    revision_review_reason: str | None

    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int


class ConclusionExecutionRead(_ReadModel):
    id: UUID
    laboratory_conclusion_id: UUID
    method_execution_id: UUID
    created_by_worker_id: int
    created_at: datetime


class ConclusionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    project_id: UUID
    items: list[ConclusionRead]


class ConclusionRevisionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    root_conclusion_id: UUID
    items: list[ConclusionRead]


class AccreditationRead(_ReadModel):
    id: UUID
    company_id: int
    certificate_number: str
    valid_from: date
    valid_until: date | None
    accreditation_scope: str | None
    status: AccreditationStatus
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
