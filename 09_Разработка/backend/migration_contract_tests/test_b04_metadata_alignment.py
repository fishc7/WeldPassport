"""Pure contracts for the B-04A canonical metadata fingerprint alignment."""

from __future__ import annotations

import pytest

from app.shared.canonical_metadata import canonical_metadata


HISTORICAL_COLUMN_ORDER = {
    "engineering.joints": (
        "id",
        "project_id",
        "line_id",
        "origin_document_revision_id",
        "current_document_revision_id",
        "system_code",
        "joint_no",
        "joint_no_normalized",
        "status",
        "record_version",
        "dn_1",
        "dn_2",
        "thickness_1",
        "thickness_2",
        "material_id_1",
        "material_id_2",
        "material_text_1",
        "material_text_2",
        "component_type_1",
        "component_type_2",
        "component_item_id_1",
        "component_item_id_2",
        "component_text_1",
        "component_text_2",
        "geometry_type",
        "weld_joint_type",
        "connection_code",
        "required_root_method",
        "required_fill_method",
        "required_cap_method",
        "planned_wps_id",
        "heat_treatment_required",
        "heat_treatment_type",
        "heat_treatment_note",
        "sheet_no",
        "drawing_zone",
        "position_x",
        "position_y",
        "coordinate_system",
        "location_note",
        "document_note",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
        "approval_version",
        "workflow_version",
        "pto_status",
        "pto_pending_reason",
        "pto_decision_method",
        "pto_approval_version",
        "pto_decided_by",
        "pto_decided_at",
        "pto_comment",
        "ogs_status",
        "ogs_pending_reason",
        "ogs_decision_method",
        "ogs_approval_version",
        "ogs_decided_by",
        "ogs_decided_at",
        "ogs_comment",
        "submitted_by",
        "submitted_at",
        "cancelled_reason",
        "cancelled_by",
        "cancelled_at",
        "superseded_by_joint_id",
        "superseded_by",
        "superseded_at",
    ),
    "quality.laboratory_conclusions": (
        "id",
        "project_id",
        "laboratory_company_id",
        "inspection_method_id",
        "root_conclusion_id",
        "revision_no",
        "supersedes_conclusion_id",
        "is_current",
        "external_revision_label",
        "correction_reason",
        "conclusion_number",
        "conclusion_year",
        "issued_at",
        "request_reference",
        "request_date",
        "requesting_company_id",
        "laboratory_accreditation_id",
        "laboratory_name_snapshot",
        "accreditation_number_snapshot",
        "accreditation_valid_from_snapshot",
        "accreditation_valid_until_snapshot",
        "accreditation_scope_snapshot",
        "lab_approver_person_id",
        "issued_by_person_id",
        "source_type",
        "source_reference",
        "source_received_at",
        "status",
        "lab_approved_by_worker_id",
        "lab_approved_at",
        "registered_by_worker_id",
        "registered_at",
        "cancellation_reason",
        "cancelled_by_worker_id",
        "cancelled_at",
        "revision_review_required",
        "revision_review_reason",
        "created_by_worker_id",
        "created_at",
        "updated_by_worker_id",
        "updated_at",
        "version",
        "normalized_conclusion_number",
    ),
    "quality.quality_audit_events": (
        "id",
        "entity_type",
        "entity_id",
        "event_type",
        "changed_fields",
        "previous_values",
        "new_values",
        "reason",
        "actor_worker_id",
        "occurred_at",
        "authorization_context",
    ),
    "quality.quality_decisions": (
        "id",
        "project_id",
        "joint_id",
        "system_code",
        "status",
        "decision_result",
        "summary",
        "return_reason",
        "supersedes_quality_decision_id",
        "created_by_worker_id",
        "created_at",
        "approved_by_worker_id",
        "approved_at",
        "approved_role",
        "version",
        "review_submitted_by_worker_id",
    ),
}

HISTORICAL_DEFAULTS = {
    ("hr.departments", "is_active"): (True, "true"),
    ("hr.positions", "is_active"): (True, "true"),
    ("hr.worker_roles", "is_active"): (True, "true"),
    ("hr.workers", "employment_status"): ("active", "active"),
    ("welding.welder_admissions", "admission_status"): ("draft", "draft"),
    ("welding.welders", "status"): ("active", "active"),
}


def _semantic_server_default(table_key: str, column_name: str) -> str | None:
    default = canonical_metadata.tables[table_key].c[column_name].server_default
    if default is None:
        return None
    return str(default.arg).strip("'")


@pytest.mark.parametrize(
    ("table_key", "expected"),
    HISTORICAL_COLUMN_ORDER.items(),
)
def test_b04_alignment_001_matches_historical_column_order(
    table_key: str,
    expected: tuple[str, ...],
) -> None:
    """Changing an ORM declaration's physical position must break this contract."""
    assert tuple(canonical_metadata.tables[table_key].c.keys()) == expected


@pytest.mark.parametrize(
    ("table_key", "column_name", "python_default", "server_default"),
    tuple(
        (table_key, column_name, python_default, server_default)
        for (table_key, column_name), (
            python_default,
            server_default,
        ) in HISTORICAL_DEFAULTS.items()
    ),
)
def test_b04_alignment_002_restores_historical_server_defaults(
    table_key: str,
    column_name: str,
    python_default: object,
    server_default: str,
) -> None:
    """Dropping either side of an approved Python/server default must fail."""
    column = canonical_metadata.tables[table_key].c[column_name]

    assert column.default is not None
    assert column.default.arg == python_default
    assert _semantic_server_default(table_key, column_name) == server_default


def test_b04_alignment_003_names_joint_self_foreign_key() -> None:
    """The historical self-FK name is part of the strict fingerprint."""
    table = canonical_metadata.tables["engineering.joints"]
    self_foreign_keys = [
        foreign_key
        for foreign_key in table.foreign_key_constraints
        if tuple(column.name for column in foreign_key.columns)
        == ("superseded_by_joint_id",)
    ]

    assert len(self_foreign_keys) == 1
    assert self_foreign_keys[0].name == "fk_engineering_joints_superseded_by_joint"
    assert self_foreign_keys[0].referred_table is table
