"""joint ↔ document_revision immutable link history with snapshot_* fields (Task 6).

Revision ID: 20260711_07_joint_doc_revisions
Revises: 20260711_06_joint_review
Create Date: 2026-07-11

Task 6 по ADR-010 и IMPLEMENTATION_PLAN §Task 6: неизменяемая история связи
Joint ↔ DocumentRevision с полным снимком инженерных параметров стыка (колонки с
префиксом `snapshot_`, явно отделяющим историческую копию от текущих полей Joint),
ролями связи (revision_role / document_role), статусом (ACTIVE/INVALIDATED) и
аннулированием. Инварианты БД: одна активная PRIMARY-связь на Joint; уникальность
`snapshot_joint_no_normalized` среди ACTIVE-связей одной ревизии; одна ORIGIN-связь
на Joint.

Данные Task 5A/5B сохраняются: для каждого существующего Joint создаётся
ORIGIN/PRIMARY/ACTIVE-связь со снимком текущих параметров (origin-ревизия).
Дополнительно: CHECK ck_engineering_joint_events_type расширяется значением
CURRENT_REVISION_CHANGED.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_07_joint_doc_revisions"
down_revision: Union[str, None] = "20260711_06_joint_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENGINEERING_SCHEMA = "engineering"

REVISION_ROLE_CHECK = (
    "revision_role IN ('ORIGIN', 'CONFIRMED', 'MODIFIED', 'REMOVED')"
)
DOCUMENT_ROLE_CHECK = (
    "document_role IN ('PRIMARY', 'ADDITIONAL', 'EXECUTIVE', 'REFERENCE')"
)
LINK_STATUS_CHECK = "link_status IN ('ACTIVE', 'INVALIDATED')"
INVALIDATION_CHECK = (
    "(link_status = 'ACTIVE' AND invalidated_at IS NULL "
    "AND invalidated_by IS NULL AND invalidated_reason IS NULL) "
    "OR (link_status = 'INVALIDATED' AND invalidated_at IS NOT NULL "
    "AND invalidated_by IS NOT NULL "
    "AND length(trim(invalidated_reason)) > 0)"
)

# CHECK joint_events: старый и новый (с CURRENT_REVISION_CHANGED) наборы.
_EVENT_TYPES_BASE = (
    "'SUBMITTED_FOR_REVIEW', 'REVIEW_REOPENED', 'PTO_APPROVED', 'PTO_REJECTED', "
    "'PTO_REVOKED', 'OGS_APPROVED', 'OGS_REJECTED', 'OGS_REVOKED', 'ACTIVATED', "
    "'DEACTIVATED', 'APPROVAL_RESET', 'APPROVAL_CARRIED_FORWARD', 'SIGNIFICANT_EDIT', "
    "'BLOCKED', 'UNBLOCKED', 'CANCELLED', 'SUPERSEDED'"
)
EVENT_TYPE_CHECK_OLD = f"event_type IN ({_EVENT_TYPES_BASE})"
EVENT_TYPE_CHECK_NEW = (
    f"event_type IN ({_EVENT_TYPES_BASE}, 'CURRENT_REVISION_CHANGED')"
)

# Колонки снимка: (имя snapshot_*, тип, nullable). Источник backfill — одноимённое
# поле Joint без префикса snapshot_.
_SNAPSHOT_SPEC = [
    ("snapshot_joint_no", sa.String(length=100), False),
    ("snapshot_joint_no_normalized", sa.String(length=100), False),
    ("snapshot_line_id", postgresql.UUID(as_uuid=True), False),
    ("snapshot_dn_1", sa.Numeric(), True),
    ("snapshot_dn_2", sa.Numeric(), True),
    ("snapshot_thickness_1", sa.Numeric(), True),
    ("snapshot_thickness_2", sa.Numeric(), True),
    ("snapshot_material_id_1", postgresql.UUID(as_uuid=True), True),
    ("snapshot_material_id_2", postgresql.UUID(as_uuid=True), True),
    ("snapshot_material_text_1", sa.String(length=255), True),
    ("snapshot_material_text_2", sa.String(length=255), True),
    ("snapshot_component_type_1", sa.String(length=50), True),
    ("snapshot_component_type_2", sa.String(length=50), True),
    ("snapshot_component_item_id_1", postgresql.UUID(as_uuid=True), True),
    ("snapshot_component_item_id_2", postgresql.UUID(as_uuid=True), True),
    ("snapshot_component_text_1", sa.String(length=255), True),
    ("snapshot_component_text_2", sa.String(length=255), True),
    ("snapshot_geometry_type", sa.String(length=20), True),
    ("snapshot_weld_joint_type", sa.String(length=20), True),
    ("snapshot_connection_code", sa.String(length=20), True),
    ("snapshot_required_root_method", sa.String(length=50), True),
    ("snapshot_required_fill_method", sa.String(length=50), True),
    ("snapshot_required_cap_method", sa.String(length=50), True),
    ("snapshot_planned_wps_id", postgresql.UUID(as_uuid=True), True),
    ("snapshot_heat_treatment_required", sa.Boolean(), False),
    ("snapshot_heat_treatment_type", sa.String(length=50), True),
    ("snapshot_heat_treatment_note", sa.Text(), True),
    ("snapshot_sheet_no", sa.String(length=50), True),
    ("snapshot_drawing_zone", sa.String(length=50), True),
    ("snapshot_position_x", sa.Numeric(), True),
    ("snapshot_position_y", sa.Numeric(), True),
    ("snapshot_coordinate_system", sa.String(length=50), True),
    ("snapshot_location_note", sa.Text(), True),
    ("snapshot_document_note", sa.Text(), True),
]


def _snapshot_columns() -> list[sa.Column]:
    cols: list[sa.Column] = []
    for name, type_, nullable in _SNAPSHOT_SPEC:
        kwargs = {}
        if name == "snapshot_heat_treatment_required":
            kwargs["server_default"] = sa.text("false")
        cols.append(sa.Column(name, type_, nullable=nullable, **kwargs))
    return cols


def _create_link_table() -> None:
    op.create_table(
        "joint_document_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("revision_role", sa.String(length=20), nullable=False),
        sa.Column("document_role", sa.String(length=20), nullable=False),
        sa.Column(
            "link_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.Text(), nullable=True),
        sa.Column("invalidated_by", sa.Integer(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        *_snapshot_columns(),
        sa.CheckConstraint(
            REVISION_ROLE_CHECK,
            name="ck_engineering_joint_doc_revisions_revision_role",
        ),
        sa.CheckConstraint(
            DOCUMENT_ROLE_CHECK,
            name="ck_engineering_joint_doc_revisions_document_role",
        ),
        sa.CheckConstraint(
            LINK_STATUS_CHECK,
            name="ck_engineering_joint_doc_revisions_link_status",
        ),
        sa.CheckConstraint(
            "length(trim(snapshot_joint_no_normalized)) > 0",
            name="ck_engineering_joint_doc_revisions_snapshot_norm_not_empty",
        ),
        sa.CheckConstraint(
            INVALIDATION_CHECK,
            name="ck_engineering_joint_doc_revisions_invalidation",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"],
            [f"{ENGINEERING_SCHEMA}.joints.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_revision_id"],
            [f"{ENGINEERING_SCHEMA}.document_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_doc_revisions_joint_id",
        "joint_document_revisions",
        ["joint_id"],
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "ix_engineering_joint_doc_revisions_revision_id",
        "joint_document_revisions",
        ["document_revision_id"],
        schema=ENGINEERING_SCHEMA,
    )
    op.create_index(
        "uq_engineering_joint_doc_revisions_active_no",
        "joint_document_revisions",
        ["document_revision_id", "snapshot_joint_no_normalized"],
        unique=True,
        schema=ENGINEERING_SCHEMA,
        postgresql_where=sa.text("link_status = 'ACTIVE'"),
    )
    op.create_index(
        "uq_engineering_joint_doc_revisions_active_primary",
        "joint_document_revisions",
        ["joint_id"],
        unique=True,
        schema=ENGINEERING_SCHEMA,
        postgresql_where=sa.text(
            "link_status = 'ACTIVE' AND document_role = 'PRIMARY'"
        ),
    )
    op.create_index(
        "uq_engineering_joint_doc_revisions_origin",
        "joint_document_revisions",
        ["joint_id"],
        unique=True,
        schema=ENGINEERING_SCHEMA,
        postgresql_where=sa.text("revision_role = 'ORIGIN'"),
    )


def _backfill_origin_links() -> None:
    """ORIGIN/PRIMARY/ACTIVE-связь для каждого существующего Joint (правило 3).

    Снимок берётся из текущих полей Joint; source-колонка = имя snapshot_* без
    префикса. Ревизия связи — origin_document_revision_id (неизменяемое основание).
    """
    snapshot_cols = ", ".join(name for name, _, _ in _SNAPSHOT_SPEC)
    snapshot_src = ", ".join(
        f"j.{name[len('snapshot_'):]}" for name, _, _ in _SNAPSHOT_SPEC
    )
    op.execute(
        f"""
        INSERT INTO {ENGINEERING_SCHEMA}.joint_document_revisions
            (id, joint_id, document_revision_id, revision_role, document_role,
             link_status, created_by, created_at, {snapshot_cols})
        SELECT
            gen_random_uuid(), j.id, j.origin_document_revision_id,
            'ORIGIN', 'PRIMARY', 'ACTIVE', j.created_by, j.created_at, {snapshot_src}
        FROM {ENGINEERING_SCHEMA}.joints AS j
        """
    )


def _extend_event_check() -> None:
    op.drop_constraint(
        "ck_engineering_joint_events_type",
        "joint_events",
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_joint_events_type",
        "joint_events",
        EVENT_TYPE_CHECK_NEW,
        schema=ENGINEERING_SCHEMA,
    )


def upgrade() -> None:
    _create_link_table()
    _backfill_origin_links()
    _extend_event_check()


def downgrade() -> None:
    # Вернуть прежний CHECK joint_events (запретив откат при наличии новых событий).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM "{ENGINEERING_SCHEMA}".joint_events
                WHERE event_type = 'CURRENT_REVISION_CHANGED'
            ) THEN
                RAISE EXCEPTION
                    'Нельзя откатить: есть события CURRENT_REVISION_CHANGED (Task 6)';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(
        "ck_engineering_joint_events_type",
        "joint_events",
        schema=ENGINEERING_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_engineering_joint_events_type",
        "joint_events",
        EVENT_TYPE_CHECK_OLD,
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "uq_engineering_joint_doc_revisions_origin",
        table_name="joint_document_revisions",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "uq_engineering_joint_doc_revisions_active_primary",
        table_name="joint_document_revisions",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "uq_engineering_joint_doc_revisions_active_no",
        table_name="joint_document_revisions",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "ix_engineering_joint_doc_revisions_revision_id",
        table_name="joint_document_revisions",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_index(
        "ix_engineering_joint_doc_revisions_joint_id",
        table_name="joint_document_revisions",
        schema=ENGINEERING_SCHEMA,
    )
    op.drop_table("joint_document_revisions", schema=ENGINEERING_SCHEMA)
