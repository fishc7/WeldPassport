"""One-role TEST-DB-F2 worker.

Database-backed modules are imported only by default dependency callables after
the authorized target has been bound.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import ContextManager, Mapping, Protocol
from uuid import UUID

from sqlalchemy import text

from app.shared.database_target import (
    DatabaseTarget,
    TestDatabaseAuthorization,
    authorize_test_database,
)
from app.testing.f2_contract import (
    F2Error,
    F2_PROTOCOL_VERSION,
    F2Role,
    F2WorkerRequest,
)
from app.testing.f2_evidence import PublishedArtifact, publish_artifact
from app.testing.f2_role_adapters import (
    CommandExecutor,
    OperationalRoleAdapter,
    RoleAdapter,
)


_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_NAMES = {
    F2Role.CANONICAL: "10_canonical.json",
    F2Role.LEGACY_COMPATIBLE: "20_legacy_compatible.json",
    F2Role.LEGACY_NEGATIVE: "30_legacy_negative.json",
}


class LiveGate(Protocol):
    def __call__(
        self,
        authorization: TestDatabaseAuthorization,
    ) -> ContextManager[object]: ...


@dataclass(frozen=True)
class WorkerDependencies:
    authorize: Callable[..., TestDatabaseAuthorization]
    bind: Callable[[DatabaseTarget], object]
    live_gate: LiveGate
    version_gate: Callable[[object], int]
    empty_gate: Callable[[object], None]
    role_adapter: RoleAdapter
    publisher: Callable[
        [Path, Mapping[str, object]],
        PublishedArtifact,
    ]


def _protocol_error() -> F2Error:
    return F2Error(
        "TEST-DB-F2-WORKER-PROTOCOL",
        "TEST-DB-F2 worker protocol is invalid",
    )


def _validate_request(
    request: F2WorkerRequest,
    environment: Mapping[str, str],
) -> Path:
    try:
        run_id = UUID(request.run_id)
    except (TypeError, ValueError):
        raise _protocol_error() from None
    artifact_path = Path(environment.get("WELDPASSPORT_F2_ARTIFACT_PATH", ""))
    expected_profile = (
        request.role is F2Role.CANONICAL
        and "WELDPASSPORT_RUNTIME_PROFILE" not in environment
        and "WELDPASSPORT_LEGACY_SCHEMA" not in environment
    ) or (
        request.role is not F2Role.CANONICAL
        and environment.get("WELDPASSPORT_RUNTIME_PROFILE")
        == "legacy_compatibility"
        and environment.get("WELDPASSPORT_LEGACY_SCHEMA") == "test"
    )
    if (
        request.protocol_version != F2_PROTOCOL_VERSION
        or run_id.version != 4
        or _SOURCE_SHA.fullmatch(request.source_sha) is None
        or request.artifact_name != _ARTIFACT_NAMES.get(request.role)
        or environment.get("WELDPASSPORT_F2_PROTOCOL_VERSION")
        != request.protocol_version
        or environment.get("WELDPASSPORT_F2_RUN_ID") != request.run_id
        or environment.get("WELDPASSPORT_F2_SOURCE_SHA")
        != request.source_sha
        or environment.get("WELDPASSPORT_F2_ROLE") != request.role.value
        or artifact_path.name != request.artifact_name
        or artifact_path.exists()
        or not expected_profile
        or _DIGEST.fullmatch(
            environment.get("WELDPASSPORT_F2_IDENTITY_DIGEST", "")
        )
        is None
        or _DIGEST.fullmatch(
            environment.get("WELDPASSPORT_F2_PREVIOUS_DIGEST", "")
        )
        is None
    ):
        raise _protocol_error()
    return artifact_path


class _BoundCommandExecutor(CommandExecutor):
    """Run Alembic in the bound process; pytest binds again in a fresh child."""

    def run(self, argv: tuple[str, ...]) -> int:
        if argv[:3] == (sys.executable, "-m", "alembic"):
            try:
                from alembic.config import CommandLine

                CommandLine(prog="alembic").main(list(argv[3:]))
                return 0
            except SystemExit as exc:
                return int(exc.code or 0)
            except Exception:
                return 1
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return 1
        return completed.returncode


def _default_dependencies() -> WorkerDependencies:
    from contextlib import contextmanager

    from app.shared.database_bootstrap import bind_database_target

    @contextmanager
    def live_gate(authorization: TestDatabaseAuthorization):
        from app.shared.db import engine
        from app.shared.test_database_ownership import (
            verify_test_database_ownership,
        )

        with engine.connect() as connection:
            verify_test_database_ownership(connection, authorization)
            yield connection

    def version_gate(connection: object) -> int:
        return int(connection.execute(text("SHOW server_version_num")).scalar_one())

    def empty_gate(connection: object) -> None:
        count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'S')
                      AND namespace.nspname NOT IN
                          ('pg_catalog', 'information_schema')
                      AND namespace.nspname NOT LIKE 'pg_toast%'
                    """
                )
            ).scalar_one()
        )
        if count != 0:
            raise F2Error(
                "TEST-DB-F2-TARGET-NOT-EMPTY",
                "TEST-DB-F2 target is not empty",
            )

    return WorkerDependencies(
        authorize=authorize_test_database,
        bind=bind_database_target,
        live_gate=live_gate,
        version_gate=version_gate,
        empty_gate=empty_gate,
        role_adapter=OperationalRoleAdapter(
            executor=_BoundCommandExecutor(),
            handlers={},
            python_executable=sys.executable,
        ),
        publisher=publish_artifact,
    )


