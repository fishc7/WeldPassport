"""Единый validation pipeline технической модели Defect (Task 9D-3B; ADR-022, Spec §8).

Чистый слой без БД и без HTTP: нормализация значений технических полей, структурная
проверка DRAFT (`validate_draft_structural`, только CHECK-уровень) и агрегированная
проверка комплектности для активации (`validate_for_activation`). Возвращает **полный
список нарушений** (как 9D-2-C11), а не first-fail. Ссылочные объекты
(`DefectType`/`DefectLocationType`) передаёт сервис; их существование/видимость проверяет
сервис отдельно (hard-ошибки).

Двухшаговый supersede (Spec §5): supersede создаёт **DRAFT**-ревизию — только
`validate_draft_structural`; полная `validate_for_activation` выполняется отдельной
командой `activate`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.quality import defect_workflow as dw
from app.quality.defect_models import Defect, DefectLocationType, DefectType


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_field_values(fields: dict[str, Any]) -> dict[str, Any]:
    """Нормализует значения технических полей (Spec §16; pure).

    Bounded-строки и пояснительный текст: trim, пустое → NULL. Окружное положение —
    нормализация по модулю 360 в [0, 360). Остальные значения — как есть.
    """
    result: dict[str, Any] = {}
    for key, value in fields.items():
        if key in dw.DEFECT_BOUNDED_STRING_FIELDS or key in dw.DEFECT_TEXT_FIELDS:
            result[key] = value.strip() or None if isinstance(value, str) else value
        elif key == "circumferential_position_deg" and value is not None:
            result[key] = dw.normalize_circumferential_deg(value)
        else:
            result[key] = value
    return result


def validate_draft_structural(defect: Defect) -> list[tuple[str, str]]:
    """Структурные (CHECK-уровня) инварианты DRAFT-ревизии (Spec §5/§6; pure).

    Проверяет только то, что значения не нарушат DB CHECK: положительность
    заполненных измерений и диапазон окружного положения `[0, 360)`. **Не**
    проверяет комплектность ACTIVE (тип, расположение, обязательные измерения,
    описание, нормативные зависимости) — это делает `validate_for_activation`
    при активации. Применяется при supersede: новая DRAFT может быть неполной,
    но обязана быть структурно допустимой (Spec §3 «validate DRAFT structural
    invariants»).
    """
    violations: list[tuple[str, str]] = []

    for field in dw.DEFECT_POSITIVE_NUMERIC_FIELDS:
        value = getattr(defect, field)
        if value is not None and Decimal(str(value)) <= 0:
            violations.append(
                (
                    dw.DEFECT_MEASUREMENT_NOT_POSITIVE,
                    f"Измерение '{field}' должно быть строго положительным",
                )
            )

    circ = defect.circumferential_position_deg
    if circ is not None and not (Decimal("0") <= Decimal(str(circ)) < Decimal("360")):
        violations.append(
            (
                dw.DEFECT_CIRC_POSITION_OUT_OF_RANGE,
                "Положение по окружности вне диапазона [0, 360)",
            )
        )

    return violations


def validate_for_activation(
    defect: Defect,
    defect_type: DefectType | None,
    location_type: DefectLocationType | None,
) -> list[tuple[str, str]]:
    """Агрегированная проверка комплектности для перехода в ACTIVE (Spec §8).

    Возвращает список `(code, message)` всех нарушений. Пустой список — валидно.
    Существование ссылок (id задан, но запись не найдена) — hard-ошибка сервиса
    (`*_NOT_FOUND`) до вызова этой функции; здесь проверяется наличие id и активность.
    """
    violations: list[tuple[str, str]] = []

    # ── Тип дефекта ────────────────────────────────────────────────────────────
    if defect.defect_type_id is None:
        violations.append((dw.DEFECT_TYPE_REQUIRED, "Не задан тип дефекта"))
    elif defect_type is not None and not defect_type.is_active:
        violations.append(
            (dw.DEFECT_TYPE_INACTIVE, "Тип дефекта неактивен и не может быть назначен")
        )

    # ── Расположение ───────────────────────────────────────────────────────────
    if defect.location_type_id is None:
        violations.append(
            (dw.DEFECT_LOCATION_TYPE_REQUIRED, "Не задано расположение дефекта")
        )
    elif location_type is not None and not location_type.is_active:
        violations.append(
            (dw.DEFECT_LOCATION_TYPE_INACTIVE, "Расположение неактивно")
        )

    # ── Расположение индикации ─────────────────────────────────────────────────
    if defect.indication_location is None:
        violations.append(
            (
                dw.DEFECT_INDICATION_LOCATION_REQUIRED,
                "Не задано расположение индикации",
            )
        )
    elif (
        defect_type is not None
        and defect_type.requires_known_indication_location
        and defect.indication_location == "UNKNOWN"
    ):
        violations.append(
            (
                dw.DEFECT_INDICATION_UNKNOWN_NOT_ALLOWED,
                "Для данного типа UNKNOWN-расположение индикации недопустимо",
            )
        )

    # ── Описание ───────────────────────────────────────────────────────────────
    if (
        defect_type is not None
        and defect_type.requires_description
        and _is_blank(defect.technical_description)
    ):
        violations.append(
            (dw.DEFECT_DESCRIPTION_REQUIRED, "Требуется техническое описание")
        )

    # ── Обязательные измерения ─────────────────────────────────────────────────
    if defect_type is not None:
        for field, flag in dw.DEFECT_MEASUREMENT_REQUIRE_FLAGS.items():
            if getattr(defect_type, flag) and getattr(defect, field) is None:
                violations.append(
                    (
                        dw.DEFECT_MEASUREMENT_REQUIRED,
                        f"Требуется измерение '{field}'",
                    )
                )

    # ── Положительность измерений ──────────────────────────────────────────────
    for field in dw.DEFECT_POSITIVE_NUMERIC_FIELDS:
        value = getattr(defect, field)
        if value is not None and Decimal(str(value)) <= 0:
            violations.append(
                (
                    dw.DEFECT_MEASUREMENT_NOT_POSITIVE,
                    f"Измерение '{field}' должно быть строго положительным",
                )
            )

    # ── Положение по окружности (после нормализации — [0, 360)) ────────────────
    circ = defect.circumferential_position_deg
    if circ is not None and not (Decimal("0") <= Decimal(str(circ)) < Decimal("360")):
        violations.append(
            (
                dw.DEFECT_CIRC_POSITION_OUT_OF_RANGE,
                "Положение по окружности вне диапазона [0, 360)",
            )
        )

    # ── Положение по длине требует текст-контекст (Spec §7.9) ──────────────────
    if defect.axial_position_mm is not None and _is_blank(defect.location_description):
        violations.append(
            (
                dw.DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED,
                "Осевое положение требует пояснения датума в location_description",
            )
        )

    # ── Нормативная ссылка (Spec §7.8) ─────────────────────────────────────────
    if (
        not _is_blank(defect.standard_revision) or not _is_blank(defect.standard_clause)
    ) and _is_blank(defect.standard_document):
        violations.append(
            (
                dw.DEFECT_STANDARD_DOCUMENT_REQUIRED,
                "standard_revision/standard_clause требуют standard_document",
            )
        )

    return violations
