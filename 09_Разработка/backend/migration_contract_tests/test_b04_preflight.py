from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.manifest import canonical_json_bytes
from migrations.b04.preflight import (
    IDENTITY_QUERY,
    PRIVILEGE_QUERY,
    PUBLIC_MARKER_QUERY,
    READ_ONLY_QUERY,
    SESSION_QUERY,
    TEST_MARKER_QUERY,
    TEST_VERSION_QUERY,
    PreflightConfig,
    PreflightError,
    EMPTY_PLATFORM_ALLOWLIST_SHA256,
    run_preflight,
    verify_backup_manifest,
)
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
    SCHEMA_SOURCE_COMMIT,
)


ARTIFACT_ROOT = (
    Path(__file__).parents[1]
    / "migrations"
    / "baselines"
    / "canonical_baseline_v1"
)
LIVE_INDEX = ARTIFACT_ROOT / "evidence-index.json"
RESTORE_INDEX = ARTIFACT_ROOT / "restore-evidence-index.json"
FROZEN_MANIFEST = ARTIFACT_ROOT / "frozen-revision-manifest.json"
SEED_MANIFEST = ARTIFACT_ROOT / "seed-manifest.json"
LIVE_FINGERPRINT = ARTIFACT_ROOT / "postgresql-18" / "expected-fingerprint.json"
RESTORE_FINGERPRINT = (
    ARTIFACT_ROOT
    / "postgresql-18"
    / "restore-roundtrip-v1"
    / "expected-fingerprint.json"
)
class _Result:
    def __init__(
        self,
        *,
        mapping: dict[str, object] | None = None,
        scalars: list[object] | None = None,
    ) -> None:
        self._mapping = mapping
        self._scalars = scalars

    def mappings(self) -> "_Result":
        return self

    def one(self) -> dict[str, object]:
        assert self._mapping is not None
        return self._mapping

    def scalar_one(self) -> object:
        assert self._scalars is not None and len(self._scalars) == 1
        return self._scalars[0]

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        assert self._scalars is not None
        return self._scalars


class _Connection:
    def __init__(self) -> None:
        self.rows: dict[str, _Result] = {
            IDENTITY_QUERY: _Result(
                mapping={
                    "database": "WeldPassport",
                    "host": "db.internal",
                    "port": 5432,
                    "username": "maintenance_operator",
                    "server_version_num": 180003,
                }
            ),
            PRIVILEGE_QUERY: _Result(
                mapping={
                    "can_read_all_stats": True,
                    "owns_test_marker": True,
                    "can_create_public_marker": True,
                }
            ),
            TEST_MARKER_QUERY: _Result(scalars=["test.alembic_version"]),
            TEST_VERSION_QUERY: _Result(scalars=[HISTORICAL_HEAD]),
            PUBLIC_MARKER_QUERY: _Result(scalars=[None]),
            READ_ONLY_QUERY: _Result(scalars=[True]),
            SESSION_QUERY: _Result(
                mapping={
                    "active_other_sessions": 0,
                    "active_migration_sessions": 0,
                    "max_active_query_seconds": 0,
                    "max_transaction_seconds": 0,
                }
            ),
        }
        self.queries: list[str] = []

    def execute(self, statement: Any) -> _Result:
        query = str(statement)
        assert query.lstrip().upper().startswith("SELECT")
        self.queries.append(query)
        return self.rows[query]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup_manifest(tmp_path: Path, *, restore_status: str = "PG_RESTORE_VERIFIED") -> Path:
    backup = tmp_path / "working.dump"
    backup.write_bytes(b"PGDMP\x01\x0f\x00accepted-backup")
    backup_sha = _sha(backup)
    restore_report = tmp_path / "restore-report.json"
    restore_report.write_bytes(
        canonical_json_bytes(
            {
                "backup_sha256": backup_sha,
                "server_version_num": 180003,
                "status": restore_status,
            }
        )
    )
    manifest = tmp_path / "backup-manifest.json"
    manifest.write_bytes(
        canonical_json_bytes(
            {
                "backup_file": backup.name,
                "backup_sha256": backup_sha,
                "format_version": 1,
                "pg_dump_version": "pg_dump (PostgreSQL) 18.3",
                "restore_report_file": restore_report.name,
                "restore_report_sha256": _sha(restore_report),
            }
        )
    )
    return manifest


