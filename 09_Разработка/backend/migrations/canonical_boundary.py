"""Pure Alembic autogenerate filtering for the canonical schema boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.canonical_metadata import CANONICAL_SCHEMAS


PUBLIC_PLATFORM_OBJECTS: frozenset[tuple[str, str]] = frozenset(
    {("public", "alembic_version")}
)

_EXCLUDED_OBJECT_TYPES = frozenset(
    {"view", "materialized_view", "sequence", "extension"}
)


def include_name(
    name: str | None,
    type_: str,
    parent_names: Mapping[str, str | None],
) -> bool:
    """Limit reflection to names owned by the canonical schema boundary."""
    if type_ == "schema":
        return name in CANONICAL_SCHEMAS

    if type_ in _EXCLUDED_OBJECT_TYPES:
        return False

    schema = parent_names.get("schema_name")
    if type_ == "table":
        if name is not None and (schema, name) in PUBLIC_PLATFORM_OBJECTS:
            return False
        return schema in CANONICAL_SCHEMAS

    if parent_names.get("table_name") is None:
        return False
    return schema in CANONICAL_SCHEMAS


def _parent_table(obj: Any, type_: str) -> Any | None:
    if type_ == "table":
        return obj
    return getattr(obj, "table", None)


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any | None,
) -> bool:
    """Keep canonical objects visible and reject objects outside the boundary."""
    del reflected, compare_to

    if type_ in _EXCLUDED_OBJECT_TYPES:
        return False

    table = _parent_table(obj, type_)
    if table is None:
        return False

    schema = getattr(table, "schema", None)
    table_name = getattr(table, "name", name)
    if table_name is not None and (schema, table_name) in PUBLIC_PLATFORM_OBJECTS:
        return False

    return schema in CANONICAL_SCHEMAS
