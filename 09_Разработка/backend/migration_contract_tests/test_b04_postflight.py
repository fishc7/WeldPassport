from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from migrations.b04.adoption_state import (
    AdoptionState,
    PreparedEvidence,
    canonical_report_bytes,
)
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.postflight import (
    PUBLIC_MARKER_QUERY,
    PUBLIC_VERSION_QUERY,
    TEST_MARKER_QUERY,
    report_digest,
    run_postflight,
)
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
    SCHEMA_SOURCE_COMMIT,
)


SHA256_A = "a" * 64
SHA256_B = "b" * 64
SHA256_C = "c" * 64
SHA256_D = "d" * 64
SHA256_E = "e" * 64
ACCEPTED_FINGERPRINT_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "baselines"
    / "canonical_baseline_v1"
    / "postgresql-18"
    / "expected-fingerprint.json"
)
ACCEPTED_FINGERPRINT = json.loads(ACCEPTED_FINGERPRINT_PATH.read_bytes())
ACCEPTED_FINGERPRINT_DIGEST = hashlib.sha256(
    ACCEPTED_FINGERPRINT_PATH.read_bytes()
).hexdigest()
POSTFLIGHT_RESULT_KEYS = (
    "postflight_public_marker_verified",
    "postflight_historical_marker_absent",
    "postflight_fingerprint_verified",
    "postflight_alembic_heads_verified",
    "postflight_alembic_current_verified",
    "postflight_alembic_history_verified",
    "postflight_alembic_check_verified",
    "postflight_read_only_smoke_verified",
    "postflight_verified",
)


@dataclass(frozen=True)
class _Result:
    scalar: object

    def scalar_one(self) -> object:
        return self.scalar


class _Connection:
    def __init__(
        self,
        *,
        public_marker: object = "public.alembic_version",
        public_version: object = BASELINE_REVISION,
        historical_marker: object = None,
    ) -> None:
        self.public_marker = public_marker
        self.public_version = public_version
        self.historical_marker = historical_marker
        self.operations: list[str] = []

    def execute(self, statement: Any, _parameters: Any = None) -> _Result:
        operation = str(statement)
        self.operations.append(operation)
        if operation == PUBLIC_MARKER_QUERY:
            return _Result(self.public_marker)
        if operation == PUBLIC_VERSION_QUERY:
            return _Result(self.public_version)
        if operation == TEST_MARKER_QUERY:
            return _Result(self.historical_marker)
        raise AssertionError(f"unexpected postflight SQL: {operation}")


class _ConnectionContext:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.entered = False
        self.exited = False

    def __enter__(self) -> _Connection:
        self.entered = True
        return self.connection

    def __exit__(self, *_: object) -> None:
        self.exited = True


def _prepared() -> PreparedEvidence:
    return PreparedEvidence(
        adoption_id="b04b-postflight-001",
        database_identity=DatabaseIdentity(
            database="WeldPassport",
            host="db.internal.example",
            port=5432,
            username="maintenance_operator",
        ),
        source_sha=SCHEMA_SOURCE_COMMIT,
        old_marker=HISTORICAL_HEAD,
        new_marker=BASELINE_REVISION,
        backup_sha256=SHA256_A,
        manifest_sha256=SHA256_B,
        fingerprint_sha256=SHA256_C,
        allowlist_sha256=SHA256_D,
        seed_sha256=SHA256_E,
        database_identity_sha256="f" * 64,
        server_version_num=180003,
        prepared_at_utc="2026-07-29T10:00:00Z",
        verification_results=(
            ("active_evidence_verified", True),
            ("backup_restore_verified", True),
            ("fingerprint_verified", True),
            ("marker_verified", True),
            ("repository_digests_verified", True),
            ("sessions_verified", True),
        ),
    )


def _fingerprint(_: _Connection) -> dict[str, object]:
    return ACCEPTED_FINGERPRINT