def _config(tmp_path: Path) -> PreflightConfig:
    maintenance_approval = tmp_path / "maintenance-approval.json"
    maintenance_approval.write_bytes(
        canonical_json_bytes(
            {
                "adoption_id": "b04b-adoption-001",
                "status": "APPROVED",
                "target_database": "WeldPassport",
            }
        )
    )
    stopped_writers = tmp_path / "stopped-writers.json"
    stopped_writers.write_bytes(
        canonical_json_bytes(
            {
                "adoption_id": "b04b-adoption-001",
                "status": "WRITERS_STOPPED",
                "target_database": "WeldPassport",
            }
        )
    )
    return PreflightConfig(
        adoption_id="b04b-adoption-001",
        expected_identity=DatabaseIdentity(
            database="WeldPassport",
            host="db.internal",
            port=5432,
            username="maintenance_operator",
        ),
        expected_server_version_num=180003,
        backup_manifest_path=_backup_manifest(tmp_path),
        artifact_root=ARTIFACT_ROOT,
        live_evidence_index_path=LIVE_INDEX,
        restore_evidence_index_path=RESTORE_INDEX,
        frozen_manifest_path=FROZEN_MANIFEST,
        seed_manifest_path=SEED_MANIFEST,
        expected_source_sha=SCHEMA_SOURCE_COMMIT,
        expected_manifest_sha256=_sha(FROZEN_MANIFEST),
        expected_fingerprint_sha256=_sha(LIVE_FINGERPRINT),
        expected_seed_sha256=_sha(SEED_MANIFEST),
        maintenance_approval_path=maintenance_approval,
        maintenance_approval_sha256=_sha(maintenance_approval),
        stopped_writers_evidence_path=stopped_writers,
        stopped_writers_evidence_sha256=_sha(stopped_writers),
        max_active_query_seconds=30,
        max_transaction_seconds=60,
        prepared_at_utc="2026-07-29T09:30:00Z",
        fingerprint_extractor=lambda _connection: json.loads(
            LIVE_FINGERPRINT.read_bytes()
        ),
    )


def test_b04b_preflight_001_backup_manifest_verifies_custom_backup_and_restore(
    tmp_path: Path,
) -> None:
    manifest = _backup_manifest(tmp_path)

    evidence = verify_backup_manifest(manifest)

    assert evidence.backup_path == tmp_path / "working.dump"
    assert evidence.backup_sha256 == _sha(evidence.backup_path)
    assert evidence.pg_dump_version == "pg_dump (PostgreSQL) 18.3"
    assert evidence.restored_server_version_num == 180003


def test_b04b_preflight_001a_restored_profile_uses_only_authorized_restore_digest(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path),
        fingerprint_profile="restored_rehearsal",
        fingerprint_extractor=lambda _connection: json.loads(
            RESTORE_FINGERPRINT.read_bytes()
        ),
    )

    evidence = run_preflight(_Connection(), config)

    assert evidence.fingerprint_sha256 == _sha(LIVE_FINGERPRINT)
    assert evidence.observed_fingerprint_sha256 == _sha(RESTORE_FINGERPRINT)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_backup",
        "wrong_backup_hash",
        "not_custom_format",
        "missing_restore_report",
        "failed_restore",
    ),
)
def test_b04b_preflight_002_invalid_backup_or_restore_evidence_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest_path = _backup_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_bytes())
    backup = tmp_path / manifest["backup_file"]
    restore_report = tmp_path / manifest["restore_report_file"]
    if mutation == "missing_backup":
        backup.rename(tmp_path / "missing.dump")
    elif mutation == "wrong_backup_hash":
        manifest["backup_sha256"] = "0" * 64
        manifest_path.write_bytes(canonical_json_bytes(manifest))
    elif mutation == "not_custom_format":
        backup.write_bytes(b"not-a-custom-backup")
        manifest["backup_sha256"] = _sha(backup)
        manifest_path.write_bytes(canonical_json_bytes(manifest))
    elif mutation == "missing_restore_report":
        restore_report.rename(tmp_path / "missing-report.json")
    else:
        report = json.loads(restore_report.read_bytes())
        report["status"] = "FAILED"
        restore_report.write_bytes(canonical_json_bytes(report))
        manifest["restore_report_sha256"] = _sha(restore_report)
        manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-BACKUP"):
        verify_backup_manifest(manifest_path)


