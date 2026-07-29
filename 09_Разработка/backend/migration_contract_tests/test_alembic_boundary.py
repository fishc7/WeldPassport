"""Pure contract tests for the B-03B Alembic canonical boundary."""

from __future__ import annotations

import importlib
from types import ModuleType

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    UniqueConstraint,
)

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


class _ForeignKeyInspector:
    def __init__(self, foreign_keys: dict[tuple[str, str], list[dict]]) -> None:
        self.foreign_keys = foreign_keys

    def get_foreign_keys(
        self,
        table_name: str,
        *,
        schema: str,
        postgresql_ignore_search_path: bool,
    ) -> list[dict]:
        assert postgresql_ignore_search_path is True
        return self.foreign_keys.get((schema, table_name), [])


def _foreign_key_pair(
    *,
    metadata_ondelete: str = "RESTRICT",
    metadata_onupdate: str | None = None,
) -> tuple[MetaData, ForeignKeyConstraint, ForeignKeyConstraint]:
    reflected_metadata = MetaData()
    Table("projects", reflected_metadata, Column("id", Integer, primary_key=True))
    reflected_table = Table(
        "documents",
        reflected_metadata,
        Column("project_id", Integer),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="documents_project_id_fkey",
            ondelete=metadata_ondelete,
            onupdate=metadata_onupdate,
        ),
        schema="engineering",
    )

    canonical_metadata = MetaData()
    Table(
        "projects",
        canonical_metadata,
        Column("id", Integer, primary_key=True),
        schema="project",
    )
    canonical_table = Table(
        "documents",
        canonical_metadata,
        Column("project_id", Integer),
        ForeignKeyConstraint(
            ["project_id"],
            ["project.projects.id"],
            ondelete=metadata_ondelete,
            onupdate=metadata_onupdate,
        ),
        schema="engineering",
    )

    reflected_fk = next(
        constraint
        for constraint in reflected_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )
    canonical_fk = next(
        constraint
        for constraint in canonical_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )
    return canonical_metadata, reflected_fk, canonical_fk


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


def test_filter_005_excludes_only_governed_historical_partial_index() -> None:
    boundary = _boundary()
    worker_roles = _table("worker_roles", "hr")
    governed_index = Index(
        "uq_hr_worker_roles_active_scope",
        worker_roles.c.code,
        unique=True,
    )

    assert not boundary.include_object(
        governed_index,
        governed_index.name,
        "index",
        True,
        None,
    )

    for schema, table_name, index_name in (
        ("quality", "worker_roles", governed_index.name),
        ("hr", "other_table", governed_index.name),
        ("hr", "worker_roles", "uq_hr_worker_roles_other"),
    ):
        table = _table(table_name, schema)
        other_index = Index(index_name, table.c.code, unique=True)
        assert boundary.include_object(
            other_index,
            other_index.name,
            "index",
            True,
            None,
        )


def test_fk_comparison_001_suppresses_schema_qualification_artifact() -> None:
    boundary = _boundary()
    metadata, reflected_fk, canonical_fk = _foreign_key_pair()
    inspector = _ForeignKeyInspector(
        {
            ("engineering", "documents"): [
                {
                    "name": "documents_project_id_fkey",
                    "constrained_columns": ["project_id"],
                    "referred_schema": "project",
                    "referred_table": "projects",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "RESTRICT"},
                }
            ]
        }
    )
    include_object = boundary.make_include_object(inspector, metadata)

    assert not include_object(
        reflected_fk,
        reflected_fk.name,
        "foreign_key_constraint",
        True,
        None,
    )
    assert not include_object(
        canonical_fk,
        canonical_fk.name,
        "foreign_key_constraint",
        False,
        None,
    )


