"""HR core: departments, positions, workers.

Revision ID: 20260702_02_hr_core
Revises:
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_02_hr_core"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HR_SCHEMA = "hr"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{HR_SCHEMA}"')

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_hr_departments_company_code"),
        schema=HR_SCHEMA,
    )
    op.create_index(
        "ix_hr_departments_company_id",
        "departments",
        ["company_id"],
        unique=False,
        schema=HR_SCHEMA,
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_hr_positions_code"),
        schema=HR_SCHEMA,
    )

    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("personnel_number", sa.String(length=50), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("middle_name", sa.String(length=100), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column(
            "employment_status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column("dismissal_date", sa.Date(), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
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
            "employment_status IN ('active', 'dismissed', 'suspended')",
            name="ck_hr_workers_employment_status",
        ),
        sa.CheckConstraint(
            "(employment_status = 'dismissed') OR (dismissal_date IS NULL)",
            name="ck_hr_workers_dismissal_date",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            [f"{HR_SCHEMA}.departments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            [f"{HR_SCHEMA}.positions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=HR_SCHEMA,
    )
    op.create_index(
        "ix_hr_workers_company_id",
        "workers",
        ["company_id"],
        unique=False,
        schema=HR_SCHEMA,
    )
    op.create_index(
        "uq_hr_workers_company_personnel_number",
        "workers",
        ["company_id", "personnel_number"],
        unique=True,
        schema=HR_SCHEMA,
        postgresql_where=sa.text("personnel_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_hr_workers_company_personnel_number",
        table_name="workers",
        schema=HR_SCHEMA,
    )
    op.drop_index("ix_hr_workers_company_id", table_name="workers", schema=HR_SCHEMA)
    op.drop_table("workers", schema=HR_SCHEMA)
    op.drop_table("positions", schema=HR_SCHEMA)
    op.drop_index("ix_hr_departments_company_id", table_name="departments", schema=HR_SCHEMA)
    op.drop_table("departments", schema=HR_SCHEMA)
    op.execute(f'DROP SCHEMA IF EXISTS "{HR_SCHEMA}" CASCADE')
