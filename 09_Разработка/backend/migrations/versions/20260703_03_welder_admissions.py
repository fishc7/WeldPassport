"""welding.welder_admissions: welder admissions (OGS v0.1).

Revision ID: 20260703_03_welder_admissions
Revises: 20260703_02_welding_welders
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260703_03_welder_admissions"
down_revision: Union[str, None] = "20260703_02_welding_welders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HR_SCHEMA = "hr"
WELDING_SCHEMA = "welding"


def upgrade() -> None:
    op.create_table(
        "welder_admissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("stamp_code", sa.Text(), nullable=False),
        sa.Column(
            "admission_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "welding_methods",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "material_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("diameter_min", sa.Numeric(), nullable=True),
        sa.Column("diameter_max", sa.Numeric(), nullable=True),
        sa.Column("thickness_min", sa.Numeric(), nullable=True),
        sa.Column("thickness_max", sa.Numeric(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("basis_document", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["worker_id"],
            [f"{HR_SCHEMA}.workers.id"],
        ),
        sa.CheckConstraint(
            "admission_status IN ('draft', 'active', 'suspended', 'expired', 'revoked')",
            name="ck_welding_welder_admissions_admission_status",
        ),
        sa.CheckConstraint(
            "length(trim(stamp_code)) > 0",
            name="ck_welding_welder_admissions_stamp_code_not_empty",
        ),
        sa.CheckConstraint(
            "diameter_min IS NULL OR diameter_max IS NULL OR diameter_min <= diameter_max",
            name="ck_welding_welder_admissions_diameter_range",
        ),
        sa.CheckConstraint(
            "thickness_min IS NULL OR thickness_max IS NULL OR thickness_min <= thickness_max",
            name="ck_welding_welder_admissions_thickness_range",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_welding_welder_admissions_valid_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=WELDING_SCHEMA,
    )
    op.create_index(
        "ix_welding_welder_admissions_worker_id",
        "welder_admissions",
        ["worker_id"],
        unique=False,
        schema=WELDING_SCHEMA,
    )
    op.create_index(
        "ix_welding_welder_admissions_stamp_code",
        "welder_admissions",
        ["stamp_code"],
        unique=False,
        schema=WELDING_SCHEMA,
    )
    op.create_index(
        "ix_welding_welder_admissions_admission_status",
        "welder_admissions",
        ["admission_status"],
        unique=False,
        schema=WELDING_SCHEMA,
    )
    op.create_index(
        "ix_welding_welder_admissions_valid_from",
        "welder_admissions",
        ["valid_from"],
        unique=False,
        schema=WELDING_SCHEMA,
    )
    op.create_index(
        "ix_welding_welder_admissions_valid_until",
        "welder_admissions",
        ["valid_until"],
        unique=False,
        schema=WELDING_SCHEMA,
    )
    op.create_index(
        "ux_welding_welder_admissions_active_stamp_code",
        "welder_admissions",
        ["stamp_code"],
        unique=True,
        schema=WELDING_SCHEMA,
        postgresql_where=sa.text("admission_status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_welding_welder_admissions_active_stamp_code",
        table_name="welder_admissions",
        schema=WELDING_SCHEMA,
    )
    op.drop_index(
        "ix_welding_welder_admissions_valid_until",
        table_name="welder_admissions",
        schema=WELDING_SCHEMA,
    )
    op.drop_index(
        "ix_welding_welder_admissions_valid_from",
        table_name="welder_admissions",
        schema=WELDING_SCHEMA,
    )
    op.drop_index(
        "ix_welding_welder_admissions_admission_status",
        table_name="welder_admissions",
        schema=WELDING_SCHEMA,
    )
    op.drop_index(
        "ix_welding_welder_admissions_stamp_code",
        table_name="welder_admissions",
        schema=WELDING_SCHEMA,
    )
    op.drop_index(
        "ix_welding_welder_admissions_worker_id",
        table_name="welder_admissions",
        schema=WELDING_SCHEMA,
    )
    op.drop_table("welder_admissions", schema=WELDING_SCHEMA)
