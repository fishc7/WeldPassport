"""Pure orchestration contracts for the B-04A equivalence runner."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import pytest

import migrations.b04.verify_baseline as verify_runner
from migrations.b04.verify_baseline import VerificationConfig, VerificationError, verify_equivalence
from migrations.b04.verify_baseline import _historical_environment
from migrations.b04.seeds import seed_manifest
from migrations.b04.disposable import DatabaseIdentity


_HISTORICAL_URL = "postgresql+psycopg://runner:history-pass@127.0.0.1:5432/wp_b04_historical_disposable"
_BASELINE_URL = "postgresql+psycopg://runner:baseline-pass@127.0.0.1:5432/wp_b04_baseline_disposable"
_TOKEN = "B04-ownership-token-2026"
_FINGERPRINT = {
    "tables": [
        {"schema": "hr", "name": "worker_roles", "indexes": [{"name": "uq_hr_worker_roles_active_scope"}]}
    ] + [{"schema": "hr", "name": f"table_{number}", "indexes": []} for number in range(72)],
    "seeds": seed_manifest(),
}


class _CommandAdapter:
    def __init__(self, events: list[str], fail_at: str | None = None) -> None:
        self.events = events
        self.fail_at = fail_at
        self.environments: dict[str, dict[str, str]] = {}
        self.commands: dict[str, tuple[str, ...]] = {}

    def __call__(self, command: Sequence[str], environment: Mapping[str, str], label: str) -> None:
        self.events.append(label)
        self.commands[label] = tuple(command)
        self.environments[label] = dict(environment)
        if label == self.fail_at:
            raise RuntimeError(f"failure:{label}")


class _Connection:
    def __init__(self, database: str) -> None:
        self.database = database

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _config(
    tmp_path: Path, events: list[str], *, fail_at: str | None = None, fail_repeat_fingerprint: bool = False
) -> VerificationConfig:
    command = _CommandAdapter(events, fail_at)

    def safety(url: str, **_: object) -> object:
        events.append("safety:historical" if url == _HISTORICAL_URL else "safety:baseline")
        if fail_at == events[-1]:
            raise ValueError(f"failure:{events[-1]}")
        return DatabaseIdentity(
            database="wp_b04_historical_disposable" if url == _HISTORICAL_URL else "wp_b04_baseline_disposable",
            host="127.0.0.1", port=5432, username="runner",
        )

    def connect(url: str) -> _Connection:
        events.append("connect:historical" if url == _HISTORICAL_URL else "connect:baseline")
        return _Connection("historical" if url == _HISTORICAL_URL else "baseline")

    baseline_fingerprint_count = 0

    def fingerprint(connection: _Connection) -> Mapping[str, object]:
        nonlocal baseline_fingerprint_count
        label = f"fingerprint:{connection.database}"
        events.append(label)
        if connection.database == "baseline":
            baseline_fingerprint_count += 1
            if fail_repeat_fingerprint and baseline_fingerprint_count == 2:
                raise RuntimeError("failure:repeat-fingerprint:baseline")
        if fail_at == label:
            raise RuntimeError(f"failure:{label}")
        return _FINGERPRINT

    def absence(connection: _Connection) -> None:
        events.append(f"absence:{connection.database}")
        if fail_at == events[-1]:
            raise RuntimeError(f"failure:{events[-1]}")

    return VerificationConfig(
        historical_url=_HISTORICAL_URL,
        baseline_url=_BASELINE_URL,
        destructive_opt_in="YES",
        ownership_token=_TOKEN,
        historical_expected_database="wp_b04_historical_disposable",
        baseline_expected_database="wp_b04_baseline_disposable",
        source_sha="6c56f99edbd4e7346264ee14658d2076b5fd0775",
        expected_fingerprint_path=tmp_path / "expected-fingerprint.json",
        expected_fingerprint_sha256_path=tmp_path / "expected-fingerprint.sha256",
        report_path=tmp_path / "verification-report.json",
        command_runner=command,
        connection_factory=connect,
        safety_validator=safety,
        fingerprint_extractor=fingerprint,
        absence_checker=absence,
        fingerprint_serializer=lambda _: b'{"b04":"fingerprint"}\n',
        historical_alembic_ini=Path("historical.ini"),
        baseline_alembic_ini=Path("baseline.ini"),
        python_executable="python.exe",
    )


def test_b04_verify_001_runs_exact_fail_closed_sequence_and_writes_accepted_artifacts(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)

    report = verify_equivalence(config)

    assert events == [
        "safety:historical", "safety:baseline", "historical-upgrade", "connect:historical",
        "fingerprint:historical", "baseline-upgrade", "connect:baseline", "fingerprint:baseline",
        "baseline-downgrade", "connect:baseline", "absence:baseline", "baseline-reupgrade",
        "connect:baseline", "fingerprint:baseline",
    ]
    assert report.status == "B04A_VERIFIED"
    assert report.historical_digest == report.baseline_digest == report.reupgrade_digest
    expected = config.expected_fingerprint_path.read_bytes()
    assert config.expected_fingerprint_sha256_path.read_text(encoding="ascii") == (
        f"{hashlib.sha256(expected).hexdigest()}  expected-fingerprint.json\n"
    )
    saved = json.loads(config.report_path.read_text(encoding="utf-8"))
    assert saved["status"] == "B04A_VERIFIED"
    assert "history-pass" not in config.report_path.read_text(encoding="utf-8")
    assert "baseline-pass" not in config.report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fail_at", "forbidden"),
    [
        ("safety:historical", "safety:baseline"),
        ("safety:baseline", "historical-upgrade"),
        ("historical-upgrade", "fingerprint:historical"),
        ("fingerprint:historical", "baseline-upgrade"),
        ("baseline-upgrade", "fingerprint:baseline"),
        ("fingerprint:baseline", "baseline-downgrade"),
        ("baseline-downgrade", "absence:baseline"),
        ("absence:baseline", "baseline-reupgrade"),
        ("baseline-reupgrade", "fingerprint:baseline"),
    ],
)
def test_b04_verify_002_each_failure_stops_later_work_without_an_accepted_report(
    tmp_path: Path, fail_at: str, forbidden: str
) -> None:
    events: list[str] = []
    config = _config(tmp_path, events, fail_at=fail_at)

    with pytest.raises(VerificationError):
        verify_equivalence(config)

    assert fail_at in events
    assert forbidden not in events[events.index(fail_at) + 1 :]
    assert not config.report_path.exists()
    assert not config.expected_fingerprint_path.exists()
    assert not config.expected_fingerprint_sha256_path.exists()


def test_b04_verify_003_subprocesses_receive_only_explicit_context_environments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "ordinary-secret-must-not-leak")
    monkeypatch.setenv("POSTGRES_HOST", "ordinary-host-must-not-leak")
    events: list[str] = []
    config = _config(tmp_path, events)

    verify_equivalence(config)

    command = config.command_runner
    assert isinstance(command, _CommandAdapter)
    historical = command.environments["historical-upgrade"]
    expected_historical = {
        "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "wp_b04_historical_disposable", "POSTGRES_USER": "runner",
        "POSTGRES_PASSWORD": "history-pass", "POSTGRES_SCHEMA": "test",
    }
    if os.name == "nt":
        expected_historical["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    assert historical == expected_historical
    for label in ("baseline-upgrade", "baseline-downgrade", "baseline-reupgrade"):
        baseline = command.environments[label]
        expected_baseline = {
            "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE", "WELDPASSPORT_B04_OWNERSHIP_TOKEN",
            "WELDPASSPORT_B04_EXPECTED_DATABASE", "WELDPASSPORT_B04_DATABASE_URL",
        }
        if os.name == "nt":
            expected_baseline.add("SYSTEMROOT")
        assert set(baseline) == expected_baseline
        assert not set(baseline).intersection({"POSTGRES_HOST", "POSTGRES_PASSWORD"})


def test_b04_verify_003a_historical_environment_adds_only_windows_systemroot_and_never_inherits_process_values(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "must-not-inherit")
    monkeypatch.setenv("PYTHONPATH", "must-not-inherit")
    monkeypatch.setenv("WELDPASSPORT_B04_OWNERSHIP_TOKEN", "must-not-inherit")
    environment = _historical_environment(
        _HISTORICAL_URL, platform_name="nt", systemroot="C:\\Windows"
    )

    assert environment == {
        "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "wp_b04_historical_disposable", "POSTGRES_USER": "runner",
        "POSTGRES_PASSWORD": "history-pass", "POSTGRES_SCHEMA": "test",
        "SYSTEMROOT": "C:\\Windows",
    }


def test_b04_verify_003b_historical_environment_is_exactly_six_variables_off_windows() -> None:
    environment = _historical_environment(
        _HISTORICAL_URL, platform_name="posix", systemroot="ignored"
    )

    assert set(environment) == {
        "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER",
        "POSTGRES_PASSWORD", "POSTGRES_SCHEMA",
    }


@pytest.mark.parametrize("systemroot", [None, "", " \t "])
def test_b04_verify_003c_historical_environment_fails_closed_without_windows_systemroot(
    systemroot: str | None,
) -> None:
    with pytest.raises(VerificationError, match="B04-VERIFY-WINDOWS-SYSTEMROOT"):
        _historical_environment(_HISTORICAL_URL, platform_name="nt", systemroot=systemroot)


def test_b04_verify_003d_baseline_environment_is_exactly_four_variables_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "must-not-inherit")
    monkeypatch.setenv("WINDIR", "must-not-inherit")
    monkeypatch.setenv("SystemDrive", "must-not-inherit")
    monkeypatch.setenv("UNRELATED", "must-not-inherit")

    environment = verify_runner._baseline_environment(
        _config(tmp_path, []), platform_name="posix", systemroot="ignored"
    )

    assert environment == {
        "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE": "YES",
        "WELDPASSPORT_B04_OWNERSHIP_TOKEN": _TOKEN,
        "WELDPASSPORT_B04_EXPECTED_DATABASE": "wp_b04_baseline_disposable",
        "WELDPASSPORT_B04_DATABASE_URL": _BASELINE_URL,
    }


def test_b04_verify_003e_baseline_environment_adds_only_windows_systemroot_and_never_inherits_process_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "must-not-inherit")
    monkeypatch.setenv("WINDIR", "must-not-inherit")
    monkeypatch.setenv("SystemDrive", "must-not-inherit")
    monkeypatch.setenv("UNRELATED", "must-not-inherit")

    environment = verify_runner._baseline_environment(
        _config(tmp_path, []), platform_name="nt", systemroot="C:\\Windows"
    )

    assert environment == {
        "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE": "YES",
        "WELDPASSPORT_B04_OWNERSHIP_TOKEN": _TOKEN,
        "WELDPASSPORT_B04_EXPECTED_DATABASE": "wp_b04_baseline_disposable",
        "WELDPASSPORT_B04_DATABASE_URL": _BASELINE_URL,
        "SYSTEMROOT": "C:\\Windows",
    }


@pytest.mark.parametrize("systemroot", [None, "", " \t "])
def test_b04_verify_003f_baseline_environment_fails_closed_without_windows_systemroot(
    tmp_path: Path, systemroot: str | None,
) -> None:
    with pytest.raises(VerificationError, match="B04-VERIFY-WINDOWS-SYSTEMROOT"):
        verify_runner._baseline_environment(_config(tmp_path, []), platform_name="nt", systemroot=systemroot)


def test_b04_verify_004_rejects_a_report_for_the_wrong_source_cut_before_replay(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.source_sha = "0" * 40

    with pytest.raises(VerificationError, match="B04-VERIFY-SOURCE-CUT"):
        verify_equivalence(config)

    assert events == []
    assert not config.report_path.exists()


def test_b04_verify_005_preflights_artifacts_and_manifest_before_any_database_action(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.manifest_verifier = lambda *_: events.append("manifest")
    config.report_path = config.expected_fingerprint_path

    with pytest.raises(VerificationError, match="B04-VERIFY-ARTIFACT-TARGET"):
        verify_equivalence(config)

    assert events == []


def test_b04_verify_005a_rejects_an_existing_artifact_before_any_database_action(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.expected_fingerprint_sha256_path.write_text("existing", encoding="ascii")

    with pytest.raises(VerificationError, match="B04-VERIFY-ARTIFACT-EXISTS"):
        verify_equivalence(config)

    assert events == []


def test_b04_verify_006_manifest_failure_stops_before_disposable_safety(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)

    def manifest(_: Path, __: Path) -> None:
        events.append("manifest")
        raise ValueError("byte drift")

    config.manifest_verifier = manifest
    with pytest.raises(VerificationError, match="B04-VERIFY-MANIFEST"):
        verify_equivalence(config)

    assert events == ["manifest"]
    assert not config.report_path.exists()


def test_b04_verify_006a_historical_command_uses_the_isolated_context_config(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.manifest_verifier = lambda *_: None
    config.historical_alembic_ini = Path("migrations/b04/historical_alembic.ini")

    verify_equivalence(config)

    command = config.command_runner
    assert isinstance(command, _CommandAdapter)
    assert command.commands["historical-upgrade"][:4] == ("python.exe", "-m", "alembic", "-c")
    assert Path(command.commands["historical-upgrade"][4]) == Path("migrations/b04/historical_alembic.ini")
    assert command.commands["historical-upgrade"][5:] == ("upgrade", "head")


@pytest.mark.parametrize("failed_target", ["expected-fingerprint.json", "expected-fingerprint.sha256", "verification-report.json"])
def test_b04_verify_007_rolls_back_every_artifact_when_atomic_publication_fails(
    tmp_path: Path, failed_target: str
) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.manifest_verifier = lambda *_: events.append("manifest")

    observed_before_failure: list[tuple[str, tuple[str, ...]]] = []

    def link(source: Path, target: Path) -> None:
        if target.name == failed_target:
            observed_before_failure.append((
                target.name,
                tuple(path.name for path in (
                    config.expected_fingerprint_path,
                    config.expected_fingerprint_sha256_path,
                    config.report_path,
                ) if path.exists()),
            ))
            raise OSError("injected publication failure")
        os.link(source, target)

    config.artifact_linker = link
    with pytest.raises(VerificationError, match="B04-VERIFY-ARTIFACT-PUBLISH"):
        verify_equivalence(config)

    assert events[:3] == ["manifest", "safety:historical", "safety:baseline"]
    expected_earlier = {
        "expected-fingerprint.json": (),
        "expected-fingerprint.sha256": ("expected-fingerprint.json",),
        "verification-report.json": ("expected-fingerprint.json", "expected-fingerprint.sha256"),
    }
    assert observed_before_failure == [(failed_target, expected_earlier[failed_target])]
    assert not config.expected_fingerprint_path.exists()
    assert not config.expected_fingerprint_sha256_path.exists()
    assert not config.report_path.exists()


def test_b04_verify_008_racing_foreign_artifact_is_never_overwritten_or_deleted(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.manifest_verifier = lambda *_: None

    def race(source: Path, target: Path) -> None:
        target.write_bytes(b"foreign-race-artifact")
        os.link(source, target)

    config.artifact_linker = race
    with pytest.raises(VerificationError, match="B04-VERIFY-ARTIFACT-PUBLISH"):
        verify_equivalence(config)

    assert config.expected_fingerprint_path.read_bytes() == b"foreign-race-artifact"
    assert not config.expected_fingerprint_sha256_path.exists()
    assert not config.report_path.exists()


def test_b04_verify_008a_repeat_baseline_fingerprint_failure_stops_before_artifact_publication(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events, fail_repeat_fingerprint=True)
    config.manifest_verifier = lambda *_: None

    with pytest.raises(VerificationError, match="B04-VERIFY-FINGERPRINT"):
        verify_equivalence(config)

    assert events[-2:] == ["connect:baseline", "fingerprint:baseline"]
    assert events.count("fingerprint:baseline") == 2
    assert not config.expected_fingerprint_path.exists()
    assert not config.expected_fingerprint_sha256_path.exists()
    assert not config.report_path.exists()


def test_b04_verify_009_publication_cleanup_removes_every_created_temporary_on_later_write_failure(tmp_path: Path) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.manifest_verifier = lambda *_: None
    created: list[Path] = []

    def temporary(target: Path, data: bytes) -> Path:
        if target.name == "expected-fingerprint.sha256":
            raise OSError("injected temporary write failure")
        path = target.parent / f".{target.name}.injected.tmp"
        path.write_bytes(data)
        created.append(path)
        return path

    config.temporary_writer = temporary
    with pytest.raises(VerificationError, match="B04-VERIFY-ARTIFACT-PUBLISH"):
        verify_equivalence(config)

    assert created and all(not path.exists() for path in created)
    assert not config.expected_fingerprint_path.exists()
    assert not config.expected_fingerprint_sha256_path.exists()
    assert not config.report_path.exists()


def test_b04_verify_010_fingerprint_connection_has_a_ten_second_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    observed: dict[str, object] = {}

    class Engine:
        def connect(self) -> object:
            return connection

    def create_engine(url: str, **kwargs: object) -> Engine:
        observed["url"] = url
        observed.update(kwargs)
        return Engine()

    monkeypatch.setattr(verify_runner, "create_engine", create_engine)

    assert verify_runner._connect(_HISTORICAL_URL) is connection
    assert observed["url"] == _HISTORICAL_URL
    assert observed["future"] is True
    assert observed["connect_args"] == {"connect_timeout": 10}


def test_b04_verify_011_alembic_subprocess_has_a_three_hundred_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run(command: Sequence[str], **kwargs: object) -> None:
        observed["command"] = tuple(command)
        observed.update(kwargs)

    monkeypatch.setattr(verify_runner.subprocess, "run", run)

    verify_runner._run_command(("python.exe", "-m", "alembic"), {"ONLY": "explicit"}, "phase")

    assert observed["command"] == ("python.exe", "-m", "alembic")
    assert observed["env"] == {"ONLY": "explicit"}
    assert observed["check"] is True
    assert observed["capture_output"] is True
    assert observed["text"] is True
    assert observed["timeout"] == 300


def test_b04_verify_012_subprocess_timeout_keeps_the_existing_phase_code_and_secret_free_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    config = _config(tmp_path, events)
    config.command_runner = verify_runner._run_command

    def timeout(command: Sequence[str], **_: object) -> None:
        raise subprocess.TimeoutExpired(
            command,
            300,
            output="historical command output with history-pass",
            stderr="POSTGRES_PASSWORD=history-pass",
        )

    monkeypatch.setattr(verify_runner.subprocess, "run", timeout)

    with pytest.raises(VerificationError, match="^B04-VERIFY-HISTORICAL-UPGRADE$") as captured:
        verify_runner._run(config, "historical-upgrade", {"POSTGRES_PASSWORD": "history-pass"}, "history.ini", "upgrade", "head")

    assert str(captured.value) == "B04-VERIFY-HISTORICAL-UPGRADE"
    assert "history-pass" not in str(captured.value)
    assert "POSTGRES_PASSWORD" not in str(captured.value)


def test_b04_verify_013_main_emits_only_stable_verification_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = object()

    monkeypatch.setattr(
        verify_runner.VerificationConfig,
        "from_environment",
        classmethod(lambda cls: config),
    )

    def fail(_: object) -> None:
        try:
            raise RuntimeError(
                "postgresql+psycopg://runner:secret-password@127.0.0.1/database "
                "ownership-token-123"
            )
        except RuntimeError as cause:
            raise VerificationError("B04-VERIFY-BASELINE-UPGRADE") from cause

    monkeypatch.setattr(verify_runner, "verify_equivalence", fail)

    with pytest.raises(SystemExit) as captured:
        verify_runner.main()

    output = capsys.readouterr()
    assert captured.value.code == 1
    assert output.out == ""
    assert output.err == "B04-VERIFY-BASELINE-UPGRADE\n"
    assert "secret-password" not in output.err
    assert "ownership-token-123" not in output.err
    assert "postgresql+psycopg://" not in output.err


def test_b04_verify_014_main_does_not_normalize_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = object()
    unexpected = RuntimeError("unexpected implementation failure")

    monkeypatch.setattr(
        verify_runner.VerificationConfig,
        "from_environment",
        classmethod(lambda cls: config),
    )

    def fail(_: object) -> None:
        raise unexpected

    monkeypatch.setattr(verify_runner, "verify_equivalence", fail)

    with pytest.raises(RuntimeError) as captured:
        verify_runner.main()

    output = capsys.readouterr()
    assert captured.value is unexpected
    assert output.out == ""
    assert output.err == ""
