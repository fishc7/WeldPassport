"""Pure contracts for the B-04 frozen quality seed manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import migrations.b04.seeds as seeds


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "baselines"
    / "canonical_baseline_v1"
    / "seed-manifest.json"
)
REQUIRES_FIELDS = (
    "requires_length",
    "requires_width",
    "requires_height",
    "requires_depth",
    "requires_area",
    "requires_quantity",
    "requires_known_indication_location",
    "requires_description",
)


def _tables(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    tables = manifest["tables"]
    assert isinstance(tables, list)
    return {str(table["name"]): table for table in tables if isinstance(table, dict)}


def test_b04_seeds_001_freezes_all_accepted_rows_with_exact_anchors() -> None:
    assert len(seeds.EXPECTED_DEFECT_TYPES) == 8
    assert len(seeds.EXPECTED_DEFECT_LOCATION_TYPES) == 7

    defect_types = {row["code"]: row for row in seeds.EXPECTED_DEFECT_TYPES}
    locations = {row["code"]: row for row in seeds.EXPECTED_DEFECT_LOCATION_TYPES}
    assert list(defect_types) == [
        "CRACK",
        "LACK_OF_FUSION",
        "LACK_OF_PENETRATION",
        "POROSITY",
        "SLAG_INCLUSION",
        "UNDERCUT",
        "BURN_THROUGH",
        "OTHER",
    ]
    assert list(locations) == [
        "WELD_METAL",
        "FUSION_LINE",
        "HEAT_AFFECTED_ZONE",
        "BASE_METAL",
        "ROOT",
        "FACE",
        "OTHER",
    ]
    assert [
        (row["id"], row["code"], row["name"], row["category"])
        for row in seeds.EXPECTED_DEFECT_TYPES
    ] == [
        ("e854686d-bbe4-52f3-86bc-b77b56b56163", "CRACK", "Трещина", None),
        ("806d5533-d0d3-58dc-815d-2184c2f2e1a7", "LACK_OF_FUSION", "Непровар (несплавление)", None),
        ("bbefdff5-e705-5d4c-b462-c91497e2a411", "LACK_OF_PENETRATION", "Неполный провар корня", None),
        ("e47f0cae-1e0b-5c32-8761-2293aad5c82d", "POROSITY", "Пористость", None),
        ("e6c09ffc-98ed-5bba-b964-dfe7dd87acd1", "SLAG_INCLUSION", "Шлаковое включение", None),
        ("8eb9b942-8eaa-58bc-b536-dffa43916b25", "UNDERCUT", "Подрез", None),
        ("9c3c8d1a-3be0-5734-872e-7a46b713e320", "BURN_THROUGH", "Прожог", None),
        ("b0a460c4-c9f2-51e9-a493-b34acd3930da", "OTHER", "Иное (уточняется описанием)", None),
    ]
    assert [
        (row["id"], row["code"], row["name"])
        for row in seeds.EXPECTED_DEFECT_LOCATION_TYPES
    ] == [
        ("fba998ec-5405-5b87-8076-c6b121d38660", "WELD_METAL", "Металл шва"),
        ("07d1fe14-ca81-5923-b192-39de7ea27587", "FUSION_LINE", "Линия сплавления"),
        ("24226093-0a41-5e82-8d39-b0d7681b429e", "HEAT_AFFECTED_ZONE", "Зона термического влияния"),
        ("9bcfd7bd-28ec-5aa0-a833-bcf7cff08d57", "BASE_METAL", "Основной металл"),
        ("11d6d763-e0e0-5b2b-bfa9-700f39787f94", "ROOT", "Корень шва"),
        ("4ced7c47-fb22-5ba5-827a-72649d02dc1f", "FACE", "Лицевая сторона шва"),
        ("1f9e81a9-57af-5e88-b312-1f2f4b239c55", "OTHER", "Иное"),
    ]
    assert defect_types["CRACK"]["id"] == "e854686d-bbe4-52f3-86bc-b77b56b56163"
    assert defect_types["OTHER"]["id"] == "b0a460c4-c9f2-51e9-a493-b34acd3930da"
    assert locations["WELD_METAL"]["id"] == "fba998ec-5405-5b87-8076-c6b121d38660"
    assert locations["OTHER"]["id"] == "1f9e81a9-57af-5e88-b312-1f2f4b239c55"

    assert len({row["id"] for row in (*seeds.EXPECTED_DEFECT_TYPES, *seeds.EXPECTED_DEFECT_LOCATION_TYPES)}) == 15
    assert len({row["code"] for row in seeds.EXPECTED_DEFECT_TYPES}) == 8
    assert len({row["code"] for row in seeds.EXPECTED_DEFECT_LOCATION_TYPES}) == 7
    for row in seeds.EXPECTED_DEFECT_TYPES:
        assert set(row) == {"id", "code", "name", "category", *REQUIRES_FIELDS}
        assert row["category"] is None
        assert all(isinstance(row[field], bool) for field in REQUIRES_FIELDS)
        assert row["requires_description"] is (row["code"] == "OTHER")


def test_b04_seeds_002_manifest_is_canonical_and_matches_checked_artifact() -> None:
    manifest = seeds.seed_manifest()
    tables = _tables(manifest)

    assert manifest["format_version"] == 1
    assert manifest["policy"] == {
        "kind": "exact_rows",
        "excluded_columns": ["created_at", "updated_at"],
    }
    assert [(table["schema"], table["name"]) for table in manifest["tables"]] == [
        ("quality", "defect_types"),
        ("quality", "defect_location_types"),
    ]
    assert tables["defect_types"]["rows"] == [dict(row) for row in seeds.EXPECTED_DEFECT_TYPES]
    assert tables["defect_location_types"]["rows"] == [
        dict(row) for row in seeds.EXPECTED_DEFECT_LOCATION_TYPES
    ]

    expected_bytes = seeds.canonical_seed_manifest_bytes(manifest)
    assert expected_bytes == ARTIFACT_PATH.read_bytes()
    assert expected_bytes.endswith(b"\n")
    assert b"\r\n" not in expected_bytes
    assert seeds.seed_digest() == hashlib.sha256(expected_bytes).hexdigest()


def test_b04_seeds_003_public_literals_are_immutable_and_manifest_has_no_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_digest = seeds.seed_digest()
    row = seeds.EXPECTED_DEFECT_TYPES[0]
    original_name = row["name"]
    try:
        with pytest.raises(TypeError):
            row["name"] = "Изменённое имя"
    finally:
        if isinstance(row, dict):
            row["name"] = original_name

    policy = seeds.SEED_MANIFEST_POLICY
    original_kind = policy["kind"]
    try:
        with pytest.raises(TypeError):
            policy["kind"] = "different_policy"
    finally:
        if isinstance(policy, dict):
            policy["kind"] = original_kind

    assert seeds.SEED_MANIFEST_POLICY["excluded_columns"] == (
        "created_at",
        "updated_at",
    )
    exclusions = seeds.SEED_MANIFEST_POLICY["excluded_columns"]
    original_exclusions = tuple(exclusions)
    try:
        with pytest.raises(TypeError):
            exclusions[0] = "another_audit_column"
    finally:
        if isinstance(exclusions, list):
            exclusions[:] = original_exclusions

    manifest = seeds.seed_manifest()
    manifest["policy"]["excluded_columns"].append("another_audit_column")
    manifest["tables"][0]["rows"][0]["name"] = "Изменённое имя"
    assert seeds.seed_manifest()["policy"] == {
        "kind": "exact_rows",
        "excluded_columns": ["created_at", "updated_at"],
    }
    assert seeds.seed_digest() == original_digest

    with pytest.raises(seeds.SeedManifestError, match="B04-SEEDS-MANIFEST-DRIFT"):
        seeds.canonical_seed_manifest_bytes(manifest)

    monkeypatch.setattr(
        seeds,
        "EXPECTED_DEFECT_TYPES",
        ({**dict(seeds.EXPECTED_DEFECT_TYPES[0]), "name": "Изменённое имя"},),
    )
    assert seeds.seed_digest() == original_digest


def test_b04_seeds_004_generation_is_byte_identical(
    tmp_path: Path,
) -> None:
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"
    seeds.write_seed_manifest(first_output)
    seeds.write_seed_manifest(second_output)
    assert first_output.read_bytes() == second_output.read_bytes() == ARTIFACT_PATH.read_bytes()


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        (
            lambda: (
                *seeds.EXPECTED_DEFECT_TYPES[:-1],
                dict(seeds.EXPECTED_DEFECT_TYPES[0]),
            ),
            "B04-SEEDS-DUPLICATE-ID",
        ),
        (
            lambda: tuple(
                {
                    **row,
                    "requires_length": "false",
                }
                if row["code"] == "CRACK"
                else dict(row)
                for row in seeds.EXPECTED_DEFECT_TYPES
            ),
            "B04-SEEDS-DEFECT-TYPE-VALUES",
        ),
    ],
)
def test_b04_seeds_005_invalid_governed_rows_fail_closed_for_candidate_validation(
    rows: object, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = seeds.seed_manifest()
    candidate["tables"][0]["rows"] = [dict(row) for row in rows()]

    with pytest.raises(seeds.SeedManifestError, match=error):
        seeds.validate_seed_manifest(candidate)
    with pytest.raises(seeds.SeedManifestError, match=error):
        seeds.canonical_seed_manifest_bytes(candidate)
