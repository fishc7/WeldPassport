from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.shared.auth import get_current_user_id
from app.shared.db import get_db
from app.welding.schemas import (
    WelderAdmissionCreate,
    WelderAdmissionRead,
    WelderAdmissionUpdate,
    WelderCreate,
    WelderRead,
    WelderUpdate,
)
from app.welding.services import WeldingService

router = APIRouter(prefix="/ogs", tags=["ogs"])


def _svc(db: Session = Depends(get_db)) -> WeldingService:
    return WeldingService(db)


@router.post("/welders", response_model=WelderRead, status_code=201)
def create_welder(
    data: WelderCreate,
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.create_welder(data)


@router.get("/welders", response_model=list[WelderRead])
def list_welders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_welders(skip=skip, limit=limit)


@router.get("/welders/{welder_id}", response_model=WelderRead)
def get_welder(
    welder_id: UUID,
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_welder(welder_id)


@router.patch("/welders/{welder_id}", response_model=WelderRead)
def update_welder(
    welder_id: UUID,
    data: WelderUpdate,
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_welder(welder_id, data)


@router.post(
    "/welder-admissions", response_model=WelderAdmissionRead, status_code=201
)
def create_welder_admission(
    data: WelderAdmissionCreate,
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.create_admission(data)


@router.get("/welder-admissions", response_model=list[WelderAdmissionRead])
def list_welder_admissions(
    worker_id: int | None = Query(default=None),
    stamp_code: str | None = Query(default=None),
    admission_status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_admissions(
        worker_id=worker_id,
        stamp_code=stamp_code,
        admission_status=admission_status,
        skip=skip,
        limit=limit,
    )


@router.get("/welder-admissions/{admission_id}", response_model=WelderAdmissionRead)
def get_welder_admission(
    admission_id: UUID,
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_admission(admission_id)


@router.patch("/welder-admissions/{admission_id}", response_model=WelderAdmissionRead)
def update_welder_admission(
    admission_id: UUID,
    data: WelderAdmissionUpdate,
    svc: WeldingService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_admission(admission_id, data)
