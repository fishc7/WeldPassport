"""Offline-only source and target preflight for TEST-DB-F2."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import subprocess
from typing import Callable, Protocol
from uuid import UUID

from app.shared.database_target import (
    DatabaseIdentity,
    TestDatabaseAuthorization,
    authorize_test_database,
)
from app.testing.f2_contract import (
    F2Error,
    F2ParentInputs,
    F2_ROLE_ORDER,
    F2Role,
)
from app.testing.f2_evidence import reserve_run_namespace


_SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class GitState:
    source_sha: str
    tracked_clean: bool


class GitInspector(Protocol):
    def read_state(self) -> GitState: ...


@dataclass(frozen=True)
class SubprocessGitInspector:
    repository_root: Path

    def read_state(self) -> GitState:
        try:
            head = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=self.repository_root,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
            )
            status = subprocess.run(
                ("git", "status", "--porcelain", "--untracked-files=no"),
                cwd=self.repository_root,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            raise _source_error() from None
        if head.returncode != 0 or status.returncode != 0:
            raise _source_error()
        return GitState(
            source_sha=head.stdout.strip(),
            tracked_clean=not status.stdout.strip(),
        )


@dataclass(frozen=True)
class F2AuthorizedTarget:
    role: F2Role
    authorization: TestDatabaseAuthorization
    identity_digest: str


@dataclass(frozen=True)
class F2OfflinePlan:
    run_id: UUID
    source_sha: str
    namespace: Path
    targets: tuple[F2AuthorizedTarget, ...]


def _source_error() -> F2Error:
    return F2Error(
        "TEST-DB-F2-SOURCE-UNSAFE",
        "TEST-DB-F2 source state is unsafe",
    )


def _identity_digest(identity: DatabaseIdentity) -> str:
    canonical = "\0".join(
        (
            identity.drivername,
            identity.host,
            str(identity.port),
            identity.database,
        )
    ).encode("utf-8")
    return sha256(
        b"weldpassport:test-db-f2:identity:v1\0" + canonical
    ).hexdigest()


def authorize_offline_targets(
    inputs: F2ParentInputs,
) -> tuple[F2AuthorizedTarget, ...]:
    roles = tuple(target.role for target in inputs.targets)
    if roles != F2_ROLE_ORDER:
        raise F2Error(
            "TEST-DB-F2-AUTHORIZATION-MISSING",
            "TEST-DB-F2 requires one exact bundle for every role",
        )

    authorized: list[F2AuthorizedTarget] = []
    identities: set[DatabaseIdentity] = set()
    for target in inputs.targets:
        authorization = authorize_test_database(
            test_database_url=target.test_database_url,
            working_database_url=inputs.working_database_url,
            destructive_opt_in=inputs.destructive_opt_in,
            confirmed_database_name=target.confirmed_name,
            ownership_token=target.ownership_token,
        )
        identity = authorization.target.identity
        if identity in identities:
            raise F2Error(
                "TEST-DB-F2-TARGET-COLLISION",
                "TEST-DB-F2 target identities collide",
            )
        identities.add(identity)
        authorized.append(
            F2AuthorizedTarget(
                role=target.role,
                authorization=authorization,
                identity_digest=_identity_digest(identity),
            )
        )
    return tuple(authorized)


def build_offline_plan(
    inputs: F2ParentInputs,
    git_inspector: GitInspector,
    uuid_factory: Callable[[], UUID],
) -> F2OfflinePlan:
    state = git_inspector.read_state()
    if not state.tracked_clean or _SOURCE_SHA.fullmatch(state.source_sha) is None:
        raise _source_error()

    authorized = authorize_offline_targets(inputs)
    run_id = uuid_factory()
    namespace = reserve_run_namespace(inputs.evidence_root, run_id)
    return F2OfflinePlan(
        run_id=run_id,
        source_sha=state.source_sha,
        namespace=namespace,
        targets=authorized,
    )