def test_fk_comparison_002_keeps_real_fk_drift_visible() -> None:
    boundary = _boundary()
    metadata, reflected_fk, canonical_fk = _foreign_key_pair()

    drift_variants = (
        {
            "constrained_columns": ["other_project_id"],
            "referred_schema": "project",
            "referred_table": "projects",
            "referred_columns": ["id"],
            "options": {"ondelete": "RESTRICT"},
        },
        {
            "constrained_columns": ["project_id"],
            "referred_schema": "other_project",
            "referred_table": "projects",
            "referred_columns": ["id"],
            "options": {"ondelete": "RESTRICT"},
        },
        {
            "constrained_columns": ["project_id"],
            "referred_schema": "project",
            "referred_table": "other_projects",
            "referred_columns": ["id"],
            "options": {"ondelete": "RESTRICT"},
        },
        {
            "constrained_columns": ["project_id"],
            "referred_schema": "project",
            "referred_table": "projects",
            "referred_columns": ["other_id"],
            "options": {"ondelete": "RESTRICT"},
        },
        {
            "constrained_columns": ["project_id"],
            "referred_schema": "project",
            "referred_table": "projects",
            "referred_columns": ["id"],
            "options": {"ondelete": "CASCADE"},
        },
        {
            "constrained_columns": ["project_id"],
            "referred_schema": "project",
            "referred_table": "projects",
            "referred_columns": ["id"],
            "options": {"ondelete": "RESTRICT", "onupdate": "CASCADE"},
        },
    )

    for variant in drift_variants:
        inspector = _ForeignKeyInspector(
            {
                ("engineering", "documents"): [
                    {"name": "documents_project_id_fkey", **variant}
                ]
            }
        )
        include_object = boundary.make_include_object(inspector, metadata)

        assert include_object(
            reflected_fk,
            reflected_fk.name,
            "foreign_key_constraint",
            True,
            None,
        )
        assert include_object(
            canonical_fk,
            canonical_fk.name,
            "foreign_key_constraint",
            False,
            None,
        )


def test_fk_comparison_003_keeps_missing_or_extra_fk_visible() -> None:
    boundary = _boundary()
    metadata, reflected_fk, canonical_fk = _foreign_key_pair()
    empty_inspector = _ForeignKeyInspector({})
    include_object = boundary.make_include_object(empty_inspector, metadata)

    assert include_object(
        canonical_fk,
        canonical_fk.name,
        "foreign_key_constraint",
        False,
        None,
    )

    metadata_without_fk = MetaData()
    Table(
        "documents",
        metadata_without_fk,
        Column("project_id", Integer),
        schema="engineering",
    )
    database_inspector = _ForeignKeyInspector(
        {
            ("engineering", "documents"): [
                {
                    "name": "documents_project_id_fkey",
                    "constrained_columns": ["project_id"],
                    "referred_schema": "project",
                    "referred_table": "projects",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "RESTRICT"},
                }
            ]
        }
    )
    include_object = boundary.make_include_object(
        database_inspector,
        metadata_without_fk,
    )

    assert include_object(
        reflected_fk,
        reflected_fk.name,
        "foreign_key_constraint",
        True,
        None,
    )


def test_fk_comparison_004_keeps_multiplicity_drift_visible() -> None:
    boundary = _boundary()
    metadata, reflected_fk, canonical_fk = _foreign_key_pair()
    database_fk = {
        "constrained_columns": ["project_id"],
        "referred_schema": "project",
        "referred_table": "projects",
        "referred_columns": ["id"],
        "options": {"ondelete": "RESTRICT"},
    }
    inspector = _ForeignKeyInspector(
        {
            ("engineering", "documents"): [
                {"name": "documents_project_id_fkey", **database_fk},
                {"name": "documents_project_id_duplicate_fkey", **database_fk},
            ]
        }
    )
    include_object = boundary.make_include_object(inspector, metadata)

    assert include_object(
        reflected_fk,
        reflected_fk.name,
        "foreign_key_constraint",
        True,
        None,
    )
    assert include_object(
        canonical_fk,
        canonical_fk.name,
        "foreign_key_constraint",
        False,
        None,
    )