def run_worker(
    request: F2WorkerRequest,
    environment: Mapping[str, str],
    dependencies: WorkerDependencies | None = None,
) -> PublishedArtifact:
    artifact_path = _validate_request(request, environment)
    deps = _default_dependencies() if dependencies is None else dependencies
    authorization = deps.authorize(
        test_database_url=environment.get("TEST_DATABASE_URL"),
        working_database_url=environment.get(
            "WELDPASSPORT_F2_WORKING_DATABASE_URL", ""
        ),
        destructive_opt_in=environment.get(
            "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS"
        ),
        confirmed_database_name=environment.get(
            "WELDPASSPORT_TEST_DB_CONFIRM"
        ),
        ownership_token=environment.get(
            "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN"
        ),
    )
    deps.bind(authorization.target)

    with deps.live_gate(authorization) as connection:
        version = deps.version_gate(connection)
        if version != 180003:
            raise F2Error(
                "TEST-DB-F2-VERSION-MISMATCH",
                "TEST-DB-F2 PostgreSQL version does not match",
            )
        deps.empty_gate(connection)
        role_result = dict(deps.role_adapter.run(request.role))

    return deps.publisher(
        artifact_path,
        {
            "protocol_version": F2_PROTOCOL_VERSION,
            "run_id": request.run_id,
            "source_sha": request.source_sha,
            "previous_digest": environment[
                "WELDPASSPORT_F2_PREVIOUS_DIGEST"
            ],
            "role": request.role.value,
            "status": "verified",
            "verified_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "server_version_num": version,
            "identity_digest": environment[
                "WELDPASSPORT_F2_IDENTITY_DIGEST"
            ],
            "gate_results": role_result,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=[role.value for role in F2Role])
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args()
    environment = os.environ
    role = F2Role(arguments.role)
    request = F2WorkerRequest(
        protocol_version=environment.get(
            "WELDPASSPORT_F2_PROTOCOL_VERSION", ""
        ),
        run_id=arguments.run_id,
        source_sha=environment.get("WELDPASSPORT_F2_SOURCE_SHA", ""),
        role=role,
        artifact_name=Path(
            environment.get("WELDPASSPORT_F2_ARTIFACT_PATH", "")
        ).name,
    )
    try:
        artifact = run_worker(request, environment)
    except Exception:
        return 1
    print(artifact.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
