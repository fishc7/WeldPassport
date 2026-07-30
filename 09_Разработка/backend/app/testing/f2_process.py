"""Isolated TEST-DB-F2 worker process boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Mapping

from app.testing.f2_contract import (
    F2Error,
    F2_PROTOCOL_VERSION,
    F2WorkerRequest,
    F2Role,
)
from app.testing.f2_preflight import F2AuthorizedTarget, F2OfflinePlan


_RUNTIME_ALLOWLIST = (
    "SystemRoot",
    "WINDIR",
    "SystemDrive",
    "TEMP",
    "TMP",
    "PATH",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
)
_SECRET_KEYS = (
    "TEST_DATABASE_URL",
    "WELDPASSPORT_F2_WORKING_DATABASE_URL",
    "WELDPASSPORT_TEST_DB_CONFIRM",
    "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN",
)


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class ProcessExecutor:
    def run(
        self,
        argv: tuple[str, ...],
        environment: Mapping[str, str],
        timeout_seconds: int,
    ) -> ProcessResult:
        secret_values = tuple(
            value
            for key, value in environment.items()
            if key in _SECRET_KEYS and value
        )
        if any(secret in argument for secret in secret_values for argument in argv):
            raise F2Error(
                "TEST-DB-F2-WORKER-PROTOCOL",
                "TEST-DB-F2 worker arguments are unsafe",
            )
        try:
            completed = subprocess.run(
                argv,
                env=dict(environment),
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(124, "", "", True)
        except OSError:
            return ProcessResult(1, "", "", False)

        return ProcessResult(
            completed.returncode,
            _redact(completed.stdout, secret_values),
            _redact(completed.stderr, secret_values),
            False,
        )


def _redact(value: str, secrets: tuple[str, ...]) -> str:
    rendered = value
    for secret in secrets:
        rendered = rendered.replace(secret, "[REDACTED]")
    return rendered


def build_worker_environment(
    plan: F2OfflinePlan,
    target: F2AuthorizedTarget,
    artifact_path: Path,
    parent_environment: Mapping[str, str],
) -> dict[str, str]:
    child = {
        key: parent_environment[key]
        for key in _RUNTIME_ALLOWLIST
        if key in parent_environment
    }
    authorization = target.authorization
    child.update(
        {
            "WELDPASSPORT_F2_PROTOCOL_VERSION": F2_PROTOCOL_VERSION,
            "WELDPASSPORT_F2_RUN_ID": str(plan.run_id),
            "WELDPASSPORT_F2_SOURCE_SHA": plan.source_sha,
            "WELDPASSPORT_F2_ROLE": target.role.value,
            "WELDPASSPORT_F2_ARTIFACT_PATH": str(artifact_path),
            "WELDPASSPORT_F2_IDENTITY_DIGEST": target.identity_digest,
            "WELDPASSPORT_F2_WORKING_DATABASE_URL": parent_environment[
                "WELDPASSPORT_F2_WORKING_DATABASE_URL"
            ],
            "TEST_DATABASE_URL": authorization.target.url.render_as_string(
                hide_password=False
            ),
            "WELDPASSPORT_TEST_DB_CONFIRM": (
                authorization.target.database_name
            ),
            "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN": (
                authorization.ownership_token
            ),
            "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
        }
    )
    if target.role is not F2Role.CANONICAL:
        child["WELDPASSPORT_RUNTIME_PROFILE"] = "legacy_compatibility"
        child["WELDPASSPORT_LEGACY_SCHEMA"] = "test"
    return child


def build_worker_argv(
    python_executable: str,
    request: F2WorkerRequest,
) -> tuple[str, ...]:
    return (
        python_executable,
        "-m",
        "app.testing.f2_worker",
        "--role",
        request.role.value,
        "--run-id",
        request.run_id,
    )
