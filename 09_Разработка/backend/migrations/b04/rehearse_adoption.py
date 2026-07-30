"""Pure orchestration contract for an isolated B-04B adoption rehearsal.

Environment-dependent database, process and publication operations are explicit
dependencies.  Importing or calling this module cannot connect to PostgreSQL or
invoke pg_restore unless the caller supplies adapters that do so.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Callable

from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.manifest import canonical_json_bytes


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ADOPTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class RehearsalError(RuntimeError):
    """One B-04B rehearsal gate failed closed."""


@dataclass(frozen=True, slots=True)
class RehearsalConfig:
    adoption_id: str
    backup_path: Path
    expected_backup_sha256: str
    working_identity: DatabaseIdentity
    rehearsal_identity: DatabaseIdentity
    recovery_identity: DatabaseIdentity
    expected_server_version_num: int
    expected_live_fingerprint_sha256: str
    expected_restore_fingerprint_sha256: str
    report_directory: Path
    started_at_utc: str
    completed_at_utc: str


@dataclass(frozen=True, slots=True)
class RehearsalReport:
    adoption_id: str
    status: str
    backup_sha256: str
    live_fingerprint_sha256: str
    restore_fingerprint_sha256: str
    server_version_num: int
    rehearsal_database: str
    recovery_database: str
    started_at_utc: str
    completed_at_utc: str


VerifyBackup = Callable[[RehearsalConfig], str]
RestoreBackup = Callable[[Path, DatabaseIdentity, int], None]
VerifyFingerprints = Callable[[RehearsalConfig], tuple[str, str]]
RunPreflight = Callable[[RehearsalConfig], object]
TransferMarker = Callable[[RehearsalConfig, object], None]
RunPostflight = Callable[[RehearsalConfig, object], object]
VerifyRecovery = Callable[[RehearsalConfig], str]
PublishReport = Callable[[RehearsalReport, Path], Path]


@dataclass(frozen=True, slots=True)
class RehearsalDependencies:
    verify_backup: VerifyBackup
    restore_backup: RestoreBackup
    verify_fingerprints: VerifyFingerprints
    run_preflight: RunPreflight
    transfer_marker: TransferMarker
    run_postflight: RunPostflight
    verify_recovery: VerifyRecovery
    publish_report: PublishReport


@dataclass(frozen=True, slots=True)
class RehearsalResult:
    report: RehearsalReport
    report_path: Path


def canonical_report_bytes(report: RehearsalReport) -> bytes:
    """Serialize a sanitized rehearsal report deterministically."""

    return canonical_json_bytes(asdict(report))


def publish_report_once(
    directory: Path,
    report: RehearsalReport,
) -> Path:
    """Create one immutable report without following a supplied report path."""

    try:
        resolved_directory = directory.resolve(strict=True)
        repository_root = _REPOSITORY_ROOT.resolve(strict=True)
    except OSError:
        _fail("REPORT")
    if (
        _ADOPTION_ID.fullmatch(report.adoption_id) is None
        or directory.is_symlink()
        or not resolved_directory.is_dir()
        or resolved_directory == repository_root
        or repository_root in resolved_directory.parents
    ):
        _fail("REPORT")
    target = resolved_directory / f"{report.adoption_id}.b04b-rehearsal.json"
    try:
        with target.open("xb") as stream:
            stream.write(canonical_report_bytes(report))
    except OSError as exc:
        _fail("REPORT", exc)
    return target


def _fail(code: str, cause: Exception | None = None) -> None:
    error = RehearsalError(f"B04B-REHEARSAL-{code}")
    if cause is None:
        raise error
    raise error from cause


def _identity_key(identity: DatabaseIdentity) -> tuple[str, str, int]:
    return (identity.host, identity.database, identity.port)


def _validate_config(config: RehearsalConfig) -> None:
    identities = {
        _identity_key(config.working_identity),
        _identity_key(config.rehearsal_identity),
        _identity_key(config.recovery_identity),
    }
    if len(identities) != 3:
        _fail("IDENTITY")
    if (
        not config.adoption_id
        or isinstance(config.expected_server_version_num, bool)
        or not isinstance(config.expected_server_version_num, int)
        or config.expected_server_version_num // 10000 != 18
        or _SHA256.fullmatch(config.expected_backup_sha256) is None
        or _SHA256.fullmatch(config.expected_live_fingerprint_sha256) is None
        or _SHA256.fullmatch(config.expected_restore_fingerprint_sha256) is None
        or config.expected_live_fingerprint_sha256
        == config.expected_restore_fingerprint_sha256
    ):
        _fail("CONFIG")


def _run(stage: str, operation: Callable[[], object]) -> object:
    try:
        return operation()
    except RehearsalError:
        raise
    except Exception as exc:
        _fail(stage, exc)


def run_rehearsal(
    config: RehearsalConfig,
    dependencies: RehearsalDependencies,
) -> RehearsalResult:
    """Run one fail-closed rehearsal using only caller-supplied side effects."""

    _validate_config(config)

    backup_digest = _run(
        "BACKUP", lambda: dependencies.verify_backup(config)
    )
    if backup_digest != config.expected_backup_sha256:
        _fail("BACKUP")

    _run(
        "RESTORE",
        lambda: dependencies.restore_backup(
            config.backup_path,
            config.rehearsal_identity,
            config.expected_server_version_num,
        ),
    )

    fingerprints = _run(
        "FINGERPRINT", lambda: dependencies.verify_fingerprints(config)
    )
    if fingerprints != (
        config.expected_live_fingerprint_sha256,
        config.expected_restore_fingerprint_sha256,
    ):
        _fail("FINGERPRINT")

    prepared = _run(
        "PREFLIGHT", lambda: dependencies.run_preflight(config)
    )
    if getattr(prepared, "adoption_id", None) != config.adoption_id:
        _fail("PREFLIGHT")

    _run(
        "TRANSFER",
        lambda: dependencies.transfer_marker(config, prepared),
    )
    postflight = _run(
        "POSTFLIGHT",
        lambda: dependencies.run_postflight(config, prepared),
    )
    if getattr(postflight, "verified", None) is not True:
        _fail("POSTFLIGHT")

    _run(
        "RECOVERY-RESTORE",
        lambda: dependencies.restore_backup(
            config.backup_path,
            config.recovery_identity,
            config.expected_server_version_num,
        ),
    )
    recovery_digest = _run(
        "RECOVERY", lambda: dependencies.verify_recovery(config)
    )
    if recovery_digest != config.expected_restore_fingerprint_sha256:
        _fail("RECOVERY")

    report = RehearsalReport(
        adoption_id=config.adoption_id,
        status="B04B_REHEARSAL_ACCEPTED",
        backup_sha256=config.expected_backup_sha256,
        live_fingerprint_sha256=config.expected_live_fingerprint_sha256,
        restore_fingerprint_sha256=config.expected_restore_fingerprint_sha256,
        server_version_num=config.expected_server_version_num,
        rehearsal_database=config.rehearsal_identity.database,
        recovery_database=config.recovery_identity.database,
        started_at_utc=config.started_at_utc,
        completed_at_utc=config.completed_at_utc,
    )
    report_path = _run(
        "REPORT",
        lambda: dependencies.publish_report(report, config.report_directory),
    )
    if not isinstance(report_path, Path):
        _fail("REPORT")
    return RehearsalResult(report=report, report_path=report_path)


def main() -> None:
    """Refuse an uncomposed run; the isolated-DB gate supplies all adapters."""

    raise SystemExit("B04B-REHEARSAL-ADAPTERS-REQUIRED")


if __name__ == "__main__":
    main()
