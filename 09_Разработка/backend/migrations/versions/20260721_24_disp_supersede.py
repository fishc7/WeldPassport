"""add DISPOSITION_SUPERSEDED event type (Task 9D-4A-4).

Revision ID: 20260721_24_disp_supersede
Revises: 20260721_23_disp_events
Create Date: 2026-07-21

Task 9D-4A-4: расширяет CHECK `quality.defect_disposition_events.event_type` новым
значением `DISPOSITION_SUPERSEDED` (событие старой версии при команде `SUPERSEDE`,
`ACTIVE → SUPERSEDED`). Миграции `20260721_22`/`20260721_23` не изменяются задним
числом — вместо этого CHECK-constraint пересоздаётся с расширенным списком значений.
Ни статусы `defect_dispositions`, ни существующие данные не затрагиваются.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260721_24_disp_supersede"
down_revision: Union[str, None] = "20260721_23_disp_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY_SCHEMA = "quality"
EVENTS_TABLE = "defect_disposition_events"
CONSTRAINT_NAME = "ck_defect_disposition_events_type"

OLD_EVENT_TYPES = (
    "DISPOSITION_CREATED",
    "DISPOSITION_PREPARED",
    "DISPOSITION_APPROVED",
    "DISPOSITION_ACTIVATED",
    "DISPOSITION_CANCELLED",
)
NEW_EVENT_TYPES = OLD_EVENT_TYPES + ("DISPOSITION_SUPERSEDED",)


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME, EVENTS_TABLE, schema=QUALITY_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        CONSTRAINT_NAME,
        EVENTS_TABLE,
        _in("event_type", NEW_EVENT_TYPES),
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME, EVENTS_TABLE, schema=QUALITY_SCHEMA, type_="check"
    )
    op.create_check_constraint(
        CONSTRAINT_NAME,
        EVENTS_TABLE,
        _in("event_type", OLD_EVENT_TYPES),
        schema=QUALITY_SCHEMA,
    )
