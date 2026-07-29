"""Pure Alembic autogenerate filtering for the canonical schema boundary."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ForeignKeyConstraint, MetaData

from app.shared.canonical_metadata import CANONICAL_SCHEMAS, canonical_metadata


PUBLIC_PLATFORM_OBJECTS: frozenset[tuple[str, str]] = frozenset(
    {("public", "alembic_version")}
)
HISTORICAL_DB_ONLY_INDEXES: frozenset[tuple[str, str, str]] = frozenset(
    {("hr", "worker_roles", "uq_hr_worker_roles_active_scope")}
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
    if type_ in _EXCLUDED_OBJECT_TYPES:
        return False

    table = _parent_table(obj, type_)
    if table is None:
        return False

    schema = getattr(table, "schema", None)
    table_name = getattr(table, "name", name)
    if table_name is not None and (schema, table_name) in PUBLIC_PLATFORM_OBJECTS:
        return False

    if (
        type_ == "index"
        and reflected
        and compare_to is None
        and (schema, table_name, name) in HISTORICAL_DB_ONLY_INDEXES
    ):
        return False

    return schema in CANONICAL_SCHEMAS


@dataclass(frozen=True)
class _ForeignKeySignature:
    source_schema: str
    source_table: str
    source_columns: tuple[str, ...]
    target_schema: str | None
    target_table: str
    target_columns: tuple[str, ...]
    ondelete: str | None
    onupdate: str | None


def _normalized_action(value: str | None) -> str | None:
    return value.upper() if value is not None else None


def _metadata_fk_signature(
    constraint: ForeignKeyConstraint,
) -> _ForeignKeySignature:
    elements = tuple(constraint.elements)
    target_tables = {element.column.table for element in elements}
    if len(target_tables) != 1:
        raise ValueError("Foreign key must target exactly one table")
    target_table = target_tables.pop()

    return _ForeignKeySignature(
        source_schema=constraint.table.schema,
        source_table=constraint.table.name,
        source_columns=tuple(element.parent.name for element in elements),
        target_schema=target_table.schema,
        target_table=target_table.name,
        target_columns=tuple(element.column.name for element in elements),
        ondelete=_normalized_action(constraint.ondelete),
        onupdate=_normalized_action(constraint.onupdate),
    )


def _reflected_fk_signature(
    schema: str,
    table_name: str,
    reflected_fk: Mapping[str, Any],
) -> _ForeignKeySignature:
    options = reflected_fk.get("options") or {}
    return _ForeignKeySignature(
        source_schema=schema,
        source_table=table_name,
        source_columns=tuple(reflected_fk["constrained_columns"]),
        target_schema=reflected_fk.get("referred_schema"),
        target_table=reflected_fk["referred_table"],
        target_columns=tuple(reflected_fk["referred_columns"]),
        ondelete=_normalized_action(options.get("ondelete")),
        onupdate=_normalized_action(options.get("onupdate")),
    )


def make_include_object(
    inspector: Any,
    metadata: MetaData = canonical_metadata,
):
    """Build an exact FK-aware filter for PostgreSQL autogenerate.

    PostgreSQL reflection normally omits a referenced schema when the target is
    visible through ``search_path``. A second reflection with
    ``postgresql_ignore_search_path`` preserves the physical target so only
    semantically identical FK pairs are suppressed.
    """
    database_fk_cache: dict[
        tuple[str, str],
        tuple[
            dict[str | None, _ForeignKeySignature],
            Counter[_ForeignKeySignature],
        ],
    ] = {}

    def database_foreign_keys(
        schema: str,
        table_name: str,
    ) -> tuple[
        dict[str | None, _ForeignKeySignature],
        Counter[_ForeignKeySignature],
    ]:
        key = (schema, table_name)
        if key not in database_fk_cache:
            reflected_fks = inspector.get_foreign_keys(
                table_name,
                schema=schema,
                postgresql_ignore_search_path=True,
            )
            signatures = [
                (
                    reflected_fk.get("name"),
                    _reflected_fk_signature(
                        schema,
                        table_name,
                        reflected_fk,
                    ),
                )
                for reflected_fk in reflected_fks
            ]
            by_name = dict(signatures)
            database_fk_cache[key] = (
                by_name,
                Counter(signature for _, signature in signatures),
            )
        return database_fk_cache[key]

    def canonical_foreign_keys(
        schema: str,
        table_name: str,
    ) -> Counter[_ForeignKeySignature]:
        table = metadata.tables.get(f"{schema}.{table_name}")
        if table is None:
            return Counter()
        return Counter(
            _metadata_fk_signature(constraint)
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        )

    def fk_aware_include_object(
        obj: Any,
        name: str | None,
        type_: str,
        reflected: bool,
        compare_to: Any | None,
    ) -> bool:
        if not include_object(obj, name, type_, reflected, compare_to):
            return False
        if type_ != "foreign_key_constraint":
            return True

        table = obj.table
        schema = table.schema
        table_name = table.name
        if schema is None:
            return True

        database_by_name, database_signatures = database_foreign_keys(
            schema,
            table_name,
        )
        canonical_signatures = canonical_foreign_keys(schema, table_name)

        if reflected:
            if name is None:
                return True
            database_signature = database_by_name.get(name)
            if database_signature is None:
                return True
            return (
                database_signatures[database_signature]
                != canonical_signatures[database_signature]
            )

        metadata_signature = _metadata_fk_signature(obj)
        return (
            database_signatures[metadata_signature]
            != canonical_signatures[metadata_signature]
        )

    return fk_aware_include_object
