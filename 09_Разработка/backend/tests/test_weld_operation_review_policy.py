"""Unit-тесты чистой доменной политики Task 8C (§17 задания).

Проверяют `weld_operation_review` без БД и HTTP: первичную маршрутизацию review
(§5.2), переходы подтверждения и review (§4.3, §5), нормализацию reason codes и
правила обоснования (§9). Интеграция ролей/scope/concurrency — в отдельных
интеграционных файлах."""

from __future__ import annotations

from app.engineering import weld_operation_review as wor


# ══ Первичная маршрутизация review (§5.2) ═════════════════════════════════════


def test_routing_pass_pass_not_disputed_is_not_required() -> None:
    assert (
        wor.initial_ogs_review_status("PASS", "PASS", "PENDING")
        == wor.OGS_REVIEW_NOT_REQUIRED
    )


def test_routing_qualification_fail_is_pending() -> None:
    assert (
        wor.initial_ogs_review_status("FAIL", "PASS", "PENDING")
        == wor.OGS_REVIEW_PENDING
    )


def test_routing_qualification_indeterminate_is_pending() -> None:
    assert (
        wor.initial_ogs_review_status("INDETERMINATE", "PASS", "PENDING")
        == wor.OGS_REVIEW_PENDING
    )


def test_routing_wps_fail_is_pending() -> None:
    assert (
        wor.initial_ogs_review_status("PASS", "FAIL", "PENDING")
        == wor.OGS_REVIEW_PENDING
    )


def test_routing_wps_indeterminate_is_pending() -> None:
    assert (
        wor.initial_ogs_review_status("PASS", "INDETERMINATE", "PENDING")
        == wor.OGS_REVIEW_PENDING
    )


def test_routing_not_checked_is_pending() -> None:
    assert (
        wor.initial_ogs_review_status("NOT_CHECKED", "NOT_CHECKED", "PENDING")
        == wor.OGS_REVIEW_PENDING
    )


def test_routing_disputed_forces_pending_even_on_pass() -> None:
    assert (
        wor.initial_ogs_review_status("PASS", "PASS", "DISPUTED")
        == wor.OGS_REVIEW_PENDING
    )


# ══ Переходы подтверждения сварщика (§4.3) ════════════════════════════════════


def test_confirmation_repeat_confirmed_is_noop() -> None:
    assert (
        wor.confirmation_noop_code("CONFIRMED", "CONFIRMED")
        == wor.WELDER_ALREADY_CONFIRMED
    )


def test_confirmation_repeat_disputed_is_noop() -> None:
    assert (
        wor.confirmation_noop_code("DISPUTED", "DISPUTED")
        == wor.WELDER_ALREADY_DISPUTED
    )


def test_confirmation_real_transitions_allowed() -> None:
    assert wor.confirmation_noop_code("PENDING", "CONFIRMED") is None
    assert wor.confirmation_noop_code("PENDING", "DISPUTED") is None
    assert wor.confirmation_noop_code("CONFIRMED", "DISPUTED") is None
    assert wor.confirmation_noop_code("DISPUTED", "CONFIRMED") is None


# ══ Переходы решения ОГС (§5, §33) ════════════════════════════════════════════


def test_review_repeat_decision_is_noop() -> None:
    assert (
        wor.review_noop_code("APPROVED", "APPROVED")
        == wor.OGS_REVIEW_ALREADY_APPROVED
    )
    assert (
        wor.review_noop_code("REJECTED", "REJECTED")
        == wor.OGS_REVIEW_ALREADY_REJECTED
    )


def test_review_new_decision_allowed() -> None:
    assert wor.review_noop_code("PENDING", "APPROVED") is None
    assert wor.review_noop_code("NOT_REQUIRED", "APPROVED") is None
    assert wor.review_noop_code("APPROVED", "REJECTED") is None
    assert wor.review_noop_code("REJECTED", "APPROVED") is None


# ══ Reason codes: нормализация и правила (§9) ═════════════════════════════════


def test_normalize_dedup_and_stable_order() -> None:
    codes = [wor.OTHER, wor.WPS_NONCOMPLIANCE, wor.OTHER, wor.QUALIFICATION_NONCOMPLIANCE]
    normalized = wor.normalize_reason_codes(codes)
    # Уникальные, в каноническом порядке REASON_CODE_ORDER.
    assert normalized == [
        wor.QUALIFICATION_NONCOMPLIANCE,
        wor.WPS_NONCOMPLIANCE,
        wor.OTHER,
    ]


def test_normalize_order_independent_of_input() -> None:
    a = wor.normalize_reason_codes([wor.WPS_EXCEPTION_ACCEPTED, wor.QUALIFICATION_EXCEPTION_ACCEPTED])
    b = wor.normalize_reason_codes([wor.QUALIFICATION_EXCEPTION_ACCEPTED, wor.WPS_EXCEPTION_ACCEPTED])
    assert a == b == [
        wor.QUALIFICATION_EXCEPTION_ACCEPTED,
        wor.WPS_EXCEPTION_ACCEPTED,
    ]


def test_requires_exception_reason_by_validation() -> None:
    assert wor.requires_exception_reason("FAIL", "PASS") is True
    assert wor.requires_exception_reason("PASS", "INDETERMINATE") is True
    assert wor.requires_exception_reason("NOT_CHECKED", "PASS") is True
    assert wor.requires_exception_reason("PASS", "PASS") is False


def test_has_exception_reason() -> None:
    assert wor.has_exception_reason([wor.QUALIFICATION_EXCEPTION_ACCEPTED]) is True
    assert wor.has_exception_reason([wor.WELDER_IDENTITY_REQUIRES_CORRECTION]) is True
    # Коды несоответствия и OTHER исключением не являются.
    assert wor.has_exception_reason([wor.QUALIFICATION_NONCOMPLIANCE]) is False
    assert wor.has_exception_reason([wor.OTHER]) is False


def test_requires_comment_only_for_other() -> None:
    assert wor.requires_comment([wor.OTHER]) is True
    assert wor.requires_comment([wor.QUALIFICATION_EXCEPTION_ACCEPTED]) is False


def test_reason_codes_unique_and_frozen() -> None:
    # Значения уникальны и порядок стабилен (§9).
    assert len(wor.REASON_CODE_ORDER) == len(set(wor.REASON_CODE_ORDER))
    assert wor.EXCEPTION_REASON_CODES <= wor.REASON_CODES
