"""defect technical model (Task 9D-3A).

Revision ID: 20260720_21_defect_model
Revises: 20260719_20_eng_evaluation_core
Create Date: 2026-07-20

Task 9D-3A по ADR-022 / Implementation Spec 9D-3: техническая модель Defect. Единой
миграцией создаются шесть таблиц схемы quality: defect_types, defect_location_types
(системные read-only справочники + seed), defect_roots (корневая идентичность цепочки,
UNIQUE(engineering_evaluation_id), per-joint defect_no), defects (техническая ревизия,
supersede-цепочка, полное структурное покрытие ADR-022 §5), defect_sequences (per-joint
счётчик), defect_events (append-only журнал).

Перечисления — CHECK-ограничениями (без native enum). Ссылки на работников
(*_by_worker_id / actor_worker_id) — Integer БЕЗ FK (переходный период). Ровно одна
ACTIVE и не более одной открытой DRAFT на цепочку — частичные UNIQUE-индексы. Seed
идемпотентен (ON CONFLICT (code) DO NOTHING). Downgrade удаляет только объекты 9D-3A;
схема quality не удаляется.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.quality.defect_seed import DEFECT_LOCATION_TYPE_SEED, DEFECT_TYPE_SEED
from app.quality.defect_workflow import (
    DEFECT_EVENT_TYPES,
    DEFECT_INDICATION_LOCATIONS,
    DEFECT_STATUSES,
)

revision: str = "20260720_21_defect_model"
down_revision: Union[str, None] = "20260719_20_eng_evaluation_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
ENGINEERING_SCHEMA = "engineering"

DEFECT_TYPES_TABLE = "defect_types"
DEFECT_LOCATION_TYPES_TABLE = "defect_location_types"
DEFECT_ROOTS_TABLE = "defect_roots"
DEFECTS_TABLE = "defects"
DEFECT_SEQUENCES_TABLE = "defect_sequences"
DEFECT_EVENTS_TABLE = "defect_events"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _null_or_in(column: str, values) -> str:
    return f"{column} IS NULL OR {_in(column, values)}"


def _bool_col(name: str) -> sa.Column:
    return sa.Column(
        name, sa.Boolean(), server_default=sa.text("false"), nullable=False
    )


def upgrade() -> None:
    # ── 1. DefectType (read-only НСИ) ──────────────────────────────────────────
    op.create_table(
        DEFECT_TYPES_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=60), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        _bool_col("requires_length"),
        _bool_col("requires_width"),
        _bool_col("requires_height"),
        _bool_col("requires_depth"),
        _bool_col("requires_area"),
        _bool_col("requires_quantity"),
        _bool_col("requires_known_indication_location"),
        _bool_col("requires_description"),
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
            "length(trim(code)) > 0", name="ck_defect_types_code_not_empty"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defect_types_code",
        DEFECT_TYPES_TABLE,
        ["code"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )

    # ── 2. DefectLocationType (read-only НСИ) ──────────────────────────────────
    op.create_table(
        DEFECT_LOCATION_TYPES_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
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
            "length(trim(code)) > 0",
            name="ck_defect_location_types_code_not_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defect_location_types_code",
        DEFECT_LOCATION_TYPES_TABLE,
        ["code"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )

    # ── 3. DefectRoot (корневая идентичность цепочки) ──────────────────────────
    op.create_table(
        DEFECT_ROOTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "engineering_evaluation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_no", sa.Integer(), nullable=False),
        sa.Column("current_defect_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_defect_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_defect_roots_version"),
        sa.CheckConstraint("defect_no >= 1", name="ck_defect_roots_defect_no"),
        sa.ForeignKeyConstraint(
            ["engineering_evaluation_id"],
            [f"{QUALITY_SCHEMA}.engineering_evaluations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defect_roots_engineering_evaluation_id",
        DEFECT_ROOTS_TABLE,
        ["engineering_evaluation_id"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defect_roots_joint_defect_no",
        DEFECT_ROOTS_TABLE,
        ["joint_id", "defect_no"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_roots_joint_id",
        DEFECT_ROOTS_TABLE,
        ["joint_id"],
        schema=QUALITY_SCHEMA,
    )

    # ── 4. Defect (техническая ревизия) ────────────────────────────────────────
    op.create_table(
        DEFECTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_root_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_defect_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("defect_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("indication_location", sa.String(length=20), nullable=True),
        sa.Column("orientation", sa.String(length=30), nullable=True),
        sa.Column("surface", sa.String(length=20), nullable=True),
        sa.Column("joint_side", sa.String(length=30), nullable=True),
        sa.Column("axial_position_mm", sa.Numeric(), nullable=True),
        sa.Column("circumferential_position_deg", sa.Numeric(), nullable=True),
        sa.Column("length_mm", sa.Numeric(), nullable=True),
        sa.Column("width_mm", sa.Numeric(), nullable=True),
        sa.Column("height_mm", sa.Numeric(), nullable=True),
        sa.Column("depth_mm", sa.Numeric(), nullable=True),
        sa.Column("affected_area_mm2", sa.Numeric(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("standard_document", sa.Text(), nullable=True),
        sa.Column("standard_revision", sa.Text(), nullable=True),
        sa.Column("standard_clause", sa.Text(), nullable=True),
        sa.Column("acceptance_level", sa.Text(), nullable=True),
        sa.Column("normative_category_code", sa.String(length=60), nullable=True),
        sa.Column("technical_description", sa.Text(), nullable=True),
        sa.Column("location_description", sa.Text(), nullable=True),
        sa.Column("evaluation_note", sa.Text(), nullable=True),
        sa.Column("technical_note", sa.Text(), nullable=True),
        sa.Column("activated_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_defects_version"),
        sa.CheckConstraint("revision_no >= 1", name="ck_defects_revision_no"),
        sa.CheckConstraint(_in("status", DEFECT_STATUSES), name="ck_defects_status"),
        sa.CheckConstraint(
            _null_or_in("indication_location", DEFECT_INDICATION_LOCATIONS),
            name="ck_defects_indication_location",
        ),
        sa.CheckConstraint(
            "length_mm IS NULL OR length_mm > 0", name="ck_defects_length_positive"
        ),
        sa.CheckConstraint(
            "width_mm IS NULL OR width_mm > 0", name="ck_defects_width_positive"
        ),
        sa.CheckConstraint(
            "height_mm IS NULL OR height_mm > 0", name="ck_defects_height_positive"
        ),
        sa.CheckConstraint(
            "depth_mm IS NULL OR depth_mm > 0", name="ck_defects_depth_positive"
        ),
        sa.CheckConstraint(
            "affected_area_mm2 IS NULL OR affected_area_mm2 > 0",
            name="ck_defects_area_positive",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0", name="ck_defects_quantity_positive"
        ),
        sa.CheckConstraint(
            "axial_position_mm IS NULL OR axial_position_mm >= 0",
            name="ck_defects_axial_position_nonneg",
        ),
        sa.CheckConstraint(
            "circumferential_position_deg IS NULL OR "
            "(circumferential_position_deg >= 0 AND circumferential_position_deg < 360)",
            name="ck_defects_circumferential_range",
        ),
        sa.CheckConstraint(
            "orientation IS NULL OR length(trim(orientation)) > 0",
            name="ck_defects_orientation_not_empty",
        ),
        sa.CheckConstraint(
            "surface IS NULL OR length(trim(surface)) > 0",
            name="ck_defects_surface_not_empty",
        ),
        sa.CheckConstraint(
            "joint_side IS NULL OR length(trim(joint_side)) > 0",
            name="ck_defects_joint_side_not_empty",
        ),
        sa.CheckConstraint(
            "standard_document IS NULL OR length(trim(standard_document)) > 0",
            name="ck_defects_standard_document_not_empty",
        ),
        sa.CheckConstraint(
            "standard_revision IS NULL OR length(trim(standard_revision)) > 0",
            name="ck_defects_standard_revision_not_empty",
        ),
        sa.CheckConstraint(
            "standard_clause IS NULL OR length(trim(standard_clause)) > 0",
            name="ck_defects_standard_clause_not_empty",
        ),
        sa.CheckConstraint(
            "standard_revision IS NULL OR standard_document IS NOT NULL",
            name="ck_defects_standard_revision_requires_document",
        ),
        sa.CheckConstraint(
            "standard_clause IS NULL OR standard_document IS NOT NULL",
            name="ck_defects_standard_clause_requires_document",
        ),
        sa.CheckConstraint(
            "status <> 'CANCELLED' OR ("
            "cancelled_at IS NOT NULL "
            "AND cancelled_by_worker_id IS NOT NULL "
            "AND cancellation_reason IS NOT NULL "
            "AND length(trim(cancellation_reason)) > 0)",
            name="ck_defects_cancelled_fields",
        ),
        sa.CheckConstraint(
            "status <> 'SUPERSEDED' OR ("
            "superseded_at IS NOT NULL AND superseded_by_worker_id IS NOT NULL)",
            name="ck_defects_superseded_fields",
        ),
        sa.CheckConstraint(
            "(activated_at IS NULL) = (activated_by_worker_id IS NULL)",
            name="ck_defects_activated_pair",
        ),
        sa.CheckConstraint(
            "supersedes_defect_id IS NULL OR supersedes_defect_id <> id",
            name="ck_defects_no_self_supersede",
        ),
        sa.ForeignKeyConstraint(
            ["defect_root_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_ROOTS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_defect_id"],
            [f"{QUALITY_SCHEMA}.{DEFECTS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["defect_type_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_TYPES_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_type_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_LOCATION_TYPES_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defects_root_revision_no",
        DEFECTS_TABLE,
        ["defect_root_id", "revision_no"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defects_one_active_per_root",
        DEFECTS_TABLE,
        ["defect_root_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_defects_one_draft_per_root",
        DEFECTS_TABLE,
        ["defect_root_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defects_root_status",
        DEFECTS_TABLE,
        ["defect_root_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defects_defect_type_id",
        DEFECTS_TABLE,
        ["defect_type_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defects_location_type_id",
        DEFECTS_TABLE,
        ["location_type_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defects_supersedes_defect_id",
        DEFECTS_TABLE,
        ["supersedes_defect_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defects_created_at",
        DEFECTS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )

    # ── 5. DefectSequence (per-joint счётчик) ──────────────────────────────────
    op.create_table(
        DEFECT_SEQUENCES_TABLE,
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_value", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("last_value >= 0", name="ck_defect_sequences_last_value"),
        sa.ForeignKeyConstraint(
            ["joint_id"], [f"{ENGINEERING_SCHEMA}.joints.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("joint_id"),
        schema=QUALITY_SCHEMA,
    )

    # ── 6. DefectEvent (append-only) ───────────────────────────────────────────
    op.create_table(
        DEFECT_EVENTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_root_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("defect_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("event_type", DEFECT_EVENT_TYPES), name="ck_defect_events_type"
        ),
        sa.CheckConstraint(
            "defect_version IS NULL OR defect_version >= 1",
            name="ck_defect_events_defect_version",
        ),
        sa.ForeignKeyConstraint(
            ["defect_root_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_ROOTS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["defect_id"],
            [f"{QUALITY_SCHEMA}.{DEFECTS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_events_defect_root_id",
        DEFECT_EVENTS_TABLE,
        ["defect_root_id", "created_at"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_events_defect_id",
        DEFECT_EVENTS_TABLE,
        ["defect_id", "created_at"],
        schema=QUALITY_SCHEMA,
    )

    # ── 7. Seed справочников (идемпотентно: ON CONFLICT (code) DO NOTHING) ──────
    _seed_reference_data()


def _seed_reference_data() -> None:
    defect_types = sa.table(
        DEFECT_TYPES_TABLE,
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("requires_length", sa.Boolean),
        sa.column("requires_width", sa.Boolean),
        sa.column("requires_height", sa.Boolean),
        sa.column("requires_depth", sa.Boolean),
        sa.column("requires_area", sa.Boolean),
        sa.column("requires_quantity", sa.Boolean),
        sa.column("requires_known_indication_location", sa.Boolean),
        sa.column("requires_description", sa.Boolean),
        schema=QUALITY_SCHEMA,
    )
    op.execute(
        pg_insert(defect_types)
        .values(DEFECT_TYPE_SEED)
        .on_conflict_do_nothing(index_elements=["code"])
    )

    defect_location_types = sa.table(
        DEFECT_LOCATION_TYPES_TABLE,
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        schema=QUALITY_SCHEMA,
    )
    op.execute(
        pg_insert(defect_location_types)
        .values(DEFECT_LOCATION_TYPE_SEED)
        .on_conflict_do_nothing(index_elements=["code"])
    )


def downgrade() -> None:
    # Обратный порядок (дети → родители). DROP TABLE снимает свои индексы, CHECK и FK,
    # а также seed-строки. Схему quality не удаляем (её создал Task 9A).
    op.drop_table(DEFECT_EVENTS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(DEFECT_SEQUENCES_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(DEFECTS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(DEFECT_ROOTS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(DEFECT_LOCATION_TYPES_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(DEFECT_TYPES_TABLE, schema=QUALITY_SCHEMA)
