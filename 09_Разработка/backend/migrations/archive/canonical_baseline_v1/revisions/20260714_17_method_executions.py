"""method executions and laboratory conclusions (Task 9C).

Revision ID: 20260714_17_method_executions
Revises: 20260713_16_method_assignments
Create Date: 2026-07-14

Task 9C по ADR-015 / Architecture Session 007: фактическое выполнение назначенного
метода контроля (`MethodExecution`), его участники, локальные результаты и стандарты,
а также лабораторное заключение (`LaboratoryConclusion`), связь заключение↔выполнение,
аккредитация лаборатории, внешнее лицо контроля и доменный аудит. В схему quality
добавляются 9 таблиц; существующие таблицы Tasks 9A/9B не изменяются.

Решения (планирование 9C + ревью 9C-1), отражённые в физической схеме:

* терминал выполнения — LAB_CONFIRMED (не VERIFIED); enum оценки —
  CONFORMING/NONCONFORMING/INCONCLUSIVE/NOT_EVALUATED;
* дочерние части выполнения (participants/result_items/standards) → method_executions
  с ON DELETE RESTRICT (историю несёт редакция, каскада производственной истории нет);
* root_*_id — обычные UUID БЕЗ self-FK; self-FK только у supersedes_* (SET NULL);
* одна текущая редакция — partial unique WHERE is_current; не более одного
  LEAD_INSPECTOR — partial unique; номер заключения нормализован partial unique
  WHERE status='ISSUED';
* лаборатория/компании — project.companies.id (Integer); actor-поля — hr.workers.id
  (Integer) БЕЗ FK (переходный период, как в 9A/9B).

Перечисления реализованы CHECK-ограничениями (без native enum). Downgrade удаляет
только объекты Task 9C; схема quality (её владеет Task 9A) не удаляется.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Локально закреплённые CHECK-наборы на момент миграции 17.
# Не импортировать из app.*: исторические миграции должны быть воспроизводимы
# при последующем расширении application-констант (см. миграцию 18 для
# расширения QUALITY_AUDIT_EVENT_TYPES).
EXECUTION_STATUSES = (
    "DRAFT",
    "IN_PROGRESS",
    "PERFORMED",
    "RESULT_RECORDED",
    "LAB_CONFIRMED",
    "CANCELLED",
    "SUPERSEDED",
)
CONFIRMATION_MODES = (
    "DIRECT_LAB_CONFIRMATION",
    "EXTERNAL_DOCUMENT_REGISTRATION",
)
TIME_PRECISIONS = ("DATE_ONLY", "START_TIME_KNOWN", "FULL_INTERVAL")
CANCELLATION_TYPES = (
    "CREATED_BY_MISTAKE",
    "DUPLICATE",
    "CONTROL_NOT_PERFORMED",
    "WRONG_ASSIGNMENT",
    "WRONG_LABORATORY",
    "OTHER",
)
PARTICIPANT_ROLES = (
    "LEAD_INSPECTOR",
    "INSPECTOR",
    "ASSISTANT",
    "TRAINEE",
    "RESULT_REVIEWER",
)
ENGAGEMENT_TYPES = (
    "EMPLOYEE",
    "CONTRACTOR",
    "SECONDMENT",
    "AUTHORIZED_EXTERNAL_SPECIALIST",
)
RESULT_STATES = ("DRAFT", "COMPLETE", "EXCLUDED")
CONTROLLED_OBJECT_TYPES = (
    "WHOLE_JOINT",
    "MEASURING_BELT_SEGMENT",
    "LINEAR_SEGMENT",
    "IMAGE",
    "SURFACE_AREA",
    "BASE_METAL_1",
    "BASE_METAL_2",
    "WELD_METAL",
    "HEAT_AFFECTED_ZONE",
    "OTHER",
)
COORDINATE_SYSTEMS = (
    "MEASURING_BELT",
    "LINEAR_WELD_LENGTH",
    "IMAGE_NUMBER",
    "SECTOR",
    "LOCAL_ZONE",
    "OTHER",
)
COORDINATE_UNITS = ("MM", "DEGREE", "NUMBER", "PERCENT", "TEXT")
CLOSED_COORDINATE_SYSTEMS = ("MEASURING_BELT", "SECTOR")
EVALUATIONS = (
    "CONFORMING",
    "NONCONFORMING",
    "INCONCLUSIVE",
    "NOT_EVALUATED",
)
REQUIRED_ACTIONS = (
    "NONE",
    "REPAIR",
    "RECONTROL",
    "ADDITIONAL_CONTROL",
    "REVIEW",
)
CALCULATED_COMPLETIONS = (
    "PARTIAL",
    "COMPLETE",
    "OVERLAPPING",
    "HAS_GAPS",
    "NOT_CALCULABLE",
)
DECLARED_COMPLETIONS = (
    "PARTIAL",
    "COMPLETE",
    "OVERFULFILLED",
    "NOT_DETERMINED",
)
INSPECTION_METHOD_CODES = ("VT", "RT", "UT", "PT", "MT", "LT")
CONCLUSION_STATUSES = (
    "DRAFT",
    "PREPARED",
    "LAB_APPROVED",
    "ISSUED",
    "CANCELLED",
    "SUPERSEDED",
)
ACCREDITATION_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")
QUALITY_AUDIT_ENTITY_TYPES = (
    "METHOD_EXECUTION",
    "METHOD_EXECUTION_PARTICIPANT",
    "METHOD_EXECUTION_RESULT_ITEM",
    "METHOD_EXECUTION_STANDARD",
    "LABORATORY_CONCLUSION",
    "LABORATORY_CONCLUSION_EXECUTION",
    "LABORATORY_ACCREDITATION",
)
# Набор event_type на момент миграции 17 (без расширений блока 9C-5 / миграции 18).
QUALITY_AUDIT_EVENT_TYPES = (
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

revision: str = "20260714_17_method_executions"
down_revision: Union[str, None] = "20260713_16_method_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUALITY = "quality"
PROJECT = "project"
ENGINEERING = "engineering"

PGUUID = postgresql.UUID(as_uuid=True)


def _in(column: str, values) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _nullable_in(column: str, values) -> str:
    return f"{column} IS NULL OR " + _in(column, values)


def _actor_audit_columns() -> list[sa.Column]:
    return [
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
    ]


def _fk_company(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{PROJECT}.companies.id"], ondelete="RESTRICT"
    )


def _fk_external_person(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{QUALITY}.quality_external_persons.id"], ondelete="RESTRICT"
    )


def _fk_execution(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{QUALITY}.method_executions.id"], ondelete="RESTRICT"
    )


_CLOSED_COORD = CLOSED_COORDINATE_SYSTEMS


def upgrade() -> None:
    _create_external_persons()
    _create_accreditations()
    _create_method_executions()
    _create_participants()
    _create_result_items()
    _create_standards()
    _create_conclusions()
    _create_conclusion_executions()
    _create_audit_events()


# ── quality_external_persons ───────────────────────────────────────────────────


def _create_external_persons() -> None:
    op.create_table(
        "quality_external_persons",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("organization_company_id", sa.Integer(), nullable=True),
        sa.Column("external_ref", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_actor_audit_columns(),
        sa.CheckConstraint(
            "length(trim(full_name)) > 0",
            name="ck_quality_external_persons_full_name_not_empty",
        ),
        _fk_company("organization_company_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_external_persons_organization",
        "quality_external_persons",
        ["organization_company_id"],
        schema=QUALITY,
    )


# ── laboratory_accreditations ──────────────────────────────────────────────────


def _create_accreditations() -> None:
    op.create_table(
        "laboratory_accreditations",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("certificate_number", sa.String(length=100), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("accreditation_scope", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        *_actor_audit_columns(),
        sa.CheckConstraint(
            _in("status", ACCREDITATION_STATUSES),
            name="ck_quality_accreditation_status",
        ),
        sa.CheckConstraint(
            "length(trim(certificate_number)) > 0",
            name="ck_quality_accreditation_cert_not_empty",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_quality_accreditation_valid_range",
        ),
        _fk_company("company_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_accreditation_company",
        "laboratory_accreditations",
        ["company_id"],
        schema=QUALITY,
    )


# ── method_executions ──────────────────────────────────────────────────────────

_EXEC_CANCELLED_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancellation_type IS NOT NULL "
    "AND cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)
_EXEC_TIME_INTERVAL_CHECK = (
    "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at"
)


def _create_method_executions() -> None:
    op.create_table(
        "method_executions",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("inspection_method_assignment_id", PGUUID, nullable=False),
        sa.Column("joint_id", PGUUID, nullable=False),
        sa.Column("project_id", PGUUID, nullable=False),
        sa.Column("laboratory_company_id", sa.Integer(), nullable=False),
        sa.Column("root_execution_id", PGUUID, nullable=False),
        sa.Column(
            "revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("supersedes_execution_id", PGUUID, nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("confirmation_mode", sa.String(length=40), nullable=True),
        sa.Column("performed_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_precision", sa.String(length=20), nullable=True),
        sa.Column("calculated_evaluation", sa.String(length=20), nullable=True),
        sa.Column("laboratory_evaluation", sa.String(length=20), nullable=True),
        sa.Column("evaluation_override_reason", sa.Text(), nullable=True),
        sa.Column("calculated_completion", sa.String(length=20), nullable=True),
        sa.Column("declared_completion", sa.String(length=20), nullable=True),
        sa.Column("completion_override_reason", sa.Text(), nullable=True),
        sa.Column("calculated_belt_length", sa.Numeric(), nullable=True),
        sa.Column("declared_belt_length", sa.Numeric(), nullable=True),
        sa.Column("belt_length_unit", sa.String(length=10), nullable=True),
        sa.Column("belt_length_override_reason", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("source_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("procedure_document_id", PGUUID, nullable=True),
        sa.Column("procedure_reference_snapshot", sa.Text(), nullable=True),
        sa.Column(
            "procedure_revision_snapshot", sa.String(length=100), nullable=True
        ),
        sa.Column("cancellation_type", sa.String(length=40), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lab_confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("lab_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lab_approver_person_id", PGUUID, nullable=True),
        sa.Column("external_lab_approver_person_id", PGUUID, nullable=True),
        sa.Column("external_lab_approval_date", sa.Date(), nullable=True),
        sa.Column("registered_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        *_actor_audit_columns(),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_quality_mexec_version"),
        sa.CheckConstraint("revision_no >= 1", name="ck_quality_mexec_revision_no"),
        sa.CheckConstraint(
            _in("status", EXECUTION_STATUSES), name="ck_quality_mexec_status"
        ),
        sa.CheckConstraint(
            _nullable_in("confirmation_mode", CONFIRMATION_MODES),
            name="ck_quality_mexec_confirmation_mode",
        ),
        sa.CheckConstraint(
            _nullable_in("time_precision", TIME_PRECISIONS),
            name="ck_quality_mexec_time_precision",
        ),
        sa.CheckConstraint(
            _nullable_in("calculated_evaluation", EVALUATIONS),
            name="ck_quality_mexec_calc_evaluation",
        ),
        sa.CheckConstraint(
            _nullable_in("laboratory_evaluation", EVALUATIONS),
            name="ck_quality_mexec_lab_evaluation",
        ),
        sa.CheckConstraint(
            _nullable_in("calculated_completion", CALCULATED_COMPLETIONS),
            name="ck_quality_mexec_calc_completion",
        ),
        sa.CheckConstraint(
            _nullable_in("declared_completion", DECLARED_COMPLETIONS),
            name="ck_quality_mexec_declared_completion",
        ),
        sa.CheckConstraint(
            _nullable_in("cancellation_type", CANCELLATION_TYPES),
            name="ck_quality_mexec_cancellation_type",
        ),
        sa.CheckConstraint(_EXEC_CANCELLED_CHECK, name="ck_quality_mexec_cancelled"),
        sa.CheckConstraint(
            _EXEC_TIME_INTERVAL_CHECK, name="ck_quality_mexec_time_interval"
        ),
        sa.ForeignKeyConstraint(
            ["inspection_method_assignment_id"],
            [f"{QUALITY}.inspection_method_assignments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["joint_id"], [f"{ENGINEERING}.joints.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], [f"{PROJECT}.projects.id"], ondelete="RESTRICT"
        ),
        _fk_company("laboratory_company_id"),
        sa.ForeignKeyConstraint(
            ["supersedes_execution_id"],
            [f"{QUALITY}.method_executions.id"],
            ondelete="SET NULL",
        ),
        _fk_external_person("lab_approver_person_id"),
        _fk_external_person("external_lab_approver_person_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "uq_quality_mexec_current_revision",
        "method_executions",
        ["root_execution_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mexec_assignment",
        "method_executions",
        ["inspection_method_assignment_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mexec_joint", "method_executions", ["joint_id"], schema=QUALITY
    )
    op.create_index(
        "ix_quality_mexec_laboratory",
        "method_executions",
        ["laboratory_company_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mexec_status", "method_executions", ["status"], schema=QUALITY
    )
    op.create_index(
        "ix_quality_mexec_root",
        "method_executions",
        ["root_execution_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mexec_created_at",
        "method_executions",
        ["created_at"],
        schema=QUALITY,
    )


# ── method_execution_participants ──────────────────────────────────────────────


def _create_participants() -> None:
    op.create_table(
        "method_execution_participants",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("method_execution_id", PGUUID, nullable=False),
        sa.Column("person_id", PGUUID, nullable=False),
        sa.Column("participant_organization_id", sa.Integer(), nullable=True),
        sa.Column("engagement_type", sa.String(length=40), nullable=True),
        sa.Column("engagement_basis", sa.Text(), nullable=True),
        sa.Column("participant_role", sa.String(length=20), nullable=False),
        sa.Column("person_certification_id", PGUUID, nullable=True),
        sa.Column("person_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column(
            "organization_name_snapshot", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "qualification_level_snapshot", sa.String(length=100), nullable=True
        ),
        sa.Column(
            "certificate_number_snapshot", sa.String(length=100), nullable=True
        ),
        sa.Column("certificate_valid_from_snapshot", sa.Date(), nullable=True),
        sa.Column("certificate_valid_until_snapshot", sa.Date(), nullable=True),
        sa.Column("certification_scope_snapshot", sa.Text(), nullable=True),
        *_actor_audit_columns(),
        sa.CheckConstraint(
            _in("participant_role", PARTICIPANT_ROLES),
            name="ck_quality_mexec_part_role",
        ),
        sa.CheckConstraint(
            _nullable_in("engagement_type", ENGAGEMENT_TYPES),
            name="ck_quality_mexec_part_engagement",
        ),
        _fk_execution("method_execution_id"),
        _fk_external_person("person_id"),
        _fk_company("participant_organization_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "uq_quality_mexec_part_lead",
        "method_execution_participants",
        ["method_execution_id"],
        unique=True,
        postgresql_where=sa.text("participant_role = 'LEAD_INSPECTOR'"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mexec_part_execution",
        "method_execution_participants",
        ["method_execution_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mexec_part_person",
        "method_execution_participants",
        ["person_id"],
        schema=QUALITY,
    )


# ── method_execution_result_items ──────────────────────────────────────────────

_RESULT_WRAPS_ZERO_CHECK = "NOT wraps_zero OR " + _in(
    "coordinate_system", _CLOSED_COORD
)
_RESULT_OTHER_CHECK = (
    "controlled_object_type <> 'OTHER' "
    "OR length(trim(coalesce(description, ''))) > 0"
)
_RESULT_EXCLUDED_CHECK = (
    "record_state <> 'EXCLUDED' "
    "OR length(trim(coalesce(excluded_reason, ''))) > 0"
)


def _create_result_items() -> None:
    op.create_table(
        "method_execution_result_items",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("method_execution_id", PGUUID, nullable=False),
        sa.Column("root_result_item_id", PGUUID, nullable=False),
        sa.Column(
            "revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("supersedes_result_item_id", PGUUID, nullable=True),
        sa.Column(
            "record_state",
            sa.String(length=20),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("controlled_object_type", sa.String(length=30), nullable=False),
        sa.Column("object_reference", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("coordinate_system", sa.String(length=30), nullable=True),
        sa.Column("coordinate_from", sa.Numeric(), nullable=True),
        sa.Column("coordinate_to", sa.Numeric(), nullable=True),
        sa.Column("coordinate_unit", sa.String(length=10), nullable=True),
        sa.Column(
            "wraps_zero",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("controlled_volume_value", sa.Numeric(), nullable=True),
        sa.Column("controlled_volume_unit", sa.String(length=10), nullable=True),
        sa.Column("coverage_percent", sa.Numeric(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("indication_description", sa.Text(), nullable=True),
        sa.Column("indication_coordinate_from", sa.Numeric(), nullable=True),
        sa.Column("indication_coordinate_to", sa.Numeric(), nullable=True),
        sa.Column(
            "indication_coordinate_unit", sa.String(length=10), nullable=True
        ),
        sa.Column(
            "evaluation",
            sa.String(length=20),
            server_default=sa.text("'NOT_EVALUATED'"),
            nullable=False,
        ),
        sa.Column("required_action", sa.String(length=30), nullable=True),
        sa.Column("laboratory_result_text", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_page_reference", sa.String(length=100), nullable=True),
        sa.Column("source_row_reference", sa.String(length=100), nullable=True),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        *_actor_audit_columns(),
        sa.CheckConstraint("revision_no >= 1", name="ck_quality_mres_revision_no"),
        sa.CheckConstraint(
            _in("record_state", RESULT_STATES), name="ck_quality_mres_state"
        ),
        sa.CheckConstraint(
            _in("controlled_object_type", CONTROLLED_OBJECT_TYPES),
            name="ck_quality_mres_object_type",
        ),
        sa.CheckConstraint(
            _nullable_in("coordinate_system", COORDINATE_SYSTEMS),
            name="ck_quality_mres_coord_system",
        ),
        sa.CheckConstraint(
            _nullable_in("coordinate_unit", COORDINATE_UNITS),
            name="ck_quality_mres_coord_unit",
        ),
        sa.CheckConstraint(
            _in("evaluation", EVALUATIONS), name="ck_quality_mres_evaluation"
        ),
        sa.CheckConstraint(
            _nullable_in("required_action", REQUIRED_ACTIONS),
            name="ck_quality_mres_required_action",
        ),
        sa.CheckConstraint(
            _RESULT_WRAPS_ZERO_CHECK, name="ck_quality_mres_wraps_zero"
        ),
        sa.CheckConstraint(_RESULT_OTHER_CHECK, name="ck_quality_mres_other_desc"),
        sa.CheckConstraint(
            _RESULT_EXCLUDED_CHECK, name="ck_quality_mres_excluded_reason"
        ),
        _fk_execution("method_execution_id"),
        sa.ForeignKeyConstraint(
            ["supersedes_result_item_id"],
            [f"{QUALITY}.method_execution_result_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mres_execution",
        "method_execution_result_items",
        ["method_execution_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mres_execution_state",
        "method_execution_result_items",
        ["method_execution_id", "record_state"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mres_root",
        "method_execution_result_items",
        ["root_result_item_id"],
        schema=QUALITY,
    )


# ── method_execution_standards ─────────────────────────────────────────────────


def _create_standards() -> None:
    op.create_table(
        "method_execution_standards",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("method_execution_id", PGUUID, nullable=False),
        sa.Column("standard_document_id", PGUUID, nullable=True),
        sa.Column("standard_code_snapshot", sa.String(length=100), nullable=True),
        sa.Column("standard_title_snapshot", sa.Text(), nullable=True),
        sa.Column("revision_snapshot", sa.String(length=100), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _fk_execution("method_execution_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_mstd_execution",
        "method_execution_standards",
        ["method_execution_id"],
        schema=QUALITY,
    )


# ── laboratory_conclusions ─────────────────────────────────────────────────────

_CONCLUSION_ISSUED_CHECK = (
    "status <> 'ISSUED' OR ("
    "conclusion_number IS NOT NULL "
    "AND conclusion_year IS NOT NULL "
    "AND issued_at IS NOT NULL)"
)
_CONCLUSION_CANCELLED_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)


def _create_conclusions() -> None:
    op.create_table(
        "laboratory_conclusions",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("project_id", PGUUID, nullable=False),
        sa.Column("laboratory_company_id", sa.Integer(), nullable=False),
        sa.Column("inspection_method_id", sa.String(length=10), nullable=False),
        sa.Column("root_conclusion_id", PGUUID, nullable=False),
        sa.Column(
            "revision_no", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("supersedes_conclusion_id", PGUUID, nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("external_revision_label", sa.String(length=100), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("conclusion_number", sa.String(length=100), nullable=True),
        sa.Column("conclusion_year", sa.Integer(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_reference", sa.Text(), nullable=True),
        sa.Column("request_date", sa.Date(), nullable=True),
        sa.Column("requesting_company_id", sa.Integer(), nullable=True),
        sa.Column("laboratory_accreditation_id", PGUUID, nullable=True),
        sa.Column("laboratory_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column(
            "accreditation_number_snapshot", sa.String(length=100), nullable=True
        ),
        sa.Column("accreditation_valid_from_snapshot", sa.Date(), nullable=True),
        sa.Column("accreditation_valid_until_snapshot", sa.Date(), nullable=True),
        sa.Column("accreditation_scope_snapshot", sa.Text(), nullable=True),
        sa.Column("lab_approver_person_id", PGUUID, nullable=True),
        sa.Column("issued_by_person_id", PGUUID, nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("source_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("lab_approved_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("lab_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revision_review_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("revision_review_reason", sa.Text(), nullable=True),
        *_actor_audit_columns(),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_quality_labconc_version"),
        sa.CheckConstraint(
            "revision_no >= 1", name="ck_quality_labconc_revision_no"
        ),
        sa.CheckConstraint(
            _in("status", CONCLUSION_STATUSES), name="ck_quality_labconc_status"
        ),
        sa.CheckConstraint(
            _in("inspection_method_id", INSPECTION_METHOD_CODES),
            name="ck_quality_labconc_method",
        ),
        sa.CheckConstraint(
            "conclusion_year IS NULL OR (conclusion_year BETWEEN 1900 AND 3000)",
            name="ck_quality_labconc_year_range",
        ),
        sa.CheckConstraint(
            _CONCLUSION_ISSUED_CHECK, name="ck_quality_labconc_issued"
        ),
        sa.CheckConstraint(
            _CONCLUSION_CANCELLED_CHECK, name="ck_quality_labconc_cancelled"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], [f"{PROJECT}.projects.id"], ondelete="RESTRICT"
        ),
        _fk_company("laboratory_company_id"),
        _fk_company("requesting_company_id"),
        sa.ForeignKeyConstraint(
            ["supersedes_conclusion_id"],
            [f"{QUALITY}.laboratory_conclusions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["laboratory_accreditation_id"],
            [f"{QUALITY}.laboratory_accreditations.id"],
            ondelete="RESTRICT",
        ),
        _fk_external_person("lab_approver_person_id"),
        _fk_external_person("issued_by_person_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "uq_quality_labconc_issued_number",
        "laboratory_conclusions",
        ["laboratory_company_id", "conclusion_number", "conclusion_year"],
        unique=True,
        postgresql_where=sa.text("status = 'ISSUED'"),
        schema=QUALITY,
    )
    op.create_index(
        "uq_quality_labconc_current_revision",
        "laboratory_conclusions",
        ["root_conclusion_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_labconc_project",
        "laboratory_conclusions",
        ["project_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_labconc_laboratory",
        "laboratory_conclusions",
        ["laboratory_company_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_labconc_status",
        "laboratory_conclusions",
        ["status"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_labconc_root",
        "laboratory_conclusions",
        ["root_conclusion_id"],
        schema=QUALITY,
    )


# ── laboratory_conclusion_executions ───────────────────────────────────────────


def _create_conclusion_executions() -> None:
    op.create_table(
        "laboratory_conclusion_executions",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("laboratory_conclusion_id", PGUUID, nullable=False),
        sa.Column("method_execution_id", PGUUID, nullable=False),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "laboratory_conclusion_id",
            "method_execution_id",
            name="uq_quality_labconc_exec_pair",
        ),
        sa.ForeignKeyConstraint(
            ["laboratory_conclusion_id"],
            [f"{QUALITY}.laboratory_conclusions.id"],
            ondelete="RESTRICT",
        ),
        _fk_execution("method_execution_id"),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_labconc_exec_conclusion",
        "laboratory_conclusion_executions",
        ["laboratory_conclusion_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_labconc_exec_execution",
        "laboratory_conclusion_executions",
        ["method_execution_id"],
        schema=QUALITY,
    )


# ── quality_audit_events ───────────────────────────────────────────────────────


def _create_audit_events() -> None:
    op.create_table(
        "quality_audit_events",
        sa.Column("id", PGUUID, nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", PGUUID, nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=True),
        sa.Column("previous_values", postgresql.JSONB(), nullable=True),
        sa.Column("new_values", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_worker_id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("entity_type", QUALITY_AUDIT_ENTITY_TYPES),
            name="ck_quality_audit_entity_type",
        ),
        sa.CheckConstraint(
            _in("event_type", QUALITY_AUDIT_EVENT_TYPES),
            name="ck_quality_audit_event_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_audit_entity",
        "quality_audit_events",
        ["entity_type", "entity_id"],
        schema=QUALITY,
    )
    op.create_index(
        "ix_quality_audit_occurred_at",
        "quality_audit_events",
        ["occurred_at"],
        schema=QUALITY,
    )


def downgrade() -> None:
    # Обратный порядок: сначала зависимые, затем родительские таблицы.
    op.drop_table("quality_audit_events", schema=QUALITY)
    op.drop_table("laboratory_conclusion_executions", schema=QUALITY)
    op.drop_table("laboratory_conclusions", schema=QUALITY)
    op.drop_table("method_execution_standards", schema=QUALITY)
    op.drop_table("method_execution_result_items", schema=QUALITY)
    op.drop_table("method_execution_participants", schema=QUALITY)
    op.drop_table("method_executions", schema=QUALITY)
    op.drop_table("laboratory_accreditations", schema=QUALITY)
    op.drop_table("quality_external_persons", schema=QUALITY)
