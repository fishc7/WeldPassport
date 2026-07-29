"""Pure/metadata contracts for AS-02 QualityDecision RBAC (ADR-028).

This file intentionally has no fixtures and can run with ``--noconftest``:
the runtime-profile/legacy-workforce test bootstrap is outside AS-02.
"""

from sqlalchemy.dialects.postgresql import JSONB

from app.quality import quality_decision_workflow as qdw
from app.quality.execution_models import QualityAuditEvent
from app.quality.quality_decision_models import QualityDecision


def test_quality_decision_has_nullable_review_submitter() -> None:
    column = QualityDecision.__table__.c.review_submitted_by_worker_id

    assert column.nullable is True


def test_quality_decision_review_submitter_matches_state() -> None:
    constraint = next(
        item
        for item in QualityDecision.__table__.constraints
        if item.name == "ck_quality_decisions_review_submitter_state"
    )

    sql = str(constraint.sqltext)
    assert "status = 'DRAFT' AND review_submitted_by_worker_id IS NULL" in sql
    assert (
        "status IN ('UNDER_REVIEW', 'DECIDED', 'SUPERSEDED') "
        "AND review_submitted_by_worker_id IS NOT NULL"
    ) in sql


def test_quality_audit_event_has_nullable_authorization_context() -> None:
    column = QualityAuditEvent.__table__.c.authorization_context

    assert column.nullable is True
    assert isinstance(column.type, JSONB)


def test_quality_decision_audit_requires_authorization_context() -> None:
    constraint = next(
        item
        for item in QualityAuditEvent.__table__.constraints
        if item.name == "ck_quality_audit_qd_authorization_context"
    )

    assert (
        str(constraint.sqltext)
        == "entity_type <> 'QUALITY_DECISION' OR authorization_context IS NOT NULL"
    )


def test_review_submitter_cannot_review_own_cycle() -> None:
    assert (
        qdw.validate_review_separation(
            actor_worker_id=42,
            review_submitted_by_worker_id=42,
        )
        == qdw.QD_SAME_ACTOR_REVIEW
    )


def test_different_worker_can_review_cycle() -> None:
    assert (
        qdw.validate_review_separation(
            actor_worker_id=43,
            review_submitted_by_worker_id=42,
        )
        is None
    )


def test_missing_submitter_does_not_create_false_same_actor_conflict() -> None:
    assert (
        qdw.validate_review_separation(
            actor_worker_id=42,
            review_submitted_by_worker_id=None,
        )
        is None
    )
