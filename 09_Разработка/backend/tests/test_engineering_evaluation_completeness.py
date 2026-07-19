"""Тесты validation matrix / completeness EngineeringEvaluation (Task 9D-2C).

Покрывают агрегированную (C11) read-only (C12) проверку готовности к PREPARED:
обязательные поля, outcome↔criteria, classification↔outcome, severity/impact↔outcome,
допустимость disposition, покрытие исключениями, confidence (+note при LOW, C16),
residual_risk, application_conditions, review_due_at, правила NOT_APPLICABLE и
INSUFFICIENT_DATA (C14), свежесть источников.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_workflow as eew

from .test_engineering_evaluation_core import EvalCtx

FUTURE = datetime.now(timezone.utc) + timedelta(days=30)


def _new(ctx: EvalCtx):
    finding = ctx.make_finding()
    repo = ctx.repo()
    _, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    return repo, rev, finding


def _set(repo, rev, **fields):
    repo.update_revision(
        rev, expected_version=rev.version,
        actor_worker_id=rev.created_by_worker_id, fields=fields,
    )
    repo.save()


def _source(repo, rev, finding, ctx):
    return repo.add_source(
        rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
        source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
    )


# ── Happy paths ───────────────────────────────────────────────────────────────


def test_acceptable_complete(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPA")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="ACCEPTABLE", classification="NOT_CONFIRMED",
         recommended_disposition="NONE", confirmed_severity="NOT_APPLICABLE",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="соответствует")
    res = repo.validate_revision(rev)
    assert res.ok, res.codes


def test_conditionally_acceptable_complete(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPB")
    repo, rev, finding = _new(ctx)
    crit = repo.add_criterion(rev, requirement_ref="r", parameter="p",
                              comparison_result="DOES_NOT_COMPLY",
                              actor_worker_id=ctx.ogs.id)
    repo.add_exception(rev, criterion_id=crit.id, basis="b", justification="j",
                       residual_risk="r", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="CONDITIONALLY_ACCEPTABLE",
         classification="CONFIRMED_DEFECT", recommended_disposition="REPAIR",
         confirmed_severity="MAJOR", impact_scope="FULL_JOINT_BLOCK",
         rationale="условно приемлемо", confidence_level="HIGH",
         residual_risk="остаточный риск", application_conditions="условия",
         review_due_at=FUTURE)
    res = repo.validate_revision(rev)
    assert res.ok, res.codes


# ── Negative cases ────────────────────────────────────────────────────────────


def test_empty_revision_aggregates_required(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPC")
    repo, rev, _ = _new(ctx)
    res = repo.validate_revision(rev)
    assert not res.ok
    for code in (
        eew.EVAL_OUTCOME_REQUIRED, eew.EVAL_CLASSIFICATION_REQUIRED,
        eew.EVAL_DISPOSITION_REQUIRED, eew.EVAL_SEVERITY_REQUIRED,
        eew.EVAL_IMPACT_SCOPE_REQUIRED, eew.EVAL_RATIONALE_REQUIRED,
        eew.EVAL_SOURCE_REQUIRED, eew.EVAL_CRITERION_REQUIRED,
    ):
        assert code in res.codes


def test_acceptable_with_deviation_mismatch(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPD")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="DOES_NOT_COMPLY", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="ACCEPTABLE", classification="NOT_CONFIRMED",
         recommended_disposition="NONE", confirmed_severity="NOT_APPLICABLE",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="x")
    assert eew.EVAL_OUTCOME_CRITERIA_MISMATCH in repo.validate_revision(rev).codes


def test_conditional_without_exception(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPE")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="DOES_NOT_COMPLY", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="CONDITIONALLY_ACCEPTABLE",
         classification="CONFIRMED_DEFECT", recommended_disposition="REPAIR",
         confirmed_severity="MAJOR", impact_scope="FULL_JOINT_BLOCK",
         rationale="x", confidence_level="HIGH", residual_risk="r",
         application_conditions="c", review_due_at=FUTURE)
    assert eew.EVAL_ACCEPT_WITHOUT_EXCEPTION in repo.validate_revision(rev).codes


def test_disposition_not_allowed(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPF")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="NOT_APPLICABLE",
                       applicability_comment="неприменимо", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="NOT_APPLICABLE", classification="OUT_OF_SCOPE",
         recommended_disposition="REPAIR", confirmed_severity="NOT_APPLICABLE",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="x")
    assert eew.EVAL_DISPOSITION_NOT_ALLOWED in repo.validate_revision(rev).codes


def test_classification_outcome_mismatch(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPG")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="ACCEPTABLE", classification="CONFIRMED_DEFECT",
         recommended_disposition="NONE", confirmed_severity="NOT_APPLICABLE",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="x")
    assert eew.EVAL_CLASSIFICATION_OUTCOME_MISMATCH in repo.validate_revision(rev).codes


def test_severity_outcome_mismatch(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPH")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="ACCEPTABLE", classification="NOT_CONFIRMED",
         recommended_disposition="NONE", confirmed_severity="MAJOR",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="x")
    assert eew.EVAL_CLASSIFICATION_OUTCOME_MISMATCH in repo.validate_revision(rev).codes


def test_na_criterion_missing_applicability_comment(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPI")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="NOT_APPLICABLE", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="NOT_APPLICABLE", classification="OUT_OF_SCOPE",
         recommended_disposition="NONE", confirmed_severity="NOT_APPLICABLE",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="x")
    assert eew.EVAL_APPLICABILITY_COMMENT_REQUIRED in repo.validate_revision(rev).codes


def test_insufficient_data_requires_confidence(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPJ")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="INSUFFICIENT_DATA", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="INSUFFICIENT_DATA",
         classification="REQUIRES_ADDITIONAL_EVIDENCE",
         recommended_disposition="ADDITIONAL_INSPECTION",
         confirmed_severity="NOT_APPLICABLE", impact_scope="NO_OPERATIONAL_IMPACT",
         rationale="x", review_due_at=FUTURE)
    assert eew.EVAL_CONFIDENCE_REQUIRED in repo.validate_revision(rev).codes


def test_low_confidence_requires_note(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPK")
    repo, rev, finding = _new(ctx)
    crit = repo.add_criterion(rev, requirement_ref="r", parameter="p",
                              comparison_result="DOES_NOT_COMPLY",
                              actor_worker_id=ctx.ogs.id)
    repo.add_exception(rev, criterion_id=crit.id, basis="b", justification="j",
                       residual_risk="r", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="CONDITIONALLY_ACCEPTABLE",
         classification="CONFIRMED_DEFECT", recommended_disposition="REPAIR",
         confirmed_severity="MAJOR", impact_scope="FULL_JOINT_BLOCK",
         rationale="x", confidence_level="LOW", residual_risk="r",
         application_conditions="c", review_due_at=FUTURE)
    assert eew.EVAL_CONFIDENCE_NOTE_REQUIRED in repo.validate_revision(rev).codes


def test_stale_source_surfaced(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "CPL")
    repo, rev, finding = _new(ctx)
    repo.add_criterion(rev, requirement_ref="r", parameter="p",
                       comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id)
    _source(repo, rev, finding, ctx)
    _set(repo, rev, evaluation_outcome="ACCEPTABLE", classification="NOT_CONFIRMED",
         recommended_disposition="NONE", confirmed_severity="NOT_APPLICABLE",
         impact_scope="NO_OPERATIONAL_IMPACT", rationale="x")
    # initial_risk входит в профиль QUALITY_FINDING → источник становится stale.
    finding.initial_risk = "LOW"
    db.commit()
    assert eew.EVAL_SOURCE_STALE in repo.validate_revision(rev).codes
