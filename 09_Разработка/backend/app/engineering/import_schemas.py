"""Pydantic-схемы контура импорта (Task 8E).

Идемпотентный ключ передаётся заголовком `Idempotency-Key` (единообразно для
multipart-загрузки и JSON-команд), поэтому в телах команд его нет. Команды несут
ожидаемые версии (optimistic locking) и обязательные комментарии там, где это
требует ТЗ.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.engineering import import_workflow as iw


# ══════════════════════════════════════════════════════════════════════════════
# Read-схемы
# ══════════════════════════════════════════════════════════════════════════════
class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ImportSessionRead(_ORMModel):
    id: UUID
    project_id: UUID
    template_version: str
    original_filename: str
    file_size_bytes: int
    mime_type: str
    file_sha256: str
    storage_object_key: str
    status: str
    duplicate_of_session_id: UUID | None
    record_version: int
    uploaded_by: int
    uploaded_at: datetime
    updated_at: datetime


class ImportRowRead(_ORMModel):
    id: UUID
    import_session_id: UUID
    row_number: int
    raw_snapshot: dict
    normalized_data: dict
    normalized_joint_no: str | None
    status: str
    error_codes: list
    conflict_codes: list
    duplicate_type: str | None
    match_classification: str | None
    matched_joint_id: UUID | None
    matched_weld_operation_id: UUID | None
    import_group_id: UUID | None
    row_version: int


class ImportGroupRead(_ORMModel):
    id: UUID
    group_key: UUID
    import_session_id: UUID
    group_order: int
    target_type: str
    target_joint_id: UUID | None
    prepared_joint_data: dict | None
    status: str
    block_reasons: list
    record_version: int


class ImportResolutionRead(_ORMModel):
    id: UUID
    import_row_id: UUID
    resolution_type: str
    comment: str | None
    resolved_by: int
    resolved_at: datetime
    selected_joint_id: UUID | None
    selected_weld_operation_id: UUID | None
    supersedes_resolution_id: UUID | None
    is_superseded: bool


class ImportRowChangeRead(_ORMModel):
    id: UUID
    import_row_id: UUID
    field: str
    old_value: str | None
    new_value: str | None
    comment: str | None
    changed_by: int
    changed_at: datetime


class ImportParseAttemptRead(_ORMModel):
    id: UUID
    import_session_id: UUID
    attempt_no: int
    initiated_by: int
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    error_code: str | None
    error_message: str | None
    rows_read: int
    rows_empty: int
    rows_created: int
    rows_error: int


class ImportApplyGroupResultRead(_ORMModel):
    id: UUID
    import_group_id: UUID
    status: str
    created_joint_id: UUID | None
    selected_joint_id: UUID | None
    created_weld_operation_ids: list
    row_ids: list
    error_category: str | None
    error_code: str | None
    is_retryable: bool | None
    error_message: str | None


class ImportApplyAttemptRead(_ORMModel):
    id: UUID
    import_session_id: UUID
    attempt_no: int
    initiated_by: int
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    groups_applied: int
    groups_failed: int
    groups_skipped: int
    error_category: str | None
    error_message: str | None


class ImportProvenanceRead(_ORMModel):
    id: UUID
    import_session_id: UUID
    import_row_id: UUID | None
    import_group_id: UUID | None
    link_type: str
    target_type: str
    target_joint_id: UUID | None
    target_weld_operation_id: UUID | None
    created_by: int
    created_at: datetime


class ImportStatusEventRead(_ORMModel):
    id: UUID
    import_session_id: UUID
    entity_type: str
    entity_id: UUID
    previous_status: str | None
    new_status: str | None
    reason: str | None
    actor_kind: str
    actor_worker_id: int | None
    created_at: datetime


class ImportSessionListResponse(BaseModel):
    items: list[ImportSessionRead]


class ImportRowListResponse(BaseModel):
    items: list[ImportRowRead]


class ImportGroupListResponse(BaseModel):
    items: list[ImportGroupRead]


class FileDownloadLink(BaseModel):
    """Короткоживущая ссылка/дескриптор на исходный XLSX (§15)."""

    storage_object_key: str
    original_filename: str
    file_sha256: str
    expires_in_seconds: int


# ══════════════════════════════════════════════════════════════════════════════
# Command-схемы (idempotency_key — через заголовок)
# ══════════════════════════════════════════════════════════════════════════════
class RowEditCommand(BaseModel):
    """Редактирование нормализованных staging-полей строки (§6)."""

    fields: dict[str, str | None] = Field(
        ..., description="Нормализованные поля к изменению"
    )
    comment: str | None = None
    expected_row_version: int | None = None


class ResolutionCommand(BaseModel):
    resolution_type: str
    selected_joint_id: UUID | None = None
    selected_weld_operation_id: UUID | None = None
    comment: str | None = None
    expected_row_version: int | None = None


class RejectRowCommand(BaseModel):
    comment: str | None = None
    expected_row_version: int | None = None


class ReturnRowCommand(BaseModel):
    comment: str
    expected_row_version: int | None = None


class CancelGroupCommand(BaseModel):
    comment: str
    expected_record_version: int | None = None


class CancelSessionCommand(BaseModel):
    comment: str
    expected_record_version: int | None = None


class SessionVersionCommand(BaseModel):
    expected_record_version: int | None = None


class ReturnSessionCommand(BaseModel):
    comment: str
    expected_record_version: int | None = None


class ReturnGroupCommand(BaseModel):
    comment: str
    expected_record_version: int | None = None


def resolution_type_is_valid(value: str) -> bool:
    return value in iw.RESOLUTION_TYPES
