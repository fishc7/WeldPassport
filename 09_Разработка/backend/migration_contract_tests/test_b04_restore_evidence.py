from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Mapping

import pytest

from migrations.b04.manifest import canonical_json_bytes
from migrations.b04.restore_evidence import (
    RESTORE_EXPECTED_ARTIFACTS,
    RestoreEvidenceError,
    RestoreEvidenceStatus,
    assert_typed_equivalence,
    build_typed_equivalence_map,
    build_accepted_restore_index,
    build_pending_restore_index,
    resolve_restore_authorizing_evidence,
    validate_equivalence_map,
    validate_restore_contract,
    validate_restore_evidence_index,
    validate_restore_report,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (
    BACKEND_ROOT / "migrations" / "baselines" / "canonical_baseline_v1"
)
RESTORE_INDEX = ARTIFACT_ROOT / "restore-evidence-index.json"
LIVE_INDEX = ARTIFACT_ROOT / "evidence-index.json"
LIVE_DIGEST = "e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a"
IMPLEMENTATION_SHA = "1" * 40
SOURCE_SHA = "6c56f99edbd4e7346264ee14658d2076b5fd0775"
HISTORICAL_MARKER = "20260724_27_qd_rbac_sod"
LIVE_ARTIFACT_SHA256 = {
    "contract.json": "ecbc45af017679500e020f1624840e1d0b9abb835195b841a77ab34cf5ef8567",
    "expected-fingerprint.json": LIVE_DIGEST,
    "expected-fingerprint.sha256": "bf7595ecb8eb52b80baa6eb32eb6351cb87f346e58fbc30898abb8ba67564440",
    "verification-report.json": "f2ab657c702852d68e2c58620faab1d56434088bbbab63307ded27a39d1b8c17",
}
ACTUAL_LIVE_FINGERPRINT = json.loads(
    (
        ARTIFACT_ROOT
        / "postgresql-18"
        / "expected-fingerprint.json"
    ).read_bytes()
)


def _empty_index() -> dict[str, object]:
    return {
        "format_version": 1,
        "baseline_id": "canonical_baseline_v1",
        "live_evidence_id": "postgresql-18-fingerprint-v2",
        "evidence_sets": [],
    }


def _copy_live_evidence_only(root: Path) -> Path:
    live_dir = root / "postgresql-18"
    live_dir.mkdir()
    for name in LIVE_ARTIFACT_SHA256:
        source = ARTIFACT_ROOT / "postgresql-18" / name
        target = live_dir / name
        if source.is_symlink() or not source.is_file() or target.exists():
            raise AssertionError("B04R test fixture live artifact boundary")
        shutil.copy2(source, target)
    if (live_dir / "restore-roundtrip-v1").exists():
        raise AssertionError("B04R test fixture inherited restore evidence")
    return live_dir


def _diff_fingerprints() -> tuple[dict[str, object], dict[str, object]]:
    live = {
        "format_version": 2,
        "schemas": ["engineering", "hr", "project", "quality", "welding"],
        "seeds": [{"schema": "quality", "name": "defect_types", "rows": [{"code": "A"}]}],
        "sequences": [],
        "tables": [
            {
                "schema": "quality",
                "name": "defects",
                "columns": [{"name": "status", "type": "character varying"}],
                "checks": [
                    {
                        "name": "ck_defects_status",
                        "definition": "CHECK (status::text = ANY (ARRAY['OPEN'::text]))",
                    }
                ],
                "indexes": [
                    {
                        "name": "ix_defects_open",
                        "predicate": "(status::text = 'OPEN'::text)",
                        "unique": False,
                    }
                ],
            }
        ],
    }
    restored = copy.deepcopy(live)
    restored["tables"][0]["checks"][0]["definition"] = (
        "CHECK ((status)::text = ANY (ARRAY['OPEN'::text]))"
    )
    restored["tables"][0]["indexes"][0]["predicate"] = (
        "((status)::text = 'OPEN'::text)"
    )
    return live, restored


def _write_candidate_artifacts(
    root: Path,
    *,
    fingerprint_override: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    live_dir = _copy_live_evidence_only(root)
    restore_dir = live_dir / "restore-roundtrip-v1"
    restore_dir.mkdir()

    fingerprint = copy.deepcopy(
        fingerprint_override or ACTUAL_LIVE_FINGERPRINT
    )
    fingerprint_bytes = canonical_json_bytes(fingerprint)
    restore_digest = hashlib.sha256(fingerprint_bytes).hexdigest()
    sha_bytes = (
        f"{restore_digest}  expected-fingerprint.json\n".encode("ascii")
    )
    equivalence_map = {
        "format_version": 1,
        "live_evidence_id": "postgresql-18-fingerprint-v2",
        "restore_evidence_id": "postgresql-18-restore-roundtrip-v1",
        "live_fingerprint_sha256": LIVE_DIGEST,
        "restore_fingerprint_sha256": restore_digest,
        "difference_count": 0,
        "differences": [],
    }
    equivalence_bytes = canonical_json_bytes(equivalence_map)
    payload_hashes = {
        "expected-fingerprint.json": restore_digest,
        "expected-fingerprint.sha256": hashlib.sha256(sha_bytes).hexdigest(),
        "equivalence-map.json": hashlib.sha256(equivalence_bytes).hexdigest(),
    }
    contract = {
        "evidence_id": "postgresql-18-restore-roundtrip-v1",
        "baseline_id": "canonical_baseline_v1",
        "live_evidence_id": "postgresql-18-fingerprint-v2",
        "source_sha": SOURCE_SHA,
        "implementation_sha": IMPLEMENTATION_SHA,
        "postgres_major": 18,
        "server_version_num": 180003,
        "pg_dump_version": "pg_dump (PostgreSQL) 18.3",
        "pg_restore_version": "pg_restore (PostgreSQL) 18.3",
        "live_fingerprint_format_version": 2,
        "restore_fingerprint_format_version": 2,
        "live_expected_fingerprint_sha256": LIVE_DIGEST,
        "restore_expected_fingerprint_sha256": restore_digest,
        "equivalence_map_sha256": payload_hashes["equivalence-map.json"],
        "shared_artifact_sha256": dict(LIVE_ARTIFACT_SHA256),
        "payload_artifact_sha256": payload_hashes,
        "canonical_table_count": 73,
        "canonical_sequence_count": 6,
        "governed_seed_count": 15,
        "expected_artifacts": list(RESTORE_EXPECTED_ARTIFACTS),
    }
    contract_bytes = canonical_json_bytes(contract)
    report_artifact_hashes = {
        "contract.json": hashlib.sha256(contract_bytes).hexdigest(),
        **payload_hashes,
    }
    marker = {
        "historical_marker": HISTORICAL_MARKER,
        "public_marker": None,
    }
    report = {
        "status": "B04_RESTORE_ROUNDTRIP_VERIFIED",
        "evidence_id": "postgresql-18-restore-roundtrip-v1",
        "live_evidence_id": "postgresql-18-fingerprint-v2",
        "source_sha": SOURCE_SHA,
        "implementation_sha": IMPLEMENTATION_SHA,
        "postgres_major": 18,
        "server_version_num": 180003,
        "pg_dump_version": "pg_dump (PostgreSQL) 18.3",
        "pg_restore_version": "pg_restore (PostgreSQL) 18.3",
        "working_database": "WeldPassport",
        "first_restore_database": "wp_b04_r18_restore_first_disposable",
        "second_restore_database": "wp_b04_r18_restore_second_disposable",
        "backup_sha256": "2" * 64,
        "live_digest": LIVE_DIGEST,
        "first_restore_digest": restore_digest,
        "second_restore_digest": restore_digest,
        "difference_counts": {
            "check_definition_deparser_roundtrip": 0,
            "index_predicate_deparser_roundtrip": 0,
        },
        "marker_state": {
            "working": marker,
            "first_restore": marker,
            "second_restore": marker,
        },
        "canonical_table_count": 73,
        "canonical_sequence_count": 6,
        "governed_seed_count": 15,
        "artifact_sha256": report_artifact_hashes,
        "first_restore_equals_second": True,
        "live_equals_authorizing": True,
        "typed_diff_equals_map": True,
    }
    report_bytes = canonical_json_bytes(report)
    payloads = {
        "contract.json": contract_bytes,
        "expected-fingerprint.json": fingerprint_bytes,
        "expected-fingerprint.sha256": sha_bytes,
        "equivalence-map.json": equivalence_bytes,
        "verification-report.json": report_bytes,
    }
    for name, data in payloads.items():
        (restore_dir / name).write_bytes(data)

    artifact_hashes = {
        name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()
    }
    pending = build_pending_restore_index(_empty_index(), artifact_hashes)
    accepted = build_accepted_restore_index(
        pending,
        accepted_at_utc="2026-07-29T07:00:00Z",
        accepted_by="repository_owner",
        verification_report_sha256=artifact_hashes["verification-report.json"],
    )
    return accepted, report


def test_b04r_index_001_repository_candidate_is_exact_and_non_authorizing() -> None:
    raw = RESTORE_INDEX.read_bytes()
    value = json.loads(raw)
    assert raw == canonical_json_bytes(value)
    validate_restore_evidence_index(value)
    assert len(value["evidence_sets"]) == 1
    entry = value["evidence_sets"][0]
    assert entry["evidence_id"] == "postgresql-18-restore-roundtrip-v1"
    assert entry["status"] == "candidate_pending_acceptance"
    assert entry["acceptance"] is None
    assert set(entry["artifact_sha256"]) == set(RESTORE_EXPECTED_ARTIFACTS)

    restore_dir = ARTIFACT_ROOT / "postgresql-18" / "restore-roundtrip-v1"
    for name, expected in entry["artifact_sha256"].items():
        actual = hashlib.sha256((restore_dir / name).read_bytes()).hexdigest()
        assert actual == expected

    live_index = json.loads(LIVE_INDEX.read_bytes())
    with pytest.raises(RestoreEvidenceError, match="B04R-ACCEPTANCE"):
        resolve_restore_authorizing_evidence(
            value,
            ARTIFACT_ROOT,
            live_index,
        )


def test_b04r_index_002_runner_transition_stops_pending_acceptance() -> None:
    updated = build_pending_restore_index(
        _empty_index(),
        {name: "a" * 64 for name in RESTORE_EXPECTED_ARTIFACTS},
    )
    entry = updated["evidence_sets"][0]
    assert entry["status"] == "candidate_pending_acceptance"
    assert entry["acceptance"] is None
    assert RestoreEvidenceStatus(entry["status"]) is (
        RestoreEvidenceStatus.CANDIDATE_PENDING_ACCEPTANCE
    )


def test_b04r_index_003_existing_live_artifacts_are_byte_identical() -> None:
    for name, expected in LIVE_ARTIFACT_SHA256.items():
        data = (ARTIFACT_ROOT / "postgresql-18" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("top_unknown", "B04R-EVIDENCE-INDEX"),
        ("entry_unknown", "B04R-EVIDENCE-INDEX"),
        ("wrong_id", "B04R-EVIDENCE-INDEX"),
        ("wrong_major", "B04R-EVIDENCE-INDEX"),
        ("wrong_path", "B04R-EVIDENCE-INDEX"),
        ("bad_acceptance", "B04R-ACCEPTANCE"),
    ],
)
def test_b04r_index_004_rejects_invalid_structure(
    mutation: str, code: str
) -> None:
    value = build_pending_restore_index(
        _empty_index(),
        {name: "a" * 64 for name in RESTORE_EXPECTED_ARTIFACTS},
    )
    if mutation == "top_unknown":
        value["unknown"] = True
    elif mutation == "entry_unknown":
        value["evidence_sets"][0]["unknown"] = True
    elif mutation == "wrong_id":
        value["evidence_sets"][0]["evidence_id"] = "other"
    elif mutation == "wrong_major":
        value["evidence_sets"][0]["postgres_major"] = 17
    elif mutation == "wrong_path":
        value["evidence_sets"][0]["contract_path"] = "../contract.json"
    elif mutation == "bad_acceptance":
        value["evidence_sets"][0]["status"] = "active_restore_authorizing"
        value["evidence_sets"][0]["acceptance"] = {
            "accepted_at_utc": "2026-07-29T07:00:00Z",
            "accepted_by": "another_actor",
            "verification_report_sha256": "a" * 64,
        }
    with pytest.raises(RestoreEvidenceError, match=code):
        validate_restore_evidence_index(value)


def test_b04r_contract_001_exact_contract_map_and_report_validate(
    tmp_path: Path,
) -> None:
    index, report = _write_candidate_artifacts(tmp_path)
    restore_dir = tmp_path / "postgresql-18" / "restore-roundtrip-v1"
    contract = json.loads((restore_dir / "contract.json").read_bytes())
    equivalence_map = json.loads((restore_dir / "equivalence-map.json").read_bytes())
    validate_restore_contract(contract)
    validate_equivalence_map(equivalence_map)
    validate_restore_report(report)
    validate_restore_evidence_index(index)


def test_b04r_resolver_001_returns_only_physically_verified_active_set(
    tmp_path: Path,
) -> None:
    index, _ = _write_candidate_artifacts(tmp_path)
    live_index = json.loads(LIVE_INDEX.read_bytes())
    evidence = resolve_restore_authorizing_evidence(
        index,
        tmp_path,
        live_index,
    )
    assert evidence.evidence_id == "postgresql-18-restore-roundtrip-v1"
    assert evidence.status is RestoreEvidenceStatus.ACTIVE_RESTORE_AUTHORIZING
    assert evidence.acceptance is not None


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("pending", "B04R-ACCEPTANCE"),
        ("report_digest", "B04R-ACCEPTANCE"),
        ("contract_digest", "B04R-EVIDENCE-INDEX"),
        ("path_escape", "B04R-EVIDENCE-INDEX"),
    ],
)
def test_b04r_resolver_002_fails_closed(
    tmp_path: Path, mutation: str, code: str
) -> None:
    index, _ = _write_candidate_artifacts(tmp_path)
    live_index = json.loads(LIVE_INDEX.read_bytes())
    entry = index["evidence_sets"][0]
    if mutation == "pending":
        entry["status"] = "candidate_pending_acceptance"
        entry["acceptance"] = None
    elif mutation == "report_digest":
        entry["acceptance"]["verification_report_sha256"] = "0" * 64
    elif mutation == "contract_digest":
        entry["artifact_sha256"]["contract.json"] = "0" * 64
    elif mutation == "path_escape":
        entry["contract_path"] = "../contract.json"
    with pytest.raises(RestoreEvidenceError, match=code):
        resolve_restore_authorizing_evidence(index, tmp_path, live_index)


