from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from migrations.b04.adopt import (
    ACCESS_EXCLUSIVE_MARKER_LOCK,
    ADVISORY_LOCK_KEY,
    IDENTITY_RECHECK_QUERY,
    MarkerTransferError,
    MarkerTransferResult,
    PUBLIC_MARKER_QUERY,
    PUBLIC_VERSION_QUERY,
    TEST_MARKER_QUERY,
    TEST_VERSION_QUERY,
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
CREATE_PUBLIC_MARKER = """CREATE TABLE public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
)"""
INSERT_BASELINE = (
    "INSERT INTO public.alembic_version (version_num) "
    "VALUES ('canonical_baseline_v1')"
)
DROP_HISTORICAL_MARKER = "DROP TABLE test.alembic_version"


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

    def _record(self, operation: str) -> None:
        self.operations.append(operation)
        if self.fail_at == len(self.operations) - 1:
            raise InjectedFailure(operation)

    def execute(self, statement: Any, _parameters: Any = None) -> _Result:
        operation = str(statement)
        self._record(operation)
        if operation == IDENTITY_RECHECK_QUERY:
            return _Result(mapping={"database": "WeldPassport", "port": 5432})
        if operation == PUBLIC_MARKER_QUERY:
            return _Result(
                scalar=(
                    "public.alembic_version"
                    if self._historical_marker_dropped
                    else None
                )
            )
        if operation == TEST_MARKER_QUERY:
            return _Result(
                scalar=(
                    None
                    if self._historical_marker_dropped
                    else "test.alembic_version"
                )
            )
        if operation == TEST_VERSION_QUERY:
            return _Result(scalar=HISTORICAL_HEAD)
        if operation == DROP_HISTORICAL_MARKER:
            self._historical_marker_dropped = True
        if operation == PUBLIC_VERSION_QUERY:
            assert self._historical_marker_dropped
            return _Result(scalar=BASELINE_REVISION)
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
        prepared_at_utc="2026-07-29T09:30:00Z",
        verification_results=(
            ("active_evidence_verified", True),
            ("backup_restore_verified", True),
            ("fingerprint_verified", True),
            ("marker_verified", True),
            ("repository_digests_verified", True),
            ("sessions_verified", True),
        ),
    )


def _accepted_fingerprint(connection: _RecordingConnection) -> dict[str, object]:
    connection.record_fingerprint()
    return json.loads(ACCEPTED_FINGERPRINT.read_bytes())


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
