"""Системные seed-данные справочников Defect (Task 9D-3A, ADR-022 §5; Spec §13/§15).

Только данные и стабильные (детерминированные) UUID — без обращения к БД. Используется
Alembic-миграцией (idempotent INSERT ... ON CONFLICT (code) DO NOTHING) и тестами.

Baseline `requires_*` — консервативный (Spec §13): все `false`, кроме `OTHER.requires_description`.
Перечни — технический стартовый набор, НЕ полный нормативный классификатор (ГОСТ/ISO/ASME).
Значения меняются только контролируемой миграцией.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# Фиксированный namespace для детерминированных UUID seed-строк (стабильны между БД).
DEFECT_SEED_NAMESPACE = UUID("6d2f9c14-0e2a-5b7d-9a3e-2f1c4b8d7e60")

# Флаги requires_* по умолчанию (Spec §13): всё false, кроме OTHER.requires_description.
_REQUIRES_FALSE: dict[str, bool] = {
    "requires_length": False,
    "requires_width": False,
    "requires_height": False,
    "requires_depth": False,
    "requires_area": False,
    "requires_quantity": False,
    "requires_known_indication_location": False,
    "requires_description": False,
}


def defect_type_uuid(code: str) -> UUID:
    """Стабильный UUID типа дефекта по коду (идемпотентность seed)."""
    return uuid5(DEFECT_SEED_NAMESPACE, f"defect_type:{code}")


def defect_location_type_uuid(code: str) -> UUID:
    """Стабильный UUID расположения по коду."""
    return uuid5(DEFECT_SEED_NAMESPACE, f"defect_location_type:{code}")


def _defect_type(code: str, name: str, **requires: bool) -> dict:
    flags = dict(_REQUIRES_FALSE)
    flags.update(requires)
    return {
        "id": defect_type_uuid(code),
        "code": code,
        "name": name,
        "category": None,
        **flags,
    }


# ── DefectType seed (Spec §15.1) ───────────────────────────────────────────────
DEFECT_TYPE_SEED: list[dict] = [
    _defect_type("CRACK", "Трещина"),
    _defect_type("LACK_OF_FUSION", "Непровар (несплавление)"),
    _defect_type("LACK_OF_PENETRATION", "Неполный провар корня"),
    _defect_type("POROSITY", "Пористость"),
    _defect_type("SLAG_INCLUSION", "Шлаковое включение"),
    _defect_type("UNDERCUT", "Подрез"),
    _defect_type("BURN_THROUGH", "Прожог"),
    # Для OTHER обязательно техническое описание (Spec §13).
    _defect_type("OTHER", "Иное (уточняется описанием)", requires_description=True),
]

# ── DefectLocationType seed (Spec §15.2) ───────────────────────────────────────
DEFECT_LOCATION_TYPE_SEED: list[dict] = [
    {"id": defect_location_type_uuid("WELD_METAL"), "code": "WELD_METAL", "name": "Металл шва"},
    {"id": defect_location_type_uuid("FUSION_LINE"), "code": "FUSION_LINE", "name": "Линия сплавления"},
    {
        "id": defect_location_type_uuid("HEAT_AFFECTED_ZONE"),
        "code": "HEAT_AFFECTED_ZONE",
        "name": "Зона термического влияния",
    },
    {"id": defect_location_type_uuid("BASE_METAL"), "code": "BASE_METAL", "name": "Основной металл"},
    {"id": defect_location_type_uuid("ROOT"), "code": "ROOT", "name": "Корень шва"},
    {"id": defect_location_type_uuid("FACE"), "code": "FACE", "name": "Лицевая сторона шва"},
    {"id": defect_location_type_uuid("OTHER"), "code": "OTHER", "name": "Иное"},
]

DEFECT_TYPE_CODES: tuple[str, ...] = tuple(row["code"] for row in DEFECT_TYPE_SEED)
DEFECT_LOCATION_TYPE_CODES: tuple[str, ...] = tuple(
    row["code"] for row in DEFECT_LOCATION_TYPE_SEED
)
