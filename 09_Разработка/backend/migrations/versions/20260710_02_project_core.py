"""project core: companies, projects, project_companies.

Revision ID: 20260710_02_project_core
Revises: 20260710_01_hr_master_role
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_02_project_core"
down_revision: Union[str, None] = "20260710_01_hr_master_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROJECT_SCHEMA = "project"

ROLE_CODE_CHECK = (
    "role_code IN ("
    "'CUSTOMER', 'GENERAL_CONTRACTOR', 'WELDING_CONTRACTOR', "
    "'NDT_LAB', 'INSPECTION', 'DESIGNER'"
    ")"
)


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{PROJECT_SCHEMA}"')

    # companies → projects → project_companies (порядок из-за FK).
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("inn", sa.String(length=20), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_project_companies_status",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_project_companies_name_not_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "uq_project_companies_inn",
        "companies",
        ["inn"],
        unique=True,
        schema=PROJECT_SCHEMA,
        postgresql_where=sa.text("inn IS NOT NULL"),
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
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
            "status IN ('draft', 'active', 'closed')",
            name="ck_project_projects_status",
        ),
        sa.CheckConstraint(
            "length(trim(code)) > 0",
            name="ck_project_projects_code_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_project_projects_name_not_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_project_projects_code"),
        schema=PROJECT_SCHEMA,
    )

    op.create_table(
        "project_companies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("role_code", sa.String(length=50), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_project_project_companies_valid_range",
        ),
        sa.CheckConstraint(
            ROLE_CODE_CHECK,
            name="ck_project_project_companies_role_code",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{PROJECT_SCHEMA}.companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_project_project_companies_project_id",
        "project_companies",
        ["project_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_project_project_companies_company_id",
        "project_companies",
        ["company_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "uq_project_project_companies_active",
        "project_companies",
        ["project_id", "company_id", "role_code"],
        unique=True,
        schema=PROJECT_SCHEMA,
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    # project_companies → projects → companies (обратный порядок).
    op.drop_index(
        "uq_project_project_companies_active",
        table_name="project_companies",
        schema=PROJECT_SCHEMA,
    )
    op.drop_index(
        "ix_project_project_companies_company_id",
        table_name="project_companies",
        schema=PROJECT_SCHEMA,
    )
    op.drop_index(
        "ix_project_project_companies_project_id",
        table_name="project_companies",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("project_companies", schema=PROJECT_SCHEMA)

    op.drop_table("projects", schema=PROJECT_SCHEMA)

    op.drop_index(
        "uq_project_companies_inn",
        table_name="companies",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("companies", schema=PROJECT_SCHEMA)

    op.execute(f'DROP SCHEMA IF EXISTS "{PROJECT_SCHEMA}" CASCADE')
