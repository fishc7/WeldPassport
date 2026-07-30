"""Immutable TEST-DB-F2 coordinator/worker protocol values."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping


F2_PROTOCOL_VERSION = "test-db-f2/v1"
F2_OPERATOR_AUTHORIZATION = "I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL"


class F2Role(StrEnum):
    CANONICAL = "canonical"
    LEGACY_COMPATIBLE = "legacy_compatible"
    LEGACY_NEGATIVE = "legacy_negative"


F2_ROLE_ORDER = (
    F2Role.CANONICAL,
    F2Role.LEGACY_COMPATIBLE,
    F2Role.LEGACY_NEGATIVE,
)


class F2MachineStatus(StrEnum):
    PRECHECK_FAILED = "TEST_DB_F2_PRECHECK_FAILED"
    REHEARSAL_FAILED = "TEST_DB_F2_REHEARSAL_FAILED"
    EVIDENCE_FAILED = "TEST_DB_F2_EVIDENCE_FAILED"
    REHEARSAL_VERIFIED = "TEST_DB_F2_REHEARSAL_VERIFIED"


class F2Error(Exception):
    """Safe TEST-DB-F2 failure that never embeds caller-supplied values."""

    def __init__(self, code: str, safe_detail: str) -> None:
        self.code = code
        self.safe_detail = safe_detail
        super().__init__(f"{code}: {safe_detail}")


@dataclass(frozen=True)
class F2TargetInput:
    role: F2Role
    test_database_url: str = field(repr=False)
    confirmed_name: str = field(repr=False)
    ownership_token: str = field(repr=False)


@dataclass(frozen=True)
class F2ParentInputs:
    working_database_url: str = field(repr=False)
    evidence_root: Path
    authorization: str = field(repr=False)
    destructive_opt_in: str = field(repr=False)
    targets: tuple[F2TargetInput, ...]


@dataclass(frozen=True)
class F2WorkerRequest:
    protocol_version: str
    run_id: str
    source_sha: str
    role: F2Role
    artifact_name: str


_ROLE_PREFIXES = {
    F2Role.CANONICAL: "CANONICAL",
    F2Role.LEGACY_COMPATIBLE: "LEGACY_COMPATIBLE",
    F2Role.LEGACY_NEGATIVE: "LEGACY_NEGATIVE",
}
_COMMON_NAMES = {
    "WELDPASSPORT_F2_WORKING_DATABASE_URL",
    "WELDPASSPORT_F2_EVIDENCE_DIR",
    "WELDPASSPORT_F2_OPERATOR_AUTHORIZATION",
    "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS",
}
_ROLE_SUFFIXES = (
    "TEST_DATABASE_URL",
    "DATABASE_CONFIRM",
    "OWNERSHIP_TOKEN",
)
_ROLE_NAMES = {
    f"WELDPASSPORT_F2_{prefix}_{suffix}"
    for prefix in _ROLE_PREFIXES.values()
    for suffix in _ROLE_SUFFIXES
}
_ALLOWED_NAMES = _COMMON_NAMES | _ROLE_NAMES
_AUTHORIZATION_ERROR = (
    "TEST-DB-F2-AUTHORIZATION-MISSING",
    "TEST-DB-F2 parent authorization is incomplete",
)


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise F2Error(*_AUTHORIZATION_ERROR)
    return value


def load_parent_inputs(environment: Mapping[str, str]) -> F2ParentInputs:
    """Parse the exact transient parent environment or fail closed."""

    unknown_f2_names = {
        name
        for name in environment
        if name.startswith("WELDPASSPORT_F2_") and name not in _ALLOWED_NAMES
    }
    if unknown_f2_names:
        raise F2Error(*_AUTHORIZATION_ERROR)

    authorization = _required(
        environment,
        "WELDPASSPORT_F2_OPERATOR_AUTHORIZATION",
    )
    destructive_opt_in = _required(
        environment,
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS",
    )
    if (
        authorization != F2_OPERATOR_AUTHORIZATION
        or destructive_opt_in != "YES"
    ):
        raise F2Error(*_AUTHORIZATION_ERROR)

    targets = tuple(
        F2TargetInput(
            role=role,
            test_database_url=_required(
                environment,
                f"WELDPASSPORT_F2_{prefix}_TEST_DATABASE_URL",
            ),
            confirmed_name=_required(
                environment,
                f"WELDPASSPORT_F2_{prefix}_DATABASE_CONFIRM",
            ),
            ownership_token=_required(
                environment,
                f"WELDPASSPORT_F2_{prefix}_OWNERSHIP_TOKEN",
            ),
        )
        for role, prefix in _ROLE_PREFIXES.items()
    )
    return F2ParentInputs(
        working_database_url=_required(
            environment,
            "WELDPASSPORT_F2_WORKING_DATABASE_URL",
        ),
        evidence_root=Path(
            _required(environment, "WELDPASSPORT_F2_EVIDENCE_DIR")
        ),
        authorization=authorization,
        destructive_opt_in=destructive_opt_in,
        targets=targets,
    )
