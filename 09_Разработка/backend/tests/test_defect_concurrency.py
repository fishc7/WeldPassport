"""Конкурентные тесты технической модели Defect (Task 9D-3B; Spec §26).

Реальная PostgreSQL-конкурентность: каждый поток — своя сессия и транзакция.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.quality import defect_workflow as dw
from app.quality.defect_models import Defect, DefectRoot
from app.quality.defect_services import DefectService
from app.shared.db import SessionLocal
from app.shared.errors import DomainError

from ._defect_support import DefectCtx, valid_active_fields


def _run_parallel(fns: list[Callable]) -> list:
    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(fn) for fn in fns]
        return [f.result() for f in futures]


def _create_active_worker(joint_id: UUID, evaluation_id: UUID, actor_id: int, fields: dict):
    def run():
        s = SessionLocal()
        try:
            d = DefectService(s).create_active(
                joint_id=joint_id, engineering_evaluation_id=evaluation_id,
                actor_worker_id=actor_id, fields=dict(fields),
            )
            root = s.get(DefectRoot, d.defect_root_id)
            return ("ok", root.defect_no)
        except DomainError as exc:
            s.rollback()
            return ("err", exc.code)
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            return ("err", type(exc).__name__)
        finally:
            s.close()

    return run


# ── 1. Два параллельных create для одной evaluation ────────────────────────────


def test_concurrent_double_create_same_evaluation(db: Session):
    ctx = DefectCtx(db, "CC1")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_confirmed_evaluation(joint)
    fields = valid_active_fields(db)
    db.commit()

    worker = _create_active_worker(joint.id, ev.id, ctx.ogs.id, fields)
    results = _run_parallel([worker, worker])
    codes = [r[0] for r in results]
    assert codes.count("ok") == 1, results
    assert codes.count("err") == 1, results
    err_code = [r[1] for r in results if r[0] == "err"][0]
    assert err_code == dw.DEFECT_ALREADY_EXISTS_FOR_EVALUATION

    db.expire_all()
    roots = db.query(DefectRoot).filter(
        DefectRoot.engineering_evaluation_id == ev.id
    ).all()
    assert len(roots) == 1
    # event count = число успешных команд (одна активация).
    from app.quality.defect_models import DefectEvent

    events = db.query(DefectEvent).filter(
        DefectEvent.defect_root_id == roots[0].id
    ).all()
    assert len(events) == 1 and events[0].event_type == "DEFECT_ACTIVATED"


# ── 2. Два параллельных supersede одной ACTIVE ─────────────────────────────────


def test_concurrent_double_supersede(db: Session):
    ctx = DefectCtx(db, "CC2")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_confirmed_evaluation(joint)
    d1 = DefectService(db).create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    root_id = d1.defect_root_id
    d1_id, d1_version = d1.id, d1.version
    db.commit()

    def worker():
        s = SessionLocal()
        try:
            new = DefectService(s).supersede(
                d1_id, expected_version=d1_version, actor_worker_id=ctx.ogs.id,
                fields={"technical_note": "уточнение"},
            )
            return ("ok", str(new.id))
        except DomainError as exc:
            s.rollback()
            return ("err", exc.code)
        except Exception as exc:  # noqa: BLE001
            s.rollback()
            return ("err", type(exc).__name__)
        finally:
            s.close()

    results = _run_parallel([worker, worker])
    codes = [r[0] for r in results]
    assert codes.count("ok") == 1, results
    assert codes.count("err") == 1, results

    db.expire_all()
    # Двухшаговый supersede (supersede-time): одна команда создаёт новую DRAFT и гасит
    # старую ACTIVE → SUPERSEDED; после команды в цепочке ноль ACTIVE и ровно одна DRAFT.
    active = db.query(Defect).filter(
        Defect.defect_root_id == root_id, Defect.status == dw.DEFECT_ACTIVE
    ).all()
    assert len(active) == 0, active  # действующей ACTIVE в цепочке нет
    drafts = db.query(Defect).filter(
        Defect.defect_root_id == root_id, Defect.status == dw.DEFECT_DRAFT
    ).all()
    assert len(drafts) == 1  # ровно одна открытая DRAFT (вторая команда отклонена)
    revs = [
        r.revision_no
        for r in db.query(Defect).filter(Defect.defect_root_id == root_id).all()
    ]
    assert len(revs) == len(set(revs))  # revision_no не дублируется


# ── 3. Параллельные create разных evaluation одного Joint ──────────────────────


def test_concurrent_create_different_evaluations_same_joint(db: Session):
    ctx = DefectCtx(db, "CC3")
    joint = ctx.new_joint("J-1")
    ev1 = ctx.new_confirmed_evaluation(joint)
    ev2 = ctx.new_confirmed_evaluation(joint)
    fields = valid_active_fields(db)
    db.commit()

    w1 = _create_active_worker(joint.id, ev1.id, ctx.ogs.id, fields)
    w2 = _create_active_worker(joint.id, ev2.id, ctx.ogs.id, fields)
    results = _run_parallel([w1, w2])
    assert all(r[0] == "ok" for r in results), results
    numbers = sorted(r[1] for r in results)
    assert numbers == [1, 2]  # независимые defect_no


# ── 4. activate vs cancel одного DRAFT ─────────────────────────────────────────


def test_concurrent_activate_vs_cancel_same_draft(db: Session):
    ctx = DefectCtx(db, "CC4")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_confirmed_evaluation(joint)
    draft = DefectService(db).create_draft(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    d_id, d_version = draft.id, draft.version
    db.commit()

    def activate_worker():
        s = SessionLocal()
        try:
            DefectService(s).activate(d_id, expected_version=d_version, actor_worker_id=ctx.ogs.id)
            return ("ok", "activate")
        except DomainError as exc:
            s.rollback()
            return ("err", exc.code)
        finally:
            s.close()

    def cancel_worker():
        s = SessionLocal()
        try:
            DefectService(s).cancel(d_id, expected_version=d_version, actor_worker_id=ctx.ogs.id, reason="конкурентная отмена")
            return ("ok", "cancel")
        except DomainError as exc:
            s.rollback()
            return ("err", exc.code)
        finally:
            s.close()

    results = _run_parallel([activate_worker, cancel_worker])
    codes = [r[0] for r in results]
    assert codes.count("ok") == 1, results  # только одна команда успешна

    db.expire_all()
    final = db.get(Defect, d_id)
    assert final.status in (dw.DEFECT_ACTIVE, dw.DEFECT_CANCELLED)  # состояние консистентно
