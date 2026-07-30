"""Offline-only operator preflight for TEST-DB-F2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Mapping, Protocol
from uuid import UUID, uuid4

from app.testing.f2_contract import (
    F2Error,
    F2ParentInputs,
    F2_OPERATOR_AUTHORIZATION,
    load_parent_inputs,
)
from app.testing.f2_evidence import (
    PublishedArtifact,
    publish_artifact,
    reserve_named_namespace,
    validate_external_evidence_root,
)
from app.testing.f2_preflight import authorize_offline_targets


F2_OPERATOR_PREFLIGHT_PROTOCOL = "test-db-f2-operator-preflight/v1"
F2_OPERATOR_PREFLIGHT_AUTHORIZATION = (
    "I_AUTHORIZE_TEST_DB_F2_OPERATOR_PREFLIGHT"
)
F2_OPERATOR_PREFLIGHT_BRANCH = "codex/b04b-maintenance-readiness-review"
F2_OPERATOR_PREFLIGHT_PREREQUISITES = (
    "20c7ea7",
    "03d4c59",
    "32ffec8",
)
_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUNTIME_ENVIRONMENT = (
    "SystemRoot",
    "WINDIR",
    "SystemDrive",
    "TEMP",
    "TMP",
    "PATH",
)


class F2OperatorPreflightStatus(StrEnum):
    READY = "TEST_DB_F2_OPERATOR_PREFLIGHT_READY"
    FAILED = "TEST_DB_F2_OPERATOR_PREFLIGHT_FAILED"
    EVIDENCE_FAILED = "TEST_DB_F2_OPERATOR_PREFLIGHT_EVIDENCE_FAILED"


@dataclass(frozen=True)
class OperatorSourceState:
    source_sha: str
    branch: str
    tracked_clean: bool
    prerequisites: tuple[tuple[str, bool], ...]


class OperatorSourceInspector(Protocol):
    def read_state(
        self,
        prerequisites: tuple[str, ...],
    ) -> OperatorSourceState: ...


def _authorization_error() -> F2Error:
    return F2Error(
        "TEST-DB-F2-AUTHORIZATION-MISSING",
        "TEST-DB-F2 operator preflight authorization is incomplete",
    )


def _source_error() -> F2Error:
    return F2Error(
        "TEST-DB-F2-SOURCE-UNSAFE",
        "TEST-DB-F2 operator preflight source is unsafe",
    )


def load_operator_preflight_inputs(
    environment: Mapping[str, str],
) -> F2ParentInputs:
    if (
        environment.get("WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION")
        != F2_OPERATOR_PREFLIGHT_AUTHORIZATION
        or "WELDPASSPORT_F2_OPERATOR_AUTHORIZATION" in environment
    ):
        raise _authorization_error()

    parser_environment = dict(environment)
    parser_environment.pop("WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION")
    parser_environment["WELDPASSPORT_F2_OPERATOR_AUTHORIZATION"] = (
        F2_OPERATOR_AUTHORIZATION
    )
    return load_parent_inputs(parser_environment)


def validate_operator_source(
    state: OperatorSourceState,
    prerequisites: tuple[str, ...],
    python_version: tuple[int, int, int],
) -> None:
    if (
        state.branch != F2_OPERATOR_PREFLIGHT_BRANCH
        or not state.tracked_clean
        or _SOURCE_SHA.fullmatch(state.source_sha) is None
        or tuple(sha for sha, _present in state.prerequisites)
        != prerequisites
        or not all(present for _sha, present in state.prerequisites)
        or python_version < (3, 12, 0)
    ):
        raise _source_error()


@dataclass(frozen=True)
class SubprocessOperatorSourceInspector:
    repository_root: Path
    parent_environment: Mapping[str, str]

    def _run(self, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        safe_environment = {
            name: self.parent_environment[name]
            for name in _RUNTIME_ENVIRONMENT
            if name in self.parent_environment
        }
        try:
            return subprocess.run(
                argv,
                cwd=self.repository_root,
                env=safe_environment,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            raise _source_error() from None

    def read_state(
        self,
        prerequisites: tuple[str, ...],
    ) -> OperatorSourceState:
        head = self._run(("git", "rev-parse", "HEAD"))
        status = self._run(
            ("git", "status", "--porcelain", "--untracked-files=no")
        )
        branch = self._run(("git", "branch", "--show-current"))
        if any(result.returncode != 0 for result in (head, status, branch)):
            raise _source_error()

        ancestry: list[tuple[str, bool]] = []
        for prerequisite in prerequisites:
            result = self._run(
                (
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    prerequisite,
                    "HEAD",
                )
            )
            if result.returncode not in (0, 1):
                raise _source_error()
            ancestry.append((prerequisite, result.returncode == 0))

        return OperatorSourceState(
            source_sha=head.stdout.strip(),
            branch=branch.stdout.strip(),
            tracked_clean=not status.stdout.strip(),
            prerequisites=tuple(ancestry),
        )


@dataclass(frozen=True)
class OperatorPreflightDependencies:
    source_inspector: OperatorSourceInspector
    uuid_factory: Callable[[], UUID]
    clock: Callable[[], str]
    publisher: Callable[
        [Path, Mapping[str, object]],
        PublishedArtifact,
    ]


@dataclass(frozen=True)
class OperatorPreflightResult:
    preflight_id: UUID | None
    source_sha: str | None
    status: F2OperatorPreflightStatus
    artifact_digest: str | None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _default_dependencies(
    repository_root: Path,
    environment: Mapping[str, str],
) -> OperatorPreflightDependencies:
    return OperatorPreflightDependencies(
        source_inspector=SubprocessOperatorSourceInspector(
            repository_root,
            environment,
        ),
        uuid_factory=uuid4,
        clock=_utc_now,
        publisher=publish_artifact,
    )


def _result(
    status: F2OperatorPreflightStatus,
    *,
    preflight_id: UUID | None = None,
    source_sha: str | None = None,
    artifact_digest: str | None = None,
) -> OperatorPreflightResult:
    return OperatorPreflightResult(
        preflight_id=preflight_id,
        source_sha=source_sha,
        status=status,
        artifact_digest=artifact_digest,
    )


def run_operator_preflight(
    environment: Mapping[str, str],
    dependencies: OperatorPreflightDependencies | None = None,
) -> OperatorPreflightResult:
    repository_root = Path(__file__).resolve().parents[4]
    deps = (
        _default_dependencies(repository_root, environment)
        if dependencies is None
        else dependencies
    )
    try:
        inputs = load_operator_preflight_inputs(environment)
        source = deps.source_inspector.read_state(
            F2_OPERATOR_PREFLIGHT_PREREQUISITES
        )
        python_version = (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        validate_operator_source(
            source,
            F2_OPERATOR_PREFLIGHT_PREREQUISITES,
            python_version,
        )
        targets = authorize_offline_targets(inputs)
        evidence_root = validate_external_evidence_root(
            inputs.evidence_root,
            repository_root,
        )
    except Exception:
        return _result(F2OperatorPreflightStatus.FAILED)

    preflight_id: UUID | None = None
    try:
        preflight_id = deps.uuid_factory()
        namespace = reserve_named_namespace(
            evidence_root,
            f"operator-preflight-{preflight_id}",
        )
        artifact = deps.publisher(
            namespace / "00_operator_preflight.json",
            {
                "protocol_version": F2_OPERATOR_PREFLIGHT_PROTOCOL,
                "preflight_id": str(preflight_id),
                "source_sha": source.source_sha,
                "branch": source.branch,
                "verified_at": deps.clock(),
                "status": F2OperatorPreflightStatus.READY.value,
                "python_version": list(python_version),
                "prerequisites": [
                    {"commit": sha, "ancestor": present}
                    for sha, present in source.prerequisites
                ],
                "targets": [
                    {
                        "role": target.role.value,
                        "identity_digest": target.identity_digest,
                    }
                    for target in targets
                ],
                "checks": {
                    "source_clean": True,
                    "branch_exact": True,
                    "prerequisites_present": True,
                    "python_supported": True,
                    "targets_authorized_offline": True,
                    "target_identities_unique": True,
                    "evidence_root_external": True,
                },
            },
        )
    except Exception:
        return _result(
            F2OperatorPreflightStatus.EVIDENCE_FAILED,
            preflight_id=preflight_id,
            source_sha=source.source_sha,
        )
    return _result(
        F2OperatorPreflightStatus.READY,
        preflight_id=preflight_id,
        source_sha=source.source_sha,
        artifact_digest=artifact.digest,
    )
