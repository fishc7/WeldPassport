"""Доменная политика жизненного цикла Inspection (Task 9A, ADR-015 / Session 007).

Единый источник словарей статусов, ролей, машинных кодов ошибок, типов событий,
кодов готовности и вычисления `Joint.inspection_state`. Здесь только чистые
константы и pure-функции без обращения к БД — по образцу `weld_operation_workflow`
и `heat_treatment_workflow` модуля engineering.

Task 9A реализует минимальное ядро `Joint → Inspection`: создание черновика,
редактирование, подтверждение производственной готовности СМР, отправку заявки в
работу с фиксацией готовности ОГС и отмену. Назначение методов, лаборатории,
результаты, решения ОГС, отчёты и дефекты (Tasks 9B–9G) НЕ входят.

Формат кодов — UPPERCASE, как во всём backend (JOINT_STATUSES, WELD_OPERATION_
STATUSES). Полный канонический набор статусов и состояний фиксируется сразу
(ADR-015), но сервисный слой Task 9A реализует только подмножество переходов.
"""

from __future__ import annotations

from typing import Literal

# ── Полный жизненный цикл заявки (ADR-015; сервис Task 9A — подмножество) ───────
# Разрешаем весь канонический набор на уровне БД/схемы, чтобы Tasks 9B–9D не
# переписывали CHECK. Через API Task 9A устанавливаются только DRAFT/REQUESTED/
# CANCELLED; статусы начиная с ASSIGNED задаются будущими задачами.
INSPECTION_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "REQUESTED",
    "ASSIGNED",
    "IN_PROGRESS",
    "COMPLETED",
    "REVIEWED",
    "CLOSED",
    "SUSPENDED",
    "CANCELLED",
    "TERMINATED",
)
InspectionStatus = Literal[
    "DRAFT",
    "REQUESTED",
    "ASSIGNED",
    "IN_PROGRESS",
    "COMPLETED",
    "REVIEWED",
    "CLOSED",
    "SUSPENDED",
    "CANCELLED",
    "TERMINATED",
]

# Терминальные статусы Task 9A: обычное редактирование и переходы запрещены.
INSPECTION_TERMINAL_STATUSES: frozenset[str] = frozenset({"CANCELLED", "TERMINATED"})
# Статусы, в которых заявка «в работе или дальше»: для них обязаны быть заполнены
# requested-/ogs-readiness-поля (CHECK в модели и миграции). DRAFT и CANCELLED —
# исключение (DRAFT ещё не отправлена, CANCELLED мог быть отменён из DRAFT).
INSPECTION_REQUESTED_OR_LATER: frozenset[str] = frozenset(
    {
        "REQUESTED",
        "ASSIGNED",
        "IN_PROGRESS",
        "COMPLETED",
        "REVIEWED",
        "CLOSED",
        "SUSPENDED",
        "TERMINATED",
    }
)
# Статусы, из которых Task 9A разрешает отмену.
INSPECTION_CANCELLABLE_STATUSES: frozenset[str] = frozenset({"DRAFT", "REQUESTED"})

# ── Типы событий журнала Task 9A (§9 задания) ─────────────────────────────────
EVENT_CREATED = "CREATED"
EVENT_UPDATED = "UPDATED"
EVENT_PRODUCTION_READINESS_CONFIRMED = "PRODUCTION_READINESS_CONFIRMED"
EVENT_REQUESTED = "REQUESTED"
EVENT_READINESS_OVERRIDDEN = "READINESS_OVERRIDDEN"
EVENT_CANCELLED = "CANCELLED"
INSPECTION_EVENT_TYPES: tuple[str, ...] = (
    EVENT_CREATED,
    EVENT_UPDATED,
    EVENT_PRODUCTION_READINESS_CONFIRMED,
    EVENT_REQUESTED,
    EVENT_READINESS_OVERRIDDEN,
    EVENT_CANCELLED,
)

# ── Роли (§15 задания; канонические role_code проекта, новых не вводим) ────────
# Бизнес-наименование WELDING_ENGINEER ↔ технический код OGS_ENGINEER. Для НК в
# каноне ролей проекта используется NDT_SPECIALIST (не «NDT»); для ОТК —
# OTK_INSPECTOR (совпадает с ADR-015). Дубликаты ролей не создаются.
ROLE_OGS_ENGINEER = "OGS_ENGINEER"
ROLE_CHIEF_WELDER = "CHIEF_WELDER"
ROLE_PTO_ENGINEER = "PTO_ENGINEER"
ROLE_OTK_INSPECTOR = "OTK_INSPECTOR"
ROLE_FOREMAN = "FOREMAN"
ROLE_MASTER = "MASTER"
ROLE_NDT_SPECIALIST = "NDT_SPECIALIST"