def test_b04b_preflight_003_success_returns_sanitized_prepared_evidence(
    tmp_path: Path,
) -> None:
    connection = _Connection()

    prepared = run_preflight(connection, _config(tmp_path))

    assert prepared.adoption_id == "b04b-adoption-001"
    assert prepared.database_identity == DatabaseIdentity(
        database="WeldPassport",
        host="[redacted]",
        port=5432,
        username="[redacted]",
    )
    assert prepared.source_sha == SCHEMA_SOURCE_COMMIT
    assert prepared.old_marker == HISTORICAL_HEAD
    assert prepared.new_marker == BASELINE_REVISION
    assert prepared.database_identity_sha256 == hashlib.sha256(
        b'{"database":"WeldPassport","host":"db.internal","port":5432,'
        b'"server_version_num":180003,"username":"maintenance_operator"}\n'
    ).hexdigest()
    assert prepared.server_version_num == 180003
    assert prepared.allowlist_sha256 == EMPTY_PLATFORM_ALLOWLIST_SHA256
    assert prepared.allowlist_sha256 != prepared.fingerprint_sha256
    assert dict(prepared.verification_results) == {
        "active_evidence_verified": True,
        "backup_restore_verified": True,
        "fingerprint_verified": True,
        "marker_verified": True,
        "repository_digests_verified": True,
        "sessions_verified": True,
    }
    assert connection.queries == [
        IDENTITY_QUERY,
        PRIVILEGE_QUERY,
        TEST_MARKER_QUERY,
        TEST_VERSION_QUERY,
        PUBLIC_MARKER_QUERY,
        READ_ONLY_QUERY,
        SESSION_QUERY,
    ]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("database", "other", "IDENTITY"),
        ("server_version_num", 170009, "POSTGRES"),
        ("server_version_num", 180004, "POSTGRES"),
    ),
)
def test_b04b_preflight_004_wrong_identity_or_version_is_rejected(
    tmp_path: Path,
    field: str,
    value: object,
    code: str,
) -> None:
    connection = _Connection()
    identity = connection.rows[IDENTITY_QUERY]._mapping
    assert identity is not None
    identity[field] = value

    with pytest.raises(PreflightError, match=f"B04-PREFLIGHT-{code}"):
        run_preflight(connection, _config(tmp_path))


