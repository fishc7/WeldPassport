"""add QualityDecision core models (Task 10A, Implementation Block 1; ADR-027 ACCEPTED).

Revision ID: 20260723_25_qd_core
Revises: 20260721_24_disp_supersede
Create Date: 2026-07-23

Task 10A Block 1 (Models + Migration only; ADR-027 QualityDecision Core Canon, ACCEPTED
2026-07-23): создаёт три таблицы схемы `quality` для нового контура `QualityDecision`,
размещённого над `EngineeringEvaluation` и перед `Defect` (ADR-027 §B). Не изменяет
`engineering_evaluations`, `engineering_evaluation_revisions`, `defects`,
`defect_dispositions` или их данные.

Создаваемые объекты:

* `quality_decisions` — официальное решение по качеству на один `Joint`; FK на
  `project.projects`, `engineering.joints`, self-FK lineage `supersedes_quality_decision_id`;
* `quality_decision_bases` — основание решения, FK на `quality_decisions` и на
  `quality.engineering_evaluation_revisions` (конкретную ревизию, не header);
* `quality_decision_sequences` — проектный счётчик номера (`<PROJECT_CODE>-QD-<SEQUENCE>`),
  тот же паттерн, что `engineering_evaluation_sequences`.

Ограничения БД (Task 10A + ADR-027 §F, открытые точки разрешены ACCEPTED; Q-D2 —
скорректированная редакция, Block 1 Correction 2026-07-23 после архитектурного review):

* CHECK статуса (`DRAFT`/`UNDER_REVIEW`/`DECIDED`/`SUPERSEDED` — ровно четыре значения,
  Q-D8) и результата (`ACCEPTED`/`NOT_CONFIRMED`/`DEFECT_CONFIRMED`, nullable до `DECIDED`);
* `UNIQUE(system_code)` — глобальная уникальность номера;
* partial `UNIQUE(joint_id) WHERE status = 'DECIDED'` — не более одного действующего
  решения на Joint. Единственное ограничение количества по Joint (Q-D2, уточнённое
  решение): `DRAFT`/`UNDER_REVIEW` на один Joint количество не ограничивают — партиальный
  индекс `UNIQUE(joint_id) WHERE status IN ('DRAFT','UNDER_REVIEW')` из первой версии
  Block 1 не соответствовал принятому решению и в этой миграции больше не создаётся;
* partial `UNIQUE(engineering_evaluation_revision_id) WHERE is_basis_of_decided = true` —
  одна ревизия не может быть основанием более чем одного `DECIDED` `QualityDecision`
  одновременно (ADR-027 §F.3).

Также расширяет существующий полиморфный аудит `quality.quality_audit_events` (миграции
17/18/23/24 не редактируются задним числом — CHECK пересоздаётся с расширенным списком,
по образцу `20260721_24_disp_supersede`):

* `ck_quality_audit_entity_type` — добавлено значение `QUALITY_DECISION`;
* `ck_quality_audit_event_type` — добавлены пять значений: `QUALITY_DECISION_CREATED`,
  `QUALITY_DECISION_SUBMITTED`, `QUALITY_DECISION_RETURNED`, `QUALITY_DECISION_DECIDED`,
  `QUALITY_DECISION_SUPERSEDED` (закрытый список ADR-027 §H). Отдельная таблица
  `QualityDecisionEvent` не создаётся.

Downgrade — полный обратный порядок: восстанавливает исходные CHECK
`quality_audit_events`, затем удаляет три новые таблицы (с их индексами/CHECK/FK).
Данные существующих таблиц не затрагиваются. Схема `quality` не удаляется (создана
Task 9A).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Локальные копии перечислений ORM (app.quality.quality_decision_models). Миграция
# самодостаточна и не импортирует application-код (migration import policy,
# TEST-B03-IMPORT-003) — при изменении набора значений в модели синхронизировать
# здесь вручную (тот же приём, что уже используется для CHECK-констант аудита ниже).
QUALITY_DECISION_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "UNDER_REVIEW",
    "DECIDED",
    "SUPERSEDED",
)
QUALITY_DECISION_RESULTS: tuple[str, ...] = (
    "ACCEPTED",
    "NOT_CONFIRMED",
    "DEFECT_CONFIRMED",
)

revision: str = "20260723_25_qd_core"
down_revision: Union[str, None] = "20260721_24_disp_supersede"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
PROJECT_SCHEMA = "project"
ENGINEERING_SCHEMA = "engineering"

QUALITY_DECISIONS_TABLE = "quality_decisions"
QUALITY_DECISION_BASES_TABLE = "quality_decision_bases"
QUALITY_DECISION_SEQUENCES_TABLE = "quality_decision_sequences"
REVISIONS_TABLE = "engineering_evaluation_revisions"

AUDIT_TABLE = "quality_audit_events"
AUDIT_ENTITY_CHECK = "ck_quality_audit_entity_type"
AUDIT_EVENT_CHECK = "ck_quality_audit_event_type"

# Набор entity_type ДО этой миграции (не редактируется задним числом).
OLD_AUDIT_ENTITY_TYPES = (
    "METHOD_EXECUTION",
    "METHOD_EXECUTION_PARTICIPANT",
    "METHOD_EXECUTION_RESULT_ITEM",
    "METHOD_EXECUTION_STANDARD",
    "LABORATORY_CONCLUSION",
    "LABORATORY_CONCLUSION_EXECUTION",
    "LABORATORY_ACCREDITATION",
)
NEW_AUDIT_ENTITY_TYPES = OLD_AUDIT_ENTITY_TYPES + ("QUALITY_DECISION",)

# Набор event_type ДО этой миграции (после миграции 18; 19/20/21/22/23/24 event_type
# quality_audit_events не расширяли — свои CHECK на собственных таблицах).
OLD_AUDIT_EVENT_TYPES = (
    "EXECUTION_CREATED",
    "STATUS_CHANGED",
    "LABORATORY_CHANGED",
    "PARTICIPANTS_CHANGED",
    "TIME_CHANGED",
    "VOLUME_CHANGED",
    "COORDINATES_CHANGED",
    "EVALUATION_CHANGED",
    "REQUIRED_ACTION_CHANGED",
    "RESULT_CONFIRMED",
    "EXECUTION_CANCELLED",
    "REVISION_CREATED",
    "REMOVED_RESULT_ITEM",
    "CONCLUSION_CREATED",
    "CONCLUSION_COMPOSITION_CHANGED",
    "CONCLUSION_APPROVED",
    "CONCLUSION_ISSUED",
    "CONCLUSION_SUPERSEDED",
    "CONCLUSION_EXECUTION_ADDED",
    "CONCLUSION_EXECUTION_REMOVED",
    "CONCLUSION_REVISION_CANCELLED",
    "CONCLUSION_REVIEW_REQUIRED",
)
NEW_AUDIT_EVENT_TYPES = OLD_AUDIT_EVENT_TYPES + (
    "QUALITY_DECISION_CREATED",
    "QUALITY_DECISION_SUBMITTED",
    "QUALITY_DECISION_RETURNED",
    "QUALITY_DECISION_DECIDED",
    "QUALITY_DECISION_SUPERSEDED",
)


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _null_or_in(column: str, values) -> str:
    return f"{column} IS NULL OR {_in(column, values)}"


def upgrade() -> None:
    # 1. quality_decisions
    op.create_table(
        QUALITY_DECISIONS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system_code", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("decision_result", sa.String(length=30), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("return_reason", sa.Text(), nullable=True),
        sa.Column(
            "supersedes_quality_decision_id",
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
        sa.Column("approved_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_role", sa.String(length=40), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_quality_decisions_version"
        ),
        sa.CheckConstraint(
            "length(trim(system_code)) > 0",
            name="ck_quality_decisions_system_code_not_empty",
        ),
        sa.CheckConstraint(
            _in("status", QUALITY_DECISION_STATUSES),
            name="ck_quality_decisions_status",
        ),
        sa.CheckConstraint(
            _null_or_in("decision_result", QUALITY_DECISION_RESULTS),
            name="ck_quality_decisions_decision_result",
        ),
        sa.CheckConstraint(
            "supersedes_quality_decision_id IS NULL OR "
            "supersedes_quality_decision_id <> id",
            name="ck_quality_decisions_no_self_supersede",
        ),
        sa.CheckConstraint(
            "(approved_at IS NULL) = (approved_by_worker_id IS NULL)",
            name="ck_quality_decisions_approved_pair",
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
        sa.ForeignKeyConstraint(
            ["supersedes_quality_decision_id"],
            [f"{QUALITY_SCHEMA}.{QUALITY_DECISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_quality_decisions_system_code",
        QUALITY_DECISIONS_TABLE,
        ["system_code"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_quality_decisions_one_decided_per_joint",
        QUALITY_DECISIONS_TABLE,
        ["joint_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DECIDED'"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decisions_project_id",
        QUALITY_DECISIONS_TABLE,
        ["project_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decisions_joint_id",
        QUALITY_DECISIONS_TABLE,
        ["joint_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decisions_status",
        QUALITY_DECISIONS_TABLE,
        ["status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decisions_joint_status",
        QUALITY_DECISIONS_TABLE,
        ["joint_id", "status"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decisions_created_by",
        QUALITY_DECISIONS_TABLE,
        ["created_by_worker_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decisions_supersedes",
        QUALITY_DECISIONS_TABLE,
        ["supersedes_quality_decision_id"],
        schema=QUALITY_SCHEMA,
    )

    # 2. quality_decision_bases
    op.create_table(
        QUALITY_DECISION_BASES_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "quality_decision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "engineering_evaluation_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "is_basis_of_decided",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("linked_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["quality_decision_id"],
            [f"{QUALITY_SCHEMA}.{QUALITY_DECISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["engineering_evaluation_revision_id"],
            [f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_quality_decision_bases_decision_revision",
        QUALITY_DECISION_BASES_TABLE,
        ["quality_decision_id", "engineering_evaluation_revision_id"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_quality_decision_bases_one_decided_per_revision",
        QUALITY_DECISION_BASES_TABLE,
        ["engineering_evaluation_revision_id"],
        unique=True,
        postgresql_where=sa.text("is_basis_of_decided = true"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decision_bases_quality_decision_id",
        QUALITY_DECISION_BASES_TABLE,
        ["quality_decision_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_quality_decision_bases_revision_id",
        QUALITY_DECISION_BASES_TABLE,
        ["engineering_evaluation_revision_id"],
        schema=QUALITY_SCHEMA,
    )

    # 3. quality_decision_sequences
    op.create_table(
        QUALITY_DECISION_SEQUENCES_TABLE,
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
            "last_value >= 0", name="ck_quality_decision_sequences_last_value"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id"),
        schema=QUALITY_SCHEMA,
    )

    # 4. Расширение полиморфного аудита ADR-027 §H (закрытый список из пяти событий).
    op.drop_constraint(
        AUDIT_ENTITY_CHECK, AUDIT_TABLE, schema=QUALITY_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        AUDIT_ENTITY_CHECK,
        AUDIT_TABLE,
        _in("entity_type", NEW_AUDIT_ENTITY_TYPES),
        schema=QUALITY_SCHEMA,
    )
    op.drop_constraint(
        AUDIT_EVENT_CHECK, AUDIT_TABLE, schema=QUALITY_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        AUDIT_EVENT_CHECK,
        AUDIT_TABLE,
        _in("event_type", NEW_AUDIT_EVENT_TYPES),
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    # 4. Восстановить исходные CHECK аудита.
    op.drop_constraint(
        AUDIT_EVENT_CHECK, AUDIT_TABLE, schema=QUALITY_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        AUDIT_EVENT_CHECK,
        AUDIT_TABLE,
        _in("event_type", OLD_AUDIT_EVENT_TYPES),
        schema=QUALITY_SCHEMA,
    )
    op.drop_constraint(
        AUDIT_ENTITY_CHECK, AUDIT_TABLE, schema=QUALITY_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        AUDIT_ENTITY_CHECK,
        AUDIT_TABLE,
        _in("entity_type", OLD_AUDIT_ENTITY_TYPES),
        schema=QUALITY_SCHEMA,
    )

    # 3. quality_decision_sequences
    op.drop_table(QUALITY_DECISION_SEQUENCES_TABLE, schema=QUALITY_SCHEMA)

    # 2. quality_decision_bases (DROP TABLE снимает собственные индексы/CHECK/FK).
    op.drop_index(
        "ix_quality_decision_bases_revision_id",
        table_name=QUALITY_DECISION_BASES_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_decision_bases_quality_decision_id",
        table_name=QUALITY_DECISION_BASES_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "uq_quality_decision_bases_one_decided_per_revision",
        table_name=QUALITY_DECISION_BASES_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "uq_quality_decision_bases_decision_revision",
        table_name=QUALITY_DECISION_BASES_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(QUALITY_DECISION_BASES_TABLE, schema=QUALITY_SCHEMA)

    # 1. quality_decisions (self-FK supersedes отпадает вместе с DROP TABLE).
    op.drop_index(
        "ix_quality_decisions_supersedes",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_decisions_created_by",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_decisions_joint_status",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_decisions_status",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_decisions_joint_id",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "ix_quality_decisions_project_id",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "uq_quality_decisions_one_decided_per_joint",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_index(
        "uq_quality_decisions_system_code",
        table_name=QUALITY_DECISIONS_TABLE,
        schema=QUALITY_SCHEMA,
    )
    op.drop_table(QUALITY_DECISIONS_TABLE, schema=QUALITY_SCHEMA)
