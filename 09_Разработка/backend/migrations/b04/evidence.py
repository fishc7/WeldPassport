"""Versioned, fail-closed evidence contracts for B-04 baseline verification."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from migrations.b04.manifest import canonical_json_bytes, sha256_hex
from migrations.b04.source_contract import (
    CANONICAL_TABLE_COUNT,
    SCHEMA_SOURCE_COMMIT,
)


EVIDENCE_INDEX_FORMAT_VERSION = 1
BASELINE_ID = "canonical_baseline_v1"
PG16_EVIDENCE_ID = "postgresql-16-fingerprint-v1"
PG18_EVIDENCE_ID = "postgresql-18-fingerprint-v2"
PG18_CONTRACT_PATH = "postgresql-18/contract.json"
PG18_SERVER_VERSION_NUM = 180003
PG18_EXPECTED_ARTIFACTS = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "verification-report.json",
)
GOVERNED_SEED_COUNT = 15

PG16_ARTIFACT_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "cut.json": "6ca7959ae2f25c6d9c0c9b02272aacda34a09e035515fcb25773cba9f5bd46dc",
        "expected-fingerprint.json": "ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6",
        "expected-fingerprint.sha256": "c4ac2c98c18778a9428dbeeb0e53246279daa7837e2b1673596b3d5148353b1e",
        "frozen-revision-manifest.json": "8e791f4204b3b68b2dfb7ac8409f3b55124547a9df4e8c5487e128b66a22ec8d",
        "frozen-revision-manifest.sha256": "7f9531008ba5d1fcb3ed2544fb3da1212aad9ec4dd98c343090e1586c0d69eaa",
        "seed-manifest.json": "64aa1533c00f940405ed7fd7cbee7a60d831f5f952ec56961034f0b5570b679d",
        "verification-report.json": "563d65195cd1e381acccccf7caa31c48b09ef22fb2fda12235d705e1fbfd8487",
    }
)

_INDEX_KEYS = frozenset({"format_version", "baseline_id", "evidence_sets"})
_EVIDENCE_KEYS = frozenset(
    {
        "evidence_id",
        "status",
        "postgres_major",
        "fingerprint_format_version",
        "artifact_sha256",
        "contract_path",
        "acceptance",
    }
)
_ACCEPTANCE_KEYS = frozenset(
    {"accepted_at_utc", "accepted_by", "verification_report_sha256"}
)
_CONTRACT_KEYS = frozenset(
    {
        "evidence_id",
        "source_sha",
        "implementation_sha",
        "postgres_major",
        "fingerprint_format_version",
        "shared_artifact_sha256",
        "canonical_table_count",
        "governed_seed_count",
        "expected_artifacts",
    }
)
_REPORT_KEYS = frozenset(
    {
        "status",
        "evidence_id",
        "source_sha",
        "implementation_sha",
        "postgres_major",
        "server_version_num",
        "fingerprint_format_version",
        "historical_database",
        "baseline_database",
        "historical_digest",
        "baseline_digest",
        "reupgrade_digest",
        "shared_artifact_sha256",
        "canonical_table_count",
        "exact_seed_count",
        "governed_index",
    }
)
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceError(ValueError):
    """Evidence metadata or filesystem state violates the B-04 contract."""


class EvidenceStatus(StrEnum):
    HISTORICAL_NON_AUTHORIZING = "historical_non_authorizing"
    CANDIDATE_PENDING_VERIFICATION = "candidate_pending_verification"
    CANDIDATE_PENDING_ACCEPTANCE = "candidate_pending_acceptance"
    ACTIVE_AUTHORIZING = "active_authorizing"


@dataclass(frozen=True, slots=True)
class EvidenceSet:
    evidence_id: str
    status: EvidenceStatus
    postgres_major: int
    fingerprint_format_version: int
    artifact_sha256: Mapping[str, str]
    contract_path: str | None
    acceptance: Mapping[str, str] | None

    @classmethod
    def from_mapping(cls, value: object) -> EvidenceSet:
        parsed = _parse_evidence_set(value)
        return cls(
            evidence_id=parsed["evidence_id"],
            status=parsed["status"],
            postgres_major=parsed["postgres_major"],
            fingerprint_format_version=parsed["fingerprint_format_version"],
            artifact_sha256=MappingProxyType(dict(parsed["artifact_sha256"])),
            contract_path=parsed["contract_path"],
            acceptance=(
                MappingProxyType(dict(parsed["acceptance"]))
                if parsed["acceptance"] is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class Pg18EvidenceContract:
    evidence_id: str
    source_sha: str
    implementation_sha: str
    postgres_major: int
    fingerprint_format_version: int
    shared_artifact_sha256: Mapping[str, str]
    canonical_table_count: int
    governed_seed_count: int
    expected_artifacts: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: object) -> Pg18EvidenceContract:
        contract = _require_mapping(value, "B04-EVIDENCE-CONTRACT-TYPE")
        validate_pg18_contract(contract)
        return cls(
            evidence_id=contract["evidence_id"],
            source_sha=contract["source_sha"],
            implementation_sha=contract["implementation_sha"],
            postgres_major=contract["postgres_major"],
            fingerprint_format_version=contract["fingerprint_format_version"],
            shared_artifact_sha256=MappingProxyType(
                dict(contract["shared_artifact_sha256"])
            ),
            canonical_table_count=contract["canonical_table_count"],
            governed_seed_count=contract["governed_seed_count"],
            expected_artifacts=tuple(contract["expected_artifacts"]),
        )


def _require_mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise EvidenceError(code)
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], code: str) -> None:
    if set(value) != expected:
        raise EvidenceError(code)


def _exact_int(value: object, expected: int, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise EvidenceError(code)


def _valid_sha(value: object, pattern: re.Pattern[str], code: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise EvidenceError(code)
    return value


def _parse_hashes(value: object, code: str) -> dict[str, str]:
    mapping = _require_mapping(value, code)
    hashes: dict[str, str] = {}
    for name, digest in mapping.items():
        if not name or PurePosixPath(name).name != name or "\\" in name:
            raise EvidenceError(code)
        hashes[name] = _valid_sha(digest, _SHA64, code)
    return hashes


def _parse_acceptance(value: object) -> dict[str, str]:
    acceptance = _require_mapping(value, "B04-EVIDENCE-ACCEPTANCE")
    _exact_keys(acceptance, _ACCEPTANCE_KEYS, "B04-EVIDENCE-ACCEPTANCE-KEYS")
    accepted_at = acceptance["accepted_at_utc"]
    if not isinstance(accepted_at, str) or not accepted_at.endswith("Z"):
        raise EvidenceError("B04-EVIDENCE-ACCEPTANCE-TIME")
    try:
        parsed_at = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("B04-EVIDENCE-ACCEPTANCE-TIME") from exc
    if parsed_at.tzinfo != timezone.utc:
        raise EvidenceError("B04-EVIDENCE-ACCEPTANCE-TIME")
    if acceptance["accepted_by"] != "repository_owner":
        raise EvidenceError("B04-EVIDENCE-ACCEPTANCE-OWNER")
    report_sha = _valid_sha(
        acceptance["verification_report_sha256"],
        _SHA64,
        "B04-EVIDENCE-ACCEPTANCE-SHA",
    )
    return {
        "accepted_at_utc": accepted_at,
        "accepted_by": "repository_owner",
        "verification_report_sha256": report_sha,
    }


def _parse_evidence_set(value: object) -> dict[str, object]:
    entry = _require_mapping(value, "B04-EVIDENCE-ENTRY-TYPE")
    _exact_keys(entry, _EVIDENCE_KEYS, "B04-EVIDENCE-ENTRY-KEYS")
    evidence_id = entry["evidence_id"]
    if not isinstance(evidence_id, str):
        raise EvidenceError("B04-EVIDENCE-ID")
    try:
        status = EvidenceStatus(entry["status"])
    except (TypeError, ValueError) as exc:
        raise EvidenceError("B04-EVIDENCE-STATUS") from exc
    hashes = _parse_hashes(entry["artifact_sha256"], "B04-EVIDENCE-ARTIFACT-SHA")
    contract_path = entry["contract_path"]
    acceptance = entry["acceptance"]

    if evidence_id == PG16_EVIDENCE_ID:
        _exact_int(entry["postgres_major"], 16, "B04-EVIDENCE-PG16-MAJOR")
        _exact_int(
            entry["fingerprint_format_version"],
            1,
            "B04-EVIDENCE-PG16-FORMAT",
        )
        if status is not EvidenceStatus.HISTORICAL_NON_AUTHORIZING:
            raise EvidenceError("B04-EVIDENCE-PG16-STATUS")
        if hashes != dict(PG16_ARTIFACT_SHA256):
            raise EvidenceError("B04-EVIDENCE-PG16-HASHES")
        if contract_path is not None or acceptance is not None:
            raise EvidenceError("B04-EVIDENCE-PG16-AUTHORIZATION")
    elif evidence_id == PG18_EVIDENCE_ID:
        _exact_int(entry["postgres_major"], 18, "B04-EVIDENCE-PG18-MAJOR")
        _exact_int(
            entry["fingerprint_format_version"],
            2,
            "B04-EVIDENCE-PG18-FORMAT",
        )
        if contract_path != PG18_CONTRACT_PATH:
            raise EvidenceError("B04-EVIDENCE-PATH")
        if status is EvidenceStatus.CANDIDATE_PENDING_VERIFICATION:
            if hashes or acceptance is not None:
                raise EvidenceError("B04-EVIDENCE-PENDING-VERIFICATION")
        elif status is EvidenceStatus.CANDIDATE_PENDING_ACCEPTANCE:
            if set(hashes) != set(PG18_EXPECTED_ARTIFACTS) or acceptance is not None:
                raise EvidenceError("B04-EVIDENCE-PENDING-ACCEPTANCE")
        elif status is EvidenceStatus.ACTIVE_AUTHORIZING:
            if set(hashes) != set(PG18_EXPECTED_ARTIFACTS):
                raise EvidenceError("B04-EVIDENCE-ACTIVE-ARTIFACTS")
            acceptance = _parse_acceptance(acceptance)
        else:
            raise EvidenceError("B04-EVIDENCE-PG18-STATUS")
    else:
        raise EvidenceError("B04-EVIDENCE-ID")

    return {
        "evidence_id": evidence_id,
        "status": status,
        "postgres_major": entry["postgres_major"],
        "fingerprint_format_version": entry["fingerprint_format_version"],
        "artifact_sha256": hashes,
        "contract_path": contract_path,
        "acceptance": acceptance,
    }


def validate_evidence_index(value: Mapping[str, object]) -> None:
    """Validate only the exact structural and state contract of an evidence index."""
    index = _require_mapping(value, "B04-EVIDENCE-INDEX-TYPE")
    _exact_keys(index, _INDEX_KEYS, "B04-EVIDENCE-INDEX-KEYS")
    _exact_int(
        index["format_version"],
        EVIDENCE_INDEX_FORMAT_VERSION,
        "B04-EVIDENCE-INDEX-FORMAT",
    )
    if index["baseline_id"] != BASELINE_ID:
        raise EvidenceError("B04-EVIDENCE-BASELINE-ID")
    raw_entries = index["evidence_sets"]
    if not isinstance(raw_entries, list):
        raise EvidenceError("B04-EVIDENCE-SETS-TYPE")
    raw_active_count = sum(
        isinstance(item, Mapping)
        and item.get("status") == EvidenceStatus.ACTIVE_AUTHORIZING
        for item in raw_entries
    )
    if raw_active_count > 1:
        raise EvidenceError("B04-EVIDENCE-ACTIVE-COUNT")
    entries = [_parse_evidence_set(item) for item in raw_entries]
    ids = [entry["evidence_id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise EvidenceError("B04-EVIDENCE-DUPLICATE-ID")
    if set(ids) != {PG16_EVIDENCE_ID, PG18_EVIDENCE_ID}:
        raise EvidenceError("B04-EVIDENCE-SET")


def validate_pg18_contract(value: Mapping[str, object]) -> None:
    """Validate the immutable exact-key PG18 evidence contract."""
    contract = _require_mapping(value, "B04-EVIDENCE-CONTRACT-TYPE")
    _exact_keys(contract, _CONTRACT_KEYS, "B04-EVIDENCE-CONTRACT-KEYS")
    if contract["evidence_id"] != PG18_EVIDENCE_ID:
        raise EvidenceError("B04-EVIDENCE-CONTRACT-ID")
    if contract["source_sha"] != SCHEMA_SOURCE_COMMIT:
        raise EvidenceError("B04-EVIDENCE-CONTRACT-SOURCE")
    _valid_sha(
        contract["implementation_sha"],
        _SHA40,
        "B04-EVIDENCE-CONTRACT-IMPLEMENTATION",
    )
    _exact_int(contract["postgres_major"], 18, "B04-EVIDENCE-CONTRACT-MAJOR")
    _exact_int(
        contract["fingerprint_format_version"],
        2,
        "B04-EVIDENCE-CONTRACT-FORMAT",
    )
    shared_hashes = _parse_hashes(
        contract["shared_artifact_sha256"],
        "B04-EVIDENCE-CONTRACT-SHARED",
    )
    if shared_hashes != dict(PG16_ARTIFACT_SHA256):
        raise EvidenceError("B04-EVIDENCE-CONTRACT-SHARED")
    _exact_int(
        contract["canonical_table_count"],
        CANONICAL_TABLE_COUNT,
        "B04-EVIDENCE-CONTRACT-TABLES",
    )
    _exact_int(
        contract["governed_seed_count"],
        GOVERNED_SEED_COUNT,
        "B04-EVIDENCE-CONTRACT-SEEDS",
    )
    if contract["expected_artifacts"] != list(PG18_EXPECTED_ARTIFACTS):
        raise EvidenceError("B04-EVIDENCE-CONTRACT-ARTIFACTS")


def validate_pg18_report(value: Mapping[str, object]) -> None:
    """Validate the exact-key PG18 verification report contract."""
    report = _require_mapping(value, "B04-EVIDENCE-REPORT-TYPE")
    _exact_keys(report, _REPORT_KEYS, "B04-EVIDENCE-REPORT-KEYS")
    if report["status"] != "B04A_VERIFIED":
        raise EvidenceError("B04-EVIDENCE-REPORT-STATUS")
    if report["evidence_id"] != PG18_EVIDENCE_ID:
        raise EvidenceError("B04-EVIDENCE-REPORT-ID")
    if report["source_sha"] != SCHEMA_SOURCE_COMMIT:
        raise EvidenceError("B04-EVIDENCE-REPORT-SOURCE")
    _valid_sha(
        report["implementation_sha"],
        _SHA40,
        "B04-EVIDENCE-REPORT-IMPLEMENTATION",
    )
    _exact_int(report["postgres_major"], 18, "B04-EVIDENCE-REPORT-MAJOR")
    _exact_int(
        report["server_version_num"],
        PG18_SERVER_VERSION_NUM,
        "B04-EVIDENCE-REPORT-SERVER-VERSION",
    )
    _exact_int(
        report["fingerprint_format_version"],
        2,
        "B04-EVIDENCE-REPORT-FORMAT",
    )
    if report["historical_database"] != "wp_b04_r18_historical_disposable":
        raise EvidenceError("B04-EVIDENCE-REPORT-HISTORICAL-DATABASE")
    if report["baseline_database"] != "wp_b04_r18_baseline_disposable":
        raise EvidenceError("B04-EVIDENCE-REPORT-BASELINE-DATABASE")
    digests = [
        _valid_sha(report[name], _SHA64, "B04-EVIDENCE-REPORT-DIGEST")
        for name in ("historical_digest", "baseline_digest", "reupgrade_digest")
    ]
    if len(set(digests)) != 1:
        raise EvidenceError("B04-EVIDENCE-REPORT-DIGEST-MISMATCH")
    shared_hashes = _parse_hashes(
        report["shared_artifact_sha256"],
        "B04-EVIDENCE-REPORT-SHARED",
    )
    if shared_hashes != dict(PG16_ARTIFACT_SHA256):
        raise EvidenceError("B04-EVIDENCE-REPORT-SHARED")
    _exact_int(
        report["canonical_table_count"],
        CANONICAL_TABLE_COUNT,
        "B04-EVIDENCE-REPORT-TABLES",
    )
    _exact_int(
        report["exact_seed_count"],
        GOVERNED_SEED_COUNT,
        "B04-EVIDENCE-REPORT-SEEDS",
    )
    if report["governed_index"] != "hr.worker_roles.uq_hr_worker_roles_active_scope":
        raise EvidenceError("B04-EVIDENCE-REPORT-INDEX")


def build_pg18_contract(implementation_sha: str) -> dict[str, object]:
    """Build and validate the immutable PG18 contract for one implementation."""
    contract: dict[str, object] = {
        "evidence_id": PG18_EVIDENCE_ID,
        "source_sha": SCHEMA_SOURCE_COMMIT,
        "implementation_sha": implementation_sha,
        "postgres_major": 18,
        "fingerprint_format_version": 2,
        "shared_artifact_sha256": dict(PG16_ARTIFACT_SHA256),
        "canonical_table_count": CANONICAL_TABLE_COUNT,
        "governed_seed_count": GOVERNED_SEED_COUNT,
        "expected_artifacts": list(PG18_EXPECTED_ARTIFACTS),
    }
    validate_pg18_contract(contract)
    return contract


def build_pending_acceptance_index(
    value: Mapping[str, object],
    artifact_sha256: Mapping[str, str],
) -> dict[str, object]:
    """Return the only allowed runner transition for PG18 evidence."""
    validate_evidence_index(value)
    hashes = _parse_hashes(
        artifact_sha256,
        "B04-EVIDENCE-PENDING-ACCEPTANCE-HASHES",
    )
    if set(hashes) != set(PG18_EXPECTED_ARTIFACTS):
        raise EvidenceError("B04-EVIDENCE-PENDING-ACCEPTANCE-HASHES")
    updated = json.loads(json.dumps(value))
    entries = updated["evidence_sets"]
    pg18 = next(
        item for item in entries if item["evidence_id"] == PG18_EVIDENCE_ID
    )
    if (
        pg18["status"] != EvidenceStatus.CANDIDATE_PENDING_VERIFICATION
        or pg18["artifact_sha256"]
        or pg18["acceptance"] is not None
    ):
        raise EvidenceError("B04-EVIDENCE-PUBLICATION-STATE")
    pg18["status"] = EvidenceStatus.CANDIDATE_PENDING_ACCEPTANCE
    pg18["artifact_sha256"] = hashes
    pg18["acceptance"] = None
    validate_evidence_index(updated)
    return updated


def _load_canonical_json(path: Path, code: str) -> Mapping[str, object]:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(code) from exc
    mapping = _require_mapping(value, code)
    if canonical_json_bytes(mapping) != data:
        raise EvidenceError(f"{code}-NONCANONICAL")
    return mapping


def _resolve_regular_file(root: Path, relative_path: str) -> Path:
    posix_path = PurePosixPath(relative_path)
    if (
        posix_path.is_absolute()
        or not posix_path.parts
        or any(part in {"", ".", ".."} for part in posix_path.parts)
        or "\\" in relative_path
    ):
        raise EvidenceError("B04-EVIDENCE-PATH")
    candidate = root.joinpath(*posix_path.parts)
    current = root
    for part in posix_path.parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceError("B04-EVIDENCE-PATH-SYMLINK")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise EvidenceError("B04-EVIDENCE-PATH") from exc
    if not resolved.is_file():
        raise EvidenceError("B04-EVIDENCE-PATH")
    return resolved


def resolve_authorizing_evidence(
    value: Mapping[str, object], artifact_root: Path
) -> EvidenceSet:
    """Return the sole physically verified active PG18 evidence set."""
    try:
        validate_evidence_index(value)
    except EvidenceError as exc:
        if str(exc) == "B04-EVIDENCE-ACTIVE-COUNT":
            raise EvidenceError("B04-EVIDENCE-NO-ACTIVE") from exc
        raise
    active = [
        item
        for item in value["evidence_sets"]
        if item["status"] == EvidenceStatus.ACTIVE_AUTHORIZING
    ]
    if len(active) != 1:
        raise EvidenceError("B04-EVIDENCE-NO-ACTIVE")
    evidence = EvidenceSet.from_mapping(active[0])
    if evidence.evidence_id != PG18_EVIDENCE_ID:
        raise EvidenceError("B04-EVIDENCE-NO-ACTIVE")

    if artifact_root.is_symlink():
        raise EvidenceError("B04-EVIDENCE-PATH-SYMLINK")
    try:
        root = artifact_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EvidenceError("B04-EVIDENCE-PATH") from exc
    if not root.is_dir():
        raise EvidenceError("B04-EVIDENCE-PATH")

    assert evidence.contract_path is not None
    contract_path = _resolve_regular_file(root, evidence.contract_path)
    report_relative = str(
        PurePosixPath(evidence.contract_path).with_name("verification-report.json")
    )
    report_path = _resolve_regular_file(root, report_relative)
    contract = _load_canonical_json(
        contract_path, "B04-EVIDENCE-CONTRACT-JSON"
    )
    validate_pg18_contract(contract)
    report = _load_canonical_json(report_path, "B04-EVIDENCE-REPORT-JSON")

    if (
        contract["evidence_id"] != evidence.evidence_id
        or contract["postgres_major"] != evidence.postgres_major
        or contract["fingerprint_format_version"]
        != evidence.fingerprint_format_version
    ):
        raise EvidenceError("B04-EVIDENCE-CONTRACT-MISMATCH")
    for key, expected in (
        ("evidence_id", evidence.evidence_id),
        ("postgres_major", evidence.postgres_major),
        ("fingerprint_format_version", evidence.fingerprint_format_version),
    ):
        if report.get(key) != expected:
            raise EvidenceError("B04-EVIDENCE-REPORT-MISMATCH")

    contract_sha = sha256_hex(contract_path.read_bytes())
    report_sha = sha256_hex(report_path.read_bytes())
    if evidence.artifact_sha256.get("contract.json") != contract_sha:
        raise EvidenceError("B04-EVIDENCE-CONTRACT-DIGEST")
    if evidence.artifact_sha256.get("verification-report.json") != report_sha:
        raise EvidenceError("B04-EVIDENCE-REPORT-DIGEST")
    assert evidence.acceptance is not None
    if evidence.acceptance["verification_report_sha256"] != report_sha:
        raise EvidenceError("B04-EVIDENCE-ACCEPTANCE-DIGEST")
    return evidence
