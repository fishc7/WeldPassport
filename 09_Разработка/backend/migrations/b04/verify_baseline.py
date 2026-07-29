"""Fail-closed two-database equivalence verification for B-04A only."""

from __future__ import annotations

import hashlib
import json
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

from migrations.b04.disposable import (
    DatabaseIdentity,
    PostgresVersion,
    assert_disposable_database,
    assert_postgresql_18,
)
from migrations.b04.evidence import (
    PG16_ARTIFACT_SHA256,
    PG18_EVIDENCE_ID,
    PG18_EXPECTED_ARTIFACTS,
    PG18_SERVER_VERSION_NUM,
    build_pending_acceptance_index,
    build_pg18_contract,
    validate_evidence_index,
    validate_pg18_report,
)
from migrations.b04.fingerprint import (
    CANONICAL_SCHEMAS,
    FINGERPRINT_FORMAT_VERSION,
    SUPPORTED_POSTGRES_MAJOR,
    canonicalize_fingerprint,
    extract_fingerprint,
)
from migrations.b04.manifest import canonical_json_bytes, sha256_hex, verify_manifest_artifact
from migrations.b04.seeds import seed_manifest
from migrations.b04.source_contract import CANONICAL_TABLE_COUNT, SCHEMA_SOURCE_COMMIT


_BASELINE_REVISION = "canonical_baseline_v1"
_HISTORICAL_DATABASE = "wp_b04_r18_historical_disposable"
_BASELINE_DATABASE = "wp_b04_r18_baseline_disposable"
_GOVERNED_INDEX = ("hr", "worker_roles", "uq_hr_worker_roles_active_scope")
_ENV_NAMES = (
    "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE",
    "WELDPASSPORT_B04_OWNERSHIP_TOKEN",
    "WELDPASSPORT_B04_HISTORICAL_URL",
    "WELDPASSPORT_B04_BASELINE_URL",
    "WELDPASSPORT_B04_HISTORICAL_EXPECTED_DATABASE",
    "WELDPASSPORT_B04_BASELINE_EXPECTED_DATABASE",
    "WELDPASSPORT_B04_IMPLEMENTATION_SHA",
)
_DEFAULT_SYSTEMROOT = object()


class VerificationError(RuntimeError):
    """The B-04A equivalence evidence is absent or not acceptable."""


