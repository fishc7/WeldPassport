"""Доменная политика жизненного цикла QualityDecision (Task 10A Block 2, ADR-027 ACCEPTED).

Чистые константы и pure-функции без обращения к БД (стиль Tasks 9A–9D-4A). Статусы и
результат совпадают с CHECK модели (`quality_decision_models`). Переход `DECIDED →
SUPERSEDED` — не пользовательская команда, а системное следствие `DECIDE` для нового
`QualityDecision` того же Joint (ADR-027 §G): `ACTION_SUPERSEDE` не входит в набор
пользовательских действий (`QD_ACTIONS`), а только участвует в подборе роли для audit
(`pick_actor_role`), по прецеденту `defect_disposition_workflow.ACTION_SUPERSEDE`.

Роли: WELDING_ENGINEER — бизнес-имя технического кода `OGS_ENGINEER` (тот же канон,
что `engineering_evaluation_workflow`/`inspection_workflow`); OTK_INSPECTOR — как есть.
CHIEF_WELDER в контуре QualityDecision не участвует и не используется как fallback
(явное требование Task 10A Block 2).
"""

from __future__ import annotations

from typing import Literal

from app.quality import inspection_workflow as iw
from app.quality import method_execution_workflow as mew
from app.quality.quality_decision_models import (
    QUALITY_DECISION_DECIDED,
    QUALITY_DECISION_DRAFT,
    QUALITY_DECISION_RESULT_ACCEPTED,
    QUALITY_DECISION_RESULT_DEFECT_CONFIRMED,
    QUALITY_DECISION_RESULT_NOT_CONFIRMED,
    QUALITY_DECISION_RESULTS,
    QUALITY_DECISION_STATUSES,
    QUALITY_DECISION_SUPERSEDED,
    QUALITY_DECISION_UNDER_REVIEW,
)

# Реэкспорт статусов/результата для сервиса/тестов.
QD_DRAFT = QUALITY_DECISION_DRAFT
QD_UNDER_REVIEW = QUALITY_DECISION_UNDER_REVIEW
QD_DECIDED = QUALITY_DECISION_DECIDED
QD_SUPERSEDED = QUALITY_DECISION_SUPERSEDED

QD_STATUSES = QUALITY_DECISION_STATUSES
QualityDecisionStatus = Literal["DRAFT", "UNDER_REVIEW", "DECIDED", "SUPERSEDED"]

QD_RESULT_ACCEPTED = QUALITY_DECISION_RESULT_ACCEPTED
QD_RESULT_NOT_CONFIRMED = QUALITY_DECISION_RESULT_NOT_CONFIRMED
QD_RESULT_DEFECT_CONFIRMED = QUALITY_DECISION_RESULT_DEFECT_CONFIRMED
QD_RESULTS = QUALITY_DECISION_RESULTS

# DECIDED/SUPERSEDED — терминальные для MVP: правка запрещена (SUPERSEDED достигается
# только системно из DECIDED через DECIDE нового решения, не отдельной командой).
QD_TERMINAL_STATUSES: frozenset[str] = frozenset({QD_DECIDED, QD_SUPERSEDED})

# Переходы жизненного цикла (Task 10A Block 2, §LIFECYCLE задания).
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    QD_DRAFT: frozenset({QD_UNDER_REVIEW}),
    QD_UNDER_REVIEW: frozenset({QD_DRAFT, QD_DECIDED}),
    QD_DECIDED: frozenset({QD_SUPERSEDED}),
    QD_SUPERSEDED: frozenset(),
}

# ── Действия сервиса ────────────────────────────────────────────────────────────
ACTION_CREATE = "CREATE"
ACTION_UPDATE_DRAFT = "UPDATE_DRAFT"
ACTION_SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
ACTION_RETURN = "RETURN"
ACTION_DECIDE = "DECIDE"
# Системное следствие DECIDE (ADR-027 §G) — не пользовательская команда/не входит в
# QD_ACTIONS; запись нужна только чтобы pick_actor_role() работал единообразно.
ACTION_SUPERSEDE = "SUPERSEDE"

# Действия-переходы состояния (потенциальный единый /transition в будущем API).
QD_ACTIONS: tuple[str, ...] = (
    ACTION_SUBMIT_FOR_REVIEW,
    ACTION_RETURN,
    ACTION_DECIDE,
)
QualityDecisionAction = Literal["SUBMIT_FOR_REVIEW", "RETURN", "DECIDE"]

_ACTION_TARGET: dict[str, str] = {
    ACTION_SUBMIT_FOR_REVIEW: QD_UNDER_REVIEW,
    ACTION_RETURN: QD_DRAFT,
    ACTION_DECIDE: QD_DECIDED,
}

# ── Роли (канонические role_code проекта, новых не вводим) ─────────────────────
# WELDING_ENGINEER (бизнес-имя ТЗ Task 10A) ↔ OGS_ENGINEER (технический role_code,
# как в engineering_evaluation_workflow/inspection_workflow).
ROLE_WELDING_ENGINEER = iw.ROLE_OGS_ENGINEER
ROLE_OTK_INSPECTOR = iw.ROLE_OTK_INSPECTOR

