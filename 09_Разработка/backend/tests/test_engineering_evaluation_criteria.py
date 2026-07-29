"""Тесты критериев EngineeringEvaluation (Task 9D-2B).

Покрывают: add/update/remove критерия в DRAFT; событие `EVALUATION_UPDATED` с
metadata `{entity, operation}` (решение 9D-2B-C01, без CRITERION_* типов);
CHECK `comparison_result`; сохранение `applicability_comment`; запрет вне DRAFT.

API/RBAC/prepare-completeness (обязательность applicability_comment при NOT_APPLICABLE —
9D-2C) здесь не проверяются.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_workflow as eew

from .test_engineering_evaluation_core import EvalCtx


def _evaluation(ctx: EvalCtx):
    finding = ctx.make_finding()
    repo = ctx.repo()
    _, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    return repo, rev


def test_add_criterion_logs_evaluation_updated_metadata(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ECA")
    repo, rev = _evaluation(ctx)
    crit = repo.add_criterion(
        rev, requirement_ref="ГОСТ 16037-80, п.1", parameter="усиление шва",
        comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    assert crit.comparison_result == "COMPLIES"
    events = repo.list_events(rev.evaluation_id)
    assert [e.event_type for e in events] == ["EVALUATION_CREATED", "EVALUATION_UPDATED"]
    meta = events[1].event_metadata
    assert meta["entity"] == "EngineeringEvaluationCriterion"
    assert meta["operation"] == "ADD"
    assert meta["criterion_id"] == str(crit.id)


def test_criterion_invalid_comparison_result_rejected(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ECB")
    repo, rev = _evaluation(ctx)
    try:
        repo.add_criterion(
            rev, requirement_ref="ref", parameter="p",
            comparison_result="WRONG", actor_worker_id=ctx.ogs.id,
        )
        db.flush()
        raised = False
    except IntegrityError:
        raised = True
    finally:
        db.rollback()
    assert raised


def test_applicability_comment_stored(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ECC")
    repo, rev = _evaluation(ctx)
    crit = repo.add_criterion(
        rev, requirement_ref="ref", parameter="p",
        comparison_result="NOT_APPLICABLE", actor_worker_id=ctx.ogs.id,
        applicability_comment="Неприменимо: шов вне области оценки",
    )
    repo.save()
    assert crit.comparison_result == "NOT_APPLICABLE"
    assert crit.applicability_comment == "Неприменимо: шов вне области оценки"


def test_update_criterion(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ECD")
    repo, rev = _evaluation(ctx)
    crit = repo.add_criterion(
        rev, requirement_ref="ref", parameter="p",
        comparison_result="INSUFFICIENT_DATA", actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    repo.update_criterion(
        crit, actor_worker_id=ctx.ogs.id,
        fields={"comparison_result": "COMPLIES", "engineer_comment": "уточнено"},
    )
    repo.save()
    assert crit.comparison_result == "COMPLIES"
    assert crit.engineer_comment == "уточнено"
    ops = [
        e.event_metadata["operation"]
        for e in repo.list_events(rev.evaluation_id)
        if e.event_type == "EVALUATION_UPDATED"
    ]
    assert ops == ["ADD", "UPDATE"]


def test_remove_criterion(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ECE")
    repo, rev = _evaluation(ctx)
    crit = repo.add_criterion(
        rev, requirement_ref="ref", parameter="p",
        comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    repo.remove_criterion(crit, actor_worker_id=ctx.ogs.id)
    repo.save()
    assert repo.list_criteria(rev.id) == []
    ops = [
        e.event_metadata["operation"]
        for e in repo.list_events(rev.evaluation_id)
        if e.event_type == "EVALUATION_UPDATED"
    ]
    assert ops == ["ADD", "REMOVE"]


def test_criterion_blocked_when_not_draft(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ECF")
    repo, rev = _evaluation(ctx)
    rev.status = "FIXED"
    db.flush()
    try:
        repo.add_criterion(
            rev, requirement_ref="ref", parameter="p",
            comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id,
        )
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    finally:
        db.rollback()
    assert code == eew.EVAL_REVISION_NOT_DRAFT
