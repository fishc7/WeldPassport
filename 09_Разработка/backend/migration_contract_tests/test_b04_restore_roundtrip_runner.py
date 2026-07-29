from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Mapping

import pytest

import migrations.b04.verify_restore_roundtrip as restore_runner
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.manifest import canonical_json_bytes
from migrations.b04.restore_evidence import HISTORICAL_MARKER
from migrations.b04.verify_restore_roundtrip import (
    RestoreVerificationReport,
    RestoreVerificationConfig,
    RestoreVerificationError,
    execute_restore_roundtrip,
    preflight_restore_verification,
    read_working_snapshot,
    verify_restore_roundtrip,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (
    BACKEND_ROOT / "migrations" / "baselines" / "canonical_baseline_v1"
)
LIVE_FINGERPRINT = json.loads(
    (
        ARTIFACT_ROOT
        / "postgresql-18"
        / "expected-fingerprint.json"
    ).read_bytes()
)
LIVE_DIGEST = "e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a"
FIRST_DATABASE = "wp_b04_r18_restore_first_disposable"
SECOND_DATABASE = "wp_b04_r18_restore_second_disposable"
WORKING_URL = (
    "postgresql+psycopg://postgres:working-password@"
    "127.0.0.1:5432/WeldPassport"
)
FIRST_URL = (
    "postgresql+psycopg://b04_runner:database-password@"
    f"127.0.0.1:5432/{FIRST_DATABASE}"
)
SECOND_URL = (
    "postgresql+psycopg://b04_runner:database-password@"
    f"127.0.0.1:5432/{SECOND_DATABASE}"
)
LIVE_ARTIFACT_NAMES = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "verification-report.json",
)


class _Scalar:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class RecordingConnection:
    def __init__(
        self,
        database: str,
        *,
        read_only: str = "on",
        server_version_num: object = "180003",
        owner: object = True,
        relation_count: object = 0,
    ) -> None:
        self.database = database
        self.read_only = read_only
        self.server_version_num = server_version_num
        self.owner = owner
        self.relation_count = relation_count
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> _Scalar:
        self.statements.append(statement)
        if statement == "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY":
            return _Scalar(None)
        if statement == "SHOW transaction_read_only":
            return _Scalar(self.read_only)
        if statement == "SHOW server_version_num":
            return _Scalar(self.server_version_num)
        if statement == "SELECT current_database()":
            return _Scalar(self.database)
        if statement == "SELECT version_num FROM test.alembic_version":
            return _Scalar(HISTORICAL_MARKER)
        if statement == "SELECT to_regclass('public.alembic_version')":
            return _Scalar(None)
        if statement.startswith("SELECT pg_get_userbyid(datdba) = current_user"):
            return _Scalar(self.owner)
        if statement.startswith("SELECT count(*) FROM pg_class"):
            return _Scalar(self.relation_count)
        raise AssertionError(f"unexpected SQL: {statement}")


class _ConnectionContext(AbstractContextManager[RecordingConnection]):
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def __enter__(self) -> RecordingConnection:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