QD_CREATE_ROLES: frozenset[str] = frozenset({ROLE_WELDING_ENGINEER})
QD_UPDATE_DRAFT_ROLES: frozenset[str] = frozenset({ROLE_WELDING_ENGINEER})
QD_SUBMIT_ROLES: frozenset[str] = frozenset({ROLE_WELDING_ENGINEER})
QD_RETURN_ROLES: frozenset[str] = frozenset({ROLE_OTK_INSPECTOR})
QD_DECIDE_ROLES: frozenset[str] = frozenset({ROLE_OTK_INSPECTOR})
# Видимость (404 вместо 403 на скрытый ресурс) — тот же широкий контур контроля,
# что EngineeringEvaluation/DefectDisposition (`iw.INSPECTION_READ_ROLES`).
QD_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES

_ACTION_ROLES: dict[str, frozenset[str]] = {
    ACTION_CREATE: QD_CREATE_ROLES,
    ACTION_UPDATE_DRAFT: QD_UPDATE_DRAFT_ROLES,
    ACTION_SUBMIT_FOR_REVIEW: QD_SUBMIT_ROLES,
    ACTION_RETURN: QD_RETURN_ROLES,
    ACTION_DECIDE: QD_DECIDE_ROLES,
    # SUPERSEDE — системное действие внутри DECIDE; роль для audit та же, что DECIDE.
    ACTION_SUPERSEDE: QD_DECIDE_ROLES,
}

# ── Типы событий аудита (реэкспорт из method_execution_workflow, Task 10A Block 1) ─
AUDIT_ENTITY = mew.AUDIT_ENTITY_QUALITY_DECISION
EVENT_CREATED = mew.AUDIT_EVENT_QUALITY_DECISION_CREATED
EVENT_SUBMITTED = mew.AUDIT_EVENT_QUALITY_DECISION_SUBMITTED
EVENT_RETURNED = mew.AUDIT_EVENT_QUALITY_DECISION_RETURNED
EVENT_DECIDED = mew.AUDIT_EVENT_QUALITY_DECISION_DECIDED
EVENT_SUPERSEDED = mew.AUDIT_EVENT_QUALITY_DECISION_SUPERSEDED

_ACTION_EVENT: dict[str, str] = {
    ACTION_SUBMIT_FOR_REVIEW: EVENT_SUBMITTED,
    ACTION_RETURN: EVENT_RETURNED,
    ACTION_DECIDE: EVENT_DECIDED,
}


def is_valid_status(status: str) -> bool:
    return status in QD_STATUSES


def is_terminal(status: str) -> bool:
    return status in QD_TERMINAL_STATUSES


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in _ALLOWED_TRANSITIONS.get(from_status, frozenset())


def target_status_for_action(action: str) -> str | None:
    return _ACTION_TARGET.get(action)


def event_type_for_action(action: str) -> str | None:
    return _ACTION_EVENT.get(action)


def is_valid_action(action: str) -> bool:
    return action in QD_ACTIONS


def roles_for_action(action: str) -> frozenset[str]:
    return _ACTION_ROLES.get(action, frozenset())


def can_perform_action(action: str, granted_roles: set[str]) -> bool:
    return bool(granted_roles & roles_for_action(action))


def can_create(granted_roles: set[str]) -> bool:
    return bool(granted_roles & QD_CREATE_ROLES)


def can_update_draft(granted_roles: set[str]) -> bool:
    return bool(granted_roles & QD_UPDATE_DRAFT_ROLES)


def is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def pick_actor_role(action: str, granted_roles: set[str]) -> str | None:
    """Выбирает role_code для audit: приоритет WELDING_ENGINEER, затем OTK_INSPECTOR.

    Fallback на CHIEF_WELDER намеренно не предусмотрен (Task 10A Block 2: роль в
    контуре QualityDecision не участвует)."""
    allowed = roles_for_action(action)
    for role in (ROLE_WELDING_ENGINEER, ROLE_OTK_INSPECTOR):
        if role in granted_roles and role in allowed:
            return role
    matched = granted_roles & allowed
    return next(iter(sorted(matched)), None)


