"""Pure contract tests for the B-03A canonical metadata boundary."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

from app.shared.db import Base


EXPECTED_CANONICAL_SCHEMAS = frozenset(
    {"hr", "welding", "project", "engineering", "quality"}
)
EXPECTED_CANONICAL_MODEL_MODULES = (
    "app.hr.models",
    "app.welding.models",
    "app.projects.models",
    "app.engineering.models",
    "app.engineering.import_models",
    "app.quality.models",
    "app.quality.execution_models",
    "app.quality.quality_finding_models",
    "app.quality.engineering_evaluation_models",
    "app.quality.defect_models",
    "app.quality.defect_disposition_models",
)
CANONICAL_PACKAGE_NAMES = ("hr", "welding", "projects", "engineering", "quality")


def _provider() -> ModuleType:
    return importlib.import_module("app.shared.canonical_metadata")


def _discover_model_modules() -> set[str]:
    app_dir = Path(__file__).resolve().parents[1] / "app"
    discovered: set[str] = set()

    for package_name in CANONICAL_PACKAGE_NAMES:
        package_dir = app_dir / package_name
        candidates = set(package_dir.glob("*_models.py"))
        models_module = package_dir / "models.py"
        if models_module.is_file():
            candidates.add(models_module)

        discovered.update(
            f"app.{package_name}.{path.stem}" for path in candidates
        )

    return discovered


def test_metadata_001_uses_base_metadata_and_exact_canonical_schemas() -> None:
    """TEST-B03-METADATA-001."""
    provider = _provider()

    assert provider.canonical_metadata is Base.metadata
    assert provider.CANONICAL_SCHEMAS == EXPECTED_CANONICAL_SCHEMAS
    assert {
        table.schema for table in provider.canonical_metadata.tables.values()
    } == EXPECTED_CANONICAL_SCHEMAS


def test_metadata_002_excludes_workforce_and_test_schema() -> None:
    """TEST-B03-METADATA-002."""
    provider = _provider()

    assert "app.workforce.models" not in provider.CANONICAL_MODEL_MODULES
    assert "app.workforce.models" not in sys.modules
    assert "test" not in provider.CANONICAL_SCHEMAS
    assert all(
        table.schema in EXPECTED_CANONICAL_SCHEMAS
        for table in provider.canonical_metadata.tables.values()
    )


def test_metadata_003_registry_matches_filesystem_and_has_69_tables() -> None:
    """TEST-B03-METADATA-003."""
    provider = _provider()

    assert provider.CANONICAL_MODEL_MODULES == EXPECTED_CANONICAL_MODEL_MODULES
    assert len(provider.CANONICAL_MODEL_MODULES) == 11
    assert set(provider.CANONICAL_MODEL_MODULES) == _discover_model_modules()
    assert len(provider.canonical_metadata.tables) == 69
    assert all(
        table.schema and table.key == f"{table.schema}.{table.name}"
        for table in provider.canonical_metadata.tables.values()
    )


def test_metadata_004_foreign_keys_resolve_inside_canonical_metadata() -> None:
    """TEST-B03-METADATA-004."""
    provider = _provider()
    metadata = provider.canonical_metadata

    for table in metadata.sorted_tables:
        for foreign_key in table.foreign_keys:
            target_table = foreign_key.column.table
            assert target_table.schema in EXPECTED_CANONICAL_SCHEMAS, (
                f"{table.key}: FK {foreign_key.target_fullname} targets "
                f"noncanonical schema {target_table.schema!r}"
            )
            assert target_table.key in metadata.tables, (
                f"{table.key}: FK target {target_table.key} is absent from metadata"
            )
            assert target_table.metadata is metadata
