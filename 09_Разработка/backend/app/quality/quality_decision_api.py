"""Thin HTTP command layer for QualityDecision (Task 10A-3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.quality.quality_decision_schemas import (
    QualityDecisionBasisRead,
    QualityDecisionCreate,
    QualityDecisionDecideCommand,
    QualityDecisionDraftUpdate,
    QualityDecisionEventRead,
    QualityDecisionRead,
    QualityDecisionReturnCommand,
    QualityDecisionVersionCommand,
)
from app.quality.quality_decision_services import QualityDecisionService
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(tags=["quality-decisions"])
_BASE = "/quality/quality-decisions"


def _service(db: Session = Depends(get_db)) -> QualityDecisionService:
    return QualityDecisionService(db)


def _idempotency_key(
    value: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
    ),
) -> str:
    return value


@router.post(_BASE, response_model=QualityDecisionRead, status_code=201)
def create_quality_decision(
    data: QualityDecisionCreate,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
    idempotency_key: str = Depends(_idempotency_key),
):
    return service.create(
        joint_id=data.joint_id,
        basis_revision_ids=data.basis_revision_ids,
        summary=data.summary,
        actor_worker_id=actor_worker_id,
        idempotency_key=idempotency_key,
    )


@router.get(f"{_BASE}/{{decision_id}}", response_model=QualityDecisionRead)
def get_quality_decision(
    decision_id: UUID,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return service.get(decision_id, actor_worker_id=actor_worker_id)


@router.get(
    f"{_BASE}/{{decision_id}}/bases",
    response_model=list[QualityDecisionBasisRead],
)
def list_quality_decision_bases(
    decision_id: UUID,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return service.list_bases(decision_id, actor_worker_id=actor_worker_id)


@router.get(
    f"{_BASE}/{{decision_id}}/events",
    response_model=list[QualityDecisionEventRead],
)
def list_quality_decision_events(
    decision_id: UUID,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return service.list_audit_events(decision_id, actor_worker_id=actor_worker_id)


@router.patch(
    f"{_BASE}/{{decision_id}}/draft",
    response_model=QualityDecisionRead,
)
def update_quality_decision_draft(
    decision_id: UUID,
    data: QualityDecisionDraftUpdate,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
    idempotency_key: str = Depends(_idempotency_key),
):
    return service.update_draft(
        decision_id,
        expected_version=data.expected_version,
        summary=data.summary,
        basis_revision_ids=data.basis_revision_ids,
        actor_worker_id=actor_worker_id,
        idempotency_key=idempotency_key,
    )


@router.post(
    f"{_BASE}/{{decision_id}}/submit-for-review",
    response_model=QualityDecisionRead,
)
def submit_quality_decision_for_review(
    decision_id: UUID,
    data: QualityDecisionVersionCommand,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
    idempotency_key: str = Depends(_idempotency_key),
):
    return service.submit_for_review(
        decision_id,
        expected_version=data.expected_version,
        actor_worker_id=actor_worker_id,
        idempotency_key=idempotency_key,
    )


@router.post(
    f"{_BASE}/{{decision_id}}/return",
    response_model=QualityDecisionRead,
)
def return_quality_decision(
    decision_id: UUID,
    data: QualityDecisionReturnCommand,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
    idempotency_key: str = Depends(_idempotency_key),
):
    return service.return_to_draft(
        decision_id,
        expected_version=data.expected_version,
        return_reason=data.return_reason,
        actor_worker_id=actor_worker_id,
        idempotency_key=idempotency_key,
    )


@router.post(
    f"{_BASE}/{{decision_id}}/decide",
    response_model=QualityDecisionRead,
)
def decide_quality_decision(
    decision_id: UUID,
    data: QualityDecisionDecideCommand,
    service: QualityDecisionService = Depends(_service),
    actor_worker_id: int = Depends(get_current_user_id),
    idempotency_key: str = Depends(_idempotency_key),
):
    return service.decide(
        decision_id,
        expected_version=data.expected_version,
        decision_result=data.decision_result,
        actor_worker_id=actor_worker_id,
        idempotency_key=idempotency_key,
    )
