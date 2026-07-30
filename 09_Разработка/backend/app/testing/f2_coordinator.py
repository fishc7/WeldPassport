"""Fixed-order fail-closed TEST-DB-F2 coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import sys
from typing import Callable, Mapping
from uuid import UUID, uuid4

from app.testing.f2_contract import (
    F2MachineStatus,
    F2_PROTOCOL_VERSION,
    F2WorkerRequest,
    load_parent_inputs,
)
from app.testing.f2_evidence import (
    PublishedArtifact,
    publish_artifact,
    verify_artifact,
)
from app.testing.f2_preflight import (
    F2OfflinePlan,
    SubprocessGitInspector,
    build_offline_plan,
)
from app.testing.f2_process import (
    ProcessExecutor,
    build_worker_argv,
    build_worker_environment,
)


_ROLE_ARTIFACTS = (
    "10_canonical.json",
    "20_legacy_compatible.json",
    "30_legacy_negative.json",
)
_ROLE_TIMEOUT_SECONDS = 3600


@dataclass(frozen=True)
class F2CoordinatorDependencies:
    preflight: Callable[[object], F2OfflinePlan]
    executor: ProcessExecutor
    clock: Callable[[], str]
    publisher: Callable[
        [Path, Mapping[str, object]],
        PublishedArtifact,
    ]


@dataclass(frozen=True)
class F2RunResult:
    run_id: UUID | None
    source_sha: str | None
    status: F2MachineStatus
    manifest_digest: str | None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _default_dependencies() -> F2CoordinatorDependencies:
    repository_root = Path(__file__).resolve().parents[4]
    inspector = SubprocessGitInspector(repository_root)
    return F2CoordinatorDependencies(
        preflight=lambda inputs: build_offline_plan(
            inputs, inspector, uuid4
        ),
        executor=ProcessExecutor(),
        clock=_utc_now,
        publisher=publish_artifact,
    )


def _result(
    plan: F2OfflinePlan | None,
    status: F2MachineStatus,
    manifest_digest: str | None = None,
) -> F2RunResult:
    return F2RunResult(
        None if plan is None else plan.run_id,
        None if plan is None else plan.source_sha,
        status,
        manifest_digest,
    )


def _failure(
    plan: F2OfflinePlan,
    status: F2MachineStatus,
    previous_digest: str | None,
    dependencies: F2CoordinatorDependencies,
) -> F2RunResult:
    try:
        dependencies.publisher(
            plan.namespace / "99_failure.json",
            {
                "protocol_version": F2_PROTOCOL_VERSION,
                "run_id": str(plan.run_id),
                "source_sha": plan.source_sha,
                "previous_digest": previous_digest,
                "status": status.value,
                "finished_at": dependencies.clock(),
            },
        )
    except Exception:
        return _result(plan, F2MachineStatus.EVIDENCE_FAILED)
    return _result(plan, status)


def run_f2(
    environment: Mapping[str, str],
    dependencies: F2CoordinatorDependencies | None = None,
) -> F2RunResult:
    deps = _default_dependencies() if dependencies is None else dependencies
    plan: F2OfflinePlan | None = None
    try:
        inputs = load_parent_inputs(environment)
        plan = deps.preflight(inputs)
    except Exception:
        return _result(None, F2MachineStatus.PRECHECK_FAILED)

    try:
        preflight_artifact = deps.publisher(
            plan.namespace / "00_preflight.json",
            {
                "protocol_version": F2_PROTOCOL_VERSION,
                "run_id": str(plan.run_id),
                "source_sha": plan.source_sha,
                "previous_digest": None,
                "role": "preflight",
                "status": "verified",
                "verified_at": deps.clock(),
                "targets": [
                    {
                        "role": target.role.value,
                        "identity_digest": target.identity_digest,
                    }
                    for target in plan.targets
                ],
            },
        )
    except Exception:
        return _result(plan, F2MachineStatus.EVIDENCE_FAILED)

    previous_digest = preflight_artifact.digest
    artifacts: list[PublishedArtifact] = [preflight_artifact]
    for target, artifact_name in zip(
        plan.targets,
        _ROLE_ARTIFACTS,
        strict=True,
    ):
        artifact_path = plan.namespace / artifact_name
        request = F2WorkerRequest(
            protocol_version=F2_PROTOCOL_VERSION,
            run_id=str(plan.run_id),
            source_sha=plan.source_sha,
            role=target.role,
            artifact_name=artifact_name,
        )
        child_environment = build_worker_environment(
            plan,
            target,
            artifact_path,
            environment,
        )
        child_environment["WELDPASSPORT_F2_PREVIOUS_DIGEST"] = previous_digest
        argv = build_worker_argv(sys.executable, request)
        try:
            process = deps.executor.run(
                argv,
                child_environment,
                _ROLE_TIMEOUT_SECONDS,
            )
        except Exception:
            return _failure(
                plan,
                F2MachineStatus.REHEARSAL_FAILED,
                previous_digest,
                deps,
            )
        if process.timed_out or process.exit_code != 0:
            return _failure(
                plan,
                F2MachineStatus.REHEARSAL_FAILED,
                previous_digest,
                deps,
            )
        try:
            artifact = verify_artifact(
                artifact_path,
                artifact_name,
                plan.run_id,
                plan.source_sha,
                previous_digest,
            )
        except Exception:
            return _failure(
                plan,
                F2MachineStatus.REHEARSAL_FAILED,
                previous_digest,
                deps,
            )
        artifacts.append(artifact)
        previous_digest = artifact.digest

    try:
        manifest = deps.publisher(
            plan.namespace / "90_manifest.json",
            {
                "protocol_version": F2_PROTOCOL_VERSION,
                "run_id": str(plan.run_id),
                "source_sha": plan.source_sha,
                "previous_digest": previous_digest,
                "status": F2MachineStatus.REHEARSAL_VERIFIED.value,
                "finished_at": deps.clock(),
                "artifacts": [
                    {"name": artifact.name, "digest": artifact.digest}
                    for artifact in artifacts
                ],
            },
        )
    except Exception:
        return _result(plan, F2MachineStatus.EVIDENCE_FAILED)
    return _result(
        plan,
        F2MachineStatus.REHEARSAL_VERIFIED,
        manifest.digest,
    )
