import json
from pathlib import Path
from uuid import UUID

import pytest

from app.testing.f2_contract import F2Role
from app.testing.f2_evidence import publish_artifact
from app.testing.f2_operator_preflight import (
    F2OperatorPreflightStatus,
    OperatorPreflightDependencies,
    OperatorSourceState,
    run_operator_preflight,
)
from scripts.run_test_db_f2_operator_preflight import main as cli_main


PREFLIGHT_ID = UUID("12345678-1234-4234-8234-123456789abc")
SOURCE_SHA = "a" * 40


def _environment(root: Path) -> dict[str, str]:
    environment = {
        "WELDPASSPORT_F2_WORKING_DATABASE_URL": (
            "postgresql+psycopg://worker:working-secret@localhost/weldpassport_dev"
        ),
        "WELDPASSPORT_F2_EVIDENCE_DIR": str(root),
        "WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION": (
            "I_AUTHORIZE_TEST_DB_F2_OPERATOR_PREFLIGHT"
        ),
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
    }
    for role in F2Role:
        prefix = role.value.upper()
        environment[f"WELDPASSPORT_F2_{prefix}_TEST_DATABASE_URL"] = (
            "postgresql+psycopg://worker:target-secret@localhost/"
            f"test_{role.value}"
        )
        environment[f"WELDPASSPORT_F2_{prefix}_DATABASE_CONFIRM"] = (
            f"test_{role.value}"
        )
        environment[f"WELDPASSPORT_F2_{prefix}_OWNERSHIP_TOKEN"] = (
            f"token-{role.value}"
        )
    return environment


class FakeSourceInspector:
    def __init__(self) -> None:
        self.calls = 0

    def read_state(
        self,
        prerequisites: tuple[str, ...],
    ) -> OperatorSourceState:
        self.calls += 1
        return OperatorSourceState(
            source_sha=SOURCE_SHA,
            branch="codex/b04b-maintenance-readiness-review",
            tracked_clean=True,
            prerequisites=tuple((sha, True) for sha in prerequisites),
        )


def _dependencies(
    source: FakeSourceInspector,
    publisher=publish_artifact,
) -> OperatorPreflightDependencies:
    return OperatorPreflightDependencies(
        source_inspector=source,
        uuid_factory=lambda: PREFLIGHT_ID,
        clock=lambda: "2026-07-30T12:00:00Z",
        publisher=publisher,
    )


def test_f2_operator_runner_001_publishes_one_redacted_ready_artifact(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    source = FakeSourceInspector()

    result = run_operator_preflight(
        _environment(evidence_root),
        _dependencies(source),
    )

    namespace = evidence_root / f"operator-preflight-{PREFLIGHT_ID}"
    artifact = namespace / "00_operator_preflight.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert result.status is F2OperatorPreflightStatus.READY
    assert result.preflight_id == PREFLIGHT_ID
    assert result.artifact_digest is not None
    assert source.calls == 1
    assert list(namespace.iterdir()) == [artifact]
    assert payload["status"] == "TEST_DB_F2_OPERATOR_PREFLIGHT_READY"
    assert [item["role"] for item in payload["targets"]] == [
        role.value for role in F2Role
    ]
    rendered = artifact.read_text(encoding="utf-8")
    for forbidden in (
        "working-secret",
        "target-secret",
        "token-",
        "weldpassport_dev",
        "test_canonical",
    ):
        assert forbidden not in rendered


def test_f2_operator_runner_002_fails_before_source_on_bad_authorization(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    environment = _environment(evidence_root)
    environment["WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION"] = "wrong"
    source = FakeSourceInspector()

    result = run_operator_preflight(environment, _dependencies(source))

    assert result.status is F2OperatorPreflightStatus.FAILED
    assert result.preflight_id is None
    assert source.calls == 0
    assert list(evidence_root.iterdir()) == []


def test_f2_operator_runner_003_collision_precedes_namespace(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    environment = _environment(evidence_root)
    environment[
        "WELDPASSPORT_F2_LEGACY_NEGATIVE_TEST_DATABASE_URL"
    ] = environment["WELDPASSPORT_F2_CANONICAL_TEST_DATABASE_URL"]
    environment["WELDPASSPORT_F2_LEGACY_NEGATIVE_DATABASE_CONFIRM"] = (
        environment["WELDPASSPORT_F2_CANONICAL_DATABASE_CONFIRM"]
    )

    result = run_operator_preflight(
        environment,
        _dependencies(FakeSourceInspector()),
    )

    assert result.status is F2OperatorPreflightStatus.FAILED
    assert result.preflight_id is None
    assert list(evidence_root.iterdir()) == []


def test_f2_operator_runner_004_evidence_failure_has_precedence(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()

    def fail_publish(path: Path, payload: dict[str, object]) -> object:
        raise OSError("raw unsafe failure")

    result = run_operator_preflight(
        _environment(evidence_root),
        _dependencies(FakeSourceInspector(), fail_publish),
    )

    assert result.status is F2OperatorPreflightStatus.EVIDENCE_FAILED
    assert result.preflight_id == PREFLIGHT_ID
    assert result.artifact_digest is None


def test_f2_operator_runner_005_existing_namespace_is_evidence_failure(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / f"operator-preflight-{PREFLIGHT_ID}").mkdir()

    result = run_operator_preflight(
        _environment(evidence_root),
        _dependencies(FakeSourceInspector()),
    )

    assert result.status is F2OperatorPreflightStatus.EVIDENCE_FAILED
    assert result.artifact_digest is None


def test_f2_operator_runner_006_cli_exit_and_output_are_safe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    environment = _environment(evidence_root)
    dependencies = _dependencies(FakeSourceInspector())

    exit_code = cli_main(
        environment=environment,
        dependencies=dependencies,
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert set(output) == {"artifact_digest", "preflight_id", "status"}
    assert output["preflight_id"] == str(PREFLIGHT_ID)
    assert output["status"] == "TEST_DB_F2_OPERATOR_PREFLIGHT_READY"
    assert len(output["artifact_digest"]) == 64
