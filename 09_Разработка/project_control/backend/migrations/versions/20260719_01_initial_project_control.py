"""Initial Project Control Center schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260719_01"
down_revision = None
branch_labels = None
depends_on = None
SCHEMA = "project_control"


def upgrade() -> None:
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    op.create_table(
        "project_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(7, 4), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "management_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["module_id"], [f"{SCHEMA}.project_modules.id"]),
        sa.UniqueConstraint("module_id", "version", name="uq_management_assessment_module_version"),
        schema=SCHEMA,
    )
    op.create_table(
        "progress_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("overall_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "source_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("source_syncs", schema=SCHEMA)
    op.drop_table("progress_snapshots", schema=SCHEMA)
    op.drop_table("management_assessments", schema=SCHEMA)
    op.drop_table("project_modules", schema=SCHEMA)
    op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{SCHEMA}"'))
