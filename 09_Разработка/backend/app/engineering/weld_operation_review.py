"""Доменная политика подтверждения сварщика и review ОГС (Task 8C, ADR-012).

Чистый доменный компонент: словари статусов, роли, reason codes, правила
переходов и первичной маршрутизации для двух независимых осей `WeldOperation`,
добавляемых Task 8C:

* `welder_confirmation_status` — подтвердил ли мастер/прораб фактического
  исполнителя (§4 задания);
* `ogs_review_status` — технологическое решение ОГС по завершённой операции
  (§5 задания).

Оси независимы друг от друга, от `lifecycle_status` и от автоматических
validation-статусов Task 8B (§2-3 задания). Здесь только чистые константы и
функции без обращения к БД и HTTP (как `weld_operation_workflow` и
`weld_operation_validation`).
"""

from __future__ import annotations

from typing import Literal

# ── Статус подтверждения сварщика (§4 задания) ────────────────────────────────
WELDER_CONFIRMATION_PENDING = "PENDING"
WELDER_CONFIRMATION_CONFIRMED = "CONFIRMED"
WELDER_CONFIRMATION_DISPUTED = "DISPUTED"

WELDER_CONFIRMATION_STATUSES: tuple[str, ...] = (
    WELDER_CONFIRMATION_PENDING,
    WELDER_CONFIRMATION_CONFIRMED,
    WELDER_CONFIRMATION_DISPUTED,
)
WelderConfirmationStatus = Literal["PENDING", "CONFIRMED", "DISPUTED"]

# Решение confirmation-команды: подтвердить или оспорить (§8.1). PENDING — только
# начальное значение, командой не устанавливается.
WELDER_CONFIRMATION_DECISIONS: tuple[str, ...] = (
    WELDER_CONFIRMATION_CONFIRMED,
    WELDER_CONFIRMATION_DISPUTED,
)
WelderConfirmationDecision = Literal["CONFIRMED", "DISPUTED"]

# ── Статус review ОГС (§5 задания) ────────────────────────────────────────────
OGS_REVIEW_NOT_REQUIRED = "NOT_REQUIRED"
OGS_REVIEW_PENDING = "PENDING"
OGS_REVIEW_APPROVED = "APPROVED"
OGS_REVIEW_REJECTED = "REJECTED"

OGS_REVIEW_STATUSES: tuple[str, ...] = (
    OGS_REVIEW_NOT_REQUIRED,
    OGS_REVIEW_PENDING,
    OGS_REVIEW_APPROVED,
    OGS_REVIEW_REJECTED,
)
OgsReviewStatus = Literal["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"]

# Решение review-команды: принять или отклонить технологический факт (§8.2).
OGS_REVIEW_DECISIONS: tuple[str, ...] = (OGS_REVIEW_APPROVED, OGS_REVIEW_REJECTED)
OgsReviewDecision = Literal["APPROVED", "REJECTED"]

# ── Роли (§6 задания; существующие role_code, новых не вводим) ─────────────────
# Подтверждают/оспаривают участие сварщика — производственные MASTER/FOREMAN и
# глобальный админ CHIEF_WELDER (§6.1). Совпадает с ролями действия Task 8A.
WELDER_CONFIRMATION_ROLES: frozenset[str] = frozenset(
    {"MASTER", "FOREMAN", "CHIEF_WELDER"}
)
# Решение ОГС принимает инженер ОГС или главный сварщик (§6.2).
OGS_REVIEW_ROLES: frozenset[str] = frozenset({"OGS_ENGINEER", "CHIEF_WELDER"})
# История подтверждений доступна производству и ОГС (§10.5).
WELDER_CONFIRMATION_HISTORY_ROLES: frozenset[str] = frozenset(
    {"MASTER", "FOREMAN", "OGS_ENGINEER", "CHIEF_WELDER"}
)
# История review ОГС — только ОГС и главный сварщик (§10.6).
OGS_REVIEW_HISTORY_ROLES: frozenset[str] = frozenset(
    {"OGS_ENGINEER", "CHIEF_WELDER"}
)

