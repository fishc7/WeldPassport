"""laboratory conclusion number normalization + audit events (Task 9C, блок 9C-5).

Revision ID: 20260714_18_labconc_extras
Revises: 20260714_17_method_executions
Create Date: 2026-07-14

Блок 9C-5 (сервисное ядро LaboratoryConclusion) требует:

* колонку `normalized_conclusion_number` для проверки бизнес-уникальности номера
  (нормализация пробелов/регистра, §5); исходный номер остаётся в
  `conclusion_number`. Partial unique index уникальности ISSUED-номера
  переносится с `conclusion_number` на `normalized_conclusion_number`;
* расширение CHECK `ck_quality_audit_event_type` четырьмя событиями заключения
  (CONCLUSION_EXECUTION_ADDED/REMOVED, CONCLUSION_REVISION_CANCELLED,
  CONCLUSION_REVIEW_REQUIRED). Миграция 17 задним числом не редактируется.

Данные существующих таблиц не изменяются. Downgrade полностью обратим.

CHECK-наборы зафиксированы локально (без импорта из app.*), чтобы исторические
миграции оставались воспроизводимы при последующем расширении application-кода.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_18_labconc_extras"
down_revision: Union[str, None] = "20260714_17_method_executions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY = "quality"
CONCLUSIONS = "laboratory_conclusions"
AUDIT = "quality_audit_events"
AUDIT_CHECK = "ck_quality_audit_event_type"
NUMBER_INDEX = "uq_quality_labconc_issued_number"

# Набор event_type после миграции 17 (до расширения 9C-5).
_AUDIT_EVENTS_AT_17 = (
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
)

# Значения, добавляемые этой миграцией.
_AUDIT_EVENTS_ADDED = (
    "CONCLUSION_EXECUTION_ADDED",
    "CONCLUSION_EXECUTION_REMOVED",
    "CONCLUSION_REVISION_CANCELLED",
    "CONCLUSION_REVIEW_REQUIRED",
)

_AUDIT_EVENTS_AT_18 = _AUDIT_EVENTS_AT_17 + _AUDIT_EVENTS_ADDED


def _event_check(values) -> str:
    return "event_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # 1. Нормализованный номер заключения.
    op.add_column(
        CONCLUSIONS,
        sa.Column(
            "normalized_conclusion_number", sa.String(length=100), nullable=True
        ),
        schema=QUALITY,
    )
    # 2. Перенос partial unique index на нормализованный номер.
    op.drop_index(NUMBER_INDEX, table_name=CONCLUSIONS, schema=QUALITY)
    op.create_index(
        NUMBER_INDEX,
        CONCLUSIONS,
        ["laboratory_company_id", "normalized_conclusion_number", "conclusion_year"],
        unique=True,
        postgresql_where=sa.text("status = 'ISSUED'"),
        schema=QUALITY,
    )
    # 3. Расширение CHECK допустимых event_type аудита.
    op.drop_constraint(AUDIT_CHECK, AUDIT, schema=QUALITY, type_="check")
    op.create_check_constraint(
        AUDIT_CHECK,
        AUDIT,
        _event_check(_AUDIT_EVENTS_AT_18),
        schema=QUALITY,
    )


def downgrade() -> None:
    op.drop_constraint(AUDIT_CHECK, AUDIT, schema=QUALITY, type_="check")
    op.create_check_constraint(
        AUDIT_CHECK,
        AUDIT,
        _event_check(_AUDIT_EVENTS_AT_17),
        schema=QUALITY,
    )
    op.drop_index(NUMBER_INDEX, table_name=CONCLUSIONS, schema=QUALITY)
    op.create_index(
        NUMBER_INDEX,
        CONCLUSIONS,
        ["laboratory_company_id", "conclusion_number", "conclusion_year"],
        unique=True,
        postgresql_where=sa.text("status = 'ISSUED'"),
        schema=QUALITY,
    )
    op.drop_column(CONCLUSIONS, "normalized_conclusion_number", schema=QUALITY)
