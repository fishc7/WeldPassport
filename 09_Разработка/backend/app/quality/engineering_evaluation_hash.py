"""Профили и вычисление контрольного хэша неревизионных источников (Task 9D-2B).

Pure hash logic (решение 9D-2B-C02): реестр версионируемых профилей значимых полей по
`source_entity_type`, каноническая сериализация и `sha256`. Состав полей выбирает
система, не пользователь (ADR-021 §2.11). Значимые поля — стабильная инженерная суть
источника; lifecycle/approvals/audit исключены, чтобы хэш не «плыл» при движении статусов.

Каноникализация Decimal (решение 9D-2B-C03): без экспоненты; незначащие нули отброшены;
разделитель «.»; `-0 → 0`; `10 == 10.0 == 10.00`.

Профили первой реализации (неревизионные): `QUALITY_FINDING@1`, `JOINT@1`. Ревизионные
источники используют `source_revision_id`, а не хэш, и здесь не обрабатываются.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.quality import engineering_evaluation_workflow as eew
from app.quality.quality_finding_models import QualityFinding

# ── Профили значимых полей (порядок = порядок сериализации) ─────────────────────
_QUALITY_FINDING_FIELDS: tuple[str, ...] = (
    "id",
    "system_code",
    "project_id",
    "joint_id",
    "origin_type",
    "initial_risk",
    "observation",
    "inspection_id",
    "method_execution_id",
    "weld_operation_id",
)
_JOINT_FIELDS: tuple[str, ...] = (
    "id",
    "project_id",
    "system_code",
    "joint_no_normalized",
    "current_document_revision_id",
    "dn_1",
    "dn_2",
    "thickness_1",
    "thickness_2",
    "material_id_1",
    "material_text_1",
    "material_id_2",
    "material_text_2",
    "weld_joint_type",
    "connection_code",
    "geometry_type",
    "required_root_method",
    "required_fill_method",
    "required_cap_method",
    "heat_treatment_required",
    "heat_treatment_type",
)

# Реестр: source_entity_type → (модель, версия, поля). Только неревизионные профили.
_PROFILES: dict[str, dict[str, Any]] = {
    "QUALITY_FINDING": {
        "model": QualityFinding,
        "version": 1,
        "fields": _QUALITY_FINDING_FIELDS,
    },
    "JOINT": {"model": Joint, "version": 1, "fields": _JOINT_FIELDS},
}


def is_known_profile(source_entity_type: str) -> bool:
    """Известен ли неревизионный профиль хэширования для типа сущности."""
    return source_entity_type in _PROFILES


def profile_version(source_entity_type: str) -> str:
    """Строка версии профиля вида `QUALITY_FINDING@1` (хранится в hash_schema_version)."""
    return f"{source_entity_type}@{_PROFILES[source_entity_type]['version']}"


def canonical_decimal(value: Decimal) -> str:
    """Каноническое строковое представление Decimal (9D-2B-C03).

    Без экспоненты, незначащие нули отброшены, разделитель «.», `-0 → 0`.
    `10 == 10.0 == 10.00` → `"10"`; `10.50 → "10.5"`.
    """
    d = Decimal(value)
    if d == 0:  # покрывает 0, 0.00, -0, -0.0
        return "0"
    return format(d.normalize(), "f")


def _normalize(value: Any) -> Any:
    """Нормализует значение поля к JSON-сериализуемому каноническому виду."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (int, str)):
        return value
    # Дат в профилях 9D-2B нет; на всякий случай — детерминированная строка.
    return str(value)


def _serialize(source_entity_type: str, entity: Any) -> str:
    """Каноническая сериализация значимых полей в стабильную строку."""
    fields = _PROFILES[source_entity_type]["fields"]
    pairs = [[f, _normalize(getattr(entity, f))] for f in fields]
    return json.dumps(pairs, ensure_ascii=False, separators=(",", ":"))


def resolve_entity(
    db: Session, source_entity_type: str, source_entity_id: UUID
) -> Any | None:
    """Возвращает исходную сущность по типу/идентификатору или None."""
    profile = _PROFILES.get(source_entity_type)
    if profile is None:
        return None
    model = profile["model"]
    return db.query(model).filter(model.id == source_entity_id).first()


def compute_source_hash(
    db: Session, *, source_entity_type: str, source_entity_id: UUID
) -> tuple[str, str]:
    """Вычисляет `(source_hash, hash_schema_version)` для неревизионного источника.

    `EVAL_SOURCE_PROFILE_UNKNOWN` — тип не имеет неревизионного профиля;
    `EVAL_SOURCE_UNAVAILABLE` — сущность не найдена.
    """
    if not is_known_profile(source_entity_type):
        raise eew.EvaluationError(
            eew.EVAL_SOURCE_PROFILE_UNKNOWN,
            f"Нет неревизионного профиля для {source_entity_type}",
        )
    entity = resolve_entity(db, source_entity_type, source_entity_id)
    if entity is None:
        raise eew.EvaluationError(
            eew.EVAL_SOURCE_UNAVAILABLE,
            f"Источник {source_entity_type}:{source_entity_id} недоступен",
        )
    payload = _serialize(source_entity_type, entity)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest, profile_version(source_entity_type)
