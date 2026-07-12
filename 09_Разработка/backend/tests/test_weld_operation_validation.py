"""Unit-тесты чистого валидатора WeldOperation (Task 8B, §17 задания).

Проверяют доменный компонент `weld_operation_validation` без БД и HTTP: допуск
сварщика (§7-8) и WPS/проектный метод (§9). Кандидаты допуска конструируются
напрямую, включая positions и project scope — измерения, которых нет в текущей
модели `welder_admissions`, но которые сохранены в чистом валидаторе (архитектурное
решение Task 8B: адаптировать DB-путь, логику проверить синтетически)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.engineering import weld_operation_validation as wov

PERFORMED_ON = date(2026, 7, 12)
PROJECT = uuid4()
OTHER_PROJECT = uuid4()


def adm(**overrides) -> wov.AdmissionCandidate:
    """Кандидат допуска, по умолчанию полностью покрывающий эталонную операцию
    (метод RAD, DN 100, толщина 8, положение не ограничено)."""
    params = dict(
        id=uuid4(),
        status="active",
        validity_from=date(2026, 1, 1),
        validity_to=date(2026, 12, 31),
        methods=("RAD",),
        positions=(),
        material_groups=("M01",),
        dn_min=Decimal("15"),
        dn_max=Decimal("150"),
        thickness_min=Decimal("2"),
        thickness_max=Decimal("12"),
        project_id=None,
        worker_id=123,
        welder_id=uuid4(),
    )
    params.update(overrides)
    return wov.AdmissionCandidate(**params)


def qual(**overrides) -> wov.QualificationResult:
    params = dict(
        welder_specified=True,
        welder_profile=wov.WelderProfileView(active=True),
        performed_on=PERFORMED_ON,
        welding_method="RAD",
        welding_position=None,
        joint_project_id=PROJECT,
        dn_sides=(Decimal("100"),),
        thickness_sides=(Decimal("8"),),
        material_present=False,
        candidates=(),
    )
    params.update(overrides)
    return wov.validate_qualification(**params)


# ══ Qualification (§17) ═══════════════════════════════════════════════════════


def test_q1_project_admission_covers_pass() -> None:
    candidate = adm(project_id=PROJECT)
    result = qual(candidates=[candidate])
    assert result.status == "PASS"
    assert result.codes == []
    assert result.admission_id == candidate.id
    assert result.snapshot is not None
    assert result.snapshot["admission_id"] == str(candidate.id)


def test_q2_global_admission_covers_pass() -> None:
    candidate = adm(project_id=None)
    result = qual(candidates=[candidate])
    assert result.status == "PASS"
    assert result.admission_id == candidate.id


def test_q3_project_admission_priority_over_global() -> None:
    global_adm = adm(project_id=None)
    project_adm = adm(project_id=PROJECT)
    result = qual(candidates=[global_adm, project_adm])
    assert result.status == "PASS"
    assert result.admission_id == project_adm.id


def test_q4_foreign_project_scope_not_eligible() -> None:
    result = qual(candidates=[adm(project_id=OTHER_PROJECT)])
    assert result.status == "FAIL"
    assert result.codes == [wov.NO_ACTIVE_ADMISSION]


def test_q5_validity_from_equals_performed_on_fits() -> None:
    result = qual(candidates=[adm(validity_from=PERFORMED_ON, validity_to=None)])
    assert result.status == "PASS"


def test_q6_validity_to_equals_performed_on_fits() -> None:
    result = qual(
        candidates=[adm(validity_from=date(2026, 1, 1), validity_to=PERFORMED_ON)]
    )
    assert result.status == "PASS"


def test_q7_future_admission_not_fit() -> None:
    future = adm(validity_from=PERFORMED_ON + timedelta(days=1), validity_to=None)
    result = qual(candidates=[future])
    assert result.status == "FAIL"
    assert result.codes == [wov.ADMISSION_NOT_YET_VALID]


def test_q8_expired_admission_not_fit() -> None:
    expired = adm(
        validity_from=date(2026, 1, 1), validity_to=PERFORMED_ON - timedelta(days=1)
    )
    result = qual(candidates=[expired])
    assert result.status == "FAIL"
    assert result.codes == [wov.ADMISSION_EXPIRED]


def test_q9_suspended_or_revoked_not_fit() -> None:
    for bad_status in ("suspended", "revoked"):
        result = qual(candidates=[adm(status=bad_status)])
        assert result.status == "FAIL"
        assert result.codes == [wov.NO_ACTIVE_ADMISSION]


def test_q10_method_not_covered() -> None:
    result = qual(candidates=[adm(methods=("RD",))])
    assert result.status == "FAIL"
    assert result.codes == [wov.METHOD_NOT_COVERED]


def test_q11_dn_below_range() -> None:
    result = qual(
        dn_sides=(Decimal("40"),),
        candidates=[adm(dn_min=Decimal("50"), dn_max=Decimal("150"))],
    )
    assert result.status == "FAIL"
    assert result.codes == [wov.DN_NOT_COVERED]


def test_q12_dn_above_range() -> None:
    result = qual(dn_sides=(Decimal("200"),), candidates=[adm()])
    assert result.status == "FAIL"
    assert result.codes == [wov.DN_NOT_COVERED]


def test_q13_both_joint_sides_checked() -> None:
    # Первая сторона в диапазоне, вторая — вне: обе стороны проверяются.
    result = qual(dn_sides=(Decimal("100"), Decimal("200")), candidates=[adm()])
    assert result.status == "FAIL"
    assert wov.DN_NOT_COVERED in result.codes


def test_q14_thickness_out_of_range() -> None:
    result = qual(thickness_sides=(Decimal("20"),), candidates=[adm()])
    assert result.status == "FAIL"
    assert result.codes == [wov.THICKNESS_NOT_COVERED]


def test_q15_position_not_covered() -> None:
    result = qual(
        welding_position="PF", candidates=[adm(positions=("PA", "PC"))]
    )
    assert result.status == "FAIL"
    assert result.codes == [wov.POSITION_NOT_COVERED]


def test_q16_welder_profile_inactive() -> None:
    result = qual(
        welder_profile=wov.WelderProfileView(active=False), candidates=[adm()]
    )
    assert result.status == "FAIL"
    assert result.codes == [wov.WELDER_PROFILE_INACTIVE]


def test_q17_no_active_admission() -> None:
    result = qual(candidates=[])
    assert result.status == "FAIL"
    assert result.codes == [wov.NO_ACTIVE_ADMISSION]


def test_q18_material_not_checkable_indeterminate() -> None:
    result = qual(material_present=True, candidates=[adm()])
    assert result.status == "INDETERMINATE"
    assert result.codes == [wov.MATERIAL_GROUP_NOT_CHECKABLE]
    assert result.admission_id is None


def test_q19_two_partial_admissions_not_merged() -> None:
    # A покрывает метод, но не DN=100; B покрывает DN, но не метод RAD.
    a = adm(methods=("RAD",), dn_min=Decimal("15"), dn_max=Decimal("50"))
    b = adm(methods=("RD",), dn_min=Decimal("15"), dn_max=Decimal("150"))
    result = qual(candidates=[a, b])
    # Ни один допуск не покрывает операцию целиком → FAIL (диапазоны не сливаются).
    assert result.status == "FAIL"


def test_q20_multiple_full_matches_deterministic() -> None:
    earlier = adm(project_id=None, validity_from=date(2026, 1, 1))
    later = adm(project_id=None, validity_from=date(2026, 3, 1))
    first = qual(candidates=[earlier, later])
    second = qual(candidates=[later, earlier])
    assert first.status == "PASS" and second.status == "PASS"
    # Более поздняя validity_from имеет приоритет; выбор не зависит от порядка.
    assert first.admission_id == later.id
    assert second.admission_id == later.id


def test_q_welder_not_specified_indeterminate() -> None:
    result = qual(welder_specified=False, candidates=[adm()])
    assert result.status == "INDETERMINATE"
    assert result.codes == [wov.WELDER_NOT_SPECIFIED]


def test_q_fail_priority_over_indeterminate() -> None:
    # Подтверждённое нарушение (метод) + пробел данных (материал) → FAIL со всеми
    # причинами (§8.2).
    result = qual(material_present=True, candidates=[adm(methods=("RD",))])
    assert result.status == "FAIL"
    assert wov.METHOD_NOT_COVERED in result.codes
    assert wov.MATERIAL_GROUP_NOT_CHECKABLE in result.codes


def test_q_joint_data_incomplete_indeterminate() -> None:
    result = qual(
        dn_sides=(None, None),
        thickness_sides=(None, None),
        candidates=[adm()],
    )
    assert result.status == "INDETERMINATE"
    assert result.codes == [wov.JOINT_DATA_INCOMPLETE]


# ══ WPS (§17) ═════════════════════════════════════════════════════════════════

WPS_A = uuid4()
WPS_B = uuid4()


def wps(**overrides) -> wov.WpsResult:
    params = dict(
        weld_stage="ROOT",
        welding_method="RAD",
        planned_wps_id=WPS_A,
        actual_wps_id=WPS_A,
        required_root_method="RAD",
        required_fill_method="RD",
        required_cap_method="RD",
    )
    params.update(overrides)
    return wov.validate_wps(**params)


def test_w1_matching_wps_and_method_pass() -> None:
    result = wps()
    assert result.status == "PASS"
    assert result.codes == []
    assert result.snapshot["planned_wps_id"] == str(WPS_A)
    assert result.snapshot["required_method"] == "RAD"


def test_w2_wps_uuid_mismatch() -> None:
    result = wps(actual_wps_id=WPS_B)
    assert result.status == "FAIL"
    assert result.codes == [wov.WPS_MISMATCH]


def test_w3_actual_wps_missing() -> None:
    result = wps(actual_wps_id=None)
    assert result.status == "FAIL"
    assert result.codes == [wov.ACTUAL_WPS_MISSING]


def test_w4_planned_missing_actual_present_indeterminate() -> None:
    result = wps(planned_wps_id=None, actual_wps_id=WPS_A)
    assert result.status == "INDETERMINATE"
    assert result.codes == [wov.PLANNED_WPS_MISSING]


def test_w5_both_wps_missing_indeterminate() -> None:
    result = wps(planned_wps_id=None, actual_wps_id=None)
    assert result.status == "INDETERMINATE"
    assert result.codes == [wov.PLANNED_WPS_MISSING, wov.ACTUAL_WPS_MISSING]


def test_w6_root_compared_with_required_root() -> None:
    result = wps(
        weld_stage="ROOT", welding_method="RD", required_root_method="RAD"
    )
    assert result.status == "FAIL"
    assert result.codes == [wov.ACTUAL_METHOD_MISMATCH]


def test_w7_fill_compared_with_required_fill() -> None:
    result = wps(
        weld_stage="FILL",
        welding_method="RD",
        required_root_method="XX",
        required_fill_method="RD",
    )
    assert result.status == "PASS"


def test_w8_cap_compared_with_required_cap() -> None:
    result = wps(
        weld_stage="CAP",
        welding_method="RD",
        required_root_method="XX",
        required_cap_method="RD",
    )
    assert result.status == "PASS"


def test_w9_actual_method_mismatch() -> None:
    result = wps(weld_stage="ROOT", welding_method="MMA", required_root_method="RAD")
    assert result.status == "FAIL"
    assert result.codes == [wov.ACTUAL_METHOD_MISMATCH]


def test_w10_required_method_missing_indeterminate() -> None:
    result = wps(required_root_method=None)
    assert result.status == "INDETERMINATE"
    assert result.codes == [wov.REQUIRED_METHOD_MISSING]


def test_w11_normalization_case_and_spaces() -> None:
    result = wps(welding_method="  rad ", required_root_method="RAD")
    assert result.status == "PASS"


def test_w12_codes_deterministic_order() -> None:
    # FAIL (метод) + два INDETERMINATE (оба WPS) → FAIL, коды в каноническом порядке.
    result = wps(
        weld_stage="ROOT",
        welding_method="RD",
        required_root_method="RAD",
        planned_wps_id=None,
        actual_wps_id=None,
    )
    assert result.status == "FAIL"
    assert result.codes == [
        wov.PLANNED_WPS_MISSING,
        wov.ACTUAL_WPS_MISSING,
        wov.ACTUAL_METHOD_MISMATCH,
    ]


def test_w_unknown_stage_indeterminate() -> None:
    for stage in ("BACK_WELD", "TACK"):
        result = wps(weld_stage=stage)
        assert result.status == "INDETERMINATE"
        assert result.codes == [wov.UNKNOWN_WELD_STAGE]
        assert result.snapshot["required_method"] is None