def test_b04r_resolver_003_rejects_self_consistent_unsupported_fingerprint(
    tmp_path: Path,
) -> None:
    unsupported = {
        "format_version": 2,
        "schemas": ["engineering", "hr", "project", "quality", "welding"],
        "seeds": [],
        "sequences": [],
        "tables": [],
    }
    index, _ = _write_candidate_artifacts(
        tmp_path,
        fingerprint_override=unsupported,
    )
    live_index = json.loads(LIVE_INDEX.read_bytes())
    with pytest.raises(
        RestoreEvidenceError, match="B04R-RESTORE-FINGERPRINT"
    ):
        resolve_restore_authorizing_evidence(index, tmp_path, live_index)


def test_b04r_resolver_004_physically_hashes_every_live_artifact(
    tmp_path: Path,
) -> None:
    index, _ = _write_candidate_artifacts(tmp_path)
    live_index = json.loads(LIVE_INDEX.read_bytes())
    (tmp_path / "postgresql-18" / "expected-fingerprint.sha256").write_bytes(
        b"corrupt\n"
    )
    with pytest.raises(RestoreEvidenceError, match="B04R-LIVE-EVIDENCE"):
        resolve_restore_authorizing_evidence(index, tmp_path, live_index)


def test_b04r_index_005_acceptance_builder_is_explicit_owner_only() -> None:
    pending = build_pending_restore_index(
        _empty_index(),
        {name: "a" * 64 for name in RESTORE_EXPECTED_ARTIFACTS},
    )
    with pytest.raises(RestoreEvidenceError, match="B04R-ACCEPTANCE"):
        build_accepted_restore_index(
            pending,
            accepted_at_utc="2026-07-29T07:00:00Z",
            accepted_by="runner",
            verification_report_sha256="a" * 64,
        )