def test_b04b_preflight_005_restored_version_must_equal_target(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    report_path = tmp_path / "restore-report.json"
    report = json.loads(report_path.read_bytes())
    report["server_version_num"] = 180004
    report_path.write_bytes(canonical_json_bytes(report))
    manifest = json.loads(config.backup_manifest_path.read_bytes())
    manifest["restore_report_sha256"] = _sha(report_path)
    config.backup_manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-RESTORE-VERSION"):
        run_preflight(_Connection(), config)


def test_b04b_preflight_006_missing_active_evidence_is_rejected(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    invalid_index = tmp_path / "evidence-index.json"
    index = json.loads(LIVE_INDEX.read_bytes())
    index["evidence_sets"][1]["status"] = "candidate_pending_acceptance"
    index["evidence_sets"][1]["acceptance"] = None
    invalid_index.write_bytes(canonical_json_bytes(index))

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-EVIDENCE"):
        run_preflight(
            _Connection(),
            replace(config, live_evidence_index_path=invalid_index),
        )


@pytest.mark.parametrize(
    "field",
    (
        "expected_source_sha",
        "expected_manifest_sha256",
        "expected_fingerprint_sha256",
        "expected_seed_sha256",
    ),
)
def test_b04b_preflight_007_repository_digest_mismatch_is_rejected(
    tmp_path: Path,
    field: str,
) -> None:
    config = replace(_config(tmp_path), **{field: "0" * (40 if field == "expected_source_sha" else 64)})

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-DIGEST"):
        run_preflight(_Connection(), config)


@pytest.mark.parametrize(
    ("query", "replacement"),
    (
        (TEST_MARKER_QUERY, _Result(scalars=[None])),
        (TEST_VERSION_QUERY, _Result(scalars=[])),
        (TEST_VERSION_QUERY, _Result(scalars=[HISTORICAL_HEAD, HISTORICAL_HEAD])),
        (PUBLIC_MARKER_QUERY, _Result(scalars=["public.alembic_version"])),
    ),
)
def test_b04b_preflight_008_marker_state_must_be_exact(
    tmp_path: Path,
    query: str,
    replacement: _Result,
) -> None:
    connection = _Connection()
    connection.rows[query] = replacement

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-MARKER"):
        run_preflight(connection, _config(tmp_path))


def test_b04b_preflight_009_live_fingerprint_must_match_authorizing_digest(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path),
        fingerprint_extractor=lambda _connection: {
            "format_version": 2,
            "schemas": [],
            "tables": [],
            "sequences": [],
            "seeds": [],
        },
    )

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-FINGERPRINT"):
        run_preflight(_Connection(), config)


def test_b04b_preflight_010_unknown_canonical_object_is_rejected(
    tmp_path: Path,
) -> None:
    config = replace(
        _config(tmp_path),
        fingerprint_extractor=lambda _connection: {
            "format_version": 2,
            "schemas": [],
            "tables": [],
            "sequences": [],
            "seeds": [],
            "unknown": [],
        },
    )

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-FINGERPRINT"):
        run_preflight(_Connection(), config)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("active_migration_sessions", 1),
        ("active_other_sessions", 1),
        ("max_active_query_seconds", 31),
        ("max_transaction_seconds", 61),
    ),
)
def test_b04b_preflight_011_active_ddl_or_long_transaction_is_rejected(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    connection = _Connection()
    session_state = {
        "active_other_sessions": 0,
        "active_migration_sessions": 0,
        "max_active_query_seconds": 0,
        "max_transaction_seconds": 0,
    }
    session_state[field] = value
    connection.rows[SESSION_QUERY] = _Result(
        mapping=session_state
    )

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-SESSIONS"):
        run_preflight(connection, _config(tmp_path))


@pytest.mark.parametrize(
    "field",
    ("maintenance_approval_sha256", "stopped_writers_evidence_sha256"),
)
def test_b04b_preflight_012_approval_and_stopped_writers_are_required(
    tmp_path: Path,
    field: str,
) -> None:
    config = replace(_config(tmp_path), **{field: None})

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-APPROVAL"):
        run_preflight(_Connection(), config)


@pytest.mark.parametrize(
    "field",
    ("can_read_all_stats", "owns_test_marker", "can_create_public_marker"),
)
def test_b04b_preflight_013_stats_visibility_and_marker_privileges_are_required(
    tmp_path: Path,
    field: str,
) -> None:
    connection = _Connection()
    privileges = connection.rows[PRIVILEGE_QUERY]._mapping
    assert privileges is not None
    privileges[field] = False

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-PRIVILEGES"):
        run_preflight(connection, _config(tmp_path))


def test_b04b_preflight_014_connection_must_already_be_read_only(
    tmp_path: Path,
) -> None:
    connection = _Connection()
    connection.rows[READ_ONLY_QUERY] = _Result(scalars=[False])

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-READ-ONLY"):
        run_preflight(connection, _config(tmp_path))


@pytest.mark.parametrize(
    "field",
    ("maintenance_approval_path", "stopped_writers_evidence_path"),
)
def test_b04b_preflight_015_operational_evidence_must_exist_and_match_digest(
    tmp_path: Path,
    field: str,
) -> None:
    config = replace(_config(tmp_path), **{field: tmp_path / "missing.json"})

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-APPROVAL"):
        run_preflight(_Connection(), config)


@pytest.mark.parametrize(
    ("path_field", "digest_field"),
    (
        ("frozen_manifest_path", "expected_manifest_sha256"),
        ("seed_manifest_path", "expected_seed_sha256"),
    ),
)
def test_b04b_preflight_016_self_consistent_external_artifact_is_rejected(
    tmp_path: Path,
    path_field: str,
    digest_field: str,
) -> None:
    external = tmp_path / f"{path_field}.json"
    external.write_bytes(
        FROZEN_MANIFEST.read_bytes()
        if path_field == "frozen_manifest_path"
        else SEED_MANIFEST.read_bytes()
    )
    config = replace(
        _config(tmp_path),
        **{path_field: external, digest_field: _sha(external)},
    )

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-DIGEST"):
        run_preflight(_Connection(), config)


@pytest.mark.parametrize(
    "field",
    ("live_evidence_index_path", "restore_evidence_index_path"),
)
def test_b04b_preflight_017_external_evidence_index_copy_is_rejected(
    tmp_path: Path,
    field: str,
) -> None:
    source = LIVE_INDEX if field == "live_evidence_index_path" else RESTORE_INDEX
    external = tmp_path / source.name
    external.write_bytes(source.read_bytes())

    with pytest.raises(PreflightError, match="B04-PREFLIGHT-EVIDENCE"):
        run_preflight(
            _Connection(),
            replace(_config(tmp_path), **{field: external}),
        )
