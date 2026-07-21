"""Тесты workflow / policy / audit DefectDisposition (Task 9D-4A-3/9D-4A-4).

Включает исправления Code Review B-01 (ACTIVATE = CHIEF only) и B-02
(SELECT FOR UPDATE / конкурентные переходы), а также supersede workflow (9D-4A-4):
ACTIVE → SUPERSEDED + новая DRAFT, root-level locking, аудит, конкурентность.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import defect_disposition_workflow as ddw
from app.quality.defect_disposition_models import (
    DefectDisposition,
    DefectDispositionEvent,
)
from app.quality.defect_disposition_services import DefectDispositionService
from app.shared.db import SessionLocal
from app.shared.errors import DomainError, RoleDeniedError

from ._defect_support import DefectCtx, make_root

API = "/api/v1/quality/defect-dispositions"


@pytest.fixture
def ctx(db: Session) -> DefectCtx:
    return DefectCtx(db, "Dd")


@pytest.fixture
def root(ctx: DefectCtx):
    joint = ctx.new_joint("J-DD-1")
    evaluation = ctx.new_evaluation(joint)
    return make_root(ctx, joint=joint, evaluation=evaluation, defect_no=1)


def _create_via_api(client: TestClient, ctx: DefectCtx, root_id, **over) -> dict:
    body = {
        "defect_root_id": str(root_id),
        "decision_type": "REPAIR_REQUIRED",
        "justification": "Требуется ремонт по результатам оценки",
    }
    body.update(over)
    r = client.post(API, json=body, headers=ctx.h(ctx.ogs))
    assert r.status_code == 201, r.text
    return r.json()


def _transition(client: TestClient, worker, disposition_id, action, comment=None):
    body = {"action": action}
    if comment is not None:
        body["comment"] = comment
    return client.post(
        f"{API}/{disposition_id}/transition",
        json=body,
        headers=DefectCtx.h(worker),
    )


def _to_approved(client: TestClient, ctx: DefectCtx, root_id) -> str:
    did = _create_via_api(client, ctx, root_id)["id"]
    assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
    assert (
        _transition(client, ctx.otk, did, "APPROVE", "Принято ОТК").status_code
        == 200
    )
    return did


def _to_active(client: TestClient, ctx: DefectCtx, root_id) -> str:
    did = _to_approved(client, ctx, root_id)
    assert (
        _transition(client, ctx.chief, did, "ACTIVATE", "Ввод в действие").status_code
        == 200
    )
    return did


def _supersede(client: TestClient, worker, disposition_id, **over):
    body = {
        "decision_type": "REPAIR_REQUIRED",
        "justification": "Пересмотр решения по новым данным",
        "supersede_reason": "Обнаружены новые обстоятельства",
    }
    body.update(over)
    return client.post(
        f"{API}/{disposition_id}/supersede",
        json=body,
        headers=DefectCtx.h(worker),
    )


# ── Workflow transitions ───────────────────────────────────────────────────────


class TestAllowedTransitions:
    def test_happy_path_draft_to_active(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        data = _create_via_api(client, ctx, root.id)
        did = data["id"]
        assert data["status"] == "DRAFT"

        r = _transition(client, ctx.ogs, did, "PREPARE")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "PREPARED"

        r = _transition(client, ctx.otk, did, "APPROVE", "Принято ОТК")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "APPROVED"
        assert body["approved_by_worker_id"] == ctx.otk.id

        r = _transition(client, ctx.chief, did, "ACTIVATE", "Ввод в действие")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ACTIVE"

    def test_cancel_from_draft(self, client: TestClient, ctx: DefectCtx, root):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = _transition(client, ctx.chief, did, "CANCEL", "Ошибочно создано")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CANCELLED"

    def test_cancel_from_prepared(self, client: TestClient, ctx: DefectCtx, root):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
        r = _transition(client, ctx.chief, did, "CANCEL", "Отмена после подготовки")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CANCELLED"


class TestForbiddenTransitions:
    def test_draft_approve_forbidden(self, client: TestClient, ctx: DefectCtx, root):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = _transition(client, ctx.otk, did, "APPROVE", "рано")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_INVALID_TRANSITION

    def test_draft_to_active_forbidden(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = _transition(client, ctx.chief, did, "ACTIVATE", "рано")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_INVALID_TRANSITION

    def test_prepared_to_active_forbidden(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
        r = _transition(client, ctx.chief, did, "ACTIVATE", "рано")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_INVALID_TRANSITION

    def test_approved_cancel_forbidden(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _to_approved(client, ctx, root.id)
        r = _transition(client, ctx.chief, did, "CANCEL", "после approve")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_INVALID_TRANSITION

    def test_approve_to_draft_not_an_action(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _to_approved(client, ctx, root.id)
        r = client.post(
            f"{API}/{did}/transition",
            json={"action": "PREPARE"},
            headers=ctx.h(ctx.ogs),
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_INVALID_TRANSITION

    def test_unknown_disposition_404(self, client: TestClient, ctx: DefectCtx):
        r = client.get(f"{API}/{uuid4()}", headers=ctx.h(ctx.ogs))
        assert r.status_code == 404, r.text

    def test_invalid_action_422(self, client: TestClient, ctx: DefectCtx, root):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = client.post(
            f"{API}/{did}/transition",
            json={"action": "SUPERSEDE"},
            headers=ctx.h(ctx.chief),
        )
        assert r.status_code == 422, r.text


class TestImmutability:
    def test_active_immutable(self, client: TestClient, ctx: DefectCtx, root):
        did = _to_approved(client, ctx, root.id)
        assert (
            _transition(
                client, ctx.chief, did, "ACTIVATE", "ввод"
            ).status_code
            == 200
        )

        r = _transition(client, ctx.chief, did, "CANCEL", "попытка")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_ACTIVE_IMMUTABLE

        r = _transition(client, ctx.ogs, did, "PREPARE")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_ACTIVE_IMMUTABLE

    def test_cancelled_cannot_restore(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert (
            _transition(
                client, ctx.chief, did, "CANCEL", "отмена"
            ).status_code
            == 200
        )
        r = _transition(client, ctx.ogs, did, "PREPARE")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_CANCELLED_IMMUTABLE


# ── Role policy ────────────────────────────────────────────────────────────────


class TestRolePolicy:
    def test_ogs_can_prepare_not_approve(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
        r = _transition(client, ctx.ogs, did, "APPROVE", "попытка")
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_PERMISSION_DENIED

    def test_otk_can_approve(self, client: TestClient, ctx: DefectCtx, root):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
        r = _transition(client, ctx.otk, did, "APPROVE", "Принято ОТК")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "APPROVED"

    def test_otk_cannot_prepare(self, client: TestClient, ctx: DefectCtx, root):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = _transition(client, ctx.otk, did, "PREPARE")
        assert r.status_code == 403, r.text

    def test_otk_inspector_cannot_activate(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _to_approved(client, ctx, root.id)
        r = _transition(client, ctx.otk, did, "ACTIVATE", "попытка ОТК")
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_PERMISSION_DENIED

    def test_chief_welder_activate_requires_reason(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _to_approved(client, ctx, root.id)
        r = _transition(client, ctx.chief, did, "ACTIVATE")
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_REASON_REQUIRED

    def test_chief_welder_can_activate_with_reason(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _to_approved(client, ctx, root.id)
        r = _transition(client, ctx.chief, did, "ACTIVATE", "Ввод в действие")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ACTIVE"

        events = client.get(f"{API}/{did}/events", headers=ctx.h(ctx.chief)).json()
        activated = [e for e in events if e["event_type"] == ddw.EVENT_ACTIVATED]
        assert len(activated) == 1
        assert activated[0]["actor_role"] == "CHIEF_WELDER"
        assert activated[0]["actor_worker_id"] == ctx.chief.id
        assert activated[0]["reason"] == "Ввод в действие"
        assert activated[0]["previous_status"] == "APPROVED"
        assert activated[0]["new_status"] == "ACTIVE"

    def test_chief_cancel_requires_reason(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = _transition(client, ctx.chief, did, "CANCEL")
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_REASON_REQUIRED

    def test_chief_override_prepare_requires_reason(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        r = _transition(client, ctx.chief, did, "PREPARE")
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_REASON_REQUIRED

        r = _transition(client, ctx.chief, did, "PREPARE", "override главного")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "PREPARED"

    def test_norole_cannot_create(self, client: TestClient, ctx: DefectCtx, root):
        r = client.post(
            API,
            json={
                "defect_root_id": str(root.id),
                "decision_type": "ACCEPT_AS_IS",
                "justification": "без роли",
            },
            headers=ctx.h(ctx.norole),
        )
        assert r.status_code == 403, r.text


# ── Audit ──────────────────────────────────────────────────────────────────────


class TestAudit:
    def test_each_transition_recorded(
        self, client: TestClient, ctx: DefectCtx, root, db: Session
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
        assert (
            _transition(client, ctx.otk, did, "APPROVE", "ok").status_code == 200
        )
        assert (
            _transition(
                client, ctx.chief, did, "ACTIVATE", "ввод"
            ).status_code
            == 200
        )

        r = client.get(f"{API}/{did}/events", headers=ctx.h(ctx.ogs))
        assert r.status_code == 200, r.text
        events = r.json()
        assert [e["event_type"] for e in events] == [
            ddw.EVENT_CREATED,
            ddw.EVENT_PREPARED,
            ddw.EVENT_APPROVED,
            ddw.EVENT_ACTIVATED,
        ]
        assert events[0]["previous_status"] is None
        assert events[0]["new_status"] == "DRAFT"
        assert events[1]["previous_status"] == "DRAFT"
        assert events[1]["new_status"] == "PREPARED"
        assert events[1]["actor_worker_id"] == ctx.ogs.id
        assert events[1]["actor_role"] == "OGS_ENGINEER"
        assert events[2]["actor_role"] == "OTK_INSPECTOR"
        assert events[2]["action"] == "APPROVE"
        assert events[3]["actor_role"] == "CHIEF_WELDER"
        assert events[3]["reason"] == "ввод"

    def test_cancel_audit_has_reason(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        did = _create_via_api(client, ctx, root.id)["id"]
        assert (
            _transition(
                client, ctx.chief, did, "CANCEL", "дубликат"
            ).status_code
            == 200
        )
        events = client.get(f"{API}/{did}/events", headers=ctx.h(ctx.chief)).json()
        cancel = events[-1]
        assert cancel["event_type"] == ddw.EVENT_CANCELLED
        assert cancel["reason"] == "дубликат"
        assert cancel["actor_role"] == "CHIEF_WELDER"

    def test_rollback_keeps_status_and_event_absent(
        self, db: Session, ctx: DefectCtx, root, monkeypatch
    ):
        """Исключение до commit → ни status, ни event не сохраняются."""
        svc = DefectDispositionService(db)
        disp = svc.create(
            defect_root_id=root.id,
            decision_type="REPAIR_REQUIRED",
            justification="rollback case",
            actor_worker_id=ctx.ogs.id,
        )
        disp_id = disp.id
        assert (
            svc.transition(
                disp_id, action="PREPARE", actor_worker_id=ctx.ogs.id
            ).status
            == "PREPARED"
        )

        def boom() -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(svc._repo, "save", boom)
        with pytest.raises(RuntimeError):
            svc.transition(
                disp_id,
                action="APPROVE",
                actor_worker_id=ctx.otk.id,
                comment="ok",
            )
        db.rollback()
        db.expire_all()

        reloaded = db.get(DefectDisposition, disp_id)
        assert reloaded is not None
        assert reloaded.status == "PREPARED"
        events = (
            db.query(DefectDispositionEvent)
            .filter(DefectDispositionEvent.defect_disposition_id == disp_id)
            .all()
        )
        assert [e.event_type for e in events] == [
            ddw.EVENT_CREATED,
            ddw.EVENT_PREPARED,
        ]


# ── Concurrency (PostgreSQL FOR UPDATE) ────────────────────────────────────────


def _run_parallel(fns: list[Callable]) -> list:
    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(fn) for fn in fns]
        return [f.result() for f in futures]


class TestConcurrency:
    def test_concurrent_approve_vs_cancel(self, db: Session):
        """PREPARED → APPROVE и PREPARED → CANCEL параллельно: один побеждает."""
        ctx = DefectCtx(db, "Dc")
        joint = ctx.new_joint("J-DC-1")
        evaluation = ctx.new_evaluation(joint)
        root = make_root(ctx, joint=joint, evaluation=evaluation, defect_no=1)
        svc = DefectDispositionService(db)
        disp = svc.create(
            defect_root_id=root.id,
            decision_type="REPAIR_REQUIRED",
            justification="concurrency",
            actor_worker_id=ctx.ogs.id,
        )
        svc.transition(disp.id, action="PREPARE", actor_worker_id=ctx.ogs.id)
        disp_id = disp.id
        otk_id = ctx.otk.id
        chief_id = ctx.chief.id
        db.commit()

        def approve_worker():
            s = SessionLocal()
            try:
                DefectDispositionService(s).transition(
                    disp_id,
                    action="APPROVE",
                    actor_worker_id=otk_id,
                    comment="approve race",
                )
                return ("ok", "APPROVED")
            except DomainError as exc:
                s.rollback()
                return ("err", exc.code)
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                return ("err", type(exc).__name__)
            finally:
                s.close()

        def cancel_worker():
            s = SessionLocal()
            try:
                DefectDispositionService(s).transition(
                    disp_id,
                    action="CANCEL",
                    actor_worker_id=chief_id,
                    comment="cancel race",
                )
                return ("ok", "CANCELLED")
            except DomainError as exc:
                s.rollback()
                return ("err", exc.code)
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                return ("err", type(exc).__name__)
            finally:
                s.close()

        results = _run_parallel([approve_worker, cancel_worker])
        codes = [r[0] for r in results]
        assert codes.count("ok") == 1, results
        assert codes.count("err") == 1, results
        err_code = [r[1] for r in results if r[0] == "err"][0]
        assert err_code in (
            ddw.DISPOSITION_INVALID_TRANSITION,
            ddw.DISPOSITION_ACTIVE_IMMUTABLE,
            ddw.DISPOSITION_CANCELLED_IMMUTABLE,
        ), results

        db.expire_all()
        from app.quality.defect_disposition_models import DefectDisposition

        final = db.get(DefectDisposition, disp_id)
        assert final is not None
        winner = [r[1] for r in results if r[0] == "ok"][0]
        assert final.status == winner

        events = (
            db.query(DefectDispositionEvent)
            .filter(DefectDispositionEvent.defect_disposition_id == disp_id)
            .order_by(DefectDispositionEvent.created_at)
            .all()
        )
        from_prepared = [
            e for e in events if e.previous_status == ddw.DISPOSITION_PREPARED
        ]
        assert len(from_prepared) == 1, [
            (e.previous_status, e.new_status, e.action) for e in events
        ]


# ── Supersede (Task 9D-4A-4) ────────────────────────────────────────────────────


class TestSupersedeHappyPath:
    def test_active_superseded_creates_new_draft(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)

        r = _supersede(
            client,
            ctx.ogs,
            old_id,
            decision_type="ACCEPT_AS_IS",
            justification="Новая формулировка решения",
            supersede_reason="Уточнение по результатам повторного анализа",
        )
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["status"] == "DRAFT"
        assert new["decision_type"] == "ACCEPT_AS_IS"
        assert new["justification"] == "Новая формулировка решения"
        assert new["supersedes_disposition_id"] == old_id
        assert new["defect_root_id"] == str(root.id)
        assert new["id"] != old_id

        old = client.get(f"{API}/{old_id}", headers=ctx.h(ctx.chief)).json()
        assert old["status"] == "SUPERSEDED"
        assert old["supersede_reason"] == "Уточнение по результатам повторного анализа"

    def test_new_version_can_reach_active(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        new_id = _supersede(client, ctx.chief, old_id, supersede_reason="Причина").json()[
            "id"
        ]

        assert _transition(client, ctx.ogs, new_id, "PREPARE").status_code == 200
        assert (
            _transition(client, ctx.otk, new_id, "APPROVE", "ok").status_code == 200
        )
        r = _transition(client, ctx.chief, new_id, "ACTIVATE", "ввод новой версии")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ACTIVE"


class TestSupersedeForbidden:
    @pytest.mark.parametrize("state", ["draft", "prepared", "approved", "cancelled"])
    def test_only_active_can_be_superseded(
        self, client: TestClient, ctx: DefectCtx, root, state: str
    ):
        if state == "draft":
            did = _create_via_api(client, ctx, root.id)["id"]
        elif state == "prepared":
            did = _create_via_api(client, ctx, root.id)["id"]
            assert _transition(client, ctx.ogs, did, "PREPARE").status_code == 200
        elif state == "approved":
            did = _to_approved(client, ctx, root.id)
        else:
            did = _create_via_api(client, ctx, root.id)["id"]
            assert (
                _transition(client, ctx.chief, did, "CANCEL", "отмена").status_code
                == 200
            )

        r = _supersede(client, ctx.chief, did)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_SUPERSEDE_REQUIRES_ACTIVE

    def test_superseded_cannot_be_superseded_again(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        assert _supersede(client, ctx.chief, old_id).status_code == 200

        r = _supersede(client, ctx.chief, old_id)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_SUPERSEDE_REQUIRES_ACTIVE

    def test_superseded_immutable_via_transition(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        assert _supersede(client, ctx.chief, old_id).status_code == 200

        r = _transition(client, ctx.chief, old_id, "CANCEL", "попытка")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_INVALID_TRANSITION

    def test_unknown_disposition_404(self, client: TestClient, ctx: DefectCtx):
        r = _supersede(client, ctx.chief, uuid4())
        assert r.status_code == 404, r.text


class TestSupersedeRolePolicy:
    def test_otk_inspector_cannot_supersede(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = _supersede(client, ctx.otk, old_id)
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_PERMISSION_DENIED

    def test_ogs_engineer_can_supersede(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = _supersede(client, ctx.ogs, old_id)
        assert r.status_code == 200, r.text

    def test_chief_welder_can_supersede(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = _supersede(client, ctx.chief, old_id)
        assert r.status_code == 200, r.text

    def test_norole_cannot_see_or_supersede(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        """`norole` не имеет даже READ-видимости → 404 раньше проверки роли действия
        (тот же порядок, что в `transition`: скрытый ресурс → 404 до 403)."""
        old_id = _to_active(client, ctx, root.id)
        r = _supersede(client, ctx.norole, old_id)
        assert r.status_code == 404, r.text


class TestSupersedeReasonAndPayload:
    def test_missing_reason_rejected_by_schema(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = client.post(
            f"{API}/{old_id}/supersede",
            json={
                "decision_type": "REPAIR_REQUIRED",
                "justification": "новая версия",
            },
            headers=ctx.h(ctx.chief),
        )
        assert r.status_code == 422, r.text

    def test_blank_reason_rejected_by_service(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = _supersede(client, ctx.chief, old_id, supersede_reason="   ")
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == ddw.DISPOSITION_REASON_REQUIRED

    def test_invalid_decision_type_rejected(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = client.post(
            f"{API}/{old_id}/supersede",
            json={
                "decision_type": "NOT_A_TYPE",
                "justification": "x",
                "supersede_reason": "x",
            },
            headers=ctx.h(ctx.chief),
        )
        assert r.status_code == 422, r.text

    def test_blank_justification_rejected(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = client.post(
            f"{API}/{old_id}/supersede",
            json={
                "decision_type": "REPAIR_REQUIRED",
                "justification": "   ",
                "supersede_reason": "x",
            },
            headers=ctx.h(ctx.chief),
        )
        assert r.status_code == 422, r.text


class TestSupersedeAudit:
    def test_events_recorded_for_old_and_new(
        self, client: TestClient, ctx: DefectCtx, root
    ):
        old_id = _to_active(client, ctx, root.id)
        r = _supersede(
            client,
            ctx.ogs,
            old_id,
            supersede_reason="Причина замещения",
        )
        assert r.status_code == 200, r.text
        new_id = r.json()["id"]

        old_events = client.get(f"{API}/{old_id}/events", headers=ctx.h(ctx.chief)).json()
        superseded = [e for e in old_events if e["event_type"] == ddw.EVENT_SUPERSEDED]
        assert len(superseded) == 1
        ev = superseded[0]
        assert ev["action"] == "SUPERSEDE"
        assert ev["previous_status"] == "ACTIVE"
        assert ev["new_status"] == "SUPERSEDED"
        assert ev["actor_role"] == "OGS_ENGINEER"
        assert ev["actor_worker_id"] == ctx.ogs.id
        assert ev["reason"] == "Причина замещения"

        new_events = client.get(f"{API}/{new_id}/events", headers=ctx.h(ctx.chief)).json()
        assert [e["event_type"] for e in new_events] == [ddw.EVENT_CREATED]
        assert new_events[0]["previous_status"] is None
        assert new_events[0]["new_status"] == "DRAFT"

    def test_rollback_keeps_old_active_and_no_new_row(
        self, db: Session, ctx: DefectCtx, root, monkeypatch
    ):
        svc = DefectDispositionService(db)
        old = svc.create(
            defect_root_id=root.id,
            decision_type="REPAIR_REQUIRED",
            justification="rollback supersede",
            actor_worker_id=ctx.ogs.id,
        )
        svc.transition(old.id, action="PREPARE", actor_worker_id=ctx.ogs.id)
        svc.transition(
            old.id, action="APPROVE", actor_worker_id=ctx.otk.id, comment="ok"
        )
        svc.transition(
            old.id, action="ACTIVATE", actor_worker_id=ctx.chief.id, comment="ввод"
        )
        old_id = old.id

        def boom() -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(svc._repo, "save", boom)
        with pytest.raises(RuntimeError):
            svc.supersede(
                old_id,
                decision_type="ACCEPT_AS_IS",
                justification="новая версия",
                actor_worker_id=ctx.ogs.id,
                reason="причина",
            )
        db.rollback()
        db.expire_all()

        reloaded = db.get(DefectDisposition, old_id)
        assert reloaded is not None
        assert reloaded.status == "ACTIVE"

        siblings = (
            db.query(DefectDisposition)
            .filter(DefectDisposition.defect_root_id == root.id)
            .all()
        )
        assert len(siblings) == 1

        events = (
            db.query(DefectDispositionEvent)
            .filter(DefectDispositionEvent.defect_disposition_id == old_id)
            .all()
        )
        assert [e.event_type for e in events] == [
            ddw.EVENT_CREATED,
            ddw.EVENT_PREPARED,
            ddw.EVENT_APPROVED,
            ddw.EVENT_ACTIVATED,
        ]


class TestSupersedeConcurrency:
    def test_concurrent_supersede_only_one_wins(self, db: Session):
        """Два конкурентных supersede одной ACTIVE-версии: только один создаёт DRAFT."""
        ctx = DefectCtx(db, "Ds")
        joint = ctx.new_joint("J-DS-1")
        evaluation = ctx.new_evaluation(joint)
        root = make_root(ctx, joint=joint, evaluation=evaluation, defect_no=1)
        svc = DefectDispositionService(db)
        disp = svc.create(
            defect_root_id=root.id,
            decision_type="REPAIR_REQUIRED",
            justification="concurrency supersede",
            actor_worker_id=ctx.ogs.id,
        )
        svc.transition(disp.id, action="PREPARE", actor_worker_id=ctx.ogs.id)
        svc.transition(
            disp.id, action="APPROVE", actor_worker_id=ctx.otk.id, comment="ok"
        )
        svc.transition(
            disp.id, action="ACTIVATE", actor_worker_id=ctx.chief.id, comment="ввод"
        )
        old_id = disp.id
        ogs_id = ctx.ogs.id
        chief_id = ctx.chief.id
        db.commit()

        def supersede_worker(actor_worker_id: int, tag: str):
            s = SessionLocal()
            try:
                new = DefectDispositionService(s).supersede(
                    old_id,
                    decision_type="ACCEPT_AS_IS",
                    justification=f"версия от {tag}",
                    actor_worker_id=actor_worker_id,
                    reason=f"race {tag}",
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

        results = _run_parallel(
            [
                lambda: supersede_worker(ogs_id, "A"),
                lambda: supersede_worker(chief_id, "B"),
            ]
        )
        codes = [r[0] for r in results]
        assert codes.count("ok") == 1, results
        assert codes.count("err") == 1, results
        err_code = [r[1] for r in results if r[0] == "err"][0]
        assert err_code == ddw.DISPOSITION_SUPERSEDE_REQUIRES_ACTIVE, results

        db.expire_all()
        old = db.get(DefectDisposition, old_id)
        assert old is not None
        assert old.status == "SUPERSEDED"

        siblings = (
            db.query(DefectDisposition)
            .filter(DefectDisposition.defect_root_id == root.id)
            .all()
        )
        assert len(siblings) == 2, siblings

        new_rows = [d for d in siblings if d.id != old_id]
        assert len(new_rows) == 1
        assert new_rows[0].status == "DRAFT"
        assert new_rows[0].supersedes_disposition_id == old_id

        events = (
            db.query(DefectDispositionEvent)
            .filter(DefectDispositionEvent.defect_disposition_id == old_id)
            .all()
        )
        superseded_events = [
            e for e in events if e.event_type == ddw.EVENT_SUPERSEDED
        ]
        assert len(superseded_events) == 1, superseded_events


# ── Pure workflow unit ─────────────────────────────────────────────────────────


class TestWorkflowPure:
    def test_allowed_matrix(self):
        assert ddw.can_transition("DRAFT", "PREPARED")
        assert ddw.can_transition("DRAFT", "CANCELLED")
        assert ddw.can_transition("PREPARED", "APPROVED")
        assert ddw.can_transition("PREPARED", "CANCELLED")
        assert ddw.can_transition("APPROVED", "ACTIVE")
        assert not ddw.can_transition("DRAFT", "ACTIVE")
        assert not ddw.can_transition("PREPARED", "ACTIVE")
        assert not ddw.can_transition("APPROVED", "DRAFT")
        assert not ddw.can_transition("APPROVED", "CANCELLED")
        assert not ddw.can_transition("ACTIVE", "CANCELLED")
        assert not ddw.can_transition("CANCELLED", "DRAFT")
        # ACTIVE → SUPERSEDED существует в таблице переходов (9D-4A-4), но выполняется
        # только отдельной командой SUPERSEDE, а не общим /transition (см. TestSupersede).
        assert ddw.can_transition("ACTIVE", "SUPERSEDED")
        assert ddw.ROLE_OTK_INSPECTOR not in ddw.DISPOSITION_ACTIVATE_ROLES
        assert ddw.DISPOSITION_ACTIVATE_ROLES == frozenset({ddw.ROLE_CHIEF_WELDER})

    def test_service_bypass_forbidden(
        self, db: Session, ctx: DefectCtx, root
    ):
        """Статус меняется только через transition — прямого set в сервисе нет."""
        svc = DefectDispositionService(db)
        disp = svc.create(
            defect_root_id=root.id,
            decision_type="REPAIR_REQUIRED",
            justification="сервисный create",
            actor_worker_id=ctx.ogs.id,
        )
        with pytest.raises(RoleDeniedError):
            svc.transition(
                disp.id,
                action="ACTIVATE",
                actor_worker_id=ctx.otk.id,
                comment="x",
            )

        with pytest.raises(RoleDeniedError):
            svc.transition(
                disp.id, action="APPROVE", actor_worker_id=ctx.ogs.id, comment="x"
            )

        with pytest.raises(DomainError) as exc:
            svc.transition(
                disp.id,
                action="ACTIVATE",
                actor_worker_id=ctx.chief.id,
                comment="рано",
            )
        assert exc.value.code == ddw.DISPOSITION_INVALID_TRANSITION
