"""Unit-тесты pure-функций и словарей выполнения контроля (Task 9C, блок 9C-1).

Проверяют доменную политику `method_execution_workflow` и
`laboratory_conclusion_workflow` БЕЗ обращения к БД: закрытые наборы кодов,
переходы жизненного цикла, агрегированную оценку, проверку времени, допустимость
`wraps_zero`, расчёт полноты покрытия, вычисляемое состояние назначения и
действие аккредитации. Модели, миграция и сервисы Task 9C здесь не участвуют.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.quality import laboratory_conclusion_workflow as lcw
from app.quality import method_execution_workflow as mew

UTC = timezone.utc


# ── Целостность словарей ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "values",
    [
        mew.EXECUTION_STATUSES,
        mew.CONFIRMATION_MODES,
        mew.TIME_PRECISIONS,
        mew.CANCELLATION_TYPES,
        mew.PARTICIPANT_ROLES,
        mew.ENGAGEMENT_TYPES,
        mew.RESULT_STATES,
        mew.CONTROLLED_OBJECT_TYPES,
        mew.COORDINATE_SYSTEMS,
        mew.COORDINATE_UNITS,
        mew.EVALUATIONS,
        mew.REQUIRED_ACTIONS,
        mew.CALCULATED_COMPLETIONS,
        mew.DECLARED_COMPLETIONS,
        mew.ASSIGNMENT_STATES,
        lcw.CONCLUSION_STATUSES,
        lcw.ACCREDITATION_STATUSES,
    ],
)
def test_enum_tuples_have_no_duplicates(values: tuple[str, ...]) -> None:
    assert len(values) == len(set(values))


def test_not_performed_not_in_result_evaluations() -> None:
    # Невыполненный контроль отражается lifecycle/cancellation_type, а не оценкой.
    assert "NOT_PERFORMED" not in mew.EVALUATIONS
    assert mew.EVAL_NOT_EVALUATED in mew.EVALUATIONS
    assert mew.CANCEL_CONTROL_NOT_PERFORMED in mew.CANCELLATION_TYPES


def test_lab_confirmed_is_terminal_and_verified_absent() -> None:
    # VERIFIED зарезервирован за ОТК вне Task 9C: в статусах выполнения его нет.
    assert "VERIFIED" not in mew.EXECUTION_STATUSES
    assert mew.EXEC_LAB_CONFIRMED in mew.EXECUTION_TERMINAL_STATUSES
    assert mew.EXEC_SUPERSEDED in mew.EXECUTION_TERMINAL_STATUSES


# ── Переходы жизненного цикла выполнения ───────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (mew.EXEC_DRAFT, mew.EXEC_IN_PROGRESS),
        (mew.EXEC_DRAFT, mew.EXEC_PERFORMED),
        (mew.EXEC_IN_PROGRESS, mew.EXEC_PERFORMED),
        (mew.EXEC_PERFORMED, mew.EXEC_RESULT_RECORDED),
        (mew.EXEC_RESULT_RECORDED, mew.EXEC_LAB_CONFIRMED),
    ],
)
def test_valid_execution_transitions(current: str, target: str) -> None:
    assert mew.can_transition_execution(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (mew.EXEC_DRAFT, mew.EXEC_RESULT_RECORDED),
        (mew.EXEC_DRAFT, mew.EXEC_LAB_CONFIRMED),
        (mew.EXEC_PERFORMED, mew.EXEC_LAB_CONFIRMED),
        (mew.EXEC_LAB_CONFIRMED, mew.EXEC_RESULT_RECORDED),
        (mew.EXEC_RESULT_RECORDED, mew.EXEC_PERFORMED),
        # Отмена/замещение — не рядовой forward-переход.
        (mew.EXEC_DRAFT, mew.EXEC_CANCELLED),
        (mew.EXEC_RESULT_RECORDED, mew.EXEC_SUPERSEDED),
    ],
)
def test_invalid_execution_transitions(current: str, target: str) -> None:
    assert mew.can_transition_execution(current, target) is False


def test_terminal_execution_statuses_have_no_forward() -> None:
    for status in mew.EXECUTION_TERMINAL_STATUSES:
        assert all(
            not mew.can_transition_execution(status, target)
            for target in mew.EXECUTION_STATUSES
        )


# ── Агрегированная оценка (§11) ────────────────────────────────────────────────


def test_aggregate_evaluation_priority_nonconforming_wins() -> None:
    assert (
        mew.aggregate_evaluation(
            [mew.EVAL_CONFORMING, mew.EVAL_NONCONFORMING, mew.EVAL_INCONCLUSIVE]
        )
        == mew.EVAL_NONCONFORMING
    )


def test_aggregate_evaluation_inconclusive_over_not_evaluated() -> None:
    assert (
        mew.aggregate_evaluation([mew.EVAL_NOT_EVALUATED, mew.EVAL_INCONCLUSIVE])
        == mew.EVAL_INCONCLUSIVE
    )


def test_aggregate_evaluation_all_conforming() -> None:
    assert (
        mew.aggregate_evaluation([mew.EVAL_CONFORMING, mew.EVAL_CONFORMING])
        == mew.EVAL_CONFORMING
    )


def test_aggregate_evaluation_empty_is_not_evaluated() -> None:
    assert mew.aggregate_evaluation([]) == mew.EVAL_NOT_EVALUATED


# ── Проверка времени (§8) ──────────────────────────────────────────────────────


def test_time_date_only_requires_date() -> None:
    assert (
        mew.check_time_consistency(
            mew.TIME_DATE_ONLY,
            performed_date=None,
            started_at=None,
            finished_at=None,
        )
        == mew.EXECUTION_PERFORMED_DATE_REQUIRED
    )
    assert (
        mew.check_time_consistency(
            mew.TIME_DATE_ONLY,
            performed_date=date(2026, 7, 14),
            started_at=None,
            finished_at=None,
        )
        is None
    )


def test_time_start_known_requires_date_and_start() -> None:
    assert (
        mew.check_time_consistency(
            mew.TIME_START_KNOWN,
            performed_date=date(2026, 7, 14),
            started_at=None,
            finished_at=None,
        )
        == mew.EXECUTION_TIME_START_REQUIRED
    )
    assert (
        mew.check_time_consistency(
            mew.TIME_START_KNOWN,
            performed_date=date(2026, 7, 14),
            started_at=datetime(2026, 7, 14, 8, tzinfo=UTC),
            finished_at=None,
        )
        is None
    )


def test_time_full_interval_finish_not_before_start() -> None:
    start = datetime(2026, 7, 14, 10, tzinfo=UTC)
    assert (
        mew.check_time_consistency(
            mew.TIME_FULL_INTERVAL,
            performed_date=None,
            started_at=start,
            finished_at=start - timedelta(hours=1),
        )
        == mew.EXECUTION_TIME_FINISH_BEFORE_START
    )
    assert (
        mew.check_time_consistency(
            mew.TIME_FULL_INTERVAL,
            performed_date=None,
            started_at=start,
            finished_at=start + timedelta(hours=1),
        )
        is None
    )


def test_time_full_interval_requires_finish() -> None:
    assert (
        mew.check_time_consistency(
            mew.TIME_FULL_INTERVAL,
            performed_date=None,
            started_at=datetime(2026, 7, 14, 10, tzinfo=UTC),
            finished_at=None,
        )
        == mew.EXECUTION_TIME_FINISH_REQUIRED
    )


# ── wraps_zero (§10.5) ─────────────────────────────────────────────────────────


def test_wraps_zero_allowed_only_for_closed_systems() -> None:
    assert mew.is_wraps_zero_allowed(mew.COORD_MEASURING_BELT) is True
    assert mew.is_wraps_zero_allowed(mew.COORD_SECTOR) is True
    assert mew.is_wraps_zero_allowed(mew.COORD_LINEAR_WELD_LENGTH) is False
    assert mew.is_wraps_zero_allowed(mew.COORD_IMAGE_NUMBER) is False


# ── Состояние назначения (§24) ─────────────────────────────────────────────────


def _outcome(status: str, evaluation: str, complete: bool) -> mew.ExecutionOutcome:
    return mew.ExecutionOutcome(
        status=status, evaluation=evaluation, coverage_complete=complete
    )


def test_assignment_state_not_started() -> None:
    assert mew.assignment_state([]) == mew.ASSIGNMENT_STATE_NOT_STARTED


def test_assignment_state_in_progress_when_none_confirmed() -> None:
    outcomes = [_outcome(mew.EXEC_RESULT_RECORDED, mew.EVAL_CONFORMING, True)]
    assert mew.assignment_state(outcomes) == mew.ASSIGNMENT_STATE_IN_PROGRESS


def test_assignment_state_partial_when_coverage_incomplete() -> None:
    outcomes = [_outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_CONFORMING, False)]
    assert (
        mew.assignment_state(outcomes)
        == mew.ASSIGNMENT_STATE_PARTIALLY_COMPLETED
    )


def test_assignment_state_completed_conforming() -> None:
    outcomes = [
        _outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_CONFORMING, True),
        _outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_CONFORMING, True),
    ]
    assert (
        mew.assignment_state(outcomes)
        == mew.ASSIGNMENT_STATE_COMPLETED_CONFORMING
    )


def test_assignment_state_completed_with_nonconforming() -> None:
    outcomes = [_outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_NONCONFORMING, True)]
    assert (
        mew.assignment_state(outcomes)
        == mew.ASSIGNMENT_STATE_COMPLETED_WITH_NONCONFORMING
    )


def test_assignment_state_nonconforming_wins_over_conforming() -> None:
    # Решение ревью 9C-1: NONCONFORMING приоритетнее «смешанного».
    outcomes = [
        _outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_CONFORMING, True),
        _outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_NONCONFORMING, True),
    ]
    assert (
        mew.assignment_state(outcomes)
        == mew.ASSIGNMENT_STATE_COMPLETED_WITH_NONCONFORMING
    )


def test_assignment_state_completed_mixed() -> None:
    # MIXED — CONFORMING вместе с INCONCLUSIVE/NOT_EVALUATED без NONCONFORMING.
    outcomes = [
        _outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_CONFORMING, True),
        _outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_INCONCLUSIVE, True),
    ]
    assert (
        mew.assignment_state(outcomes) == mew.ASSIGNMENT_STATE_COMPLETED_MIXED
    )


def test_assignment_state_completed_inconclusive() -> None:
    outcomes = [_outcome(mew.EXEC_LAB_CONFIRMED, mew.EVAL_INCONCLUSIVE, True)]
    assert (
        mew.assignment_state(outcomes)
        == mew.ASSIGNMENT_STATE_COMPLETED_INCONCLUSIVE
    )


# ── Полнота покрытия (§12) ─────────────────────────────────────────────────────


def _seg(start, end, wraps=False) -> mew.CoverageSegment:
    return mew.CoverageSegment(start=start, end=end, wraps_zero=wraps)


def test_coverage_complete_single_segment() -> None:
    assert (
        mew.analyze_coverage([_seg(0, 1000)], 1000, closed=False)
        == mew.COMPLETION_COMPLETE
    )


def test_coverage_complete_two_adjacent_segments() -> None:
    segments = [_seg(0, 400), _seg(400, 1000)]
    assert (
        mew.analyze_coverage(segments, 1000, closed=False)
        == mew.COMPLETION_COMPLETE
    )


def test_coverage_partial_contiguous() -> None:
    assert (
        mew.analyze_coverage([_seg(0, 600)], 1000, closed=False)
        == mew.COMPLETION_PARTIAL
    )


def test_coverage_has_gaps() -> None:
    segments = [_seg(0, 300), _seg(600, 1000)]
    assert (
        mew.analyze_coverage(segments, 1000, closed=False)
        == mew.COMPLETION_HAS_GAPS
    )


def test_coverage_overlapping() -> None:
    segments = [_seg(0, 600), _seg(400, 1000)]
    assert (
        mew.analyze_coverage(segments, 1000, closed=False)
        == mew.COMPLETION_OVERLAPPING
    )


def test_coverage_closed_belt_wraps_zero_complete() -> None:
    # Замкнутый мерной пояс 4800: участок 4800→0 (весь пояс) даёт полное покрытие.
    segments = [_seg(0, 4800)]
    assert (
        mew.analyze_coverage(segments, 4800, closed=True)
        == mew.COMPLETION_COMPLETE
    )


def test_coverage_wraps_zero_segments_join_across_zero() -> None:
    # 4000→200 (через ноль) + 200→4000 покрывают весь замкнутый пояс.
    segments = [_seg(4000, 200, wraps=True), _seg(200, 4000)]
    assert (
        mew.analyze_coverage(segments, 4800, closed=True)
        == mew.COMPLETION_COMPLETE
    )


def test_coverage_wraps_zero_in_open_system_not_calculable() -> None:
    segments = [_seg(900, 100, wraps=True)]
    assert (
        mew.analyze_coverage(segments, 1000, closed=False)
        == mew.COMPLETION_NOT_CALCULABLE
    )


def test_coverage_not_calculable_without_total() -> None:
    assert (
        mew.analyze_coverage([_seg(0, 500)], None, closed=False)
        == mew.COMPLETION_NOT_CALCULABLE
    )


def test_coverage_out_of_bounds_not_calculable() -> None:
    assert (
        mew.analyze_coverage([_seg(0, 1200)], 1000, closed=False)
        == mew.COMPLETION_NOT_CALCULABLE
    )


# ── Заключение: переходы и аккредитация ────────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (lcw.CONCLUSION_DRAFT, lcw.CONCLUSION_PREPARED),
        (lcw.CONCLUSION_PREPARED, lcw.CONCLUSION_LAB_APPROVED),
        (lcw.CONCLUSION_LAB_APPROVED, lcw.CONCLUSION_ISSUED),
    ],
)
def test_valid_conclusion_transitions(current: str, target: str) -> None:
    assert lcw.can_transition_conclusion(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (lcw.CONCLUSION_DRAFT, lcw.CONCLUSION_LAB_APPROVED),
        (lcw.CONCLUSION_DRAFT, lcw.CONCLUSION_ISSUED),
        (lcw.CONCLUSION_ISSUED, lcw.CONCLUSION_PREPARED),
        (lcw.CONCLUSION_PREPARED, lcw.CONCLUSION_ISSUED),
    ],
)
def test_invalid_conclusion_transitions(current: str, target: str) -> None:
    assert lcw.can_transition_conclusion(current, target) is False


def test_accreditation_valid_active_within_range() -> None:
    assert (
        lcw.is_accreditation_valid_on(
            lcw.ACCREDITATION_ACTIVE,
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
            on_date=date(2026, 7, 14),
        )
        is True
    )


def test_accreditation_invalid_when_not_active() -> None:
    assert (
        lcw.is_accreditation_valid_on(
            lcw.ACCREDITATION_SUSPENDED,
            valid_from=date(2026, 1, 1),
            valid_until=None,
            on_date=date(2026, 7, 14),
        )
        is False
    )


def test_accreditation_invalid_when_expired_by_date() -> None:
    assert (
        lcw.is_accreditation_valid_on(
            lcw.ACCREDITATION_ACTIVE,
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 6, 30),
            on_date=date(2026, 7, 14),
        )
        is False
    )


def test_accreditation_open_ended_valid_until() -> None:
    assert (
        lcw.is_accreditation_valid_on(
            lcw.ACCREDITATION_ACTIVE,
            valid_from=date(2026, 1, 1),
            valid_until=None,
            on_date=date(2030, 1, 1),
        )
        is True
    )