# Создание, редактирование DRAFT, отправка и отмена заявки (§15.1).
INSPECTION_LIFECYCLE_ROLES: frozenset[str] = frozenset(
    {ROLE_OGS_ENGINEER, ROLE_CHIEF_WELDER}
)
# Отправку в REQUESTED выполняют те же роли (§14).
INSPECTION_REQUEST_ROLES: frozenset[str] = frozenset(
    {ROLE_OGS_ENGINEER, ROLE_CHIEF_WELDER}
)
# Право обойти отсутствие подтверждения СМР при отправке — только у главного
# сварщика (§14.1). Обычный ОГС override не имеет.
INSPECTION_OVERRIDE_ROLES: frozenset[str] = frozenset({ROLE_CHIEF_WELDER})
# Подтверждение производственной готовности — СМР: мастер/прораб (§13, §15.3).
PRODUCTION_READINESS_ROLES: frozenset[str] = frozenset({ROLE_FOREMAN, ROLE_MASTER})
# Чтение заявки (§15.4). NDT_SPECIALIST в Task 9A получает только чтение заявки.
INSPECTION_READ_ROLES: frozenset[str] = frozenset(
    {
        ROLE_CHIEF_WELDER,
        ROLE_OGS_ENGINEER,
        ROLE_PTO_ENGINEER,
        ROLE_OTK_INSPECTOR,
        ROLE_FOREMAN,
        ROLE_MASTER,
        ROLE_NDT_SPECIALIST,
    }
)
# Чтение readiness (§15.5). NDT_SPECIALIST не получает readiness до Task 9B.
READINESS_READ_ROLES: frozenset[str] = frozenset(
    {
        ROLE_CHIEF_WELDER,
        ROLE_OGS_ENGINEER,
        ROLE_PTO_ENGINEER,
        ROLE_OTK_INSPECTOR,
        ROLE_FOREMAN,
        ROLE_MASTER,
    }
)

# ── Машинные коды доменных ошибок (§18 задания) ───────────────────────────────
# HTTP-семантика: 403 — роль/scope; 404 — объект не найден или скрыт scope;
# 409 — конфликт версии/недопустимый переход/повтор/готовность; 422 — структурно
# недопустимая команда.
INSPECTION_NOT_FOUND = "INSPECTION_NOT_FOUND"
INSPECTION_ROLE_DENIED = "INSPECTION_ROLE_DENIED"
INSPECTION_VERSION_CONFLICT = "INSPECTION_VERSION_CONFLICT"
INSPECTION_NOT_DRAFT = "INSPECTION_NOT_DRAFT"
INSPECTION_INVALID_TRANSITION = "INSPECTION_INVALID_TRANSITION"
INSPECTION_ALREADY_CANCELLED = "INSPECTION_ALREADY_CANCELLED"
INSPECTION_NOT_READY = "INSPECTION_NOT_READY"
INSPECTION_SMR_NOT_CONFIRMED = "INSPECTION_SMR_NOT_CONFIRMED"
INSPECTION_OVERRIDE_NOT_ALLOWED = "INSPECTION_OVERRIDE_NOT_ALLOWED"
INSPECTION_DUPLICATE_EXTERNAL_NO = "INSPECTION_DUPLICATE_EXTERNAL_NO"
INSPECTION_IDEMPOTENCY_CONFLICT = "INSPECTION_IDEMPOTENCY_CONFLICT"
INSPECTION_PROJECT_MISMATCH = "INSPECTION_PROJECT_MISMATCH"

# ── Коды готовности Joint к контролю (§12 задания) ────────────────────────────
# Стабильные машинные коды блокирующих причин и предупреждений. Помимо кода
# readiness возвращает человекочитаемое сообщение (§12).
READINESS_JOINT_NOT_ACTIVE = "JOINT_NOT_ACTIVE"
READINESS_NO_COMPLETED_WELD_OPERATION = "NO_COMPLETED_WELD_OPERATION"
READINESS_WELD_OPERATION_NOT_CURRENT = "WELD_OPERATION_NOT_CURRENT"
READINESS_HEAT_TREATMENT_NOT_ACCEPTED = "HEAT_TREATMENT_NOT_ACCEPTED"

