from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
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
    PostflightError,
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


@contextmanager
def _external_report_directory() -> Any:
    with TemporaryDirectory(prefix="b04-postflight-") as raw_directory:
        yield Path(raw_directory)


def test_b04b_postflight_001_success_stays_unverified_until_owner_signing(
) -> None:
    """Self-accepting a clean machine postflight would bypass the Task 7 owner gate."""

    connection = _Connection()
    context = _ConnectionContext(connection)
    commands: list[str] = []
    smoke_connections: list[_Connection] = []
    fingerprint = _fingerprint(connection)
    evidence = replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST)

    with _external_report_directory() as report_directory:
        report = run_postflight(
            lambda: context,
            evidence,
            fingerprint_extractor=_fingerprint,
            alembic_runner=lambda command: commands.append(command) is None,
            read_only_smoke=lambda observed: smoke_connections.append(observed) is None,
            completed_at_utc="2026-07-29T10:05:00Z",
            report_directory=report_directory,
        )
        report_bytes = (report_directory / "b04b-postflight-001.json").read_bytes()

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
    assert report_bytes == canonical_report_bytes(report)
    assert report_digest(report) == hashlib.sha256(canonical_report_bytes(report)).hexdigest()
    assert "db.internal.example" not in canonical_report_bytes(report).decode("utf-8")
    assert "maintenance_operator" not in canonical_report_bytes(report).decode("utf-8")
    assert fingerprint == ACCEPTED_FINGERPRINT


def test_b04b_postflight_002_failed_postcommit_marker_check_never_retries_transfer(
) -> None:
    """A post-commit marker mismatch must preserve the committed-unverified stop state."""

    connection = _Connection(public_version="wrong_revision")
    commands: list[str] = []

    with _external_report_directory() as report_directory:
        report = run_postflight(
            lambda: _ConnectionContext(connection),
            _prepared(),
            fingerprint_extractor=_fingerprint,
            alembic_runner=lambda command: commands.append(command) is None,
            read_only_smoke=lambda _: True,
            completed_at_utc="2026-07-29T10:05:00Z",
            report_directory=report_directory,
        )
        report_bytes = (report_directory / "b04b-postflight-001.json").read_bytes()

    assert report.attempt_status is AdoptionState.COMMITTED_UNVERIFIED
    assert report.completed_at_utc == "2026-07-29T10:05:00Z"
    assert report.verification_results[-1] == ("postflight_verified", False)
    assert connection.operations == [PUBLIC_MARKER_QUERY, PUBLIC_VERSION_QUERY]
    assert commands == []
    assert not any(
        operation.startswith(("CREATE", "INSERT", "DROP", "ALTER"))
        for operation in connection.operations
    )
    assert report_bytes == canonical_report_bytes(report)


def test_b04b_postflight_003_failed_alembic_check_stops_before_read_only_smoke() -> None:
    """Continuing to later checks after an Alembic failure would hide an incomplete postflight."""

    connection = _Connection()
    commands: list[str] = []
    smoke_calls: list[_Connection] = []
    evidence = replace(
        _prepared(),
        fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST,
    )

    with _external_report_directory() as report_directory:
        report = run_postflight(
            lambda: _ConnectionContext(connection),
            evidence,
            fingerprint_extractor=_fingerprint,
            alembic_runner=lambda command: (
                commands.append(command) is None and command != "history"
            ),
            read_only_smoke=lambda observed: smoke_calls.append(observed) is None,
            completed_at_utc="2026-07-29T10:05:00Z",
            report_directory=report_directory,
        )

    assert report.attempt_status is AdoptionState.COMMITTED_UNVERIFIED
    assert report.verification_results[-1] == ("postflight_verified", False)
    assert commands == ["heads", "current", "history"]
    assert smoke_calls == []


