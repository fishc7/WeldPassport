from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from migrations.b04.evidence import (
    PG16_ARTIFACT_SHA256,
    EvidenceError,
    EvidenceSet,
    EvidenceStatus,
    Pg18EvidenceContract,
    resolve_authorizing_evidence,
    validate_evidence_index,
    validate_pg18_contract,
    validate_pg18_report,
)
from migrations.b04.manifest import canonical_json_bytes


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = (
    BACKEND_ROOT / "migrations" / "baselines" / "canonical_baseline_v1"
)
INDEX_PATH = ARTIFACT_DIR / "evidence-index.json"
PG18_ID = "postgresql-18-fingerprint-v2"
PG18_ARTIFACT_NAMES = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "verification-report.json",
)


def _pending_verification_index() -> dict[str, object]:
    return {
        "baseline_id": "canonical_baseline_v1",
        "evidence_sets": [
            {
                "acceptance": None,
                "artifact_sha256": dict(PG16_ARTIFACT_SHA256),
                "contract_path": None,
                "evidence_id": "postgresql-16-fingerprint-v1",
                "fingerprint_format_version": 1,
                "postgres_major": 16,
                "status": "historical_non_authorizing",
            },
            {
                "acceptance": None,
                "artifact_sha256": {},
                "contract_path": "postgresql-18/contract.json",
                "evidence_id": PG18_ID,
                "fingerprint_format_version": 2,
                "postgres_major": 18,
                "status": "candidate_pending_verification",
            },
        ],
        "format_version": 1,
    }


def _pg18_contract() -> dict[str, object]:
    return {
        "canonical_table_count": 73,
        "evidence_id": PG18_ID,
        "expected_artifacts": list(PG18_ARTIFACT_NAMES),
        "fingerprint_format_version": 2,
        "governed_seed_count": 15,
        "implementation_sha": "a" * 40,
        "postgres_major": 18,
        "shared_artifact_sha256": dict(PG16_ARTIFACT_SHA256),
        "source_sha": "6c56f99edbd4e7346264ee14658d2076b5fd0775",
    }


def _pg18_report() -> dict[str, object]:
    digest = "d" * 64
    return {
        "baseline_database": "wp_b04_r18_baseline_disposable",
        "baseline_digest": digest,
        "canonical_table_count": 73,
        "evidence_id": PG18_ID,
        "exact_seed_count": 15,
        "fingerprint_format_version": 2,
        "governed_index": "hr.worker_roles.uq_hr_worker_roles_active_scope",
        "historical_database": "wp_b04_r18_historical_disposable",
        "historical_digest": digest,
        "implementation_sha": "a" * 40,
        "postgres_major": 18,
        "reupgrade_digest": digest,
        "server_version_num": 180003,
        "shared_artifact_sha256": dict(PG16_ARTIFACT_SHA256),
        "source_sha": "6c56f99edbd4e7346264ee14658d2076b5fd0775",
        "status": "B04A_VERIFIED",
    }


def test_b04_r18_evidence_000_report_has_exact_keys_and_rejects_unknown_keys() -> None:
    validate_pg18_report(_pg18_report())
    invalid = dict(_pg18_report(), unknown=True)

    with pytest.raises(EvidenceError, match="B04-EVIDENCE-REPORT-KEYS"):
        validate_pg18_report(invalid)


def _active_index(root: Path) -> dict[str, object]:
    value = _pending_verification_index()
    entries = value["evidence_sets"]
    assert isinstance(entries, list)
    pg18 = next(item for item in entries if item["evidence_id"] == PG18_ID)
    evidence_dir = root / "postgresql-18"
    evidence_dir.mkdir()

    contract_bytes = canonical_json_bytes(_pg18_contract())
    report_bytes = canonical_json_bytes(
        {
            "evidence_id": PG18_ID,
            "fingerprint_format_version": 2,
            "postgres_major": 18,
        }
    )
    (evidence_dir / "contract.json").write_bytes(contract_bytes)
    (evidence_dir / "verification-report.json").write_bytes(report_bytes)

    report_sha = hashlib.sha256(report_bytes).hexdigest()
    artifact_sha256 = {name: "b" * 64 for name in PG18_ARTIFACT_NAMES}
    artifact_sha256["contract.json"] = hashlib.sha256(contract_bytes).hexdigest()
    artifact_sha256["verification-report.json"] = report_sha
    pg18.update(
        {
            "acceptance": {
                "accepted_at_utc": "2026-07-28T12:00:00Z",
                "accepted_by": "repository_owner",
                "verification_report_sha256": report_sha,
            },
            "artifact_sha256": artifact_sha256,
            "status": "active_authorizing",
        }
    )
    return value


