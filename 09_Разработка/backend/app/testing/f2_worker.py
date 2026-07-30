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


def _assert_result_has_no_secrets(
    value: object,
    environment: Mapping[str, str],
) -> None:
    secrets = tuple(
        environment.get(name, "")
        for name in (
            "TEST_DATABASE_URL",
            "WELDPASSPORT_F2_WORKING_DATABASE_URL",
            "WELDPASSPORT_TEST_DB_CONFIRM",
            "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN",
        )
        if environment.get(name)
    )

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                visit(key)
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and any(
            secret in item for secret in secrets
        ):
            raise F2Error(
                "TEST-DB-F2-EVIDENCE-UNSAFE",
                "TEST-DB-F2 result contains unsafe data",
            )

    visit(value)


class _BoundCommandExecutor(CommandExecutor):
    """Run Alembic in the bound process; pytest binds again in a fresh child."""

    def run(self, argv: tuple[str, ...]) -> int:
        if argv[:3] == (sys.executable, "-m", "alembic"):
            try:
                from alembic import command
                from alembic.config import Config

                backend_root = Path(__file__).resolve().parents[2]
                configuration = Config(str(backend_root / "alembic.ini"))
                configuration.set_main_option(
                    "script_location",
                    str(backend_root / "migrations"),
                )
                action, *arguments = argv[3:]
                if action == "upgrade" and arguments == ["head"]:
                    command.upgrade(configuration, "head")
                elif action == "heads" and not arguments:
                    command.heads(configuration)
                elif action == "current" and not arguments:
                    command.current(configuration)
                elif action == "check" and not arguments:
                    command.check(configuration)
                else:
                    return 1
                return 0
            except Exception:
                return 1
        safe_argv = argv
        if argv[:4] == (sys.executable, "-m", "pytest", "tests"):
            safe_argv = (
                *argv[:3],
                str(Path(__file__).resolve().parents[2] / "tests"),
                *argv[4:],
            )
        try:
            completed = subprocess.run(
                safe_argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return 1
        return completed.returncode


def _default_role_handlers(
    connection_provider: Callable[[], object],
) -> dict[str, Callable[[], Mapping[str, object]]]:
    state: dict[str, object] = {}

    def create_legacy_fixture(*, negative: bool) -> Mapping[str, object]:
        from sqlalchemy import MetaData, UniqueConstraint

        from app.workforce import models as _legacy_models  # noqa: F401
        from app.workforce.legacy_orm import (
            LegacyBase,
            bind_legacy_schema,
        )

        connection = connection_provider()
        bind_legacy_schema("test")
        connection.execute(text('CREATE SCHEMA "test"'))
        connection.commit()
        if not negative:
            LegacyBase.metadata.create_all(bind=connection)
            connection.commit()
            return {"fixture": "compatible"}

        incomplete = MetaData()
        for table in LegacyBase.metadata.sorted_tables:
            table.to_metadata(incomplete)
        removable = next(
            (
                (table, constraint)
                for table in incomplete.tables.values()
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            ),
            None,
        )
        if removable is None:
            raise F2Error(
                "TEST-DB-F2-RUNTIME-FAILED",
                "TEST-DB-F2 negative fixture could not be built",
            )
        removable_table, removable_constraint = removable
        removable_table.constraints.remove(removable_constraint)
        incomplete.create_all(bind=connection)
        connection.commit()
        return {"fixture": "one_required_constraint_omitted"}

    def runtime_start(*, expect_legacy: bool) -> Mapping[str, object]:
        from fastapi.testclient import TestClient

        from app.shared.application_factory import create_app
        from app.shared.runtime_profile import resolve_runtime_configuration

        application = create_app(
            resolve_runtime_configuration(
                runtime_profile=os.environ.get(
                    "WELDPASSPORT_RUNTIME_PROFILE"
                ),
                legacy_schema=os.environ.get("WELDPASSPORT_LEGACY_SCHEMA"),
            )
        )
        try:
            with TestClient(application) as client:
                response = client.get("/openapi.json")
                if response.status_code != 200:
                    raise F2Error(
                        "TEST-DB-F2-RUNTIME-FAILED",
                        "TEST-DB-F2 runtime probe failed",
                    )
                paths = set(response.json().get("paths", {}))
        except F2Error:
            raise
        except Exception:
            raise F2Error(
                "TEST-DB-F2-RUNTIME-FAILED",
                "TEST-DB-F2 runtime startup failed",
            ) from None

        workforce_present = "/api/v1/workers" in paths
        if workforce_present is not expect_legacy:
            raise F2Error(
                "TEST-DB-F2-RUNTIME-FAILED",
                "TEST-DB-F2 runtime route boundary failed",
            )
        return {
            "runtime_ready": True,
            "workforce_router_attached": workforce_present,
            "route_count": len(paths),
        }

    def compatible_smoke() -> Mapping[str, object]:
        from sqlalchemy.orm import Session

        from app.workforce.models import Rabotnik

        connection = connection_provider()
        with Session(bind=connection) as session:
            worker = Rabotnik(fio="TEST-DB-F2 smoke")
            session.add(worker)
            session.flush()
            identity = worker.id_rabotnika
            if session.get(Rabotnik, identity) is None:
                raise F2Error(
                    "TEST-DB-F2-RUNTIME-FAILED",
                    "TEST-DB-F2 legacy read/write smoke failed",
                )
            session.delete(worker)
            session.commit()
        return {"write": "verified", "read": "verified", "cleanup": "verified"}

    def negative_snapshot() -> str:
        from hashlib import sha256

        from sqlalchemy import func, select

        from app.workforce.legacy_orm import LegacyBase
        from app.workforce.legacy_preflight import (
            read_observed_legacy_contract,
        )

        connection = connection_provider()
        observed = read_observed_legacy_contract(connection, "test")
        counts = tuple(
            (
                table.name,
                int(
                    connection.execute(
                        select(func.count()).select_from(table)
                    ).scalar_one()
                ),
            )
            for table in LegacyBase.metadata.sorted_tables
        )
        material = f"{observed!r}\0{counts!r}".encode("utf-8")
        return sha256(material).hexdigest()

    def negative_before() -> Mapping[str, object]:
        digest = negative_snapshot()
        state["negative_snapshot"] = digest
        return {"catalog_data_digest": digest}

    def negative_runtime() -> Mapping[str, object]:
        from fastapi.testclient import TestClient

        from app.shared.application_factory import create_app
        from app.shared.runtime_profile import (
            RuntimeContractError,
            resolve_runtime_configuration,
        )

        application = create_app(
            resolve_runtime_configuration(
                runtime_profile=os.environ.get(
                    "WELDPASSPORT_RUNTIME_PROFILE"
                ),
                legacy_schema=os.environ.get("WELDPASSPORT_LEGACY_SCHEMA"),
            )
        )
        try:
            with TestClient(application):
                pass
        except RuntimeContractError as exc:
            if exc.code == "LEGACY-CONTRACT-MISMATCH":
                return {
                    "startup_rejected": True,
                    "error_code": exc.code,
                    "workforce_router_attached": bool(
                        application.state.workforce_router_attached
                    ),
                }
        except Exception:
            pass
        raise F2Error(
            "TEST-DB-F2-RUNTIME-FAILED",
            "TEST-DB-F2 negative runtime did not fail as required",
        )

    def negative_after() -> Mapping[str, object]:
        digest = negative_snapshot()
        if digest != state.get("negative_snapshot"):
            raise F2Error(
                "TEST-DB-F2-RUNTIME-FAILED",
                "TEST-DB-F2 negative runtime changed catalog or data",
            )
        return {"catalog_data_unchanged": True, "catalog_data_digest": digest}

    return {
        "canonical_runtime": lambda: runtime_start(expect_legacy=False),
        "compatible_fixture": lambda: create_legacy_fixture(negative=False),
        "compatible_runtime": lambda: runtime_start(expect_legacy=True),
        "compatible_smoke": compatible_smoke,
        "negative_fixture": lambda: create_legacy_fixture(negative=True),
        "negative_before": negative_before,
        "negative_runtime": negative_runtime,
        "negative_after": negative_after,
    }


def _default_dependencies() -> WorkerDependencies:
    from contextlib import contextmanager

    from app.shared.database_bootstrap import bind_database_target

    connection_state: dict[str, object] = {}

    def require_connection() -> object:
        connection = connection_state.get("connection")
        if connection is None:
            raise F2Error(
                "TEST-DB-F2-RUNTIME-FAILED",
                "TEST-DB-F2 live connection is unavailable",
            )
        return connection

    @contextmanager
    def live_gate(authorization: TestDatabaseAuthorization):
        from app.shared.db import engine
        from app.shared.test_database_ownership import (
            verify_test_database_ownership,
        )

        with engine.connect() as connection:
            verify_test_database_ownership(connection, authorization)
            connection_state["connection"] = connection
            try:
                yield connection
            finally:
                connection_state.pop("connection", None)

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
            handlers=_default_role_handlers(require_connection),
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
    if dependencies is None:
        os.chdir(artifact_path.parent)
        deps = _default_dependencies()
    else:
        deps = dependencies
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

    _assert_result_has_no_secrets(role_result, environment)
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
