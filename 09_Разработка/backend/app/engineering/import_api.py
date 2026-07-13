"""HTTP-слой контура импорта (Task 8E, §15).

Идемпотентный ключ — заголовок `Idempotency-Key`; актор — `X-User-Id`. Все
write-команды проходят RBAC/scope/идемпотентность на уровне сервиса.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.engineering.import_schemas import (
    CancelGroupCommand,
    CancelSessionCommand,
    FileDownloadLink,
    ImportApplyAttemptRead,
    ImportGroupListResponse,
    ImportGroupRead,
    ImportParseAttemptRead,
    ImportProvenanceRead,
    ImportResolutionRead,
    ImportRowChangeRead,
    ImportRowListResponse,
    ImportRowRead,
    ImportSessionListResponse,
    ImportSessionRead,
    ImportStatusEventRead,
    RejectRowCommand,
    ResolutionCommand,
    ReturnGroupCommand,
    ReturnRowCommand,
    ReturnSessionCommand,
    RowEditCommand,
    SessionVersionCommand,
)
from app.engineering.import_services import ImportService
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(prefix="/engineering/imports", tags=["engineering-import"])


def _svc(db: Session = Depends(get_db)) -> ImportService:
    return ImportService(db)


def _idem(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return idempotency_key


# ══════════════════════════════════════════════════════════════════════════════
# Загрузка и разбор
# ══════════════════════════════════════════════════════════════════════════════
@router.post("", response_model=ImportSessionRead, status_code=201)
def upload_import(
    project_id: UUID = Form(...),
    file: UploadFile = File(...),
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    data = file.file.read()
    session = svc.upload(
        project_id=project_id,
        filename=file.filename or "import.xlsx",
        content_type=file.content_type,
        data=data,
        actor=uid,
        idempotency_key=idem,
    )
    return ImportSessionRead.model_validate(session)


@router.post("/{session_id}/reparse", response_model=ImportSessionRead)
def reparse_import(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportSessionRead.model_validate(
        svc.reparse(session_id, actor=uid, idempotency_key=idem)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Чтение
# ══════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=ImportSessionListResponse)
def list_imports(
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    items = svc.list_sessions(
        project_id=project_id, status=status, skip=skip, limit=limit
    )
    return ImportSessionListResponse(
        items=[ImportSessionRead.model_validate(s) for s in items]
    )


@router.get("/{session_id}", response_model=ImportSessionRead)
def get_import(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return ImportSessionRead.model_validate(svc.get_session(session_id))


@router.get("/{session_id}/rows", response_model=ImportRowListResponse)
def list_import_rows(
    session_id: UUID,
    status: str | None = Query(default=None),
    group_id: UUID | None = Query(default=None),
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    rows = svc.list_rows(session_id, status=status, group_id=group_id)
    return ImportRowListResponse(
        items=[ImportRowRead.model_validate(r) for r in rows]
    )


@router.get("/{session_id}/errors", response_model=ImportRowListResponse)
def list_import_errors(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    rows = svc.list_rows(session_id, only_conflicts=True)
    return ImportRowListResponse(
        items=[ImportRowRead.model_validate(r) for r in rows]
    )


@router.get("/{session_id}/groups", response_model=ImportGroupListResponse)
def list_import_groups(
    session_id: UUID,
    status: str | None = Query(default=None),
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    groups = svc.list_groups(session_id, status=status)
    return ImportGroupListResponse(
        items=[ImportGroupRead.model_validate(g) for g in groups]
    )


@router.get("/{session_id}/parse-attempts", response_model=list[ImportParseAttemptRead])
def list_parse_attempts(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return [
        ImportParseAttemptRead.model_validate(a)
        for a in svc.list_parse_attempts(session_id)
    ]


@router.get("/{session_id}/apply-attempts", response_model=list[ImportApplyAttemptRead])
def list_apply_attempts(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return [
        ImportApplyAttemptRead.model_validate(a)
        for a in svc.list_apply_attempts(session_id)
    ]


@router.get(
    "/{session_id}/status-events", response_model=list[ImportStatusEventRead]
)
def list_status_events(
    session_id: UUID,
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return [
        ImportStatusEventRead.model_validate(e)
        for e in svc.list_status_events(
            session_id, entity_type=entity_type, entity_id=entity_id
        )
    ]


@router.get("/{session_id}/provenance", response_model=list[ImportProvenanceRead])
def list_provenance(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return [
        ImportProvenanceRead.model_validate(p)
        for p in svc.list_provenance(session_id)
    ]


@router.get("/{session_id}/file-link", response_model=FileDownloadLink)
def get_file_link(
    session_id: UUID,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.download_link(session_id, uid)


@router.get(
    "/rows/{row_id}/changes", response_model=list[ImportRowChangeRead]
)
def list_row_changes(
    row_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return [
        ImportRowChangeRead.model_validate(c) for c in svc.list_row_changes(row_id)
    ]


@router.get(
    "/rows/{row_id}/resolutions", response_model=list[ImportResolutionRead]
)
def list_row_resolutions(
    row_id: UUID,
    svc: ImportService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return [
        ImportResolutionRead.model_validate(r) for r in svc.list_resolutions(row_id)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Команды над строкой
# ══════════════════════════════════════════════════════════════════════════════
@router.patch("/rows/{row_id}", response_model=ImportRowRead)
def edit_row(
    row_id: UUID,
    data: RowEditCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportRowRead.model_validate(
        svc.edit_row(row_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/rows/{row_id}/resolutions", response_model=ImportRowRead, status_code=201)
def resolve_row(
    row_id: UUID,
    data: ResolutionCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportRowRead.model_validate(
        svc.resolve_row(row_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/rows/{row_id}/reject", response_model=ImportRowRead)
def reject_row(
    row_id: UUID,
    data: RejectRowCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportRowRead.model_validate(
        svc.reject_row(row_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/rows/{row_id}/return", response_model=ImportRowRead)
def return_row(
    row_id: UUID,
    data: ReturnRowCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportRowRead.model_validate(
        svc.return_row(row_id, data, actor=uid, idempotency_key=idem)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Команды над группой
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/groups/{group_id}/cancel", response_model=ImportGroupRead)
def cancel_group(
    group_id: UUID,
    data: CancelGroupCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportGroupRead.model_validate(
        svc.cancel_group(group_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/groups/{group_id}/return-after-failed", response_model=ImportGroupRead)
def return_group_after_failed(
    group_id: UUID,
    data: ReturnGroupCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportGroupRead.model_validate(
        svc.return_group_after_failed(group_id, data, actor=uid, idempotency_key=idem)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Команды над сессией
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{session_id}/cancel", response_model=ImportSessionRead)
def cancel_session(
    session_id: UUID,
    data: CancelSessionCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportSessionRead.model_validate(
        svc.cancel_session(session_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/{session_id}/ready-for-apply", response_model=ImportSessionRead)
def to_ready_for_apply(
    session_id: UUID,
    data: SessionVersionCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportSessionRead.model_validate(
        svc.to_ready_for_apply(session_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/{session_id}/apply", response_model=ImportSessionRead)
def apply_import(
    session_id: UUID,
    data: SessionVersionCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportSessionRead.model_validate(
        svc.apply(session_id, data, actor=uid, idempotency_key=idem)
    )


@router.post("/{session_id}/return-after-apply-failed", response_model=ImportSessionRead)
def return_session_after_apply_failed(
    session_id: UUID,
    data: ReturnSessionCommand,
    svc: ImportService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
    idem: str | None = Depends(_idem),
):
    return ImportSessionRead.model_validate(
        svc.return_session_after_apply_failed(
            session_id, data, actor=uid, idempotency_key=idem
        )
    )
