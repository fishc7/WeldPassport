"""engineering joints: joints, joint_sequences (Task 5A, ADR-010).

Revision ID: 20260711_05_engineering_joints
Revises: 20260710_04_engineering_docs
Create Date: 2026-07-11

Ядро Joint по ADR-010: обязательная связь с Line, origin/current ревизии,
автогенерация system_code через служебный счётчик joint_sequences, нормализация
joint_no, optimistic locking (version). Lifecycle-переходы согласования, история
снимков и bulk — последующие Task 5B/6/7 (здесь не создаются).

Партиальный уникальный индекс uq_engineering_joints_revision_joint_no
(project_id, current_document_revision_id, joint_no_normalized) заранее исключает
статусы CANCELLED/SUPERSEDED (появятся в Task 5B). В Task 6 бизнес-ключ номера
переносится в partial unique index на joint_document_revisions
(WHERE link_status='ACTIVE'); тогда этот индекс снимается отдельной миграцией.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_05_engineering_joints"
down_revision: Union[str, None] = "20260710_04_engineering_docs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROJECT_SCHEMA = "project"
ENGINEERING_SCHEMA = "engineering"

STATUS_CHECK = "status IN ('DRAFT')"
GEOMETRY_TYPE_CHECK = (
    "geometry_type IS NULL OR geometry_type IN "
    "('BUTT', 'FILLET', 'TEE', 'LAP', 'SLOT', 'OTHER')"
)
WELD_JOINT_TYPE_CHECK = (
    "weld_joint_type IS NULL OR weld_joint_type IN ('BW', 'SW', 'FW', 'OTHER')"
)
CONNECTION_CODE_CHECK = (
    "connection_code IS NULL OR connection_code IN "
    "('C', 'U', 'T', 'N', 'P', 'OTHER')"
)
COORDINATE_SYSTEM_CHECK = (
    "(position_x IS NULL AND position_y IS NULL) OR coordinate_system IS NOT NULL"
)


def upgrade() -> None:
    # Служебный счётчик system_code по проекту (отдельная последовательность).
    op.create_table(
        "joint_sequences",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
        schema=ENGINEERING_SCHEMA,
    )

    op.create_table(
        "joints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "origin_document_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "current_document_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("system_code", sa.String(length=64), nullable=False),
        sa.Column("joint_no", sa.String(length=100), nullable=False),
        sa.Column("joint_no_normalized", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        # Инженерные поля по сторонам соединения.
        sa.Column("dn_1", sa.Numeric(), nullable=True),
        sa.Column("dn_2", sa.Numeric(), nullable=True),
        sa.Column("thickness_1", sa.Numeric(), nullable=True),
        sa.Column("thickness_2", sa.Numeric(), nullable=True),
        sa.Column("material_id_1", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("material_id_2", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("material_text_1", sa.String(length=255), nullable=True),
        sa.Column("material_text_2", sa.String(length=255), nullable=True),
        sa.Column("component_type_1", sa.String(length=50), nullable=True),
        sa.Column("component_type_2", sa.String(length=50), nullable=True),
        sa.Column(
            "component_item_id_1", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "component_item_id_2", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("component_text_1", sa.String(length=255), nullable=True),
        sa.Column("component_text_2", sa.String(length=255), nullable=True),
        # Классификация.
        sa.Column("geometry_type", sa.String(length=20), nullable=True),
        sa.Column("weld_joint_type", sa.String(length=20), nullable=True),
        sa.Column("connection_code", sa.String(length=20), nullable=True),
        # Проектные способы сварки (без FK на WPS — Р-4).
        sa.Column("required_root_method", sa.String(length=50), nullable=True),
        sa.Column("required_fill_method", sa.String(length=50), nullable=True),
        sa.Column("required_cap_method", sa.String(length=50), nullable=True),
        sa.Column("planned_wps_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Термообработка.
        sa.Column(
            "heat_treatment_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("heat_treatment_type", sa.String(length=50), nullable=True),
        sa.Column("heat_treatment_note", sa.Text(), nullable=True),
        # Положение на чертеже.
        sa.Column("sheet_no", sa.String(length=50), nullable=True),
        sa.Column("drawing_zone", sa.String(length=50), nullable=True),
        sa.Column("position_x", sa.Numeric(), nullable=True),
        sa.Column("position_y", sa.Numeric(), nullable=True),
        sa.Column("coordinate_system", sa.String(length=50), nullable=True),
        sa.Column("location_note", sa.Text(), nullable=True),
        sa.Column("document_note", sa.Text(), nullable=True),
        # Аудит.
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
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
            "length(trim(joint_no)) > 0",
            name="ck_engineering_joints_joint_no_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(joint_no_normalized)) > 0",
            name="ck_engineering_joints_joint_no_normalized_not_empty",
        ),
        sa.CheckConstraint(STATUS_CHECK, name="ck_engineering_joints_status"),
        sa.CheckConstraint(
            "version > 0", name="ck_engineering_joints_version_positive"
        ),
        sa.CheckConstraint(
            GEOMETRY_TYPE_CHECK, name="ck_engineering_joints_geometry_type"
        ),
        sa.CheckConstraint(
            WELD_JOINT_TYPE_CHECK, name="ck_engineering_joints_weld_joint_type"
        ),
        sa.CheckConstraint(
            CONNECTION_CODE_CHECK, name="ck_engineering_joints_connection_code"
        ),
        sa.CheckConstraint(
            COORDINATE_SYSTEM_CHECK,
            name="ck_engineering_joints_coordinate_system",
        ),
        sa.CheckConstraint(
            "dn_1 IS NULL OR dn_1 > 0", name="ck_engineering_joints_dn_1_positive"
        ),
        sa.CheckConstraint(
            "dn_2 IS NULL OR dn_2 > 0", name="ck_engineering_joints_dn_2_positive"
        ),
        sa.CheckConstraint(
            "thickness_1 IS NULL OR thickness_1 > 0",
            name="ck_engineering_joints_thickness_1_positive",
        ),
        sa.CheckConstraint(
            "thickness_2 IS NULL OR thickness_2 > 0",
            name="ck_engineering_joints_thickness_2_positive",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            [f"{PROJECT_SCHEMA}.lines.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["origin_document_revision_id"],
            [f"{ENGINEERING_SCHEMA}.document_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_document_revision_id"],
            [f"{ENGINEERING_SCHEMA}.document_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "system_code",
            name="uq_engineering_joints_project_system_code",
        ),
        schema=ENGINEERING_SCHEMA,
    )

    op.create_index(
        "uq_engineering_joints_revision_joint_no",
        "joints",
        ["project_id", "current_document_revision_id", "joint_no_normalized"],
        unique=True,
        schema=ENGINEERING_SCHEMA,
        postgresql_where=sa.text("status NOT IN ('CANCELLED', 'SUPERSEDED')"),
    )
    op.create_index(
        "ix_engineering_joints_project_id",
        "joints",
        ["project_id"],
        unique=False,
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joints_line_id",
        "joints",
        ["line_id"],
        unique=False,
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joints_current_revision_id",
        "joints",
        ["current_document_revision_id"],
        unique=False,
        schema=ENGINEERING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_engineering_joints_current_revision_id",
        table_name="joints",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "ix_engineering_joints_line_id",
        table_name="joints",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "ix_engineering_joints_project_id",
        table_name="joints",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "uq_engineering_joints_revision_joint_no",
        table_name="joints",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table("joints", schema=ENGINEERING_SCHEMA)
    op.drop_table("joint_sequences", schema=ENGINEERING_SCHEMA)
