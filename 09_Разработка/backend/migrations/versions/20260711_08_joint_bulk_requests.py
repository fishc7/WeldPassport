"""joint bulk import idempotency requests (Task 7).

Revision ID: 20260711_08_joint_bulk_requests
Revises: 20260711_07_joint_doc_revisions
Create Date: 2026-07-11

Task 7 по ADR-010 и IMPLEMENTATION_PLAN §Task 7: таблица идемпотентных запросов
массового создания Joint. Хранит только успешные пакеты (status='COMPLETED');
полный ответ — в response_payload (JSONB), не пересобирается из текущего состояния.
UNIQUE(project_id, idempotency_key) — последняя защита от гонки; один ключ допустим
в разных проектах. created_by — hr.workers.id без FK (Р-3, переходный период).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_08_joint_bulk_requests"
down_revision: Union[str, None] = "20260711_07_joint_doc_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"
PROJECT_SCHEMA = "project"


def upgrade() -> None:
    op.create_table(
        "joint_bulk_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'COMPLETED'"),
        ),
        sa.Column("response_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status = 'COMPLETED'",
            name="ck_engineering_joint_bulk_requests_status",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_engineering_joint_bulk_requests_key_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_engineering_joint_bulk_requests_project_key",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_bulk_requests_project_id",
        "joint_bulk_requests",
        ["project_id"],
        schema=ENGINEERING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_engineering_joint_bulk_requests_project_id",
        table_name="joint_bulk_requests",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table("joint_bulk_requests", schema=ENGINEERING_SCHEMA)
