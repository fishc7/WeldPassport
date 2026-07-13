"""import pipeline & conflict resolution (Task 8E).

Revision ID: 20260712_13_import_pipeline
Revises: 20260712_12_weld_op_corrections
Create Date: 2026-07-12

Task 8E по ADR-012 / Architecture Session 005: безопасный импорт канонического XLSX
через staging-контур (ImportSession → ImportRow → ImportGroup), предварительную
проверку, сопоставление Joint, разрешение конфликтов, атомарное применение по
группам, провенанс, идемпотентность и неизменяемую историю статусов.

Создаёт только новые таблицы контура импорта в схеме engineering. Семантику таблиц
Task 8D (weld_operations, weld_operation_corrections и др.) не меняет, второго
Alembic head не вводит. FK на joints/weld_operations — RESTRICT; дочерние таблицы
импорта — CASCADE на import_sessions (физическое удаление сессии запрещено доменно).

Downgrade удаляет только объекты Task 8E, в обратном порядке зависимостей FK, без
CASCADE.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260712_13_import_pipeline"
down_revision: Union[str, None] = "20260712_12_weld_op_corrections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "engineering"

# Порядок создания учитывает зависимости FK (родители раньше детей).
_CREATE_STATEMENTS: tuple[str, ...] = (
    # ── import_sessions ───────────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_sessions (
        id UUID NOT NULL,
        project_id UUID NOT NULL,
        template_version VARCHAR(20) NOT NULL,
        original_filename VARCHAR(512) NOT NULL,
        file_size_bytes INTEGER NOT NULL,
        mime_type VARCHAR(255) NOT NULL,
        file_sha256 VARCHAR(64) NOT NULL,
        storage_object_key VARCHAR(1024) NOT NULL,
        status VARCHAR(40) DEFAULT 'UPLOADED' NOT NULL,
        duplicate_of_session_id UUID,
        record_version INTEGER DEFAULT '1' NOT NULL,
        uploaded_by INTEGER NOT NULL,
        uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_by INTEGER NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_engineering_import_sessions_status CHECK (status IN ('UPLOADED', 'PARSING', 'PARSE_FAILED', 'UNDER_REVIEW', 'READY_FOR_APPLY', 'APPLYING', 'PARTIALLY_APPLIED', 'PARTIALLY_APPLIED_WITH_FAILURES', 'APPLY_FAILED', 'COMPLETED', 'CANCELLED')),
        CONSTRAINT ck_engineering_import_sessions_sha256_len CHECK (length(trim(file_sha256)) = 64),
        CONSTRAINT ck_engineering_import_sessions_size_positive CHECK (file_size_bytes > 0),
        CONSTRAINT ck_engineering_import_sessions_record_version_positive CHECK (record_version > 0),
        CONSTRAINT ck_engineering_import_sessions_no_self_duplicate CHECK (duplicate_of_session_id IS NULL OR duplicate_of_session_id <> id),
        FOREIGN KEY(project_id) REFERENCES project.projects (id) ON DELETE RESTRICT,
        FOREIGN KEY(duplicate_of_session_id) REFERENCES engineering.import_sessions (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_engineering_import_sessions_project_id ON engineering.import_sessions (project_id)",
    "CREATE INDEX ix_engineering_import_sessions_status ON engineering.import_sessions (status)",
    "CREATE INDEX ix_engineering_import_sessions_file_sha256 ON engineering.import_sessions (file_sha256)",
    "CREATE INDEX ix_engineering_import_sessions_duplicate_of ON engineering.import_sessions (duplicate_of_session_id)",
    # ── import_parse_attempts ─────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_parse_attempts (
        id UUID NOT NULL,
        import_session_id UUID NOT NULL,
        attempt_no INTEGER NOT NULL,
        initiated_by INTEGER NOT NULL,
        started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        finished_at TIMESTAMP WITH TIME ZONE,
        outcome VARCHAR(20),
        error_code VARCHAR(80),
        error_message TEXT,
        rows_read INTEGER DEFAULT '0' NOT NULL,
        rows_empty INTEGER DEFAULT '0' NOT NULL,
        rows_created INTEGER DEFAULT '0' NOT NULL,
        rows_error INTEGER DEFAULT '0' NOT NULL,
        correlation_id UUID,
        causation_id UUID,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_engineering_import_parse_attempts_no UNIQUE (import_session_id, attempt_no),
        CONSTRAINT ck_engineering_import_parse_attempts_no_positive CHECK (attempt_no > 0),
        CONSTRAINT ck_engineering_import_parse_attempts_outcome CHECK (outcome IS NULL OR outcome IN ('SUCCEEDED', 'FAILED')),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_engineering_import_parse_attempts_session ON engineering.import_parse_attempts (import_session_id)",
    # ── import_groups ─────────────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_groups (
        id UUID NOT NULL,
        group_key UUID NOT NULL,
        import_session_id UUID NOT NULL,
        group_order INTEGER NOT NULL,
        target_type VARCHAR(20) NOT NULL,
        target_joint_id UUID,
        prepared_joint_data JSONB,
        status VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
        block_reasons JSONB DEFAULT '[]'::jsonb NOT NULL,
        record_version INTEGER DEFAULT '1' NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_engineering_import_groups_key UNIQUE (import_session_id, group_key),
        CONSTRAINT uq_engineering_import_groups_order UNIQUE (import_session_id, group_order),
        CONSTRAINT ck_engineering_import_groups_status CHECK (status IN ('PENDING', 'BLOCKED', 'READY', 'APPLYING', 'APPLIED', 'FAILED', 'NO_ACTION', 'EMPTY', 'CANCELLED')),
        CONSTRAINT ck_engineering_import_groups_target_type CHECK (target_type IN ('NEW_JOINT', 'EXISTING_JOINT')),
        CONSTRAINT ck_engineering_import_groups_target_consistency CHECK ((target_type = 'EXISTING_JOINT' AND target_joint_id IS NOT NULL) OR (target_type = 'NEW_JOINT' AND target_joint_id IS NULL)),
        CONSTRAINT ck_engineering_import_groups_block_reasons_array CHECK (jsonb_typeof(block_reasons) = 'array'),
        CONSTRAINT ck_engineering_import_groups_record_version_positive CHECK (record_version > 0),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE,
        FOREIGN KEY(target_joint_id) REFERENCES engineering.joints (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_engineering_import_groups_session ON engineering.import_groups (import_session_id)",
    "CREATE INDEX ix_engineering_import_groups_order ON engineering.import_groups (group_order)",
    "CREATE INDEX ix_engineering_import_groups_status ON engineering.import_groups (status)",
    "CREATE INDEX ix_engineering_import_groups_target_joint ON engineering.import_groups (target_joint_id)",
    # ── import_rows ───────────────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_rows (
        id UUID NOT NULL,
        import_session_id UUID NOT NULL,
        row_number INTEGER NOT NULL,
        raw_snapshot JSONB NOT NULL,
        normalized_data JSONB DEFAULT '{}'::jsonb NOT NULL,
        normalized_joint_no VARCHAR(100),
        status VARCHAR(30) DEFAULT 'PENDING_MATCH' NOT NULL,
        error_codes JSONB DEFAULT '[]'::jsonb NOT NULL,
        conflict_codes JSONB DEFAULT '[]'::jsonb NOT NULL,
        duplicate_type VARCHAR(40),
        match_classification VARCHAR(20),
        matched_joint_id UUID,
        matched_weld_operation_id UUID,
        import_group_id UUID,
        row_version INTEGER DEFAULT '1' NOT NULL,
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_by INTEGER NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_engineering_import_rows_number UNIQUE (import_session_id, row_number),
        CONSTRAINT ck_engineering_import_rows_number_positive CHECK (row_number > 0),
        CONSTRAINT ck_engineering_import_rows_status CHECK (status IN ('VALIDATION_ERROR', 'PENDING_MATCH', 'MATCH_CONFLICT', 'DUPLICATE', 'PENDING_RESOLUTION', 'RESOLVED_CREATE_NEW', 'RESOLVED_LINK_EXISTING', 'RESOLVED_CREATE_NEW_JOINT', 'READY', 'APPLIED', 'SKIPPED_DUPLICATE', 'RESOLVED_AS_DUPLICATE', 'REJECTED', 'CANCELLED')),
        CONSTRAINT ck_engineering_import_rows_duplicate_type CHECK (duplicate_type IS NULL OR duplicate_type IN ('INTRA_FILE_DUPLICATE', 'EXISTING_OPERATION_DUPLICATE', 'EXISTING_OPERATION_CONFLICT')),
        CONSTRAINT ck_engineering_import_rows_match_classification CHECK (match_classification IS NULL OR match_classification IN ('EXACT_MATCH', 'NO_MATCH', 'CONFLICT', 'MULTIPLE_MATCHES')),
        CONSTRAINT ck_engineering_import_rows_error_codes_array CHECK (jsonb_typeof(error_codes) = 'array'),
        CONSTRAINT ck_engineering_import_rows_conflict_codes_array CHECK (jsonb_typeof(conflict_codes) = 'array'),
        CONSTRAINT ck_engineering_import_rows_raw_snapshot_object CHECK (jsonb_typeof(raw_snapshot) = 'object'),
        CONSTRAINT ck_engineering_import_rows_normalized_object CHECK (jsonb_typeof(normalized_data) = 'object'),
        CONSTRAINT ck_engineering_import_rows_row_version_positive CHECK (row_version > 0),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE,
        FOREIGN KEY(matched_joint_id) REFERENCES engineering.joints (id) ON DELETE RESTRICT,
        FOREIGN KEY(matched_weld_operation_id) REFERENCES engineering.weld_operations (id) ON DELETE RESTRICT,
        FOREIGN KEY(import_group_id) REFERENCES engineering.import_groups (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_engineering_import_rows_session ON engineering.import_rows (import_session_id)",
    "CREATE INDEX ix_engineering_import_rows_number ON engineering.import_rows (row_number)",
    "CREATE INDEX ix_engineering_import_rows_status ON engineering.import_rows (status)",
    "CREATE INDEX ix_engineering_import_rows_normalized_joint_no ON engineering.import_rows (normalized_joint_no)",
    "CREATE INDEX ix_engineering_import_rows_matched_joint ON engineering.import_rows (matched_joint_id)",
    "CREATE INDEX ix_engineering_import_rows_group ON engineering.import_rows (import_group_id)",
    # ── import_row_changes ────────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_row_changes (
        id UUID NOT NULL,
        import_row_id UUID NOT NULL,
        field VARCHAR(80) NOT NULL,
        old_value TEXT,
        new_value TEXT,
        comment TEXT,
        changed_by INTEGER NOT NULL,
        changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        correlation_id UUID,
        causation_id UUID,
        PRIMARY KEY (id),
        FOREIGN KEY(import_row_id) REFERENCES engineering.import_rows (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_engineering_import_row_changes_row ON engineering.import_row_changes (import_row_id)",
    # ── import_resolutions ────────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_resolutions (
        id UUID NOT NULL,
        import_row_id UUID NOT NULL,
        resolution_type VARCHAR(40) NOT NULL,
        comment TEXT,
        resolved_by INTEGER NOT NULL,
        resolved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        selected_joint_id UUID,
        selected_weld_operation_id UUID,
        supersedes_resolution_id UUID,
        is_superseded BOOLEAN DEFAULT 'false' NOT NULL,
        correlation_id UUID,
        causation_id UUID,
        PRIMARY KEY (id),
        CONSTRAINT ck_engineering_import_resolutions_type CHECK (resolution_type IN ('LINK_EXISTING_JOINT', 'CREATE_NEW_JOINT', 'MARK_OPERATION_DUPLICATE', 'CREATE_NEW_OPERATION', 'REJECT_ROW')),
        CONSTRAINT ck_engineering_import_resolutions_no_self_supersede CHECK (supersedes_resolution_id IS NULL OR supersedes_resolution_id <> id),
        FOREIGN KEY(import_row_id) REFERENCES engineering.import_rows (id) ON DELETE CASCADE,
        FOREIGN KEY(selected_joint_id) REFERENCES engineering.joints (id) ON DELETE RESTRICT,
        FOREIGN KEY(selected_weld_operation_id) REFERENCES engineering.weld_operations (id) ON DELETE RESTRICT,
        FOREIGN KEY(supersedes_resolution_id) REFERENCES engineering.import_resolutions (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_engineering_import_resolutions_row ON engineering.import_resolutions (import_row_id)",
    "CREATE UNIQUE INDEX uq_engineering_import_resolutions_active ON engineering.import_resolutions (import_row_id) WHERE is_superseded = false",
    # ── import_apply_attempts ─────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_apply_attempts (
        id UUID NOT NULL,
        import_session_id UUID NOT NULL,
        attempt_no INTEGER NOT NULL,
        initiated_by INTEGER NOT NULL,
        started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        finished_at TIMESTAMP WITH TIME ZONE,
        outcome VARCHAR(20),
        groups_applied INTEGER DEFAULT '0' NOT NULL,
        groups_failed INTEGER DEFAULT '0' NOT NULL,
        groups_skipped INTEGER DEFAULT '0' NOT NULL,
        error_category VARCHAR(20),
        error_message TEXT,
        correlation_id UUID,
        causation_id UUID,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_engineering_import_apply_attempts_no UNIQUE (import_session_id, attempt_no),
        CONSTRAINT ck_engineering_import_apply_attempts_no_positive CHECK (attempt_no > 0),
        CONSTRAINT ck_engineering_import_apply_attempts_outcome CHECK (outcome IS NULL OR outcome IN ('SUCCEEDED', 'PARTIAL', 'FAILED')),
        CONSTRAINT ck_engineering_import_apply_attempts_error_category CHECK (error_category IS NULL OR error_category IN ('BUSINESS', 'VALIDATION', 'CONFLICT', 'INFRASTRUCTURE', 'DATABASE', 'UNEXPECTED')),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_engineering_import_apply_attempts_session ON engineering.import_apply_attempts (import_session_id)",
    # ── import_apply_group_results ────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_apply_group_results (
        id UUID NOT NULL,
        import_apply_attempt_id UUID NOT NULL,
        import_group_id UUID NOT NULL,
        status VARCHAR(20) NOT NULL,
        created_joint_id UUID,
        selected_joint_id UUID,
        created_weld_operation_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
        row_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
        error_category VARCHAR(20),
        error_code VARCHAR(80),
        is_retryable BOOLEAN,
        error_message TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_engineering_import_apply_group_results_status CHECK (status IN ('APPLIED', 'FAILED', 'SKIPPED')),
        CONSTRAINT ck_engineering_import_apply_group_results_error_category CHECK (error_category IS NULL OR error_category IN ('BUSINESS', 'VALIDATION', 'CONFLICT', 'INFRASTRUCTURE', 'DATABASE', 'UNEXPECTED')),
        CONSTRAINT ck_engineering_import_apply_group_results_created_ops_array CHECK (jsonb_typeof(created_weld_operation_ids) = 'array'),
        CONSTRAINT ck_engineering_import_apply_group_results_row_ids_array CHECK (jsonb_typeof(row_ids) = 'array'),
        FOREIGN KEY(import_apply_attempt_id) REFERENCES engineering.import_apply_attempts (id) ON DELETE CASCADE,
        FOREIGN KEY(import_group_id) REFERENCES engineering.import_groups (id) ON DELETE CASCADE,
        FOREIGN KEY(created_joint_id) REFERENCES engineering.joints (id) ON DELETE RESTRICT,
        FOREIGN KEY(selected_joint_id) REFERENCES engineering.joints (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_engineering_import_apply_group_results_attempt ON engineering.import_apply_group_results (import_apply_attempt_id)",
    "CREATE INDEX ix_engineering_import_apply_group_results_group ON engineering.import_apply_group_results (import_group_id)",
    # ── import_provenance ─────────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_provenance (
        id UUID NOT NULL,
        import_session_id UUID NOT NULL,
        import_row_id UUID,
        import_group_id UUID,
        link_type VARCHAR(30) NOT NULL,
        target_type VARCHAR(20) NOT NULL,
        target_joint_id UUID,
        target_weld_operation_id UUID,
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_engineering_import_provenance_link_type CHECK (link_type IN ('CREATED', 'MATCHED_EXISTING', 'SKIPPED_DUPLICATE', 'RESOLVED_AS_DUPLICATE')),
        CONSTRAINT ck_engineering_import_provenance_target_type CHECK (target_type IN ('JOINT', 'WELD_OPERATION')),
        CONSTRAINT ck_engineering_import_provenance_target_consistency CHECK ((target_type = 'JOINT' AND target_joint_id IS NOT NULL AND target_weld_operation_id IS NULL) OR (target_type = 'WELD_OPERATION' AND target_weld_operation_id IS NOT NULL AND target_joint_id IS NULL)),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE,
        FOREIGN KEY(import_row_id) REFERENCES engineering.import_rows (id) ON DELETE CASCADE,
        FOREIGN KEY(import_group_id) REFERENCES engineering.import_groups (id) ON DELETE CASCADE,
        FOREIGN KEY(target_joint_id) REFERENCES engineering.joints (id) ON DELETE RESTRICT,
        FOREIGN KEY(target_weld_operation_id) REFERENCES engineering.weld_operations (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_engineering_import_provenance_session ON engineering.import_provenance (import_session_id)",
    "CREATE INDEX ix_engineering_import_provenance_row ON engineering.import_provenance (import_row_id)",
    "CREATE INDEX ix_engineering_import_provenance_target_joint ON engineering.import_provenance (target_joint_id)",
    "CREATE INDEX ix_engineering_import_provenance_target_operation ON engineering.import_provenance (target_weld_operation_id)",
    # ── import_status_events ──────────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_status_events (
        id UUID NOT NULL,
        import_session_id UUID NOT NULL,
        entity_type VARCHAR(20) NOT NULL,
        entity_id UUID NOT NULL,
        previous_status VARCHAR(40),
        new_status VARCHAR(40),
        reason TEXT,
        actor_kind VARCHAR(10) NOT NULL,
        actor_worker_id INTEGER,
        correlation_id UUID,
        causation_id UUID,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_engineering_import_status_events_entity_type CHECK (entity_type IN ('SESSION', 'GROUP', 'ROW')),
        CONSTRAINT ck_engineering_import_status_events_actor_kind CHECK (actor_kind IN ('USER', 'SYSTEM')),
        CONSTRAINT ck_engineering_import_status_events_actor_consistency CHECK ((actor_kind = 'SYSTEM' AND actor_worker_id IS NULL) OR (actor_kind = 'USER' AND actor_worker_id IS NOT NULL)),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_engineering_import_status_events_session ON engineering.import_status_events (import_session_id)",
    "CREATE INDEX ix_engineering_import_status_events_entity ON engineering.import_status_events (entity_type, entity_id)",
    "CREATE INDEX ix_engineering_import_status_events_correlation ON engineering.import_status_events (correlation_id)",
    # ── import_idempotency_keys ───────────────────────────────────────────────
    """
    CREATE TABLE engineering.import_idempotency_keys (
        id UUID NOT NULL,
        scope VARCHAR(10) NOT NULL,
        command_type VARCHAR(50) NOT NULL,
        import_session_id UUID,
        user_id INTEGER NOT NULL,
        idempotency_key VARCHAR(200) NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        response_payload JSONB,
        response_status_code INTEGER,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_engineering_import_idempotency_command_type CHECK (command_type IN ('UPLOAD', 'REPARSE', 'EDIT_ROW', 'RESOLVE', 'REJECT_ROW', 'RETURN_ROW', 'CANCEL_GROUP', 'CANCEL_SESSION', 'TO_READY_FOR_APPLY', 'APPLY', 'RETURN_SESSION_AFTER_APPLY_FAILED', 'RETURN_GROUP_AFTER_FAILED')),
        CONSTRAINT ck_engineering_import_idempotency_scope CHECK (scope IN ('USER', 'SESSION')),
        CONSTRAINT ck_engineering_import_idempotency_key_not_empty CHECK (length(trim(idempotency_key)) > 0),
        CONSTRAINT ck_engineering_import_idempotency_session_presence CHECK ((scope = 'SESSION' AND import_session_id IS NOT NULL) OR (scope = 'USER')),
        FOREIGN KEY(import_session_id) REFERENCES engineering.import_sessions (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_engineering_import_idempotency_session_fk ON engineering.import_idempotency_keys (import_session_id)",
    "CREATE INDEX ix_engineering_import_idempotency_key ON engineering.import_idempotency_keys (idempotency_key)",
    "CREATE UNIQUE INDEX uq_engineering_import_idempotency_user ON engineering.import_idempotency_keys (user_id, command_type, idempotency_key) WHERE scope = 'USER'",
    "CREATE UNIQUE INDEX uq_engineering_import_idempotency_session ON engineering.import_idempotency_keys (import_session_id, command_type, idempotency_key) WHERE scope = 'SESSION'",
)

# Обратный порядок для downgrade (дети раньше родителей). Индексы падают вместе с
# таблицами — CASCADE не нужен.
_DROP_TABLES: tuple[str, ...] = (
    "import_idempotency_keys",
    "import_status_events",
    "import_provenance",
    "import_apply_group_results",
    "import_apply_attempts",
    "import_resolutions",
    "import_row_changes",
    "import_rows",
    "import_groups",
    "import_parse_attempts",
    "import_sessions",
)


def upgrade() -> None:
    for statement in _CREATE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in _DROP_TABLES:
        op.execute(f"DROP TABLE {SCHEMA}.{table}")
