from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.engineering.schemas import (
    DocumentRevisionCreate,
    DocumentRevisionRead,
    DocumentType,
    EngineeringDocumentCreate,
    EngineeringDocumentListFilters,
    EngineeringDocumentRead,
    EngineeringStatus,
    GeometryType,
    JointCreate,
    JointListFilters,
    JointListResponse,
    JointRead,
    JointSortBy,
    JointUpdate,
    SortOrder,
    WeldJointType,
)
from app.engineering.services import EngineeringService, joint_to_read
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(prefix="/engineering", tags=["engineering"])


def _svc(db: Session = Depends(get_db)) -> EngineeringService:
    return EngineeringService(db)


# ── Документы ─────────────────────────────────────────────────────────────────


@router.post("/documents", response_model=EngineeringDocumentRead, status_code=201)
def create_document(
    data: EngineeringDocumentCreate,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_document(data, created_by=uid)


@router.get("/documents", response_model=list[EngineeringDocumentRead])
def list_documents(
    project_id: UUID | None = Query(default=None),
    line_id: UUID | None = Query(default=None),
    document_type: DocumentType | None = Query(default=None),
    status: EngineeringStatus | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    filters = EngineeringDocumentListFilters(
        project_id=project_id,
        line_id=line_id,
        document_type=document_type,
        status=status,
        skip=skip,
        limit=limit,
    )
    return svc.list_documents(filters)


# ── Ревизии по revision_id ────────────────────────────────────────────────────
# Статические пути /revisions/{revision_id} и /documents/{document_id} не
# конфликтуют: разные литеральные префиксы верхнего уровня.


@router.post(
    "/revisions/{revision_id}/approve", response_model=DocumentRevisionRead
)
def approve_revision(
    revision_id: UUID,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.approve_revision(revision_id, worker_id=uid)


@router.post(
    "/revisions/{revision_id}/cancel", response_model=DocumentRevisionRead
)
def cancel_revision(
    revision_id: UUID,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_revision(revision_id, worker_id=uid)


@router.post(
    "/revisions/{revision_id}/supersede", response_model=DocumentRevisionRead
)
def supersede_revision(
    revision_id: UUID,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.supersede_revision(revision_id, worker_id=uid)


# ── Документ: детали, переходы, ревизии ───────────────────────────────────────


@router.get("/documents/{document_id}", response_model=EngineeringDocumentRead)
def get_document(
    document_id: UUID,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_document(document_id)


@router.post(
    "/documents/{document_id}/approve", response_model=EngineeringDocumentRead
)
def approve_document(
    document_id: UUID,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.approve_document(document_id, worker_id=uid)


@router.post(
    "/documents/{document_id}/cancel", response_model=EngineeringDocumentRead
)
def cancel_document(
    document_id: UUID,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_document(document_id, worker_id=uid)


@router.post(
    "/documents/{document_id}/supersede", response_model=EngineeringDocumentRead
)
def supersede_document(
    document_id: UUID,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.supersede_document(document_id, worker_id=uid)


@router.post(
    "/documents/{document_id}/revisions",
    response_model=DocumentRevisionRead,
    status_code=201,
)
def create_revision(
    document_id: UUID,
    data: DocumentRevisionCreate,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_revision(document_id, data, created_by=uid)


@router.get(
    "/documents/{document_id}/revisions",
    response_model=list[DocumentRevisionRead],
)
def list_revisions(
    document_id: UUID,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_revisions(document_id)


# ── Стыки (Joint, Task 5A) ────────────────────────────────────────────────────


@router.post("/joints", response_model=JointRead, status_code=201)
def create_joint(
    data: JointCreate,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return joint_to_read(svc.create_joint(data))


@router.get("/joints", response_model=JointListResponse)
def list_joints(
    project_id: UUID | None = Query(default=None),
    line_id: UUID | None = Query(default=None),
    current_document_revision_id: UUID | None = Query(default=None),
    system_code: str | None = Query(default=None),
    joint_no: str | None = Query(default=None),
    geometry_type: GeometryType | None = Query(default=None),
    weld_joint_type: WeldJointType | None = Query(default=None),
    ready_for_welding: bool | None = Query(default=None),
    sort_by: JointSortBy = Query(default="created_at"),
    sort_order: SortOrder = Query(default="asc"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    filters = JointListFilters(
        project_id=project_id,
        line_id=line_id,
        current_document_revision_id=current_document_revision_id,
        system_code=system_code,
        joint_no=joint_no,
        geometry_type=geometry_type,
        weld_joint_type=weld_joint_type,
        ready_for_welding=ready_for_welding,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return svc.list_joints(filters)


@router.get("/joints/{joint_id}", response_model=JointRead)
def get_joint(
    joint_id: UUID,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return joint_to_read(svc.get_joint(joint_id))


@router.patch("/joints/{joint_id}", response_model=JointRead)
def update_joint(
    joint_id: UUID,
    data: JointUpdate,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return joint_to_read(svc.update_joint(joint_id, data))
