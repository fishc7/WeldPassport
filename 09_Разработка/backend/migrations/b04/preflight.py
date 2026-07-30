"""Fail-closed read-only maintenance preflight for B-04B."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePath, PurePosixPath
import re
from typing import Any, Callable, Mapping

from sqlalchemy import text

from migrations.b04.adoption_state import (
    MANDATORY_VERIFICATION_RESULTS,
    PreparedEvidence,
    database_identity_digest,
)
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.evidence import resolve_authorizing_evidence
from migrations.b04.fingerprint import fingerprint_digest
from migrations.b04.manifest import canonical_json_bytes
from migrations.b04.restore_evidence import resolve_restore_authorizing_evidence
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
    SCHEMA_SOURCE_COMMIT,
)


IDENTITY_QUERY = """SELECT
    current_database() AS database,
    inet_server_addr()::text AS host,
    inet_server_port() AS port,
    current_user AS username,
    current_setting('server_version_num')::integer AS server_version_num"""

PRIVILEGE_QUERY = """SELECT
    pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER') AS can_read_all_stats,
    (
        SELECT pg_get_userbyid(c.relowner) = current_user
        FROM pg_class AS c
        WHERE c.oid = to_regclass('test.alembic_version')
    ) AS owns_test_marker,
    has_schema_privilege(current_user, 'public', 'CREATE') AS can_create_public_marker"""

TEST_MARKER_QUERY = "SELECT to_regclass('test.alembic_version')"
TEST_VERSION_QUERY = "SELECT version_num FROM test.alembic_version"
PUBLIC_MARKER_QUERY = "SELECT to_regclass('public.alembic_version')"
READ_ONLY_QUERY = (
    "SELECT current_setting('transaction_read_only') = 'on'"
)

SESSION_QUERY = """SELECT
    count(*) FILTER (WHERE state <> 'idle')::integer AS active_other_sessions,
    count(*) FILTER (
        WHERE state = 'active'
          AND query ~* '(alembic|migration|create|alter|drop|truncate|reindex)'
    )::integer AS active_migration_sessions,
    COALESCE(max(EXTRACT(EPOCH FROM clock_timestamp() - query_start))
        FILTER (WHERE state = 'active'), 0)::integer AS max_active_query_seconds,
    COALESCE(max(EXTRACT(EPOCH FROM clock_timestamp() - xact_start))
        FILTER (WHERE xact_start IS NOT NULL), 0)::integer AS max_transaction_seconds
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()"""


class PreflightError(ValueError):
    """A B-04B preflight prerequisite is absent or mismatched."""


@dataclass(frozen=True, slots=True)
class BackupEvidence:
    backup_path: Path
    backup_sha256: str
    pg_dump_version: str
    restore_report_sha256: str
    restored_server_version_num: int


FingerprintExtractor = Callable[[Any], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class PreflightConfig:
    adoption_id: str
    expected_identity: DatabaseIdentity
    expected_server_version_num: int
    backup_manifest_path: Path
    artifact_root: Path
    live_evidence_index_path: Path
    restore_evidence_index_path: Path
    frozen_manifest_path: Path
    seed_manifest_path: Path
    expected_source_sha: str
    expected_manifest_sha256: str
    expected_fingerprint_sha256: str
    expected_seed_sha256: str
    maintenance_approval_path: Path | None
    maintenance_approval_sha256: str | None
    stopped_writers_evidence_path: Path | None
    stopped_writers_evidence_sha256: str | None
    max_active_query_seconds: int
    max_transaction_seconds: int
    prepared_at_utc: str
    fingerprint_extractor: FingerprintExtractor
    fingerprint_profile: str = "live"


_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_PG_DUMP_18 = re.compile(r"pg_dump \(PostgreSQL\) 18(?:\.[0-9]+)+\Z")
EMPTY_PLATFORM_ALLOWLIST_SHA256 = hashlib.sha256(
    canonical_json_bytes([])
).hexdigest()
_BACKUP_MANIFEST_KEYS = frozenset(
    {
        "format_version",
        "backup_file",
        "backup_sha256",
        "pg_dump_version",
        "restore_report_file",
        "restore_report_sha256",
    }
)
_RESTORE_REPORT_KEYS = frozenset(
    {"status", "backup_sha256", "server_version_num"}
)


def _fail(code: str) -> None:
    raise PreflightError(f"B04-PREFLIGHT-{code}")


def _sha256(path: Path, code: str = "DIGEST") -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        _fail(code)


def _canonical_mapping(path: Path, code: str) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or canonical_json_bytes(value) != raw
    ):
        _fail(code)
    return value


def _safe_child(root: Path, filename: object) -> Path:
    if (
        not isinstance(filename, str)
        or not filename
        or PurePath(filename).name != filename
        or "/" in filename
        or "\\" in filename
    ):
        _fail("BACKUP")
    candidate = root / filename
    if candidate.is_symlink():
        _fail("BACKUP")
    return candidate


def verify_backup_manifest(path: Path) -> BackupEvidence:
    """Verify one canonical external custom-backup and restore record."""

    if path.is_symlink():
        _fail("BACKUP")
    manifest = _canonical_mapping(path, "BACKUP")
    if set(manifest) != _BACKUP_MANIFEST_KEYS or manifest["format_version"] != 1:
        _fail("BACKUP")
    backup = _safe_child(path.parent, manifest["backup_file"])
    restore_report_path = _safe_child(
        path.parent, manifest["restore_report_file"]
    )
    try:
        backup_raw = backup.read_bytes()
    except OSError:
        _fail("BACKUP")
    backup_sha = hashlib.sha256(backup_raw).hexdigest()
    if (
        not backup_raw.startswith(b"PGDMP")
        or not isinstance(manifest["backup_sha256"], str)
        or _SHA64.fullmatch(manifest["backup_sha256"]) is None
        or backup_sha != manifest["backup_sha256"]
        or not isinstance(manifest["pg_dump_version"], str)
        or _PG_DUMP_18.fullmatch(manifest["pg_dump_version"]) is None
    ):
        _fail("BACKUP")

    report = _canonical_mapping(restore_report_path, "BACKUP")
    report_sha = _sha256(restore_report_path)
    if (
        set(report) != _RESTORE_REPORT_KEYS
        or report["status"] != "PG_RESTORE_VERIFIED"
        or report["backup_sha256"] != backup_sha
        or isinstance(report["server_version_num"], bool)
        or not isinstance(report["server_version_num"], int)
        or not isinstance(manifest["restore_report_sha256"], str)
        or _SHA64.fullmatch(manifest["restore_report_sha256"]) is None
        or report_sha != manifest["restore_report_sha256"]
    ):
        _fail("BACKUP")
    return BackupEvidence(
        backup_path=backup,
        backup_sha256=backup_sha,
        pg_dump_version=manifest["pg_dump_version"],
        restore_report_sha256=report_sha,
        restored_server_version_num=report["server_version_num"],
    )


def _load_active_evidence(
    config: PreflightConfig,
) -> tuple[Mapping[str, object], str]:
    if (
        config.live_evidence_index_path
        != config.artifact_root / "evidence-index.json"
        or config.restore_evidence_index_path
        != config.artifact_root / "restore-evidence-index.json"
    ):
        _fail("EVIDENCE")
    try:
        live_index = _canonical_mapping(
            config.live_evidence_index_path, "EVIDENCE"
        )
        restore_index = _canonical_mapping(
            config.restore_evidence_index_path, "EVIDENCE"
        )
        live = resolve_authorizing_evidence(live_index, config.artifact_root)
        restore = resolve_restore_authorizing_evidence(
            restore_index,
            config.artifact_root,
            live_index,
        )
    except (OSError, TypeError, ValueError):
        _fail("EVIDENCE")
    assert live.contract_path is not None
    live_contract = _canonical_mapping(
        config.artifact_root / Path(*PurePosixPath(live.contract_path).parts),
        "EVIDENCE",
    )
    if (
        live_contract.get("source_sha") != SCHEMA_SOURCE_COMMIT
        or live.artifact_sha256["expected-fingerprint.json"]
        != config.expected_fingerprint_sha256
    ):
        _fail("DIGEST")
    if config.fingerprint_profile == "live":
        observed_digest = config.expected_fingerprint_sha256
    elif config.fingerprint_profile == "restored_rehearsal":
        observed_digest = restore.artifact_sha256["expected-fingerprint.json"]
    else:
        _fail("EVIDENCE")
    return live_contract, observed_digest


def _verify_repository_digests(
    config: PreflightConfig,
    live_contract: Mapping[str, object],
) -> None:
    shared = live_contract.get("shared_artifact_sha256")
    expected_frozen = config.artifact_root / "frozen-revision-manifest.json"
    expected_seed = config.artifact_root / "seed-manifest.json"
    if (
        not isinstance(shared, Mapping)
        or config.frozen_manifest_path != expected_frozen
        or config.seed_manifest_path != expected_seed
        or _SHA40.fullmatch(config.expected_source_sha) is None
        or config.expected_source_sha != SCHEMA_SOURCE_COMMIT
        or _SHA64.fullmatch(config.expected_manifest_sha256) is None
        or _SHA64.fullmatch(config.expected_fingerprint_sha256) is None
        or _SHA64.fullmatch(config.expected_seed_sha256) is None
        or _sha256(config.frozen_manifest_path)
        != config.expected_manifest_sha256
        or _sha256(config.seed_manifest_path) != config.expected_seed_sha256
        or shared.get("frozen-revision-manifest.json")
        != config.expected_manifest_sha256
        or shared.get("seed-manifest.json") != config.expected_seed_sha256
    ):
        _fail("DIGEST")
    manifest = _canonical_mapping(config.frozen_manifest_path, "DIGEST")
    if manifest.get("source_commit") != config.expected_source_sha:
        _fail("DIGEST")


def _identity(connection: Any, config: PreflightConfig) -> tuple[DatabaseIdentity, int]:
    row = connection.execute(text(IDENTITY_QUERY)).mappings().one()
    try:
        observed = DatabaseIdentity(
            database=row["database"],
            host=row["host"],
            port=row["port"],
            username=row["username"],
        )
        version = row["server_version_num"]
    except (KeyError, TypeError):
        _fail("IDENTITY")
    if observed != config.expected_identity:
        _fail("IDENTITY")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version // 10000 != 18
        or version != config.expected_server_version_num
    ):
        _fail("POSTGRES")
    return observed, version


def _privileges(connection: Any) -> None:
    row = connection.execute(text(PRIVILEGE_QUERY)).mappings().one()
    if (
        row.get("can_read_all_stats") is not True
        or row.get("owns_test_marker") is not True
        or row.get("can_create_public_marker") is not True
    ):
        _fail("PRIVILEGES")


def _markers(connection: Any) -> None:
    historical = connection.execute(text(TEST_MARKER_QUERY)).scalar_one()
    historical_versions = connection.execute(
        text(TEST_VERSION_QUERY)
    ).scalars().all()
    public = connection.execute(text(PUBLIC_MARKER_QUERY)).scalar_one()
    if (
        historical != "test.alembic_version"
        or historical_versions != [HISTORICAL_HEAD]
        or public is not None
    ):
        _fail("MARKER")


def _sessions(connection: Any, config: PreflightConfig) -> None:
    if (
        config.max_active_query_seconds <= 0
        or config.max_transaction_seconds <= 0
    ):
        _fail("SESSIONS")
    row = connection.execute(text(SESSION_QUERY)).mappings().one()
    if (
        row.get("active_other_sessions") != 0
        or row.get("active_migration_sessions") != 0
        or not isinstance(row.get("max_active_query_seconds"), int)
        or row["max_active_query_seconds"] > config.max_active_query_seconds
        or not isinstance(row.get("max_transaction_seconds"), int)
        or row["max_transaction_seconds"] > config.max_transaction_seconds
    ):
        _fail("SESSIONS")


def _require_read_only(connection: Any) -> None:
    if connection.execute(text(READ_ONLY_QUERY)).scalar_one() is not True:
        _fail("READ-ONLY")


def _verify_operational_evidence(config: PreflightConfig) -> None:
    documents = (
        (
            config.maintenance_approval_path,
            config.maintenance_approval_sha256,
            "APPROVED",
        ),
        (
            config.stopped_writers_evidence_path,
            config.stopped_writers_evidence_sha256,
            "WRITERS_STOPPED",
        ),
    )
    for path, expected_sha, expected_status in documents:
        if (
            path is None
            or expected_sha is None
            or _SHA64.fullmatch(expected_sha) is None
            or _sha256(path, "APPROVAL") != expected_sha
        ):
            _fail("APPROVAL")
        document = _canonical_mapping(path, "APPROVAL")
        if (
            set(document) != {"adoption_id", "status", "target_database"}
            or document["adoption_id"] != config.adoption_id
            or document["status"] != expected_status
            or document["target_database"] != config.expected_identity.database
        ):
            _fail("APPROVAL")


def run_preflight(connection: Any, config: PreflightConfig) -> PreparedEvidence:
    """Run the complete B-04B preflight without issuing a mutating statement."""

    _verify_operational_evidence(config)
    backup = verify_backup_manifest(config.backup_manifest_path)
    live_contract, expected_observed_fingerprint = _load_active_evidence(config)
    _verify_repository_digests(config, live_contract)
    observed_identity, server_version_num = _identity(connection, config)
    if backup.restored_server_version_num != server_version_num:
        _fail("RESTORE-VERSION")
    _privileges(connection)
    _markers(connection)
    _require_read_only(connection)
    _sessions(connection, config)

    try:
        observed_fingerprint = config.fingerprint_extractor(connection)
        observed_digest = fingerprint_digest(observed_fingerprint)
    except Exception:
        _fail("FINGERPRINT")
    if observed_digest != expected_observed_fingerprint:
        _fail("FINGERPRINT")

    return PreparedEvidence(
        adoption_id=config.adoption_id,
        database_identity=DatabaseIdentity(
            database=observed_identity.database,
            host="[redacted]",
            port=observed_identity.port,
            username="[redacted]",
        ),
        source_sha=config.expected_source_sha,
        old_marker=HISTORICAL_HEAD,
        new_marker=BASELINE_REVISION,
        backup_sha256=backup.backup_sha256,
        manifest_sha256=config.expected_manifest_sha256,
        fingerprint_sha256=config.expected_fingerprint_sha256,
        allowlist_sha256=EMPTY_PLATFORM_ALLOWLIST_SHA256,
        seed_sha256=config.expected_seed_sha256,
        database_identity_sha256=database_identity_digest(
            observed_identity,
            server_version_num,
        ),
        server_version_num=server_version_num,
        prepared_at_utc=config.prepared_at_utc,
        verification_results=tuple(
            (key, True) for key in MANDATORY_VERIFICATION_RESULTS
        ),
        observed_fingerprint_sha256=(
            expected_observed_fingerprint
            if config.fingerprint_profile == "restored_rehearsal"
            else None
        ),
    )
