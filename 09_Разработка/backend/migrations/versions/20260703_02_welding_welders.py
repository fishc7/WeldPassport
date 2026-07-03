"""welding.welders: сварочный профиль работника (ОГС).

Revision ID: 20260703_02_welding_welders
Revises: 20260703_01_hr_worker_roles
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260703_02_welding_welders"
down_revision: Union[str, None] = "20260703_01_hr_worker_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HR_SCHEMA = "hr"
WELDING_SCHEMA = "welding"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{WELDING_SCHEMA}"')

    op.create_table(
        "welders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("stamp_code", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="active",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'suspended')",
            name="ck_welding_welders_status",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            [f"{HR_SCHEMA}.workers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", name="uq_welding_welders_worker_id"),
        sa.UniqueConstraint("stamp_code", name="uq_welding_welders_stamp_code"),
        schema=WELDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("welders", schema=WELDING_SCHEMA)
    op.execute(f'DROP SCHEMA IF EXISTS "{WELDING_SCHEMA}" CASCADE')
