from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.quality.schemas import (
    CancelInspectionCommand,
    CancelMethodAssignmentCommand,
    ConfirmProductionReadinessCommand,
    InspectionCreate,
    InspectionEventRead,
    InspectionListFilters,
    InspectionListResponse,
    InspectionRead,
    InspectionReadinessRead,
    InspectionUpdate,
    MethodAssignmentCreate,
    MethodAssignmentListResponse,
    MethodAssignmentRead,
    MethodAssignmentUpdate,
    ReplaceMethodAssignmentCommand,
    RequestInspectionCommand,
)
from app.quality.inspection_workflow import InspectionStatus
from app.quality.method_assignment_services import MethodAssignmentService
from app.quality.method_assignment_workflow import AssignmentStatus
from app.quality.services import InspectionService
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

# Пустой prefix: маршруты монтируются под /api/v1 (POST /api/v1/inspections,
# GET /api/v1/joints/{joint_id}/inspection-readiness) — вне /engineering (§16).
router = APIRouter(tags=["quality"])


def _svc(db: Session = Depends(get_db)) -> InspectionService:
    return InspectionService(db)


def _asvc(db: Session = Depends(get_db)) -> MethodAssignmentService:
    return MethodAssignmentService(db)


# ── Создание ───────────────────────────────────────────────────────────────────


@router.post("/inspections", response_model=InspectionRead, status_code=201)
def create_inspection(
    data: InspectionCreate,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return svc.create_inspection(
        data, actor_worker_id=uid, idempotency_key=idempotency_key
    )


# ── Список ──────────────────────────────────────────────────────────────────────


@router.get("/inspections", response_model=InspectionListResponse)
def list_inspections(
    project_id: UUID | None = Query(default=None),
    joint_id: UUID | None = Query(default=None),
    status: InspectionStatus | None = Query(default=None),
    system_code: str | None = Query(default=None),
    external_request_no: str | None = Query(default=None),
    created_by_worker_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    filters = InspectionListFilters(
        project_id=project_id,
        joint_id=joint_id,
        status=status,
        system_code=system_code,
        external_request_no=external_request_no,
        created_by_worker_id=created_by_worker_id,
        limit=limit,
        offset=offset,
    )
    return svc.list_inspections(filters, actor_worker_id=uid)


# ── Получение одной заявки ──────────────────────────────────────────────────────


@router.get("/inspections/{inspection_id}", response_model=InspectionRead)
def get_inspection(
    inspection_id: UUID,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_inspection(inspection_id, actor_worker_id=uid)


# ── Редактирование DRAFT ────────────────────────────────────────────────────────


@router.patch("/inspections/{inspection_id}", response_model=InspectionRead)
def update_inspection(
    inspection_id: UUID,
    data: InspectionUpdate,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_inspection(inspection_id, data, actor_worker_id=uid)


# ── Готовность стыка к контролю (ничего не изменяет) ────────────────────────────


@router.get(
    "/joints/{joint_id}/inspection-readiness",
    response_model=InspectionReadinessRead,
)
def joint_inspection_readiness(
    joint_id: UUID,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.readiness(joint_id, actor_worker_id=uid)


# ── Подтверждение производственной готовности СМР ───────────────────────────────


@router.post(
    "/inspections/{inspection_id}/confirm-production-readiness",
    response_model=InspectionRead,
)
def confirm_production_readiness(
    inspection_id: UUID,
    data: ConfirmProductionReadinessCommand,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.confirm_production_readiness(inspection_id, data, actor_worker_id=uid)


# ── Отправка заявки ─────────────────────────────────────────────────────────────


@router.post("/inspections/{inspection_id}/request", response_model=InspectionRead)
def request_inspection(
    inspection_id: UUID,
    data: RequestInspectionCommand,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.request_inspection(inspection_id, data, actor_worker_id=uid)


# ── Отмена ──────────────────────────────────────────────────────────────────────


@router.post("/inspections/{inspection_id}/cancel", response_model=InspectionRead)
def cancel_inspection(
    inspection_id: UUID,
    data: CancelInspectionCommand,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_inspection(inspection_id, data, actor_worker_id=uid)


# ── События ─────────────────────────────────────────────────────────────────────


@router.get(
    "/inspections/{inspection_id}/events",
    response_model=list[InspectionEventRead],
)
def list_inspection_events(
    inspection_id: UUID,
    svc: InspectionService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_events(inspection_id, actor_worker_id=uid)


# ── Task 9B: назначение методов контроля и лаборатории ──────────────────────────
# Prefix модуля quality (Task 9A) пустой — маршруты монтируются под /api/v1 без
# сегмента /quality; сохраняем существующий стиль (§16 «использовать текущий
# prefix»), а не пример /api/v1/quality/... из рекомендаций ТЗ.


@router.post(
    "/inspections/{inspection_id}/method-assignments",
    response_model=MethodAssignmentRead,
    status_code=201,
)
def create_method_assignment(
    inspection_id: UUID,
    data: MethodAssignmentCreate,
    svc: MethodAssignmentService = Depends(_asvc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_assignment(inspection_id, data, actor_worker_id=uid)


@router.get(
    "/inspections/{inspection_id}/method-assignments",
    response_model=MethodAssignmentListResponse,
)
def list_method_assignments(
    inspection_id: UUID,
    status: AssignmentStatus | None = Query(default=None),
    active_only: bool = Query(default=False),
    svc: MethodAssignmentService = Depends(_asvc),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_assignments(
        inspection_id,
        actor_worker_id=uid,
        status=status,
        active_only=active_only,
    )


@router.get(
    "/inspection-method-assignments/{assignment_id}",
    response_model=MethodAssignmentRead,
)
def get_method_assignment(
    assignment_id: UUID,
    svc: MethodAssignmentService = Depends(_asvc),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_assignment(assignment_id, actor_worker_id=uid)


@router.patch(
    "/inspection-method-assignments/{assignment_id}",
    response_model=MethodAssignmentRead,
)
def update_method_assignment(
    assignment_id: UUID,
    data: MethodAssignmentUpdate,
    svc: MethodAssignmentService = Depends(_asvc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_assignment(assignment_id, data, actor_worker_id=uid)


@router.post(
    "/inspection-method-assignments/{assignment_id}/cancel",
    response_model=MethodAssignmentRead,
)
def cancel_method_assignment(
    assignment_id: UUID,
    data: CancelMethodAssignmentCommand,
    svc: MethodAssignmentService = Depends(_asvc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_assignment(assignment_id, data, actor_worker_id=uid)


@router.post(
    "/inspection-method-assignments/{assignment_id}/replace",
    response_model=MethodAssignmentRead,
)
def replace_method_assignment(
    assignment_id: UUID,
    data: ReplaceMethodAssignmentCommand,
    svc: MethodAssignmentService = Depends(_asvc),
    uid: int = Depends(get_current_user_id),
):
    return svc.replace_assignment(assignment_id, data, actor_worker_id=uid)
