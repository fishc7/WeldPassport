from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.projects.schemas import (
    CompanyCreate,
    CompanyRead,
    LineCreate,
    LineRead,
    LineUpdate,
    ProjectCompanyCreate,
    ProjectCompanyRead,
    ProjectCompanyRole,
    ProjectCreate,
    ProjectListFilters,
    ProjectRead,
)
from app.projects.services import ProjectService
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(prefix="/projects", tags=["projects"])


def _svc(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


# ── Организации (реестр) ──────────────────────────────────────────────────────
# Статические пути /companies объявлены раньше динамического /{project_id},
# чтобы не перехватываться как project_id.


@router.post("/companies", response_model=CompanyRead, status_code=201)
def create_company(
    data: CompanyCreate,
    svc: ProjectService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_company(data, created_by=uid)


@router.get("/companies", response_model=list[CompanyRead])
def list_companies(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: ProjectService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_companies(skip=skip, limit=limit)


# ── Проекты ───────────────────────────────────────────────────────────────────


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    data: ProjectCreate,
    svc: ProjectService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_project(data, created_by=uid)


@router.get("", response_model=list[ProjectRead])
def list_projects(
    company_id: int | None = Query(default=None),
    role_code: ProjectCompanyRole | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: ProjectService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    filters = ProjectListFilters(
        company_id=company_id,
        role_code=role_code,
        skip=skip,
        limit=limit,
    )
    return svc.list_projects(filters)


# ── Линии: детали по line_id ──────────────────────────────────────────────────
# Статические пути /lines/{line_id} объявлены раньше динамического /{project_id},
# иначе "lines" перехватывается как project_id (UUID) и даёт 422.


@router.get("/lines/{line_id}", response_model=LineRead)
def get_line(
    line_id: UUID,
    svc: ProjectService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_line(line_id)


@router.patch("/lines/{line_id}", response_model=LineRead)
def update_line(
    line_id: UUID,
    data: LineUpdate,
    svc: ProjectService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_line(line_id, data, updated_by=uid)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: UUID,
    svc: ProjectService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_project(project_id)


# ── Участие организаций в проекте ─────────────────────────────────────────────


@router.post(
    "/{project_id}/companies",
    response_model=ProjectCompanyRead,
    status_code=201,
)
def add_project_company(
    project_id: UUID,
    data: ProjectCompanyCreate,
    svc: ProjectService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_project_company(project_id, data, created_by=uid)


@router.get(
    "/{project_id}/companies",
    response_model=list[ProjectCompanyRead],
)
def list_project_companies(
    project_id: UUID,
    svc: ProjectService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_project_companies(project_id)


# ── Линии проекта ─────────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/lines",
    response_model=LineRead,
    status_code=201,
)
def create_line(
    project_id: UUID,
    data: LineCreate,
    svc: ProjectService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_line(project_id, data, created_by=uid)


@router.get(
    "/{project_id}/lines",
    response_model=list[LineRead],
)
def list_lines(
    project_id: UUID,
    svc: ProjectService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_lines(project_id)
