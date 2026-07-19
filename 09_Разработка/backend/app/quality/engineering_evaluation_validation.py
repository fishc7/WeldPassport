"""Проверка комплектности и validation matrix EngineeringEvaluation (Task 9D-2C).

**Pure, read-only** (решение 9D-2-C12): функции работают над уже загруженными объектами
ревизии/критериев/исключений/источников и **не** обращаются к БД, не пишут `verified_at`,
не меняют хэши и статусы, не коммитят. Результат — **агрегированный** список нарушений
(решение 9D-2-C11), без first-fail.

Свежесть источников (нужна БД) вычисляется в repository и передаётся сюда как
`source_issues`. Здесь только детерминированные правила матрицы (ADR-021 §8):

* обязательные поля ревизии;
* согласованность outcome ↔ criteria, classification ↔ outcome, severity/impact ↔ outcome;
* допустимость `recommended_disposition` по исходу;
* покрытие отклонённых критериев исключениями и валидность исключений;
* обязательность `confidence` (+ `confidence_note` при LOW), `residual_risk`,
  `application_conditions`, `review_due_at`;
* правила `NOT_APPLICABLE` и `INSUFFICIENT_DATA`.

Вызывается из `prepare-revision` (9D-2D); сам переход статуса выполняет 9D-2D, не 9D-2C.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.quality import engineering_evaluation_workflow as eew

_NO_DEFECT_OUTCOMES = frozenset({"ACCEPTABLE", "NOT_APPLICABLE"})
_DEFECT_SEVERITY = frozenset({"MINOR", "MAJOR", "CRITICAL"})


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str = ""


@dataclass(frozen=True)
class ValidationResult:
    violations: tuple[Violation, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def codes(self) -> list[str]:
        return [v.code for v in self.violations]


def _blank(value: object) -> bool:
    """None или пустая/пробельная строка."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def check_prepare_completeness(
    revision,
    *,
    criteria: Sequence,
    exceptions: Sequence,
    sources: Sequence,
    source_issues: Iterable[Violation] = (),
) -> ValidationResult:
    """Возвращает агрегированный `ValidationResult` для перехода DRAFT → PREPARED."""
    v: list[Violation] = []

    outcome = revision.evaluation_outcome
    classification = revision.classification
    disposition = revision.recommended_disposition
    severity = revision.confirmed_severity
    impact = revision.impact_scope

    # ── Обязательные поля ревизии (C13: disposition обязателен, NONE валиден) ──
    if _blank(outcome):
        v.append(Violation(eew.EVAL_OUTCOME_REQUIRED))
    if _blank(classification):
        v.append(Violation(eew.EVAL_CLASSIFICATION_REQUIRED))
    if _blank(disposition):
        v.append(Violation(eew.EVAL_DISPOSITION_REQUIRED))
    if _blank(severity):
        v.append(Violation(eew.EVAL_SEVERITY_REQUIRED))
    if _blank(impact):
        v.append(Violation(eew.EVAL_IMPACT_SCOPE_REQUIRED))
    if _blank(revision.rationale):
        v.append(Violation(eew.EVAL_RATIONALE_REQUIRED))
    if len(sources) < 1:
        v.append(Violation(eew.EVAL_SOURCE_REQUIRED))
    if len(criteria) < 1:
        v.append(Violation(eew.EVAL_CRITERION_REQUIRED))

    # ── applicability_comment у каждого NOT_APPLICABLE-критерия ────────────────
    for c in criteria:
        if c.comparison_result == "NOT_APPLICABLE" and _blank(c.applicability_comment):
            v.append(
                Violation(eew.EVAL_APPLICABILITY_COMMENT_REQUIRED, detail=str(c.id))
            )

    # ── Свежесть источников (передана из repository, read-only) ────────────────
    v.extend(source_issues)

    # Дальнейшие правила зависят от исхода; при неизвестном/пустом — пропускаем.
    if outcome in eew.EVALUATION_OUTCOMES:
        _check_outcome(v, revision, outcome, disposition, severity, impact,
                       criteria, exceptions)

    if not _blank(classification) and outcome in eew.EVALUATION_OUTCOMES:
        allowed = eew.CLASSIFICATION_OUTCOME_MATRIX.get(classification, ())
        if outcome not in allowed:
            v.append(Violation(eew.EVAL_CLASSIFICATION_OUTCOME_MISMATCH))

    return ValidationResult(tuple(v))


