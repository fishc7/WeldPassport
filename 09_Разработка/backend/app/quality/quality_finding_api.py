"""HTTP-слой ядра QualityFinding (Task 9D-1, ADR-019).

Маршруты монтируются под /api/v1. В отличие от Task 9A (пустой prefix для
inspections), для нового ресурса используется явный namespace `/quality/findings`
согласно ТЗ 9D-1; список по стыку — под `/joints/{joint_id}/quality-findings`.

Бизнес-действия оформлены командами (`register`/`acknowledge`/`cancel`), а не
универсальным PATCH статуса (п.5 доменных правил: переходы — команды с проверкой
условий). Актор — из X-User-Id; RBAC/scope проверяются на backend в сервисе.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.quality.quality_finding_schemas import (
    AcknowledgeFindingCommand,
    CancelFindingCommand,
    DeleteFindingCommand,
    FindingCreate,
    FindingEventRead,
    FindingListFilters,
    FindingListResponse,
    FindingRead,
    RegisterFindingCommand,
    FindingUpdate,
)
from app.quality.quality_finding_services import QualityFindingService
from app.quality.quality_finding_workflow import (
    FindingInitialRisk,
    FindingOriginType,
    FindingStatus,
)
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(tags=["quality-findings"])


def _svc(db: Session = Depends(get_db)) -> QualityFindingService:
    return QualityFindingService(db)


# ── Создание ────────────────────────────────────────────────────────────────────


@router.post("/quality/findings", response_model=FindingRead, status_code=201)
def create_finding(
    data: FindingCreate,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_finding(data, actor_worker_id=uid)


# ── Список ────────────────────────────────────────────────────────────────────────


@router.get("/quality/findings", response_model=FindingListResponse)
def list_findings(
    project_id: UUID | None = Query(default=None),
    joint_id: UUID | None = Query(default=None),
    status: FindingStatus | None = Query(default=None),
    origin_type: FindingOriginType | None = Query(default=None),
    initial_risk: FindingInitialRisk | None = Query(default=None),
    system_code: str | None = Query(default=None),
    external_no: str | None = Query(default=None),
    created_by_worker_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    filters = FindingListFilters(
        project_id=project_id,
        joint_id=joint_id,
        status=status,
        origin_type=origin_type,
        initial_risk=initial_risk,
        system_code=system_code,
        external_no=external_no,
        created_by_worker_id=created_by_worker_id,
        limit=limit,
        offset=offset,
    )
    return svc.list_findings(filters, actor_worker_id=uid)


# ── Получение одного finding ──────────────────────────────────────────────────────


@router.get("/quality/findings/{finding_id}", response_model=FindingRead)
def get_finding(
    finding_id: UUID,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_finding(finding_id, actor_worker_id=uid)


# ── Редактирование DRAFT ──────────────────────────────────────────────────────────


@router.patch("/quality/findings/{finding_id}", response_model=FindingRead)
def update_finding(
    finding_id: UUID,
    data: FindingUpdate,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_finding(finding_id, data, actor_worker_id=uid)


# ── Регистрация DRAFT → REGISTERED ────────────────────────────────────────────────


@router.post("/quality/findings/{finding_id}/register", response_model=FindingRead)
def register_finding(
    finding_id: UUID,
    data: RegisterFindingCommand,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.register_finding(finding_id, data, actor_worker_id=uid)


# ── Подтверждение получения ОГС: REGISTERED → UNDER_EVALUATION ────────────────────


@router.post("/quality/findings/{finding_id}/acknowledge", response_model=FindingRead)
def acknowledge_finding(
    finding_id: UUID,
    data: AcknowledgeFindingCommand,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.acknowledge_finding(finding_id, data, actor_worker_id=uid)


# ── Отмена ────────────────────────────────────────────────────────────────────────


@router.post("/quality/findings/{finding_id}/cancel", response_model=FindingRead)
def cancel_finding(
    finding_id: UUID,
    data: CancelFindingCommand,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_finding(finding_id, data, actor_worker_id=uid)


# ── Удаление DRAFT (физическое) ───────────────────────────────────────────────────


@router.delete("/quality/findings/{finding_id}", status_code=204)
def delete_finding(
    finding_id: UUID,
    expected_version: int = Query(...),
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    svc.delete_finding(
        finding_id,
        DeleteFindingCommand(expected_version=expected_version),
        actor_worker_id=uid,
    )
    return Response(status_code=204)


# ── События ───────────────────────────────────────────────────────────────────────


@router.get(
    "/quality/findings/{finding_id}/events",
    response_model=list[FindingEventRead],
)
def list_finding_events(
    finding_id: UUID,
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_events(finding_id, actor_worker_id=uid)


# ── Список finding по стыку ───────────────────────────────────────────────────────


@router.get(
    "/joints/{joint_id}/quality-findings", response_model=FindingListResponse
)
def list_joint_findings(
    joint_id: UUID,
    status: FindingStatus | None = Query(default=None),
    origin_type: FindingOriginType | None = Query(default=None),
    initial_risk: FindingInitialRisk | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: QualityFindingService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    filters = FindingListFilters(
        status=status,
        origin_type=origin_type,
        initial_risk=initial_risk,
        limit=limit,
        offset=offset,
    )
    return svc.list_by_joint(joint_id, filters, actor_worker_id=uid)
