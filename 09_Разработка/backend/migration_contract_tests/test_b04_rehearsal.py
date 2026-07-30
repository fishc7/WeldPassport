from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

from migrations.b04.disposable import DatabaseIdentity
import migrations.b04.rehearse_adoption as rehearsal_module
from migrations.b04.rehearse_adoption import (
    RehearsalConfig,
    RehearsalDependencies,
    RehearsalError,
    RehearsalReport,
    canonical_report_bytes,
    main,
    publish_report_once,
    run_rehearsal,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


@dataclass(frozen=True)
class _Prepared:
    adoption_id: str


@dataclass(frozen=True)
class _Postflight:
    verified: bool


def _identity(database: str) -> DatabaseIdentity:
    return DatabaseIdentity(
        database=database,
        host="db.internal",
        port=5432,
        username="maintenance_operator",
    )


def _config(tmp_path: Path) -> RehearsalConfig:
    backup = tmp_path / "working.dump"
    backup.write_bytes(b"PGDMP accepted backup")
    report_directory = tmp_path / "external-reports"
    report_directory.mkdir()
    return RehearsalConfig(
        adoption_id="b04b-rehearsal-001",
        backup_path=backup,
        expected_backup_sha256=SHA_A,
        working_identity=_identity("WeldPassport"),
        rehearsal_identity=_identity("wp_b04b_rehearsal"),
        recovery_identity=_identity("wp_b04b_recovery"),
        expected_server_version_num=180003,
        expected_live_fingerprint_sha256=SHA_B,
        expected_restore_fingerprint_sha256=SHA_C,
        report_directory=report_directory,
        started_at_utc="2026-07-30T09:00:00Z",
        completed_at_utc="2026-07-30T09:10:00Z",
    )


def _dependencies(events: list[str]) -> RehearsalDependencies:
    def verify_backup(config: RehearsalConfig) -> str:
        events.append("backup")
        return config.expected_backup_sha256

    def restore_backup(
        _backup: Path,
        identity: DatabaseIdentity,
        version: int,
    ) -> None:
        events.append(f"restore:{identity.database}:{version}")

    def verify_fingerprints(config: RehearsalConfig) -> tuple[str, str]:
        events.append("fingerprints")
        return (
            config.expected_live_fingerprint_sha256,
            config.expected_restore_fingerprint_sha256,
        )

    def preflight(config: RehearsalConfig) -> _Prepared:
        events.append("preflight")
        return _Prepared(config.adoption_id)

    def transfer(config: RehearsalConfig, prepared: object) -> None:
        assert prepared == _Prepared(config.adoption_id)
        events.append("transfer")

    def postflight(config: RehearsalConfig, prepared: object) -> _Postflight:
        assert prepared == _Prepared(config.adoption_id)
        events.append("postflight")
        return _Postflight(verified=True)

    def verify_recovery(config: RehearsalConfig) -> str:
        events.append("recovery")
        return config.expected_restore_fingerprint_sha256

    def publish(report: RehearsalReport, directory: Path) -> Path:
        events.append("report")
        assert directory.name == "external-reports"
        assert report.status == "B04B_REHEARSAL_ACCEPTED"
        return directory / f"{report.adoption_id}.json"

    return RehearsalDependencies(
        verify_backup=verify_backup,
        restore_backup=restore_backup,
        verify_fingerprints=verify_fingerprints,
        run_preflight=preflight,
        transfer_marker=transfer,
        run_postflight=postflight,
        verify_recovery=verify_recovery,
        publish_report=publish,
    )


def test_b04b_rehearsal_001_runs_the_complete_sequence_once(tmp_path: Path) -> None:
    events: list[str] = []

    result = run_rehearsal(_config(tmp_path), _dependencies(events))

    assert events == [
        "backup",
        "restore:wp_b04b_rehearsal:180003",
        "fingerprints",
        "preflight",
        "transfer",
        "postflight",
        "restore:wp_b04b_recovery:180003",
        "recovery",
        "report",
    ]
    assert result.report.status == "B04B_REHEARSAL_ACCEPTED"
    assert result.report_path.name == "b04b-rehearsal-001.json"


@pytest.mark.parametrize(
    ("working", "rehearsal", "recovery"),
    [
        ("same", "same", "recovery"),
        ("working", "same", "same"),
        ("same", "same", "same"),
    ],
)
def test_b04b_rehearsal_002_refuses_reused_database_identity_before_io(
    tmp_path: Path,
    working: str,
    rehearsal: str,
    recovery: str,
) -> None:
    config = _config(tmp_path)
    config = replace(
        config,
        working_identity=_identity(working),
        rehearsal_identity=_identity(rehearsal),
        recovery_identity=_identity(recovery),
    )
    events: list[str] = []

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-IDENTITY"):
        run_rehearsal(config, _dependencies(events))

    assert events == []


@pytest.mark.parametrize(
    "failure_stage",
    [
        "backup",
        "restore:wp_b04b_rehearsal:180003",
        "fingerprints",
        "preflight",
        "transfer",
        "postflight",
        "restore:wp_b04b_recovery:180003",
        "recovery",
    ],
)
def test_b04b_rehearsal_003_stops_at_first_failure_without_acceptance_report(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    events: list[str] = []
    dependencies = _dependencies(events)

    def fail(*_args: object) -> object:
        events.append(failure_stage)
        raise RuntimeError("secret=postgresql://user:password@host/db")

    replacements = {
        "backup": "verify_backup",
        "restore:wp_b04b_rehearsal:180003": "restore_backup",
        "fingerprints": "verify_fingerprints",
        "preflight": "run_preflight",
        "transfer": "transfer_marker",
        "postflight": "run_postflight",
        "restore:wp_b04b_recovery:180003": "restore_backup",
        "recovery": "verify_recovery",
    }
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values[replacements[failure_stage]] = fail

    with pytest.raises(RehearsalError) as caught:
        run_rehearsal(_config(tmp_path), RehearsalDependencies(**values))

    assert "password" not in str(caught.value)
    assert "postgresql://" not in str(caught.value)
    assert "report" not in events


def test_b04b_rehearsal_004_rejects_unexpected_authorizing_digests(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    dependencies = _dependencies(events)
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values["verify_fingerprints"] = lambda _config: (SHA_C, SHA_B)

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-FINGERPRINT"):
        run_rehearsal(_config(tmp_path), RehearsalDependencies(**values))

    assert "preflight" not in events
    assert "report" not in events


def test_b04b_rehearsal_005_requires_verified_postflight(tmp_path: Path) -> None:
    events: list[str] = []
    dependencies = _dependencies(events)
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values["run_postflight"] = lambda _config, _prepared: _Postflight(
        verified=False
    )

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-POSTFLIGHT"):
        run_rehearsal(_config(tmp_path), RehearsalDependencies(**values))

    assert "recovery" not in events
    assert "report" not in events


def test_b04b_rehearsal_006_requires_recovery_restore_digest(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    dependencies = _dependencies(events)
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values["verify_recovery"] = lambda _config: SHA_B

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-RECOVERY"):
        run_rehearsal(_config(tmp_path), RehearsalDependencies(**values))

    assert "report" not in events


def test_b04b_rehearsal_007_report_is_canonical_and_contains_no_credentials(
    tmp_path: Path,
) -> None:
    result = run_rehearsal(_config(tmp_path), _dependencies([]))

    raw = canonical_report_bytes(result.report)
    value = json.loads(raw)

    assert raw.endswith(b"\n")
    assert raw == (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert set(value) == {
        "adoption_id",
        "backup_sha256",
        "completed_at_utc",
        "live_fingerprint_sha256",
        "recovery_database",
        "rehearsal_database",
        "restore_fingerprint_sha256",
        "server_version_num",
        "started_at_utc",
        "status",
    }
    assert b"maintenance_operator" not in raw
    assert b"db.internal" not in raw


def test_b04b_rehearsal_008_report_publication_is_create_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    result = run_rehearsal(config, _dependencies([]))
    unrelated_root = tmp_path / "unrelated-repository"
    unrelated_root.mkdir()
    monkeypatch.setattr(
        rehearsal_module,
        "_REPOSITORY_ROOT",
        unrelated_root,
    )

    first = publish_report_once(config.report_directory, result.report)
    original = first.read_bytes()

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-REPORT"):
        publish_report_once(config.report_directory, result.report)

    assert first.read_bytes() == original


def test_b04b_rehearsal_009_report_publication_refuses_repository_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    result = run_rehearsal(config, _dependencies([]))
    monkeypatch.setattr(
        rehearsal_module,
        "_REPOSITORY_ROOT",
        tmp_path.parent,
    )

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-REPORT"):
        publish_report_once(config.report_directory, result.report)


def test_b04b_rehearsal_010_malformed_version_fails_before_io(
    tmp_path: Path,
) -> None:
    config = replace(_config(tmp_path), expected_server_version_num="180003")
    events: list[str] = []

    with pytest.raises(RehearsalError, match="B04B-REHEARSAL-CONFIG"):
        run_rehearsal(config, _dependencies(events))

    assert events == []


def test_b04b_rehearsal_011_second_restore_failure_stops_before_recovery(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    dependencies = _dependencies(events)
    restore_calls = 0

    def fail_second_restore(
        backup: Path,
        identity: DatabaseIdentity,
        version: int,
    ) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 2:
            raise RuntimeError("recovery restore failed")
        dependencies.restore_backup(backup, identity, version)

    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values["restore_backup"] = fail_second_restore

    with pytest.raises(
        RehearsalError,
        match="B04B-REHEARSAL-RECOVERY-RESTORE",
    ):
        run_rehearsal(_config(tmp_path), RehearsalDependencies(**values))

    assert "recovery" not in events
    assert "report" not in events


def test_b04b_rehearsal_012_standalone_invocation_requires_operator_adapters(
) -> None:
    with pytest.raises(
        SystemExit,
        match="B04B-REHEARSAL-ADAPTERS-REQUIRED",
    ):
        main()