def test_b04b_postflight_004_external_report_is_append_only(
) -> None:
    """Replacing an operator evidence record would destroy the audit trail."""

    evidence = replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST)
    with _external_report_directory() as report_directory:
        kwargs = {
            "fingerprint_extractor": _fingerprint,
            "alembic_runner": lambda _: True,
            "read_only_smoke": lambda _: True,
            "completed_at_utc": "2026-07-29T10:05:00Z",
            "report_directory": report_directory,
        }

        run_postflight(lambda: _ConnectionContext(_Connection()), evidence, **kwargs)
        original = (report_directory / "b04b-postflight-001.json").read_bytes()

        with pytest.raises(FileExistsError):
            run_postflight(lambda: _ConnectionContext(_Connection()), evidence, **kwargs)

        assert (report_directory / "b04b-postflight-001.json").read_bytes() == original


@pytest.mark.parametrize(
    "verification_results",
    (
        _prepared().verification_results
        + (("postflight_verified", True),),
        _prepared().verification_results
        + (
            ("postflight_verified", True),
            ("postflight_verified", True),
        ),
    ),
)
def test_b04b_postflight_005_rejects_spoofed_postflight_results_before_connection(
    verification_results: tuple[tuple[str, bool], ...],
) -> None:
    """Prepared evidence must not predeclare machine postflight success or duplicate report keys."""

    factory_calls: list[None] = []
    evidence = replace(
        _prepared(),
        fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST,
        verification_results=verification_results,
    )

    with _external_report_directory() as report_directory:
        with pytest.raises(PostflightError, match="B04-POSTFLIGHT-PREPARED"):
            run_postflight(
                lambda: factory_calls.append(None),
                evidence,
                fingerprint_extractor=_fingerprint,
                alembic_runner=lambda _: True,
                read_only_smoke=lambda _: True,
                report_directory=report_directory,
            )

    assert factory_calls == []


@pytest.mark.parametrize(
    "report_directory",
    (
        None,
        Path(__file__).resolve().parents[3],
        Path(__file__).resolve().parents[1],
    ),
)
def test_b04b_postflight_006_requires_an_existing_external_report_directory(
    report_directory: Path | None,
) -> None:
    """A repository-local or omitted evidence destination would make audit evidence mutable."""

    factory_calls: list[None] = []

    with pytest.raises(PostflightError, match="B04-POSTFLIGHT-REPORT"):
        run_postflight(
            lambda: factory_calls.append(None),
            replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST),
            fingerprint_extractor=_fingerprint,
            alembic_runner=lambda _: True,
            read_only_smoke=lambda _: True,
            report_directory=report_directory,
        )

    assert factory_calls == []


def test_b04b_postflight_007_rejects_external_symlink_resolving_into_worktree() -> None:
    """A symlink must not disguise a repository-local report directory as external evidence."""

    with _external_report_directory() as external_directory:
        link = external_directory / "worktree-link"
        try:
            link.symlink_to(Path(__file__).resolve().parents[3], target_is_directory=True)
        except OSError:
            pytest.skip("directory symlink is not supported by this Windows test environment")

        with pytest.raises(PostflightError, match="B04-POSTFLIGHT-REPORT"):
            run_postflight(
                lambda: _ConnectionContext(_Connection()),
                replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST),
                fingerprint_extractor=_fingerprint,
                alembic_runner=lambda _: True,
                read_only_smoke=lambda _: True,
                report_directory=link,
            )


class _CardinalityErrorResult:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def scalar_one(self) -> object:
        raise self.error


class _CardinalityErrorConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def execute(self, statement: Any, _parameters: Any = None) -> _CardinalityErrorResult:
        self.operations.append(str(statement))
        return _CardinalityErrorResult(self.error)


class _BrokenContext:
    def __init__(self, phase: str, connection: _Connection) -> None:
        self.phase = phase
        self.connection = connection

    def __enter__(self) -> _Connection:
        if self.phase == "enter":
            raise RuntimeError("enter failed")
        return self.connection

    def __exit__(self, *_: object) -> None:
        if self.phase == "exit":
            raise RuntimeError("exit failed")