def test_b04r_diff_001_accepts_only_exact_expression_leaves() -> None:
    live, restored = _diff_fingerprints()
    result = build_typed_equivalence_map(live, restored)
    assert result["difference_count"] == 2
    assert [item["kind"] for item in result["differences"]] == [
        "check_definition_deparser_roundtrip",
        "index_predicate_deparser_roundtrip",
    ]
    assert result["differences"][0]["schema"] == "quality"
    assert result["differences"][0]["table"] == "defects"
    assert result["differences"][0]["object_name"] == "ck_defects_status"
    assert result["differences"][0]["live_json_pointer"] == (
        "/tables/0/checks/0/definition"
    )
    assert result["differences"][1]["live_json_pointer"] == (
        "/tables/0/indexes/0/predicate"
    )
    assert_typed_equivalence(live, restored, result)


@pytest.mark.parametrize(
    "mutation",
    ["column_type", "missing_check", "extra_index", "index_unique", "seed_value"],
)
def test_b04r_diff_002_rejects_every_non_expression_difference(
    mutation: str,
) -> None:
    live, restored = _diff_fingerprints()
    if mutation == "column_type":
        restored["tables"][0]["columns"][0]["type"] = "text"
    elif mutation == "missing_check":
        restored["tables"][0]["checks"] = []
    elif mutation == "extra_index":
        restored["tables"][0]["indexes"].append(
            {"name": "ix_extra", "predicate": None, "unique": False}
        )
    elif mutation == "index_unique":
        restored["tables"][0]["indexes"][0]["unique"] = True
    elif mutation == "seed_value":
        restored["seeds"][0]["rows"][0]["code"] = "B"
    with pytest.raises(RestoreEvidenceError, match="B04R-DIFF-KIND"):
        build_typed_equivalence_map(live, restored)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "pointer", "wildcard", "live_hash", "restore_hash", "identity"],
)
def test_b04r_diff_003_rejects_mutated_map(mutation: str) -> None:
    live, restored = _diff_fingerprints()
    equivalence = build_typed_equivalence_map(live, restored)
    if mutation == "missing":
        equivalence["differences"].pop()
        equivalence["difference_count"] = 1
    elif mutation == "extra":
        equivalence["differences"].append(copy.deepcopy(equivalence["differences"][0]))
        equivalence["differences"][-1]["object_name"] = "other"
        equivalence["difference_count"] = 3
    elif mutation == "pointer":
        equivalence["differences"][0]["live_json_pointer"] = (
            "/tables/0/checks/1/definition"
        )
    elif mutation == "wildcard":
        equivalence["differences"][0]["live_json_pointer"] = (
            "/tables/*/checks/0/definition"
        )
    elif mutation == "live_hash":
        equivalence["differences"][0]["live_expression_sha256"] = "0" * 64
    elif mutation == "restore_hash":
        equivalence["differences"][0]["restore_expression_sha256"] = "0" * 64
    elif mutation == "identity":
        equivalence["differences"][0]["object_name"] = "ck_other"
    with pytest.raises(RestoreEvidenceError, match="B04R-DIFF-MAP"):
        assert_typed_equivalence(live, restored, equivalence)


def test_b04r_diff_004_rejects_duplicate_map_identity() -> None:
    live, restored = _diff_fingerprints()
    equivalence = build_typed_equivalence_map(live, restored)
    equivalence["differences"].append(copy.deepcopy(equivalence["differences"][0]))
    equivalence["difference_count"] = 3
    with pytest.raises(RestoreEvidenceError, match="B04R-DIFF-MAP"):
        assert_typed_equivalence(live, restored, equivalence)
