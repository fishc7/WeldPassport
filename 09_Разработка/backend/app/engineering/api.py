from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.engineering.joint_bulk import JointBulkService
from app.engineering.schemas import (
    ApproveOgsCommand,
    ApprovePtoCommand,
    BlockCommand,
    CancelCommand,
    DocumentRevisionCreate,
    DocumentRevisionRead,
    DocumentRole,
    DocumentType,
    EngineeringDocumentCreate,
    EngineeringDocumentListFilters,
    EngineeringDocumentRead,
    EngineeringStatus,
    GeometryType,
    InvalidateLinkCommand,
    JointBlockRead,
    JointBulkCreate,
    JointBulkResponse,
    JointCreate,
    JointDocumentRevisionCreate,
    JointDocumentRevisionRead,
    JointEventRead,
    JointListFilters,
    JointListResponse,
    JointRead,
    JointSortBy,
    JointUpdate,
    LinkStatus,
    RejectCommand,
    RevisionRole,
    RevokeCommand,
    SetCurrentRevisionCommand,
    SortOrder,
    SubmitForReviewCommand,
    SupersedeCommand,
    UnblockCommand,
    WeldJointType,
)
from app.engineering.services import EngineeringService, joint_to_read
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(prefix="/engineering", tags=["engineering"])


def _svc(db: Session = Depends(get_db)) -> EngineeringService:
    return EngineeringService(db)


def _bulk_svc(db: Session = Depends(get_db)) -> JointBulkService:
    return JointBulkService(db)


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


# Маршрут /joints/bulk объявлен ДО динамического /joints/{joint_id}, чтобы строка
# "bulk" не интерпретировалась как UUID пути (§6 задания). Первый успех — 201;
# идемпотентный повтор — 200 (Response.status_code переопределяет default).
@router.post("/joints/bulk", response_model=JointBulkResponse, status_code=201)
def bulk_create_joints(
    data: JointBulkCreate,
    response: Response,
    svc: JointBulkService = Depends(_bulk_svc),
    uid: int = Depends(get_current_user_id),
):
    result = svc.create_bulk(payload=data, actor_worker_id=uid)
    if result.replayed:
        response.status_code = 200
    return result.response_payload


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
    uid: int = Depends(get_current_user_id),
):
    return svc.read_joint(joint_id, uid)


@router.patch("/joints/{joint_id}", response_model=JointRead)
def update_joint(
    joint_id: UUID,
    data: JointUpdate,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.update_joint(joint_id, data)


# ── Стыки: команды жизненного цикла (Task 5B, §7 ADR-011) ─────────────────────
# Актор — только из X-User-Id (§17 ADR-011); тело несёт причины/версии.


@router.post("/joints/{joint_id}/submit-for-review", response_model=JointRead)
def submit_for_review(
    joint_id: UUID,
    data: SubmitForReviewCommand = SubmitForReviewCommand(),
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.submit_for_review(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/approve-pto", response_model=JointRead)
def approve_pto(
    joint_id: UUID,
    data: ApprovePtoCommand = ApprovePtoCommand(),
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.approve_pto(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/reject-pto", response_model=JointRead)
def reject_pto(
    joint_id: UUID,
    data: RejectCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.reject_pto(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/revoke-pto", response_model=JointRead)
def revoke_pto(
    joint_id: UUID,
    data: RevokeCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.revoke_pto(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/approve-ogs", response_model=JointRead)
def approve_ogs(
    joint_id: UUID,
    data: ApproveOgsCommand = ApproveOgsCommand(),
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.approve_ogs(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/reject-ogs", response_model=JointRead)
def reject_ogs(
    joint_id: UUID,
    data: RejectCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.reject_ogs(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/revoke-ogs", response_model=JointRead)
def revoke_ogs(
    joint_id: UUID,
    data: RevokeCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.revoke_ogs(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/block", response_model=JointRead)
def block_joint(
    joint_id: UUID,
    data: BlockCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.block(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/unblock", response_model=JointRead)
def unblock_joint(
    joint_id: UUID,
    data: UnblockCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.unblock(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/cancel", response_model=JointRead)
def cancel_joint(
    joint_id: UUID,
    data: CancelCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel(joint_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/supersede", response_model=JointRead)
def supersede_joint(
    joint_id: UUID,
    data: SupersedeCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.supersede(joint_id, data, actor_worker_id=uid)


@router.get("/joints/{joint_id}/blocks", response_model=list[JointBlockRead])
def list_joint_blocks(
    joint_id: UUID,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_blocks(joint_id)


@router.get("/joints/{joint_id}/events", response_model=list[JointEventRead])
def list_joint_events(
    joint_id: UUID,
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_events(joint_id)


# ── Стыки: история связей с ревизиями (Task 6) ────────────────────────────────


@router.get(
    "/joints/{joint_id}/document-revisions",
    response_model=list[JointDocumentRevisionRead],
)
def list_joint_document_revisions(
    joint_id: UUID,
    link_status: LinkStatus | None = Query(default=None),
    document_role: DocumentRole | None = Query(default=None),
    revision_role: RevisionRole | None = Query(default=None),
    svc: EngineeringService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_revision_links(
        joint_id,
        link_status=link_status,
        document_role=document_role,
        revision_role=revision_role,
    )


@router.post(
    "/joints/{joint_id}/document-revisions",
    response_model=JointDocumentRevisionRead,
    status_code=201,
)
def create_joint_document_revision(
    joint_id: UUID,
    data: JointDocumentRevisionCreate,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_revision_link(joint_id, data, actor_worker_id=uid)


@router.post(
    "/joints/{joint_id}/document-revisions/{link_id}/invalidate",
    response_model=JointDocumentRevisionRead,
)
def invalidate_joint_document_revision(
    joint_id: UUID,
    link_id: UUID,
    data: InvalidateLinkCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.invalidate_link(joint_id, link_id, data, actor_worker_id=uid)


@router.post("/joints/{joint_id}/set-current-revision", response_model=JointRead)
def set_current_revision(
    joint_id: UUID,
    data: SetCurrentRevisionCommand,
    svc: EngineeringService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.set_current_revision(joint_id, data, actor_worker_id=uid)
