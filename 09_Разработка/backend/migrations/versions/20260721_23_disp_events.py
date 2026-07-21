"""add defect disposition events (Task 9D-4A-3).

Revision ID: 20260721_23_disp_events
Revises: 20260721_22_defect_dispositions
Create Date: 2026-07-21

Task 9D-4A-3: append-only журнал переходов `DefectDisposition`. Создаётся таблица
`quality.defect_disposition_events` (FK на dispositions и defect_roots, CHECK типов
событий, индексы по disposition/root + created_at). Lifecycle-переходы и RBAC —
в сервисе; эта миграция только уровень данных аудита.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260721_23_disp_events"
down_revision: Union[str, None] = "20260721_22_defect_dispositions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
DEFECT_ROOTS_TABLE = "defect_roots"
DEFECT_DISPOSITIONS_TABLE = "defect_dispositions"
EVENTS_TABLE = "defect_disposition_events"

EVENT_TYPES = (
    "DISPOSITION_CREATED",
    "DISPOSITION_PREPARED",
    "DISPOSITION_APPROVED",
    "DISPOSITION_ACTIVATED",
    "DISPOSITION_CANCELLED",
)


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT to_regclass(:reg)"),
        {"reg": f"{QUALITY_SCHEMA}.{EVENTS_TABLE}"},
    ).scalar()
    if exists:
        # Повторный upgrade после усечения revision_id (varchar(32)): таблица уже есть.
        return

    op.create_table(
        EVENTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "defect_disposition_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("defect_root_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=True),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("event_type", EVENT_TYPES),
            name="ck_defect_disposition_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["defect_disposition_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_DISPOSITIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["defect_root_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_ROOTS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_disposition_events_disposition_id",
        EVENTS_TABLE,
        ["defect_disposition_id", "created_at"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_disposition_events_root_id",
        EVENTS_TABLE,
        ["defect_root_id", "created_at"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_defect_disposition_events_root_id",
        table_name=EVENTS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_defect_disposition_events_disposition_id",
        table_name=EVENTS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(EVENTS_TABLE, schema=QUALITY_SCHEMA)
