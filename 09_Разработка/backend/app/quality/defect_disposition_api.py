"""HTTP-слой DefectDisposition (Task 9D-4A-3/9D-4A-4, ADR-023).

Тонкий транспорт: маршрутизация, Pydantic, актор из `server-authenticated actor worker id`. Переходы статуса —
только через `POST …/transition` (команда `action`); прямого PATCH status нет.
`SUPERSEDE` (Task 9D-4A-4) — отдельный эндпойнт `POST …/supersede`, т.к. создаёт
новую версию (новую строку), а не только меняет статус текущей.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.quality.defect_disposition_schemas import (
    DefectDispositionCreateRequest,
    DefectDispositionEventRead,
    DefectDispositionRead,
    DefectDispositionSupersedeRequest,
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


@router.post(
    "/quality/defect-dispositions/{disposition_id}/supersede",
    response_model=DefectDispositionRead,
)
def supersede_disposition(
    disposition_id: UUID,
    payload: DefectDispositionSupersedeRequest,
    svc: DefectDispositionService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    """Открывает новую версию решения (Task 9D-4A-4): `ACTIVE → SUPERSEDED` + новая
    `DRAFT`. Возвращает новую версию; старая доступна по её собственному `GET`."""
    return svc.supersede(
        disposition_id,
        decision_type=payload.decision_type,
        justification=payload.justification,
        actor_worker_id=actor_worker_id,
        comment=payload.comment,
        reason=payload.supersede_reason,
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
