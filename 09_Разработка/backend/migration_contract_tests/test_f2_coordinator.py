from pathlib import Path
from uuid import UUID

from app.shared.database_target import authorize_test_database
from app.testing.f2_contract import F2MachineStatus, F2Role
from app.testing.f2_coordinator import (
    F2CoordinatorDependencies,
    run_f2,
)
from app.testing.f2_evidence import publish_artifact
from app.testing.f2_preflight import F2AuthorizedTarget, F2OfflinePlan
from app.testing.f2_process import ProcessResult


RUN_ID = UUID("12345678-1234-4234-8234-123456789abc")
SOURCE_SHA = "a" * 40


def _environment(root: Path) -> dict[str, str]:
    result = {
        "WELDPASSPORT_F2_WORKING_DATABASE_URL": (
            "postgresql+psycopg://worker:secret@localhost/weldpassport_dev"
        ),
        "WELDPASSPORT_F2_EVIDENCE_DIR": str(root),
        "WELDPASSPORT_F2_OPERATOR_AUTHORIZATION": (
            "I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL"
        ),
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
    }
    for role in F2Role:
        prefix = role.value.upper()
        result[f"WELDPASSPORT_F2_{prefix}_TEST_DATABASE_URL"] = (
            "postgresql+psycopg://worker:secret@localhost/"
            f"test_{role.value}"
        )
        result[f"WELDPASSPORT_F2_{prefix}_DATABASE_CONFIRM"] = (
            f"test_{role.value}"
        )
        result[f"WELDPASSPORT_F2_{prefix}_OWNERSHIP_TOKEN"] = (
            f"token-{role.value}"
        )
    return result


def _plan(root: Path) -> F2OfflinePlan:
    targets = []
    for role in F2Role:
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
        targets.append(F2AuthorizedTarget(role, authorization, "d" * 64))
    namespace = root / str(RUN_ID)
    namespace.mkdir()
    return F2OfflinePlan(RUN_ID, SOURCE_SHA, namespace, tuple(targets))


class SuccessfulExecutor:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def run(
        self,
        argv: tuple[str, ...],
        environment: dict[str, str],
        timeout_seconds: int,
    ) -> ProcessResult:
        role = environment["WELDPASSPORT_F2_ROLE"]
        self.roles.append(role)
        publish_artifact(
            Path(environment["WELDPASSPORT_F2_ARTIFACT_PATH"]),
            {
                "protocol_version": environment[
                    "WELDPASSPORT_F2_PROTOCOL_VERSION"
                ],
                "run_id": environment["WELDPASSPORT_F2_RUN_ID"],
                "source_sha": environment["WELDPASSPORT_F2_SOURCE_SHA"],
                "previous_digest": environment[
                    "WELDPASSPORT_F2_PREVIOUS_DIGEST"
                ],
                "role": role,
                "status": "verified",
            },
        )
        return ProcessResult(0, "", "", False)


def test_f2_coordinator_001_success_is_fixed_order_and_manifest_last(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    executor = SuccessfulExecutor()
    dependencies = F2CoordinatorDependencies(
        preflight=lambda _inputs: plan,
        executor=executor,
        clock=lambda: "2026-07-30T12:00:00Z",
        publisher=publish_artifact,
    )

    result = run_f2(_environment(tmp_path), dependencies)

    assert result.status is F2MachineStatus.REHEARSAL_VERIFIED
    assert executor.roles == [role.value for role in F2Role]
    assert [path.name for path in plan.namespace.iterdir()] == [
        "00_preflight.json",
        "10_canonical.json",
        "20_legacy_compatible.json",
        "30_legacy_negative.json",
        "90_manifest.json",
    ]
    assert result.manifest_digest is not None
    assert not (plan.namespace / "TEST_DB_F2_ACCEPTED").exists()


class FailingExecutor(SuccessfulExecutor):
    def run(
        self,
        argv: tuple[str, ...],
        environment: dict[str, str],
        timeout_seconds: int,
    ) -> ProcessResult:
        self.roles.append(environment["WELDPASSPORT_F2_ROLE"])
        return ProcessResult(9, "safe", "safe", False)


def test_f2_coordinator_002_failure_short_circuits_without_retry(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    executor = FailingExecutor()

    result = run_f2(
        _environment(tmp_path),
        F2CoordinatorDependencies(
            preflight=lambda _inputs: plan,
            executor=executor,
            clock=lambda: "2026-07-30T12:00:00Z",
            publisher=publish_artifact,
        ),
    )

    assert result.status is F2MachineStatus.REHEARSAL_FAILED
    assert executor.roles == ["canonical"]
    assert (plan.namespace / "99_failure.json").exists()
    assert not (plan.namespace / "90_manifest.json").exists()


def test_f2_coordinator_003_evidence_failure_has_precedence(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    def failed_publisher(path: Path, payload: dict[str, object]) -> object:
        raise OSError("unsafe raw failure")

    result = run_f2(
        _environment(tmp_path),
        F2CoordinatorDependencies(
            preflight=lambda _inputs: plan,
            executor=SuccessfulExecutor(),
            clock=lambda: "2026-07-30T12:00:00Z",
            publisher=failed_publisher,
        ),
    )

    assert result.status is F2MachineStatus.EVIDENCE_FAILED
    assert result.manifest_digest is None
