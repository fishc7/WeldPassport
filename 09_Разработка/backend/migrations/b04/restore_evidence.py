"""Fail-closed contracts for B-04R PostgreSQL restore-roundtrip evidence."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from migrations.b04.evidence import (
    BASELINE_ID,
    PG18_EVIDENCE_ID,
    PG18_EXPECTED_ARTIFACTS,
    PG18_SERVER_VERSION_NUM,
    EvidenceError,
    EvidenceSet,
    resolve_authorizing_evidence,
)
from migrations.b04.fingerprint import (
    FingerprintError,
    assert_supported_catalog,
    canonicalize_fingerprint,
)
from migrations.b04.manifest import canonical_json_bytes, sha256_hex
from migrations.b04.seeds import seed_manifest
from migrations.b04.source_contract import CANONICAL_TABLE_COUNT, SCHEMA_SOURCE_COMMIT


RESTORE_INDEX_FORMAT_VERSION = 1
RESTORE_EVIDENCE_ID = "postgresql-18-restore-roundtrip-v1"
RESTORE_CONTRACT_PATH = "postgresql-18/restore-roundtrip-v1/contract.json"
RESTORE_EXPECTED_ARTIFACTS = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "equivalence-map.json",
    "verification-report.json",
)
RESTORE_PAYLOAD_ARTIFACTS = (
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "equivalence-map.json",
)
RESTORE_REPORT_ARTIFACTS = ("contract.json", *RESTORE_PAYLOAD_ARTIFACTS)
LIVE_EXPECTED_FINGERPRINT_SHA256 = (
    "e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a"
)
CANONICAL_SEQUENCE_COUNT = 6
GOVERNED_SEED_COUNT = 15
HISTORICAL_MARKER = "20260724_27_qd_rbac_sod"

_INDEX_KEYS = frozenset(
    {"format_version", "baseline_id", "live_evidence_id", "evidence_sets"}
)
_RESTORE_ENTRY_KEYS = frozenset(
    {
        "evidence_id",
        "status",
        "postgres_major",
        "contract_path",
        "artifact_sha256",
        "acceptance",
    }
)
_ACCEPTANCE_KEYS = frozenset(
    {"accepted_at_utc", "accepted_by", "verification_report_sha256"}
)
_RESTORE_CONTRACT_KEYS = frozenset(
    {
        "evidence_id",
        "baseline_id",
        "live_evidence_id",
        "source_sha",
        "implementation_sha",
        "postgres_major",
        "server_version_num",
        "pg_dump_version",
        "pg_restore_version",
        "live_fingerprint_format_version",
        "restore_fingerprint_format_version",
        "live_expected_fingerprint_sha256",
        "restore_expected_fingerprint_sha256",
        "equivalence_map_sha256",
        "shared_artifact_sha256",
        "payload_artifact_sha256",
        "canonical_table_count",
        "canonical_sequence_count",
        "governed_seed_count",
        "expected_artifacts",
    }
)
_EQUIVALENCE_MAP_KEYS = frozenset(
    {
        "format_version",
        "live_evidence_id",
        "restore_evidence_id",
        "live_fingerprint_sha256",
        "restore_fingerprint_sha256",
        "difference_count",
        "differences",
    }
)
_DIFFERENCE_KEYS = frozenset(
    {
        "kind",
        "schema",
        "table",
        "object_name",
        "live_json_pointer",
        "restore_json_pointer",
        "live_expression_sha256",
        "restore_expression_sha256",
    }
)
_RESTORE_REPORT_KEYS = frozenset(
    {
        "status",
        "evidence_id",
        "live_evidence_id",
        "source_sha",
        "implementation_sha",
        "postgres_major",
        "server_version_num",
        "pg_dump_version",
        "pg_restore_version",
        "working_database",
        "first_restore_database",
        "second_restore_database",
        "backup_sha256",
        "live_digest",
        "first_restore_digest",
        "second_restore_digest",
        "difference_counts",
        "marker_state",
        "canonical_table_count",
        "canonical_sequence_count",
        "governed_seed_count",
        "artifact_sha256",
        "first_restore_equals_second",
        "live_equals_authorizing",
        "typed_diff_equals_map",
    }
)
_MARKER_STATE_KEYS = frozenset({"working", "first_restore", "second_restore"})
_MARKER_KEYS = frozenset({"historical_marker", "public_marker"})
_DIFFERENCE_COUNT_KEYS = frozenset(
    {
        "check_definition_deparser_roundtrip",
        "index_predicate_deparser_roundtrip",
    }
)
_DIFFERENCE_KINDS = _DIFFERENCE_COUNT_KEYS
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_TOOL_VERSION = re.compile(r"pg_(?:dump|restore) \(PostgreSQL\) 18(?:\.[0-9]+)+\Z")


class RestoreEvidenceError(ValueError):
    """Restore evidence metadata or artifact state violates ADR-031."""


class RestoreEvidenceStatus(StrEnum):
    CANDIDATE_PENDING_VERIFICATION = "candidate_pending_verification"
    CANDIDATE_PENDING_ACCEPTANCE = "candidate_pending_acceptance"
    ACTIVE_RESTORE_AUTHORIZING = "active_restore_authorizing"


@dataclass(frozen=True, slots=True)
class RestoreEvidenceSet:
    evidence_id: str
    status: RestoreEvidenceStatus
    postgres_major: int
    contract_path: str
    artifact_sha256: Mapping[str, str]
    acceptance: Mapping[str, str] | None


@dataclass(frozen=True, slots=True)
class ExpressionDifference:
    kind: str
    schema: str
    table: str
    object_name: str
    live_json_pointer: str
    restore_json_pointer: str
    live_expression_sha256: str
    restore_expression_sha256: str


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise RestoreEvidenceError(code)
    return value


def _exact_keys(
    value: Mapping[str, object], expected: frozenset[str], code: str
) -> None:
    if set(value) != expected:
        raise RestoreEvidenceError(code)


def _exact_int(value: object, expected: int, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise RestoreEvidenceError(code)


def _nonnegative_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RestoreEvidenceError(code)
    return value


def _sha(value: object, code: str, *, length: int = 64) -> str:
    pattern = _SHA40 if length == 40 else _SHA64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RestoreEvidenceError(code)
    return value


def _hashes(
    value: object,
    expected_names: tuple[str, ...],
    code: str,
) -> dict[str, str]:
    mapping = _mapping(value, code)
    if set(mapping) != set(expected_names):
        raise RestoreEvidenceError(code)
    return {name: _sha(mapping[name], code) for name in expected_names}


def _utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RestoreEvidenceError("B04R-ACCEPTANCE") from None
    if parsed.tzinfo != timezone.utc:
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    return value


def _acceptance(value: object) -> dict[str, str]:
    acceptance = _mapping(value, "B04R-ACCEPTANCE")
    _exact_keys(acceptance, _ACCEPTANCE_KEYS, "B04R-ACCEPTANCE")
    if acceptance["accepted_by"] != "repository_owner":
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    return {
        "accepted_at_utc": _utc_timestamp(acceptance["accepted_at_utc"]),
        "accepted_by": "repository_owner",
        "verification_report_sha256": _sha(
            acceptance["verification_report_sha256"], "B04R-ACCEPTANCE"
        ),
    }


def _parse_restore_entry(value: object) -> dict[str, object]:
    entry = _mapping(value, "B04R-EVIDENCE-INDEX")
    _exact_keys(entry, _RESTORE_ENTRY_KEYS, "B04R-EVIDENCE-INDEX")
    if entry["evidence_id"] != RESTORE_EVIDENCE_ID:
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    _exact_int(entry["postgres_major"], 18, "B04R-EVIDENCE-INDEX")
    if entry["contract_path"] != RESTORE_CONTRACT_PATH:
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    try:
        status = RestoreEvidenceStatus(entry["status"])
    except (TypeError, ValueError):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX") from None
    acceptance: dict[str, str] | None = None
    if status is RestoreEvidenceStatus.CANDIDATE_PENDING_VERIFICATION:
        if entry["artifact_sha256"] != {} or entry["acceptance"] is not None:
            raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
        hashes: dict[str, str] = {}
    else:
        hashes = _hashes(
            entry["artifact_sha256"],
            RESTORE_EXPECTED_ARTIFACTS,
            "B04R-EVIDENCE-INDEX",
        )
        if status is RestoreEvidenceStatus.CANDIDATE_PENDING_ACCEPTANCE:
            if entry["acceptance"] is not None:
                raise RestoreEvidenceError("B04R-ACCEPTANCE")
        else:
            acceptance = _acceptance(entry["acceptance"])
    return {
        "evidence_id": RESTORE_EVIDENCE_ID,
        "status": status,
        "postgres_major": 18,
        "contract_path": RESTORE_CONTRACT_PATH,
        "artifact_sha256": hashes,
        "acceptance": acceptance,
    }


def validate_restore_evidence_index(value: Mapping[str, object]) -> None:
    """Validate the exact restore evidence index and its state transition shape."""
    index = _mapping(value, "B04R-EVIDENCE-INDEX")
    _exact_keys(index, _INDEX_KEYS, "B04R-EVIDENCE-INDEX")
    _exact_int(
        index["format_version"],
        RESTORE_INDEX_FORMAT_VERSION,
        "B04R-EVIDENCE-INDEX",
    )
    if (
        index["baseline_id"] != BASELINE_ID
        or index["live_evidence_id"] != PG18_EVIDENCE_ID
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    entries = index["evidence_sets"]
    if not isinstance(entries, list) or len(entries) > 1:
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    if entries:
        _parse_restore_entry(entries[0])


def validate_restore_contract(value: Mapping[str, object]) -> None:
    """Validate an immutable, acyclic B-04R contract."""
    contract = _mapping(value, "B04R-EVIDENCE-INDEX")
    _exact_keys(contract, _RESTORE_CONTRACT_KEYS, "B04R-EVIDENCE-INDEX")
    if (
        contract["evidence_id"] != RESTORE_EVIDENCE_ID
        or contract["baseline_id"] != BASELINE_ID
        or contract["live_evidence_id"] != PG18_EVIDENCE_ID
        or contract["source_sha"] != SCHEMA_SOURCE_COMMIT
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    _sha(contract["implementation_sha"], "B04R-EVIDENCE-INDEX", length=40)
    _exact_int(contract["postgres_major"], 18, "B04R-SERVER-VERSION")
    _exact_int(
        contract["server_version_num"],
        PG18_SERVER_VERSION_NUM,
        "B04R-SERVER-VERSION",
    )
    for name in ("pg_dump_version", "pg_restore_version"):
        value_string = contract[name]
        if (
            not isinstance(value_string, str)
            or _TOOL_VERSION.fullmatch(value_string) is None
            or not value_string.startswith(name.removesuffix("_version"))
        ):
            raise RestoreEvidenceError("B04R-TOOL-VERSION")
    _exact_int(
        contract["live_fingerprint_format_version"],
        2,
        "B04R-EVIDENCE-INDEX",
    )
    _exact_int(
        contract["restore_fingerprint_format_version"],
        2,
        "B04R-EVIDENCE-INDEX",
    )
    if (
        _sha(
            contract["live_expected_fingerprint_sha256"],
            "B04R-LIVE-EVIDENCE",
        )
        != LIVE_EXPECTED_FINGERPRINT_SHA256
    ):
        raise RestoreEvidenceError("B04R-LIVE-EVIDENCE")
    restore_digest = _sha(
        contract["restore_expected_fingerprint_sha256"],
        "B04R-RESTORE-FINGERPRINT",
    )
    map_digest = _sha(contract["equivalence_map_sha256"], "B04R-DIFF-MAP")
    _hashes(
        contract["shared_artifact_sha256"],
        PG18_EXPECTED_ARTIFACTS,
        "B04R-LIVE-EVIDENCE",
    )
    payload = _hashes(
        contract["payload_artifact_sha256"],
        RESTORE_PAYLOAD_ARTIFACTS,
        "B04R-EVIDENCE-INDEX",
    )
    if (
        payload["expected-fingerprint.json"] != restore_digest
        or payload["equivalence-map.json"] != map_digest
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    _exact_int(
        contract["canonical_table_count"],
        CANONICAL_TABLE_COUNT,
        "B04R-EVIDENCE-INDEX",
    )
    _exact_int(
        contract["canonical_sequence_count"],
        CANONICAL_SEQUENCE_COUNT,
        "B04R-EVIDENCE-INDEX",
    )
    _exact_int(
        contract["governed_seed_count"],
        GOVERNED_SEED_COUNT,
        "B04R-EVIDENCE-INDEX",
    )
    if contract["expected_artifacts"] != list(RESTORE_EXPECTED_ARTIFACTS):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")


def validate_equivalence_map(value: Mapping[str, object]) -> None:
    """Validate exact typed live/restore expression-difference metadata."""
    equivalence = _mapping(value, "B04R-DIFF-MAP")
    _exact_keys(equivalence, _EQUIVALENCE_MAP_KEYS, "B04R-DIFF-MAP")
    _exact_int(equivalence["format_version"], 1, "B04R-DIFF-MAP")
    if (
        equivalence["live_evidence_id"] != PG18_EVIDENCE_ID
        or equivalence["restore_evidence_id"] != RESTORE_EVIDENCE_ID
    ):
        raise RestoreEvidenceError("B04R-DIFF-MAP")
    _sha(equivalence["live_fingerprint_sha256"], "B04R-DIFF-MAP")
    _sha(equivalence["restore_fingerprint_sha256"], "B04R-DIFF-MAP")
    count = _nonnegative_int(equivalence["difference_count"], "B04R-DIFF-MAP")
    differences = equivalence["differences"]
    if not isinstance(differences, list) or len(differences) != count:
        raise RestoreEvidenceError("B04R-DIFF-MAP")
    identities: set[tuple[object, ...]] = set()
    for raw in differences:
        item = _mapping(raw, "B04R-DIFF-MAP")
        _exact_keys(item, _DIFFERENCE_KEYS, "B04R-DIFF-MAP")
        if item["kind"] not in _DIFFERENCE_KINDS:
            raise RestoreEvidenceError("B04R-DIFF-KIND")
        string_fields = (
            "schema",
            "table",
            "object_name",
            "live_json_pointer",
            "restore_json_pointer",
        )
        if any(
            not isinstance(item[name], str) or not item[name]
            for name in string_fields
        ):
            raise RestoreEvidenceError("B04R-DIFF-MAP")
        _sha(item["live_expression_sha256"], "B04R-DIFF-MAP")
        _sha(item["restore_expression_sha256"], "B04R-DIFF-MAP")
        identity = tuple(item[name] for name in ("kind", *string_fields))
        if identity in identities:
            raise RestoreEvidenceError("B04R-DIFF-MAP")
        identities.add(identity)


def _expression_difference(
    path: tuple[object, ...],
    live_root: Mapping[str, object],
    restore_root: Mapping[str, object],
    live_value: object,
    restore_value: object,
) -> ExpressionDifference:
    if (
        len(path) != 5
        or path[0] != "tables"
        or not isinstance(path[1], int)
        or path[2] not in {"checks", "indexes"}
        or not isinstance(path[3], int)
        or path[4] not in {"definition", "predicate"}
        or not isinstance(live_value, str)
        or not live_value
        or not isinstance(restore_value, str)
        or not restore_value
    ):
        raise RestoreEvidenceError("B04R-DIFF-KIND")
    if (path[2], path[4]) not in {
        ("checks", "definition"),
        ("indexes", "predicate"),
    }:
        raise RestoreEvidenceError("B04R-DIFF-KIND")
    try:
        live_table = live_root["tables"][path[1]]
        restore_table = restore_root["tables"][path[1]]
        live_object = live_table[path[2]][path[3]]
        restore_object = restore_table[path[2]][path[3]]
        schema = live_table["schema"]
        table = live_table["name"]
        object_name = live_object["name"]
    except (KeyError, IndexError, TypeError):
        raise RestoreEvidenceError("B04R-DIFF-KIND") from None
    if (
        not isinstance(live_table, Mapping)
        or not isinstance(restore_table, Mapping)
        or not isinstance(live_object, Mapping)
        or not isinstance(restore_object, Mapping)
        or not all(
            isinstance(value, str) and value
            for value in (schema, table, object_name)
        )
        or restore_table.get("schema") != schema
        or restore_table.get("name") != table
        or restore_object.get("name") != object_name
    ):
        raise RestoreEvidenceError("B04R-DIFF-KIND")
    pointer = "/" + "/".join(str(item) for item in path)
    kind = (
        "check_definition_deparser_roundtrip"
        if path[2] == "checks"
        else "index_predicate_deparser_roundtrip"
    )
    return ExpressionDifference(
        kind=kind,
        schema=schema,
        table=table,
        object_name=object_name,
        live_json_pointer=pointer,
        restore_json_pointer=pointer,
        live_expression_sha256=sha256_hex(live_value.encode("utf-8")),
        restore_expression_sha256=sha256_hex(restore_value.encode("utf-8")),
    )


def _collect_leaf_differences(
    live: object,
    restored: object,
    *,
    live_root: Mapping[str, object],
    restore_root: Mapping[str, object],
    path: tuple[object, ...] = (),
) -> list[ExpressionDifference]:
    if type(live) is not type(restored):
        raise RestoreEvidenceError("B04R-DIFF-KIND")
    if isinstance(live, Mapping):
        if not isinstance(restored, Mapping) or set(live) != set(restored):
            raise RestoreEvidenceError("B04R-DIFF-KIND")
        result: list[ExpressionDifference] = []
        for key in sorted(live):
            result.extend(
                _collect_leaf_differences(
                    live[key],
                    restored[key],
                    live_root=live_root,
                    restore_root=restore_root,
                    path=(*path, key),
                )
            )
        return result
    if isinstance(live, list):
        if not isinstance(restored, list) or len(live) != len(restored):
            raise RestoreEvidenceError("B04R-DIFF-KIND")
        result = []
        for index, (live_item, restored_item) in enumerate(
            zip(live, restored, strict=True)
        ):
            result.extend(
                _collect_leaf_differences(
                    live_item,
                    restored_item,
                    live_root=live_root,
                    restore_root=restore_root,
                    path=(*path, index),
                )
            )
        return result
    if live == restored:
        return []
    return [
        _expression_difference(path, live_root, restore_root, live, restored)
    ]


def build_typed_equivalence_map(
    live: Mapping[str, object],
    restored: Mapping[str, object],
) -> dict[str, object]:
    """Build the complete exact map for the two permitted expression leaf kinds."""
    live_mapping = _mapping(live, "B04R-DIFF-KIND")
    restore_mapping = _mapping(restored, "B04R-DIFF-KIND")
    differences = _collect_leaf_differences(
        live_mapping,
        restore_mapping,
        live_root=live_mapping,
        restore_root=restore_mapping,
    )
    ordered = sorted(
        differences,
        key=lambda item: (
            item.kind,
            item.schema,
            item.table,
            item.object_name,
            item.live_json_pointer,
            item.restore_json_pointer,
        ),
    )
    result: dict[str, object] = {
        "format_version": 1,
        "live_evidence_id": PG18_EVIDENCE_ID,
        "restore_evidence_id": RESTORE_EVIDENCE_ID,
        "live_fingerprint_sha256": sha256_hex(
            canonical_json_bytes(live_mapping)
        ),
        "restore_fingerprint_sha256": sha256_hex(
            canonical_json_bytes(restore_mapping)
        ),
        "difference_count": len(ordered),
        "differences": [
            {
                "kind": item.kind,
                "schema": item.schema,
                "table": item.table,
                "object_name": item.object_name,
                "live_json_pointer": item.live_json_pointer,
                "restore_json_pointer": item.restore_json_pointer,
                "live_expression_sha256": item.live_expression_sha256,
                "restore_expression_sha256": item.restore_expression_sha256,
            }
            for item in ordered
        ],
    }
    validate_equivalence_map(result)
    return result


def assert_typed_equivalence(
    live: Mapping[str, object],
    restored: Mapping[str, object],
    equivalence_map: Mapping[str, object],
) -> None:
    """Require the supplied map to equal the complete recomputed typed diff."""
    try:
        validate_equivalence_map(equivalence_map)
        expected = build_typed_equivalence_map(live, restored)
    except RestoreEvidenceError as exc:
        if str(exc) == "B04R-DIFF-KIND":
            raise
        raise RestoreEvidenceError("B04R-DIFF-MAP") from exc
    if canonical_json_bytes(equivalence_map) != canonical_json_bytes(expected):
        raise RestoreEvidenceError("B04R-DIFF-MAP")


def _marker_state(value: object) -> None:
    states = _mapping(value, "B04R-RESTORE-FINGERPRINT")
    _exact_keys(states, _MARKER_STATE_KEYS, "B04R-RESTORE-FINGERPRINT")
    for raw in states.values():
        marker = _mapping(raw, "B04R-RESTORE-FINGERPRINT")
        _exact_keys(marker, _MARKER_KEYS, "B04R-RESTORE-FINGERPRINT")
        if (
            marker["historical_marker"] != HISTORICAL_MARKER
            or marker["public_marker"] is not None
        ):
            raise RestoreEvidenceError("B04R-RESTORE-FINGERPRINT")


def validate_restore_report(value: Mapping[str, object]) -> None:
    """Validate the exact secret-free B-04R verification report."""
    report = _mapping(value, "B04R-EVIDENCE-INDEX")
    _exact_keys(report, _RESTORE_REPORT_KEYS, "B04R-EVIDENCE-INDEX")
    if (
        report["status"] != "B04_RESTORE_ROUNDTRIP_VERIFIED"
        or report["evidence_id"] != RESTORE_EVIDENCE_ID
        or report["live_evidence_id"] != PG18_EVIDENCE_ID
        or report["source_sha"] != SCHEMA_SOURCE_COMMIT
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    _sha(report["implementation_sha"], "B04R-EVIDENCE-INDEX", length=40)
    _exact_int(report["postgres_major"], 18, "B04R-SERVER-VERSION")
    _exact_int(
        report["server_version_num"],
        PG18_SERVER_VERSION_NUM,
        "B04R-SERVER-VERSION",
    )
    for name in ("pg_dump_version", "pg_restore_version"):
        value_string = report[name]
        if (
            not isinstance(value_string, str)
            or _TOOL_VERSION.fullmatch(value_string) is None
            or not value_string.startswith(name.removesuffix("_version"))
        ):
            raise RestoreEvidenceError("B04R-TOOL-VERSION")
    expected_databases = {
        "first_restore_database": "wp_b04_r18_restore_first_disposable",
        "second_restore_database": "wp_b04_r18_restore_second_disposable",
    }
    if (
        not isinstance(report["working_database"], str)
        or not report["working_database"]
        or any(report[name] != expected for name, expected in expected_databases.items())
    ):
        raise RestoreEvidenceError("B04R-RESTORE-FINGERPRINT")
    _sha(report["backup_sha256"], "B04R-BACKUP")
    digests = {
        name: _sha(report[name], "B04R-RESTORE-FINGERPRINT")
        for name in ("live_digest", "first_restore_digest", "second_restore_digest")
    }
    if (
        digests["live_digest"] != LIVE_EXPECTED_FINGERPRINT_SHA256
        or digests["first_restore_digest"] != digests["second_restore_digest"]
    ):
        raise RestoreEvidenceError("B04R-FIXED-POINT")
    counts = _mapping(report["difference_counts"], "B04R-DIFF-MAP")
    _exact_keys(counts, _DIFFERENCE_COUNT_KEYS, "B04R-DIFF-MAP")
    for count in counts.values():
        _nonnegative_int(count, "B04R-DIFF-MAP")
    _marker_state(report["marker_state"])
    _exact_int(
        report["canonical_table_count"],
        CANONICAL_TABLE_COUNT,
        "B04R-RESTORE-FINGERPRINT",
    )
    _exact_int(
        report["canonical_sequence_count"],
        CANONICAL_SEQUENCE_COUNT,
        "B04R-RESTORE-FINGERPRINT",
    )
    _exact_int(
        report["governed_seed_count"],
        GOVERNED_SEED_COUNT,
        "B04R-RESTORE-FINGERPRINT",
    )
    _hashes(
        report["artifact_sha256"],
        RESTORE_REPORT_ARTIFACTS,
        "B04R-EVIDENCE-INDEX",
    )
    if any(
        report[name] is not True
        for name in (
            "first_restore_equals_second",
            "live_equals_authorizing",
            "typed_diff_equals_map",
        )
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")


def build_pending_restore_index(
    value: Mapping[str, object],
    artifact_sha256: Mapping[str, str],
) -> dict[str, object]:
    """Add the only runner-produced pending restore evidence entry."""
    validate_restore_evidence_index(value)
    if value["evidence_sets"]:
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    hashes = _hashes(
        artifact_sha256,
        RESTORE_EXPECTED_ARTIFACTS,
        "B04R-EVIDENCE-INDEX",
    )
    updated = copy.deepcopy(dict(value))
    updated["evidence_sets"] = [
        {
            "evidence_id": RESTORE_EVIDENCE_ID,
            "status": RestoreEvidenceStatus.CANDIDATE_PENDING_ACCEPTANCE,
            "postgres_major": 18,
            "contract_path": RESTORE_CONTRACT_PATH,
            "artifact_sha256": hashes,
            "acceptance": None,
        }
    ]
    validate_restore_evidence_index(updated)
    return updated


def build_accepted_restore_index(
    value: Mapping[str, object],
    *,
    accepted_at_utc: str,
    accepted_by: str,
    verification_report_sha256: str,
) -> dict[str, object]:
    """Apply an explicit repository-owner acceptance to pending evidence."""
    validate_restore_evidence_index(value)
    entries = value["evidence_sets"]
    if len(entries) != 1:
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    parsed = _parse_restore_entry(entries[0])
    if parsed["status"] is not RestoreEvidenceStatus.CANDIDATE_PENDING_ACCEPTANCE:
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    acceptance = _acceptance(
        {
            "accepted_at_utc": accepted_at_utc,
            "accepted_by": accepted_by,
            "verification_report_sha256": verification_report_sha256,
        }
    )
    if (
        parsed["artifact_sha256"]["verification-report.json"]
        != acceptance["verification_report_sha256"]
    ):
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    updated = copy.deepcopy(dict(value))
    updated["evidence_sets"][0]["status"] = (
        RestoreEvidenceStatus.ACTIVE_RESTORE_AUTHORIZING
    )
    updated["evidence_sets"][0]["acceptance"] = acceptance
    validate_restore_evidence_index(updated)
    return updated


def _canonical_mapping(path: Path, code: str) -> Mapping[str, object]:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RestoreEvidenceError(code) from None
    mapping = _mapping(value, code)
    if canonical_json_bytes(mapping) != data:
        raise RestoreEvidenceError(code)
    return mapping


def _regular_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in relative
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX") from None
    if not resolved.is_file():
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    return resolved


def verify_live_evidence_artifacts(
    live: EvidenceSet,
    artifact_root: Path,
) -> None:
    """Physically hash every artifact named by the accepted live evidence."""
    if artifact_root.is_symlink() or live.contract_path is None:
        raise RestoreEvidenceError("B04R-LIVE-EVIDENCE")
    try:
        root = artifact_root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RestoreEvidenceError("B04R-LIVE-EVIDENCE") from None
    if not root.is_dir():
        raise RestoreEvidenceError("B04R-LIVE-EVIDENCE")
    live_dir = PurePosixPath(live.contract_path).parent
    for name, expected in live.artifact_sha256.items():
        try:
            live_path = _regular_file(root, str(live_dir / name))
        except RestoreEvidenceError:
            raise RestoreEvidenceError("B04R-LIVE-EVIDENCE") from None
        try:
            actual = sha256_hex(live_path.read_bytes())
        except OSError:
            raise RestoreEvidenceError("B04R-LIVE-EVIDENCE") from None
        if actual != expected:
            raise RestoreEvidenceError("B04R-LIVE-EVIDENCE")


def resolve_restore_authorizing_evidence(
    value: Mapping[str, object],
    artifact_root: Path,
    live_index: Mapping[str, object],
) -> RestoreEvidenceSet:
    """Return the sole physically verified active restore evidence set."""
    validate_restore_evidence_index(value)
    entries = value["evidence_sets"]
    if (
        len(entries) != 1
        or entries[0].get("status")
        != RestoreEvidenceStatus.ACTIVE_RESTORE_AUTHORIZING
    ):
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    parsed = _parse_restore_entry(entries[0])
    try:
        live: EvidenceSet = resolve_authorizing_evidence(live_index, artifact_root)
    except (EvidenceError, OSError, ValueError):
        raise RestoreEvidenceError("B04R-LIVE-EVIDENCE") from None
    verify_live_evidence_artifacts(live, artifact_root)
    if artifact_root.is_symlink():
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    try:
        root = artifact_root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX") from None
    if not root.is_dir():
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    restore_dir = PurePosixPath(RESTORE_CONTRACT_PATH).parent
    paths = {
        name: _regular_file(root, str(restore_dir / name))
        for name in RESTORE_EXPECTED_ARTIFACTS
    }
    for name, path in paths.items():
        if sha256_hex(path.read_bytes()) != parsed["artifact_sha256"][name]:
            raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")

    contract = _canonical_mapping(paths["contract.json"], "B04R-EVIDENCE-INDEX")
    fingerprint = _canonical_mapping(
        paths["expected-fingerprint.json"], "B04R-RESTORE-FINGERPRINT"
    )
    try:
        assert_supported_catalog(fingerprint)
        if canonicalize_fingerprint(fingerprint) != paths[
            "expected-fingerprint.json"
        ].read_bytes():
            raise ValueError
        if (
            len(fingerprint["tables"]) != CANONICAL_TABLE_COUNT
            or len(fingerprint["sequences"]) != CANONICAL_SEQUENCE_COUNT
            or fingerprint["seeds"] != seed_manifest()
        ):
            raise ValueError
    except (FingerprintError, KeyError, TypeError, ValueError):
        raise RestoreEvidenceError("B04R-RESTORE-FINGERPRINT") from None
    equivalence = _canonical_mapping(
        paths["equivalence-map.json"], "B04R-DIFF-MAP"
    )
    report = _canonical_mapping(
        paths["verification-report.json"], "B04R-EVIDENCE-INDEX"
    )
    validate_restore_contract(contract)
    validate_equivalence_map(equivalence)
    validate_restore_report(report)

    fingerprint_bytes = paths["expected-fingerprint.json"].read_bytes()
    fingerprint_digest = sha256_hex(fingerprint_bytes)
    expected_sha_line = (
        f"{fingerprint_digest}  expected-fingerprint.json\n".encode("ascii")
    )
    if paths["expected-fingerprint.sha256"].read_bytes() != expected_sha_line:
        raise RestoreEvidenceError("B04R-RESTORE-FINGERPRINT")
    if contract["payload_artifact_sha256"] != {
        name: sha256_hex(paths[name].read_bytes())
        for name in RESTORE_PAYLOAD_ARTIFACTS
    }:
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    if contract["shared_artifact_sha256"] != dict(live.artifact_sha256):
        raise RestoreEvidenceError("B04R-LIVE-EVIDENCE")
    if (
        contract["live_expected_fingerprint_sha256"]
        != live.artifact_sha256["expected-fingerprint.json"]
        or contract["restore_expected_fingerprint_sha256"] != fingerprint_digest
        or contract["equivalence_map_sha256"]
        != sha256_hex(paths["equivalence-map.json"].read_bytes())
    ):
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    if (
        equivalence["live_fingerprint_sha256"]
        != contract["live_expected_fingerprint_sha256"]
        or equivalence["restore_fingerprint_sha256"] != fingerprint_digest
    ):
        raise RestoreEvidenceError("B04R-DIFF-MAP")
    report_hashes = {
        name: sha256_hex(paths[name].read_bytes())
        for name in RESTORE_REPORT_ARTIFACTS
    }
    if report["artifact_sha256"] != report_hashes:
        raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    for name, expected in (
        ("evidence_id", RESTORE_EVIDENCE_ID),
        ("live_evidence_id", PG18_EVIDENCE_ID),
        ("source_sha", contract["source_sha"]),
        ("implementation_sha", contract["implementation_sha"]),
        ("server_version_num", contract["server_version_num"]),
        ("pg_dump_version", contract["pg_dump_version"]),
        ("pg_restore_version", contract["pg_restore_version"]),
        ("live_digest", contract["live_expected_fingerprint_sha256"]),
        ("first_restore_digest", fingerprint_digest),
        ("second_restore_digest", fingerprint_digest),
    ):
        if report[name] != expected:
            raise RestoreEvidenceError("B04R-EVIDENCE-INDEX")
    acceptance = parsed["acceptance"]
    assert isinstance(acceptance, Mapping)
    if (
        acceptance["verification_report_sha256"]
        != sha256_hex(paths["verification-report.json"].read_bytes())
    ):
        raise RestoreEvidenceError("B04R-ACCEPTANCE")
    return RestoreEvidenceSet(
        evidence_id=RESTORE_EVIDENCE_ID,
        status=RestoreEvidenceStatus.ACTIVE_RESTORE_AUTHORIZING,
        postgres_major=18,
        contract_path=RESTORE_CONTRACT_PATH,
        artifact_sha256=MappingProxyType(dict(parsed["artifact_sha256"])),
        acceptance=MappingProxyType(dict(acceptance)),
    )
