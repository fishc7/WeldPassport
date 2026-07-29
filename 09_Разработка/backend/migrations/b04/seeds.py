"""Frozen, fail-closed B-04 seed manifest for the quality reference data."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import UUID

from migrations.b04.manifest import canonical_json_bytes, sha256_hex


SEED_MANIFEST_FORMAT_VERSION = 1
SEED_MANIFEST_POLICY: Mapping[str, object] = MappingProxyType(
    {
        "kind": "exact_rows",
        "excluded_columns": ("created_at", "updated_at"),
    }
)
_REQUIRES_FIELDS = (
    "requires_length",
    "requires_width",
    "requires_height",
    "requires_depth",
    "requires_area",
    "requires_quantity",
    "requires_known_indication_location",
    "requires_description",
)


class SeedManifestError(ValueError):
    """The frozen seed rows violate the B-04 exact-row contract."""


# These 15 rows are deliberately literal: B-04 must not depend on runtime seed code.
def _freeze_rows(
    rows: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    return tuple(MappingProxyType(dict(row)) for row in rows)


EXPECTED_DEFECT_TYPES: tuple[Mapping[str, object], ...] = _freeze_rows((
    {
        "id": "e854686d-bbe4-52f3-86bc-b77b56b56163",
        "code": "CRACK",
        "name": "Трещина",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "806d5533-d0d3-58dc-815d-2184c2f2e1a7",
        "code": "LACK_OF_FUSION",
        "name": "Непровар (несплавление)",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "bbefdff5-e705-5d4c-b462-c91497e2a411",
        "code": "LACK_OF_PENETRATION",
        "name": "Неполный провар корня",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "e47f0cae-1e0b-5c32-8761-2293aad5c82d",
        "code": "POROSITY",
        "name": "Пористость",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "e6c09ffc-98ed-5bba-b964-dfe7dd87acd1",
        "code": "SLAG_INCLUSION",
        "name": "Шлаковое включение",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "8eb9b942-8eaa-58bc-b536-dffa43916b25",
        "code": "UNDERCUT",
        "name": "Подрез",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "9c3c8d1a-3be0-5734-872e-7a46b713e320",
        "code": "BURN_THROUGH",
        "name": "Прожог",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": False,
    },
    {
        "id": "b0a460c4-c9f2-51e9-a493-b34acd3930da",
        "code": "OTHER",
        "name": "Иное (уточняется описанием)",
        "category": None,
        "requires_length": False,
        "requires_width": False,
        "requires_height": False,
        "requires_depth": False,
        "requires_area": False,
        "requires_quantity": False,
        "requires_known_indication_location": False,
        "requires_description": True,
    },
))

EXPECTED_DEFECT_LOCATION_TYPES: tuple[Mapping[str, object], ...] = _freeze_rows((
    {"id": "fba998ec-5405-5b87-8076-c6b121d38660", "code": "WELD_METAL", "name": "Металл шва"},
    {"id": "07d1fe14-ca81-5923-b192-39de7ea27587", "code": "FUSION_LINE", "name": "Линия сплавления"},
    {
        "id": "24226093-0a41-5e82-8d39-b0d7681b429e",
        "code": "HEAT_AFFECTED_ZONE",
        "name": "Зона термического влияния",
    },
    {"id": "9bcfd7bd-28ec-5aa0-a833-bcf7cff08d57", "code": "BASE_METAL", "name": "Основной металл"},
    {"id": "11d6d763-e0e0-5b2b-bfa9-700f39787f94", "code": "ROOT", "name": "Корень шва"},
    {"id": "4ced7c47-fb22-5ba5-827a-72649d02dc1f", "code": "FACE", "name": "Лицевая сторона шва"},
    {"id": "1f9e81a9-57af-5e88-b312-1f2f4b239c55", "code": "OTHER", "name": "Иное"},
))

# Generation and digest use these immutable accepted references, never mutable callers.
_ACCEPTED_DEFECT_TYPES = EXPECTED_DEFECT_TYPES
_ACCEPTED_DEFECT_LOCATION_TYPES = EXPECTED_DEFECT_LOCATION_TYPES


def _is_lowercase_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _validate_rows(
    defect_types: Sequence[Mapping[str, object]],
    location_types: Sequence[Mapping[str, object]],
) -> None:
    if len(defect_types) != 8 or len(location_types) != 7:
        raise SeedManifestError("B04-SEEDS-ROW-COUNT")

    defect_type_fields = {"id", "code", "name", "category", *_REQUIRES_FIELDS}
    location_type_fields = {"id", "code", "name"}
    all_ids: list[str] = []
    for row in defect_types:
        if not isinstance(row, Mapping) or set(row) != defect_type_fields:
            raise SeedManifestError("B04-SEEDS-DEFECT-TYPE-SHAPE")
        if (
            not _is_lowercase_uuid(row["id"])
            or not isinstance(row["code"], str)
            or not row["code"]
            or not isinstance(row["name"], str)
            or not row["name"]
            or (row["category"] is not None and not isinstance(row["category"], str))
            or any(not isinstance(row[field], bool) for field in _REQUIRES_FIELDS)
            or any(
                row[field]
                for field in _REQUIRES_FIELDS
                if field != "requires_description"
            )
            or row["requires_description"] != (row["code"] == "OTHER")
        ):
            raise SeedManifestError("B04-SEEDS-DEFECT-TYPE-VALUES")
        all_ids.append(row["id"])

    for row in location_types:
        if not isinstance(row, Mapping) or set(row) != location_type_fields:
            raise SeedManifestError("B04-SEEDS-LOCATION-TYPE-SHAPE")
        if (
            not _is_lowercase_uuid(row["id"])
            or not isinstance(row["code"], str)
            or not row["code"]
            or not isinstance(row["name"], str)
            or not row["name"]
        ):
            raise SeedManifestError("B04-SEEDS-LOCATION-TYPE-VALUES")
        all_ids.append(row["id"])

    if len(set(all_ids)) != len(all_ids):
        raise SeedManifestError("B04-SEEDS-DUPLICATE-ID")
    if len({row["code"] for row in defect_types}) != len(defect_types):
        raise SeedManifestError("B04-SEEDS-DUPLICATE-DEFECT-TYPE-CODE")
    if len({row["code"] for row in location_types}) != len(location_types):
        raise SeedManifestError("B04-SEEDS-DUPLICATE-LOCATION-TYPE-CODE")


def _materialize_policy() -> dict[str, object]:
    return {
        "kind": SEED_MANIFEST_POLICY["kind"],
        "excluded_columns": list(SEED_MANIFEST_POLICY["excluded_columns"]),
    }


def validate_seed_manifest(manifest: Mapping[str, object]) -> None:
    """Validate a JSON-compatible candidate before comparing it to the frozen rows."""
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "format_version",
        "policy",
        "tables",
    }:
        raise SeedManifestError("B04-SEEDS-MANIFEST-SHAPE")
    if not isinstance(manifest["format_version"], int) or isinstance(
        manifest["format_version"], bool
    ):
        raise SeedManifestError("B04-SEEDS-MANIFEST-FORMAT")
    policy = manifest["policy"]
    if (
        not isinstance(policy, Mapping)
        or set(policy) != {"kind", "excluded_columns"}
        or not isinstance(policy["kind"], str)
        or not isinstance(policy["excluded_columns"], list)
        or any(not isinstance(column, str) for column in policy["excluded_columns"])
    ):
        raise SeedManifestError("B04-SEEDS-MANIFEST-POLICY")
    tables = manifest["tables"]
    if not isinstance(tables, list) or len(tables) != 2:
        raise SeedManifestError("B04-SEEDS-MANIFEST-TABLES")

    expected_tables = (
        ("quality", "defect_types"),
        ("quality", "defect_location_types"),
    )
    rows_by_table: dict[str, Sequence[Mapping[str, object]]] = {}
    for table, (schema, name) in zip(tables, expected_tables, strict=True):
        if (
            not isinstance(table, Mapping)
            or set(table) != {"schema", "name", "rows"}
            or table["schema"] != schema
            or table["name"] != name
            or not isinstance(table["rows"], list)
            or any(not isinstance(row, Mapping) for row in table["rows"])
        ):
            raise SeedManifestError("B04-SEEDS-MANIFEST-TABLE")
        rows_by_table[name] = table["rows"]
    _validate_rows(
        rows_by_table["defect_types"], rows_by_table["defect_location_types"]
    )


def seed_manifest() -> dict[str, object]:
    """Materialize fresh JSON-compatible data from the immutable accepted rows."""
    _validate_rows(_ACCEPTED_DEFECT_TYPES, _ACCEPTED_DEFECT_LOCATION_TYPES)
    manifest = {
        "format_version": SEED_MANIFEST_FORMAT_VERSION,
        "policy": _materialize_policy(),
        "tables": [
            {
                "schema": "quality",
                "name": "defect_types",
                "rows": [dict(row) for row in _ACCEPTED_DEFECT_TYPES],
            },
            {
                "schema": "quality",
                "name": "defect_location_types",
                "rows": [dict(row) for row in _ACCEPTED_DEFECT_LOCATION_TYPES],
            },
        ],
    }
    validate_seed_manifest(manifest)
    return manifest


def canonical_seed_manifest_bytes(manifest: Mapping[str, object] | None = None) -> bytes:
    """Return canonical bytes only after the exact-row contract is validated."""
    if manifest is not None:
        validate_seed_manifest(manifest)
        expected = seed_manifest()
        if manifest != expected:
            raise SeedManifestError("B04-SEEDS-MANIFEST-DRIFT")
    return canonical_json_bytes(seed_manifest())


def seed_digest() -> str:
    """Return SHA-256 of the exact canonical ``seed-manifest.json`` bytes."""
    return sha256_hex(canonical_seed_manifest_bytes())


def write_seed_manifest(output: Path) -> None:
    """Write the canonical artifact; repeated writes are byte-identical."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_seed_manifest_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_seed_manifest(args.output)


if __name__ == "__main__":
    main()
