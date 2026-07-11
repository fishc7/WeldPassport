"""joint review lifecycle: statuses, approvals, versions, blocks, events (Task 5B).

Revision ID: 20260711_06_joint_review
Revises: 20260711_05_engineering_joints
Create Date: 2026-07-11

Task 5B по ADR-011 (канон закрыт решениями Р-11-1 — Р-11-4 и решением владельца
2026-07-11): жизненный цикл Joint (DRAFT/PENDING_REVIEW/ACTIVE/CANCELLED/
SUPERSEDED), независимые согласования ПТО/ОГС, три версии (record/approval/
workflow), самоссылка замены, отдельные таблицы блокировок и истории. Данные
Task 5A сохраняются: version → record_version (переименование), approval_version /
workflow_version backfill = 1, оба согласования = NOT_SUBMITTED.

Дополнительно: hr.worker_roles — аддитивно PTO_MANAGER/CHIEF_WELDER/AUDITOR в CHECK
role_code, ENGINEERING_DOCUMENT в CHECK scope_type, инвариант CHIEF_WELDER=GLOBAL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_06_joint_review"
down_revision: Union[str, None] = "20260711_05_engineering_joints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROJECT_SCHEMA = "project"
ENGINEERING_SCHEMA = "engineering"
HR_SCHEMA = "hr"

# ── CHECK-выражения Joint (зеркало app/engineering/models.py) ─────────────────
STATUS_CHECK_NEW = (
    "status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'CANCELLED', 'SUPERSEDED')"
)
STATUS_CHECK_OLD = "status IN ('DRAFT')"

_APPROVAL_STATES = "'NOT_SUBMITTED', 'PENDING', 'APPROVED', 'REJECTED', 'REVOKED'"
_PENDING_REASONS = (
    "'INITIAL_REVIEW', 'REVIEW_REOPENED', 'TEMPORARY_SUSPENSION', 'REVALIDATION'"
)
_DECISION_METHODS = "'AUTOMATIC', 'MANUAL', 'OVERRIDE'"

PTO_STATUS_CHECK = f"pto_status IN ({_APPROVAL_STATES})"
OGS_STATUS_CHECK = f"ogs_status IN ({_APPROVAL_STATES})"
PTO_PENDING_REASON_CHECK = (
    f"pto_pending_reason IS NULL OR pto_pending_reason IN ({_PENDING_REASONS})"
)
OGS_PENDING_REASON_CHECK = (
    f"ogs_pending_reason IS NULL OR ogs_pending_reason IN ({_PENDING_REASONS})"
)
PTO_DECISION_METHOD_CHECK = (
    f"pto_decision_method IS NULL OR pto_decision_method IN ({_DECISION_METHODS})"
)
OGS_DECISION_METHOD_CHECK = (
    f"ogs_decision_method IS NULL OR ogs_decision_method IN ({_DECISION_METHODS})"
)
PTO_METHOD_CONSISTENCY_CHECK = (
    "(pto_status = 'NOT_SUBMITTED' AND pto_decision_method IS NULL) "
    "OR (pto_status = 'PENDING') "
    "OR (pto_status IN ('APPROVED', 'REJECTED', 'REVOKED') "
    "AND pto_decision_method IS NOT NULL)"
)
OGS_METHOD_CONSISTENCY_CHECK = (
    "(ogs_status = 'NOT_SUBMITTED' AND ogs_decision_method IS NULL) "
    "OR (ogs_status = 'PENDING') "
    "OR (ogs_status IN ('APPROVED', 'REJECTED', 'REVOKED') "
    "AND ogs_decision_method IS NOT NULL)"
)
PTO_PENDING_PRESENCE_CHECK = "(pto_status = 'PENDING') OR (pto_pending_reason IS NULL)"
OGS_PENDING_PRESENCE_CHECK = "(ogs_status = 'PENDING') OR (ogs_pending_reason IS NULL)"
NO_SELF_SUPERSEDE_CHECK = (
    "superseded_by_joint_id IS NULL OR superseded_by_joint_id <> id"
)

BLOCK_TYPE_CHECK = (
    "block_type IN ('REPLACEMENT_PENDING', 'WPS_INVALID', 'APPROVAL_REVOKED', "
    "'REVISION_IMPACT_REVIEW', 'APPROVAL_EXPIRED', 'MANUAL_HOLD', "
    "'ADMIN_OVERRIDE_EXPIRED', 'REVALIDATION_PENDING', 'INTEGRITY_VIOLATION')"
)
BLOCK_SCOPE_CHECK = "scope IN ('PRODUCTION', 'EDITING', 'APPROVAL', 'ALL')"
EVENT_TYPE_CHECK = (
    "event_type IN ('SUBMITTED_FOR_REVIEW', 'REVIEW_REOPENED', 'PTO_APPROVED', "
    "'PTO_REJECTED', 'PTO_REVOKED', 'OGS_APPROVED', 'OGS_REJECTED', 'OGS_REVOKED', "
    "'ACTIVATED', 'DEACTIVATED', 'APPROVAL_RESET', 'APPROVAL_CARRIED_FORWARD', "
    "'SIGNIFICANT_EDIT', 'BLOCKED', 'UNBLOCKED', 'CANCELLED', 'SUPERSEDED')"
)

# ── HR CHECK-выражения ────────────────────────────────────────────────────────
ROLE_CODE_CHECK_NEW = (
    "role_code IN ("
    "'WELDER', 'FOREMAN', 'MASTER', 'PTO_ENGINEER', 'OTK_INSPECTOR', "
    "'NDT_SPECIALIST', 'OGS_ENGINEER', 'CONFIRMING_PERSON', 'CLOSING_RESPONSIBLE', "
    "'PTO_MANAGER', 'CHIEF_WELDER', 'AUDITOR'"
    ")"
)
ROLE_CODE_CHECK_OLD = (
    "role_code IN ("
    "'WELDER', 'FOREMAN', 'MASTER', 'PTO_ENGINEER', 'OTK_INSPECTOR', "
    "'NDT_SPECIALIST', 'OGS_ENGINEER', 'CONFIRMING_PERSON', 'CLOSING_RESPONSIBLE'"
    ")"
)
SCOPE_TYPE_CHECK_NEW = (
    "scope_type IN ("
    "'GLOBAL', 'COMPANY', 'PROJECT', 'SITE', 'LINE', 'ENGINEERING_DOCUMENT'"
    ")"
)
SCOPE_TYPE_CHECK_OLD = "scope_type IN ('GLOBAL', 'COMPANY', 'PROJECT', 'SITE', 'LINE')"
CHIEF_WELDER_GLOBAL_CHECK = "role_code <> 'CHIEF_WELDER' OR scope_type = 'GLOBAL'"


def _add_joint_columns() -> None:
    j = "joints"
    # Три версии: record_version (переименование version), approval/workflow новые.
    op.alter_column(
        j, "version", new_column_name="record_version", schema=ENGINEERING_SCHEMA
    )
    op.drop_constraint(
        "ck_engineering_joints_version_positive",
        j,
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_joints_record_version_positive",
        j,
        "record_version > 0",
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column(
            "approval_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column(
            "workflow_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=ENGINEERING_SCHEMA,
    )

    # Согласования ПТО/ОГС.
    for prefix in ("pto", "ogs"):
        op.add_column(
            j,
            sa.Column(
                f"{prefix}_status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'NOT_SUBMITTED'"),
            ),
            schema=ENGINEERING_SCHEMA,
        )
        op.add_column(
            j,
            sa.Column(f"{prefix}_pending_reason", sa.String(length=30), nullable=True),
            schema=ENGINEERING_SCHEMA,
        )
        op.add_column(
            j,
            sa.Column(f"{prefix}_decision_method", sa.String(length=20), nullable=True),
            schema=ENGINEERING_SCHEMA,
        )
        op.add_column(
            j,
            sa.Column(f"{prefix}_approval_version", sa.Integer(), nullable=True),
            schema=ENGINEERING_SCHEMA,
        )
        op.add_column(
            j,
            sa.Column(f"{prefix}_decided_by", sa.Integer(), nullable=True),
            schema=ENGINEERING_SCHEMA,
        )
        op.add_column(
            j,
            sa.Column(
                f"{prefix}_decided_at", sa.DateTime(timezone=True), nullable=True
            ),
            schema=ENGINEERING_SCHEMA,
        )
        op.add_column(
            j,
            sa.Column(f"{prefix}_comment", sa.Text(), nullable=True),
            schema=ENGINEERING_SCHEMA,
        )

    # Отправка / отмена / замена.
    op.add_column(
        j,
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column(
            "superseded_by_joint_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        j,
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_foreign_key(
        "fk_engineering_joints_superseded_by_joint",
        j,
        j,
        ["superseded_by_joint_id"],
        ["id"],
        source_schema=ENGINEERING_SCHEMA,
        referent_schema=ENGINEERING_SCHEMA,
        ondelete="RESTRICT",
    )


def _add_joint_checks() -> None:
    j = "joints"
    # Расширяем статус жизненного цикла.
    op.drop_constraint(
        "ck_engineering_joints_status", j, schema=ENGINEERING_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        "ck_engineering_joints_status", j, STATUS_CHECK_NEW, schema=ENGINEERING_SCHEMA
    )
    checks = [
        ("ck_engineering_joints_approval_version_positive", "approval_version > 0"),
        ("ck_engineering_joints_workflow_version_positive", "workflow_version > 0"),
        ("ck_engineering_joints_pto_status", PTO_STATUS_CHECK),
        ("ck_engineering_joints_ogs_status", OGS_STATUS_CHECK),
        ("ck_engineering_joints_pto_pending_reason", PTO_PENDING_REASON_CHECK),
        ("ck_engineering_joints_ogs_pending_reason", OGS_PENDING_REASON_CHECK),
        ("ck_engineering_joints_pto_decision_method", PTO_DECISION_METHOD_CHECK),
        ("ck_engineering_joints_ogs_decision_method", OGS_DECISION_METHOD_CHECK),
        ("ck_engineering_joints_pto_method_consistency", PTO_METHOD_CONSISTENCY_CHECK),
        ("ck_engineering_joints_ogs_method_consistency", OGS_METHOD_CONSISTENCY_CHECK),
        ("ck_engineering_joints_pto_pending_presence", PTO_PENDING_PRESENCE_CHECK),
        ("ck_engineering_joints_ogs_pending_presence", OGS_PENDING_PRESENCE_CHECK),
        ("ck_engineering_joints_no_self_supersede", NO_SELF_SUPERSEDE_CHECK),
    ]
    for name, expr in checks:
        op.create_check_constraint(name, j, expr, schema=ENGINEERING_SCHEMA)


def _create_block_and_event_tables() -> None:
    op.create_table(
        "joint_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_type", sa.String(length=30), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("released_by", sa.Integer(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            BLOCK_TYPE_CHECK, name="ck_engineering_joint_blocks_type"
        ),
        sa.CheckConstraint(
            BLOCK_SCOPE_CHECK, name="ck_engineering_joint_blocks_scope"
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_engineering_joint_blocks_reason_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_blocks_joint_id",
        "joint_blocks",
        ["joint_id"],
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_blocks_active",
        "joint_blocks",
        ["joint_id"],
        schema=ENGINEERING_SCHEMA,
        postgresql_where=sa.text("released_at IS NULL"),
    )

    op.create_table(
        "joint_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("actor_role_code", sa.String(length=50), nullable=True),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=True),
        sa.Column("previous_pto_status", sa.String(length=20), nullable=True),
        sa.Column("new_pto_status", sa.String(length=20), nullable=True),
        sa.Column("previous_ogs_status", sa.String(length=20), nullable=True),
        sa.Column("new_ogs_status", sa.String(length=20), nullable=True),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("decision_method", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            EVENT_TYPE_CHECK, name="ck_engineering_joint_events_type"
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_events_joint_id",
        "joint_events",
        ["joint_id"],
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_events_created_at",
        "joint_events",
        ["created_at"],
        schema=ENGINEERING_SCHEMA,
    )


def _extend_hr_checks() -> None:
    op.drop_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        ROLE_CODE_CHECK_NEW,
        schema=HR_SCHEMA,
    )
    op.drop_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        SCOPE_TYPE_CHECK_NEW,
        schema=HR_SCHEMA,
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_chief_welder_global",
        "worker_roles",
        CHIEF_WELDER_GLOBAL_CHECK,
        schema=HR_SCHEMA,
    )


def upgrade() -> None:
    _add_joint_columns()
    _add_joint_checks()
    _create_block_and_event_tables()
    _extend_hr_checks()


def downgrade() -> None:
    # HR: снять новые CHECK и вернуть прежние (с защитой от несовместимых данных).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM "{HR_SCHEMA}".worker_roles
                WHERE role_code IN ('PTO_MANAGER', 'CHIEF_WELDER', 'AUDITOR')
                   OR scope_type = 'ENGINEERING_DOCUMENT'
            ) THEN
                RAISE EXCEPTION
                    'Нельзя откатить: есть роли/scope Task 5B в worker_roles';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(
        "ck_hr_worker_roles_chief_welder_global",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_scope_type",
        "worker_roles",
        SCOPE_TYPE_CHECK_OLD,
        schema=HR_SCHEMA,
    )
    op.drop_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        schema=HR_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hr_worker_roles_role_code",
        "worker_roles",
        ROLE_CODE_CHECK_OLD,
        schema=HR_SCHEMA,
    )

    # Engineering: события и блокировки.
    op.drop_table("joint_events", schema=ENGINEERING_SCHEMA)
    op.drop_table("joint_blocks", schema=ENGINEERING_SCHEMA)

    # Защита: откат сужения статусов запрещён, если есть не-DRAFT стыки.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM "{ENGINEERING_SCHEMA}".joints
                WHERE status <> 'DRAFT'
            ) THEN
                RAISE EXCEPTION
                    'Нельзя откатить: есть Joint в статусе жизненного цикла Task 5B';
            END IF;
        END $$;
        """
    )

    j = "joints"
    for name in (
        "ck_engineering_joints_no_self_supersede",
        "ck_engineering_joints_ogs_pending_presence",
        "ck_engineering_joints_pto_pending_presence",
        "ck_engineering_joints_ogs_method_consistency",
        "ck_engineering_joints_pto_method_consistency",
        "ck_engineering_joints_ogs_decision_method",
        "ck_engineering_joints_pto_decision_method",
        "ck_engineering_joints_ogs_pending_reason",
        "ck_engineering_joints_pto_pending_reason",
        "ck_engineering_joints_ogs_status",
        "ck_engineering_joints_pto_status",
        "ck_engineering_joints_workflow_version_positive",
        "ck_engineering_joints_approval_version_positive",
    ):
        op.drop_constraint(name, j, schema=ENGINEERING_SCHEMA, type_="check")

    op.drop_constraint(
        "ck_engineering_joints_status", j, schema=ENGINEERING_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        "ck_engineering_joints_status", j, STATUS_CHECK_OLD, schema=ENGINEERING_SCHEMA
    )

    op.drop_constraint(
        "fk_engineering_joints_superseded_by_joint",
        j,
        schema=ENGINEERING_SCHEMA,
        type_="foreignkey",
    )
    for col in (
        "superseded_at",
        "superseded_by",
        "superseded_by_joint_id",
        "cancelled_at",
        "cancelled_by",
        "cancelled_reason",
        "submitted_at",
        "submitted_by",
    ):
        op.drop_column(j, col, schema=ENGINEERING_SCHEMA)
    for prefix in ("ogs", "pto"):
        for suffix in (
            "comment",
            "decided_at",
            "decided_by",
            "approval_version",
            "decision_method",
            "pending_reason",
            "status",
        ):
            op.drop_column(j, f"{prefix}_{suffix}", schema=ENGINEERING_SCHEMA)
    op.drop_column(j, "workflow_version", schema=ENGINEERING_SCHEMA)
    op.drop_column(j, "approval_version", schema=ENGINEERING_SCHEMA)

    op.drop_constraint(
        "ck_engineering_joints_record_version_positive",
        j,
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_joints_version_positive",
        j,
        "record_version > 0",
        schema=ENGINEERING_SCHEMA,
    )
    op.alter_column(
        j, "record_version", new_column_name="version", schema=ENGINEERING_SCHEMA
    )
