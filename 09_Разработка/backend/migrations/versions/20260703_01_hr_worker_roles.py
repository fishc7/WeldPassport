"""HR worker roles: hr.worker_roles.

Revision ID: 20260703_01_hr_worker_roles
Revises: 20260702_02_hr_core
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_01_hr_worker_roles"
down_revision: Union[str, None] = "20260702_02_hr_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HR_SCHEMA = "hr"


def upgrade() -> None:
    op.create_table(
        "worker_roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("role_code", sa.String(length=50), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(length=20),
            nullable=False,
            server_default="GLOBAL",
        ),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("note", sa.Text(), nullable=True),
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
            "role_code IN ("
            "'WELDER', 'FOREMAN', 'PTO_ENGINEER', 'OTK_INSPECTOR', "
            "'NDT_SPECIALIST', 'OGS_ENGINEER', 'CONFIRMING_PERSON', 'CLOSING_RESPONSIBLE'"
            ")",
            name="ck_hr_worker_roles_role_code",
        ),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL', 'COMPANY', 'PROJECT', 'SITE')",
            name="ck_hr_worker_roles_scope_type",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            [f"{HR_SCHEMA}.workers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=HR_SCHEMA,
    )
    op.create_index(
        "ix_hr_worker_roles_worker_id",
        "worker_roles",
        ["worker_id"],
        unique=False,
        schema=HR_SCHEMA,
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_hr_worker_roles_active_scope
        ON "{HR_SCHEMA}".worker_roles (
            worker_id,
            role_code,
            scope_type,
            COALESCE(scope_id, 0)
        )
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_hr_worker_roles_active_scope",
        table_name="worker_roles",
        schema=HR_SCHEMA,
    )
    op.drop_index(
        "ix_hr_worker_roles_worker_id",
        table_name="worker_roles",
        schema=HR_SCHEMA,
    )
    op.drop_table("worker_roles", schema=HR_SCHEMA)