def test_b04_r18_evidence_001_pg16_artifacts_are_byte_identical() -> None:
    for name, expected in PG16_ARTIFACT_SHA256.items():
        data = (ARTIFACT_DIR / name).read_bytes()
        assert b"\r\n" not in data
        assert hashlib.sha256(data).hexdigest() == expected


def test_b04_r18_evidence_002_repository_index_is_active_authorizing() -> None:
    index_bytes = INDEX_PATH.read_bytes()
    value = json.loads(index_bytes)
    assert b"\r\n" not in index_bytes
    assert index_bytes == canonical_json_bytes(value)
    validate_evidence_index(value)
    statuses = {
        item["evidence_id"]: item["status"] for item in value["evidence_sets"]
    }
    assert statuses == {
        "postgresql-16-fingerprint-v1": "historical_non_authorizing",
        PG18_ID: "active_authorizing",
    }
    pg18 = next(
        item for item in value["evidence_sets"] if item["evidence_id"] == PG18_ID
    )
    assert pg18["acceptance"] == {
        "accepted_at_utc": "2026-07-29T05:51:15Z",
        "accepted_by": "repository_owner",
        "verification_report_sha256": (
            "f2ab657c702852d68e2c58620faab1d56434088bbbab63307ded27a39d1b8c17"
        ),
    }
    assert set(pg18["artifact_sha256"]) == set(PG18_ARTIFACT_NAMES)
    evidence_dir = ARTIFACT_DIR / "postgresql-18"
    assert {path.name for path in evidence_dir.iterdir()} == set(
        PG18_ARTIFACT_NAMES
    )
    for name, expected in pg18["artifact_sha256"].items():
        observed = hashlib.sha256((evidence_dir / name).read_bytes()).hexdigest()
        assert observed == expected
    resolved = resolve_authorizing_evidence(value, ARTIFACT_DIR)
    assert resolved.evidence_id == PG18_ID
    assert resolved.status is EvidenceStatus.ACTIVE_AUTHORIZING


def test_b04_r18_evidence_003_contract_and_models_are_typed_and_immutable() -> None:
    validate_pg18_contract(_pg18_contract())
    contract = Pg18EvidenceContract.from_mapping(_pg18_contract())
    assert contract.postgres_major == 18
    assert contract.fingerprint_format_version == 2
    assert contract.expected_artifacts == PG18_ARTIFACT_NAMES
    with pytest.raises(FrozenInstanceError):
        contract.postgres_major = 16  # type: ignore[misc]

    evidence = EvidenceSet.from_mapping(
        _pending_verification_index()["evidence_sets"][0]
    )
    assert evidence.status is EvidenceStatus.HISTORICAL_NON_AUTHORIZING
    with pytest.raises(FrozenInstanceError):
        evidence.status = EvidenceStatus.ACTIVE_AUTHORIZING  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value["evidence_sets"][0].update({"unknown": True}),
        lambda value: value["evidence_sets"].append(
            dict(value["evidence_sets"][0])
        ),
        lambda value: value["evidence_sets"][0].update(
            {
                "status": "active_authorizing",
                "acceptance": {
                    "accepted_at_utc": "2026-07-28T12:00:00Z",
                    "accepted_by": "repository_owner",
                    "verification_report_sha256": "a" * 64,
                },
            }
        ),
        lambda value: value["evidence_sets"][1].update(
            {"status": "active_authorizing"}
        ),
        lambda value: value["evidence_sets"][1].update(
            {
                "status": "active_authorizing",
                "acceptance": {
                    "accepted_at_utc": "2026-07-28T12:00:00Z",
                    "accepted_by": "another_actor",
                    "verification_report_sha256": "a" * 64,
                },
            }
        ),
    ],
    ids=[
        "unknown-index-key",
        "unknown-entry-key",
        "duplicate-evidence-id",
        "pg16-cannot-authorize",
        "active-requires-acceptance",
        "acceptance-owner-is-exact",
    ],
)
def test_b04_r18_evidence_004_rejects_invalid_index_structure(
    mutation: object,
) -> None:
    value = _pending_verification_index()
    mutation(value)  # type: ignore[operator]
    with pytest.raises(EvidenceError, match="B04-EVIDENCE-"):
        validate_evidence_index(value)


def test_b04_r18_evidence_005_rejects_more_than_one_active_set() -> None:
    value = _pending_verification_index()
    for item in value["evidence_sets"]:
        item["status"] = "active_authorizing"
        item["acceptance"] = {
            "accepted_at_utc": "2026-07-28T12:00:00Z",
            "accepted_by": "repository_owner",
            "verification_report_sha256": "a" * 64,
        }
    with pytest.raises(EvidenceError, match="B04-EVIDENCE-ACTIVE"):
        validate_evidence_index(value)


