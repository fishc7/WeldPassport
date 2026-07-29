"""Atomic, caller-committed B-04B Alembic marker transfer."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection

from migrations.b04.adoption_state import (
    PreparedEvidence,
    PreparedEvidenceError,
    database_identity_digest,
    validate_prepared_evidence,
)
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.fingerprint import assert_supported_catalog, extract_fingerprint, fingerprint_digest
from migrations.b04.source_contract import (
    CANONICAL_TABLE_COUNT,
)


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
_ACCEPTED_FINGERPRINT = (
    Path(__file__).parents[1]
    / "baselines"
    / "canonical_baseline_v1"
    / "postgresql-18"
    / "expected-fingerprint.json"
)


class MarkerTransferError(ValueError):
    """The caller-supplied B-04B transfer prerequisites no longer hold."""


@dataclass(frozen=True, slots=True)
class MarkerTransferResult:
    """The in-transaction marker state, pending the caller-owned commit."""

    adoption_id: str
    old_marker: str
    new_marker: str
    fingerprint_sha256: str


def _fail(code: str) -> None:
    raise MarkerTransferError(f"B04-ADOPT-{code}")


def _accepted_table_pairs(evidence: PreparedEvidence) -> tuple[tuple[str, str], ...]:
    """Load exactly the accepted table allowlist before quoting identifiers."""

    try:
        raw = _ACCEPTED_FINGERPRINT.read_bytes()
        fingerprint = json.loads(raw)
        assert isinstance(fingerprint, Mapping)
        assert_supported_catalog(fingerprint)
    except Exception as exc:
        raise MarkerTransferError("B04-ADOPT-EVIDENCE") from exc
    if hashlib.sha256(raw).hexdigest() != evidence.fingerprint_sha256:
        _fail("EVIDENCE")

    pairs = tuple(
        sorted(
            (table["schema"], table["name"])
            for table in fingerprint["tables"]
            if isinstance(table, Mapping)
            and isinstance(table.get("schema"), str)
            and isinstance(table.get("name"), str)
        )
    )
    if len(pairs) != CANONICAL_TABLE_COUNT or len(pairs) != len(set(pairs)):
        _fail("EVIDENCE")
    return pairs


def _validate_prepared_evidence(evidence: PreparedEvidence) -> None:
    try:
        validate_prepared_evidence(evidence)
    except PreparedEvidenceError as exc:
        raise MarkerTransferError("B04-ADOPT-PREPARED") from exc


def _recheck_identity(connection: Connection, evidence: PreparedEvidence) -> None:
    row = connection.execute(text(IDENTITY_RECHECK_QUERY)).mappings().one()
    try:
        observed = DatabaseIdentity(
            database=row["database"],
            host=row["host"],
            port=row["port"],
            username=row["username"],
        )
        version = row["server_version_num"]
        observed_digest = database_identity_digest(observed, version)
    except (KeyError, TypeError, ValueError):
        _fail("IDENTITY")
    if (
        observed_digest != evidence.database_identity_sha256
        or version != evidence.server_version_num
        or observed.database != evidence.database_identity.database
        or observed.port != evidence.database_identity.port
    ):
        _fail("IDENTITY")


def _recheck_historical_marker(connection: Connection, evidence: PreparedEvidence) -> None:
    public_marker = connection.execute(text(PUBLIC_MARKER_QUERY)).scalar_one()
    if public_marker is not None:
        _fail("MARKER")
    test_marker = connection.execute(text(TEST_MARKER_QUERY)).scalar_one()
    if test_marker != "test.alembic_version":
        _fail("MARKER")
    test_version = connection.execute(text(TEST_VERSION_QUERY)).scalar_one()
    if test_version != evidence.old_marker:
        _fail("MARKER")


def _recheck_baseline_marker(connection: Connection, evidence: PreparedEvidence) -> None:
    public_marker = connection.execute(text(PUBLIC_MARKER_QUERY)).scalar_one()
    if public_marker != "public.alembic_version":
        _fail("MARKER")
    public_version = connection.execute(text(PUBLIC_VERSION_QUERY)).scalar_one()
    if public_version != evidence.new_marker:
        _fail("MARKER")
    test_marker = connection.execute(text(TEST_MARKER_QUERY)).scalar_one()
    if test_marker is not None:
        _fail("MARKER")


def _recheck_fingerprint(connection: Connection, evidence: PreparedEvidence) -> None:
    try:
        actual = fingerprint_digest(extract_fingerprint(connection))
    except Exception as exc:
        raise MarkerTransferError("B04-ADOPT-FINGERPRINT") from exc
    if actual != evidence.fingerprint_sha256:
        _fail("FINGERPRINT")


def transfer_marker(
    connection: Connection,
    evidence: PreparedEvidence,
) -> MarkerTransferResult:
    """Transfer one marker without creating an engine or committing the transaction."""

    _validate_prepared_evidence(evidence)
    table_pairs = _accepted_table_pairs(evidence)

    connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '30s'"))
    connection.execute(text("SET LOCAL search_path = pg_catalog"))
    connection.execute(text(f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK_KEY})"))
    _recheck_identity(connection, evidence)

    preparer = connection.dialect.identifier_preparer
    for schema, table in table_pairs:
        quoted_schema = preparer.quote_identifier(schema)
        quoted_table = preparer.quote_identifier(table)
        connection.execute(text(f"LOCK TABLE {quoted_schema}.{quoted_table} IN SHARE MODE"))
    connection.execute(text(ACCESS_EXCLUSIVE_MARKER_LOCK))

    _recheck_historical_marker(connection, evidence)
    _recheck_fingerprint(connection, evidence)
    connection.execute(
        text(
            """CREATE TABLE public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
)"""
        )
    )
    connection.execute(
        text(
            "INSERT INTO public.alembic_version (version_num) "
            "VALUES ('canonical_baseline_v1')"
        )
    )
    connection.execute(text("DROP TABLE test.alembic_version"))
    _recheck_baseline_marker(connection, evidence)
    _recheck_fingerprint(connection, evidence)

    return MarkerTransferResult(
        adoption_id=evidence.adoption_id,
        old_marker=evidence.old_marker,
        new_marker=evidence.new_marker,
        fingerprint_sha256=evidence.fingerprint_sha256,
    )
