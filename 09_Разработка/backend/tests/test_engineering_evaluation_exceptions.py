"""Тесты EngineeringException (Task 9D-2C).

Покрывают: add исключения к отклонённому критерию (`DOES_NOT_COMPLY`/
`CONDITIONALLY_COMPLIES`, C15); отказ для `COMPLIES` (`EVAL_EXCEPTION_CRITERION_INVALID`);
дубль (`EVAL_EXCEPTION_DUPLICATE`, C17); критерий не из ревизии
(`EVAL_CRITERION_NOT_FOUND`); запрет вне DRAFT; remove; события `EVALUATION_UPDATED` с
metadata {entity: EngineeringException, operation: ADD|REMOVE}.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_workflow as eew

from .test_engineering_evaluation_core import EvalCtx


def _eval_with_deviated_criterion(ctx: EvalCtx):
    finding = ctx.make_finding()
    repo = ctx.repo()
    _, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    crit = repo.add_criterion(
        rev, requirement_ref="ГОСТ", parameter="p",
        comparison_result="DOES_NOT_COMPLY", actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    return repo, rev, crit


def _add(repo, rev, crit_id, ctx):
    return repo.add_exception(
        rev, criterion_id=crit_id, basis="п.5.2", justification="локальное отступление",
        residual_risk="контролируемый", actor_worker_id=ctx.ogs.id,
    )


def test_add_exception_to_deviated_criterion(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EXA")
    repo, rev, crit = _eval_with_deviated_criterion(ctx)
    exc = _add(repo, rev, crit.id, ctx)
    repo.save()
    assert exc.criterion_id == crit.id
    events = repo.list_events(rev.evaluation_id)
    upd = [e for e in events if e.event_type == "EVALUATION_UPDATED"]
    add_ev = upd[-1]
    assert add_ev.event_metadata["entity"] == "EngineeringException"
    assert add_ev.event_metadata["operation"] == "ADD"
    assert add_ev.event_metadata["exception_id"] == str(exc.id)


def test_add_exception_to_compliant_criterion_rejected(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EXB")
    finding = ctx.make_finding()
    repo = ctx.repo()
    _, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    crit = repo.add_criterion(
        rev, requirement_ref="r", parameter="p",
        comparison_result="COMPLIES", actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    try:
        _add(repo, rev, crit.id, ctx)
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    finally:
        db.rollback()
    assert code == eew.EVAL_EXCEPTION_CRITERION_INVALID


def test_duplicate_exception_rejected(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EXC")
    repo, rev, crit = _eval_with_deviated_criterion(ctx)
    _add(repo, rev, crit.id, ctx)
    repo.save()
    try:
        _add(repo, rev, crit.id, ctx)
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    finally:
        db.rollback()
    assert code == eew.EVAL_EXCEPTION_DUPLICATE


def test_exception_criterion_not_in_revision(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EXD")
    repo, rev, _ = _eval_with_deviated_criterion(ctx)
    try:
        repo.add_exception(
            rev, criterion_id=uuid4(), basis="b", justification="j",
            residual_risk="r", actor_worker_id=ctx.ogs.id,
        )
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    assert code == eew.EVAL_CRITERION_NOT_FOUND


def test_exception_blocked_when_not_draft(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EXE")
    repo, rev, crit = _eval_with_deviated_criterion(ctx)
    rev.status = "PREPARED"
    db.flush()
    try:
        _add(repo, rev, crit.id, ctx)
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    finally:
        db.rollback()
    assert code == eew.EVAL_REVISION_NOT_DRAFT


def test_remove_exception_with_event(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EXF")
    repo, rev, crit = _eval_with_deviated_criterion(ctx)
    exc = _add(repo, rev, crit.id, ctx)
    repo.save()
    repo.remove_exception(exc, actor_worker_id=ctx.ogs.id)
    repo.save()
    assert repo.list_exceptions(rev.id) == []
    ops = [
        e.event_metadata["operation"]
        for e in repo.list_events(rev.evaluation_id)
        if e.event_type == "EVALUATION_UPDATED"
        and e.event_metadata.get("entity") == "EngineeringException"
    ]
    assert ops == ["ADD", "REMOVE"]
