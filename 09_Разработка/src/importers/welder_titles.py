"""Определение сварочных должностей для импорта ОК / табелей / 1С."""
from __future__ import annotations

WELDER_TITLES_EXACT = {
    "эл/сварщик",
    "эл/сварщик тт",
    "электросварщик",
    "электросварщик тт",
    "газосварщик",
    "газорезчик",
    "сварщик",
    "сварщик тт",
}

# Маркеры должностей, которые не являются сварщиками (ИТР, мастера, склад и т.д.).
_NON_WELDER_MARKERS = (
    "мастер",
    "прораб",
    "кладов",
    "инженер",
    "техник",
    "нормиров",
    "контрол",
    "отк",
    "кранов",
    "пто",
    "отдел кадров",
    "кадров",
    "начальник",
    "директор",
    "экономист",
    "бухгалт",
    "логист",
    "снабжен",
    "итр",
    "дефектоскоп",
    "лаборант",
    "оператор",
    "слесар",
    "монтажник",
    "электромонт",
    "токар",
    "фрезер",
    "водитель",
    "охран",
    "уборщ",
    "cook",
    "повар",
    "мед",
    "секретар",
    "диспетчер",
)


def _norm(title: str) -> str:
    return title.strip().lower().replace("ё", "е")


def is_welder_dolzhnost(title: str | None) -> bool:
    """True, если должность относится к сварщику (профиль СВАРЩИКИ нужен)."""
    if not title or not str(title).strip():
        return False
    t = _norm(str(title))
    if any(marker in t for marker in _NON_WELDER_MARKERS):
        return False
    if t in WELDER_TITLES_EXACT:
        return True
    if "сварщ" in t:
        return True
    if t.startswith("эл/") and "свар" in t:
        return True
    return False

