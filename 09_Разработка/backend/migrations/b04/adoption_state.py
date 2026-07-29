"""Immutable state and report contracts for B-04B baseline adoption."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from pathlib import Path
import re

from migrations.b04.disposable import DatabaseIdentity
from migrations.b04.manifest import canonical_json_bytes
from migrations.b04.source_contract import (
    BASELINE_REVISION,
    HISTORICAL_HEAD,
)


class AdoptionState(StrEnum):
    READY = "READY"
    ALREADY_ADOPTED = "ALREADY_ADOPTED"
    AMBIGUOUS = "AMBIGUOUS"
    COMMITTED_UNVERIFIED = "COMMITTED_UNVERIFIED"
    ACCEPTED = "ACCEPTED"


@dataclass(frozen=True, slots=True)
class MarkerSnapshot:
    """Observed marker rows plus the accepted active canonical graph."""

    public_table_exists: bool
    public_versions: tuple[str, ...]
    test_table_exists: bool
    test_versions: tuple[str, ...]
    canonical_revision_edges: tuple[tuple[str, str], ...] = ()


def _reachable_canonical_revisions(
    edges: tuple[tuple[str, str], ...],
) -> frozenset[str] | None:
    """Return one exact linear path rooted at the baseline, or fail closed."""

    if len(edges) != len(set(edges)):
        return None
    children: dict[str, list[str]] = {}
    for parent, child in edges:
        if not parent.strip() or not child.strip() or parent == child:
            return None
        children.setdefault(parent, []).append(child)

    reachable = {BASELINE_REVISION}
    current = BASELINE_REVISION
    traversed = 0
    while current in children:
        candidates = children[current]
        if len(candidates) != 1 or candidates[0] in reachable:
            return None
        current = candidates[0]
        reachable.add(current)
        traversed += 1

    if traversed != len(edges):
        return None
    return frozenset(reachable)


def classify_marker_state(snapshot: MarkerSnapshot) -> AdoptionState:
    """Classify an exact marker snapshot without repair or inference."""

    if snapshot.public_table_exists == snapshot.test_table_exists:
        return AdoptionState.AMBIGUOUS
    if not snapshot.public_table_exists and snapshot.public_versions:
        return AdoptionState.AMBIGUOUS
    if not snapshot.test_table_exists and snapshot.test_versions:
        return AdoptionState.AMBIGUOUS

    if (
        snapshot.test_table_exists
        and snapshot.test_versions == (HISTORICAL_HEAD,)
        and not snapshot.public_table_exists
    ):
        return AdoptionState.READY

    accepted = _reachable_canonical_revisions(snapshot.canonical_revision_edges)
    if (
        snapshot.public_table_exists
        and len(snapshot.public_versions) == 1
        and not snapshot.test_table_exists
        and accepted is not None
        and snapshot.public_versions[0] in accepted
    ):
        return AdoptionState.ALREADY_ADOPTED

    return AdoptionState.AMBIGUOUS


VerificationResults = tuple[tuple[str, bool], ...]
MANDATORY_VERIFICATION_RESULTS = (
    "active_evidence_verified",
    "backup_restore_verified",
    "fingerprint_verified",
    "marker_verified",
    "repository_digests_verified",
    "sessions_verified",
)


def database_identity_digest(
    identity: DatabaseIdentity,
    server_version_num: int,
) -> str:
    """Bind unredacted identity facts without publishing them in evidence."""

    if isinstance(server_version_num, bool) or not isinstance(server_version_num, int):
        raise ValueError("B04-IDENTITY-VERSION")
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "database": identity.database,
                "host": identity.host,
                "port": identity.port,
                "server_version_num": server_version_num,
                "username": identity.username,
            }
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    """Immutable PREPARED evidence emitted by the future read-only preflight."""

    adoption_id: str
    database_identity: DatabaseIdentity
    source_sha: str
    old_marker: str
    new_marker: str
    backup_sha256: str
    manifest_sha256: str
    fingerprint_sha256: str
    allowlist_sha256: str
    seed_sha256: str
    database_identity_sha256: str
    server_version_num: int
    prepared_at_utc: str
    verification_results: VerificationResults


@dataclass(frozen=True, slots=True)
class AdoptionReport:
    """Immutable, sanitized record suitable for append-only publication."""

    adoption_id: str
    database_identity: DatabaseIdentity
    source_sha: str
    old_marker: str
    new_marker: str
    backup_sha256: str
    manifest_sha256: str
    fingerprint_sha256: str
    allowlist_sha256: str
    seed_sha256: str
    attempt_status: AdoptionState
    started_at_utc: str
    completed_at_utc: str | None
    verification_results: VerificationResults


def canonical_report_bytes(report: AdoptionReport) -> bytes:
    """Serialize one report deterministically without credentials."""

    identity = report.database_identity
    return canonical_json_bytes(
        {
            "adoption_id": report.adoption_id,
            "database_identity": {
                "database": identity.database,
                "host": identity.host,
                "port": identity.port,
                "username": identity.username,
            },
            "source_sha": report.source_sha,
            "old_marker": report.old_marker,
            "new_marker": report.new_marker,
            "backup_sha256": report.backup_sha256,
            "manifest_sha256": report.manifest_sha256,
            "fingerprint_sha256": report.fingerprint_sha256,
            "allowlist_sha256": report.allowlist_sha256,
            "seed_sha256": report.seed_sha256,
            "attempt_status": report.attempt_status.value,
            "started_at_utc": report.started_at_utc,
            "completed_at_utc": report.completed_at_utc,
            "verification_results": dict(report.verification_results),
        }
    )


_ADOPTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def publish_report_once(directory: Path, report: AdoptionReport) -> Path:
    """Create one report by adoption ID without replacing an existing record."""

    if _ADOPTION_ID.fullmatch(report.adoption_id) is None:
        raise ValueError("B04-ADOPTION-ID")
    target = directory / f"{report.adoption_id}.json"
    with target.open("xb") as stream:
        stream.write(canonical_report_bytes(report))
    return target