@pytest.mark.parametrize(
    ("field", "replacement", "error"),
    [
        ("acceptance", None, "B04-EVIDENCE-ACCEPTANCE"),
        (
            "accepted_by",
            "another_actor",
            "B04-EVIDENCE-ACCEPTANCE-OWNER",
        ),
    ],
)
def test_b04_r18_evidence_005a_active_acceptance_is_exact(
    tmp_path: Path, field: str, replacement: object, error: str
) -> None:
    value = _active_index(tmp_path)
    pg18 = next(
        item for item in value["evidence_sets"] if item["evidence_id"] == PG18_ID
    )
    if field == "acceptance":
        pg18[field] = replacement
    else:
        pg18["acceptance"][field] = replacement
    with pytest.raises(EvidenceError, match=error):
        validate_evidence_index(value)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("unknown", True),
        ("evidence_id", "other"),
        ("source_sha", "a" * 40),
        ("implementation_sha", "not-a-sha"),
        ("postgres_major", 16),
        ("fingerprint_format_version", 1),
        ("canonical_table_count", 72),
        ("governed_seed_count", 14),
        ("shared_artifact_sha256", {}),
        ("expected_artifacts", ["verification-report.json"]),
    ],
)
def test_b04_r18_evidence_006_rejects_invalid_pg18_contract(
    field: str, replacement: object
) -> None:
    value = _pg18_contract()
    value[field] = replacement
    with pytest.raises(EvidenceError, match="B04-EVIDENCE-CONTRACT"):
        validate_pg18_contract(value)


def test_b04_r18_evidence_007_initial_resolver_fails_closed() -> None:
    with pytest.raises(EvidenceError, match="B04-EVIDENCE-NO-ACTIVE"):
        resolve_authorizing_evidence(
            _pending_verification_index(), ARTIFACT_DIR
        )


def test_b04_r18_evidence_008_resolver_returns_verified_active_set(
    tmp_path: Path,
) -> None:
    value = _active_index(tmp_path)
    result = resolve_authorizing_evidence(value, tmp_path)
    assert result.evidence_id == PG18_ID
    assert result.status is EvidenceStatus.ACTIVE_AUTHORIZING
    assert result.postgres_major == 18
    assert result.fingerprint_format_version == 2


@pytest.mark.parametrize(
    "failure",
    [
        "missing-contract",
        "missing-report",
        "report-digest",
        "contract-evidence-id",
        "contract-major",
        "contract-format",
        "report-evidence-id",
        "report-major",
        "report-format",
    ],
)
def test_b04_r18_evidence_009_resolver_rejects_corrupt_active_set(
    tmp_path: Path, failure: str
) -> None:
    value = _active_index(tmp_path)
    evidence_dir = tmp_path / "postgresql-18"
    pg18 = next(
        item for item in value["evidence_sets"] if item["evidence_id"] == PG18_ID
    )

    if failure == "missing-contract":
        (evidence_dir / "contract.json").unlink()
    elif failure == "missing-report":
        (evidence_dir / "verification-report.json").unlink()
    elif failure == "report-digest":
        pg18["acceptance"]["verification_report_sha256"] = "c" * 64
    elif failure.startswith("contract-"):
        contract = _pg18_contract()
        suffix = failure.removeprefix("contract-")
        field = {
            "evidence-id": "evidence_id",
            "major": "postgres_major",
            "format": "fingerprint_format_version",
        }[suffix]
        contract[field] = {
            "evidence-id": "other",
            "major": 17,
            "format": 1,
        }[suffix]
        (evidence_dir / "contract.json").write_bytes(
            canonical_json_bytes(contract)
        )
    else:
        report = {
            "evidence_id": PG18_ID,
            "fingerprint_format_version": 2,
            "postgres_major": 18,
        }
        suffix = failure.removeprefix("report-")
        field = {
            "evidence-id": "evidence_id",
            "major": "postgres_major",
            "format": "fingerprint_format_version",
        }[suffix]
        report[field] = {
            "evidence-id": "other",
            "major": 17,
            "format": 1,
        }[suffix]
        report_bytes = canonical_json_bytes(report)
        (evidence_dir / "verification-report.json").write_bytes(report_bytes)
        report_sha = hashlib.sha256(report_bytes).hexdigest()
        pg18["acceptance"]["verification_report_sha256"] = report_sha
        pg18["artifact_sha256"]["verification-report.json"] = report_sha

    with pytest.raises(EvidenceError, match="B04-EVIDENCE-"):
        resolve_authorizing_evidence(value, tmp_path)


def test_b04_r18_evidence_010_resolver_rejects_path_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    value = _active_index(root)
    pg18 = next(
        item for item in value["evidence_sets"] if item["evidence_id"] == PG18_ID
    )
    pg18["contract_path"] = "../outside/contract.json"
    with pytest.raises(EvidenceError, match="B04-EVIDENCE-PATH"):
        resolve_authorizing_evidence(value, root)
