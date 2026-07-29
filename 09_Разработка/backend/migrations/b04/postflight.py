"""Fail-closed post-commit verification for B-04B marker adoption."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import text

from migrations.b04.adoption_state import (
    AdoptionReport,
    AdoptionState,
    PreparedEvidence,
    canonical_report_bytes,
    publish_report_once,
)
from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.fingerprint import extract_fingerprint, fingerprint_digest
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
    SCHEMA_SOURCE_COMMIT,
)


PUBLIC_MARKER_QUERY = "SELECT to_regclass('public.alembic_version')"
PUBLIC_VERSION_QUERY = "SELECT version_num FROM public.alembic_version"
TEST_MARKER_QUERY = "SELECT to_regclass('test.alembic_version')"

_POSTFLIGHT_RESULT_KEYS = (
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
_ALEMBIC_CHECKS = ("heads", "current", "history", "check")

ConnectionFactory = Callable[[], AbstractContextManager[Any]]
AlembicRunner = Callable[[str], bool]
ReadOnlySmoke = Callable[[Any], bool]
FingerprintExtractor = Callable[[Any], dict[str, object]]


class PostflightError(ValueError):
    """A post-commit fact could not be verified without retrying adoption."""


def _fail(code: str) -> None:
    raise PostflightError(f"B04-POSTFLIGHT-{code}")


def _completed_at(value: str | None) -> str:
    if value is not None:
        return value
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sanitized_identity(identity: DatabaseIdentity) -> DatabaseIdentity:
    """Keep only the non-secret identity facts allowed in an external report."""

    return DatabaseIdentity(
        database=identity.database,
        host="[redacted]",
        port=identity.port,
        username="[redacted]",
    )


def _report(
    evidence: PreparedEvidence,
    *,
    completed_at_utc: str,
    verified: bool,
) -> AdoptionReport:
    verification_results = evidence.verification_results
    if verified:
        verification_results = (
            *verification_results,
            *((key, True) for key in _POSTFLIGHT_RESULT_KEYS),
        )
    else:
        verification_results = (*verification_results, ("postflight_verified", False))
    return AdoptionReport(
        adoption_id=evidence.adoption_id,
        database_identity=_sanitized_identity(evidence.database_identity),
        source_sha=evidence.source_sha,
        old_marker=evidence.old_marker,
        new_marker=evidence.new_marker,
        backup_sha256=evidence.backup_sha256,
        manifest_sha256=evidence.manifest_sha256,
        fingerprint_sha256=evidence.fingerprint_sha256,
        allowlist_sha256=evidence.allowlist_sha256,
        seed_sha256=evidence.seed_sha256,
        # Machine verification is never the Task 7 owner-signed acceptance.
        attempt_status=AdoptionState.COMMITTED_UNVERIFIED,
        started_at_utc=evidence.prepared_at_utc,
        completed_at_utc=completed_at_utc,
        verification_results=verification_results,
    )


def _validate_evidence(evidence: PreparedEvidence) -> None:
    if (
        evidence.source_sha != SCHEMA_SOURCE_COMMIT
        or evidence.old_marker != HISTORICAL_HEAD
        or evidence.new_marker != BASELINE_REVISION
    ):
        _fail("EVIDENCE")


def _verify_markers(connection: Any, evidence: PreparedEvidence) -> None:
    if (
        connection.execute(text(PUBLIC_MARKER_QUERY)).scalar_one()
        != "public.alembic_version"
    ):
        _fail("MARKER")
    if connection.execute(text(PUBLIC_VERSION_QUERY)).scalar_one() != evidence.new_marker:
        _fail("MARKER")
    if connection.execute(text(TEST_MARKER_QUERY)).scalar_one() is not None:
        _fail("MARKER")


def _verify_fingerprint(
    connection: Any,
    evidence: PreparedEvidence,
    fingerprint_extractor: FingerprintExtractor,
) -> None:
    try:
        observed_digest = fingerprint_digest(fingerprint_extractor(connection))
    except Exception as exc:
        raise PostflightError("B04-POSTFLIGHT-FINGERPRINT") from exc
    if observed_digest != evidence.fingerprint_sha256:
        _fail("FINGERPRINT")


def _verify_alembic(alembic_runner: AlembicRunner) -> None:
    for command in _ALEMBIC_CHECKS:
        if alembic_runner(command) is not True:
            _fail("ALEMBIC")


def report_digest(report: AdoptionReport) -> str:
    """Return a deterministic digest of the sanitized canonical report."""

    return hashlib.sha256(canonical_report_bytes(report)).hexdigest()


def run_postflight(
    connection_factory: ConnectionFactory,
    evidence: PreparedEvidence,
    *,
    fingerprint_extractor: FingerprintExtractor = extract_fingerprint,
    alembic_runner: AlembicRunner | None = None,
    read_only_smoke: ReadOnlySmoke | None = None,
    completed_at_utc: str | None = None,
    report_directory: Path | None = None,
) -> AdoptionReport:
    """Verify committed adoption once; failures remain committed-unverified.

    The caller supplies every environment-dependent dependency.  This function
    creates no engine, executes no marker transfer, and never creates a report
    path unless the caller explicitly provides an external destination.
    """

    completed = _completed_at(completed_at_utc)
    try:
        if alembic_runner is None or read_only_smoke is None:
            _fail("DEPENDENCY")
        _validate_evidence(evidence)
        with connection_factory() as connection:
            _verify_markers(connection, evidence)
            _verify_fingerprint(connection, evidence, fingerprint_extractor)
            _verify_alembic(alembic_runner)
            if read_only_smoke(connection) is not True:
                _fail("SMOKE")
    except Exception:
        report = _report(evidence, completed_at_utc=completed, verified=False)
        if report_directory is not None:
            publish_report_once(report_directory, report)
        return report

    report = _report(evidence, completed_at_utc=completed, verified=True)
    if report_directory is not None:
        publish_report_once(report_directory, report)
    return report
