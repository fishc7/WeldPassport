"""inspection method assignments (Task 9B).

Revision ID: 20260713_16_method_assignments
Revises: 20260713_15_inspection_core
Create Date: 2026-07-13

Идентификатор revision укорочён (`20260713_16_method_assignments`) относительно
имени файла: alembic_version.version_num — VARCHAR(32), полное имя из ТЗ не
помещается. Бизнес-смысл и порядок миграций сохранены.

Task 9B по ADR-015 / Architecture Session 007: назначение метода контроля и
лаборатории для заявки на контроль. В схему quality добавляется одна таблица
quality.inspection_method_assignments (назначение метода + лаборатория + жизненный
цикл ASSIGNED/CANCELLED/REPLACED).

Перечисления реализованы CHECK-ограничениями в стиле Task 9A (без native enum).
FK: inspection_id → quality.inspections (RESTRICT), laboratory_company_id →
project.companies (RESTRICT; company.id — Integer), self-FK replaced_by_assignment_id
→ inspection_method_assignments (SET NULL, физического удаления нет). Actor-поля
(assigned_by/created_by/updated_by/cancelled_by _worker_id) — hr.workers.id типа
Integer БЕЗ FK, как в Inspection (переходный период).

Не более одного активного назначения метода на Inspection обеспечивает partial
unique index (inspection_id, method_code) WHERE status = 'ASSIGNED'.

Данные Task 9A не изменяются: существующие таблицы не трогаются, добавляется только
новая таблица Task 9B. Downgrade удаляет только объекты Task 9B; DROP SCHEMA ...
CASCADE не используется, схема quality не удаляется (её владеет Task 9A).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.quality.method_assignment_workflow import (
    ASSIGNMENT_STATUSES,
    INSPECTION_METHOD_CODES,
)

revision: str = "20260713_16_method_assignments"
down_revision: Union[str, None] = "20260713_15_inspection_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
PROJECT_SCHEMA = "project"

ASSIGNMENTS_TABLE = "inspection_method_assignments"
INSPECTIONS_TABLE = "inspections"
COMPANIES_TABLE = "companies"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


_STATUS_CHECK = _in("status", ASSIGNMENT_STATUSES)
_METHOD_CHECK = _in("method_code", INSPECTION_METHOD_CODES)
_CANCELLED_FIELDS_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)


def upgrade() -> None:
    op.create_table(
        ASSIGNMENTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inspection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method_code", sa.String(length=10), nullable=False),
        sa.Column("laboratory_company_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ASSIGNED'"),
            nullable=False,
        ),
        sa.Column("laboratory_note", sa.Text(), nullable=True),
        sa.Column("assignment_note", sa.Text(), nullable=True),
        sa.Column("assigned_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column(
            "replaced_by_assignment_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
        sa.CheckConstraint("version >= 1", name="ck_quality_ima_version"),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_quality_ima_status"),
        sa.CheckConstraint(_METHOD_CHECK, name="ck_quality_ima_method_code"),
        sa.CheckConstraint(
            _CANCELLED_FIELDS_CHECK, name="ck_quality_ima_cancelled_fields"
        ),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            [f"{QUALITY_SCHEMA}.{INSPECTIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["laboratory_company_id"],
            [f"{PROJECT_SCHEMA}.{COMPANIES_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_assignment_id"],
            [f"{QUALITY_SCHEMA}.{ASSIGNMENTS_TABLE}.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    # Не более одного активного назначения метода на Inspection (§9).
    op.create_index(
        "uq_quality_ima_active_method",
        ASSIGNMENTS_TABLE,
        ["inspection_id", "method_code"],
        unique=True,
        postgresql_where=sa.text("status = 'ASSIGNED'"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_ima_inspection_id",
        ASSIGNMENTS_TABLE,
        ["inspection_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_ima_inspection_status",
        ASSIGNMENTS_TABLE,
        ["inspection_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_ima_laboratory_company_id",
        ASSIGNMENTS_TABLE,
        ["laboratory_company_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_ima_created_at",
        ASSIGNMENTS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    for index_name in (
        "ix_quality_ima_created_at",
        "ix_quality_ima_laboratory_company_id",
        "ix_quality_ima_inspection_status",
        "ix_quality_ima_inspection_id",
        "uq_quality_ima_active_method",
    ):
        op.drop_index(
            index_name, table_name=ASSIGNMENTS_TABLE, schema=QUALITY_SCHEMA
        )
    op.drop_table(ASSIGNMENTS_TABLE, schema=QUALITY_SCHEMA)
