"""add defect dispositions (Task 9D-4A-2).

Revision ID: 20260721_22_defect_dispositions
Revises: 20260720_21_defect_model
Create Date: 2026-07-21

Task 9D-4A-2: миграционный этап модели `DefectDisposition` — официального
исполняемого решения по дефекту. Создаётся одна таблица схемы quality:
`defect_dispositions` (FK на `quality.defect_roots`, self-FK supersede-цепочки,
три индекса и частичный UNIQUE «одно ACTIVE решение на дефект»).

Решение привязано к `defect_roots` (цепочке версий дефекта), а не к ревизии
`defects`: техническая ревизия заменяется через supersede, официальное решение
должно это переживать. Инвариант «одно действующее решение» — частичный UNIQUE
по `defect_root_id WHERE status = 'ACTIVE'`, тем же приёмом, что
`uq_defects_one_active_per_root` (9D-3A).

Перечисления — CHECK-ограничениями (без native enum), как во всей схеме quality
(ADR-022 / 9D-3A). Ссылки на работников (`*_by_worker_id`) — Integer БЕЗ FK
(переходный период). Время — timestamptz. API, сервисы, workflow и RBAC в объём
не входят. Downgrade удаляет только объекты 9D-4A-2; схема quality не удаляется.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.quality.defect_disposition_models import (
    DEFECT_DISPOSITION_DECISION_TYPES,
    DEFECT_DISPOSITION_STATUSES,
)

revision: str = "20260721_22_defect_dispositions"
down_revision: Union[str, None] = "20260720_21_defect_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"

DEFECT_ROOTS_TABLE = "defect_roots"
DEFECT_DISPOSITIONS_TABLE = "defect_dispositions"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        DEFECT_DISPOSITIONS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_root_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "supersedes_disposition_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("decision_type", sa.String(length=30), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("supersede_reason", sa.Text(), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in("decision_type", DEFECT_DISPOSITION_DECISION_TYPES),
            name="ck_defect_dispositions_decision_type",
        ),
        sa.CheckConstraint(
            _in("status", DEFECT_DISPOSITION_STATUSES),
            name="ck_defect_dispositions_status",
        ),
        sa.CheckConstraint(
            "length(trim(justification)) > 0",
            name="ck_defect_dispositions_justification_not_empty",
        ),
        sa.CheckConstraint(
            "supersedes_disposition_id IS NULL OR supersedes_disposition_id <> id",
            name="ck_defect_dispositions_no_self_supersede",
        ),
        sa.CheckConstraint(
            "(approved_at IS NULL) = (approved_by_worker_id IS NULL)",
            name="ck_defect_dispositions_approved_pair",
        ),
        sa.ForeignKeyConstraint(
            ["defect_root_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_ROOTS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_disposition_id"],
            [f"{QUALITY_SCHEMA}.{DEFECT_DISPOSITIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )

    # Одно ACTIVE решение на один дефект (цепочку версий).
    op.create_index(
        "uq_defect_dispositions_one_active_per_root",
        DEFECT_DISPOSITIONS_TABLE,
        ["defect_root_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_dispositions_defect_root_id",
        DEFECT_DISPOSITIONS_TABLE,
        ["defect_root_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_dispositions_root_status",
        DEFECT_DISPOSITIONS_TABLE,
        ["defect_root_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_defect_dispositions_created_by",
        DEFECT_DISPOSITIONS_TABLE,
        ["created_by_worker_id"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    # DROP TABLE снимает собственные индексы, CHECK и FK (включая self-FK).
    # Схему quality не удаляем (её создал Task 9A).
    op.drop_index(
        "ix_defect_dispositions_created_by",
        table_name=DEFECT_DISPOSITIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_defect_dispositions_root_status",
        table_name=DEFECT_DISPOSITIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_defect_dispositions_defect_root_id",
        table_name=DEFECT_DISPOSITIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "uq_defect_dispositions_one_active_per_root",
        table_name=DEFECT_DISPOSITIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(DEFECT_DISPOSITIONS_TABLE, schema=QUALITY_SCHEMA)
