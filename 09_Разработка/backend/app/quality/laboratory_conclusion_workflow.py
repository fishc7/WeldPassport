"""Доменная политика лабораторного заключения (Task 9C, ADR-015 / Session 007).

Продолжение канона Tasks 9A/9B/9C: только чистые константы и pure-функции без
обращения к БД. Здесь фиксируются жизненный цикл `LaboratoryConclusion`, статусы
аккредитации лаборатории, машинные коды ошибок и pure-функции переходов.

`LaboratoryConclusion` — отдельный официальный документ лаборатории (§15 задания).
Одно заключение может объединять несколько выполнений (`MethodExecution`) одной
лаборатории, одного проекта и одного метода контроля. Единый итог ACCEPTABLE/
UNACCEPTABLE для всего заключения НЕ хранится (§15.1). Гибрид именования: имя
сущности — по ТЗ (`LaboratoryConclusion`); прежний термин канона `InspectionReport`
считается ЗАМЕНЁННЫМ, а не параллельным (обновление docs — отдельным шагом).
"""

from __future__ import annotations

from typing import Literal

from app.quality import inspection_workflow as iw

# ── Роли работы с заключением (§11 задания; канонические role_code) ─────────────
# Чтение — как чтение заявки/выполнения (широкий набор); запись/регистрация —
# ОТК, действующая роль ОГС (OGS_ENGINEER) и главный сварщик (§22, решение 9C-29).
CONCLUSION_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES
CONCLUSION_WRITE_ROLES: frozenset[str] = frozenset(
    {iw.ROLE_OTK_INSPECTOR, iw.ROLE_OGS_ENGINEER, iw.ROLE_CHIEF_WELDER}
)

# ── Жизненный цикл заключения (§16 задания) ────────────────────────────────────
# DRAFT → PREPARED → LAB_APPROVED → ISSUED. CANCELLED — только до ISSUED.
# SUPERSEDED — для предыдущей редакции после выпуска новой редакции (§19).
CONCLUSION_DRAFT = "DRAFT"
CONCLUSION_PREPARED = "PREPARED"
CONCLUSION_LAB_APPROVED = "LAB_APPROVED"
CONCLUSION_ISSUED = "ISSUED"
CONCLUSION_CANCELLED = "CANCELLED"
CONCLUSION_SUPERSEDED = "SUPERSEDED"

CONCLUSION_STATUSES: tuple[str, ...] = (
    CONCLUSION_DRAFT,
    CONCLUSION_PREPARED,
    CONCLUSION_LAB_APPROVED,
    CONCLUSION_ISSUED,
    CONCLUSION_CANCELLED,
    CONCLUSION_SUPERSEDED,
)
ConclusionStatus = Literal[
    "DRAFT", "PREPARED", "LAB_APPROVED", "ISSUED", "CANCELLED", "SUPERSEDED"
]

# Терминальные статусы: обычное редактирование запрещено. ISSUED исправляется только
# новой редакцией (§19); CANCELLED/SUPERSEDED — неизменяемая история.
CONCLUSION_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {CONCLUSION_ISSUED, CONCLUSION_CANCELLED, CONCLUSION_SUPERSEDED}
)
# Статусы, из которых допустима отмена черновика исправления (до ISSUED, §16).
CONCLUSION_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {CONCLUSION_DRAFT, CONCLUSION_PREPARED, CONCLUSION_LAB_APPROVED}
)
# Статусы выполнения, которые разрешено связывать с заключением в DRAFT (§16):
# PERFORMED / RESULT_RECORDED / LAB_CONFIRMED. Для LAB_APPROVED все связанные
# выполнения обязаны быть LAB_CONFIRMED (проверка в сервисе).
CONCLUSION_LINKABLE_EXECUTION_STATUSES: frozenset[str] = frozenset(
    {"PERFORMED", "RESULT_RECORDED", "LAB_CONFIRMED"}
)

_CONCLUSION_FORWARD_TRANSITIONS: dict[str, frozenset[str]] = {
    CONCLUSION_DRAFT: frozenset({CONCLUSION_PREPARED}),
    CONCLUSION_PREPARED: frozenset({CONCLUSION_LAB_APPROVED}),
    CONCLUSION_LAB_APPROVED: frozenset({CONCLUSION_ISSUED}),
    CONCLUSION_ISSUED: frozenset(),
    CONCLUSION_CANCELLED: frozenset(),
    CONCLUSION_SUPERSEDED: frozenset(),
}


# ── Статус аккредитации лаборатории (§21 задания) ──────────────────────────────
ACCREDITATION_ACTIVE = "ACTIVE"
ACCREDITATION_SUSPENDED = "SUSPENDED"
ACCREDITATION_EXPIRED = "EXPIRED"
ACCREDITATION_REVOKED = "REVOKED"
ACCREDITATION_STATUSES: tuple[str, ...] = (
    ACCREDITATION_ACTIVE,
    ACCREDITATION_SUSPENDED,
    ACCREDITATION_EXPIRED,
    ACCREDITATION_REVOKED,
)
AccreditationStatus = Literal["ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"]


