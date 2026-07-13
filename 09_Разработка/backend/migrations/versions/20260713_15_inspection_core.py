"""inspection core (Task 9A).

Revision ID: 20260713_15_inspection_core
Revises: 20260713_14_heat_treatment
Create Date: 2026-07-13

Task 9A по ADR-015 / Architecture Session 007: ядро контура контроля качества и
НК — заявка на контроль сварного соединения. Создаётся отдельная схема quality и
три таблицы: quality.inspections (заявка), quality.inspection_sequences
(проектный счётчик system_code) и quality.inspection_events (неизменяемый журнал).

Перечисления реализованы CHECK-ограничениями в стиле модулей engineering/quality
(как weld_operations/heat_treatment_*), без native enum-типов. Ссылки на
работников (*_by_worker_id / actor_worker_id) — hr.workers.id типа Integer БЕЗ FK
(переходный период, как в Joint/WeldOperation): X-User-Id и hr.workers.id —
целочисленные. FK добавляются на project.projects и engineering.joints (UUID).

Данные Tasks 8A–8F не изменяются: существующие таблицы не трогаются, добавляются
только новые объекты Task 9A. Downgrade удаляет только объекты Task 9A и пустую
схему quality; DROP SCHEMA ... CASCADE не используется.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.quality.inspection_workflow import (
    INSPECTION_EVENT_TYPES,
    INSPECTION_STATUSES,
)

revision: str = "20260713_15_inspection_core"
down_revision: Union[str, None] = "20260713_14_heat_treatment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
PROJECT_SCHEMA = "project"
ENGINEERING_SCHEMA = "engineering"

INSPECTIONS_TABLE = "inspections"
SEQUENCES_TABLE = "inspection_sequences"
EVENTS_TABLE = "inspection_events"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


_STATUS_CHECK = _in("status", INSPECTION_STATUSES)
_EVENT_TYPE_CHECK = _in("event_type", INSPECTION_EVENT_TYPES)
_REQUESTED_FIELDS_CHECK = (
    "status IN ('DRAFT', 'CANCELLED') OR ("
    "requested_at IS NOT NULL "
    "AND requested_by_worker_id IS NOT NULL "
    "AND ogs_readiness_confirmed_at IS NOT NULL "
    "AND ogs_readiness_confirmed_by_worker_id IS NOT NULL)"
)
_CANCELLED_FIELDS_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{QUALITY_SCHEMA}"')

    # ── Проектный счётчик system_code заявок ──────────────────────────────────
    op.create_table(
        SEQUENCES_TABLE,
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_value",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_value >= 0",
            name="ck_quality_inspection_sequences_last_value",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id"),
        schema=QUALITY_SCHEMA,
    )

    # ── Заявка на контроль ─────────────────────────────────────────────────────
    op.create_table(
        INSPECTIONS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system_code", sa.String(length=64), nullable=False),
        sa.Column("external_request_no", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "production_ready_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "production_ready_confirmed_by_worker_id", sa.Integer(), nullable=True
        ),
        sa.Column(
            "ogs_readiness_confirmed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "ogs_readiness_confirmed_by_worker_id", sa.Integer(), nullable=True
        ),
        sa.Column("readiness_override_reason", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_worker_id", sa.Integer(), nullable=True),
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
        sa.CheckConstraint("version >= 1", name="ck_quality_inspections_version"),
        sa.CheckConstraint(
            "length(trim(request_reason)) > 0",
            name="ck_quality_inspections_request_reason_not_empty",
        ),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_quality_inspections_status"),
        sa.CheckConstraint(
            _REQUESTED_FIELDS_CHECK,
            name="ck_quality_inspections_requested_fields",
        ),
        sa.CheckConstraint(
            _CANCELLED_FIELDS_CHECK,
            name="ck_quality_inspections_cancelled_fields",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "system_code", name="uq_quality_inspections_system_code"
        ),
        schema=QUALITY_SCHEMA,
    )
    # Партиальные уникальные индексы (пустые значения не участвуют в уникальности).
    op.create_index(
        "uq_quality_inspections_project_external_no",
        INSPECTIONS_TABLE,
        ["project_id", "external_request_no"],
        unique=True,
        postgresql_where=sa.text("external_request_no IS NOT NULL"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_quality_inspections_created_by_idempotency_key",
        INSPECTIONS_TABLE,
        ["created_by_worker_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspections_project_id",
        INSPECTIONS_TABLE,
        ["project_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspections_joint_id",
        INSPECTIONS_TABLE,
        ["joint_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspections_status",
        INSPECTIONS_TABLE,
        ["status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspections_project_status",
        INSPECTIONS_TABLE,
        ["project_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspections_joint_status",
        INSPECTIONS_TABLE,
        ["joint_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspections_created_at",
        INSPECTIONS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )

    # ── Неизменяемый журнал событий ────────────────────────────────────────────
    op.create_table(
        EVENTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inspection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("inspection_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _EVENT_TYPE_CHECK, name="ck_quality_inspection_events_type"
        ),
        sa.CheckConstraint(
            "inspection_version >= 1",
            name="ck_quality_inspection_events_version",
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            [f"{QUALITY_SCHEMA}.{INSPECTIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspection_events_inspection_id",
        EVENTS_TABLE,
        ["inspection_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_inspection_events_created_at",
        EVENTS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    # Порядок обратный созданию: события → заявки → счётчик → пустая схема.
    op.drop_index(
        "ix_quality_inspection_events_created_at",
        table_name=EVENTS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_inspection_events_inspection_id",
        table_name=EVENTS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(EVENTS_TABLE, schema=QUALITY_SCHEMA)

    for index_name in (
        "ix_quality_inspections_created_at",
        "ix_quality_inspections_joint_status",
        "ix_quality_inspections_project_status",
        "ix_quality_inspections_status",
        "ix_quality_inspections_joint_id",
        "ix_quality_inspections_project_id",
        "uq_quality_inspections_created_by_idempotency_key",
        "uq_quality_inspections_project_external_no",
    ):
        op.drop_index(
            index_name, table_name=INSPECTIONS_TABLE, schema=QUALITY_SCHEMA
        )
    op.drop_table(INSPECTIONS_TABLE, schema=QUALITY_SCHEMA)

    op.drop_table(SEQUENCES_TABLE, schema=QUALITY_SCHEMA)

    op.execute(f'DROP SCHEMA IF EXISTS "{QUALITY_SCHEMA}"')