def _config(
    *,
    working: RecordingConnection | None = None,
    first: RecordingConnection | None = None,
    second: RecordingConnection | None = None,
    version_overrides: Mapping[str, str] | None = None,
    restored_fingerprint: Mapping[str, object] | None = None,
    second_fingerprint: Mapping[str, object] | None = None,
    backup_path: Path = Path("operator-backup.dump"),
    command_runner: Any | None = None,
    temporary_archive_factory: Any | None = None,
    artifact_root: Path = ARTIFACT_ROOT,
    artifact_linker: Any | None = None,
    index_replacer: Any | None = None,
) -> tuple[RestoreVerificationConfig, dict[str, RecordingConnection]]:
    connections = {
        "WeldPassport": working or RecordingConnection("WeldPassport"),
        FIRST_DATABASE: first or RecordingConnection(FIRST_DATABASE),
        SECOND_DATABASE: second or RecordingConnection(SECOND_DATABASE),
    }

    def connection_factory(url: str) -> _ConnectionContext:
        database = url.rsplit("/", 1)[-1]
        return _ConnectionContext(connections[database])

    versions = {
        "pg_dump": "pg_dump (PostgreSQL) 18.3",
        "pg_restore": "pg_restore (PostgreSQL) 18.3",
        **dict(version_overrides or {}),
    }

    def version_probe(executable: str) -> str:
        return versions["pg_restore" if "restore" in executable else "pg_dump"]

    restored_value = restored_fingerprint or LIVE_FINGERPRINT
    second_value = second_fingerprint or restored_value

    def fingerprint_extractor(connection: RecordingConnection) -> Mapping[str, object]:
        if connection.database == FIRST_DATABASE:
            return restored_value
        if connection.database == SECOND_DATABASE:
            return second_value
        return LIVE_FINGERPRINT

    config_kwargs: dict[str, object] = {}
    if command_runner is not None:
        config_kwargs["command_runner"] = command_runner
    if temporary_archive_factory is not None:
        config_kwargs["temporary_archive_factory"] = temporary_archive_factory
    if artifact_linker is not None:
        config_kwargs["artifact_linker"] = artifact_linker
    if index_replacer is not None:
        config_kwargs["index_replacer"] = index_replacer
    config = RestoreVerificationConfig(
        working_url=WORKING_URL,
        first_url=FIRST_URL,
        second_url=SECOND_URL,
        destructive_opt_in="YES",
        ownership_token="B04-owner-token-2026",
        first_expected_database=FIRST_DATABASE,
        second_expected_database=SECOND_DATABASE,
        backup_path=backup_path,
        artifact_root=artifact_root,
        implementation_sha="1" * 40,
        pg_dump_executable="C:/PostgreSQL/18/bin/pg_dump.exe",
        pg_restore_executable="C:/PostgreSQL/18/bin/pg_restore.exe",
        expected_pg_dump_version="pg_dump (PostgreSQL) 18.3",
        expected_pg_restore_version="pg_restore (PostgreSQL) 18.3",
        connection_factory=connection_factory,
        version_probe=version_probe,
        fingerprint_extractor=fingerprint_extractor,
        **config_kwargs,
    )
    return config, connections


def test_b04r_readonly_001_begin_is_first_working_statement() -> None:
    connection = RecordingConnection("WeldPassport")
    snapshot = read_working_snapshot(
        connection,
        fingerprint_extractor=lambda _: LIVE_FINGERPRINT,
    )
    assert connection.statements[0] == (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert snapshot.transaction_read_only == "on"
    assert snapshot.fingerprint_digest == LIVE_DIGEST
    assert snapshot.historical_marker == HISTORICAL_MARKER
    assert snapshot.public_marker is None
    assert snapshot.canonical_table_count == 73
    assert snapshot.canonical_sequence_count == 6
    assert snapshot.governed_seed_count == 15


def test_b04r_preflight_000_escapes_percent_for_psycopg_driver_sql() -> None:
    assert "n.nspname NOT LIKE 'pg_toast%%'" in restore_runner._EMPTY_SQL


def test_b04r_preflight_001_returns_sanitized_verified_state() -> None:
    config, connections = _config()
    result = preflight_restore_verification(config)
    assert result.working.database == "WeldPassport"
    assert result.first_identity == DatabaseIdentity(
        database=FIRST_DATABASE,
        host="127.0.0.1",
        port=5432,
        username="b04_runner",
    )
    assert result.second_identity.database == SECOND_DATABASE
    assert result.pg_dump_version == "pg_dump (PostgreSQL) 18.3"
    assert result.pg_restore_version == "pg_restore (PostgreSQL) 18.3"
    assert connections[FIRST_DATABASE].statements[0] == "SHOW server_version_num"


def test_b04r_preflight_002a_physically_hashes_every_live_artifact(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "canonical_baseline_v1"
    shutil.copytree(ARTIFACT_ROOT, artifact_root)
    (
        artifact_root
        / "postgresql-18"
        / "expected-fingerprint.sha256"
    ).write_bytes(b"0" * 64 + b"  expected-fingerprint.json\n")
    config, _ = _config(artifact_root=artifact_root)

    with pytest.raises(RestoreVerificationError, match="B04R-LIVE-EVIDENCE"):
        preflight_restore_verification(config)


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("read_only", "B04R-WORKING-READONLY"),
        ("working_version", "B04R-SERVER-VERSION"),
        ("first_version", "B04R-SERVER-VERSION"),
        ("owner", "B04R-DISPOSABLE-SAFETY"),
        ("nonempty", "B04R-DISPOSABLE-SAFETY"),
        ("tool", "B04R-TOOL-VERSION"),
    ],
)
def test_b04r_preflight_002_fails_closed_before_restore(
    field: str, expected_code: str
) -> None:
    working = RecordingConnection(
        "WeldPassport",
        read_only="off" if field == "read_only" else "on",
        server_version_num="180004" if field == "working_version" else "180003",
    )
    first = RecordingConnection(
        FIRST_DATABASE,
        server_version_num="180004" if field == "first_version" else "180003",
        owner=False if field == "owner" else True,
        relation_count=1 if field == "nonempty" else 0,
    )
    versions = (
        {"pg_dump": "pg_dump (PostgreSQL) 18.4"}
        if field == "tool"
        else None
    )
    config, _ = _config(
        working=working,
        first=first,
        version_overrides=versions,
    )
    with pytest.raises(RestoreVerificationError, match=expected_code):
        preflight_restore_verification(config)


