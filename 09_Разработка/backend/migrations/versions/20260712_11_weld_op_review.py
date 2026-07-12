"""weld operation welder confirmation & OGS review (Task 8C).

Revision ID: 20260712_11_weld_op_review
Revises: 20260712_10_weld_op_validation
Create Date: 2026-07-12

Task 8C по ADR-012: добавляет в engineering.weld_operations две независимые оси
состояния — подтверждение фактического сварщика (§4 задания) и технологическое
решение ОГС (§5). Полная история решений хранится в двух append-only таблицах.

Оси не объединяются с lifecycle и с автоматическими validation-статусами Task 8B
(§2-3 задания). Новые колонки получают server defaults и детерминированный backfill
(§14.1): existing DRAFT/CANCELLED → PENDING/PENDING; COMPLETED → confirmation
PENDING и ogs_review NOT_REQUIRED только при PASS/PASS validation, иначе PENDING.
History rows при backfill не создаются (исторического actor-решения не было).

Не изменяет welder_admissions и таблицы Task 8D/8E (их ещё не существует).
Downgrade удаляет только объекты Task 8C.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_11_weld_op_review"
down_revision: Union[str, None] = "20260712_10_weld_op_validation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"
TABLE = "weld_operations"
CONFIRM_TABLE = "weld_operation_welder_confirmations"
REVIEW_TABLE = "weld_operation_ogs_reviews"

_CONFIRMATION_STATUS_VALUES = "('PENDING', 'CONFIRMED', 'DISPUTED')"
_REVIEW_STATUS_VALUES = "('NOT_REQUIRED', 'PENDING', 'APPROVED', 'REJECTED')"

_WELDER_CONFIRMATION_ACTOR_CHECK = (
    "(welder_confirmation_status = 'PENDING' "
    "AND welder_confirmed_at IS NULL AND welder_confirmed_by IS NULL) "
    "OR (welder_confirmation_status IN ('CONFIRMED', 'DISPUTED') "
    "AND welder_confirmed_at IS NOT NULL AND welder_confirmed_by IS NOT NULL)"
)
_OGS_REVIEW_ACTOR_CHECK = (
    "(ogs_review_status IN ('NOT_REQUIRED', 'PENDING') "
    "AND ogs_reviewed_at IS NULL AND ogs_reviewed_by IS NULL) "
    "OR (ogs_review_status IN ('APPROVED', 'REJECTED') "
    "AND ogs_reviewed_at IS NOT NULL AND ogs_reviewed_by IS NOT NULL)"
)

# CHECK-и проекции weld_operations (§7.3). Порядок: имя → условие.
_WELD_OP_CHECKS = (
    (
        "ck_engineering_weld_operations_welder_confirmation_status",
        f"welder_confirmation_status IN {_CONFIRMATION_STATUS_VALUES}",
    ),
    (
        "ck_engineering_weld_operations_ogs_review_status",
        f"ogs_review_status IN {_REVIEW_STATUS_VALUES}",
    ),
    (
        "ck_engineering_weld_operations_welder_confirmation_version",
        "welder_confirmation_version > 0",
    ),
    (
        "ck_engineering_weld_operations_ogs_review_version",
        "ogs_review_version > 0",
    ),
    (
        "ck_engineering_weld_operations_welder_confirmation_actor",
        _WELDER_CONFIRMATION_ACTOR_CHECK,
    ),
    (
        "ck_engineering_weld_operations_ogs_review_actor",
        _OGS_REVIEW_ACTOR_CHECK,
    ),
    (
        "ck_engineering_weld_operations_ogs_review_reason_array",
        "jsonb_typeof(ogs_review_reason_codes) = 'array'",
    ),
    (
        "ck_engineering_weld_operations_ogs_review_reject_reason",
        "ogs_review_status <> 'REJECTED' "
        "OR jsonb_array_length(ogs_review_reason_codes) > 0",
    ),
)

_WELD_OP_INDEXES = (
    (
        "ix_engineering_weld_operations_welder_confirmation_status",
        ["welder_confirmation_status"],
    ),
    (
        "ix_engineering_weld_operations_ogs_review_status",
        ["ogs_review_status"],
    ),
)


def upgrade() -> None:
    # 1. Колонки-проекции confirmation (§7.1) с server defaults.
    op.add_column(
        TABLE,
        sa.Column(
            "welder_confirmation_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "welder_confirmation_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "welder_confirmed_at", sa.DateTime(timezone=True), nullable=True
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("welder_confirmed_by", sa.Integer(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("welder_confirmation_comment", sa.Text(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )

    # 2. Колонки-проекции review ОГС (§7.2) с server defaults.
    op.add_column(
        TABLE,
        sa.Column(
            "ogs_review_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "ogs_review_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("ogs_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("ogs_reviewed_by", sa.Integer(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("ogs_review_comment", sa.Text(), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "ogs_review_reason_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=ENGINEERING_SCHEMA,
    )

    # 3. Backfill существующих операций (§14.1). Server defaults уже дали PENDING
    # для confirmation и review; корректируем только завершённые PASS/PASS в
    # NOT_REQUIRED. History rows не создаём — исторического решения не было.
    op.execute(
        f"""
        UPDATE {ENGINEERING_SCHEMA}.{TABLE}
        SET ogs_review_status = 'NOT_REQUIRED'
        WHERE lifecycle_status = 'COMPLETED'
          AND qualification_validation_status = 'PASS'
          AND wps_validation_status = 'PASS'
        """
    )

    # 4. CHECK constraints и индексы проекции (§7.3).
    for name, condition in _WELD_OP_CHECKS:
        op.create_check_constraint(
            name, TABLE, condition, schema=ENGINEERING_SCHEMA
        )
    for name, columns in _WELD_OP_INDEXES:
        op.create_index(name, TABLE, columns, schema=ENGINEERING_SCHEMA)

    # 5. История подтверждений сварщика (§8.1), append-only.
    op.create_table(
        CONFIRM_TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "weld_operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{ENGINEERING_SCHEMA}.{TABLE}.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("confirmation_version", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "weld_operation_id",
            "confirmation_version",
            name="uq_engineering_weld_op_welder_confirmations_version",
        ),
        sa.CheckConstraint(
            "decision IN ('CONFIRMED', 'DISPUTED')",
            name="ck_engineering_weld_op_welder_confirmations_decision",
        ),
        sa.CheckConstraint(
            "confirmation_version > 0",
            name="ck_engineering_weld_op_welder_confirmations_version_positive",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_weld_op_welder_confirmations_operation_id",
        CONFIRM_TABLE,
        ["weld_operation_id"],
        schema=ENGINEERING_SCHEMA,
    )

    # 6. История review ОГС (§8.2), append-only, со снимком validation Task 8B.
    op.create_table(
        REVIEW_TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "weld_operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{ENGINEERING_SCHEMA}.{TABLE}.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column(
            "qualification_validation_status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "qualification_validation_codes",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "wps_validation_status", sa.String(length=20), nullable=False
        ),
        sa.Column(
            "wps_validation_codes", postgresql.JSONB(), nullable=False
        ),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "weld_operation_id",
            "review_version",
            name="uq_engineering_weld_op_ogs_reviews_version",
        ),
        sa.CheckConstraint(
            "decision IN ('APPROVED', 'REJECTED')",
            name="ck_engineering_weld_op_ogs_reviews_decision",
        ),
        sa.CheckConstraint(
            "review_version > 0",
            name="ck_engineering_weld_op_ogs_reviews_version_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reason_codes) = 'array'",
            name="ck_engineering_weld_op_ogs_reviews_reason_array",
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_weld_op_ogs_reviews_operation_id",
        REVIEW_TABLE,
        ["weld_operation_id"],
        schema=ENGINEERING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_engineering_weld_op_ogs_reviews_operation_id",
        table_name=REVIEW_TABLE,
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table(REVIEW_TABLE, schema=ENGINEERING_SCHEMA)
    op.drop_index(
        "ix_engineering_weld_op_welder_confirmations_operation_id",
        table_name=CONFIRM_TABLE,
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table(CONFIRM_TABLE, schema=ENGINEERING_SCHEMA)

    for name, _columns in reversed(_WELD_OP_INDEXES):
        op.drop_index(name, table_name=TABLE, schema=ENGINEERING_SCHEMA)
    for name, _condition in reversed(_WELD_OP_CHECKS):
        op.drop_constraint(name, TABLE, schema=ENGINEERING_SCHEMA, type_="check")
    for column in (
        "ogs_review_reason_codes",
        "ogs_review_comment",
        "ogs_reviewed_by",
        "ogs_reviewed_at",
        "ogs_review_version",
        "ogs_review_status",
        "welder_confirmation_comment",
        "welder_confirmed_by",
        "welder_confirmed_at",
        "welder_confirmation_version",
        "welder_confirmation_status",
    ):
        op.drop_column(TABLE, column, schema=ENGINEERING_SCHEMA)