@pytest.mark.parametrize(
    ("phase", "connection", "fingerprint_extractor", "expected_operations"),
    (
        ("enter", _Connection(), _fingerprint, []),
        ("body", _CardinalityErrorConnection(RuntimeError("zero rows")), _fingerprint, [PUBLIC_MARKER_QUERY]),
        ("body", _CardinalityErrorConnection(RuntimeError("multiple rows")), _fingerprint, [PUBLIC_MARKER_QUERY]),
        ("exit", _Connection(), _fingerprint, [PUBLIC_MARKER_QUERY, PUBLIC_VERSION_QUERY, TEST_MARKER_QUERY]),
    ),
)
def test_b04b_postflight_008_context_failures_produce_published_unverified_report(
    phase: str,
    connection: _Connection,
    fingerprint_extractor: Any,
    expected_operations: list[str],
) -> None:
    """Enter, body, and exit failures after commit must stop without a marker retry."""

    commands: list[str] = []
    smoke_calls: list[object] = []
    evidence = replace(_prepared(), fingerprint_sha256=ACCEPTED_FINGERPRINT_DIGEST)
    with _external_report_directory() as report_directory:
        report = run_postflight(
            lambda: _BrokenContext(phase, connection),
            evidence,
            fingerprint_extractor=fingerprint_extractor,
            alembic_runner=lambda command: commands.append(command) is None,
            read_only_smoke=lambda observed: smoke_calls.append(observed) is None,
            report_directory=report_directory,
        )
        assert (report_directory / "b04b-postflight-001.json").read_bytes() == canonical_report_bytes(report)

    assert report.attempt_status is AdoptionState.COMMITTED_UNVERIFIED
    assert report.verification_results[-1] == ("postflight_verified", False)
    assert connection.operations == expected_operations
    if phase == "exit":
        assert commands == ["heads", "current", "history", "check"]
        assert smoke_calls == [connection]
    else:
        assert commands == []
        assert smoke_calls == []


@pytest.mark.parametrize(
    ("fingerprint_sha256", "alembic_result", "smoke_result", "expected_commands"),
    (
        ("f" * 64, True, True, []),
        (ACCEPTED_FINGERPRINT_DIGEST, 1, True, ["heads"]),
        (ACCEPTED_FINGERPRINT_DIGEST, True, 1, ["heads", "current", "history", "check"]),
    ),
)
def test_b04b_postflight_009_rejects_fingerprint_mismatch_and_truthy_dependencies(
    fingerprint_sha256: str,
    alembic_result: object,
    smoke_result: object,
    expected_commands: list[str],
) -> None:
    """Digest drift and truthy dependency answers must not be accepted as postflight proof."""

    connection = _Connection()
    commands: list[str] = []
    with _external_report_directory() as report_directory:
        report = run_postflight(
            lambda: _ConnectionContext(connection),
            replace(_prepared(), fingerprint_sha256=fingerprint_sha256),
            fingerprint_extractor=_fingerprint,
            alembic_runner=lambda command: commands.append(command) is None and alembic_result,
            read_only_smoke=lambda _: smoke_result,
            report_directory=report_directory,
        )

    assert report.verification_results[-1] == ("postflight_verified", False)
    assert commands == expected_commands


def test_b04b_postflight_010_failed_report_collision_preserves_first_failure() -> None:
    """A second failed post-commit attempt must not overwrite the first immutable failure evidence."""

    kwargs = {
        "fingerprint_extractor": _fingerprint,
        "alembic_runner": lambda _: True,
        "read_only_smoke": lambda _: True,
    }
    with _external_report_directory() as report_directory:
        first = run_postflight(
            lambda: _ConnectionContext(_Connection(public_version="wrong_revision")),
            _prepared(),
            report_directory=report_directory,
            **kwargs,
        )
        original = (report_directory / "b04b-postflight-001.json").read_bytes()

        with pytest.raises(FileExistsError):
            run_postflight(
                lambda: _ConnectionContext(_Connection(public_version="wrong_revision")),
                _prepared(),
                report_directory=report_directory,
                **kwargs,
            )

        assert (report_directory / "b04b-postflight-001.json").read_bytes() == original
    assert first.verification_results[-1] == ("postflight_verified", False)