def test_b04r_preflight_003_rejects_working_disposable_identity_collision() -> None:
    config, _ = _config(working=RecordingConnection(FIRST_DATABASE))
    with pytest.raises(
        RestoreVerificationError, match="B04R-DISPOSABLE-SAFETY"
    ):
        preflight_restore_verification(config)


def test_b04r_environment_001_requires_every_explicit_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in RestoreVerificationConfig.environment_names():
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(
        RestoreVerificationError, match="B04R-EVIDENCE-INDEX"
    ):
        RestoreVerificationConfig.from_environment()


def _deparser_restored_fingerprint() -> dict[str, object]:
    restored = copy.deepcopy(LIVE_FINGERPRINT)
    check = next(
        check
        for table in restored["tables"]
        for check in table["checks"]
        if isinstance(check.get("definition"), str)
    )
    check["definition"] = f"({check['definition']})"
    return restored


class RecordingCommandRunner:
    def __init__(self, *, fail_phase: str | None = None) -> None:
        self.fail_phase = fail_phase
        self.calls: list[tuple[tuple[str, ...], dict[str, str], str]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        environment: Mapping[str, str],
        phase: str,
    ) -> None:
        self.calls.append((tuple(command), dict(environment), phase))
        if phase == self.fail_phase:
            raise RuntimeError("external failure containing database-password")
        if phase == "second-dump":
            output = next(
                argument.removeprefix("--file=")
                for argument in command
                if argument.startswith("--file=")
            )
            Path(output).write_bytes(b"PGDMP-second")


