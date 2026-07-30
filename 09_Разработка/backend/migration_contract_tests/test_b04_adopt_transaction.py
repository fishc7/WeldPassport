from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from migrations.b04.adopt import (
    MarkerTransferError,
    MarkerTransferResult,
    transfer_marker,
)
from migrations.b04.adoption_state import PreparedEvidence
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
    SCHEMA_SOURCE_COMMIT,
)


ARTIFACT_ROOT = (
    Path(__file__).parents[1]
    / "migrations"
    / "baselines"
    / "canonical_baseline_v1"
)
ACCEPTED_FINGERPRINT = (
    ARTIFACT_ROOT / "postgresql-18" / "expected-fingerprint.json"
)
RESTORE_FINGERPRINT = (
    ARTIFACT_ROOT
    / "postgresql-18"
    / "restore-roundtrip-v1"
    / "expected-fingerprint.json"
)
CREATE_PUBLIC_MARKER = """CREATE TABLE public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
)"""
INSERT_BASELINE = (
    "INSERT INTO public.alembic_version (version_num) "
    "VALUES ('canonical_baseline_v1')"
)
DROP_HISTORICAL_MARKER = "DROP TABLE test.alembic_version"
ADVISORY_LOCK_KEY = 4_042_904
IDENTITY_RECHECK_QUERY = """SELECT
    current_database() AS database,
    inet_server_addr()::text AS host,
    inet_server_port() AS port,
    current_user AS username,
    current_setting('server_version_num')::integer AS server_version_num"""
PUBLIC_MARKER_QUERY = "SELECT to_regclass('public.alembic_version')"
PUBLIC_VERSION_QUERY = "SELECT version_num FROM public.alembic_version"
TEST_MARKER_QUERY = "SELECT to_regclass('test.alembic_version')"
TEST_VERSION_QUERY = "SELECT version_num FROM test.alembic_version"
ACCESS_EXCLUSIVE_MARKER_LOCK = (
    "LOCK TABLE test.alembic_version IN ACCESS EXCLUSIVE MODE"
)
MANDATORY_VERIFICATION_RESULTS = (
    ("active_evidence_verified", True),
    ("backup_restore_verified", True),
    ("fingerprint_verified", True),
    ("marker_verified", True),
    ("repository_digests_verified", True),
    ("sessions_verified", True),
)
RAW_IDENTITY_DIGEST = hashlib.sha256(
    b'{"database":"WeldPassport","host":"db.internal","port":5432,'
    b'"server_version_num":180003,"username":"maintenance_operator"}\n'
).hexdigest()


class InjectedFailure(RuntimeError):
    """A recording-connection failure at one transaction boundary."""


@dataclass(frozen=True)
class _Result:
    mapping: dict[str, object] | None = None
    scalar: object | None = None

    def mappings(self) -> "_Result":
        return self

    def one(self) -> dict[str, object]:
        assert self.mapping is not None
        return self.mapping

    def scalar_one(self) -> object:
        return self.scalar


def _accepted_table_pairs() -> tuple[tuple[str, str], ...]:
    fingerprint = json.loads(ACCEPTED_FINGERPRINT.read_bytes())
    return tuple(
        sorted((table["schema"], table["name"]) for table in fingerprint["tables"])
    )


def _share_lock(schema: str, table: str) -> str:
    return f'LOCK TABLE "{schema}"."{table}" IN SHARE MODE'


def _expected_operations() -> list[str]:
    return [
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        "SET LOCAL lock_timeout = '5s'",
        "SET LOCAL statement_timeout = '30s'",
        "SET LOCAL search_path = pg_catalog",
        f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK_KEY})",
        IDENTITY_RECHECK_QUERY,
        *[_share_lock(schema, table) for schema, table in _accepted_table_pairs()],
        ACCESS_EXCLUSIVE_MARKER_LOCK,
        PUBLIC_MARKER_QUERY,
        TEST_MARKER_QUERY,
        TEST_VERSION_QUERY,
        "fingerprint",
        CREATE_PUBLIC_MARKER,
        INSERT_BASELINE,
        DROP_HISTORICAL_MARKER,
        PUBLIC_MARKER_QUERY,
        PUBLIC_VERSION_QUERY,
        TEST_MARKER_QUERY,
        "fingerprint",
    ]


