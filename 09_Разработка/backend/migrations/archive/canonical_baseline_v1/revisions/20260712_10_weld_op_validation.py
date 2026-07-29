"""weld operation qualification & wps validation (Task 8B).

Revision ID: 20260712_10_weld_op_validation
Revises: 20260712_09_weld_operations
Create Date: 2026-07-12

Task 8B по ADR-012: расширяет engineering.weld_operations полями автоматической
технической проверки допуска сварщика и WPS. Проверка информационная — не
блокирует производственный факт и не пересчитывается после COMPLETED (§4 задания).

Новые колонки получают server defaults, поэтому существующие операции переходят в
NOT_CHECKED без исторического пересчёта (§15). Не создаются таблицы WPS/review и не
изменяется welder_admissions. Downgrade удаляет только объекты Task 8B.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_10_weld_op_validation"
down_revision: Union[str, None] = "20260712_09_weld_operations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"
TABLE = "weld_operations"

_CHECKED_AT_CHECK = (
    "(validation_checked_at IS NULL "
    "AND qualification_validation_status = 'NOT_CHECKED' "
    "AND wps_validation_status = 'NOT_CHECKED') "
    "OR (validation_checked_at IS NOT NULL "
    "AND qualification_validation_status <> 'NOT_CHECKED' "
    "AND wps_validation_status <> 'NOT_CHECKED')"
)
_QUAL_CODES_CHECK = (
    "(qualification_validation_status IN ('FAIL', 'INDETERMINATE') "
    "AND jsonb_array_length(qualification_validation_codes) > 0) "
    "OR (qualification_validation_status IN ('NOT_CHECKED', 'PASS') "
    "AND jsonb_array_length(qualification_validation_codes) = 0)"
)
_WPS_CODES_CHECK = (
    "(wps_validation_status IN ('FAIL', 'INDETERMINATE') "
    "AND jsonb_array_length(wps_validation_codes) > 0) "
    "OR (wps_validation_status IN ('NOT_CHECKED', 'PASS') "
    "AND jsonb_array_length(wps_validation_codes) = 0)"
)

_STATUS_VALUES = "('NOT_CHECKED', 'PASS', 'FAIL', 'INDETERMINATE')"

_CHECKS = (
    (
        "ck_engineering_weld_operations_qual_validation_status",
        f"qualification_validation_status IN {_STATUS_VALUES}",
    ),
    (
        "ck_engineering_weld_operations_wps_validation_status",
        f"wps_validation_status IN {_STATUS_VALUES}",
    ),
    ("ck_engineering_weld_operations_validation_checked_at", _CHECKED_AT_CHECK),
    ("ck_engineering_weld_operations_qual_validation_codes", _QUAL_CODES_CHECK),
    ("ck_engineering_weld_operations_wps_validation_codes", _WPS_CODES_CHECK),
)

_INDEXES = (
    (
        "ix_engineering_weld_operations_qual_validation_status",
        ["qualification_validation_status"],
    ),
    (
        "ix_engineering_weld_operations_wps_validation_status",
        ["wps_validation_status"],
    ),
)


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("validation_checked_at", sa.DateTime(timezone=True), nullable=True),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "validation_source_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "qualification_validation_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NOT_CHECKED'"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "qualification_validation_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "qualification_admission_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "qualification_snapshot",
            postgresql.JSONB(),
            nullable=True,
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "wps_validation_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NOT_CHECKED'"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "wps_validation_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=ENGINEERING_SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "wps_validation_snapshot",
            postgresql.JSONB(),
            nullable=True,
        ),
        schema=ENGINEERING_SCHEMA,
    )

    for name, condition in _CHECKS:
        op.create_check_constraint(
            name, TABLE, condition, schema=ENGINEERING_SCHEMA
        )
    for name, columns in _INDEXES:
        op.create_index(name, TABLE, columns, schema=ENGINEERING_SCHEMA)


def downgrade() -> None:
    for name, _columns in reversed(_INDEXES):
        op.drop_index(name, table_name=TABLE, schema=ENGINEERING_SCHEMA)
    for name, _condition in reversed(_CHECKS):
        op.drop_constraint(name, TABLE, schema=ENGINEERING_SCHEMA, type_="check")
    for column in (
        "wps_validation_snapshot",
        "wps_validation_codes",
        "wps_validation_status",
        "qualification_snapshot",
        "qualification_admission_id",
        "qualification_validation_codes",
        "qualification_validation_status",
        "validation_source_version",
        "validation_checked_at",
    ):
        op.drop_column(TABLE, column, schema=ENGINEERING_SCHEMA)
