"""HTTP-слой ядра EngineeringEvaluation (Task 9D-2D, ADR-021; Spec §10).

Маршруты монтируются под `/api/v1`. Namespace: `/quality/findings/{finding_id}/
engineering-evaluation` (оценка по finding) и `/quality/engineering-evaluation-
revisions/{id}` (ревизия и её дочерние сущности/переходы). Бизнес-действия — команды
(не универсальный PATCH статуса). Актор — из `X-User-Id`; RBAC/scope — в сервисе.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.quality.engineering_evaluation_schemas import (
    CheckReviewOverdueCommand,
    ConfirmReviewCommand,
    CriterionAddCommand,
    CriterionRead,
    CriterionUpdateCommand,
    EvaluationCreateCommand,
    EvaluationEventRead,
    EvaluationRead,
    ExceptionAddCommand,
    ExceptionRead,
    FixCommand,
    PrepareCommand,
    RequestReviewConfirmationCommand,
    RevisionCreateCommand,
    RevisionDetailRead,
    RevisionUpdateCommand,
    ReturnCommand,
    SetEffectiveCommand,
    SourceAddCommand,
    SourceRead,
    SourceReverifyCommand,
    WithdrawCommand,
)
from app.quality.engineering_evaluation_services import (
    EngineeringEvaluationService,
)
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(tags=["engineering-evaluation"])

_REV = "/quality/engineering-evaluation-revisions"


def _svc(db: Session = Depends(get_db)) -> EngineeringEvaluationService:
    return EngineeringEvaluationService(db)


# ── Оценка по finding ─────────────────────────────────────────────────────────


@router.post(
    "/quality/findings/{finding_id}/engineering-evaluation",
    response_model=RevisionDetailRead,
    status_code=201,
)
def create_evaluation(
    finding_id: UUID,
    data: EvaluationCreateCommand | None = None,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_evaluation(finding_id, actor_worker_id=uid)


@router.get(
    "/quality/findings/{finding_id}/engineering-evaluation",
    response_model=EvaluationRead,
)
def get_evaluation(
    finding_id: UUID,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_by_finding(finding_id, actor_worker_id=uid)


@router.post(
    "/quality/findings/{finding_id}/engineering-evaluation/revisions",
    response_model=RevisionDetailRead,
    status_code=201,
)
def create_revision(
    finding_id: UUID,
    data: RevisionCreateCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_revision(finding_id, data, actor_worker_id=uid)


# ── Ревизия: чтение / правка DRAFT ─────────────────────────────────────────────


@router.get(f"{_REV}/{{revision_id}}", response_model=RevisionDetailRead)
def get_revision(
    revision_id: UUID,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_revision(revision_id, actor_worker_id=uid)


@router.post(f"{_REV}/{{revision_id}}/update", response_model=RevisionDetailRead)
def update_revision(
    revision_id: UUID,
    data: RevisionUpdateCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_revision(revision_id, data, actor_worker_id=uid)


# ── Источники ──────────────────────────────────────────────────────────────────


@router.post(
    f"{_REV}/{{revision_id}}/sources", response_model=SourceRead, status_code=201
)
def add_source(
    revision_id: UUID,
    data: SourceAddCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_source(revision_id, data, actor_worker_id=uid)


@router.delete(f"{_REV}/{{revision_id}}/sources/{{source_id}}", status_code=204)
def remove_source(
    revision_id: UUID,
    source_id: UUID,
    expected_version: int = Query(...),
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    svc.remove_source(revision_id, source_id, expected_version, actor_worker_id=uid)
    return Response(status_code=204)


@router.post(
    f"{_REV}/{{revision_id}}/reverify-sources",
    response_model=RevisionDetailRead,
)
def reverify_sources(
    revision_id: UUID,
    data: SourceReverifyCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.reverify_sources(revision_id, data, actor_worker_id=uid)


# ── Критерии ───────────────────────────────────────────────────────────────────


@router.post(
    f"{_REV}/{{revision_id}}/criteria",
    response_model=CriterionRead,
    status_code=201,
)
def add_criterion(
    revision_id: UUID,
    data: CriterionAddCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_criterion(revision_id, data, actor_worker_id=uid)


@router.post(
    f"{_REV}/{{revision_id}}/criteria/{{criterion_id}}/update",
    response_model=CriterionRead,
)
def update_criterion(
    revision_id: UUID,
    criterion_id: UUID,
    data: CriterionUpdateCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_criterion(revision_id, criterion_id, data, actor_worker_id=uid)


@router.delete(
    f"{_REV}/{{revision_id}}/criteria/{{criterion_id}}", status_code=204
)
def remove_criterion(
    revision_id: UUID,
    criterion_id: UUID,
    expected_version: int = Query(...),
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    svc.remove_criterion(
        revision_id, criterion_id, expected_version, actor_worker_id=uid
    )
    return Response(status_code=204)


# ── Исключения ─────────────────────────────────────────────────────────────────


@router.post(
    f"{_REV}/{{revision_id}}/exceptions",
    response_model=ExceptionRead,
    status_code=201,
)
def add_exception(
    revision_id: UUID,
    data: ExceptionAddCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_exception(revision_id, data, actor_worker_id=uid)


@router.delete(
    f"{_REV}/{{revision_id}}/exceptions/{{exception_id}}", status_code=204
)
def remove_exception(
    revision_id: UUID,
    exception_id: UUID,
    expected_version: int = Query(...),
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    svc.remove_exception(
        revision_id, exception_id, expected_version, actor_worker_id=uid
    )
    return Response(status_code=204)


# ── Lifecycle-команды ──────────────────────────────────────────────────────────


@router.post(f"{_REV}/{{revision_id}}/prepare", response_model=RevisionDetailRead)
def prepare(
    revision_id: UUID,
    data: PrepareCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.prepare(revision_id, data, actor_worker_id=uid)


@router.post(f"{_REV}/{{revision_id}}/return", response_model=RevisionDetailRead)
def return_revision(
    revision_id: UUID,
    data: ReturnCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.return_revision(revision_id, data, actor_worker_id=uid)


@router.post(f"{_REV}/{{revision_id}}/fix", response_model=RevisionDetailRead)
def fix(
    revision_id: UUID,
    data: FixCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.fix(revision_id, data, actor_worker_id=uid)


@router.post(
    f"{_REV}/{{revision_id}}/set-effective", response_model=RevisionDetailRead
)
def set_effective(
    revision_id: UUID,
    data: SetEffectiveCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.set_effective(revision_id, data, actor_worker_id=uid)


@router.post(f"{_REV}/{{revision_id}}/withdraw", response_model=RevisionDetailRead)
def withdraw(
    revision_id: UUID,
    data: WithdrawCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.withdraw(revision_id, data, actor_worker_id=uid)


@router.post(
    f"{_REV}/{{revision_id}}/request-review-confirmation",
    response_model=RevisionDetailRead,
)
def request_review_confirmation(
    revision_id: UUID,
    data: RequestReviewConfirmationCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.request_review_confirmation(revision_id, data, actor_worker_id=uid)


@router.post(
    f"{_REV}/{{revision_id}}/confirm-review", response_model=RevisionDetailRead
)
def confirm_review(
    revision_id: UUID,
    data: ConfirmReviewCommand,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.confirm_review(revision_id, data, actor_worker_id=uid)


@router.post(
    f"{_REV}/{{revision_id}}/check-review-overdue",
    response_model=RevisionDetailRead,
)
def check_review_overdue(
    revision_id: UUID,
    data: CheckReviewOverdueCommand | None = None,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.check_review_overdue(
        revision_id, data or CheckReviewOverdueCommand(), actor_worker_id=uid
    )


# ── События (append-only) ──────────────────────────────────────────────────────


@router.get(
    "/quality/engineering-evaluations/{evaluation_id}/events",
    response_model=list[EvaluationEventRead],
)
def list_events(
    evaluation_id: UUID,
    svc: EngineeringEvaluationService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_events(evaluation_id, actor_worker_id=uid)
