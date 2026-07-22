"""Pure contract tests for the B-03B Alembic canonical boundary."""

from __future__ import annotations

import importlib
from types import ModuleType

from sqlalchemy import Column, Index, Integer, MetaData, Table, UniqueConstraint

from app.shared.canonical_metadata import CANONICAL_SCHEMAS


def _boundary() -> ModuleType:
    return importlib.import_module("migrations.canonical_boundary")


def _table(name: str, schema: str) -> Table:
    return Table(
        name,
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("code", Integer, nullable=False),
        UniqueConstraint("code", name=f"uq_{name}_code"),
        schema=schema,
    )


def test_metadata_005_future_canonical_table_needs_no_name_list() -> None:
    """TEST-B03-METADATA-005."""
    boundary = _boundary()
    future_table = _table("future_quality_idempotency", "quality")

    assert boundary.include_name(
        future_table.name,
        "table",
        {"schema_name": future_table.schema},
    )
    assert boundary.include_object(
        future_table,
        future_table.name,
        "table",
        False,
        None,
    )
    assert not any(name.endswith("_MANAGED_TABLES") for name in vars(boundary))


def test_filter_001_includes_canonical_tables_and_children() -> None:
    """TEST-B03-FILTER-001."""
    boundary = _boundary()

    for schema in CANONICAL_SCHEMAS:
        assert boundary.include_name(schema, "schema", {})

    reflected_table = _table("unlisted_reflected_table", "engineering")
    reflected_index = Index("ix_unlisted_reflected_code", reflected_table.c.code)
    unique_constraint = next(
        constraint
        for constraint in reflected_table.constraints
        if isinstance(constraint, UniqueConstraint)
    )

    assert boundary.include_object(
        reflected_table,
        reflected_table.name,
        "table",
        True,
        None,
    )
    assert boundary.include_name(
        reflected_table.c.code.name,
        "column",
        {
            "schema_name": reflected_table.schema,
            "table_name": reflected_table.name,
        },
    )
    assert boundary.include_object(
        reflected_table.c.code,
        reflected_table.c.code.name,
        "column",
        True,
        None,
    )
    assert boundary.include_object(
        reflected_index,
        reflected_index.name,
        "index",
        True,
        None,
    )
    assert boundary.include_object(
        unique_constraint,
        unique_constraint.name,
        "unique_constraint",
        True,
        None,
    )


def test_filter_002_excludes_legacy_and_noncanonical_objects() -> None:
    """TEST-B03-FILTER-002."""
    boundary = _boundary()

    for schema in (None, "test", "public", "workforce", "pg_temp_7"):
        assert not boundary.include_name(schema, "schema", {})

    workforce_table = _table("РАБОТНИКИ", "test")
    assert not boundary.include_name(
        workforce_table.name,
        "table",
        {"schema_name": workforce_table.schema},
    )
    assert not boundary.include_object(
        workforce_table,
        workforce_table.name,
        "table",
        True,
        None,
    )
    assert not boundary.include_object(
        workforce_table.c.code,
        workforce_table.c.code.name,
        "column",
        True,
        None,
    )

    canonical_table = _table("reporting_projection", "quality")
    for object_type in ("view", "materialized_view", "sequence", "extension"):
        assert not boundary.include_object(
            canonical_table,
            canonical_table.name,
            object_type,
            True,
            None,
        )


def test_filter_003_keeps_unknown_canonical_database_table_visible() -> None:
    """TEST-B03-FILTER-003."""
    boundary = _boundary()
    unknown_table = _table("unexpected_database_table", "hr")

    assert boundary.include_name(
        unknown_table.name,
        "table",
        {"schema_name": unknown_table.schema},
    )
    assert boundary.include_object(
        unknown_table,
        unknown_table.name,
        "table",
        True,
        None,
    )


def test_filter_004_excludes_alembic_platform_markers_from_drift() -> None:
    """TEST-B03-FILTER-004."""
    boundary = _boundary()
    public_marker = _table("alembic_version", "public")
    historical_marker = _table("alembic_version", "test")

    assert boundary.CANONICAL_SCHEMAS is CANONICAL_SCHEMAS
    assert boundary.PUBLIC_PLATFORM_OBJECTS == frozenset(
        {("public", "alembic_version")}
    )

    for marker in (public_marker, historical_marker):
        assert not boundary.include_name(
            marker.name,
            "table",
            {"schema_name": marker.schema},
        )
        assert not boundary.include_object(
            marker,
            marker.name,
            "table",
            True,
            None,
        )

    other_public_table = _table("unapproved_platform_table", "public")
    assert not boundary.include_object(
        other_public_table,
        other_public_table.name,
        "table",
        True,
        None,
    )
