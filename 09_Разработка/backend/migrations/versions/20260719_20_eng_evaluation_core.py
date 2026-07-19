"""engineering evaluation core (Task 9D-2A).

Revision ID: 20260719_20_eng_evaluation_core
Revises: 20260719_19_quality_finding_core
Create Date: 2026-07-19

Task 9D-2A по ADR-021 (решения 9D-2-C01…C10): структурное ядро EngineeringEvaluation.
Единой миграцией (C08) создаются семь таблиц схемы quality:
engineering_evaluations, engineering_evaluation_revisions, engineering_evaluation_sources,
engineering_evaluation_criteria, engineering_exceptions, engineering_evaluation_events,
engineering_evaluation_sequences.

sources/criteria/exceptions создаются структурно; бизнес-поведение — блоки 9D-2B/2C.
Набор статусов ревизии — ровно семь (C06/C09), RETURNED_FOR_REVISION не используется.
Классификация/исход/judgement-поля ревизии создаются сразу (C10), nullable в DRAFT;
enum-CHECK действует только при NOT NULL. Указатели current/effective_revision_id —
UUID без FK (9D-2A-T01), разрыв цикла без ALTER.

Перечисления — CHECK-ограничениями (без native enum). Ссылки на работников
(*_by_worker_id / actor_worker_id) — Integer БЕЗ FK (переходный период). Downgrade
удаляет только объекты Task 9D-2A; схема quality не удаляется.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.quality.engineering_evaluation_workflow import (
    CONFIDENCE_LEVELS,
    CONFIRMED_SEVERITIES,
    CRITERION_RESULTS,
    EVALUATION_CLASSIFICATIONS,
    EVALUATION_EVENT_TYPES,
    EVALUATION_OUTCOMES,
    EVALUATION_STATUSES,
    IMPACT_SCOPES,
    RECOMMENDED_DISPOSITIONS,
    SOURCE_ROLES,
)

revision: str = "20260719_20_eng_evaluation_core"
down_revision: Union[str, None] = "20260719_19_quality_finding_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
PROJECT_SCHEMA = "project"

EVALUATIONS_TABLE = "engineering_evaluations"
REVISIONS_TABLE = "engineering_evaluation_revisions"
SOURCES_TABLE = "engineering_evaluation_sources"
CRITERIA_TABLE = "engineering_evaluation_criteria"
EXCEPTIONS_TABLE = "engineering_exceptions"
EVENTS_TABLE = "engineering_evaluation_events"
SEQUENCES_TABLE = "engineering_evaluation_sequences"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _null_or_in(column: str, values) -> str:
    return f"{column} IS NULL OR {_in(column, values)}"


def upgrade() -> None:
    # ── 1. Проектный счётчик номера оценки ─────────────────────────────────────
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
        sa.CheckConstraint("last_value >= 0", name="ck_ee_sequences_last_value"),
        sa.ForeignKeyConstraint(
            ["project_id"], [f"{PROJECT_SCHEMA}.projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("project_id"),
        schema=QUALITY_SCHEMA,
    )

    # ── 2. EngineeringEvaluation (указатели ревизий — без FK, 9D-2A-T01) ───────
    op.create_table(
        EVALUATIONS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system_code", sa.String(length=64), nullable=False),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "effective_revision_id", postgresql.UUID(as_uuid=True), nullable=True
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
        sa.CheckConstraint("version >= 1", name="ck_engineering_evaluations_version"),
        sa.CheckConstraint(
            "length(trim(system_code)) > 0",
            name="ck_engineering_evaluations_system_code_not_empty",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], [f"{PROJECT_SCHEMA}.projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            [f"{QUALITY_SCHEMA}.quality_findings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_engineering_evaluations_finding_id",
        EVALUATIONS_TABLE,
        ["finding_id"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_engineering_evaluations_system_code",
        EVALUATIONS_TABLE,
        ["system_code"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_engineering_evaluations_project_id",
        EVALUATIONS_TABLE,
        ["project_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_engineering_evaluations_created_at",
        EVALUATIONS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )

    # ── 3. EngineeringEvaluationRevision (полная схема, C10) ────────────────────
    op.create_table(
        REVISIONS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("evaluation_outcome", sa.String(length=30), nullable=True),
        sa.Column("classification", sa.String(length=40), nullable=True),
        sa.Column("recommended_disposition", sa.String(length=30), nullable=True),
        sa.Column("confirmed_severity", sa.String(length=20), nullable=True),
        sa.Column("impact_scope", sa.String(length=40), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.String(length=10), nullable=True),
        sa.Column("confidence_note", sa.Text(), nullable=True),
        sa.Column("residual_risk", sa.Text(), nullable=True),
        sa.Column("application_conditions", sa.Text(), nullable=True),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_impact", sa.Text(), nullable=True),
        sa.Column("required_approval_route", sa.Text(), nullable=True),
        sa.Column("prepared_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fixed_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("version >= 1", name="ck_ee_revisions_version"),
        sa.CheckConstraint("revision_no >= 1", name="ck_ee_revisions_revision_no"),
        sa.CheckConstraint(
            _in("status", EVALUATION_STATUSES), name="ck_ee_revisions_status"
        ),
        sa.CheckConstraint(
            _null_or_in("evaluation_outcome", EVALUATION_OUTCOMES),
            name="ck_ee_revisions_evaluation_outcome",
        ),
        sa.CheckConstraint(
            _null_or_in("classification", EVALUATION_CLASSIFICATIONS),
            name="ck_ee_revisions_classification",
        ),
        sa.CheckConstraint(
            _null_or_in("recommended_disposition", RECOMMENDED_DISPOSITIONS),
            name="ck_ee_revisions_recommended_disposition",
        ),
        sa.CheckConstraint(
            _null_or_in("confirmed_severity", CONFIRMED_SEVERITIES),
            name="ck_ee_revisions_confirmed_severity",
        ),
        sa.CheckConstraint(
            _null_or_in("impact_scope", IMPACT_SCOPES),
            name="ck_ee_revisions_impact_scope",
        ),
        sa.CheckConstraint(
            _null_or_in("confidence_level", CONFIDENCE_LEVELS),
            name="ck_ee_revisions_confidence_level",
        ),
        sa.CheckConstraint(
            "revision_no = 1 OR revision_reason IS NOT NULL",
            name="ck_ee_revisions_revision_reason",
        ),
        sa.CheckConstraint(
            "status <> 'WITHDRAWN' OR ("
            "withdrawn_at IS NOT NULL "
            "AND withdrawn_by_worker_id IS NOT NULL "
            "AND length(trim(withdrawal_reason)) > 0)",
            name="ck_ee_revisions_withdrawn_fields",
        ),
        sa.CheckConstraint(
            "(prepared_at IS NULL) = (prepared_by_worker_id IS NULL)",
            name="ck_ee_revisions_prepared_pair",
        ),
        sa.CheckConstraint(
            "(fixed_at IS NULL) = (fixed_by_worker_id IS NULL)",
            name="ck_ee_revisions_fixed_pair",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            [f"{QUALITY_SCHEMA}.{EVALUATIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            [f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_ee_revisions_evaluation_revno",
        REVISIONS_TABLE,
        ["evaluation_id", "revision_no"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_revisions_evaluation_id",
        REVISIONS_TABLE,
        ["evaluation_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_revisions_status", REVISIONS_TABLE, ["status"], schema=QUALITY_SCHEMA
    )
    op.create_index(
        "ix_ee_revisions_previous_revision_id",
        REVISIONS_TABLE,
        ["previous_revision_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_revisions_created_at",
        REVISIONS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )

    # ── 4. EngineeringEvaluationSource (структурно) ────────────────────────────
    op.create_table(
        SOURCES_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_role", sa.String(length=30), nullable=False),
        sa.Column("source_entity_type", sa.String(length=60), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_hash", sa.String(length=128), nullable=True),
        sa.Column("hash_schema_version", sa.String(length=40), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applicability_note", sa.Text(), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("source_role", SOURCE_ROLES), name="ck_ee_sources_role"
        ),
        sa.CheckConstraint(
            "source_revision_id IS NOT NULL OR "
            "(source_hash IS NOT NULL AND hash_schema_version IS NOT NULL)",
            name="ck_ee_sources_revisional_or_hash",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            [f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_sources_revision_id",
        SOURCES_TABLE,
        ["revision_id"],
        schema=QUALITY_SCHEMA,
    )

    # ── 5. EngineeringEvaluationCriterion (структурно) ─────────────────────────
    op.create_table(
        CRITERIA_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_ref", sa.Text(), nullable=False),
        sa.Column("clause", sa.Text(), nullable=True),
        sa.Column("parameter", sa.Text(), nullable=False),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column("actual_num", sa.Numeric(), nullable=True),
        sa.Column("allowed_value", sa.Text(), nullable=True),
        sa.Column("allowed_num_min", sa.Numeric(), nullable=True),
        sa.Column("allowed_num_max", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("comparison_result", sa.String(length=30), nullable=False),
        sa.Column("applicability_comment", sa.Text(), nullable=True),
        sa.Column("engineer_comment", sa.Text(), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("comparison_result", CRITERION_RESULTS),
            name="ck_ee_criteria_comparison_result",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            [f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_criteria_revision_id",
        CRITERIA_TABLE,
        ["revision_id"],
        schema=QUALITY_SCHEMA,
    )

    # ── 6. EngineeringException (структурно) ───────────────────────────────────
    op.create_table(
        EXCEPTIONS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("criterion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("residual_risk", sa.Text(), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("required_approval_route", sa.Text(), nullable=True),
        sa.Column(
            "is_draft_copy",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            [f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"],
            [f"{QUALITY_SCHEMA}.{CRITERIA_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "uq_ee_exceptions_revision_criterion",
        EXCEPTIONS_TABLE,
        ["revision_id", "criterion_id"],
        unique=True,
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_exceptions_revision_id",
        EXCEPTIONS_TABLE,
        ["revision_id"],
        schema=QUALITY_SCHEMA,
    )

    # ── 7. EngineeringEvaluationEvent (append-only) ────────────────────────────
    op.create_table(
        EVENTS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column("actor_role", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("event_type", EVALUATION_EVENT_TYPES), name="ck_ee_events_type"
        ),
        sa.CheckConstraint(
            "revision_version IS NULL OR revision_version >= 1",
            name="ck_ee_events_revision_version",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            [f"{QUALITY_SCHEMA}.{EVALUATIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            [f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_events_evaluation_id",
        EVENTS_TABLE,
        ["evaluation_id"],
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_ee_events_created_at",
        EVENTS_TABLE,
        ["created_at"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    # Порядок обратный созданию (дети → родители). DROP TABLE снимает свои индексы,
    # CHECK и FK. Схему quality не удаляем (её создал Task 9A и используют 9A–9D-1).
    op.drop_table(EVENTS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(EXCEPTIONS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(CRITERIA_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(SOURCES_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(REVISIONS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(EVALUATIONS_TABLE, schema=QUALITY_SCHEMA)
    op.drop_table(SEQUENCES_TABLE, schema=QUALITY_SCHEMA)