# ── Reason codes решения ОГС (§9 задания) ─────────────────────────────────────
# Коды-исключения: обоснованное принятие технологического факта поверх нарушения
# или недостатка данных. Требуются при APPROVED поверх FAIL/INDETERMINATE (§5.1).
QUALIFICATION_EXCEPTION_ACCEPTED = "QUALIFICATION_EXCEPTION_ACCEPTED"
WPS_EXCEPTION_ACCEPTED = "WPS_EXCEPTION_ACCEPTED"
INSUFFICIENT_SOURCE_DATA_ACCEPTED = "INSUFFICIENT_SOURCE_DATA_ACCEPTED"
WELDER_IDENTITY_REQUIRES_CORRECTION = "WELDER_IDENTITY_REQUIRES_CORRECTION"
# Коды несоответствия: обоснование отклонения технологического факта.
QUALIFICATION_NONCOMPLIANCE = "QUALIFICATION_NONCOMPLIANCE"
WPS_NONCOMPLIANCE = "WPS_NONCOMPLIANCE"
WELDER_IDENTITY_DISPUTED = "WELDER_IDENTITY_DISPUTED"
# Прочее основание — требует непустого комментария (§9).
OTHER = "OTHER"

# Детерминированный стабильный порядок кодов (§9: порядок нормализован и стабилен).
REASON_CODE_ORDER: tuple[str, ...] = (
    QUALIFICATION_EXCEPTION_ACCEPTED,
    WPS_EXCEPTION_ACCEPTED,
    INSUFFICIENT_SOURCE_DATA_ACCEPTED,
    WELDER_IDENTITY_REQUIRES_CORRECTION,
    QUALIFICATION_NONCOMPLIANCE,
    WPS_NONCOMPLIANCE,
    WELDER_IDENTITY_DISPUTED,
    OTHER,
)
REASON_CODES: frozenset[str] = frozenset(REASON_CODE_ORDER)
ReasonCode = Literal[
    "QUALIFICATION_EXCEPTION_ACCEPTED",
    "WPS_EXCEPTION_ACCEPTED",
    "INSUFFICIENT_SOURCE_DATA_ACCEPTED",
    "WELDER_IDENTITY_REQUIRES_CORRECTION",
    "QUALIFICATION_NONCOMPLIANCE",
    "WPS_NONCOMPLIANCE",
    "WELDER_IDENTITY_DISPUTED",
    "OTHER",
]

# Подмножество кодов-исключений: минимум один обязателен при APPROVED поверх
# отрицательного/неопределённого автоматического результата (§5.1, §9).
EXCEPTION_REASON_CODES: frozenset[str] = frozenset(
    {
        QUALIFICATION_EXCEPTION_ACCEPTED,
        WPS_EXCEPTION_ACCEPTED,
        INSUFFICIENT_SOURCE_DATA_ACCEPTED,
        WELDER_IDENTITY_REQUIRES_CORRECTION,
    }
)

# Автоматические validation-статусы, при которых требуется обоснование исключения
# (§5.1). NOT_CHECKED у завершённой операции считается требующим ручного review.
_VALIDATION_NEEDS_EXCEPTION: frozenset[str] = frozenset(
    {"FAIL", "INDETERMINATE", "NOT_CHECKED"}
)

# ── Машинные коды доменных ошибок (§13 задания) ───────────────────────────────
# HTTP-семантика: 403 — роль/scope; 404 — операция не найдена; 409 — lifecycle
# conflict, повтор решения, version conflict; 422 — структурно недопустимая команда
# или отсутствует обязательное обоснование.
WELD_OPERATION_NOT_COMPLETED = "WELD_OPERATION_NOT_COMPLETED"
WELDER_CONFIRMATION_VERSION_CONFLICT = "WELDER_CONFIRMATION_VERSION_CONFLICT"
WELDER_ALREADY_CONFIRMED = "WELDER_ALREADY_CONFIRMED"
WELDER_ALREADY_DISPUTED = "WELDER_ALREADY_DISPUTED"
WELDER_DISPUTE_COMMENT_REQUIRED = "WELDER_DISPUTE_COMMENT_REQUIRED"

