"""add QualityDecision command idempotency records (Task 10A-1R).

Revision ID: 20260724_26_qd_idempotency
Revises: 20260723_25_qd_core
Create Date: 2026-07-24

Self-contained correcting migration for ADR-027 Governance Recovery Addendum L.2.
Revision 25 is intentionally not modified.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_26_qd_idempotency"
down_revision: Union[str, None] = "20260723_25_qd_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
TABLE = "quality_decision_idempotency_records"
DECISIONS_TABLE = "quality_decisions"

COMMAND_TYPES = (
    "CREATE",
    "UPDATE_DRAFT",
    "SUBMIT_FOR_REVIEW",
    "RETURN",
    "DECIDE",
)
TARGET_TYPES = ("JOINT", "QUALITY_DECISION")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "quality_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("command_type", COMMAND_TYPES),
            name="ck_qd_idem_command_type",
        ),
        sa.CheckConstraint(
            _in("target_type", TARGET_TYPES),
            name="ck_qd_idem_target_type",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_qd_idem_key_not_empty",
        ),
        sa.CheckConstraint(
            "response_status BETWEEN 200 AND 299",
            name="ck_qd_idem_response_status",
        ),
        sa.ForeignKeyConstraint(
            ["quality_decision_id"],
            [f"{QUALITY_SCHEMA}.{DECISIONS_TABLE}.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_qd_idem_command_target_key",
        TABLE,
        [
            "actor_worker_id",
            "command_type",
            "target_type",
            "target_id",
            "idempotency_key",
        ],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_qd_idem_quality_decision_id",
        TABLE,
        ["quality_decision_id"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_qd_idem_quality_decision_id",
        table_name=TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "uq_qd_idem_command_target_key",
        table_name=TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(TABLE, schema=QUALITY_SCHEMA)

