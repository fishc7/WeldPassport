"""weld operations core (Task 8A).

Revision ID: 20260712_09_weld_operations
Revises: 20260711_08_joint_bulk_requests
Create Date: 2026-07-12

Task 8A по ADR-012 / Architecture Session 005: таблица engineering.weld_operations —
неизменяемый после завершения производственный факт сварки (один Joint + один
фактический сварщик + один классифицированный этап + один способ). Не создаётся
логика Tasks 8B–8E (проверка допуска, WPS-валидация, review ОГС, подтверждение
сварщика, корректировки, импорт). FK на Joint — ondelete RESTRICT; FK на welder —
ondelete RESTRICT. WPS хранится как nullable UUID без FK (домен не реализован).
Уникальность (joint_id, sequence_no) — последняя защита при конкурентной нумерации.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_09_weld_operations"
down_revision: Union[str, None] = "20260711_08_joint_bulk_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"
WELDING_SCHEMA = "welding"

_COMPLETION_CHECK = (
    "(lifecycle_status = 'COMPLETED' AND completed_by IS NOT NULL "
    "AND completed_at IS NOT NULL AND actual_welder_id IS NOT NULL) "
    "OR (lifecycle_status <> 'COMPLETED' AND completed_by IS NULL "
    "AND completed_at IS NULL)"
)
_CANCELLATION_CHECK = (
    "(lifecycle_status = 'CANCELLED' AND cancelled_by IS NOT NULL "
    "AND cancelled_at IS NOT NULL AND length(trim(cancellation_reason)) > 0) "
    "OR (lifecycle_status <> 'CANCELLED' AND cancelled_by IS NULL "
    "AND cancelled_at IS NULL AND cancellation_reason IS NULL)"
)
_TIME_CHECK = "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at"

_INDEXES = (
    ("ix_engineering_weld_operations_joint_id", ["joint_id"]),
    ("ix_engineering_weld_operations_actual_welder_id", ["actual_welder_id"]),
    (
        "ix_engineering_weld_operations_responsible_worker_id",
        ["responsible_worker_id"],
    ),
    ("ix_engineering_weld_operations_lifecycle_status", ["lifecycle_status"]),
    ("ix_engineering_weld_operations_performed_on", ["performed_on"]),
)


def upgrade() -> None:
    op.create_table(
        "weld_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column(
            "lifecycle_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("weld_stage", sa.String(length=20), nullable=False),
        sa.Column("welding_method", sa.String(length=50), nullable=False),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_welder_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entered_stamp_code", sa.String(length=100), nullable=True),
        sa.Column("profile_stamp_snapshot", sa.String(length=100), nullable=True),
        sa.Column("responsible_worker_id", sa.Integer(), nullable=False),
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
        sa.Column("completed_by", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("executor_company_id", sa.Integer(), nullable=True),
        sa.Column("executor_department_id", sa.Integer(), nullable=True),
        sa.Column("welder_company_id", sa.Integer(), nullable=True),
        sa.Column("welder_department_id", sa.Integer(), nullable=True),
        sa.Column("production_area_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("production_area_text", sa.Text(), nullable=True),
        sa.Column("shift_ref", sa.String(length=100), nullable=True),
        sa.Column("shift_assignment_ref", sa.String(length=100), nullable=True),
        sa.Column("production_report_ref", sa.String(length=100), nullable=True),
        sa.Column("actual_wps_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("welding_position", sa.String(length=50), nullable=True),
        sa.Column("shielding_gas", sa.String(length=100), nullable=True),
        sa.Column("back_purge", sa.Boolean(), nullable=True),
        sa.Column("operation_note", sa.Text(), nullable=True),
        sa.Column(
            "record_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint(
            "sequence_no > 0",
            name="ck_engineering_weld_operations_sequence_positive",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('DRAFT', 'COMPLETED', 'CANCELLED')",
            name="ck_engineering_weld_operations_lifecycle_status",
        ),
        sa.CheckConstraint(
            "weld_stage IN ('ROOT', 'FILL', 'CAP', 'BACK_WELD', 'TACK')",
            name="ck_engineering_weld_operations_weld_stage",
        ),
        sa.CheckConstraint(
            "length(trim(welding_method)) > 0",
            name="ck_engineering_weld_operations_method_not_empty",
        ),
        sa.CheckConstraint(
            "record_version > 0",
            name="ck_engineering_weld_operations_record_version_positive",
        ),
        sa.CheckConstraint(
            _TIME_CHECK, name="ck_engineering_weld_operations_time_range"
        ),
        sa.CheckConstraint(
            _COMPLETION_CHECK, name="ck_engineering_weld_operations_completion"
        ),
        sa.CheckConstraint(
            _CANCELLATION_CHECK,
            name="ck_engineering_weld_operations_cancellation",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actual_welder_id"],
            [f"{WELDING_SCHEMA}.welders.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "joint_id",
            "sequence_no",
            name="uq_engineering_weld_operations_joint_sequence",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    for name, columns in _INDEXES:
        op.create_index(
            name, "weld_operations", columns, schema=ENGINEERING_SCHEMA
        )


def downgrade() -> None:
    for name, _columns in reversed(_INDEXES):
        op.drop_index(
            name, table_name="weld_operations", schema=ENGINEERING_SCHEMA
        )
    op.drop_table("weld_operations", schema=ENGINEERING_SCHEMA)
