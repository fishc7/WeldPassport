"""quality finding core (Task 9D-1).

Revision ID: 20260719_19_quality_finding_core
Revises: 20260714_18_labconc_extras
Create Date: 2026-07-19

Task 9D-1 по ADR-019 / Architecture Session 008-07: тёмное ядро QualityFinding —
зарегистрированный факт для рассмотрения. Добавляются три таблицы схемы quality:
quality.quality_findings (finding), quality.quality_finding_sequences (проектный
счётчик номера `<PROJECT_CODE>-QF-<SEQUENCE>`) и quality.quality_finding_events
(неизменяемый журнал).

Перечисления реализованы CHECK-ограничениями в стиле Tasks 9A–9C (без native enum).
Ссылки на работников (*_by_worker_id / actor_worker_id) — hr.workers.id типа Integer
БЕЗ FK (переходный период). FK на project.projects, engineering.joints,
engineering.weld_operations, quality.inspections и quality.method_executions (UUID).
Источники контроля необязательны (nullable), с ondelete RESTRICT.

EngineeringEvaluation, Defect, FindingDisposition, ProductionHold и дочерние сущности
finding (Location/Evidence/Correction/Assignment) в это ядро НЕ входят (блоки
9D-2 … 9D-6). Данные Tasks 8–9C не изменяются. Downgrade удаляет только объекты
Task 9D-1; схема quality не удаляется (её создал Task 9A и используют 9A–9C).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.quality.quality_finding_workflow import (
    FINDING_EVENT_TYPES,
    FINDING_INITIAL_RISKS,
    FINDING_INITIAL_RISK_DEFAULT,
    FINDING_ORIGIN_TYPES,
    FINDING_STATUSES,
)

revision: str = "20260719_19_quality_finding_core"
down_revision: Union[str, None] = "20260714_18_labconc_extras"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
PROJECT_SCHEMA = "project"
ENGINEERING_SCHEMA = "engineering"

FINDINGS_TABLE = "quality_findings"
SEQUENCES_TABLE = "quality_finding_sequences"
EVENTS_TABLE = "quality_finding_events"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


_STATUS_CHECK = _in("status", FINDING_STATUSES)
_ORIGIN_CHECK = _in("origin_type", FINDING_ORIGIN_TYPES)
_RISK_CHECK = _in("initial_risk", FINDING_INITIAL_RISKS)
_EVENT_TYPE_CHECK = _in("event_type", FINDING_EVENT_TYPES)
_REGISTERED_FIELDS_CHECK = (
    "status = 'DRAFT' OR ("
    "system_code IS NOT NULL "
    "AND registered_at IS NOT NULL "
    "AND registered_by_worker_id IS NOT NULL)"
)
_CANCELLED_FIELDS_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)
_ACKNOWLEDGED_FIELDS_CHECK = (
    "(acknowledged_at IS NULL) = (acknowledged_by_worker_id IS NULL)"
)


def upgrade() -> None:
    # ── Проектный счётчик номера finding ──────────────────────────────────────
    op.create_table(
        SEQUENCES_TABLE,
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_value", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_value >= 0", name="ck_quality_finding_sequences_last_value"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], [f"{PROJECT_SCHEMA}.projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("project_id"),
        schema=QUALITY_SCHEMA,
    )

    # ── QualityFinding ─────────────────────────────────────────────────────────
    op.create_table(
        FINDINGS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system_code", sa.String(length=64), nullable=True),
        sa.Column("external_no", sa.String(length=100), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("origin_type", sa.String(length=40), nullable=False),
        sa.Column(
            "initial_risk",
            sa.String(length=20),
            server_default=sa.text(f"'{FINDING_INITIAL_RISK_DEFAULT}'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("inspection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "method_execution_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("weld_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("registered_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("version >= 1", name="ck_quality_findings_version"),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_quality_findings_status"),
        sa.CheckConstraint(_ORIGIN_CHECK, name="ck_quality_findings_origin_type"),
        sa.CheckConstraint(_RISK_CHECK, name="ck_quality_findings_initial_risk"),
        sa.CheckConstraint(
            "length(trim(observation)) > 0",
            name="ck_quality_findings_observation_not_empty",
        ),
        sa.CheckConstraint(
            _REGISTERED_FIELDS_CHECK, name="ck_quality_findings_registered_fields"
        ),
        sa.CheckConstraint(
            _CANCELLED_FIELDS_CHECK, name="ck_quality_findings_cancelled_fields"
        ),
        sa.CheckConstraint(
            _ACKNOWLEDGED_FIELDS_CHECK,
            name="ck_quality_findings_acknowledged_fields",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], [f"{PROJECT_SCHEMA}.projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"], [f"{ENGINEERING_SCHEMA}.joints.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            [f"{QUALITY_SCHEMA}.inspections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["method_execution_id"],
            [f"{QUALITY_SCHEMA}.method_executions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["weld_operation_id"],
            [f"{ENGINEERING_SCHEMA}.weld_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    # Партиальные уникальные индексы (пустые значения не участвуют в уникальности).
    op.create_index(
        "uq_quality_findings_system_code",
        FINDINGS_TABLE,
        ["system_code"],
        unique=True,
        postgresql_where=sa.text("system_code IS NOT NULL"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_quality_findings_project_external_no",
        FINDINGS_TABLE,
        ["project_id", "external_no"],
        unique=True,
        postgresql_where=sa.text("external_no IS NOT NULL"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_findings_project_id",
        FINDINGS_TABLE,
        ["project_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_findings_joint_id",
        FINDINGS_TABLE,
        ["joint_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_findings_status",
        FINDINGS_TABLE,
        ["status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_findings_project_status",
        FINDINGS_TABLE,
        ["project_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_findings_joint_status",
        FINDINGS_TABLE,
        ["joint_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_findings_created_at",
        FINDINGS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )

    # ── Неизменяемый журнал событий finding ────────────────────────────────────
    op.create_table(
        EVENTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("finding_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _EVENT_TYPE_CHECK, name="ck_quality_finding_events_type"
        ),
        sa.CheckConstraint(
            "finding_version >= 1", name="ck_quality_finding_events_version"
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            [f"{QUALITY_SCHEMA}.{FINDINGS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_finding_events_finding_id",
        EVENTS_TABLE,
        ["finding_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_finding_events_created_at",
        EVENTS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    # Порядок обратный созданию: события → finding → счётчик. Схему quality не
    # удаляем (её создал Task 9A и используют 9A–9C).
    op.drop_index(
        "ix_quality_finding_events_created_at",
        table_name=EVENTS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_finding_events_finding_id",
        table_name=EVENTS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(EVENTS_TABLE, schema=QUALITY_SCHEMA)

    for index_name in (
        "ix_quality_findings_created_at",
        "ix_quality_findings_joint_status",
        "ix_quality_findings_project_status",
        "ix_quality_findings_status",
        "ix_quality_findings_joint_id",
        "ix_quality_findings_project_id",
        "uq_quality_findings_project_external_no",
        "uq_quality_findings_system_code",
    ):
        op.drop_index(
            index_name, table_name=FINDINGS_TABLE, schema=QUALITY_SCHEMA
        )
    op.drop_table(FINDINGS_TABLE, schema=QUALITY_SCHEMA)

    op.drop_table(SEQUENCES_TABLE, schema=QUALITY_SCHEMA)
