"""ORM-модели контура импорта XLSX (Task 8E, ADR-012 / Session 005).

Отдельный файл (не в `models.py`), чтобы изолировать Task 8E от Task 8A–8D (§2
задания: не менять и не дублировать модель WeldOperation/Joint и correction/
supersede Task 8D). Провенанс доменных данных выносится в `import_provenance`, а не
в поля Joint/WeldOperation. Все словари — `String` + `CHECK ... IN (...)` (native PG
enum в проекте не используются).

FK-политика: связи с `joints`/`weld_operations` — `RESTRICT` (доменные данные не
теряются молча); дочерние таблицы контура импорта — `CASCADE` на `import_sessions`
(физическое удаление сессии запрещено доменно, каскад — только техническая
целостность). Append-only историю (`import_parse_attempts`, `import_row_changes`,
`import_resolutions`, `import_apply_attempts`, `import_apply_group_results`,
`import_provenance`, `import_status_events`) не редактируем и не удаляем.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering import import_workflow as iw
from app.engineering.models import ENGINEERING_SCHEMA, _in_check
from app.projects.models import PROJECT_SCHEMA
from app.shared.orm import Base

_JOINTS = f"{ENGINEERING_SCHEMA}.joints.id"
_WELD_OPS = f"{ENGINEERING_SCHEMA}.weld_operations.id"
_SESSIONS = f"{ENGINEERING_SCHEMA}.import_sessions.id"


def _nullable_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR " + _in_check(column, values)


# ══════════════════════════════════════════════════════════════════════════════
# ImportSession — корневая сущность одной загрузки XLSX (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportSession(Base):
    """Корневая сущность одной загрузки XLSX. Физическое удаление запрещено (§6).

    Исходный файл — постоянный неизменяемый артефакт: метаданные (sha256, ключ
    хранилища, размер, mime) фиксируются при загрузке и не меняются. `record_version`
    — оптимистическая блокировка для команд уровня сессии."""

    __tablename__ = "import_sessions"
    __table_args__ = (
        CheckConstraint(
            _in_check("status", iw.SESSION_STATUSES),
            name="ck_engineering_import_sessions_status",
        ),
        CheckConstraint(
            "length(trim(file_sha256)) = 64",
            name="ck_engineering_import_sessions_sha256_len",
        ),
        CheckConstraint(
            "file_size_bytes > 0",
            name="ck_engineering_import_sessions_size_positive",
        ),
        CheckConstraint(
            "record_version > 0",
            name="ck_engineering_import_sessions_record_version_positive",
        ),
        CheckConstraint(
            "duplicate_of_session_id IS NULL OR duplicate_of_session_id <> id",
            name="ck_engineering_import_sessions_no_self_duplicate",
        ),
        Index("ix_engineering_import_sessions_project_id", "project_id"),
        Index("ix_engineering_import_sessions_status", "status"),
        Index("ix_engineering_import_sessions_file_sha256", "file_sha256"),
        Index(
            "ix_engineering_import_sessions_duplicate_of",
            "duplicate_of_session_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_version: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=iw.SESSION_UPLOADED
    )
    duplicate_of_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="RESTRICT"),
    )
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    uploaded_by: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportParseAttempt — неизменяемая запись каждой попытки разбора (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportParseAttempt(Base):
    __tablename__ = "import_parse_attempts"
    __table_args__ = (
        UniqueConstraint(
            "import_session_id",
            "attempt_no",
            name="uq_engineering_import_parse_attempts_no",
        ),
        CheckConstraint(
            "attempt_no > 0",
            name="ck_engineering_import_parse_attempts_no_positive",
        ),
        CheckConstraint(
            _nullable_check("outcome", iw.PARSE_ATTEMPT_OUTCOMES),
            name="ck_engineering_import_parse_attempts_outcome",
        ),
        Index(
            "ix_engineering_import_parse_attempts_session",
            "import_session_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    initiated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    rows_read: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_empty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_created: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_error: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportGroup — атомарная группа одного Joint и его импортируемых операций (§6, §9)
# ══════════════════════════════════════════════════════════════════════════════
class ImportGroup(Base):
    __tablename__ = "import_groups"
    __table_args__ = (
        UniqueConstraint(
            "import_session_id",
            "group_key",
            name="uq_engineering_import_groups_key",
        ),
        UniqueConstraint(
            "import_session_id",
            "group_order",
            name="uq_engineering_import_groups_order",
        ),
        CheckConstraint(
            _in_check("status", iw.GROUP_STATUSES),
            name="ck_engineering_import_groups_status",
        ),
        CheckConstraint(
            _in_check("target_type", iw.GROUP_TARGET_TYPES),
            name="ck_engineering_import_groups_target_type",
        ),
        CheckConstraint(
            "(target_type = 'EXISTING_JOINT' AND target_joint_id IS NOT NULL) "
            "OR (target_type = 'NEW_JOINT' AND target_joint_id IS NULL)",
            name="ck_engineering_import_groups_target_consistency",
        ),
        CheckConstraint(
            "jsonb_typeof(block_reasons) = 'array'",
            name="ck_engineering_import_groups_block_reasons_array",
        ),
        CheckConstraint(
            "record_version > 0",
            name="ck_engineering_import_groups_record_version_positive",
        ),
        Index("ix_engineering_import_groups_session", "import_session_id"),
        Index("ix_engineering_import_groups_order", "group_order"),
        Index("ix_engineering_import_groups_status", "status"),
        Index("ix_engineering_import_groups_target_joint", "target_joint_id"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    group_key: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, default=uuid4
    )
    import_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
        nullable=False,
    )
    group_order: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_JOINTS, ondelete="RESTRICT")
    )
    prepared_joint_data: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=iw.GROUP_PENDING
    )
    block_reasons: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportRow — staging-представление строки XLSX (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportRow(Base):
    """Staging-строка. `raw_snapshot` — неизменяемый исходный снимок; `normalized_data`
    — нормализованные поля; статус и коды — результат валидации/сопоставления/дублей.
    `row_version` — оптимистическая блокировка. После применения строка неизменяема."""

    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint(
            "import_session_id",
            "row_number",
            name="uq_engineering_import_rows_number",
        ),
        CheckConstraint(
            "row_number > 0",
            name="ck_engineering_import_rows_number_positive",
        ),
        CheckConstraint(
            _in_check("status", iw.ROW_STATUSES),
            name="ck_engineering_import_rows_status",
        ),
        CheckConstraint(
            _nullable_check("duplicate_type", iw.DUPLICATE_TYPES),
            name="ck_engineering_import_rows_duplicate_type",
        ),
        CheckConstraint(
            _nullable_check("match_classification", iw.MATCH_CLASSIFICATIONS),
            name="ck_engineering_import_rows_match_classification",
        ),
        CheckConstraint(
            "jsonb_typeof(error_codes) = 'array'",
            name="ck_engineering_import_rows_error_codes_array",
        ),
        CheckConstraint(
            "jsonb_typeof(conflict_codes) = 'array'",
            name="ck_engineering_import_rows_conflict_codes_array",
        ),
        CheckConstraint(
            "jsonb_typeof(raw_snapshot) = 'object'",
            name="ck_engineering_import_rows_raw_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(normalized_data) = 'object'",
            name="ck_engineering_import_rows_normalized_object",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_engineering_import_rows_row_version_positive",
        ),
        Index("ix_engineering_import_rows_session", "import_session_id"),
        Index("ix_engineering_import_rows_number", "row_number"),
        Index("ix_engineering_import_rows_status", "status"),
        Index(
            "ix_engineering_import_rows_normalized_joint_no",
            "normalized_joint_no",
        ),
        Index("ix_engineering_import_rows_matched_joint", "matched_joint_id"),
        Index("ix_engineering_import_rows_group", "import_group_id"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    normalized_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    normalized_joint_no: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=iw.ROW_PENDING_MATCH
    )
    error_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    conflict_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    duplicate_type: Mapped[str | None] = mapped_column(String(40))
    match_classification: Mapped[str | None] = mapped_column(String(20))
    matched_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_JOINTS, ondelete="RESTRICT")
    )
    matched_weld_operation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_WELD_OPS, ondelete="RESTRICT")
    )
    import_group_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.import_groups.id", ondelete="CASCADE"),
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportRowChange — неизменяемая история ручных изменений staging-полей (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportRowChange(Base):
    __tablename__ = "import_row_changes"
    __table_args__ = (
        Index(
            "ix_engineering_import_row_changes_row", "import_row_id"
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_row_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.import_rows.id", ondelete="CASCADE"),
        nullable=False,
    )
    field: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


# ══════════════════════════════════════════════════════════════════════════════
# ImportResolution — неизменяемое решение по конфликту, supersede-цепочка (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportResolution(Base):
    """Принятое решение по строке. Новое решение не перезаписывает старое, а
    supersede-связывается с ним (`supersedes_resolution_id`); активное решение —
    `is_superseded = false` (partial unique). Это НЕ supersede-механизм Task 8D."""

    __tablename__ = "import_resolutions"
    __table_args__ = (
        CheckConstraint(
            _in_check("resolution_type", iw.RESOLUTION_TYPES),
            name="ck_engineering_import_resolutions_type",
        ),
        CheckConstraint(
            "supersedes_resolution_id IS NULL OR supersedes_resolution_id <> id",
            name="ck_engineering_import_resolutions_no_self_supersede",
        ),
        Index("ix_engineering_import_resolutions_row", "import_row_id"),
        # Ровно одно активное (не superseded) решение на строку.
        Index(
            "uq_engineering_import_resolutions_active",
            "import_row_id",
            unique=True,
            postgresql_where=text("is_superseded = false"),
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_row_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.import_rows.id", ondelete="CASCADE"),
        nullable=False,
    )
    resolution_type: Mapped[str] = mapped_column(String(40), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    selected_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_JOINTS, ondelete="RESTRICT")
    )
    selected_weld_operation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_WELD_OPS, ondelete="RESTRICT")
    )
    supersedes_resolution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.import_resolutions.id", ondelete="RESTRICT"
        ),
    )
    is_superseded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


# ══════════════════════════════════════════════════════════════════════════════
# ImportApplyAttempt — неизменяемая запись попытки применения сессии (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportApplyAttempt(Base):
    __tablename__ = "import_apply_attempts"
    __table_args__ = (
        UniqueConstraint(
            "import_session_id",
            "attempt_no",
            name="uq_engineering_import_apply_attempts_no",
        ),
        CheckConstraint(
            "attempt_no > 0",
            name="ck_engineering_import_apply_attempts_no_positive",
        ),
        CheckConstraint(
            _nullable_check("outcome", iw.APPLY_ATTEMPT_OUTCOMES),
            name="ck_engineering_import_apply_attempts_outcome",
        ),
        CheckConstraint(
            _nullable_check("error_category", iw.ERROR_CATEGORIES),
            name="ck_engineering_import_apply_attempts_error_category",
        ),
        Index(
            "ix_engineering_import_apply_attempts_session",
            "import_session_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    initiated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(20))
    groups_applied: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    groups_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    groups_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error_category: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportApplyGroupResult — результат применения группы внутри попытки (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportApplyGroupResult(Base):
    __tablename__ = "import_apply_group_results"
    __table_args__ = (
        CheckConstraint(
            _in_check("status", iw.APPLY_GROUP_RESULT_STATUSES),
            name="ck_engineering_import_apply_group_results_status",
        ),
        CheckConstraint(
            _nullable_check("error_category", iw.ERROR_CATEGORIES),
            name="ck_engineering_import_apply_group_results_error_category",
        ),
        CheckConstraint(
            "jsonb_typeof(created_weld_operation_ids) = 'array'",
            name="ck_engineering_import_apply_group_results_created_ops_array",
        ),
        CheckConstraint(
            "jsonb_typeof(row_ids) = 'array'",
            name="ck_engineering_import_apply_group_results_row_ids_array",
        ),
        Index(
            "ix_engineering_import_apply_group_results_attempt",
            "import_apply_attempt_id",
        ),
        Index(
            "ix_engineering_import_apply_group_results_group",
            "import_group_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_apply_attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.import_apply_attempts.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    import_group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.import_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_JOINTS, ondelete="RESTRICT")
    )
    selected_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_JOINTS, ondelete="RESTRICT")
    )
    created_weld_operation_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    row_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    error_category: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    is_retryable: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportProvenance — неизменяемое происхождение доменных данных (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportProvenance(Base):
    """Провенанс created/matched/duplicate. Создаётся только после успешного
    применения группы. Физическое удаление и изменение запрещены (§6). Import-поля
    в Joint/WeldOperation не добавляются — только эта таблица."""

    __tablename__ = "import_provenance"
    __table_args__ = (
        CheckConstraint(
            _in_check("link_type", iw.PROVENANCE_LINK_TYPES),
            name="ck_engineering_import_provenance_link_type",
        ),
        CheckConstraint(
            _in_check("target_type", iw.PROVENANCE_TARGET_TYPES),
            name="ck_engineering_import_provenance_target_type",
        ),
        CheckConstraint(
            "(target_type = 'JOINT' AND target_joint_id IS NOT NULL "
            "AND target_weld_operation_id IS NULL) "
            "OR (target_type = 'WELD_OPERATION' "
            "AND target_weld_operation_id IS NOT NULL "
            "AND target_joint_id IS NULL)",
            name="ck_engineering_import_provenance_target_consistency",
        ),
        Index(
            "ix_engineering_import_provenance_session", "import_session_id"
        ),
        Index(
            "ix_engineering_import_provenance_target_joint", "target_joint_id"
        ),
        Index(
            "ix_engineering_import_provenance_target_operation",
            "target_weld_operation_id",
        ),
        Index("ix_engineering_import_provenance_row", "import_row_id"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
        nullable=False,
    )
    import_row_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.import_rows.id", ondelete="CASCADE"),
    )
    import_group_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.import_groups.id", ondelete="CASCADE"),
    )
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_JOINTS, ondelete="RESTRICT")
    )
    target_weld_operation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_WELD_OPS, ondelete="RESTRICT")
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportStatusEvent — неизменяемая история переходов session/group/row (§6)
# ══════════════════════════════════════════════════════════════════════════════
class ImportStatusEvent(Base):
    __tablename__ = "import_status_events"
    __table_args__ = (
        CheckConstraint(
            _in_check("entity_type", iw.EVENT_ENTITY_TYPES),
            name="ck_engineering_import_status_events_entity_type",
        ),
        CheckConstraint(
            _in_check("actor_kind", iw.EVENT_ACTOR_KINDS),
            name="ck_engineering_import_status_events_actor_kind",
        ),
        CheckConstraint(
            "(actor_kind = 'SYSTEM' AND actor_worker_id IS NULL) "
            "OR (actor_kind = 'USER' AND actor_worker_id IS NOT NULL)",
            name="ck_engineering_import_status_events_actor_consistency",
        ),
        Index(
            "ix_engineering_import_status_events_session", "import_session_id"
        ),
        Index(
            "ix_engineering_import_status_events_entity",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_engineering_import_status_events_correlation", "correlation_id"
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    import_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_worker_id: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ══════════════════════════════════════════════════════════════════════════════
# ImportIdempotencyKey — постоянное хранение идемпотентных ключей команд (§13)
# ══════════════════════════════════════════════════════════════════════════════
class ImportIdempotencyKey(Base):
    """Ключ + hash канонизированного payload + сохранённый результат команды.

    Область уникальности: UPLOAD — (user_id, command_type, key); остальные —
    (import_session_id, command_type, key). Реализовано двумя partial unique
    индексами по `scope`."""

    __tablename__ = "import_idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            _in_check("command_type", iw.IDEMPOTENT_COMMANDS),
            name="ck_engineering_import_idempotency_command_type",
        ),
        CheckConstraint(
            "scope IN ('USER', 'SESSION')",
            name="ck_engineering_import_idempotency_scope",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_engineering_import_idempotency_key_not_empty",
        ),
        CheckConstraint(
            "(scope = 'SESSION' AND import_session_id IS NOT NULL) "
            "OR (scope = 'USER')",
            name="ck_engineering_import_idempotency_session_presence",
        ),
        # UPLOAD: уникальность по (пользователь, тип команды, ключ).
        Index(
            "uq_engineering_import_idempotency_user",
            "user_id",
            "command_type",
            "idempotency_key",
            unique=True,
            postgresql_where=text("scope = 'USER'"),
        ),
        # Остальные команды: уникальность по (сессия, тип команды, ключ).
        Index(
            "uq_engineering_import_idempotency_session",
            "import_session_id",
            "command_type",
            "idempotency_key",
            unique=True,
            postgresql_where=text("scope = 'SESSION'"),
        ),
        Index(
            "ix_engineering_import_idempotency_session_fk",
            "import_session_id",
        ),
        Index("ix_engineering_import_idempotency_key", "idempotency_key"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    import_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SESSIONS, ondelete="CASCADE"),
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    response_status_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
