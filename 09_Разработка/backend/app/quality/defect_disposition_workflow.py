"""Доменная политика жизненного цикла DefectDisposition (Task 9D-4A-3, ADR-023).

Чистые константы и pure-функции без обращения к БД. Статусы совпадают с CHECK
модели (`defect_disposition_models`); полный канонический набор включает
`SUPERSEDED`, но переходы в него в 9D-4A-3 **не** реализуются (отдельный сценарий
замены). Стиль Tasks 9A–9D-3: UPPERCASE-коды, frozenset переходов.
"""

from __future__ import annotations

from typing import Literal

from app.quality import inspection_workflow as iw
from app.quality.defect_disposition_models import (
    DEFECT_DISPOSITION_ACTIVE,
    DEFECT_DISPOSITION_APPROVED,
    DEFECT_DISPOSITION_CANCELLED,
    DEFECT_DISPOSITION_DRAFT,
    DEFECT_DISPOSITION_PREPARED,
    DEFECT_DISPOSITION_STATUSES,
    DEFECT_DISPOSITION_SUPERSEDED,
)

# Реэкспорт статусов для сервиса/схем/тестов.
DISPOSITION_DRAFT = DEFECT_DISPOSITION_DRAFT
DISPOSITION_PREPARED = DEFECT_DISPOSITION_PREPARED
DISPOSITION_APPROVED = DEFECT_DISPOSITION_APPROVED
DISPOSITION_ACTIVE = DEFECT_DISPOSITION_ACTIVE
DISPOSITION_SUPERSEDED = DEFECT_DISPOSITION_SUPERSEDED
DISPOSITION_CANCELLED = DEFECT_DISPOSITION_CANCELLED

DISPOSITION_STATUSES = DEFECT_DISPOSITION_STATUSES
DispositionStatus = Literal[
    "DRAFT", "PREPARED", "APPROVED", "ACTIVE", "SUPERSEDED", "CANCELLED"
]

# Конечные для MVP workflow: правка и переходы запрещены.
# SUPERSEDED — тоже конечный (переходы не вводятся в 9D-4A-3).
DISPOSITION_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {DISPOSITION_ACTIVE, DISPOSITION_CANCELLED, DISPOSITION_SUPERSEDED}
)

# Открытые (незавершённые) статусы: не более одной такой записи на defect_root.
DISPOSITION_OPEN_STATUSES: frozenset[str] = frozenset(
    {
        DISPOSITION_DRAFT,
        DISPOSITION_PREPARED,
        DISPOSITION_APPROVED,
        DISPOSITION_ACTIVE,
    }
)

# MVP-переходы (SUPERSEDED не входит — отдельный сценарий замены).
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    DISPOSITION_DRAFT: frozenset({DISPOSITION_PREPARED, DISPOSITION_CANCELLED}),
    DISPOSITION_PREPARED: frozenset({DISPOSITION_APPROVED, DISPOSITION_CANCELLED}),
    DISPOSITION_APPROVED: frozenset({DISPOSITION_ACTIVE}),
    DISPOSITION_ACTIVE: frozenset(),
    DISPOSITION_SUPERSEDED: frozenset(),
    DISPOSITION_CANCELLED: frozenset(),
}

# ── Действия API/сервиса ───────────────────────────────────────────────────────
ACTION_PREPARE = "PREPARE"
ACTION_APPROVE = "APPROVE"
ACTION_ACTIVATE = "ACTIVATE"
ACTION_CANCEL = "CANCEL"

DISPOSITION_ACTIONS: tuple[str, ...] = (
    ACTION_PREPARE,
    ACTION_APPROVE,
    ACTION_ACTIVATE,
    ACTION_CANCEL,
)
DispositionAction = Literal["PREPARE", "APPROVE", "ACTIVATE", "CANCEL"]

_ACTION_TARGET: dict[str, str] = {
    ACTION_PREPARE: DISPOSITION_PREPARED,
    ACTION_APPROVE: DISPOSITION_APPROVED,
    ACTION_ACTIVATE: DISPOSITION_ACTIVE,
    ACTION_CANCEL: DISPOSITION_CANCELLED,
}

# ── Типы событий аудита ────────────────────────────────────────────────────────
EVENT_CREATED = "DISPOSITION_CREATED"
EVENT_PREPARED = "DISPOSITION_PREPARED"
EVENT_APPROVED = "DISPOSITION_APPROVED"
EVENT_ACTIVATED = "DISPOSITION_ACTIVATED"
EVENT_CANCELLED = "DISPOSITION_CANCELLED"