# ── Машинные коды доменных ошибок (§27 задания) ────────────────────────────────
CONCLUSION_NOT_FOUND = "CONCLUSION_NOT_FOUND"
CONCLUSION_ROLE_DENIED = "CONCLUSION_ROLE_DENIED"
CONCLUSION_VERSION_CONFLICT = "CONCLUSION_VERSION_CONFLICT"
CONCLUSION_INVALID_TRANSITION = "CONCLUSION_INVALID_TRANSITION"
CONCLUSION_ISSUED_IMMUTABLE = "CONCLUSION_ISSUED_IMMUTABLE"
CONCLUSION_DUPLICATE_NUMBER = "CONCLUSION_DUPLICATE_NUMBER"
CONCLUSION_METHOD_MISMATCH = "CONCLUSION_METHOD_MISMATCH"
CONCLUSION_LABORATORY_MISMATCH = "CONCLUSION_LABORATORY_MISMATCH"
CONCLUSION_PROJECT_MISMATCH = "CONCLUSION_PROJECT_MISMATCH"
CONCLUSION_EXECUTION_NOT_CONFIRMED = "CONCLUSION_EXECUTION_NOT_CONFIRMED"
CONCLUSION_EXECUTION_NOT_LINKABLE = "CONCLUSION_EXECUTION_NOT_LINKABLE"
CONCLUSION_NO_EXECUTIONS = "CONCLUSION_NO_EXECUTIONS"
CONCLUSION_ISSUE_FIELDS_REQUIRED = "CONCLUSION_ISSUE_FIELDS_REQUIRED"
ACCREDITATION_NOT_FOUND = "ACCREDITATION_NOT_FOUND"
ACCREDITATION_LABORATORY_MISMATCH = "ACCREDITATION_LABORATORY_MISMATCH"
ACCREDITATION_INVALID = "ACCREDITATION_INVALID"
# ── Дополнительные коды блока 9C-5 ─────────────────────────────────────────────
CONCLUSION_LABORATORY_NOT_NDT_LAB = "CONCLUSION_LABORATORY_NOT_NDT_LAB"
CONCLUSION_LABORATORY_NOT_FOUND = "CONCLUSION_LABORATORY_NOT_FOUND"
CONCLUSION_INVALID_METHOD = "CONCLUSION_INVALID_METHOD"
CONCLUSION_COMPOSITION_LOCKED = "CONCLUSION_COMPOSITION_LOCKED"
CONCLUSION_EXECUTION_NOT_FOUND = "CONCLUSION_EXECUTION_NOT_FOUND"
CONCLUSION_EXECUTION_DUPLICATE = "CONCLUSION_EXECUTION_DUPLICATE"
CONCLUSION_LINK_NOT_FOUND = "CONCLUSION_LINK_NOT_FOUND"
CONCLUSION_APPROVER_REQUIRED = "CONCLUSION_APPROVER_REQUIRED"
CONCLUSION_ISSUER_REQUIRED = "CONCLUSION_ISSUER_REQUIRED"
CONCLUSION_VERSION_REQUIRED = "CONCLUSION_VERSION_REQUIRED"
CONCLUSION_NUMBER_REQUIRED = "CONCLUSION_NUMBER_REQUIRED"
CONCLUSION_NOT_ISSUED_FOR_REVISION = "CONCLUSION_NOT_ISSUED_FOR_REVISION"
CONCLUSION_NOT_CURRENT_REVISION = "CONCLUSION_NOT_CURRENT_REVISION"
CONCLUSION_CORRECTION_REASON_REQUIRED = "CONCLUSION_CORRECTION_REASON_REQUIRED"
CONCLUSION_REVISION_IN_PROGRESS = "CONCLUSION_REVISION_IN_PROGRESS"
CONCLUSION_REVISION_CONFLICT = "CONCLUSION_REVISION_CONFLICT"
CONCLUSION_CANCELLATION_REASON_REQUIRED = "CONCLUSION_CANCELLATION_REASON_REQUIRED"

# Причина автоматического флага пересмотра (§9): связанное выполнение замещено.
REVIEW_REASON_LINKED_EXECUTION_SUPERSEDED = "LINKED_EXECUTION_SUPERSEDED"


def normalize_conclusion_number(raw: str | None) -> str | None:
    """Нормализует номер заключения для проверки уникальности (§5).

    Обрезает края, схлопывает повторяющиеся пробелы, приводит к верхнему регистру
    (канон проекта — UPPERCASE-коды). Исходный номер сохраняется отдельно в
    `conclusion_number`. Пустая/None-строка → None.
    """
    if raw is None:
        return None
    collapsed = " ".join(raw.split())
    if not collapsed:
        return None
    return collapsed.upper()


def is_valid_conclusion_status(status: str) -> bool:
    """Входит ли статус в закрытый набор статусов заключения (§16)."""
    return status in CONCLUSION_STATUSES


def can_transition_conclusion(current: str, target: str) -> bool:
    """Допустим ли прямой переход статуса заключения вперёд по цепочке (§16).

    Отмена (→CANCELLED) и замещение (→SUPERSEDED) — отдельные команды со своими
    инвариантами (черновик исправления; успешный выпуск новой редакции), сюда не
    входят и проверяются в сервисном слое.
    """
    return target in _CONCLUSION_FORWARD_TRANSITIONS.get(current, frozenset())


def is_accreditation_valid_on(
    status: str,
    *,
    valid_from: object,
    valid_until: object,
    on_date: object,
) -> bool:
    """Действует ли аккредитация на дату контроля (§21).

    Валидна, если статус ACTIVE и `on_date` входит в интервал [valid_from,
    valid_until] (границы включительно; открытая правая граница — бессрочно).
    Сравнение — обычными операторами date; типы приводит вызывающий код.
    """
    if status != ACCREDITATION_ACTIVE:
        return False
    if valid_from is not None and on_date < valid_from:  # type: ignore[operator]
        return False
    if valid_until is not None and on_date > valid_until:  # type: ignore[operator]
        return False
    return True