def test_b04r_roundtrip_001_runs_exact_secret_free_sequence(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "operator.dump"
    backup.write_bytes(b"PGDMP-operator")
    temporary = tmp_path / ".b04r-roundtrip-test.dump"
    commands = RecordingCommandRunner()
    restored = _deparser_restored_fingerprint()
    config, _ = _config(
        restored_fingerprint=restored,
        backup_path=backup,
        command_runner=commands,
        temporary_archive_factory=lambda _: temporary,
    )
    preflight = preflight_restore_verification(config)
    result = execute_restore_roundtrip(config, preflight)

    assert [phase for _, _, phase in commands.calls] == [
        "backup-list",
        "first-restore",
        "second-dump",
        "second-restore",
    ]
    assert result.backup_sha256 == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert result.first_restore.fingerprint_digest == (
        result.second_restore.fingerprint_digest
    )
    assert result.equivalence_map["difference_count"] == 1
    assert not temporary.exists()
    for command, environment, _ in commands.calls:
        rendered = " ".join(command)
        assert "postgresql+psycopg://" not in rendered
        assert "database-password" not in rendered
        assert "working-password" not in rendered
        assert set(environment) <= {
            "PGHOST",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGPASSWORD",
            "SYSTEMROOT",
        }


@pytest.mark.parametrize(
    "phase",
    ["backup-list", "first-restore", "second-dump", "second-restore"],
)
def test_b04r_roundtrip_002_stops_after_exact_failing_phase(
    tmp_path: Path, phase: str
) -> None:
    backup = tmp_path / "operator.dump"
    backup.write_bytes(b"PGDMP-operator")
    temporary = tmp_path / ".b04r-roundtrip-failure.dump"
    commands = RecordingCommandRunner(fail_phase=phase)
    config, _ = _config(
        restored_fingerprint=_deparser_restored_fingerprint(),
        backup_path=backup,
        command_runner=commands,
        temporary_archive_factory=lambda _: temporary,
    )
    preflight = preflight_restore_verification(config)
    with pytest.raises(RestoreVerificationError) as error:
        execute_restore_roundtrip(config, preflight)
    assert "database-password" not in str(error.value)
    assert commands.calls[-1][2] == phase
    assert not temporary.exists()


def test_b04r_roundtrip_003_rejects_second_restore_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "operator.dump"
    backup.write_bytes(b"PGDMP-operator")
    temporary = tmp_path / ".b04r-roundtrip-mismatch.dump"
    commands = RecordingCommandRunner()
    config, _ = _config(
        restored_fingerprint=_deparser_restored_fingerprint(),
        second_fingerprint=LIVE_FINGERPRINT,
        backup_path=backup,
        command_runner=commands,
        temporary_archive_factory=lambda _: temporary,
    )
    preflight = preflight_restore_verification(config)
    with pytest.raises(RestoreVerificationError, match="B04R-FIXED-POINT"):
        execute_restore_roundtrip(config, preflight)


def test_b04r_roundtrip_004_rejects_non_expression_structural_drift(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "operator.dump"
    backup.write_bytes(b"PGDMP-operator")
    temporary = tmp_path / ".b04r-roundtrip-structural.dump"
    commands = RecordingCommandRunner()
    restored = _deparser_restored_fingerprint()
    index = next(
        index
        for table in restored["tables"]
        for index in table["indexes"]
    )
    index["ready"] = not index["ready"]
    config, _ = _config(
        restored_fingerprint=restored,
        backup_path=backup,
        command_runner=commands,
        temporary_archive_factory=lambda _: temporary,
    )
    preflight = preflight_restore_verification(config)
    with pytest.raises(RestoreVerificationError, match="B04R-DIFF-KIND"):
        execute_restore_roundtrip(config, preflight)


def test_b04r_roundtrip_005_rejects_missing_or_symlink_backup(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.dump"
    config, _ = _config(
        backup_path=missing,
        command_runner=RecordingCommandRunner(),
        temporary_archive_factory=lambda _: tmp_path / "temporary.dump",
    )
    preflight = preflight_restore_verification(config)
    with pytest.raises(RestoreVerificationError, match="B04R-BACKUP"):
        execute_restore_roundtrip(config, preflight)


def _empty_restore_index() -> dict[str, object]:
    return {
        "format_version": 1,
        "baseline_id": "canonical_baseline_v1",
        "live_evidence_id": "postgresql-18-fingerprint-v2",
        "evidence_sets": [],
    }


def _copy_live_evidence_only(root: Path) -> Path:
    live_dir = root / "postgresql-18"
    live_dir.mkdir()
    for name in LIVE_ARTIFACT_NAMES:
        source = ARTIFACT_ROOT / "postgresql-18" / name
        target = live_dir / name
        if source.is_symlink() or not source.is_file() or target.exists():
            raise AssertionError(
                "B04R publication fixture live artifact boundary"
            )
        shutil.copy2(source, target)
    if (live_dir / "restore-roundtrip-v1").exists():
        raise AssertionError(
            "B04R publication fixture inherited restore evidence"
        )
    return live_dir


def _publication_root(tmp_path: Path) -> Path:
    root = tmp_path / "canonical_baseline_v1"
    root.mkdir()
    shutil.copy2(ARTIFACT_ROOT / "evidence-index.json", root / "evidence-index.json")
    (root / "restore-evidence-index.json").write_bytes(
        canonical_json_bytes(_empty_restore_index())
    )
    _copy_live_evidence_only(root)
    return root


def _publication_config(
    tmp_path: Path,
    *,
    artifact_linker: Any | None = None,
    index_replacer: Any | None = None,
) -> tuple[RestoreVerificationConfig, RecordingCommandRunner, Path]:
    root = _publication_root(tmp_path)
    backup = tmp_path / "operator.dump"
    backup.write_bytes(b"PGDMP-operator")
    temporary = tmp_path / ".b04r-roundtrip-publication.dump"
    commands = RecordingCommandRunner()
    config, _ = _config(
        restored_fingerprint=_deparser_restored_fingerprint(),
        backup_path=backup,
        command_runner=commands,
        temporary_archive_factory=lambda _: temporary,
        artifact_root=root,
        artifact_linker=artifact_linker,
        index_replacer=index_replacer,
    )
    return config, commands, root


def test_b04r_publication_001_publishes_exact_pending_artifact_graph(
    tmp_path: Path,
) -> None:
    config, _, root = _publication_config(tmp_path)
    report = verify_restore_roundtrip(config)
    assert isinstance(report, RestoreVerificationReport)

    restore_dir = root / "postgresql-18" / "restore-roundtrip-v1"
    names = sorted(path.name for path in restore_dir.iterdir())
    assert names == sorted(
        [
            "contract.json",
            "expected-fingerprint.json",
            "expected-fingerprint.sha256",
            "equivalence-map.json",
            "verification-report.json",
        ]
    )
    index = json.loads((root / "restore-evidence-index.json").read_bytes())
    entry = index["evidence_sets"][0]
    assert entry["status"] == "candidate_pending_acceptance"
    assert entry["acceptance"] is None
    assert set(entry["artifact_sha256"]) == set(names)

    contract = json.loads((restore_dir / "contract.json").read_bytes())
    report_value = json.loads((restore_dir / "verification-report.json").read_bytes())
    assert "verification-report.json" not in contract["payload_artifact_sha256"]
    assert "contract.json" not in contract["payload_artifact_sha256"]
    assert "verification-report.json" not in report_value["artifact_sha256"]
    assert set(report_value["artifact_sha256"]) == {
        "contract.json",
        "expected-fingerprint.json",
        "expected-fingerprint.sha256",
        "equivalence-map.json",
    }
    rendered = json.dumps(report_value)
    assert "postgresql+psycopg://" not in rendered
    assert "database-password" not in rendered
    assert "working-password" not in rendered
    assert "127.0.0.1" not in rendered
    assert "b04_runner" not in rendered


@pytest.mark.parametrize(
    "failing_name",
    ["contract.json", "equivalence-map.json", "verification-report.json"],
)
def test_b04r_publication_002_rolls_back_every_owned_artifact(
    tmp_path: Path, failing_name: str
) -> None:
    def linker(source: Path, target: Path) -> None:
        if target.name == failing_name:
            raise OSError("injected link failure")
        os.link(source, target)

    config, _, root = _publication_config(tmp_path, artifact_linker=linker)
    original_index = (root / "restore-evidence-index.json").read_bytes()
    with pytest.raises(
        RestoreVerificationError, match="B04R-ARTIFACT-PUBLISH"
    ):
        verify_restore_roundtrip(config)
    restore_dir = root / "postgresql-18" / "restore-roundtrip-v1"
    assert not restore_dir.exists() or not list(restore_dir.iterdir())
    assert (root / "restore-evidence-index.json").read_bytes() == original_index
    assert not list(root.rglob("*.tmp"))


def test_b04r_publication_003_index_failure_preserves_prior_index(
    tmp_path: Path,
) -> None:
    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected index replace failure")

    config, _, root = _publication_config(tmp_path, index_replacer=fail_replace)
    original_index = (root / "restore-evidence-index.json").read_bytes()
    with pytest.raises(
        RestoreVerificationError, match="B04R-ARTIFACT-PUBLISH"
    ):
        verify_restore_roundtrip(config)
    restore_dir = root / "postgresql-18" / "restore-roundtrip-v1"
    assert not restore_dir.exists() or not list(restore_dir.iterdir())
    assert (root / "restore-evidence-index.json").read_bytes() == original_index
    assert not list(root.rglob("*.tmp"))


def test_b04r_publication_004_preexisting_foreign_file_stops_before_tools(
    tmp_path: Path,
) -> None:
    config, commands, root = _publication_config(tmp_path)
    restore_dir = root / "postgresql-18" / "restore-roundtrip-v1"
    restore_dir.mkdir()
    foreign = restore_dir / "contract.json"
    foreign.write_bytes(b"foreign")
    with pytest.raises(
        RestoreVerificationError, match="B04R-ARTIFACT-PUBLISH"
    ):
        verify_restore_roundtrip(config)
    assert foreign.read_bytes() == b"foreign"
    assert commands.calls == []


def test_b04r_cli_001_emits_only_stable_error_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        RestoreVerificationConfig,
        "from_environment",
        classmethod(lambda cls: object()),
    )

    def fail(_: object) -> RestoreVerificationReport:
        raise RestoreVerificationError("B04R-BACKUP")

    monkeypatch.setattr(restore_runner, "verify_restore_roundtrip", fail)
    with pytest.raises(SystemExit) as exit_info:
        restore_runner.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "B04R-BACKUP\n"
    assert "database-password" not in captured.err
