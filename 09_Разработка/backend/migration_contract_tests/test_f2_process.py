from pathlib import Path
from uuid import UUID

import pytest

from app.shared.database_target import authorize_test_database
from app.testing.f2_contract import (
    F2_PROTOCOL_VERSION,
    F2Role,
    F2WorkerRequest,
)
from app.testing.f2_preflight import (
    F2AuthorizedTarget,
    F2OfflinePlan,
)
from app.testing.f2_process import (
    ProcessExecutor,
    build_worker_argv,
    build_worker_environment,
)


RUN_ID = UUID("12345678-1234-4234-8234-123456789abc")


def _target(role: F2Role) -> F2AuthorizedTarget:
    authorization = authorize_test_database(
        test_database_url=(
            "postgresql+psycopg://worker:secret@localhost/"
            f"test_{role.value}"
        ),
        working_database_url=(
            "postgresql+psycopg://worker:secret@localhost/weldpassport_dev"
        ),
        destructive_opt_in="YES",
        confirmed_database_name=f"test_{role.value}",
        ownership_token=f"token-{role.value}",
    )
    return F2AuthorizedTarget(role, authorization, "d" * 64)


def _plan(tmp_path: Path, role: F2Role) -> tuple[F2OfflinePlan, F2AuthorizedTarget]:
    target = _target(role)
    return (
        F2OfflinePlan(RUN_ID, "a" * 40, tmp_path, (target,)),
        target,
    )


@pytest.mark.parametrize("role", list(F2Role))
def test_f2_process_001_child_environment_is_minimal(
    tmp_path: Path,
    role: F2Role,
) -> None:
    plan, target = _plan(tmp_path, role)
    parent = {
        "SystemRoot": "C:\\Windows",
        "PATH": "C:\\Python",
        "UNRELATED_SENTINEL": "must-not-pass",
        "DATABASE_URL": "parent-secret",
        "WELDPASSPORT_F2_WORKING_DATABASE_URL": (
            "postgresql+psycopg://worker:secret@localhost/weldpassport_dev"
        ),
    }

    child = build_worker_environment(
        plan,
        target,
        tmp_path / "result.json",
        parent,
    )

    assert "UNRELATED_SENTINEL" not in child
    assert "DATABASE_URL" not in child
    assert child["WELDPASSPORT_F2_WORKING_DATABASE_URL"].endswith(
        "/weldpassport_dev"
    )
    assert child["TEST_DATABASE_URL"].endswith(f"/test_{role.value}")
    assert child["WELDPASSPORT_F2_ROLE"] == role.value
    if role is F2Role.CANONICAL:
        assert "WELDPASSPORT_RUNTIME_PROFILE" not in child
        assert "WELDPASSPORT_LEGACY_SCHEMA" not in child
    else:
        assert child["WELDPASSPORT_RUNTIME_PROFILE"] == "legacy_compatibility"
        assert child["WELDPASSPORT_LEGACY_SCHEMA"] == "test"


def test_f2_process_002_worker_argv_contains_only_safe_identity() -> None:
    request = F2WorkerRequest(
        F2_PROTOCOL_VERSION,
        str(RUN_ID),
        "a" * 40,
        F2Role.CANONICAL,
        "10_canonical.json",
    )

    argv = build_worker_argv("C:\\Python\\python.exe", request)
    rendered = " ".join(argv)

    assert argv[:3] == (
        "C:\\Python\\python.exe",
        "-m",
        "app.testing.f2_worker",
    )
    assert "secret" not in rendered
    assert "postgresql" not in rendered
    assert request.role.value in argv
    assert request.run_id in argv


def test_f2_process_003_executor_uses_shell_false_and_redacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Completed:
        returncode = 7
        stdout = "url-secret appeared"
        stderr = "token-secret appeared"

    def fake_run(*args: object, **kwargs: object) -> Completed:
        calls.append({"args": args, **kwargs})
        return Completed()

    monkeypatch.setattr("app.testing.f2_process.subprocess.run", fake_run)
    result = ProcessExecutor().run(
        ("python", "-m", "worker"),
        {
            "TEST_DATABASE_URL": "url-secret",
            "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN": "token-secret",
        },
        60,
    )

    assert len(calls) == 1
    assert calls[0]["shell"] is False
    assert calls[0]["check"] is False
    assert "url-secret" not in result.stdout
    assert "token-secret" not in result.stderr
    assert result.exit_code == 7
    assert result.timed_out is False


def test_f2_process_004_timeout_is_safe_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def timeout(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise __import__("subprocess").TimeoutExpired(args[0], 1)

    monkeypatch.setattr("app.testing.f2_process.subprocess.run", timeout)
    result = ProcessExecutor().run(("python",), {}, 1)

    assert calls == 1
    assert result.timed_out is True
    assert result.exit_code != 0
    assert result.stdout == result.stderr == ""


def test_f2_process_005_redacts_url_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Completed:
        returncode = 1
        stdout = "driver exposed pw-123 for test_canonical"
        stderr = ""

    monkeypatch.setattr(
        "app.testing.f2_process.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )
    result = ProcessExecutor().run(
        ("python",),
        {
            "TEST_DATABASE_URL": (
                "postgresql+psycopg://worker:pw-123@localhost/test_canonical"
            )
        },
        10,
    )

    assert "pw-123" not in result.stdout
    assert "test_canonical" not in result.stdout