CommandRunner = Callable[[Sequence[str], Mapping[str, str], str], None]
ConnectionFactory = Callable[[str], AbstractContextManager[Any]]
SafetyValidator = Callable[..., DatabaseIdentity]
VersionValidator = Callable[[Any], PostgresVersion]
FingerprintExtractor = Callable[[Any], Mapping[str, object]]
AbsenceChecker = Callable[[Any], None]
ManifestVerifier = Callable[[Path, Path], None]
ArtifactLinker = Callable[[Path, Path], None]
TemporaryWriter = Callable[[Path, bytes], Path]
IndexReplacer = Callable[[Path, Path], None]


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
    evidence_id: str
    source_sha: str
    implementation_sha: str
    postgres_major: int
    server_version_num: int
    fingerprint_format_version: int
    historical_database: str
    baseline_database: str
    historical_digest: str
    baseline_digest: str
    reupgrade_digest: str
    shared_artifact_sha256: Mapping[str, str]
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
    implementation_sha: str
    contract_path: Path
    expected_fingerprint_path: Path
    expected_fingerprint_sha256_path: Path
    report_path: Path
    evidence_index_path: Path
    command_runner: CommandRunner = _run_command
    connection_factory: ConnectionFactory = _connect
    safety_validator: SafetyValidator = assert_disposable_database
    version_validator: VersionValidator = assert_postgresql_18
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
    index_replacer: IndexReplacer = os.replace
    python_executable: str = field(default_factory=lambda: os.sys.executable)

    @classmethod
    def from_environment(cls) -> VerificationConfig:
        values = {name: os.environ.get(name) for name in _ENV_NAMES}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise VerificationError("B04-VERIFY-MISSING-ENVIRONMENT")
        artifact_dir = Path("migrations/baselines/canonical_baseline_v1")
        evidence_dir = artifact_dir / "postgresql-18"
        return cls(
            historical_url=str(values["WELDPASSPORT_B04_HISTORICAL_URL"]),
            baseline_url=str(values["WELDPASSPORT_B04_BASELINE_URL"]),
            destructive_opt_in=values["WELDPASSPORT_B04_ALLOW_DESTRUCTIVE"],
            ownership_token=values["WELDPASSPORT_B04_OWNERSHIP_TOKEN"],
            historical_expected_database=str(values["WELDPASSPORT_B04_HISTORICAL_EXPECTED_DATABASE"]),
            baseline_expected_database=str(values["WELDPASSPORT_B04_BASELINE_EXPECTED_DATABASE"]),
            source_sha=SCHEMA_SOURCE_COMMIT,
            implementation_sha=str(values["WELDPASSPORT_B04_IMPLEMENTATION_SHA"]),
            contract_path=evidence_dir / "contract.json",
            expected_fingerprint_path=evidence_dir / "expected-fingerprint.json",
            expected_fingerprint_sha256_path=evidence_dir / "expected-fingerprint.sha256",
            report_path=evidence_dir / "verification-report.json",
            evidence_index_path=artifact_dir / "evidence-index.json",
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


def _assert_database_roles(config: VerificationConfig) -> None:
    if (
        config.historical_expected_database != _HISTORICAL_DATABASE
        or config.baseline_expected_database != _BASELINE_DATABASE
    ):
        raise VerificationError("B04-VERIFY-DATABASE-IDENTITY")


def _checked_version(config: VerificationConfig, url: str) -> PostgresVersion:
    try:
        with config.connection_factory(url) as connection:
            version = config.version_validator(connection)
        if (
            not isinstance(version, PostgresVersion)
            or isinstance(version.server_version_num, bool)
            or not isinstance(version.server_version_num, int)
            or version.server_version_num // 10_000 != 18
            or version.major != 18
        ):
            raise ValueError
        return version
    except Exception as exc:
        raise VerificationError("B04-VERIFY-POSTGRESQL-VERSION") from exc


def _preflight_postgres_versions(config: VerificationConfig) -> PostgresVersion:
    historical = _checked_version(config, config.historical_url)
    baseline = _checked_version(config, config.baseline_url)
    if historical.server_version_num != baseline.server_version_num:
        raise VerificationError("B04-VERIFY-POSTGRESQL-VERSION-MISMATCH")
    if historical.server_version_num != PG18_SERVER_VERSION_NUM:
        raise VerificationError("B04-VERIFY-POSTGRESQL-VERSION")
    return historical


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


def _preflight_artifact_targets(
    config: VerificationConfig,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    targets = (
        (config.contract_path, "contract.json"),
        (config.expected_fingerprint_path, "expected-fingerprint.json"),
        (config.expected_fingerprint_sha256_path, "expected-fingerprint.sha256"),
        (config.report_path, "verification-report.json"),
    )
    paths = [path for path, _ in targets]
    artifact_root = config.evidence_index_path.parent
    evidence_dir = artifact_root / "postgresql-18"
    if (
        len(set(paths)) != len(paths)
        or len({path.parent for path in paths}) != 1
        or paths[0].parent != evidence_dir
        or any(path.name != expected_name for path, expected_name in targets)
        or config.evidence_index_path.name != "evidence-index.json"
    ):
        raise VerificationError("B04-VERIFY-ARTIFACT-TARGET")
    if (
        artifact_root.is_symlink()
        or evidence_dir.is_symlink()
        or config.evidence_index_path.is_symlink()
        or any(path.is_symlink() for path in paths)
    ):
        raise VerificationError("B04-VERIFY-ARTIFACT-SYMLINK")
    existing = [path for path in paths if path.exists()]
    if 0 < len(existing) < len(paths):
        raise VerificationError("B04-VERIFY-ARTIFACT-PARTIAL")
    if existing:
        raise VerificationError("B04-VERIFY-ARTIFACT-EXISTS")
    try:
        index_bytes = config.evidence_index_path.read_bytes()
        index = json.loads(index_bytes)
        if (
            not isinstance(index, Mapping)
            or canonical_json_bytes(index) != index_bytes
        ):
            raise ValueError
        validate_evidence_index(index)
        contract = build_pg18_contract(config.implementation_sha)
        build_pending_acceptance_index(
            index,
            {name: "0" * 64 for name in PG18_EXPECTED_ARTIFACTS},
        )
        for name, expected in PG16_ARTIFACT_SHA256.items():
            shared_path = artifact_root / name
            if (
                shared_path.is_symlink()
                or not shared_path.is_file()
                or sha256_hex(shared_path.read_bytes()) != expected
            ):
                raise ValueError
    except Exception as exc:
        raise VerificationError("B04-VERIFY-EVIDENCE-PREFLIGHT") from exc
    return index, contract


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


def _publish_pending_artifacts(
    config: VerificationConfig,
    fingerprint_bytes: bytes,
    report: VerificationReport,
    contract: Mapping[str, object],
    initial_index: Mapping[str, object],
) -> None:
    digest_line = f"{hashlib.sha256(fingerprint_bytes).hexdigest()}  expected-fingerprint.json\n".encode("ascii")
    payloads = (
        (config.contract_path, canonical_json_bytes(contract)),
        (config.expected_fingerprint_path, fingerprint_bytes),
        (config.expected_fingerprint_sha256_path, digest_line),
        (config.report_path, canonical_json_bytes(asdict(report))),
    )
    artifact_sha256 = {
        target.name: sha256_hex(data) for target, data in payloads
    }
    try:
        validate_pg18_report(asdict(report))
        updated_index = build_pending_acceptance_index(
            initial_index,
            artifact_sha256,
        )
        index_bytes = canonical_json_bytes(updated_index)
    except Exception as exc:
        raise VerificationError("B04-VERIFY-EVIDENCE-CONTRACT") from exc
    temporary_paths: list[Path] = []
    published_paths: list[Path] = []
    index_temporary: Path | None = None
    try:
        for target, data in payloads:
            temporary_paths.append(config.temporary_writer(target, data))
        index_temporary = config.temporary_writer(
            config.evidence_index_path,
            index_bytes,
        )
        for temporary, (target, _) in zip(temporary_paths, payloads, strict=True):
            config.artifact_linker(temporary, target)
            published_paths.append(target)
            temporary.unlink()
        config.index_replacer(index_temporary, config.evidence_index_path)
        index_temporary = None
    except Exception as exc:
        _best_effort_unlink(published_paths)
        _best_effort_unlink(temporary_paths)
        if index_temporary is not None:
            _best_effort_unlink((index_temporary,))
        raise VerificationError("B04-VERIFY-ARTIFACT-PUBLISH") from exc


def verify_equivalence(config: VerificationConfig) -> VerificationReport:
    """Run B-04A's two-database sequence and publish pending evidence last."""
    initial_index, contract = _preflight_artifact_targets(config)
    if config.source_sha != SCHEMA_SOURCE_COMMIT:
        raise VerificationError("B04-VERIFY-SOURCE-CUT")
    try:
        config.manifest_verifier(config.frozen_manifest_path, config.repository_root)
    except Exception as exc:
        raise VerificationError("B04-VERIFY-MANIFEST") from exc
    _assert_database_roles(config)
    historical_identity = _checked_identity(config, config.historical_url, config.historical_expected_database)
    baseline_identity = _checked_identity(config, config.baseline_url, config.baseline_expected_database)
    postgres_version = _preflight_postgres_versions(config)
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
        evidence_id=PG18_EVIDENCE_ID,
        source_sha=config.source_sha,
        implementation_sha=config.implementation_sha,
        postgres_major=SUPPORTED_POSTGRES_MAJOR,
        server_version_num=postgres_version.server_version_num,
        fingerprint_format_version=FINGERPRINT_FORMAT_VERSION,
        historical_database=historical_identity.database,
        baseline_database=baseline_identity.database,
        historical_digest=historical_digest,
        baseline_digest=baseline_digest,
        reupgrade_digest=reupgrade_digest,
        shared_artifact_sha256=dict(PG16_ARTIFACT_SHA256),
        canonical_table_count=CANONICAL_TABLE_COUNT,
        exact_seed_count=15,
        governed_index="hr.worker_roles.uq_hr_worker_roles_active_scope",
    )
    _publish_pending_artifacts(
        config,
        historical_bytes,
        report,
        contract,
        initial_index,
    )
    return report


def main() -> None:
    try:
        verify_equivalence(VerificationConfig.from_environment())
    except VerificationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