OGS_REVIEW_VERSION_CONFLICT = "OGS_REVIEW_VERSION_CONFLICT"
OGS_REVIEW_REASON_REQUIRED = "OGS_REVIEW_REASON_REQUIRED"
OGS_REVIEW_COMMENT_REQUIRED = "OGS_REVIEW_COMMENT_REQUIRED"
OGS_REVIEW_REASON_INVALID = "OGS_REVIEW_REASON_INVALID"
OGS_REVIEW_EXCEPTION_REASON_REQUIRED = "OGS_REVIEW_EXCEPTION_REASON_REQUIRED"
OGS_REVIEW_NOT_ALLOWED = "OGS_REVIEW_NOT_ALLOWED"
OGS_REVIEW_ALREADY_APPROVED = "OGS_REVIEW_ALREADY_APPROVED"
OGS_REVIEW_ALREADY_REJECTED = "OGS_REVIEW_ALREADY_REJECTED"


# ── Первичная маршрутизация review при завершении (§5.2) ───────────────────────


def initial_ogs_review_status(
    qualification_status: str,
    wps_status: str,
    welder_confirmation_status: str,
) -> str:
    """Первичный `ogs_review_status` завершённой операции (§5.2).

    NOT_REQUIRED только когда одновременно: допуск PASS, WPS PASS и сварщик не
    оспорен. Иначе (любой FAIL/INDETERMINATE/NOT_CHECKED или спор сварщика) —
    PENDING (ручное рассмотрение ОГС)."""
    if welder_confirmation_status == WELDER_CONFIRMATION_DISPUTED:
        return OGS_REVIEW_PENDING
    if qualification_status == "PASS" and wps_status == "PASS":
        return OGS_REVIEW_NOT_REQUIRED
    return OGS_REVIEW_PENDING


# ── Переходы подтверждения сварщика (§4.3) ────────────────────────────────────


def confirmation_noop_code(current_status: str, decision: str) -> str | None:
    """Код конфликта, если решение не меняет текущий статус (§4.3).

    Повтор идентичного решения — доменный конфликт 409, а не новая запись истории.
    None → реальный переход разрешён."""
    if decision == current_status:
        if decision == WELDER_CONFIRMATION_CONFIRMED:
            return WELDER_ALREADY_CONFIRMED
        if decision == WELDER_CONFIRMATION_DISPUTED:
            return WELDER_ALREADY_DISPUTED
    return None


# ── Переходы решения ОГС (§5, §10.3-10.4) ─────────────────────────────────────


def review_noop_code(current_status: str, decision: str) -> str | None:
    """Код конфликта, если решение ОГС не меняет текущий статус (§17.2 #33).

    Повтор идентичного текущего решения (APPROVED→APPROVED, REJECTED→REJECTED) —
    409 без новой версии истории. None → новое решение разрешено."""
    if decision == current_status:
        if decision == OGS_REVIEW_APPROVED:
            return OGS_REVIEW_ALREADY_APPROVED
        if decision == OGS_REVIEW_REJECTED:
            return OGS_REVIEW_ALREADY_REJECTED
    return None


# ── Reason codes: нормализация и проверки (§9) ────────────────────────────────


def normalize_reason_codes(codes: list[str] | tuple[str, ...]) -> list[str]:
    """Уникальные reason codes в детерминированном каноническом порядке (§9)."""
    present = set(codes)
    return [code for code in REASON_CODE_ORDER if code in present]


def requires_exception_reason(
    qualification_status: str, wps_status: str
) -> bool:
    """Требует ли APPROVE обоснования исключения при данных validation-статусах.

    True, если хотя бы один автоматический результат — FAIL/INDETERMINATE или
    незавершённый NOT_CHECKED (§5.1)."""
    return (
        qualification_status in _VALIDATION_NEEDS_EXCEPTION
        or wps_status in _VALIDATION_NEEDS_EXCEPTION
    )


def has_exception_reason(codes: list[str] | tuple[str, ...]) -> bool:
    """Есть ли среди кодов хотя бы один код-исключение (§5.1, §9)."""
    return bool(set(codes) & EXCEPTION_REASON_CODES)


def requires_comment(codes: list[str] | tuple[str, ...]) -> bool:
    """Обязателен ли непустой комментарий из-за состава кодов (§9: OTHER)."""
    return OTHER in set(codes)
