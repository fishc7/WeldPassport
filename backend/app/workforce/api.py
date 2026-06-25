from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import get_current_user_id
from app.shared.db import get_db
from app.workforce.schemas import (
    AttestatsiyaOut,
    DokumentOut,
    DopuskKObektuOut,
    RabotnikCreate,
    RabotnikOut,
    RabotnikUpdate,
    SvarshchikCreate,
    SvarshchikOut,
    SvarshchikUpdate,
    VnutrenniyDopuskOut,
)
from app.workforce.services import WorkforceService

router = APIRouter(tags=["workforce"])


def _svc(db: Session = Depends(get_db)) -> WorkforceService:
    return WorkforceService(db)


# ── Работники ────────────────────────────────────────────────────────────────

@router.get("/workers", response_model=list[RabotnikOut])
def list_workers(
    skip: int = 0,
    limit: int = 100,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_workers(skip, limit)


@router.get("/workers/{id}", response_model=RabotnikOut)
def get_worker(
    id: int,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_worker(id)


@router.post("/workers", response_model=RabotnikOut, status_code=201)
def create_worker(
    data: RabotnikCreate,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.create_worker(data)


@router.patch("/workers/{id}", response_model=RabotnikOut)
def update_worker(
    id: int,
    data: RabotnikUpdate,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_worker(id, data)


# ── Сварщики ─────────────────────────────────────────────────────────────────

@router.get("/welders", response_model=list[SvarshchikOut])
def list_welders(
    skip: int = 0,
    limit: int = 100,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_welders(skip, limit)


@router.get("/welders/{id}", response_model=SvarshchikOut)
def get_welder(
    id: int,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_welder(id)


@router.post("/welders", response_model=SvarshchikOut, status_code=201)
def create_welder(
    data: SvarshchikCreate,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.create_welder(data)


@router.patch("/welders/{id}", response_model=SvarshchikOut)
def update_welder(
    id: int,
    data: SvarshchikUpdate,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_welder(id, data)


@router.get("/welders/{id}/documents", response_model=list[DokumentOut])
def get_welder_documents(
    id: int,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_welder_documents(id)


@router.get("/welders/{id}/certifications", response_model=list[AttestatsiyaOut])
def get_welder_certifications(
    id: int,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_welder_certifications(id)


@router.get("/welders/{id}/admissions/internal", response_model=list[VnutrenniyDopuskOut])
def get_welder_internal_admissions(
    id: int,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_welder_internal_admissions(id)


@router.get("/welders/{id}/admissions/site", response_model=list[DopuskKObektuOut])
def get_welder_site_admissions(
    id: int,
    svc: WorkforceService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_welder_site_admissions(id)
