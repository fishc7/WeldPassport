"""heat treatment integration (Task 8F).

Revision ID: 20260713_14_heat_treatment
Revises: 20260712_13_import_pipeline
Create Date: 2026-07-13

Task 8F по ADR-014 / Architecture Session 006: минимальный рабочий контур
термической обработки сварных соединений. Два ядра — общий фактический цикл
engineering.heat_treatment_batches и участие Joint engineering.
heat_treatment_operations; технологическая карта — нейтральная минимальная
ссылочная сущность engineering.heat_treatment_procedure_revisions (не WPS);
подтверждающие документы engineering.heat_treatment_records и отклонения
engineering.heat_treatment_deviations.

Перечисления реализованы CHECK-ограничениями в стиле модуля engineering (как
weld_operations), без native enum-типов. Данные Tasks 8A–8E не изменяются:
существующие таблицы не трогаются, только добавляются новые. Downgrade удаляет
только объекты Task 8F. DROP SCHEMA не используется.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.engineering.heat_treatment_workflow import (
    AUTO_CHECK_RESULTS,
    BATCH_REVIEW_RESULTS,
    BATCH_STATUSES,
    DEVIATION_OGS_DECISIONS,
    DEVIATION_SEVERITIES,
    DEVIATION_STATUSES,
    DEVIATION_TYPES,
    EVIDENCE_SUFFICIENCY_VALUES,
    OPERATION_REASONS,
    OPERATION_RESULTS,
    OPERATION_STATUSES,
    PROCEDURE_REVISION_STATUSES,
    RECORD_STATUSES,
    RECORD_TYPES,
)

revision: str = "20260713_14_heat_treatment"
down_revision: Union[str, None] = "20260712_13_import_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"
PROJECT_SCHEMA = "project"

PROC_TABLE = "heat_treatment_procedure_revisions"
BATCH_TABLE = "heat_treatment_batches"
OP_TABLE = "heat_treatment_operations"
RECORD_TABLE = "heat_treatment_records"
DEVIATION_TABLE = "heat_treatment_deviations"


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # ── Технологическая карта термообработки (минимальная ссылочная) ──────────
    op.create_table(
        PROC_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("procedure_no", sa.String(length=100), nullable=False),
        sa.Column("revision_no", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("ht_type", sa.String(length=50), nullable=True),
        sa.Column("heating_method", sa.String(length=50), nullable=True),
        sa.Column("min_temperature", sa.Numeric(), nullable=True),
        sa.Column("max_temperature", sa.Numeric(), nullable=True),
        sa.Column("soak_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("max_heating_rate", sa.Numeric(), nullable=True),
        sa.Column("max_cooling_rate", sa.Numeric(), nullable=True),
        sa.Column("tolerances", postgresql.JSONB(), nullable=True),
        sa.Column("applicable_line_ids", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("status", PROCEDURE_REVISION_STATUSES),
            name="ck_engineering_ht_procedure_revisions_status",
        ),
        sa.CheckConstraint(
            "length(trim(procedure_no)) > 0",
            name="ck_engineering_ht_procedure_revisions_no_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(revision_no)) > 0",
            name="ck_engineering_ht_procedure_revisions_rev_not_empty",
        ),
        sa.CheckConstraint(
            "min_temperature IS NULL OR max_temperature IS NULL "
            "OR max_temperature >= min_temperature",
            name="ck_engineering_ht_procedure_revisions_temp_range",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "procedure_no",
            "revision_no",
            name="uq_engineering_ht_procedure_revisions_no",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_ht_procedure_revisions_project_id",
        PROC_TABLE,
        ["project_id"],
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_ht_procedure_revisions_status",
        PROC_TABLE,
        ["status"],
        schema=ENGINEERING_SCHEMA,
    )

    # ── Общий цикл термообработки ─────────────────────────────────────────────
    op.create_table(
        BATCH_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_no", sa.String(length=100), nullable=False),
        sa.Column(
            "procedure_revision_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_worker_id", sa.Integer(), nullable=True),
        sa.Column("operator_name_text", sa.String(length=255), nullable=True),
        sa.Column("equipment_text", sa.Text(), nullable=True),
        sa.Column("actual_soak_temperature", sa.Numeric(), nullable=True),
        sa.Column("actual_min_temperature", sa.Numeric(), nullable=True),
        sa.Column("actual_max_temperature", sa.Numeric(), nullable=True),
        sa.Column("actual_soak_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_heating_rate", sa.Numeric(), nullable=True),
        sa.Column("actual_cooling_rate", sa.Numeric(), nullable=True),
        sa.Column("process_comment", sa.Text(), nullable=True),
        sa.Column("procedure_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "auto_check_result",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NOT_CHECKED'"),
        ),
        sa.Column("auto_check_details", postgresql.JSONB(), nullable=True),
        sa.Column("auto_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "review_result",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.CheckConstraint(
            "length(trim(batch_no)) > 0",
            name="ck_engineering_ht_batches_batch_no_not_empty",
        ),
        sa.CheckConstraint(
            _in("status", BATCH_STATUSES), name="ck_engineering_ht_batches_status"
        ),
        sa.CheckConstraint(
            _in("review_result", BATCH_REVIEW_RESULTS),
            name="ck_engineering_ht_batches_review_result",
        ),
        sa.CheckConstraint(
            _in("auto_check_result", AUTO_CHECK_RESULTS),
            name="ck_engineering_ht_batches_auto_check_result",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_engineering_ht_batches_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{PROJECT_SCHEMA}.projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["procedure_revision_id"],
            [f"{ENGINEERING_SCHEMA}.{PROC_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_batches_procedure_revision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "batch_no",
            name="uq_engineering_ht_batches_project_batch_no",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    for name, columns in (
        ("ix_engineering_ht_batches_project_id", ["project_id"]),
        ("ix_engineering_ht_batches_batch_no", ["batch_no"]),
        ("ix_engineering_ht_batches_status", ["status"]),
        (
            "ix_engineering_ht_batches_procedure_revision_id",
            ["procedure_revision_id"],
        ),
        ("ix_engineering_ht_batches_actual_started_at", ["actual_started_at"]),
    ):
        op.create_index(name, BATCH_TABLE, columns, schema=ENGINEERING_SCHEMA)

    # ── Участие Joint в цикле ─────────────────────────────────────────────────
    op.create_table(
        OP_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weld_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "previous_heat_treatment_operation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'AFTER_INITIAL_WELD'"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PLANNED'"),
        ),
        sa.Column(
            "result",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "evidence_sufficiency",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'NOT_EVALUATED'"),
        ),
        sa.Column("individual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "individual_completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("result_comment", sa.Text(), nullable=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("evaluated_by", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.CheckConstraint(
            _in("reason", OPERATION_REASONS),
            name="ck_engineering_ht_operations_reason",
        ),
        sa.CheckConstraint(
            _in("status", OPERATION_STATUSES),
            name="ck_engineering_ht_operations_status",
        ),
        sa.CheckConstraint(
            _in("result", OPERATION_RESULTS),
            name="ck_engineering_ht_operations_result",
        ),
        sa.CheckConstraint(
            _in("evidence_sufficiency", EVIDENCE_SUFFICIENCY_VALUES),
            name="ck_engineering_ht_operations_evidence_sufficiency",
        ),
        sa.CheckConstraint(
            "reason <> 'REPEAT_AFTER_REJECTION' "
            "OR previous_heat_treatment_operation_id IS NOT NULL",
            name="ck_engineering_ht_operations_repeat_previous",
        ),
        sa.CheckConstraint(
            "previous_heat_treatment_operation_id IS NULL "
            "OR previous_heat_treatment_operation_id <> id",
            name="ck_engineering_ht_operations_no_self_previous",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_engineering_ht_operations_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            [f"{ENGINEERING_SCHEMA}.{BATCH_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_operations_batch",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_operations_joint",
        ),
        sa.ForeignKeyConstraint(
            ["weld_operation_id"],
            [f"{ENGINEERING_SCHEMA}.weld_operations.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_operations_weld_operation",
        ),
        sa.ForeignKeyConstraint(
            ["previous_heat_treatment_operation_id"],
            [f"{ENGINEERING_SCHEMA}.{OP_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_operations_previous",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id", "joint_id", name="uq_engineering_ht_operations_batch_joint"
        ),
        schema=ENGINEERING_SCHEMA,
    )
    for name, columns in (
        ("ix_engineering_ht_operations_batch_id", ["batch_id"]),
        ("ix_engineering_ht_operations_joint_id", ["joint_id"]),
        ("ix_engineering_ht_operations_weld_operation_id", ["weld_operation_id"]),
        ("ix_engineering_ht_operations_result", ["result"]),
    ):
        op.create_index(name, OP_TABLE, columns, schema=ENGINEERING_SCHEMA)

    # ── Подтверждающие документы ──────────────────────────────────────────────
    op.create_table(
        RECORD_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("document_no", sa.String(length=100), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'UPLOADED'"),
        ),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("verified_by", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in("record_type", RECORD_TYPES),
            name="ck_engineering_ht_records_type",
        ),
        sa.CheckConstraint(
            _in("status", RECORD_STATUSES), name="ck_engineering_ht_records_status"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            [f"{ENGINEERING_SCHEMA}.{BATCH_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_records_batch",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_ht_records_batch_id",
        RECORD_TABLE,
        ["batch_id"],
        schema=ENGINEERING_SCHEMA,
    )

    # ── Отклонения ────────────────────────────────────────────────────────────
    op.create_table(
        DEVIATION_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deviation_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("planned_value", sa.String(length=255), nullable=True),
        sa.Column("actual_value", sa.String(length=255), nullable=True),
        sa.Column(
            "severity",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'MINOR'"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'OPEN'"),
        ),
        sa.Column("ogs_decision", sa.String(length=40), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _in("deviation_type", DEVIATION_TYPES),
            name="ck_engineering_ht_deviations_type",
        ),
        sa.CheckConstraint(
            _in("severity", DEVIATION_SEVERITIES),
            name="ck_engineering_ht_deviations_severity",
        ),
        sa.CheckConstraint(
            _in("status", DEVIATION_STATUSES),
            name="ck_engineering_ht_deviations_status",
        ),
        sa.CheckConstraint(
            "ogs_decision IS NULL OR " + _in("ogs_decision", DEVIATION_OGS_DECISIONS),
            name="ck_engineering_ht_deviations_ogs_decision",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            [f"{ENGINEERING_SCHEMA}.{BATCH_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_deviations_batch",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            [f"{ENGINEERING_SCHEMA}.{OP_TABLE}.id"],
            ondelete="RESTRICT",
            name="fk_engineering_ht_deviations_operation",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ENGINEERING_SCHEMA,
    )
    for name, columns in (
        ("ix_engineering_ht_deviations_batch_id", ["batch_id"]),
        ("ix_engineering_ht_deviations_operation_id", ["operation_id"]),
        ("ix_engineering_ht_deviations_status", ["status"]),
    ):
        op.create_index(name, DEVIATION_TABLE, columns, schema=ENGINEERING_SCHEMA)


def downgrade() -> None:
    for name in (
        "ix_engineering_ht_deviations_status",
        "ix_engineering_ht_deviations_operation_id",
        "ix_engineering_ht_deviations_batch_id",
    ):
        op.drop_index(name, table_name=DEVIATION_TABLE, schema=ENGINEERING_SCHEMA)
    op.drop_table(DEVIATION_TABLE, schema=ENGINEERING_SCHEMA)

    op.drop_index(
        "ix_engineering_ht_records_batch_id",
        table_name=RECORD_TABLE,
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table(RECORD_TABLE, schema=ENGINEERING_SCHEMA)

    for name in (
        "ix_engineering_ht_operations_result",
        "ix_engineering_ht_operations_weld_operation_id",
        "ix_engineering_ht_operations_joint_id",
        "ix_engineering_ht_operations_batch_id",
    ):
        op.drop_index(name, table_name=OP_TABLE, schema=ENGINEERING_SCHEMA)
    op.drop_table(OP_TABLE, schema=ENGINEERING_SCHEMA)

    for name in (
        "ix_engineering_ht_batches_actual_started_at",
        "ix_engineering_ht_batches_procedure_revision_id",
        "ix_engineering_ht_batches_status",
        "ix_engineering_ht_batches_batch_no",
        "ix_engineering_ht_batches_project_id",
    ):
        op.drop_index(name, table_name=BATCH_TABLE, schema=ENGINEERING_SCHEMA)
    op.drop_table(BATCH_TABLE, schema=ENGINEERING_SCHEMA)

    for name in (
        "ix_engineering_ht_procedure_revisions_status",
        "ix_engineering_ht_procedure_revisions_project_id",
    ):
        op.drop_index(name, table_name=PROC_TABLE, schema=ENGINEERING_SCHEMA)
    op.drop_table(PROC_TABLE, schema=ENGINEERING_SCHEMA)
