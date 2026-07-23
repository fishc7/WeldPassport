"""Canonical SQLAlchemy metadata boundary for migration governance."""

from __future__ import annotations

from importlib import import_module

from sqlalchemy import MetaData
from sqlalchemy.exc import NoReferencedTableError

from app.shared.db import Base


CANONICAL_SCHEMAS: frozenset[str] = frozenset(
    {"hr", "welding", "project", "engineering", "quality"}
)

CANONICAL_MODEL_MODULES: tuple[str, ...] = (
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
    "app.quality.quality_decision_models",
)

_CURRENT_CANONICAL_TABLE_COUNT = 72


for _module_name in CANONICAL_MODEL_MODULES:
    import_module(_module_name)


def validate_canonical_metadata() -> None:
    """Fail fast when registered models cross the accepted canonical boundary."""
    metadata = Base.metadata
    tables = tuple(metadata.tables.values())
    actual_schemas = frozenset(table.schema for table in tables)

    if actual_schemas != CANONICAL_SCHEMAS:
        raise RuntimeError(
            "Canonical metadata schema mismatch: "
            f"expected {sorted(CANONICAL_SCHEMAS)!r}, "
            f"got {sorted(actual_schemas, key=lambda value: value or '')!r}"
        )

    if len(tables) != _CURRENT_CANONICAL_TABLE_COUNT:
        raise RuntimeError(
            "Canonical metadata table count mismatch: "
            f"expected {_CURRENT_CANONICAL_TABLE_COUNT}, got {len(tables)}"
        )

    for table in tables:
        for foreign_key in table.foreign_keys:
            try:
                target_table = foreign_key.column.table
            except NoReferencedTableError as exc:
                raise RuntimeError(
                    f"Canonical FK {table.key} -> {foreign_key.target_fullname} "
                    "does not resolve inside canonical metadata"
                ) from exc

            if (
                target_table.schema not in CANONICAL_SCHEMAS
                or target_table.key not in metadata.tables
                or target_table.metadata is not metadata
            ):
                raise RuntimeError(
                    f"Canonical FK {table.key} -> {target_table.key} "
                    "targets outside canonical metadata"
                )


validate_canonical_metadata()
canonical_metadata: MetaData = Base.metadata
