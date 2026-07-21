"""HTTP-слой DefectDisposition (Task 9D-4A-3, ADR-023).

Тонкий транспорт: маршрутизация, Pydantic, актор из `X-User-Id`. Переходы статуса —
только через `POST …/transition` (команда `action`); прямого PATCH status нет.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.quality.defect_disposition_schemas import (
    DefectDispositionCreateRequest,
    DefectDispositionEventRead,
    DefectDispositionRead,
    DefectDispositionTransitionRequest,
)
from app.quality.defect_disposition_services import DefectDispositionService
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(tags=["Quality — Defect Dispositions"])


def _svc(db: Session = Depends(get_db)) -> DefectDispositionService:
    return DefectDispositionService(db)


@router.post(
    "/quality/defect-dispositions",
    response_model=DefectDispositionRead,
    status_code=201,
)
def create_disposition(
    payload: DefectDispositionCreateRequest,
    svc: DefectDispositionService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.create(
        defect_root_id=payload.defect_root_id,
        decision_type=payload.decision_type,
        justification=payload.justification,
        actor_worker_id=actor_worker_id,
        comment=payload.comment,
    )


@router.get(
    "/quality/defect-dispositions/{disposition_id}",
    response_model=DefectDispositionRead,
)
def get_disposition(
    disposition_id: UUID,
    svc: DefectDispositionService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.get(disposition_id, actor_worker_id=actor_worker_id)


@router.post(
    "/quality/defect-dispositions/{disposition_id}/transition",
    response_model=DefectDispositionRead,
)
def transition_disposition(
    disposition_id: UUID,
    payload: DefectDispositionTransitionRequest,
    svc: DefectDispositionService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.transition(
        disposition_id,
        action=payload.action,
        actor_worker_id=actor_worker_id,
        comment=payload.comment,
    )


@router.get(
    "/quality/defect-dispositions/{disposition_id}/events",
    response_model=list[DefectDispositionEventRead],
)
def list_disposition_events(
    disposition_id: UUID,
    svc: DefectDispositionService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.list_events(disposition_id, actor_worker_id=actor_worker_id)