def test_b04b_postflight_001_success_stays_unverified_until_owner_signing(
    tmp_path: Path,
) -> None:
    """Self-accepting a clean machine postflight would bypass the Task 7 owner gate."""

    connection = _Connection()
    context = _ConnectionContext(connection)
    commands: list[str] = []
    smoke_connections: list[_Connection] = []
    fingerprint = _fingerprint(connection)
    evidence = replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST)

    report = run_postflight(
        lambda: context,
        evidence,
        fingerprint_extractor=_fingerprint,
        alembic_runner=lambda command: commands.append(command) is None,
        read_only_smoke=lambda observed: smoke_connections.append(observed) is None,
        completed_at_utc="2026-07-29T10:05:00Z",
        report_directory=tmp_path,
    )

    assert connection.operations == [
        PUBLIC_MARKER_QUERY,
        PUBLIC_VERSION_QUERY,
        TEST_MARKER_QUERY,
    ]
    assert context.entered is True
    assert context.exited is True
    assert commands == ["heads", "current", "history", "check"]
    assert smoke_connections == [connection]
    assert report.attempt_status is AdoptionState.COMMITTED_UNVERIFIED
    assert report.completed_at_utc == "2026-07-29T10:05:00Z"
    assert tuple(report.verification_results[-len(POSTFLIGHT_RESULT_KEYS) :]) == tuple(
        (key, True) for key in POSTFLIGHT_RESULT_KEYS
    )
    assert report.database_identity == DatabaseIdentity(
        database="WeldPassport",
        host="[redacted]",
        port=5432,
        username="[redacted]",
    )
    assert (tmp_path / "b04b-postflight-001.json").read_bytes() == canonical_report_bytes(
        report
    )
    assert report_digest(report) == hashlib.sha256(canonical_report_bytes(report)).hexdigest()
    assert "db.internal.example" not in canonical_report_bytes(report).decode("utf-8")
    assert "maintenance_operator" not in canonical_report_bytes(report).decode("utf-8")
    assert fingerprint == ACCEPTED_FINGERPRINT


def test_b04b_postflight_002_failed_postcommit_marker_check_never_retries_transfer(
    tmp_path: Path,
) -> None:
    """A post-commit marker mismatch must preserve the committed-unverified stop state."""

    connection = _Connection(public_version="wrong_revision")
    commands: list[str] = []

    report = run_postflight(
        lambda: _ConnectionContext(connection),
        _prepared(),
        fingerprint_extractor=_fingerprint,
        alembic_runner=lambda command: commands.append(command) is None,
        read_only_smoke=lambda _: True,
        completed_at_utc="2026-07-29T10:05:00Z",
        report_directory=tmp_path,
    )

    assert report.attempt_status is AdoptionState.COMMITTED_UNVERIFIED
    assert report.completed_at_utc == "2026-07-29T10:05:00Z"
    assert report.verification_results[-1] == ("postflight_verified", False)
    assert connection.operations == [PUBLIC_MARKER_QUERY, PUBLIC_VERSION_QUERY]
    assert commands == []
    assert not any(
        operation.startswith(("CREATE", "INSERT", "DROP", "ALTER"))
        for operation in connection.operations
    )
    assert (tmp_path / "b04b-postflight-001.json").read_bytes() == canonical_report_bytes(
        report
    )


def test_b04b_postflight_003_failed_alembic_check_stops_before_read_only_smoke() -> None:
    """Continuing to later checks after an Alembic failure would hide an incomplete postflight."""

    connection = _Connection()
    commands: list[str] = []
    smoke_calls: list[_Connection] = []
    evidence = replace(
        _prepared(),
        fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST,
    )

    report = run_postflight(
        lambda: _ConnectionContext(connection),
        evidence,
        fingerprint_extractor=_fingerprint,
        alembic_runner=lambda command: (
            commands.append(command) is None and command != "history"
        ),
        read_only_smoke=lambda observed: smoke_calls.append(observed) is None,
        completed_at_utc="2026-07-29T10:05:00Z",
    )

    assert report.attempt_status is AdoptionState.COMMITTED_UNVERIFIED
    assert report.verification_results[-1] == ("postflight_verified", False)
    assert commands == ["heads", "current", "history"]
    assert smoke_calls == []


def test_b04b_postflight_004_external_report_is_append_only(
    tmp_path: Path,
) -> None:
    """Replacing an operator evidence record would destroy the audit trail."""

    evidence = replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST)
    kwargs = {
        "fingerprint_extractor": _fingerprint,
        "alembic_runner": lambda _: True,
        "read_only_smoke": lambda _: True,
        "completed_at_utc": "2026-07-29T10:05:00Z",
        "report_directory": tmp_path,
    }

    run_postflight(lambda: _ConnectionContext(_Connection()), evidence, **kwargs)
    original = (tmp_path / "b04b-postflight-001.json").read_bytes()

    with pytest.raises(FileExistsError):
        run_postflight(lambda: _ConnectionContext(_Connection()), evidence, **kwargs)

    assert (tmp_path / "b04b-postflight-001.json").read_bytes() == original
