"""Pydantic-схемы HTTP-слоя DefectDisposition (Task 9D-4A-3, ADR-023).

Вход с `extra="forbid"`; актор — из `X-User-Id`, не из тела. Статус через API
напрямую не принимается: только команда `action` в transition. Доменные проверки —
в сервисе/policy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.quality.defect_disposition_workflow import DispositionAction, DispositionStatus

DecisionType = Literal[
    "REPAIR_REQUIRED",
    "REINSPECTION_REQUIRED",
    "ACCEPT_AS_IS",
    "REJECT_JOINT",
]


class DefectDispositionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defect_root_id: UUID
    decision_type: DecisionType
    justification: str = Field(min_length=1)
    comment: str | None = None


class DefectDispositionTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DispositionAction
    comment: str | None = None


class DefectDispositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    defect_root_id: UUID
    supersedes_disposition_id: UUID | None
    decision_type: str
    status: DispositionStatus
    justification: str
    comment: str | None
    supersede_reason: str | None
    created_by_worker_id: int
    created_at: datetime
    approved_by_worker_id: int | None
    approved_at: datetime | None


class DefectDispositionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    defect_disposition_id: UUID
    defect_root_id: UUID
    event_type: str
    action: str
    previous_status: str | None
    new_status: str | None
    actor_worker_id: int
    actor_role: str | None
    reason: str | None
    created_at: datetime
