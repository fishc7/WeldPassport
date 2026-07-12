"""Интеграционные тесты полной переварки WeldOperation (Task 8D, §16, §21.7).

Переварка — новая операция (operation_kind=REWELD), а не редактирование старой и не
локальный ремонт. Черновик нельзя завершить без решения ОГС APPROVE; успешное
завершение атомарно переводит исходную операцию в SUPERSEDED."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.engineering.models import WeldOperation

from .test_weld_operation_corrections import Ctx, ENGINEERING_URL, _get_op, _role_worker


def _reweld(client, ctx: Ctx, op: dict, worker=None, **body):
    payload = {
        "reason": "WRONG_WPS",
        "comment": "Требуется полная переварка соединения",
        "expected_source_record_version": op["record_version"],
    }
    payload.update(body)
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/reweld",
        json=payload, headers=ctx.headers(worker or ctx.master),
    )


def _decision(client, ctx: Ctx, reweld_id, worker=None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{reweld_id}/reweld-decision",
        json=body, headers=ctx.headers(worker or ctx.ogs),
    )


def _complete(client, ctx: Ctx, op_id, worker=None):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/complete", json={},
        headers=ctx.headers(worker or ctx.master),
    )


def test_master_creates_reweld_draft(client, db):
    ctx = Ctx(db, "R01")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _reweld(client, ctx, op, patch={"welding_method": "MMA"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["operation_kind"] == "REWELD"
    assert body["supersedes_operation_id"] == op["id"]
    assert body["reweld_reason"] == "WRONG_WPS"
    assert body["lifecycle_status"] == "DRAFT"
    # Исходная операция ещё действующая.
    assert _get_op(client, ctx, op["id"])["lifecycle_status"] == "COMPLETED"


def test_reweld_reason_required(client, db):
    ctx = Ctx(db, "R02")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/reweld",
        json={"comment": "x", "expected_source_record_version": op["record_version"]},
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 422


def test_reweld_comment_required(client, db):
    ctx = Ctx(db, "R03")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _reweld(client, ctx, op, comment="   ")
    assert resp.status_code == 422


def test_reweld_self_reference_forbidden_by_db(client, db):
    ctx = Ctx(db, "R04")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    row = db.query(WeldOperation).filter(
        WeldOperation.id == op["id"]
    ).one()
    row.supersedes_operation_id = row.id
    raised = False
    try:
        db.commit()
    except IntegrityError:
        raised = True
        db.rollback()
    assert raised


def test_reweld_foreign_scope_denied(client, db):
    ctx = Ctx(db, "R05")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    other = _role_worker(db, "R05Other", "MASTER",
                         scope_type="PROJECT", scope_id=str(uuid4()))
    resp = _reweld(client, ctx, op, worker=other)
    assert resp.status_code == 403


def test_reweld_cannot_complete_without_ogs(client, db):
    ctx = Ctx(db, "R06")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    reweld = _reweld(client, ctx, op, patch={"welding_method": "MMA"}).json()
    resp = _complete(client, ctx, reweld["id"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "REWELD_DECISION_REQUIRED"


def test_ogs_rejects_reweld_cancels_draft(client, db):
    ctx = Ctx(db, "R07")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    reweld = _reweld(client, ctx, op).json()
    resp = _decision(client, ctx, reweld["id"], decision="REJECT",
                     comment="переварка не нужна")
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "CANCELLED"
    # Исходная операция не изменилась.
    assert _get_op(client, ctx, op["id"])["lifecycle_status"] == "COMPLETED"


def test_ogs_approves_and_completion_supersedes_source(client, db):
    ctx = Ctx(db, "R08")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    reweld = _reweld(client, ctx, op, patch={"welding_method": "MMA"}).json()
    resp = _decision(client, ctx, reweld["id"], decision="APPROVE",
                     comment="переварка разрешена")
    assert resp.status_code == 200, resp.text
    approved = resp.json()
    assert approved["reweld_decided_by"] == ctx.ogs.id
    assert approved["lifecycle_status"] == "DRAFT"
    # Теперь завершение допустимо и атомарно supersede исходную операцию.
    resp = _complete(client, ctx, reweld["id"])
    assert resp.status_code == 200, resp.text
    done = resp.json()
    assert done["lifecycle_status"] == "COMPLETED"
    assert done["supersedes_operation_id"] == op["id"]
    src = _get_op(client, ctx, op["id"])
    assert src["lifecycle_status"] == "SUPERSEDED"
    assert src["superseded_by_operation_id"] == reweld["id"]


def test_reweld_chief_welder_can_decide(client, db):
    ctx = Ctx(db, "R09")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    reweld = _reweld(client, ctx, op).json()
    resp = _decision(client, ctx, reweld["id"], worker=ctx.chief,
                     decision="APPROVE", comment="ок")
    assert resp.status_code == 200
    assert resp.json()["reweld_decided_by"] == ctx.chief.id
