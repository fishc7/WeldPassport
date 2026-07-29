"""Тесты вычисления готовности Joint к контролю (Task 9A, §12).

Проверяют стабильные машинные коды блокирующих причин и предупреждений, а также
что endpoint readiness ничего не изменяет и пересчитывается заново (не читает
сохранённый флаг). Использует общий контекст InsCtx из test_inspections_api.
"""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering.models import Joint, WeldOperation
from app.quality.models import Inspection

from .test_inspections_api import API, InsCtx


def _readiness(ctx: InsCtx, client: TestClient, joint_id: str, worker=None):
    r = client.get(
        f"{API}/joints/{joint_id}/inspection-readiness",
        headers=ctx.h(worker or ctx.ogs),
    )
    return r


def _ctx(db: Session) -> InsCtx:
    return InsCtx(db, "RD500")


def test_blocking_joint_not_active(db: Session, client: TestClient) -> None:
    ctx = _ctx(db)
    joint_id = ctx.create_joint(client, "J-1")
    ctx.complete_weld_op(client, joint_id)  # но не активируем
    r = _readiness(ctx, client, joint_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready_for_inspection"] is False
    codes = [b["code"] for b in body["blocking_reasons"]]
    assert "JOINT_NOT_ACTIVE" in codes


def test_blocking_no_completed_weld_operation(
    db: Session, client: TestClient
) -> None:
    ctx = _ctx(db)
    joint_id = ctx.create_joint(client, "J-1")
    ctx.activate(joint_id)
    body = _readiness(ctx, client, joint_id).json()
    codes = [b["code"] for b in body["blocking_reasons"]]
    assert "NO_COMPLETED_WELD_OPERATION" in codes
    assert body["weld_operation_id"] is None


def test_blocking_weld_operation_not_current(
    db: Session, client: TestClient
) -> None:
    ctx = _ctx(db)
    joint_id = ctx.ready_joint(client, "J-1")
    op = db.query(WeldOperation).filter(
        WeldOperation.joint_id == UUID(joint_id)
    ).first()
    op.lifecycle_status = "SUPERSEDED"
    db.commit()
    body = _readiness(ctx, client, joint_id).json()
    codes = [b["code"] for b in body["blocking_reasons"]]
    assert "WELD_OPERATION_NOT_CURRENT" in codes


def test_blocking_required_heat_treatment(db: Session, client: TestClient) -> None:
    ctx = _ctx(db)
    joint_id = ctx.ready_joint(client, "J-1")
    joint = db.query(Joint).filter(Joint.id == UUID(joint_id)).first()
    joint.heat_treatment_required = True
    db.commit()
    body = _readiness(ctx, client, joint_id).json()
    codes = [b["code"] for b in body["blocking_reasons"]]
    assert "HEAT_TREATMENT_NOT_ACCEPTED" in codes


def test_ready_success(db: Session, client: TestClient) -> None:
    ctx = _ctx(db)
    joint_id = ctx.ready_joint(client, "J-1")
    body = _readiness(ctx, client, joint_id).json()
    assert body["ready_for_inspection"] is True
    assert body["blocking_reasons"] == []
    assert body["weld_operation_id"] is not None


def test_other_inspection_is_warning_not_blocker(
    db: Session, client: TestClient
) -> None:
    ctx = _ctx(db)
    joint_id = ctx.ready_joint(client, "J-1")
    ctx.draft(client, ctx.ogs, joint_id)
    body = _readiness(ctx, client, joint_id).json()
    assert body["ready_for_inspection"] is True
    warning_codes = [w["code"] for w in body["warnings"]]
    assert "OTHER_ACTIVE_INSPECTION_EXISTS" in warning_codes


def test_readiness_endpoint_is_read_only(db: Session, client: TestClient) -> None:
    ctx = _ctx(db)
    joint_id = ctx.ready_joint(client, "J-1")
    before = db.query(Inspection).count()
    _readiness(ctx, client, joint_id)
    _readiness(ctx, client, joint_id)
    assert db.query(Inspection).count() == before


def test_readiness_recomputed_not_cached(db: Session, client: TestClient) -> None:
    ctx = _ctx(db)
    joint_id = ctx.ready_joint(client, "J-1")
    assert _readiness(ctx, client, joint_id).json()["ready_for_inspection"] is True
    op = db.query(WeldOperation).filter(
        WeldOperation.joint_id == UUID(joint_id)
    ).first()
    op.lifecycle_status = "SUPERSEDED"
    db.commit()
    body = _readiness(ctx, client, joint_id).json()
    assert body["ready_for_inspection"] is False
