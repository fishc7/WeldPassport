"""project lines: технологические линии проекта.

Revision ID: 20260710_03_project_lines
Revises: 20260710_02_project_core
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_03_project_lines"
down_revision: Union[str, None] = "20260710_02_project_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROJECT_SCHEMA = "project"

LINE_STATUS_CHECK = "status IN ('draft', 'active', 'cancelled')"


def upgrade() -> None:
    # Схема project уже создана миграцией 20260710_02_project_core.
    op.create_table(
        "lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_no", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("medium", sa.String(length=255), nullable=True),
        sa.Column("nominal_dn", sa.Numeric(), nullable=True),
        sa.Column("class_code", sa.String(length=50), nullable=True),
        sa.Column("category_code", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "required_inspection_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
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
            "length(trim(line_no)) > 0",
            name="ck_project_lines_line_no_not_empty",
        ),
        sa.CheckConstraint(
            "nominal_dn IS NULL OR nominal_dn > 0",
            name="ck_project_lines_nominal_dn_positive",
        ),
        sa.CheckConstraint(
            LINE_STATUS_CHECK,
            name="ck_project_lines_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "line_no", name="uq_project_lines_project_line_no"
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_project_lines_project_id",
        "lines",
        ["project_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    # Удаляем только project.lines; схема project и остальные таблицы остаются.
    op.drop_index(
        "ix_project_lines_project_id",
        table_name="lines",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("lines", schema=PROJECT_SCHEMA)