WARNING_PRODUCTION_READINESS_NOT_CONFIRMED = "PRODUCTION_READINESS_NOT_CONFIRMED"
WARNING_OPEN_OGS_WELD_REVIEW = "OPEN_OGS_WELD_REVIEW"
WARNING_OTHER_ACTIVE_INSPECTION_EXISTS = "OTHER_ACTIVE_INSPECTION_EXISTS"

READINESS_MESSAGES: dict[str, str] = {
    READINESS_JOINT_NOT_ACTIVE: (
        "Стык не в статусе ACTIVE: контроль не может быть назначен."
    ),
    READINESS_NO_COMPLETED_WELD_OPERATION: (
        "Для стыка отсутствует актуальная завершённая сварочная операция."
    ),
    READINESS_WELD_OPERATION_NOT_CURRENT: (
        "Завершённая сварочная операция стыка заменена и не является актуальной "
        "производственной версией."
    ),
    READINESS_HEAT_TREATMENT_NOT_ACCEPTED: (
        "Требуемая термообработка стыка ещё не выполнена и не принята."
    ),
    WARNING_PRODUCTION_READINESS_NOT_CONFIRMED: (
        "Производственная готовность стыка (СМР) ещё не подтверждена."
    ),
    WARNING_OPEN_OGS_WELD_REVIEW: (
        "По сварочной операции стыка есть незакрытая проверка ОГС."
    ),
    WARNING_OTHER_ACTIVE_INSPECTION_EXISTS: (
        "Для стыка уже существует другая действующая заявка на контроль."
    ),
}


def readiness_reason(code: str) -> dict[str, str]:
    """Строит стабильную причину `{code, message}` для readiness (§12)."""
    return {"code": code, "message": READINESS_MESSAGES.get(code, code)}


# ── Вычисляемое состояние контроля Joint (§17 задания) ────────────────────────
# Полный канонический enum фиксируется сразу; в Task 9A достоверно вычисляются
# только NOT_REQUIRED / PENDING / IN_PROGRESS (§17). Значения PASSED / FAILED /
# REPAIR_REQUIRED / REINSPECTION_REQUIRED появятся начиная с Task 9D — из одного
# статуса Inspection они не выводятся.
INSPECTION_STATES: tuple[str, ...] = (
    "NOT_REQUIRED",
    "PENDING",
    "IN_PROGRESS",
    "PASSED",
    "FAILED",
    "REPAIR_REQUIRED",
    "REINSPECTION_REQUIRED",
)
InspectionState = Literal[
    "NOT_REQUIRED",
    "PENDING",
    "IN_PROGRESS",
    "PASSED",
    "FAILED",
    "REPAIR_REQUIRED",
    "REINSPECTION_REQUIRED",
]

# Статусы Inspection, дающие PENDING (§17.1).
INSPECTION_STATE_PENDING_STATUSES: frozenset[str] = frozenset(
    {"DRAFT", "REQUESTED", "ASSIGNED"}
)
# Статусы Inspection, дающие IN_PROGRESS (§17.1). Приоритет IN_PROGRESS > PENDING.
INSPECTION_STATE_IN_PROGRESS_STATUSES: frozenset[str] = frozenset(
    {"IN_PROGRESS", "COMPLETED", "REVIEWED"}
)


def inspection_state_from_statuses(statuses: list[str]) -> str:
    """Выводит `Joint.inspection_state` из статусов действующих заявок (§17.1).

    CANCELLED/TERMINATED игнорируются. CLOSED не становится автоматически PASSED
    (§17.1) и в Task 9A не влияет на состояние. Приоритет IN_PROGRESS > PENDING.
    Отсутствие действующих заявок — базовое NOT_REQUIRED (§17.2): временное
    состояние, которое Task 9B уточнит по требуемым методам контроля. НЕ означает
    доменного утверждения об отсутствии нормативного требования.
    """
    has_in_progress = any(
        s in INSPECTION_STATE_IN_PROGRESS_STATUSES for s in statuses
    )
    if has_in_progress:
        return "IN_PROGRESS"
    has_pending = any(s in INSPECTION_STATE_PENDING_STATUSES for s in statuses)
    if has_pending:
        return "PENDING"
    return "NOT_REQUIRED"
