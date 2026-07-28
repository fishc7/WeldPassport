"""Fail-closed two-database equivalence verification for B-04A only."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from migrations.b04.disposable import DatabaseIdentity, assert_disposable_database
from migrations.b04.fingerprint import CANONICAL_SCHEMAS, canonicalize_fingerprint, extract_fingerprint
from migrations.b04.manifest import canonical_json_bytes, verify_manifest_artifact
from migrations.b04.seeds import seed_manifest
from migrations.b04.source_contract import CANONICAL_TABLE_COUNT, SCHEMA_SOURCE_COMMIT


_BASELINE_REVISION = "canonical_baseline_v1"
_GOVERNED_INDEX = ("hr", "worker_roles", "uq_hr_worker_roles_active_scope")
_ENV_NAMES = (
    "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE",
    "WELDPASSPORT_B04_OWNERSHIP_TOKEN",
    "WELDPASSPORT_B04_HISTORICAL_URL",
    "WELDPASSPORT_B04_BASELINE_URL",
    "WELDPASSPORT_B04_HISTORICAL_EXPECTED_DATABASE",
    "WELDPASSPORT_B04_BASELINE_EXPECTED_DATABASE",
)
_DEFAULT_SYSTEMROOT = object()


class VerificationError(RuntimeError):
    """The B-04A equivalence evidence is absent or not acceptable."""


CommandRunner = Callable[[Sequence[str], Mapping[str, str], str], None]
ConnectionFactory = Callable[[str], AbstractContextManager[Any]]
SafetyValidator = Callable[..., DatabaseIdentity]
FingerprintExtractor = Callable[[Any], Mapping[str, object]]
AbsenceChecker = Callable[[Any], None]
ManifestVerifier = Callable[[Path, Path], None]
ArtifactLinker = Callable[[Path, Path], None]
TemporaryWriter = Callable[[Path, bytes], Path]


def _run_command(command: Sequence[str], environment: Mapping[str, str], _: str) -> None:
    subprocess.run(command, env=dict(environment), check=True, capture_output=True, text=True, timeout=300)


def _connect(url: str) -> AbstractContextManager[Any]:
    return create_engine(url, future=True, connect_args={"connect_timeout": 10}).connect()


def _hard_link_no_clobber(source: Path, target: Path) -> None:
    """Publish one same-directory artifact only if its final name is still absent."""
    os.link(source, target)


def _assert_canonical_objects_absent(connection: Any) -> None:
    rows = connection.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:schemas)"),
        {"schemas": list(CANONICAL_SCHEMAS)},
    ).scalars().all()
    if rows:
        raise VerificationError("B04-VERIFY-DOWNGRADE-OBJECTS-REMAIN")


@dataclass(frozen=True, slots=True)
class VerificationReport:
    status: str
    source_sha: str
    historical_database: str
    baseline_database: str
    historical_digest: str
    baseline_digest: str
    reupgrade_digest: str
    canonical_table_count: int
    exact_seed_count: int
    governed_index: str


@dataclass(slots=True)
class VerificationConfig:
    """Explicit inputs and injectable adapters for a single B-04A evidence run."""

    historical_url: str
    baseline_url: str
    destructive_opt_in: str | None
    ownership_token: str | None
    historical_expected_database: str
    baseline_expected_database: str
    source_sha: str
    expected_fingerprint_path: Path
    expected_fingerprint_sha256_path: Path
    report_path: Path
    command_runner: CommandRunner = _run_command
    connection_factory: ConnectionFactory = _connect
    safety_validator: SafetyValidator = assert_disposable_database
    fingerprint_extractor: FingerprintExtractor = extract_fingerprint
    absence_checker: AbsenceChecker = _assert_canonical_objects_absent
    fingerprint_serializer: Callable[[Mapping[str, object]], bytes] = canonicalize_fingerprint
    historical_alembic_ini: Path = Path("migrations/b04/historical_alembic.ini")
    baseline_alembic_ini: Path = Path("migrations/b04/candidate_alembic.ini")
    frozen_manifest_path: Path = Path("migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.json")
    repository_root: Path = Path(".")
    manifest_verifier: ManifestVerifier = verify_manifest_artifact
    artifact_linker: ArtifactLinker = _hard_link_no_clobber
    temporary_writer: TemporaryWriter = lambda target, data: _write_temporary(target, data)
    python_executable: str = field(default_factory=lambda: os.sys.executable)

    @classmethod
    def from_environment(cls) -> VerificationConfig:
        values = {name: os.environ.get(name) for name in _ENV_NAMES}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise VerificationError("B04-VERIFY-MISSING-ENVIRONMENT")
        artifact_dir = Path("migrations/baselines/canonical_baseline_v1")
        return cls(
            historical_url=str(values["WELDPASSPORT_B04_HISTORICAL_URL"]),
            baseline_url=str(values["WELDPASSPORT_B04_BASELINE_URL"]),
            destructive_opt_in=values["WELDPASSPORT_B04_ALLOW_DESTRUCTIVE"],
            ownership_token=values["WELDPASSPORT_B04_OWNERSHIP_TOKEN"],
            historical_expected_database=str(values["WELDPASSPORT_B04_HISTORICAL_EXPECTED_DATABASE"]),
            baseline_expected_database=str(values["WELDPASSPORT_B04_BASELINE_EXPECTED_DATABASE"]),
            source_sha=SCHEMA_SOURCE_COMMIT,
            expected_fingerprint_path=artifact_dir / "expected-fingerprint.json",
            expected_fingerprint_sha256_path=artifact_dir / "expected-fingerprint.sha256",
            report_path=artifact_dir / "verification-report.json",
        )


def _checked_identity(config: VerificationConfig, url: str, expected_database: str) -> DatabaseIdentity:
    try:
        return config.safety_validator(
            url,
            opt_in=config.destructive_opt_in,
            ownership_token=config.ownership_token,
            expected_database=expected_database,
        )
    except Exception as exc:
        raise VerificationError("B04-VERIFY-DISPOSABLE-SAFETY") from exc


def _historical_environment(
    url: str,
    *,
    platform_name: str | None = None,
    systemroot: str | None | object = _DEFAULT_SYSTEMROOT,
) -> dict[str, str]:
    """Build the complete, non-inheriting historical Alembic subprocess environment."""
    try:
        parsed = make_url(url)
        values = {
            "POSTGRES_HOST": parsed.host,
            "POSTGRES_PORT": str(parsed.port),
            "POSTGRES_DB": parsed.database,
            "POSTGRES_USER": parsed.username,
            "POSTGRES_PASSWORD": parsed.password,
            "POSTGRES_SCHEMA": "test",
        }
    except Exception as exc:
        raise VerificationError("B04-VERIFY-HISTORICAL-URL") from exc
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise VerificationError("B04-VERIFY-HISTORICAL-URL")
    if (os.name if platform_name is None else platform_name) == "nt":
        root = os.environ.get("SYSTEMROOT") if systemroot is _DEFAULT_SYSTEMROOT else systemroot
        if not isinstance(root, str) or not root.strip():
            raise VerificationError("B04-VERIFY-WINDOWS-SYSTEMROOT")
        values["SYSTEMROOT"] = root
    return values  # type: ignore[return-value]


def _baseline_environment(
    config: VerificationConfig,
    *,
    platform_name: str | None = None,
    systemroot: str | None | object = _DEFAULT_SYSTEMROOT,
) -> dict[str, str]:
    """Build the complete, non-inheriting baseline Alembic subprocess environment."""
    values = {
        "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE": config.destructive_opt_in,
        "WELDPASSPORT_B04_OWNERSHIP_TOKEN": config.ownership_token,
        "WELDPASSPORT_B04_EXPECTED_DATABASE": config.baseline_expected_database,
        "WELDPASSPORT_B04_DATABASE_URL": config.baseline_url,
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise VerificationError("B04-VERIFY-BASELINE-CONTEXT")
    if (os.name if platform_name is None else platform_name) == "nt":
        root = os.environ.get("SYSTEMROOT") if systemroot is _DEFAULT_SYSTEMROOT else systemroot
        if not isinstance(root, str) or not root.strip():
            raise VerificationError("B04-VERIFY-WINDOWS-SYSTEMROOT")
        values["SYSTEMROOT"] = root
    return values  # type: ignore[return-value]


def _run(config: VerificationConfig, label: str, environment: Mapping[str, str], *args: str) -> None:
    try:
        config.command_runner((config.python_executable, "-m", "alembic", "-c", *args), environment, label)
    except Exception as exc:
        raise VerificationError(f"B04-VERIFY-{label.upper()}") from exc


def _fingerprint(config: VerificationConfig, url: str) -> tuple[Mapping[str, object], bytes, str]:
    try:
        with config.connection_factory(url) as connection:
            value = config.fingerprint_extractor(connection)
        data = config.fingerprint_serializer(value)
    except Exception as exc:
        raise VerificationError("B04-VERIFY-FINGERPRINT") from exc
    return value, data, hashlib.sha256(data).hexdigest()


def _assert_accepted_fingerprint(value: Mapping[str, object]) -> None:
    tables = value.get("tables")
    seeds = value.get("seeds")
    if not isinstance(tables, list) or len(tables) != CANONICAL_TABLE_COUNT:
        raise VerificationError("B04-VERIFY-TABLE-COUNT")
    if seeds != seed_manifest():
        raise VerificationError("B04-VERIFY-SEEDS")
    indexes = {
        (table.get("schema"), table.get("name"), index.get("name"))
        for table in tables
        if isinstance(table, Mapping)
        for index in table.get("indexes", [])
        if isinstance(index, Mapping)
    }
    if _GOVERNED_INDEX not in indexes:
        raise VerificationError("B04-VERIFY-GOVERNED-INDEX")


def _preflight_artifact_targets(config: VerificationConfig) -> None:
    targets = (
        (config.expected_fingerprint_path, "expected-fingerprint.json"),
        (config.expected_fingerprint_sha256_path, "expected-fingerprint.sha256"),
        (config.report_path, "verification-report.json"),
    )
    paths = [path for path, _ in targets]
    if (
        len(set(paths)) != len(paths)
        or len({path.parent for path in paths}) != 1
        or any(path.name != expected_name for path, expected_name in targets)
    ):
        raise VerificationError("B04-VERIFY-ARTIFACT-TARGET")
    if any(path.exists() or path.is_symlink() for path in paths):
        raise VerificationError("B04-VERIFY-ARTIFACT-EXISTS")


def _write_temporary(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _best_effort_unlink(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_accepted_artifacts(config: VerificationConfig, fingerprint_bytes: bytes, report: VerificationReport) -> None:
    digest_line = f"{hashlib.sha256(fingerprint_bytes).hexdigest()}  expected-fingerprint.json\n".encode("ascii")
    payloads = (
        (config.expected_fingerprint_path, fingerprint_bytes),
        (config.expected_fingerprint_sha256_path, digest_line),
        (config.report_path, canonical_json_bytes(asdict(report))),
    )
    temporary_paths: list[Path] = []
    published_paths: list[Path] = []
    try:
        for target, data in payloads:
            temporary_paths.append(config.temporary_writer(target, data))
        for temporary, (target, _) in zip(temporary_paths, payloads, strict=True):
            config.artifact_linker(temporary, target)
            published_paths.append(target)
            temporary.unlink()
    except Exception as exc:
        _best_effort_unlink(published_paths)
        _best_effort_unlink(temporary_paths)
        raise VerificationError("B04-VERIFY-ARTIFACT-PUBLISH") from exc


def verify_equivalence(config: VerificationConfig) -> VerificationReport:
    """Run B-04A's required two-database sequence and emit accepted evidence last."""
    _preflight_artifact_targets(config)
    if config.source_sha != SCHEMA_SOURCE_COMMIT:
        raise VerificationError("B04-VERIFY-SOURCE-CUT")
    try:
        config.manifest_verifier(config.frozen_manifest_path, config.repository_root)
    except Exception as exc:
        raise VerificationError("B04-VERIFY-MANIFEST") from exc
    historical_identity = _checked_identity(config, config.historical_url, config.historical_expected_database)
    baseline_identity = _checked_identity(config, config.baseline_url, config.baseline_expected_database)
    historical_environment = _historical_environment(config.historical_url)
    baseline_environment = _baseline_environment(config)

    _run(config, "historical-upgrade", historical_environment, str(config.historical_alembic_ini), "upgrade", "head")
    historical_value, historical_bytes, historical_digest = _fingerprint(config, config.historical_url)
    _run(config, "baseline-upgrade", baseline_environment, str(config.baseline_alembic_ini), "upgrade", _BASELINE_REVISION)
    baseline_value, baseline_bytes, baseline_digest = _fingerprint(config, config.baseline_url)
    if historical_bytes != baseline_bytes:
        raise VerificationError("B04-VERIFY-FINGERPRINT-MISMATCH")
    _run(config, "baseline-downgrade", baseline_environment, str(config.baseline_alembic_ini), "downgrade", "base")
    try:
        with config.connection_factory(config.baseline_url) as connection:
            config.absence_checker(connection)
    except Exception as exc:
        raise VerificationError("B04-VERIFY-DOWNGRADE-ABSENCE") from exc
    _run(config, "baseline-reupgrade", baseline_environment, str(config.baseline_alembic_ini), "upgrade", _BASELINE_REVISION)
    reupgrade_value, reupgrade_bytes, reupgrade_digest = _fingerprint(config, config.baseline_url)
    if historical_bytes != reupgrade_bytes:
        raise VerificationError("B04-VERIFY-REUPGRADE-MISMATCH")
    _assert_accepted_fingerprint(historical_value)
    _assert_accepted_fingerprint(baseline_value)
    _assert_accepted_fingerprint(reupgrade_value)
    report = VerificationReport(
        status="B04A_VERIFIED",
        source_sha=config.source_sha,
        historical_database=historical_identity.database,
        baseline_database=baseline_identity.database,
        historical_digest=historical_digest,
        baseline_digest=baseline_digest,
        reupgrade_digest=reupgrade_digest,
        canonical_table_count=CANONICAL_TABLE_COUNT,
        exact_seed_count=15,
        governed_index="hr.worker_roles.uq_hr_worker_roles_active_scope",
    )
    _write_accepted_artifacts(config, historical_bytes, report)
    return report


def main() -> None:
    try:
        verify_equivalence(VerificationConfig.from_environment())
    except VerificationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