class _RecordingConnection:
    """A strict no-I/O SQLAlchemy boundary fake for the marker transaction."""

    def __init__(self, *, fail_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.operations: list[str] = []
        self._historical_marker_dropped = False
        self.dialect = postgresql.dialect()
        self.identity = {
            "database": "WeldPassport",
            "host": "db.internal",
            "port": 5432,
            "username": "maintenance_operator",
            "server_version_num": 180003,
        }
        self.pre_public_marker: object = None
        self.pre_test_marker: object = "test.alembic_version"
        self.pre_test_version: object = HISTORICAL_HEAD
        self.post_public_marker: object = "public.alembic_version"
        self.post_public_version: object = BASELINE_REVISION
        self.post_test_marker: object = None

    def _record(self, operation: str) -> None:
        self.operations.append(operation)
        if self.fail_at == len(self.operations) - 1:
            raise InjectedFailure(operation)

    def execute(self, statement: Any, _parameters: Any = None) -> _Result:
        operation = str(statement)
        self._record(operation)
        if operation == IDENTITY_RECHECK_QUERY:
            return _Result(mapping=self.identity)
        if operation == PUBLIC_MARKER_QUERY:
            return _Result(
                scalar=(
                    self.post_public_marker
                    if self._historical_marker_dropped
                    else self.pre_public_marker
                )
            )
        if operation == TEST_MARKER_QUERY:
            return _Result(
                scalar=(
                    self.post_test_marker
                    if self._historical_marker_dropped
                    else self.pre_test_marker
                )
            )
        if operation == TEST_VERSION_QUERY:
            return _Result(scalar=self.pre_test_version)
        if operation == DROP_HISTORICAL_MARKER:
            self._historical_marker_dropped = True
        if operation == PUBLIC_VERSION_QUERY:
            assert self._historical_marker_dropped
            return _Result(scalar=self.post_public_version)
        return _Result()

    def record_fingerprint(self) -> None:
        self._record("fingerprint")

    def commit(self) -> None:
        self._record("caller commit")


def _prepared() -> PreparedEvidence:
    fingerprint_sha256 = hashlib.sha256(ACCEPTED_FINGERPRINT.read_bytes()).hexdigest()
    return PreparedEvidence(
        adoption_id="b04b-adoption-001",
        database_identity=DatabaseIdentity(
            database="WeldPassport",
            host="[redacted]",
            port=5432,
            username="[redacted]",
        ),
        source_sha=SCHEMA_SOURCE_COMMIT,
        old_marker=HISTORICAL_HEAD,
        new_marker=BASELINE_REVISION,
        backup_sha256="a" * 64,
        manifest_sha256="b" * 64,
        fingerprint_sha256=fingerprint_sha256,
        allowlist_sha256="c" * 64,
        seed_sha256="d" * 64,
        database_identity_sha256=RAW_IDENTITY_DIGEST,
        server_version_num=180003,
        prepared_at_utc="2026-07-29T09:30:00Z",
        verification_results=MANDATORY_VERIFICATION_RESULTS,
    )


def _accepted_fingerprint(connection: _RecordingConnection) -> dict[str, object]:
    connection.record_fingerprint()
    return json.loads(ACCEPTED_FINGERPRINT.read_bytes())


def _different_fingerprint(connection: _RecordingConnection) -> dict[str, object]:
    connection.record_fingerprint()
    value = json.loads(ACCEPTED_FINGERPRINT.read_bytes())
    value["tables"][0]["columns"][0]["default"] = "0"
    return value


def _restore_fingerprint(connection: _RecordingConnection) -> dict[str, object]:
    connection.record_fingerprint()
    return json.loads(RESTORE_FINGERPRINT.read_bytes())


def test_b04b_adopt_001_transfers_only_in_the_required_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing, reordering, or committing any transfer boundary is a defect."""

    connection = _RecordingConnection()
    monkeypatch.setattr("migrations.b04.adopt.extract_fingerprint", _accepted_fingerprint)

    result = transfer_marker(connection, _prepared())

    assert result == MarkerTransferResult(
        adoption_id="b04b-adoption-001",
        old_marker=HISTORICAL_HEAD,
        new_marker=BASELINE_REVISION,
        fingerprint_sha256=hashlib.sha256(ACCEPTED_FINGERPRINT.read_bytes()).hexdigest(),
    )
    assert connection.operations == _expected_operations()
    assert "caller commit" not in connection.operations

    connection.commit()

    assert connection.operations == [*_expected_operations(), "caller commit"]


def test_b04b_adopt_001a_restored_profile_keeps_live_trust_and_checks_restore_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _RecordingConnection()
    monkeypatch.setattr(
        "migrations.b04.adopt.extract_fingerprint",
        _restore_fingerprint,
    )
    evidence = replace(
        _prepared(),
        observed_fingerprint_sha256=hashlib.sha256(
            RESTORE_FINGERPRINT.read_bytes()
        ).hexdigest(),
    )

    result = transfer_marker(connection, evidence)

    assert result.fingerprint_sha256 == evidence.fingerprint_sha256
    assert connection.operations == _expected_operations()


def test_b04b_adopt_001b_rejects_unbound_restore_digest_before_sql() -> None:
    connection = _RecordingConnection()

    with pytest.raises(MarkerTransferError, match="B04-ADOPT-PREPARED"):
        transfer_marker(
            connection,
            replace(_prepared(), observed_fingerprint_sha256="0" * 64),
        )

    assert connection.operations == []


@pytest.mark.parametrize("fail_at", range(len(_expected_operations())))
def test_b04b_adopt_002_failure_at_any_boundary_stops_before_later_sql(
    monkeypatch: pytest.MonkeyPatch,
    fail_at: int,
) -> None:
    """Continuing after a failed lock, recheck, DDL, or DML boundary is a defect."""

    connection = _RecordingConnection(fail_at=fail_at)
    monkeypatch.setattr("migrations.b04.adopt.extract_fingerprint", _accepted_fingerprint)

    with pytest.raises((InjectedFailure, MarkerTransferError)):
        transfer_marker(connection, _prepared())

    assert connection.operations == _expected_operations()[: fail_at + 1]
    assert "caller commit" not in connection.operations


@pytest.mark.parametrize(
    "verification_results",
    (
        (),
        MANDATORY_VERIFICATION_RESULTS[:-1],
        (*MANDATORY_VERIFICATION_RESULTS, ("unexpected", True)),
        (*MANDATORY_VERIFICATION_RESULTS, ("marker_verified", True)),
        (
            ("active_evidence_verified", 1),
            *MANDATORY_VERIFICATION_RESULTS[1:],
        ),
        (
            ("active_evidence_verified", False),
            *MANDATORY_VERIFICATION_RESULTS[1:],
        ),
    ),
)
def test_b04b_adopt_003_verification_results_are_an_exact_true_only_set(
    verification_results: tuple[tuple[str, object], ...],
) -> None:
    """Missing, unknown, duplicate, or truthy-non-bool evidence must not transfer."""

    connection = _RecordingConnection()

    with pytest.raises(MarkerTransferError, match="B04-ADOPT-PREPARED"):
        transfer_marker(
            connection,
            replace(_prepared(), verification_results=verification_results),
        )

    assert connection.operations == []
    assert "caller commit" not in connection.operations


@pytest.mark.parametrize(
    ("mutation", "expected_count", "error_code"),
    (
        ("identity_host", 6, "IDENTITY"),
        ("identity_username", 6, "IDENTITY"),
        ("identity_server_version", 6, "IDENTITY"),
        ("pre_public_marker", 81, "MARKER"),
        ("pre_test_marker", 82, "MARKER"),
        ("pre_test_version", 83, "MARKER"),
        ("first_fingerprint_mismatch", 84, "FINGERPRINT"),
        ("fingerprint_extractor_failure", 84, "FINGERPRINT"),
        ("post_public_marker", 88, "MARKER"),
        ("post_public_version", 89, "MARKER"),
        ("post_test_marker", 90, "MARKER"),
        ("final_fingerprint_mismatch", 91, "FINGERPRINT"),
    ),
)
def test_b04b_adopt_004_semantic_recheck_failures_stop_before_later_sql(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_count: int,
    error_code: str,
) -> None:
    """A semantic mismatch must stop the transfer before another SQL boundary."""

    connection = _RecordingConnection()
    extractor = _accepted_fingerprint
    if mutation == "identity_host":
        connection.identity["host"] = "other.internal"
    elif mutation == "identity_username":
        connection.identity["username"] = "other_operator"
    elif mutation == "identity_server_version":
        connection.identity["server_version_num"] = 180004
    elif mutation == "pre_public_marker":
        connection.pre_public_marker = "public.alembic_version"
    elif mutation == "pre_test_marker":
        connection.pre_test_marker = None
    elif mutation == "pre_test_version":
        connection.pre_test_version = "unexpected_revision"
    elif mutation == "first_fingerprint_mismatch":
        extractor = _different_fingerprint
    elif mutation == "fingerprint_extractor_failure":
        def extractor(connection: _RecordingConnection) -> dict[str, object]:
            connection.record_fingerprint()
            raise RuntimeError("catalog unavailable")
    elif mutation == "post_public_marker":
        connection.post_public_marker = None
    elif mutation == "post_public_version":
        connection.post_public_version = "unexpected_revision"
    elif mutation == "post_test_marker":
        connection.post_test_marker = "test.alembic_version"
    else:
        calls = 0

        def extractor(connection: _RecordingConnection) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return _accepted_fingerprint(connection) if calls == 1 else _different_fingerprint(connection)

    monkeypatch.setattr("migrations.b04.adopt.extract_fingerprint", extractor)

    with pytest.raises(MarkerTransferError, match=f"B04-ADOPT-{error_code}"):
        transfer_marker(connection, _prepared())

    assert connection.operations == _expected_operations()[:expected_count]
    assert "caller commit" not in connection.operations
