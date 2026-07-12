"""Юнит-тесты доменной политики корректировок и переварки (Task 8D, §21).

Чистый доменный модуль без БД: словари статусов, матрица типов и согласований,
критические поля, набор снимка, готовность к применению. Проверяет инварианты ТЗ,
включая отсутствие импортных сущностей Task 8E."""

from __future__ import annotations

from app.engineering import weld_operation_corrections as wc
from app.engineering import weld_operation_workflow as wow


# ── Типы корректировки (§7.2) ─────────────────────────────────────────────────


def test_correction_types_exact_set():
    assert set(wc.CORRECTION_TYPES) == {
        "DATA_CORRECTION",
        "WELDER_CORRECTION",
        "TECHNOLOGY_CORRECTION",
        "CANCEL_FALSE_RECORD",
        "SUPERSEDE_RECORD",
    }


def test_no_import_conflict_resolution_type():
    # IMPORT_CONFLICT_RESOLUTION относится только к Task 8E (§7.2, §25).
    assert "IMPORT_CONFLICT_RESOLUTION" not in wc.CORRECTION_TYPES


def test_source_types_only_manual():
    assert wc.SOURCE_TYPES == ("MANUAL",)


# ── Матрица типов: replacement и review (§10) ─────────────────────────────────


def test_creates_replacement_matrix():
    assert wc.creates_replacement("DATA_CORRECTION") is True
    assert wc.creates_replacement("WELDER_CORRECTION") is True
    assert wc.creates_replacement("TECHNOLOGY_CORRECTION") is True
    assert wc.creates_replacement("SUPERSEDE_RECORD") is True
    assert wc.creates_replacement("CANCEL_FALSE_RECORD") is False


def test_requires_ogs_review_matrix():
    assert wc.requires_ogs_review("DATA_CORRECTION") is False
    assert wc.requires_ogs_review("WELDER_CORRECTION") is True
    assert wc.requires_ogs_review("TECHNOLOGY_CORRECTION") is True
    assert wc.requires_ogs_review("CANCEL_FALSE_RECORD") is True
    assert wc.requires_ogs_review("SUPERSEDE_RECORD") is True


# ── Impact level (§7.3, §9) ───────────────────────────────────────────────────


def test_impact_critical_change_is_technological():
    assert wc.compute_impact_level("SUPERSEDE_RECORD", True) == "TECHNOLOGICAL"


def test_impact_data_correction_non_technical():
    assert wc.compute_impact_level("DATA_CORRECTION", False) == "NON_TECHNICAL"


def test_impact_welder_technology_always_technological():
    assert wc.compute_impact_level("WELDER_CORRECTION", False) == "TECHNOLOGICAL"
    assert wc.compute_impact_level("TECHNOLOGY_CORRECTION", False) == "TECHNOLOGICAL"


def test_impact_cancel_false_record_technological():
    assert wc.compute_impact_level("CANCEL_FALSE_RECORD", False) == "TECHNOLOGICAL"


# ── Критические поля и разрешённые patch-поля (§9, §10) ───────────────────────


def test_critical_fields_use_real_columns():
    assert "actual_welder_id" in wc.CRITICAL_FIELDS
    assert "entered_stamp_code" in wc.CRITICAL_FIELDS
    assert "actual_wps_id" in wc.CRITICAL_FIELDS
    assert "welding_method" in wc.CRITICAL_FIELDS
    assert "weld_stage" in wc.CRITICAL_FIELDS
    assert "welding_position" in wc.CRITICAL_FIELDS
    assert "performed_on" in wc.CRITICAL_FIELDS


def test_data_correction_excludes_critical_fields():
    allowed = wc.allowed_patch_fields("DATA_CORRECTION")
    assert allowed.isdisjoint(wc.CRITICAL_FIELDS)
    assert "operation_note" in allowed


def test_welder_correction_allowed_fields():
    assert wc.allowed_patch_fields("WELDER_CORRECTION") == {
        "actual_welder_id",
        "entered_stamp_code",
    }


def test_cancel_false_record_allows_no_fields():
    assert wc.allowed_patch_fields("CANCEL_FALSE_RECORD") == frozenset()


def test_supersede_allows_all_patchable_fields():
    assert wc.allowed_patch_fields("SUPERSEDE_RECORD") == wc.PATCHABLE_FIELDS


# ── Готовность к применению (§14) ─────────────────────────────────────────────


def test_ready_only_when_smr_approved_and_ogs_ready():
    assert wc.readiness_after_decisions("APPROVED", "NOT_REQUIRED") is True
    assert wc.readiness_after_decisions("APPROVED", "ACCEPTED") is True
    assert wc.readiness_after_decisions("APPROVED", "ACCEPTED_WITH_REMARK") is True
    assert wc.readiness_after_decisions("APPROVED", "PENDING") is False
    assert wc.readiness_after_decisions("PENDING", "ACCEPTED") is False
    assert wc.readiness_after_decisions("REJECTED", "ACCEPTED") is False


# ── Активные статусы и партиклы (§12) ─────────────────────────────────────────


def test_active_lifecycle_statuses():
    assert wc.ACTIVE_LIFECYCLE_STATUSES == frozenset(
        {"DRAFT", "SUBMITTED", "APPROVED"}
    )
    for terminal in ("APPLIED", "REJECTED", "CANCELLED"):
        assert terminal not in wc.ACTIVE_LIFECYCLE_STATUSES


# ── Снимок (§8.1) ─────────────────────────────────────────────────────────────


def test_snapshot_fields_cover_key_production_attributes():
    for field in (
        "id",
        "joint_id",
        "weld_stage",
        "welding_method",
        "actual_welder_id",
        "entered_stamp_code",
        "actual_wps_id",
        "performed_on",
        "lifecycle_status",
        "qualification_validation_status",
        "wps_validation_status",
        "welder_confirmation_status",
        "ogs_review_status",
        "record_version",
    ):
        assert field in wc.SNAPSHOT_FIELDS


# ── Ретраи (§15.4) ────────────────────────────────────────────────────────────


def test_max_application_attempts_is_three():
    assert wc.MAX_APPLICATION_ATTEMPTS == 3


# ── Переварка (§6.2, §16) ─────────────────────────────────────────────────────


def test_operation_kinds():
    assert wow.OPERATION_KINDS == ("STANDARD", "REWELD")


def test_superseded_is_terminal_status():
    assert "SUPERSEDED" in wow.WELD_OPERATION_STATUSES
    assert "SUPERSEDED" in wow.WELD_OPERATION_TERMINAL_STATUSES


def test_reweld_reasons_exact_set():
    assert set(wow.REWELD_REASONS) == {
        "WELD_REJECTED_BY_OGS",
        "INSPECTION_FAILURE",
        "NDT_FAILURE",
        "WRONG_WELDER",
        "WRONG_WPS",
        "WRONG_WELDING_METHOD",
        "MATERIAL_MISMATCH",
        "DIMENSIONAL_NONCONFORMITY",
        "OTHER",
    }


def test_reweld_decisions():
    assert wow.REWELD_DECISIONS == ("APPROVE", "REJECT")
