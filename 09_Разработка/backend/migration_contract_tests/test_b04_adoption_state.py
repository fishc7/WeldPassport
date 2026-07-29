from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from migrations.b04.adoption_state import (
    AdoptionReport,
    AdoptionState,
    MarkerSnapshot,
    PreparedEvidence,
    canonical_report_bytes,
    classify_marker_state,
    publish_report_once,
)
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
    SCHEMA_SOURCE_COMMIT,
)


SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "baselines"
    / "canonical_baseline_v1"
    / "adoption-report.schema.json"
)
SHA256_A = "a" * 64
SHA256_B = "b" * 64
SHA256_C = "c" * 64
SHA256_D = "d" * 64
SHA256_E = "e" * 64


def _snapshot(
    *,
    public_exists: bool,
    public_versions: tuple[str, ...] = (),
    test_exists: bool,
    test_versions: tuple[str, ...] = (),
    canonical_revision_edges: tuple[tuple[str, str], ...] = (),
) -> MarkerSnapshot:
    return MarkerSnapshot(
        public_table_exists=public_exists,
        public_versions=public_versions,
        test_table_exists=test_exists,
        test_versions=test_versions,
        canonical_revision_edges=canonical_revision_edges,
    )


def _prepared() -> PreparedEvidence:
    return PreparedEvidence(
        adoption_id="b04b-adoption-001",
        database_identity=DatabaseIdentity(
            database="weldpassport",
            host="db.internal",
            port=5432,
            username="maintenance_operator",
        ),
        source_sha=SCHEMA_SOURCE_COMMIT,
        old_marker=HISTORICAL_HEAD,
        new_marker=BASELINE_REVISION,
        backup_sha256=SHA256_A,
        manifest_sha256=SHA256_B,
        fingerprint_sha256=SHA256_C,
        allowlist_sha256=SHA256_D,
        seed_sha256=SHA256_E,
        prepared_at_utc="2026-07-29T09:00:00Z",
        verification_results=(
            ("manifest_verified", True),
            ("fingerprint_verified", True),
            ("seeds_verified", True),
        ),
    )


def _report() -> AdoptionReport:
    prepared = _prepared()
    return AdoptionReport(
        adoption_id=prepared.adoption_id,
        database_identity=prepared.database_identity,
        source_sha=prepared.source_sha,
        old_marker=prepared.old_marker,
        new_marker=prepared.new_marker,
        backup_sha256=prepared.backup_sha256,
        manifest_sha256=prepared.manifest_sha256,
        fingerprint_sha256=prepared.fingerprint_sha256,
        allowlist_sha256=prepared.allowlist_sha256,
        seed_sha256=prepared.seed_sha256,
        attempt_status=AdoptionState.ACCEPTED,
        started_at_utc=prepared.prepared_at_utc,
        completed_at_utc="2026-07-29T09:05:00Z",
        verification_results=prepared.verification_results
        + (("postflight_verified", True),),
    )


def test_b04b_state_001_exact_enum_values() -> None:
    assert tuple(state.value for state in AdoptionState) == (
        "READY",
        "ALREADY_ADOPTED",
        "AMBIGUOUS",
        "COMMITTED_UNVERIFIED",
        "ACCEPTED",
    )


def test_b04b_state_002_historical_marker_only_is_ready() -> None:
    snapshot = _snapshot(
        public_exists=False,
        test_exists=True,
        test_versions=(HISTORICAL_HEAD,),
    )

    assert classify_marker_state(snapshot) is AdoptionState.READY


@pytest.mark.parametrize(
    ("public_version", "canonical_revision_edges"),
    (
        (BASELINE_REVISION, ()),
        (
            "20260801_01_after_baseline",
            ((BASELINE_REVISION, "20260801_01_after_baseline"),),
        ),
    ),
)
def test_b04b_state_003_accepted_public_marker_only_is_already_adopted(
    public_version: str,
    canonical_revision_edges: tuple[tuple[str, str], ...],
) -> None:
    snapshot = _snapshot(
        public_exists=True,
        public_versions=(public_version,),
        test_exists=False,
        canonical_revision_edges=canonical_revision_edges,
    )

    assert classify_marker_state(snapshot) is AdoptionState.ALREADY_ADOPTED


