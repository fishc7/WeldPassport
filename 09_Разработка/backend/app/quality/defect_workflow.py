"""Доменная политика жизненного цикла Defect (Task 9D-3A, ADR-022).

Продолжение канона Tasks 9A–9D-2 (`inspection_workflow`, `quality_finding_workflow`,
`engineering_evaluation_workflow`): только чистые константы и pure-функции без обращения
к БД. Здесь фиксируются статусы технической ревизии дефекта, допустимые переходы,
контролируемый перечень расположения индикации, типы событий append-only-журнала и
чистая нормализация окружного положения.

Границы Task 9D-3A (модели/миграция/seed/нумерация): здесь только политика уровня
данных. Бизнес-команды (`create`/`activate`/`supersede`/`cancel`), сервисы, валидация
активации, RBAC и API — блоки 9D-3B/3C и в этот модуль не входят. Полный канонический
набор статусов фиксируется сразу (как в 9A/9D-1), чтобы будущие блоки не переписывали
CHECK; переходы задаются pure-функцией.

Формат кодов — UPPERCASE, как во всём backend.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

# ── Жизненный цикл технической ревизии Defect (ADR-022 §6) ─────────────────────
DEFECT_STATUSES: tuple[str, ...] = ("DRAFT", "ACTIVE", "SUPERSEDED", "CANCELLED")
DefectStatus = Literal["DRAFT", "ACTIVE", "SUPERSEDED", "CANCELLED"]

DEFECT_DRAFT = "DRAFT"
DEFECT_ACTIVE = "ACTIVE"
DEFECT_SUPERSEDED = "SUPERSEDED"
DEFECT_CANCELLED = "CANCELLED"

# Конечные статусы: обычное редактирование и переходы запрещены (ADR-022 §6).
DEFECT_TERMINAL_STATUSES: frozenset[str] = frozenset({DEFECT_SUPERSEDED, DEFECT_CANCELLED})

# Допустимые переходы (ADR-022 §6 / Spec §5). `ACTIVE → SUPERSEDED` выполняется только
# при активации следующей ревизии цепочки (D05); прямого `ACTIVE → DRAFT` нет.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    DEFECT_DRAFT: frozenset({DEFECT_ACTIVE, DEFECT_CANCELLED}),
    DEFECT_ACTIVE: frozenset({DEFECT_SUPERSEDED, DEFECT_CANCELLED}),
    DEFECT_SUPERSEDED: frozenset(),
    DEFECT_CANCELLED: frozenset(),
}


def is_valid_status(status: str) -> bool:
    """Известен ли статус (принадлежит каноническому набору)."""
    return status in DEFECT_STATUSES


def is_terminal(status: str) -> bool:
    """Является ли статус конечным (`SUPERSEDED`/`CANCELLED`)."""
    return status in DEFECT_TERMINAL_STATUSES


def can_transition(from_status: str, to_status: str) -> bool:
    """Разрешён ли переход статуса ревизии `from_status → to_status` (pure)."""
    return to_status in _ALLOWED_TRANSITIONS.get(from_status, frozenset())


# ── Расположение индикации (ADR-022 §5 / Spec §4.2) ────────────────────────────
DEFECT_INDICATION_LOCATIONS: tuple[str, ...] = (
    "SURFACE",
    "INTERNAL",
    "THROUGH_THICKNESS",
    "UNKNOWN",
)
DefectIndicationLocation = Literal[
    "SURFACE", "INTERNAL", "THROUGH_THICKNESS", "UNKNOWN"
]

# ── Типы событий append-only-журнала (ADR-022 §11 / Spec §4.3) ─────────────────
# Ровно шесть канонических типов. Repair/Reweld/Reinspection/закрытие — не вводятся.
DEFECT_EVENT_TYPES: tuple[str, ...] = (
    "DEFECT_DRAFT_CREATED",
    "DEFECT_UPDATED",
    "DEFECT_ACTIVATED",
    "DEFECT_REVISION_CREATED",
    "DEFECT_SUPERSEDED",
    "DEFECT_CANCELLED",
)


# ── Нормализация окружного положения (Spec §7.9; pure-функция, не сервис) ───────
_FULL_CIRCLE = Decimal("360")


def normalize_circumferential_deg(value: Decimal | int | float) -> Decimal:
    """Нормализует градусы по модулю 360 в диапазон [0, 360) (Spec §7.9).

    Чистая функция уровня workflow: `370 → 10`, `-15 → 345`, `360 → 0`. База хранит
    только нормализованное значение (CHECK `0 <= x < 360`). Нормализатор-сервис в
    9D-3A не реализуется — только эта функция для валидации/тестов моделей.
    """
    result = Decimal(str(value)) % _FULL_CIRCLE
    # Python `%` для Decimal уже даёт неотрицательный результат при положительном
    # модуле, но фиксируем инвариант явно на случай особых значений.
    if result < 0:
        result += _FULL_CIRCLE
    return result
