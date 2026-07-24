"""Pydantic contracts for the Task 10A QualityDecision command API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityDecisionCreate(_Command):
    joint_id: UUID
    basis_revision_ids: list[UUID] = Field(min_length=1)
    summary: str | None = None


class QualityDecisionDraftUpdate(_Command):
    expected_version: int = Field(ge=1)
    summary: str | None = None
    basis_revision_ids: list[UUID] | None = Field(default=None, min_length=1)


class QualityDecisionVersionCommand(_Command):
    expected_version: int = Field(ge=1)


class QualityDecisionReturnCommand(QualityDecisionVersionCommand):
    return_reason: str = Field(min_length=1)


class QualityDecisionDecideCommand(QualityDecisionVersionCommand):
    decision_result: Literal["ACCEPTED", "NOT_CONFIRMED", "DEFECT_CONFIRMED"]


class QualityDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    joint_id: UUID
    system_code: str
    status: str
    decision_result: str | None
    summary: str | None
    return_reason: str | None
    supersedes_quality_decision_id: UUID | None
    created_by_worker_id: int
    created_at: datetime
    approved_by_worker_id: int | None
    approved_at: datetime | None
    approved_role: str | None
    version: int


class QualityDecisionBasisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    quality_decision_id: UUID
    engineering_evaluation_revision_id: UUID
    is_basis_of_decided: bool
    linked_by_worker_id: int
    linked_at: datetime


class QualityDecisionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    event_type: str
    changed_fields: dict | None
    previous_values: dict | None
    new_values: dict | None
    reason: str | None
    actor_worker_id: int
    occurred_at: datetime