def _check_outcome(v, revision, outcome, disposition, severity, impact, criteria,
                   exceptions) -> None:
    results = [c.comparison_result for c in criteria]
    has_deviation = any(r in eew.DEVIATED_CRITERION_RESULTS for r in results)
    has_insufficient = any(r == eew.CRITERION_INSUFFICIENT_DATA for r in results)
    all_compliant = bool(results) and all(
        r in ("COMPLIES", "NOT_APPLICABLE") for r in results
    )
    all_na = bool(results) and all(r == "NOT_APPLICABLE" for r in results)
    deviated_ids = {c.id for c in criteria if c.comparison_result in eew.DEVIATED_CRITERION_RESULTS}
    exception_ids = {e.criterion_id for e in exceptions}

    # ── outcome ↔ criteria (правило 2/матрица) ────────────────────────────────
    mismatch = False
    if outcome == "ACCEPTABLE":
        mismatch = not all_compliant
    elif outcome == "NOT_APPLICABLE":
        mismatch = not all_na
    elif outcome == "NONCONFORMING":
        mismatch = not any(r == "DOES_NOT_COMPLY" for r in results)
    elif outcome == "CONDITIONALLY_ACCEPTABLE":
        mismatch = not has_deviation
    elif outcome == "INSUFFICIENT_DATA":  # C14: только через comparison_result
        mismatch = not has_insufficient
    if mismatch:
        v.append(Violation(eew.EVAL_OUTCOME_CRITERIA_MISMATCH))

    # ── допустимость disposition по исходу (правило 7) ─────────────────────────
    allowed_disp = eew.DISPOSITION_BY_OUTCOME.get(outcome, ())
    if not _blank(disposition) and disposition not in allowed_disp:
        v.append(Violation(eew.EVAL_DISPOSITION_NOT_ALLOWED))

    # ── валидность исключений (правило 4, C15) ─────────────────────────────────
    for e in exceptions:
        if e.criterion_id not in deviated_ids:
            v.append(
                Violation(eew.EVAL_EXCEPTION_CRITERION_INVALID, detail=str(e.id))
            )

    # ── покрытие отклонённых критериев исключениями (правила 3/5) ──────────────
    if outcome == "CONDITIONALLY_ACCEPTABLE":
        if deviated_ids - exception_ids:
            v.append(Violation(eew.EVAL_ACCEPT_WITHOUT_EXCEPTION))
    elif disposition == "ACCEPT_AS_IS" and (deviated_ids - exception_ids):
        v.append(Violation(eew.EVAL_ACCEPT_WITHOUT_EXCEPTION))

    # ── severity/impact ↔ outcome (правило 9) ─────────────────────────────────
    if not _blank(severity) and not _blank(impact):
        if outcome in _NO_DEFECT_OUTCOMES:
            if severity != "NOT_APPLICABLE" or impact != "NO_OPERATIONAL_IMPACT":
                v.append(Violation(eew.EVAL_CLASSIFICATION_OUTCOME_MISMATCH))
        elif outcome in ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"):
            if severity not in _DEFECT_SEVERITY:
                v.append(Violation(eew.EVAL_CLASSIFICATION_OUTCOME_MISMATCH))

    # ── confidence (§7.4) ─────────────────────────────────────────────────────
    confidence_required = (
        outcome in ("INSUFFICIENT_DATA", "CONDITIONALLY_ACCEPTABLE")
        or bool(exceptions)
        or has_insufficient
    )
    if confidence_required and _blank(revision.confidence_level):
        v.append(Violation(eew.EVAL_CONFIDENCE_REQUIRED))
    if revision.confidence_level == "LOW" and _blank(revision.confidence_note):
        v.append(Violation(eew.EVAL_CONFIDENCE_NOTE_REQUIRED))  # C16

    # ── residual_risk (§7.5) ──────────────────────────────────────────────────
    residual_required = (
        bool(exceptions)
        or outcome == "CONDITIONALLY_ACCEPTABLE"
        or revision.confidence_level in ("MEDIUM", "LOW")
    )
    if residual_required and _blank(revision.residual_risk):
        v.append(Violation(eew.EVAL_RESIDUAL_RISK_REQUIRED))

    # ── application_conditions (§7.5b) ────────────────────────────────────────
    if outcome == "CONDITIONALLY_ACCEPTABLE" and _blank(revision.application_conditions):
        v.append(Violation(eew.EVAL_CONDITIONS_REQUIRED))

    # ── review_due_at (§7.6) ──────────────────────────────────────────────────
    review_required = (
        outcome == "CONDITIONALLY_ACCEPTABLE"
        or bool(exceptions)
        or not _blank(revision.residual_risk)
        or disposition == "ADDITIONAL_INSPECTION"
    )
    if review_required and revision.review_due_at is None:
        v.append(Violation(eew.EVAL_REVIEW_DUE_REQUIRED))
