"""Policy-слой DefectDisposition (Task 9D-4A-3/9D-4A-4, ADR-023).

Проверка роли и разрешённости операции — вне API, models и schemas.
Scope (Joint) вычисляется сервисом через permissions-framework; сюда передаётся
уже полученный набор granted role_code. Pure-функции без обращения к БД.
"""

from __future__ import annotations

from app.quality import defect_disposition_workflow as ddw


def is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def can_create(granted_roles: set[str]) -> bool:
    return bool(granted_roles & ddw.DISPOSITION_CREATE_ROLES)


def can_read(granted_roles: set[str]) -> bool:
    return bool(granted_roles & ddw.DISPOSITION_READ_ROLES)


def can_perform_action(action: str, granted_roles: set[str]) -> bool:
    """Достаточно ли ролей для действия (без проверки перехода статуса)."""
    allowed = ddw.roles_for_action(action)
    return bool(granted_roles & allowed)


def requires_reason(action: str, granted_roles: set[str]) -> bool:
    """Причина обязательна для cancel, activate и override главного сварщика.

    ACTIVATE — только CHIEF_WELDER; reason и audit обязательны (9D-4A-3 Role Decision).
    CANCEL всегда требует reason.
    CHIEF на prepare/approve без primary OGS/OTK — административный override → reason.
    """
    if action in (ddw.ACTION_CANCEL, ddw.ACTION_ACTIVATE):
        return True
    if granted_roles & ddw.DISPOSITION_OVERRIDE_ROLES:
        if action in (ddw.ACTION_PREPARE, ddw.ACTION_APPROVE):
            primary = ddw.roles_for_action(action) - ddw.DISPOSITION_OVERRIDE_ROLES
            if not (granted_roles & primary):
                return True
    return False


def validate_transition_request(
    *,
    action: str,
    current_status: str,
    granted_roles: set[str],
    reason: str | None,
) -> str | None:
    """Возвращает машинный код ошибки или None, если операция допустима.

    Порядок проверок: action → роль → immutability → переход → reason.
    """
    if not ddw.is_valid_action(action):
        return ddw.DISPOSITION_INVALID_ACTION

    if not can_perform_action(action, granted_roles):
        return ddw.DISPOSITION_PERMISSION_DENIED

    if current_status == ddw.DISPOSITION_ACTIVE:
        return ddw.DISPOSITION_ACTIVE_IMMUTABLE
    if current_status == ddw.DISPOSITION_CANCELLED:
        return ddw.DISPOSITION_CANCELLED_IMMUTABLE

    target = ddw.target_status_for_action(action)
    if target is None or not ddw.can_transition(current_status, target):
        return ddw.DISPOSITION_INVALID_TRANSITION

    if requires_reason(action, granted_roles) and is_blank(reason):
        return ddw.DISPOSITION_REASON_REQUIRED

    return None


def can_supersede(granted_roles: set[str]) -> bool:
    return bool(granted_roles & ddw.DISPOSITION_SUPERSEDE_ROLES)


def validate_supersede_request(
    *,
    current_status: str,
    granted_roles: set[str],
    reason: str | None,
    has_conflicting_open_version: bool,
) -> str | None:
    """Возвращает машинный код ошибки или None, если supersede допустим (Task 9D-4A-4).

    Вызывается сервисом ПОСЛЕ блокировки `DefectRoot` и старой disposition (порядок
    9D-4A-4 Decision: lock root → visibility → status recheck → open-version recheck →
    role/reason). Здесь — только чистая проверка полученных на вход фактов; сам lock
    и перечитывание статуса — забота репозитория/сервиса.
    """
    if current_status != ddw.DISPOSITION_ACTIVE:
        return ddw.DISPOSITION_SUPERSEDE_REQUIRES_ACTIVE
    if has_conflicting_open_version:
        return ddw.DISPOSITION_ALREADY_OPEN
    if not can_supersede(granted_roles):
        return ddw.DISPOSITION_PERMISSION_DENIED
    if is_blank(reason):
        return ddw.DISPOSITION_REASON_REQUIRED
    return None


def pick_actor_role(action: str, granted_roles: set[str]) -> str | None:
    """Выбирает role_code для audit: приоритет основной роли действия, затем CHIEF."""
    allowed = ddw.roles_for_action(action)
    for role in (
        ddw.ROLE_OGS_ENGINEER,
        ddw.ROLE_OTK_INSPECTOR,
        ddw.ROLE_CHIEF_WELDER,
    ):
        if role in granted_roles and role in allowed:
            return role
    matched = granted_roles & allowed
    return next(iter(sorted(matched)), None)
