from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.hr.schemas import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    EmploymentStatus,
    PositionCreate,
    PositionOut,
    PositionUpdate,
    WorkerCard,
    WorkerCreate,
    WorkerDismiss,
    WorkerListFilters,
    WorkerOut,
    WorkerUpdate,
)
from app.hr.services import HrService, to_worker_card, to_worker_out
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(prefix="/hr", tags=["hr"])


def _svc(db: Session = Depends(get_db)) -> HrService:
    return HrService(db)


# ── Подразделения ────────────────────────────────────────────────────────────

@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(
    company_id: int | None = None,
    is_active: bool | None = True,
    skip: int = 0,
    limit: int = 200,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_departments(
        company_id=company_id,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(
    data: DepartmentCreate,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.create_department(data)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    data: DepartmentUpdate,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_department(department_id, data)


# ── Должности ────────────────────────────────────────────────────────────────

@router.get("/positions", response_model=list[PositionOut])
def list_positions(
    is_active: bool | None = True,
    skip: int = 0,
    limit: int = 200,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_positions(is_active=is_active, skip=skip, limit=limit)


@router.post("/positions", response_model=PositionOut, status_code=201)
def create_position(
    data: PositionCreate,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.create_position(data)


@router.patch("/positions/{position_id}", response_model=PositionOut)
def update_position(
    position_id: int,
    data: PositionUpdate,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_position(position_id, data)


# ── Работники ────────────────────────────────────────────────────────────────

@router.get("/workers", response_model=list[WorkerOut])
def list_workers(
    company_id: int | None = None,
    department_id: int | None = None,
    position_id: int | None = None,
    employment_status: EmploymentStatus | None = None,
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    filters = WorkerListFilters(
        company_id=company_id,
        department_id=department_id,
        position_id=position_id,
        employment_status=employment_status,
        search=search,
        skip=skip,
        limit=limit,
    )
    workers = svc.list_workers(filters)
    return [to_worker_out(w) for w in workers]


@router.post("/workers", response_model=WorkerCard, status_code=201)
def create_worker(
    data: WorkerCreate,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return to_worker_card(svc.create_worker(data))


@router.get("/workers/{worker_id}", response_model=WorkerCard)
def get_worker(
    worker_id: int,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return to_worker_card(svc.get_worker(worker_id))


@router.patch("/workers/{worker_id}", response_model=WorkerCard)
def update_worker(
    worker_id: int,
    data: WorkerUpdate,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return to_worker_card(svc.update_worker(worker_id, data))


@router.post("/workers/{worker_id}/dismiss", response_model=WorkerCard)
def dismiss_worker(
    worker_id: int,
    data: WorkerDismiss,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return to_worker_card(svc.dismiss_worker(worker_id, data))


@router.post("/workers/{worker_id}/activate", response_model=WorkerCard)
def activate_worker(
    worker_id: int,
    svc: HrService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return to_worker_card(svc.activate_worker(worker_id))
