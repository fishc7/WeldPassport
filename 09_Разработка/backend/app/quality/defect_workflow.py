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

from app.quality import inspection_workflow as iw

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
EVENT_DRAFT_CREATED = "DEFECT_DRAFT_CREATED"
EVENT_UPDATED = "DEFECT_UPDATED"
EVENT_ACTIVATED = "DEFECT_ACTIVATED"
EVENT_REVISION_CREATED = "DEFECT_REVISION_CREATED"
EVENT_SUPERSEDED = "DEFECT_SUPERSEDED"
EVENT_CANCELLED = "DEFECT_CANCELLED"

DEFECT_EVENT_TYPES: tuple[str, ...] = (
    EVENT_DRAFT_CREATED,
    EVENT_UPDATED,
    EVENT_ACTIVATED,
    EVENT_REVISION_CREATED,
    EVENT_SUPERSEDED,
    EVENT_CANCELLED,
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


# ── Роли (существующий канон; новых role_code не вводим, ADR-019/§18) ───────────
# Бизнес-роль WELDING_ENGINEER ↔ технический код OGS_ENGINEER (как в 9A–9D-2).
DEFECT_WRITE_ROLES: frozenset[str] = frozenset(
    {iw.ROLE_OGS_ENGINEER, iw.ROLE_CHIEF_WELDER}
)
DEFECT_OVERRIDE_ROLES: frozenset[str] = frozenset({iw.ROLE_CHIEF_WELDER})
DEFECT_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES


# ── Машинные коды доменных ошибок (UPPERCASE; HTTP-семантику задаёт сервис) ─────
DEFECT_NOT_FOUND = "DEFECT_NOT_FOUND"
DEFECT_ROOT_NOT_FOUND = "DEFECT_ROOT_NOT_FOUND"
DEFECT_VERSION_CONFLICT = "DEFECT_VERSION_CONFLICT"
DEFECT_INVALID_TRANSITION = "DEFECT_INVALID_TRANSITION"
DEFECT_ACTIVE_IMMUTABLE = "DEFECT_ACTIVE_IMMUTABLE"
# Двухшаговый supersede (Spec §5/§11): у цепочки нет ACTIVE для замещения /
# в цепочке уже есть открытая DRAFT-ревизия (D04).
DEFECT_SUPERSEDE_REQUIRES_ACTIVE = "DEFECT_SUPERSEDE_REQUIRES_ACTIVE"
DEFECT_CHAIN_HAS_OPEN_DRAFT = "DEFECT_CHAIN_HAS_OPEN_DRAFT"
DEFECT_ALREADY_EXISTS_FOR_EVALUATION = "DEFECT_ALREADY_EXISTS_FOR_EVALUATION"
DEFECT_EVALUATION_NOT_FOUND = "DEFECT_EVALUATION_NOT_FOUND"
DEFECT_EVALUATION_NOT_EFFECTIVE = "DEFECT_EVALUATION_NOT_EFFECTIVE"
DEFECT_EVALUATION_NOT_CONFIRMED = "DEFECT_EVALUATION_NOT_CONFIRMED"
DEFECT_JOINT_MISMATCH = "DEFECT_JOINT_MISMATCH"
DEFECT_TYPE_NOT_FOUND = "DEFECT_TYPE_NOT_FOUND"
DEFECT_TYPE_INACTIVE = "DEFECT_TYPE_INACTIVE"
DEFECT_LOCATION_TYPE_NOT_FOUND = "DEFECT_LOCATION_TYPE_NOT_FOUND"
DEFECT_LOCATION_TYPE_INACTIVE = "DEFECT_LOCATION_TYPE_INACTIVE"
DEFECT_TYPE_REQUIRED = "DEFECT_TYPE_REQUIRED"
DEFECT_LOCATION_TYPE_REQUIRED = "DEFECT_LOCATION_TYPE_REQUIRED"
DEFECT_MEASUREMENT_REQUIRED = "DEFECT_MEASUREMENT_REQUIRED"
DEFECT_MEASUREMENT_NOT_POSITIVE = "DEFECT_MEASUREMENT_NOT_POSITIVE"
DEFECT_DESCRIPTION_REQUIRED = "DEFECT_DESCRIPTION_REQUIRED"
DEFECT_INDICATION_LOCATION_REQUIRED = "DEFECT_INDICATION_LOCATION_REQUIRED"
DEFECT_INDICATION_UNKNOWN_NOT_ALLOWED = "DEFECT_INDICATION_UNKNOWN_NOT_ALLOWED"
DEFECT_CIRC_POSITION_OUT_OF_RANGE = "DEFECT_CIRC_POSITION_OUT_OF_RANGE"
DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED = "DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED"
DEFECT_STANDARD_DOCUMENT_REQUIRED = "DEFECT_STANDARD_DOCUMENT_REQUIRED"
DEFECT_ACTIVATION_INCOMPLETE = "DEFECT_ACTIVATION_INCOMPLETE"
DEFECT_CANCELLATION_REASON_REQUIRED = "DEFECT_CANCELLATION_REASON_REQUIRED"
DEFECT_PERMISSION_DENIED = "DEFECT_PERMISSION_DENIED"

# Технические поля, переносимые снимком при supersede и редактируемые в DRAFT.
DEFECT_TECHNICAL_FIELDS: tuple[str, ...] = (
    "defect_type_id",
    "location_type_id",
    "indication_location",
    "orientation",
    "surface",
    "joint_side",
    "axial_position_mm",
    "circumferential_position_deg",
    "length_mm",
    "width_mm",
    "height_mm",
    "depth_mm",
    "affected_area_mm2",
    "quantity",
    "standard_document",
    "standard_revision",
    "standard_clause",
    "acceptance_level",
    "normative_category_code",
    "technical_description",
    "location_description",
    "evaluation_note",
    "technical_note",
)

# Обязательные измерения ↔ флаг DefectType.requires_*.
DEFECT_MEASUREMENT_REQUIRE_FLAGS: dict[str, str] = {
    "length_mm": "requires_length",
    "width_mm": "requires_width",
    "height_mm": "requires_height",
    "depth_mm": "requires_depth",
    "affected_area_mm2": "requires_area",
    "quantity": "requires_quantity",
}

# Числовые поля, строго положительные при NOT NULL.
DEFECT_POSITIVE_NUMERIC_FIELDS: tuple[str, ...] = (
    "length_mm",
    "width_mm",
    "height_mm",
    "depth_mm",
    "affected_area_mm2",
    "quantity",
)

# Bounded-строки: пустое значение нормализуется в NULL.
DEFECT_BOUNDED_STRING_FIELDS: tuple[str, ...] = (
    "orientation",
    "surface",
    "joint_side",
    "standard_document",
    "standard_revision",
    "standard_clause",
    "acceptance_level",
    "normative_category_code",
)

# Текстовые пояснительные поля: пустое → NULL.
DEFECT_TEXT_FIELDS: tuple[str, ...] = (
    "technical_description",
    "location_description",
    "evaluation_note",
    "technical_note",
)