@pytest.mark.parametrize(
    "snapshot",
    (
        _snapshot(
            public_exists=True,
            public_versions=(BASELINE_REVISION,),
            test_exists=True,
            test_versions=(HISTORICAL_HEAD,),
        ),
        _snapshot(public_exists=False, test_exists=False),
        _snapshot(public_exists=True, public_versions=(), test_exists=False),
        _snapshot(public_exists=False, test_exists=True, test_versions=()),
        _snapshot(
            public_exists=True,
            public_versions=(BASELINE_REVISION, BASELINE_REVISION),
            test_exists=False,
        ),
        _snapshot(
            public_exists=False,
            test_exists=True,
            test_versions=(HISTORICAL_HEAD, HISTORICAL_HEAD),
        ),
        _snapshot(
            public_exists=True,
            public_versions=("unexpected_revision",),
            test_exists=False,
        ),
        _snapshot(
            public_exists=True,
            public_versions=("unreachable_revision",),
            test_exists=False,
            canonical_revision_edges=(
                ("unrelated_root", "unreachable_revision"),
            ),
        ),
        _snapshot(
            public_exists=True,
            public_versions=("cycle_revision",),
            test_exists=False,
            canonical_revision_edges=(
                (BASELINE_REVISION, "cycle_revision"),
                ("cycle_revision", BASELINE_REVISION),
            ),
        ),
        _snapshot(
            public_exists=False,
            test_exists=True,
            test_versions=("unexpected_revision",),
        ),
    ),
)
def test_b04b_state_004_unsafe_marker_shapes_are_ambiguous(
    snapshot: MarkerSnapshot,
) -> None:
    assert classify_marker_state(snapshot) is AdoptionState.AMBIGUOUS


def test_b04b_state_005_evidence_and_report_are_frozen() -> None:
    prepared = _prepared()
    report = _report()

    with pytest.raises(FrozenInstanceError):
        prepared.adoption_id = "replacement"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.attempt_status = AdoptionState.READY  # type: ignore[misc]


def test_b04b_state_006_report_serialization_is_canonical_and_sanitized() -> None:
    report = _report()

    raw = canonical_report_bytes(report)
    value = json.loads(raw)

    assert raw.endswith(b"\n")
    assert value == {
        "adoption_id": "b04b-adoption-001",
        "allowlist_sha256": SHA256_D,
        "attempt_status": "ACCEPTED",
        "backup_sha256": SHA256_A,
        "completed_at_utc": "2026-07-29T09:05:00Z",
        "database_identity": {
            "database": "weldpassport",
            "host": "db.internal",
            "port": 5432,
            "username": "maintenance_operator",
        },
        "fingerprint_sha256": SHA256_C,
        "manifest_sha256": SHA256_B,
        "new_marker": BASELINE_REVISION,
        "old_marker": HISTORICAL_HEAD,
        "seed_sha256": SHA256_E,
        "source_sha": SCHEMA_SOURCE_COMMIT,
        "started_at_utc": "2026-07-29T09:00:00Z",
        "verification_results": {
            "fingerprint_verified": True,
            "manifest_verified": True,
            "postflight_verified": True,
            "seeds_verified": True,
        },
    }
    assert "password" not in raw.decode("utf-8").lower()


def test_b04b_state_007_report_schema_requires_complete_closed_shape() -> None:
    schema = json.loads(SCHEMA_PATH.read_bytes())
    report = json.loads(canonical_report_bytes(_report()))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(report)
    assert schema["properties"]["attempt_status"]["enum"] == [
        "READY",
        "ALREADY_ADOPTED",
        "AMBIGUOUS",
        "COMMITTED_UNVERIFIED",
        "ACCEPTED",
    ]
    assert schema["properties"]["database_identity"]["additionalProperties"] is False
    assert "password" not in schema["properties"]["database_identity"]["properties"]


def test_b04b_state_008_accepted_report_publication_is_create_exclusive(
    tmp_path: Path,
) -> None:
    accepted = _report()
    target = publish_report_once(tmp_path, accepted)
    original = target.read_bytes()

    with pytest.raises(FileExistsError):
        publish_report_once(
            tmp_path,
            replace(
                accepted,
                attempt_status=AdoptionState.COMMITTED_UNVERIFIED,
                completed_at_utc=None,
            ),
        )

    assert target.name == "b04b-adoption-001.json"
    assert target.read_bytes() == original
