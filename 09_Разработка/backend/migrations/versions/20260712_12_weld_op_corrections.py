"""weld operation corrections & supersede (Task 8D).

Revision ID: 20260712_12_weld_op_corrections
Revises: 20260712_11_weld_op_review
Create Date: 2026-07-12

Task 8D по ADR-012 / Architecture Session 005: контролируемое исправление
завершённых производственных записей сварки через отдельную трассируемую сущность
engineering.weld_operation_corrections и минимальный контур полной переварки
(reweld). Завершённый WeldOperation остаётся неизменяемым; исправление создаёт
заменяющую операцию и атомарно переводит исходную в SUPERSEDED либо (ложная
запись) в CANCELLED.

Изменения weld_operations: поля трассировки замены (supersedes/superseded_by,
self-FK RESTRICT), вид операции (operation_kind) и реквизиты переварки (reweld_*).
Расширяется CHECK lifecycle_status (добавлен SUPERSEDED) и CHECK completion (чтобы
SUPERSEDED сохранял поля завершения, а COMPLETED→CANCELLED был допустим).

Импортных таблиц/полей (Task 8E) не создаёт. Merge revision не вводит. Downgrade
удаляет только объекты Task 8D и восстанавливает прежние CHECK-и.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_12_weld_op_corrections"
down_revision: Union[str, None] = "20260712_11_weld_op_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"
OP_TABLE = "weld_operations"
CORR_TABLE = "weld_operation_corrections"

# ── CHECK-и weld_operations, изменяемые Task 8D ───────────────────────────────
_OLD_LIFECYCLE_CHECK = "lifecycle_status IN ('DRAFT', 'COMPLETED', 'CANCELLED')"
_NEW_LIFECYCLE_CHECK = (
    "lifecycle_status IN ('DRAFT', 'COMPLETED', 'CANCELLED', 'SUPERSEDED')"
)
_OLD_COMPLETION_CHECK = (
    "(lifecycle_status = 'COMPLETED' AND completed_by IS NOT NULL "
    "AND completed_at IS NOT NULL AND actual_welder_id IS NOT NULL) "
    "OR (lifecycle_status <> 'COMPLETED' AND completed_by IS NULL "
    "AND completed_at IS NULL)"
)
_NEW_COMPLETION_CHECK = (
    "(lifecycle_status IN ('COMPLETED', 'SUPERSEDED') AND completed_by IS NOT NULL "
    "AND completed_at IS NOT NULL AND actual_welder_id IS NOT NULL) "
    "OR (lifecycle_status = 'DRAFT' AND completed_by IS NULL "
    "AND completed_at IS NULL) "
    "OR (lifecycle_status = 'CANCELLED')"
)

_OPERATION_KIND_CHECK = "operation_kind IN ('STANDARD', 'REWELD')"
_REWELD_REASONS = (
    "'WELD_REJECTED_BY_OGS', 'INSPECTION_FAILURE', 'NDT_FAILURE', 'WRONG_WELDER', "
    "'WRONG_WPS', 'WRONG_WELDING_METHOD', 'MATERIAL_MISMATCH', "
    "'DIMENSIONAL_NONCONFORMITY', 'OTHER'"
)
_REWELD_REASON_CHECK = f"reweld_reason IS NULL OR reweld_reason IN ({_REWELD_REASONS})"
_NO_SELF_SUPERSEDE_CHECK = (
    "(supersedes_operation_id IS NULL OR supersedes_operation_id <> id) "
    "AND (superseded_by_operation_id IS NULL OR superseded_by_operation_id <> id)"
)
_REWELD_REQUIRED_CHECK = (
    "operation_kind <> 'REWELD' "
    "OR (supersedes_operation_id IS NOT NULL AND reweld_reason IS NOT NULL)"
)

_OP_NEW_CHECKS = (
    ("ck_engineering_weld_operations_operation_kind", _OPERATION_KIND_CHECK),
    ("ck_engineering_weld_operations_reweld_reason", _REWELD_REASON_CHECK),
    ("ck_engineering_weld_operations_no_self_supersede", _NO_SELF_SUPERSEDE_CHECK),
    ("ck_engineering_weld_operations_reweld_required", _REWELD_REQUIRED_CHECK),
)
_OP_FKS = (
    ("fk_engineering_weld_operations_supersedes", "supersedes_operation_id"),
    ("fk_engineering_weld_operations_superseded_by", "superseded_by_operation_id"),
)
_OP_INDEXES = (
    (
        "ix_engineering_weld_operations_supersedes_operation_id",
        ["supersedes_operation_id"],
    ),
    (
        "ix_engineering_weld_operations_superseded_by_operation_id",
        ["superseded_by_operation_id"],
    ),
)

# ── CHECK-и таблицы корректировок (§19) ───────────────────────────────────────
_CORR_TYPES = (
    "'DATA_CORRECTION', 'WELDER_CORRECTION', 'TECHNOLOGY_CORRECTION', "
    "'CANCEL_FALSE_RECORD', 'SUPERSEDE_RECORD'"
)
_CORR_LIFECYCLE = "'DRAFT', 'SUBMITTED', 'APPROVED', 'APPLIED', 'REJECTED', 'CANCELLED'"
_CORR_SMR = (
    "'NOT_REQUIRED', 'PENDING', 'APPROVED', 'RETURNED_FOR_CLARIFICATION', 'REJECTED'"
)
_CORR_OGS = (
    "'NOT_REQUIRED', 'PENDING', 'ACCEPTED', 'ACCEPTED_WITH_REMARK', "
    "'RETURNED_FOR_CLARIFICATION', 'REJECTED'"
)
_CORR_APP = "'NOT_READY', 'READY_TO_APPLY', 'APPLIED', 'FAILED'"

_CORR_CHECKS = (
    ("ck_engineering_weld_op_corrections_type", f"correction_type IN ({_CORR_TYPES})"),
    (
        "ck_engineering_weld_op_corrections_impact",
        "impact_level IN ('NON_TECHNICAL', 'TECHNOLOGICAL')",
    ),
    (
        "ck_engineering_weld_op_corrections_source_type",
        "source_type IN ('MANUAL')",
    ),
    (
        "ck_engineering_weld_op_corrections_lifecycle",
        f"lifecycle_status IN ({_CORR_LIFECYCLE})",
    ),
    (
        "ck_engineering_weld_op_corrections_smr_status",
        f"smr_approval_status IN ({_CORR_SMR})",
    ),
    (
        "ck_engineering_weld_op_corrections_ogs_status",
        f"ogs_review_status IN ({_CORR_OGS})",
    ),
    (
        "ck_engineering_weld_op_corrections_application_status",
        f"application_status IN ({_CORR_APP})",
    ),
    (
        "ck_engineering_weld_op_corrections_source_not_replacement",
        "replacement_operation_id IS NULL "
        "OR replacement_operation_id <> source_operation_id",
    ),
    (
        "ck_engineering_weld_op_corrections_cancel_no_replacement",
        "correction_type <> 'CANCEL_FALSE_RECORD' "
        "OR (replacement_operation_id IS NULL AND after_snapshot IS NULL)",
    ),
    (
        "ck_engineering_weld_op_corrections_applied_replacement",
        "application_status <> 'APPLIED' "
        "OR correction_type = 'CANCEL_FALSE_RECORD' "
        "OR replacement_operation_id IS NOT NULL",
    ),
    (
        "ck_engineering_weld_op_corrections_reason_not_empty",
        "length(trim(reason)) > 0",
    ),
    (
        "ck_engineering_weld_op_corrections_attempts_non_negative",
        "application_attempts >= 0",
    ),
    (
        "ck_engineering_weld_op_corrections_record_version_positive",
        "record_version > 0",
    ),
    (
        "ck_engineering_weld_op_corrections_changed_fields_array",
        "jsonb_typeof(changed_fields) = 'array'",
    ),
    (
        "ck_engineering_weld_op_corrections_field_changes_object",
        "jsonb_typeof(field_changes) = 'object'",
    ),
    (
        "ck_engineering_weld_op_corrections_before_snapshot_object",
        "jsonb_typeof(before_snapshot) = 'object'",
    ),
)
_CORR_INDEXES = (
    (
        "ix_engineering_weld_op_corrections_source_operation_id",
        ["source_operation_id"],
        False,
        None,
    ),
    (
        "ix_engineering_weld_op_corrections_replacement_operation_id",
        ["replacement_operation_id"],
        False,
        None,
    ),
    (
        "ix_engineering_weld_op_corrections_lifecycle_status",
        ["lifecycle_status"],
        False,
        None,
    ),
    (
        "ix_engineering_weld_op_corrections_application_status",
        ["application_status"],
        False,
        None,
    ),
    (
        "uq_engineering_weld_op_corrections_active_source",
        ["source_operation_id"],
        True,
        "lifecycle_status IN ('DRAFT', 'SUBMITTED', 'APPROVED')",
    ),
)


def upgrade() -> None:
    # 1. Новые поля weld_operations (§6).
    op.add_column(
        OP_TABLE,
        sa.Column("supersedes_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        OP_TABLE,
        sa.Column(
            "superseded_by_operation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        OP_TABLE,
        sa.Column(
            "operation_kind",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'STANDARD'"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        OP_TABLE,
        sa.Column("reweld_reason", sa.String(length=40), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        OP_TABLE,
        sa.Column("reweld_decision_comment", sa.Text(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        OP_TABLE,
        sa.Column("reweld_decided_by", sa.Integer(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        OP_TABLE,
        sa.Column("reweld_decided_at", sa.DateTime(timezone=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )

    # 2. Расширяем CHECK lifecycle_status (SUPERSEDED) и completion.
    op.drop_constraint(
        "ck_engineering_weld_operations_lifecycle_status",
        OP_TABLE,
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_weld_operations_lifecycle_status",
        OP_TABLE,
        _NEW_LIFECYCLE_CHECK,
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_constraint(
        "ck_engineering_weld_operations_completion",
        OP_TABLE,
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_weld_operations_completion",
        OP_TABLE,
        _NEW_COMPLETION_CHECK,
        schema=ENGINEERING_SCHEMA,
    )

    # 3. Новые CHECK-и, self-FK и индексы трассировки.
    for name, condition in _OP_NEW_CHECKS:
        op.create_check_constraint(
            name, OP_TABLE, condition, schema=ENGINEERING_SCHEMA
        )
    for name, column in _OP_FKS:
        op.create_foreign_key(
            name,
            OP_TABLE,
            OP_TABLE,
            [column],
            ["id"],
            source_schema=ENGINEERING_SCHEMA,
            referent_schema=ENGINEERING_SCHEMA,
            ondelete="RESTRICT",
        )
    for name, columns in _OP_INDEXES:
        op.create_index(name, OP_TABLE, columns, schema=ENGINEERING_SCHEMA)

    # 4. Таблица корректировок (§7).
    op.create_table(
        CORR_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "replacement_operation_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("correction_type", sa.String(length=30), nullable=False),
        sa.Column("impact_level", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("after_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("field_changes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'MANUAL'"),
        ),
        sa.Column(
            "lifecycle_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column(
            "smr_approval_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "ogs_review_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'NOT_REQUIRED'"),
        ),
        sa.Column(
            "application_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NOT_READY'"),
        ),
        sa.Column(
            "record_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("smr_decided_by", sa.Integer(), nullable=True),
        sa.Column("smr_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("smr_comment", sa.Text(), nullable=True),
        sa.Column("ogs_decided_by", sa.Integer(), nullable=True),
        sa.Column("ogs_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ogs_comment", sa.Text(), nullable=True),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "application_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_application_error", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["source_operation_id"],
            [f"{ENGINEERING_SCHEMA}.{OP_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_weld_op_corrections_source",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_operation_id"],
            [f"{ENGINEERING_SCHEMA}.{OP_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_weld_op_corrections_replacement",
        ),
        sa.UniqueConstraint(
            "replacement_operation_id",
            name="uq_engineering_weld_op_corrections_replacement",
        ),
        *[
            sa.CheckConstraint(condition, name=name)
            for name, condition in _CORR_CHECKS
        ],
        schema=ENGINEERING_SCHEMA,
    )
    for name, columns, unique, where in _CORR_INDEXES:
        kwargs = {"unique": unique, "schema": ENGINEERING_SCHEMA}
        if where is not None:
            kwargs["postgresql_where"] = sa.text(where)
        op.create_index(name, CORR_TABLE, columns, **kwargs)


def downgrade() -> None:
    for name, _columns, _unique, _where in reversed(_CORR_INDEXES):
        op.drop_index(name, table_name=CORR_TABLE, schema=ENGINEERING_SCHEMA)
    op.drop_table(CORR_TABLE, schema=ENGINEERING_SCHEMA)

    for name, _columns in reversed(_OP_INDEXES):
        op.drop_index(name, table_name=OP_TABLE, schema=ENGINEERING_SCHEMA)
    for name, _column in reversed(_OP_FKS):
        op.drop_constraint(
            name, OP_TABLE, schema=ENGINEERING_SCHEMA, type_="foreignkey"
        )
    for name, _condition in reversed(_OP_NEW_CHECKS):
        op.drop_constraint(name, OP_TABLE, schema=ENGINEERING_SCHEMA, type_="check")

    # Восстанавливаем прежние CHECK-и (без SUPERSEDED).
    op.drop_constraint(
        "ck_engineering_weld_operations_completion",
        OP_TABLE,
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_weld_operations_completion",
        OP_TABLE,
        _OLD_COMPLETION_CHECK,
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_constraint(
        "ck_engineering_weld_operations_lifecycle_status",
        OP_TABLE,
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_weld_operations_lifecycle_status",
        OP_TABLE,
        _OLD_LIFECYCLE_CHECK,
        schema=ENGINEERING_SCHEMA,
    )

    for column in (
        "reweld_decided_at",
        "reweld_decided_by",
        "reweld_decision_comment",
        "reweld_reason",
        "operation_kind",
        "superseded_by_operation_id",
        "supersedes_operation_id",
    ):
        op.drop_column(OP_TABLE, column, schema=ENGINEERING_SCHEMA)