# ── Машинные коды ошибок ─────────────────────────────────────────────────────────
QD_NOT_FOUND = "QD_NOT_FOUND"
QD_JOINT_NOT_FOUND = "QD_JOINT_NOT_FOUND"
QD_PROJECT_NOT_FOUND = "QD_PROJECT_NOT_FOUND"
QD_INVALID_ACTION = "QD_INVALID_ACTION"
QD_INVALID_TRANSITION = "QD_INVALID_TRANSITION"
QD_TERMINAL_IMMUTABLE = "QD_TERMINAL_IMMUTABLE"
QD_ONLY_DRAFT_EDITABLE = "QD_ONLY_DRAFT_EDITABLE"
QD_PERMISSION_DENIED = "QD_PERMISSION_DENIED"
QD_BASIS_REQUIRED = "QD_BASIS_REQUIRED"
QD_SUMMARY_REQUIRED = "QD_SUMMARY_REQUIRED"
QD_RETURN_REASON_REQUIRED = "QD_RETURN_REASON_REQUIRED"
QD_RESULT_REQUIRED = "QD_RESULT_REQUIRED"
QD_RESULT_INVALID = "QD_RESULT_INVALID"
QD_REVISION_NOT_FOUND = "QD_REVISION_NOT_FOUND"
QD_REVISION_WRONG_JOINT = "QD_REVISION_WRONG_JOINT"
QD_REVISION_NOT_EFFECTIVE = "QD_REVISION_NOT_EFFECTIVE"
QD_REVISION_ALREADY_DECIDED = "QD_REVISION_ALREADY_DECIDED"
QD_VERSION_CONFLICT = "QD_VERSION_CONFLICT"

QD_ERROR_MESSAGES: dict[str, str] = {
    QD_NOT_FOUND: "QualityDecision не найден",
    QD_JOINT_NOT_FOUND: "Joint не найден",
    QD_PROJECT_NOT_FOUND: "Проект Joint не найден",
    QD_INVALID_ACTION: "Неизвестное действие",
    QD_INVALID_TRANSITION: "Недопустимый переход статуса",
    QD_TERMINAL_IMMUTABLE: "DECIDED/SUPERSEDED QualityDecision нельзя изменить",
    QD_ONLY_DRAFT_EDITABLE: "Редактирование допустимо только в статусе DRAFT",
    QD_PERMISSION_DENIED: "Недостаточно прав для операции",
    QD_BASIS_REQUIRED: "Требуется минимум одно основание (QualityDecisionBasis)",
    QD_SUMMARY_REQUIRED: "Для отправки на рассмотрение обязательно summary",
    QD_RETURN_REASON_REQUIRED: (
        "Для возврата на доработку обязательна причина (return_reason)"
    ),
    QD_RESULT_REQUIRED: "Для принятия решения обязателен decision_result",
    QD_RESULT_INVALID: "Недопустимый decision_result",
    QD_REVISION_NOT_FOUND: "EngineeringEvaluationRevision не найдена",
    QD_REVISION_WRONG_JOINT: "Ревизия относится к другому Joint",
    QD_REVISION_NOT_EFFECTIVE: "Ревизия должна быть в статусе EFFECTIVE",
    QD_REVISION_ALREADY_DECIDED: (
        "Ревизия уже является основанием другого действующего решения"
    ),
    QD_VERSION_CONFLICT: (
        "Конфликт версии: перечитайте QualityDecision и повторите вручную"
    ),
}


# ── Валидация команд (pure; DB-проверки — на службе сервиса) ────────────────────


def validate_create_request(
    *, granted_roles: set[str], has_basis: bool
) -> str | None:
    if not can_create(granted_roles):
        return QD_PERMISSION_DENIED
    if not has_basis:
        return QD_BASIS_REQUIRED
    return None


def validate_update_draft_request(
    *, current_status: str, granted_roles: set[str]
) -> str | None:
    if not can_update_draft(granted_roles):
        return QD_PERMISSION_DENIED
    if current_status != QD_DRAFT:
        return QD_ONLY_DRAFT_EDITABLE
    return None


def validate_submit_request(
    *,
    current_status: str,
    granted_roles: set[str],
    has_summary: bool,
    has_basis: bool,
) -> str | None:
    if not can_perform_action(ACTION_SUBMIT_FOR_REVIEW, granted_roles):
        return QD_PERMISSION_DENIED
    if is_terminal(current_status):
        return QD_TERMINAL_IMMUTABLE
    if not can_transition(current_status, QD_UNDER_REVIEW):
        return QD_INVALID_TRANSITION
    if not has_summary:
        return QD_SUMMARY_REQUIRED
    if not has_basis:
        return QD_BASIS_REQUIRED
    return None


def validate_return_request(
    *, current_status: str, granted_roles: set[str], reason: str | None
) -> str | None:
    if not can_perform_action(ACTION_RETURN, granted_roles):
        return QD_PERMISSION_DENIED
    if is_terminal(current_status):
        return QD_TERMINAL_IMMUTABLE
    if not can_transition(current_status, QD_DRAFT):
        return QD_INVALID_TRANSITION
    if is_blank(reason):
        return QD_RETURN_REASON_REQUIRED
    return None


def validate_decide_request(
    *,
    current_status: str,
    granted_roles: set[str],
    result: str | None,
    has_basis: bool,
) -> str | None:
    if not can_perform_action(ACTION_DECIDE, granted_roles):
        return QD_PERMISSION_DENIED
    if is_terminal(current_status):
        return QD_TERMINAL_IMMUTABLE
    if not can_transition(current_status, QD_DECIDED):
        return QD_INVALID_TRANSITION
    if is_blank(result):
        return QD_RESULT_REQUIRED
    if result not in QD_RESULTS:
        return QD_RESULT_INVALID
    if not has_basis:
        return QD_BASIS_REQUIRED
    return None
