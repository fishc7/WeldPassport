"""Explicit-input, fail-closed B-04R restore-roundtrip verification."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from migrations.b04.disposable import (
    DatabaseIdentity,
    assert_disposable_database,
)
from migrations.b04.evidence import (
    EvidenceError,
    EvidenceSet,
    resolve_authorizing_evidence,
)
from migrations.b04.fingerprint import (
    canonicalize_fingerprint,
    extract_fingerprint,
)
from migrations.b04.restore_evidence import (
    CANONICAL_SEQUENCE_COUNT,
    GOVERNED_SEED_COUNT,
    HISTORICAL_MARKER,
    LIVE_EXPECTED_FINGERPRINT_SHA256,
    RESTORE_EVIDENCE_ID,
    RESTORE_EXPECTED_ARTIFACTS,
    RestoreEvidenceError,
    assert_typed_equivalence,
    build_pending_restore_index,
    build_typed_equivalence_map,
    validate_equivalence_map,
    validate_restore_contract,
    validate_restore_evidence_index,
    validate_restore_report,
    verify_live_evidence_artifacts,
)
from migrations.b04.manifest import canonical_json_bytes, sha256_hex
from migrations.b04.source_contract import (
    CANONICAL_TABLE_COUNT,
    SCHEMA_SOURCE_COMMIT,
)


FIRST_RESTORE_DATABASE = "wp_b04_r18_restore_first_disposable"
SECOND_RESTORE_DATABASE = "wp_b04_r18_restore_second_disposable"
SERVER_VERSION_NUM = 180003

_ENV_NAMES = (
    "WELDPASSPORT_B04R_WORKING_URL",
    "WELDPASSPORT_B04R_FIRST_URL",
    "WELDPASSPORT_B04R_SECOND_URL",
    "WELDPASSPORT_B04R_ALLOW_DESTRUCTIVE",
    "WELDPASSPORT_B04R_OWNERSHIP_TOKEN",
    "WELDPASSPORT_B04R_FIRST_EXPECTED_DATABASE",
    "WELDPASSPORT_B04R_SECOND_EXPECTED_DATABASE",
    "WELDPASSPORT_B04R_BACKUP_PATH",
    "WELDPASSPORT_B04R_ARTIFACT_ROOT",
    "WELDPASSPORT_B04R_IMPLEMENTATION_SHA",
    "WELDPASSPORT_B04R_PG_DUMP_EXE",
    "WELDPASSPORT_B04R_PG_RESTORE_EXE",
    "WELDPASSPORT_B04R_EXPECTED_PG_DUMP_VERSION",
    "WELDPASSPORT_B04R_EXPECTED_PG_RESTORE_VERSION",
)
_OWNER_SQL = (
    "SELECT pg_get_userbyid(datdba) = current_user "
    "FROM pg_database WHERE datname = current_database()"
)
_EMPTY_SQL = (
    "SELECT count(*) FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
    "AND n.nspname NOT LIKE 'pg_toast%' "
    "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
)


class RestoreVerificationError(RuntimeError):
    """One stable B-04R verification phase failed."""


ConnectionFactory = Callable[[str], AbstractContextManager[Any]]
SafetyValidator = Callable[..., DatabaseIdentity]
VersionProbe = Callable[[str], str]
FingerprintExtractor = Callable[[Any], Mapping[str, object]]
FingerprintSerializer = Callable[[Mapping[str, object]], bytes]
CommandRunner = Callable[[tuple[str, ...], Mapping[str, str], str], None]
TemporaryArchiveFactory = Callable[[Path], Path]
TemporaryWriter = Callable[[Path, bytes], Path]
ArtifactLinker = Callable[[Path, Path], None]
IndexReplacer = Callable[[Path, Path], None]


def _connect(url: str) -> AbstractContextManager[Any]:
    return create_engine(
        url,
        future=True,
        connect_args={"connect_timeout": 10},
    ).connect()


def _probe_version(executable: str) -> str:
    environment: dict[str, str] = {}
    if os.name == "nt":
        systemroot = os.environ.get("SYSTEMROOT")
        if not systemroot:
            raise RestoreVerificationError("B04R-TOOL-VERSION")
        environment["SYSTEMROOT"] = systemroot
    try:
        result = subprocess.run(
            (executable, "--version"),
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        raise RestoreVerificationError("B04R-TOOL-VERSION") from None
    return result.stdout.strip()


def _run_command(
    command: tuple[str, ...],
    environment: Mapping[str, str],
    _: str,
) -> None:
    subprocess.run(
        command,
        env=dict(environment),
        check=True,
        capture_output=True,
        timeout=300,
    )


def _temporary_archive(parent: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=".b04r-roundtrip-",
        suffix=".dump",
        dir=parent,
    )
    os.close(descriptor)
    return Path(name)


def _write_temporary(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _hard_link_no_clobber(source: Path, target: Path) -> None:
    os.link(source, target)


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    database: str
    server_version_num: int
    transaction_read_only: str
    historical_marker: str
    public_marker: str | None
    fingerprint: Mapping[str, object]
    fingerprint_bytes: bytes
    fingerprint_digest: str
    canonical_table_count: int
    canonical_sequence_count: int
    governed_seed_count: int


@dataclass(frozen=True, slots=True)
class PreflightResult:
    working: DatabaseSnapshot
    first_identity: DatabaseIdentity
    second_identity: DatabaseIdentity
    pg_dump_version: str
    pg_restore_version: str
    live_evidence: EvidenceSet


@dataclass(frozen=True, slots=True)
class RestoreRoundtripResult:
    working: DatabaseSnapshot
    first_restore: DatabaseSnapshot
    second_restore: DatabaseSnapshot
    backup_sha256: str
    pg_dump_version: str
    pg_restore_version: str
    equivalence_map: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RestoreVerificationReport:
    status: str
    evidence_id: str
    live_evidence_id: str
    source_sha: str
    implementation_sha: str
    postgres_major: int
    server_version_num: int
    pg_dump_version: str
    pg_restore_version: str
    working_database: str
    first_restore_database: str
    second_restore_database: str
    backup_sha256: str
    live_digest: str
    first_restore_digest: str
    second_restore_digest: str
    difference_counts: Mapping[str, int]
    marker_state: Mapping[str, Mapping[str, str | None]]
    canonical_table_count: int
    canonical_sequence_count: int
    governed_seed_count: int
    artifact_sha256: Mapping[str, str]
    first_restore_equals_second: bool
    live_equals_authorizing: bool
    typed_diff_equals_map: bool


@dataclass(slots=True)
class RestoreVerificationConfig:
    working_url: str
    first_url: str
    second_url: str
    destructive_opt_in: str | None
    ownership_token: str | None
    first_expected_database: str
    second_expected_database: str
    backup_path: Path
    artifact_root: Path
    implementation_sha: str
    pg_dump_executable: str
    pg_restore_executable: str
    expected_pg_dump_version: str
    expected_pg_restore_version: str
    connection_factory: ConnectionFactory = _connect
    safety_validator: SafetyValidator = assert_disposable_database
    version_probe: VersionProbe = _probe_version
    fingerprint_extractor: FingerprintExtractor = extract_fingerprint
    fingerprint_serializer: FingerprintSerializer = canonicalize_fingerprint
    command_runner: CommandRunner = _run_command
    temporary_archive_factory: TemporaryArchiveFactory = _temporary_archive
    temporary_writer: TemporaryWriter = _write_temporary
    artifact_linker: ArtifactLinker = _hard_link_no_clobber
    index_replacer: IndexReplacer = os.replace

    @classmethod
    def environment_names(cls) -> tuple[str, ...]:
        return _ENV_NAMES

    @classmethod
    def from_environment(cls) -> RestoreVerificationConfig:
        values = {name: os.environ.get(name) for name in _ENV_NAMES}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise RestoreVerificationError("B04R-EVIDENCE-INDEX")
        return cls(
            working_url=str(values["WELDPASSPORT_B04R_WORKING_URL"]),
            first_url=str(values["WELDPASSPORT_B04R_FIRST_URL"]),
            second_url=str(values["WELDPASSPORT_B04R_SECOND_URL"]),
            destructive_opt_in=values[
                "WELDPASSPORT_B04R_ALLOW_DESTRUCTIVE"
            ],
            ownership_token=values["WELDPASSPORT_B04R_OWNERSHIP_TOKEN"],
            first_expected_database=str(
                values["WELDPASSPORT_B04R_FIRST_EXPECTED_DATABASE"]
            ),
            second_expected_database=str(
                values["WELDPASSPORT_B04R_SECOND_EXPECTED_DATABASE"]
            ),
            backup_path=Path(str(values["WELDPASSPORT_B04R_BACKUP_PATH"])),
            artifact_root=Path(
                str(values["WELDPASSPORT_B04R_ARTIFACT_ROOT"])
            ),
            implementation_sha=str(
                values["WELDPASSPORT_B04R_IMPLEMENTATION_SHA"]
            ),
            pg_dump_executable=str(
                values["WELDPASSPORT_B04R_PG_DUMP_EXE"]
            ),
            pg_restore_executable=str(
                values["WELDPASSPORT_B04R_PG_RESTORE_EXE"]
            ),
            expected_pg_dump_version=str(
                values["WELDPASSPORT_B04R_EXPECTED_PG_DUMP_VERSION"]
            ),
            expected_pg_restore_version=str(
                values["WELDPASSPORT_B04R_EXPECTED_PG_RESTORE_VERSION"]
            ),
        )


def _scalar(connection: Any, statement: str) -> object:
    return connection.exec_driver_sql(statement).scalar_one()


def _seed_count(fingerprint: Mapping[str, object]) -> int:
    try:
        seeds = fingerprint["seeds"]
        if not isinstance(seeds, Mapping):
            raise TypeError
        tables = seeds["tables"]
        if not isinstance(tables, list):
            raise TypeError
        return sum(
            len(table["rows"])
            for table in tables
            if isinstance(table, Mapping) and isinstance(table.get("rows"), list)
        )
    except (KeyError, TypeError):
        raise RestoreVerificationError("B04R-RESTORE-FINGERPRINT") from None


def read_working_snapshot(
    connection: Any,
    *,
    fingerprint_extractor: FingerprintExtractor,
    fingerprint_serializer: FingerprintSerializer = canonicalize_fingerprint,
) -> DatabaseSnapshot:
    """Read one complete working snapshot after the mandatory read-only BEGIN."""
    try:
        connection.exec_driver_sql(
            "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        transaction_read_only = _scalar(connection, "SHOW transaction_read_only")
        if transaction_read_only != "on":
            raise RestoreVerificationError("B04R-WORKING-READONLY")
        raw_version = _scalar(connection, "SHOW server_version_num")
        if str(raw_version) != str(SERVER_VERSION_NUM):
            raise RestoreVerificationError("B04R-SERVER-VERSION")
        database = _scalar(connection, "SELECT current_database()")
        marker = _scalar(
            connection, "SELECT version_num FROM test.alembic_version"
        )
        public_marker = connection.exec_driver_sql(
            "SELECT to_regclass('public.alembic_version')"
        ).scalar_one_or_none()
        fingerprint = fingerprint_extractor(connection)
        fingerprint_bytes = fingerprint_serializer(fingerprint)
    except RestoreVerificationError:
        raise
    except Exception:
        raise RestoreVerificationError("B04R-WORKING-FINGERPRINT") from None
    if (
        not isinstance(database, str)
        or not database
        or marker != HISTORICAL_MARKER
        or public_marker is not None
    ):
        raise RestoreVerificationError("B04R-WORKING-FINGERPRINT")
    tables = fingerprint.get("tables")
    sequences = fingerprint.get("sequences")
    if (
        not isinstance(tables, list)
        or len(tables) != CANONICAL_TABLE_COUNT
        or not isinstance(sequences, list)
        or len(sequences) != CANONICAL_SEQUENCE_COUNT
        or _seed_count(fingerprint) != GOVERNED_SEED_COUNT
    ):
        raise RestoreVerificationError("B04R-WORKING-FINGERPRINT")
    return DatabaseSnapshot(
        database=database,
        server_version_num=SERVER_VERSION_NUM,
        transaction_read_only="on",
        historical_marker=HISTORICAL_MARKER,
        public_marker=None,
        fingerprint=fingerprint,
        fingerprint_bytes=fingerprint_bytes,
        fingerprint_digest=hashlib.sha256(fingerprint_bytes).hexdigest(),
        canonical_table_count=CANONICAL_TABLE_COUNT,
        canonical_sequence_count=CANONICAL_SEQUENCE_COUNT,
        governed_seed_count=GOVERNED_SEED_COUNT,
    )


def _load_live_index(root: Path) -> Mapping[str, object]:
    path = root / "evidence-index.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RestoreVerificationError("B04R-LIVE-EVIDENCE") from None
    if not isinstance(value, Mapping):
        raise RestoreVerificationError("B04R-LIVE-EVIDENCE")
    return value


def _checked_disposable_identity(
    config: RestoreVerificationConfig,
    url: str,
    expected_database: str,
) -> DatabaseIdentity:
    try:
        return config.safety_validator(
            url,
            opt_in=config.destructive_opt_in,
            ownership_token=config.ownership_token,
            expected_database=expected_database,
        )
    except Exception:
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY") from None


def _preflight_disposable_connection(
    config: RestoreVerificationConfig,
    url: str,
    identity: DatabaseIdentity,
) -> None:
    try:
        with config.connection_factory(url) as connection:
            version = _scalar(connection, "SHOW server_version_num")
            database = _scalar(connection, "SELECT current_database()")
            owner = _scalar(connection, _OWNER_SQL)
            relation_count = _scalar(connection, _EMPTY_SQL)
    except Exception:
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY") from None
    if str(version) != str(SERVER_VERSION_NUM):
        raise RestoreVerificationError("B04R-SERVER-VERSION")
    if (
        database != identity.database
        or owner is not True
        or isinstance(relation_count, bool)
        or relation_count != 0
    ):
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY")


def _working_identity(config: RestoreVerificationConfig) -> DatabaseIdentity:
    try:
        url = make_url(config.working_url)
        if (
            url.drivername != "postgresql+psycopg"
            or not isinstance(url.host, str)
            or not isinstance(url.port, int)
            or not isinstance(url.username, str)
            or not isinstance(url.database, str)
        ):
            raise ValueError
        return DatabaseIdentity(
            database=url.database,
            host=url.host,
            port=url.port,
            username=url.username,
        )
    except Exception:
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY") from None


def preflight_restore_verification(
    config: RestoreVerificationConfig,
) -> PreflightResult:
    """Perform all read-only and disposable checks before any restore command."""
    if (
        config.first_expected_database != FIRST_RESTORE_DATABASE
        or config.second_expected_database != SECOND_RESTORE_DATABASE
        or len(config.implementation_sha) != 40
        or any(character not in "0123456789abcdef" for character in config.implementation_sha)
    ):
        raise RestoreVerificationError("B04R-EVIDENCE-INDEX")
    try:
        live = resolve_authorizing_evidence(
            _load_live_index(config.artifact_root),
            config.artifact_root,
        )
    except (EvidenceError, RestoreEvidenceError, ValueError):
        raise RestoreVerificationError("B04R-LIVE-EVIDENCE") from None
    try:
        verify_live_evidence_artifacts(live, config.artifact_root)
    except (RestoreEvidenceError, OSError):
        raise RestoreVerificationError("B04R-LIVE-EVIDENCE") from None
    try:
        pg_dump_version = config.version_probe(config.pg_dump_executable)
        pg_restore_version = config.version_probe(config.pg_restore_executable)
    except Exception:
        raise RestoreVerificationError("B04R-TOOL-VERSION") from None
    if (
        pg_dump_version != config.expected_pg_dump_version
        or pg_restore_version != config.expected_pg_restore_version
    ):
        raise RestoreVerificationError("B04R-TOOL-VERSION")

    try:
        with config.connection_factory(config.working_url) as connection:
            working = read_working_snapshot(
                connection,
                fingerprint_extractor=config.fingerprint_extractor,
                fingerprint_serializer=config.fingerprint_serializer,
            )
    except RestoreVerificationError:
        raise
    except Exception:
        raise RestoreVerificationError("B04R-WORKING-FINGERPRINT") from None
    if (
        working.fingerprint_digest
        != live.artifact_sha256["expected-fingerprint.json"]
        or working.fingerprint_digest != LIVE_EXPECTED_FINGERPRINT_SHA256
    ):
        raise RestoreVerificationError("B04R-WORKING-FINGERPRINT")

    first = _checked_disposable_identity(
        config, config.first_url, config.first_expected_database
    )
    second = _checked_disposable_identity(
        config, config.second_url, config.second_expected_database
    )
    working_identity = _working_identity(config)
    if (
        working.database != working_identity.database
        or first == second
        or working_identity in {first, second}
        or first.database == working.database
        or second.database == working.database
    ):
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY")
    _preflight_disposable_connection(config, config.first_url, first)
    _preflight_disposable_connection(config, config.second_url, second)
    return PreflightResult(
        working=working,
        first_identity=first,
        second_identity=second,
        pg_dump_version=pg_dump_version,
        pg_restore_version=pg_restore_version,
        live_evidence=live,
    )


def _system_environment() -> dict[str, str]:
    environment: dict[str, str] = {}
    if os.name == "nt":
        systemroot = os.environ.get("SYSTEMROOT")
        if not systemroot:
            raise RestoreVerificationError("B04R-TOOL-VERSION")
        environment["SYSTEMROOT"] = systemroot
    return environment


def _database_environment(url: str) -> dict[str, str]:
    try:
        parsed = make_url(url)
        values = {
            "PGHOST": parsed.host,
            "PGPORT": str(parsed.port),
            "PGDATABASE": parsed.database,
            "PGUSER": parsed.username,
            "PGPASSWORD": parsed.password,
        }
    except Exception:
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY") from None
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise RestoreVerificationError("B04R-DISPOSABLE-SAFETY")
    return {**_system_environment(), **values}  # type: ignore[arg-type]


def _run_tool(
    config: RestoreVerificationConfig,
    command: tuple[str, ...],
    environment: Mapping[str, str],
    phase: str,
    failure_code: str,
) -> None:
    try:
        config.command_runner(command, environment, phase)
    except Exception:
        raise RestoreVerificationError(failure_code) from None


def _read_restored_snapshot(
    config: RestoreVerificationConfig,
    url: str,
) -> DatabaseSnapshot:
    try:
        with config.connection_factory(url) as connection:
            return read_working_snapshot(
                connection,
                fingerprint_extractor=config.fingerprint_extractor,
                fingerprint_serializer=config.fingerprint_serializer,
            )
    except RestoreVerificationError:
        raise RestoreVerificationError("B04R-RESTORE-FINGERPRINT") from None
    except Exception:
        raise RestoreVerificationError("B04R-RESTORE-FINGERPRINT") from None


def _assert_fixed_point(
    first: DatabaseSnapshot,
    second: DatabaseSnapshot,
) -> None:
    if (
        first.server_version_num != second.server_version_num
        or first.historical_marker != second.historical_marker
        or first.public_marker != second.public_marker
        or first.fingerprint_bytes != second.fingerprint_bytes
        or first.fingerprint_digest != second.fingerprint_digest
        or first.canonical_table_count != second.canonical_table_count
        or first.canonical_sequence_count != second.canonical_sequence_count
        or first.governed_seed_count != second.governed_seed_count
    ):
        raise RestoreVerificationError("B04R-FIXED-POINT")


def _canonical_fingerprint_mapping(snapshot: DatabaseSnapshot) -> Mapping[str, object]:
    try:
        value = json.loads(snapshot.fingerprint_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RestoreVerificationError("B04R-RESTORE-FINGERPRINT") from None
    if not isinstance(value, Mapping):
        raise RestoreVerificationError("B04R-RESTORE-FINGERPRINT")
    return value


def execute_restore_roundtrip(
    config: RestoreVerificationConfig,
    preflight: PreflightResult,
) -> RestoreRoundtripResult:
    """Restore twice, prove a fixed point and return in-memory evidence only."""
    backup = config.backup_path
    if backup.is_symlink() or not backup.is_file():
        raise RestoreVerificationError("B04R-BACKUP")
    try:
        backup_bytes = backup.read_bytes()
    except OSError:
        raise RestoreVerificationError("B04R-BACKUP") from None
    if not backup_bytes:
        raise RestoreVerificationError("B04R-BACKUP")
    backup_sha256 = hashlib.sha256(backup_bytes).hexdigest()

    _run_tool(
        config,
        (config.pg_restore_executable, "--list", str(backup)),
        _system_environment(),
        "backup-list",
        "B04R-BACKUP",
    )
    _run_tool(
        config,
        (
            config.pg_restore_executable,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--dbname={preflight.first_identity.database}",
            str(backup),
        ),
        _database_environment(config.first_url),
        "first-restore",
        "B04R-RESTORE",
    )
    first = _read_restored_snapshot(config, config.first_url)

    temporary: Path | None = None
    try:
        temporary = config.temporary_archive_factory(
            config.artifact_root.parent
        )
        if temporary.is_symlink():
            raise RestoreVerificationError("B04R-BACKUP")
        _run_tool(
            config,
            (
                config.pg_dump_executable,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={temporary}",
                f"--dbname={preflight.first_identity.database}",
            ),
            _database_environment(config.first_url),
            "second-dump",
            "B04R-RESTORE",
        )
        if temporary.is_symlink() or not temporary.is_file() or temporary.stat().st_size == 0:
            raise RestoreVerificationError("B04R-RESTORE")
        _run_tool(
            config,
            (
                config.pg_restore_executable,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                f"--dbname={preflight.second_identity.database}",
                str(temporary),
            ),
            _database_environment(config.second_url),
            "second-restore",
            "B04R-RESTORE",
        )
        second = _read_restored_snapshot(config, config.second_url)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    _assert_fixed_point(first, second)
    live_mapping = _canonical_fingerprint_mapping(preflight.working)
    first_mapping = _canonical_fingerprint_mapping(first)
    second_mapping = _canonical_fingerprint_mapping(second)
    try:
        equivalence = build_typed_equivalence_map(live_mapping, first_mapping)
        assert_typed_equivalence(live_mapping, second_mapping, equivalence)
    except RestoreEvidenceError as exc:
        code = str(exc)
        if code not in {"B04R-DIFF-KIND", "B04R-DIFF-MAP"}:
            code = "B04R-DIFF-MAP"
        raise RestoreVerificationError(code) from None
    return RestoreRoundtripResult(
        working=preflight.working,
        first_restore=first,
        second_restore=second,
        backup_sha256=backup_sha256,
        pg_dump_version=preflight.pg_dump_version,
        pg_restore_version=preflight.pg_restore_version,
        equivalence_map=equivalence,
    )


def _canonical_index(path: Path) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH") from None
    if (
        not isinstance(value, Mapping)
        or canonical_json_bytes(value) != raw
    ):
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH")
    try:
        validate_restore_evidence_index(value)
    except RestoreEvidenceError:
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH") from None
    return value


def _preflight_publication(
    config: RestoreVerificationConfig,
) -> tuple[Mapping[str, object], dict[str, Path]]:
    root = config.artifact_root
    live_dir = root / "postgresql-18"
    restore_dir = live_dir / "restore-roundtrip-v1"
    index_path = root / "restore-evidence-index.json"
    if (
        root.is_symlink()
        or live_dir.is_symlink()
        or index_path.is_symlink()
        or not root.is_dir()
        or not live_dir.is_dir()
        or restore_dir.exists()
    ):
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH")
    index = _canonical_index(index_path)
    if index["evidence_sets"]:
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH")
    targets = {
        name: restore_dir / name for name in RESTORE_EXPECTED_ARTIFACTS
    }
    if any(path.exists() or path.is_symlink() for path in targets.values()):
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH")
    return index, targets


def _marker_state(snapshot: DatabaseSnapshot) -> dict[str, str | None]:
    return {
        "historical_marker": snapshot.historical_marker,
        "public_marker": snapshot.public_marker,
    }


def _difference_counts(
    equivalence_map: Mapping[str, object],
) -> dict[str, int]:
    counts = {
        "check_definition_deparser_roundtrip": 0,
        "index_predicate_deparser_roundtrip": 0,
    }
    differences = equivalence_map["differences"]
    assert isinstance(differences, list)
    for item in differences:
        assert isinstance(item, Mapping)
        kind = item["kind"]
        assert isinstance(kind, str)
        counts[kind] += 1
    return counts


def _build_artifacts(
    config: RestoreVerificationConfig,
    preflight: PreflightResult,
    result: RestoreRoundtripResult,
) -> tuple[dict[str, bytes], RestoreVerificationReport]:
    fingerprint_bytes = result.first_restore.fingerprint_bytes
    restore_digest = result.first_restore.fingerprint_digest
    sha_bytes = (
        f"{restore_digest}  expected-fingerprint.json\n".encode("ascii")
    )
    equivalence = dict(result.equivalence_map)
    validate_equivalence_map(equivalence)
    equivalence_bytes = canonical_json_bytes(equivalence)
    payload_hashes = {
        "expected-fingerprint.json": sha256_hex(fingerprint_bytes),
        "expected-fingerprint.sha256": sha256_hex(sha_bytes),
        "equivalence-map.json": sha256_hex(equivalence_bytes),
    }
    contract: dict[str, object] = {
        "evidence_id": RESTORE_EVIDENCE_ID,
        "baseline_id": "canonical_baseline_v1",
        "live_evidence_id": preflight.live_evidence.evidence_id,
        "source_sha": SCHEMA_SOURCE_COMMIT,
        "implementation_sha": config.implementation_sha,
        "postgres_major": 18,
        "server_version_num": SERVER_VERSION_NUM,
        "pg_dump_version": result.pg_dump_version,
        "pg_restore_version": result.pg_restore_version,
        "live_fingerprint_format_version": 2,
        "restore_fingerprint_format_version": 2,
        "live_expected_fingerprint_sha256": result.working.fingerprint_digest,
        "restore_expected_fingerprint_sha256": restore_digest,
        "equivalence_map_sha256": payload_hashes["equivalence-map.json"],
        "shared_artifact_sha256": dict(
            preflight.live_evidence.artifact_sha256
        ),
        "payload_artifact_sha256": payload_hashes,
        "canonical_table_count": result.first_restore.canonical_table_count,
        "canonical_sequence_count": result.first_restore.canonical_sequence_count,
        "governed_seed_count": result.first_restore.governed_seed_count,
        "expected_artifacts": list(RESTORE_EXPECTED_ARTIFACTS),
    }
    validate_restore_contract(contract)
    contract_bytes = canonical_json_bytes(contract)
    report_artifact_hashes = {
        "contract.json": sha256_hex(contract_bytes),
        **payload_hashes,
    }
    report = RestoreVerificationReport(
        status="B04_RESTORE_ROUNDTRIP_VERIFIED",
        evidence_id=RESTORE_EVIDENCE_ID,
        live_evidence_id=preflight.live_evidence.evidence_id,
        source_sha=SCHEMA_SOURCE_COMMIT,
        implementation_sha=config.implementation_sha,
        postgres_major=18,
        server_version_num=SERVER_VERSION_NUM,
        pg_dump_version=result.pg_dump_version,
        pg_restore_version=result.pg_restore_version,
        working_database=result.working.database,
        first_restore_database=result.first_restore.database,
        second_restore_database=result.second_restore.database,
        backup_sha256=result.backup_sha256,
        live_digest=result.working.fingerprint_digest,
        first_restore_digest=result.first_restore.fingerprint_digest,
        second_restore_digest=result.second_restore.fingerprint_digest,
        difference_counts=_difference_counts(equivalence),
        marker_state={
            "working": _marker_state(result.working),
            "first_restore": _marker_state(result.first_restore),
            "second_restore": _marker_state(result.second_restore),
        },
        canonical_table_count=result.first_restore.canonical_table_count,
        canonical_sequence_count=result.first_restore.canonical_sequence_count,
        governed_seed_count=result.first_restore.governed_seed_count,
        artifact_sha256=report_artifact_hashes,
        first_restore_equals_second=(
            result.first_restore.fingerprint_bytes
            == result.second_restore.fingerprint_bytes
        ),
        live_equals_authorizing=(
            result.working.fingerprint_digest
            == preflight.live_evidence.artifact_sha256[
                "expected-fingerprint.json"
            ]
        ),
        typed_diff_equals_map=True,
    )
    validate_restore_report(asdict(report))
    report_bytes = canonical_json_bytes(asdict(report))
    return (
        {
            "contract.json": contract_bytes,
            "expected-fingerprint.json": fingerprint_bytes,
            "expected-fingerprint.sha256": sha_bytes,
            "equivalence-map.json": equivalence_bytes,
            "verification-report.json": report_bytes,
        },
        report,
    )


def _best_effort_unlink(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _publish_candidate_artifacts(
    config: RestoreVerificationConfig,
    initial_index: Mapping[str, object],
    targets: Mapping[str, Path],
    payloads: Mapping[str, bytes],
) -> None:
    artifact_hashes = {
        name: sha256_hex(payloads[name]) for name in RESTORE_EXPECTED_ARTIFACTS
    }
    try:
        updated_index = build_pending_restore_index(
            initial_index,
            artifact_hashes,
        )
        index_bytes = canonical_json_bytes(updated_index)
    except RestoreEvidenceError:
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH") from None

    temporary_paths: list[Path] = []
    published_paths: list[Path] = []
    index_temporary: Path | None = None
    index_path = config.artifact_root / "restore-evidence-index.json"
    try:
        for name in RESTORE_EXPECTED_ARTIFACTS:
            temporary_paths.append(
                config.temporary_writer(targets[name], payloads[name])
            )
        index_temporary = config.temporary_writer(index_path, index_bytes)
        for name, temporary in zip(
            RESTORE_EXPECTED_ARTIFACTS,
            temporary_paths,
            strict=True,
        ):
            target = targets[name]
            config.artifact_linker(temporary, target)
            published_paths.append(target)
            temporary.unlink()
        config.index_replacer(index_temporary, index_path)
        index_temporary = None
    except Exception:
        _best_effort_unlink(published_paths)
        _best_effort_unlink(temporary_paths)
        if index_temporary is not None:
            _best_effort_unlink([index_temporary])
        restore_dir = next(iter(targets.values())).parent
        try:
            restore_dir.rmdir()
        except OSError:
            pass
        raise RestoreVerificationError("B04R-ARTIFACT-PUBLISH") from None


def verify_restore_roundtrip(
    config: RestoreVerificationConfig,
) -> RestoreVerificationReport:
    """Run B-04R and publish only candidate-pending-acceptance evidence."""
    initial_index, targets = _preflight_publication(config)
    preflight = preflight_restore_verification(config)
    result = execute_restore_roundtrip(config, preflight)
    payloads, report = _build_artifacts(config, preflight, result)
    _publish_candidate_artifacts(
        config,
        initial_index,
        targets,
        payloads,
    )
    return report


def main() -> None:
    try:
        report = verify_restore_roundtrip(
            RestoreVerificationConfig.from_environment()
        )
    except RestoreVerificationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    print(report.status)


if __name__ == "__main__":
    main()