DISPOSITION_EVENT_TYPES: tuple[str, ...] = (
    EVENT_CREATED,
    EVENT_PREPARED,
    EVENT_APPROVED,
    EVENT_ACTIVATED,
    EVENT_CANCELLED,
)

_ACTION_EVENT: dict[str, str] = {
    ACTION_PREPARE: EVENT_PREPARED,
    ACTION_APPROVE: EVENT_APPROVED,
    ACTION_ACTIVATE: EVENT_ACTIVATED,
    ACTION_CANCEL: EVENT_CANCELLED,
}


def is_valid_status(status: str) -> bool:
    return status in DISPOSITION_STATUSES


def is_terminal(status: str) -> bool:
    return status in DISPOSITION_TERMINAL_STATUSES


def can_transition(from_status: str, to_status: str) -> bool:
    """Разрешён ли переход статуса (pure; SUPERSEDED недостижим в MVP)."""
    return to_status in _ALLOWED_TRANSITIONS.get(from_status, frozenset())


def target_status_for_action(action: str) -> str | None:
    return _ACTION_TARGET.get(action)


def event_type_for_action(action: str) -> str | None:
    return _ACTION_EVENT.get(action)


def is_valid_action(action: str) -> bool:
    return action in DISPOSITION_ACTIONS


# ── Роли (канонические role_code; новых не вводим) ─────────────────────────────
ROLE_OGS_ENGINEER = iw.ROLE_OGS_ENGINEER
ROLE_OTK_INSPECTOR = iw.ROLE_OTK_INSPECTOR
ROLE_CHIEF_WELDER = iw.ROLE_CHIEF_WELDER

DISPOSITION_CREATE_ROLES: frozenset[str] = frozenset(
    {ROLE_OGS_ENGINEER, ROLE_CHIEF_WELDER}
)
DISPOSITION_PREPARE_ROLES: frozenset[str] = frozenset(
    {ROLE_OGS_ENGINEER, ROLE_CHIEF_WELDER}
)
DISPOSITION_APPROVE_ROLES: frozenset[str] = frozenset(
    {ROLE_OTK_INSPECTOR, ROLE_CHIEF_WELDER}
)
# Активация (APPROVED → ACTIVE): только главный сварщик (решение 9D-4A-3 Role Decision).
# OTK_INSPECTOR утверждает (APPROVE), но не активирует.
DISPOSITION_ACTIVATE_ROLES: frozenset[str] = frozenset({ROLE_CHIEF_WELDER})
DISPOSITION_CANCEL_ROLES: frozenset[str] = frozenset({ROLE_CHIEF_WELDER})
DISPOSITION_OVERRIDE_ROLES: frozenset[str] = frozenset({ROLE_CHIEF_WELDER})
DISPOSITION_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES

_ACTION_ROLES: dict[str, frozenset[str]] = {
    ACTION_PREPARE: DISPOSITION_PREPARE_ROLES,
    ACTION_APPROVE: DISPOSITION_APPROVE_ROLES,
    ACTION_ACTIVATE: DISPOSITION_ACTIVATE_ROLES,
    ACTION_CANCEL: DISPOSITION_CANCEL_ROLES,
}


def roles_for_action(action: str) -> frozenset[str]:
    return _ACTION_ROLES.get(action, frozenset())


# ── Машинные коды ошибок ───────────────────────────────────────────────────────
DISPOSITION_NOT_FOUND = "DISPOSITION_NOT_FOUND"
DISPOSITION_ROOT_NOT_FOUND = "DISPOSITION_ROOT_NOT_FOUND"
DISPOSITION_INVALID_TRANSITION = "DISPOSITION_INVALID_TRANSITION"
DISPOSITION_INVALID_ACTION = "DISPOSITION_INVALID_ACTION"
DISPOSITION_ACTIVE_IMMUTABLE = "DISPOSITION_ACTIVE_IMMUTABLE"
DISPOSITION_CANCELLED_IMMUTABLE = "DISPOSITION_CANCELLED_IMMUTABLE"
DISPOSITION_REASON_REQUIRED = "DISPOSITION_REASON_REQUIRED"
DISPOSITION_PERMISSION_DENIED = "DISPOSITION_PERMISSION_DENIED"
DISPOSITION_ALREADY_OPEN = "DISPOSITION_ALREADY_OPEN"
DISPOSITION_JUSTIFICATION_REQUIRED = "DISPOSITION_JUSTIFICATION_REQUIRED"
DISPOSITION_DECISION_TYPE_INVALID = "DISPOSITION_DECISION_TYPE_INVALID"
