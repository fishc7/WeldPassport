from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.shared.auth import get_current_user_id
from app.shared.db import get_db
from app.welding.schemas import WelderCreate, WelderRead, WelderUpdate
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
