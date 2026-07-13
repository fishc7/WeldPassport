"""Интеграционные и модульные тесты термической обработки (Task 8F, ADR-014).

Покрывают: создание/состав цикла, жизненный цикл DRAFT→…→CLOSED и недопустимые
переходы, снимок и применимость технологической карты, фактические параметры и
автоматическую проверку, документы, права и решение ОГС (общий цикл и по стыку),
повторную термообработку, интеграцию с Joint и журнал. Импорт Task 8E,
корректировки Task 8D и контур контроля качества здесь не моделируются.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering import heat_treatment_workflow as htw
from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    Joint,
)
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project

from .conftest import TEST_COMPANY_ID

URL = "/api/v1/engineering"
TODAY = date.today()
NOW = datetime.now(timezone.utc).isoformat()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"HT{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=TODAY,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _role_worker(db: Session, suffix: str, role_code: str, **scope) -> Worker:
    w = _worker(db, suffix)
    role = WorkerRole(
        worker_id=w.id,
        role_code=role_code,
        scope_type=scope.get("scope_type", "GLOBAL"),
        scope_id=scope.get("scope_id"),
        is_active=True,
        valid_from=TODAY,
    )
    db.add(role)
    db.commit()
    return w


class HtCtx:
    def __init__(self, db: Session, code: str) -> None:
        self.db = db
        self.creator = _worker(db, f"{code}Cr")
        self.project = Project(
            code=code, name=f"Проект {code}", status="active",
            created_by=self.creator.id,
        )
        db.add(self.project)
        db.commit()
        db.refresh(self.project)
        self.line = Line(
            project_id=self.project.id, line_no=f"L-{code}", status="active",
            required_inspection_types=[], created_by=self.creator.id,
        )
        db.add(self.line)
        db.commit()
        db.refresh(self.line)
        self.document = EngineeringDocument(
            project_id=self.project.id, line_id=self.line.id,
            document_no=f"DOC-{code}", document_type="ISOMETRIC",
            status="APPROVED", created_by=self.creator.id,
        )
        db.add(self.document)
        db.commit()
        db.refresh(self.document)
        self.revision = DocumentRevision(
            engineering_document_id=self.document.id, revision_code="R0",
            status="APPROVED", created_by=self.creator.id,
        )
        db.add(self.revision)
        db.commit()
        db.refresh(self.revision)
        self.master = _role_worker(db, f"{code}M", "MASTER")
        self.ogs = _role_worker(db, f"{code}O", "OGS_ENGINEER")
        self.chief = _role_worker(db, f"{code}C", "CHIEF_WELDER")
        self.otk = _role_worker(db, f"{code}K", "OTK_INSPECTOR")
        self.pto = _role_worker(db, f"{code}P", "PTO_ENGINEER")
        # Профиль сварщика для завершения WeldOperation.
        from app.welding.models import Welder

        welder_worker = _worker(db, f"{code}Wk")
        self.welder = Welder(
            worker_id=welder_worker.id, stamp_code=f"ST-{code}", status="active"
        )
        db.add(self.welder)
        db.commit()
        db.refresh(self.welder)

    def h(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    # -- Joint --
    def create_joint(
        self, client: TestClient, joint_no: str, *, heat_treatment_required=False
    ) -> str:
        payload = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": joint_no,
            "created_by": self.creator.id,
        }
        resp = client.post(
            f"{URL}/joints", json=payload, headers=self.h(self.pto)
        )
        assert resp.status_code == 201, resp.text
        joint_id = resp.json()["id"]
        if heat_treatment_required:
            joint = self.db.query(Joint).filter(Joint.id == joint_id).first()
            joint.heat_treatment_required = True
            self.db.commit()
        return joint_id

    def create_completed_weld_op(self, client: TestClient, joint_id: str) -> str:
        payload = {
            "joint_id": joint_id,
            "responsible_worker_id": self.master.id,
            "actual_welder_id": str(self.welder.id),
            "entered_stamp_code": self.welder.stamp_code,
            "weld_stage": "ROOT",
            "welding_method": "RAD",
            "performed_on": TODAY.isoformat(),
        }
        r = client.post(
            f"{URL}/weld-operations", json=payload, headers=self.h(self.master)
        )
        assert r.status_code == 201, r.text
        op_id = r.json()["id"]
        rc = client.post(
            f"{URL}/weld-operations/{op_id}/complete", json={},
            headers=self.h(self.master),
        )
        assert rc.status_code == 200, rc.text
        return op_id

    # -- Procedure --
    def approved_procedure(self, client: TestClient, code="P1", **fields) -> str:
        payload = {
            "project_id": str(self.project.id),
            "procedure_no": f"HT-{code}",
            "revision_no": "1",
            "min_temperature": "600",
            "max_temperature": "700",
            "soak_duration_minutes": 60,
            "max_heating_rate": "100",
            "max_cooling_rate": "100",
        }
        payload.update(fields)
        r = client.post(
            f"{URL}/heat-treatment-procedures", json=payload,
            headers=self.h(self.master),
        )
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        ra = client.post(
            f"{URL}/heat-treatment-procedures/{rid}/approve",
            headers=self.h(self.ogs),
        )
        assert ra.status_code == 200, ra.text
        return rid

    # -- Batch --
    def create_batch(
        self, client: TestClient, batch_no="B-1", procedure_id=None, **fields
    ) -> str:
        payload = {
            "project_id": str(self.project.id),
            "batch_no": batch_no,
            "procedure_revision_id": procedure_id,
            "planned_start_at": NOW,
            "operator_worker_id": self.master.id,
        }
        payload.update(fields)
        r = client.post(
            f"{URL}/heat-treatment-batches", json=payload, headers=self.h(self.master)
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def add_op(self, client: TestClient, batch_id, joint_id, **fields):
        payload = {"joint_id": joint_id}
        payload.update(fields)
        return client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/operations",
            json=payload, headers=self.h(self.master),
        )

    def set_actuals(self, client, batch_id, **overrides):
        body = {
            "actual_soak_temperature": "650",
            "actual_soak_duration_minutes": 70,
            "actual_heating_rate": "80",
            "actual_cooling_rate": "80",
        }
        body.update(overrides)
        return client.patch(
            f"{URL}/heat-treatment-batches/{batch_id}", json=body,
            headers=self.h(self.master),
        )

    def upload_chart(self, client, batch_id, verify=False):
        r = client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/records",
            json={"record_type": "TEMPERATURE_CHART", "document_no": "TC-1"},
            headers=self.h(self.master),
        )
        assert r.status_code == 201, r.text
        rec_id = r.json()["id"]
        if verify:
            rv = client.post(
                f"{URL}/heat-treatment-records/{rec_id}/verify",
                headers=self.h(self.ogs),
            )
            assert rv.status_code == 200, rv.text
        return rec_id

    def plan(self, client, batch_id):
        return client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/plan", json={},
            headers=self.h(self.master),
        )

    def start(self, client, batch_id):
        return client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/start",
            json={"actual_started_at": NOW}, headers=self.h(self.master),
        )

    def complete(self, client, batch_id):
        return client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/complete",
            json={"actual_completed_at": NOW}, headers=self.h(self.master),
        )

    def review(self, client, batch_id, result="ACCEPTED", worker=None, comment=None):
        body = {"result": result}
        if comment is not None:
            body["comment"] = comment
        return client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/review", json=body,
            headers=self.h(worker or self.ogs),
        )

    def evaluate(self, client, op_id, result="ACCEPTED",
                 evidence="SUFFICIENT", comment=None, worker=None):
        body = {"result": result, "evidence_sufficiency": evidence}
        if comment is not None:
            body["result_comment"] = comment
        return client.post(
            f"{URL}/heat-treatment-operations/{op_id}/evaluate", json=body,
            headers=self.h(worker or self.ogs),
        )

    def close(self, client, batch_id):
        return client.post(
            f"{URL}/heat-treatment-batches/{batch_id}/close", json={},
            headers=self.h(self.master),
        )


def _op_id(resp) -> str:
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ══ 1. Создание ═══════════════════════════════════════════════════════════════


def test_create_draft_batch(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CR1")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    r = client.get(f"{URL}/heat-treatment-batches/{batch_id}", headers=ctx.h(ctx.master))
    assert r.status_code == 200
    assert r.json()["status"] == "DRAFT"
    assert r.json()["version"] == 1


def test_procedure_required_before_plan(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CR2")
    batch_id = ctx.create_batch(client, procedure_id=None)
    joint = ctx.create_joint(client, "J1")
    _op_id(ctx.add_op(client, batch_id, joint))
    r = ctx.plan(client, batch_id)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_PROCEDURE_REQUIRED


def test_duplicate_batch_no_in_project(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CR3")
    ctx.create_batch(client, batch_no="DUP")
    payload = {
        "project_id": str(ctx.project.id),
        "batch_no": "DUP",
        "planned_start_at": NOW,
    }
    r = client.post(
        f"{URL}/heat-treatment-batches", json=payload, headers=ctx.h(ctx.master)
    )
    assert r.status_code == 409


def test_create_batch_scope_denied(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CR4")
    payload = {
        "project_id": str(ctx.project.id),
        "batch_no": "B-DENY",
        "planned_start_at": NOW,
    }
    r = client.post(
        f"{URL}/heat-treatment-batches", json=payload, headers=ctx.h(ctx.pto)
    )
    assert r.status_code == 403


# ══ 2. Состав цикла ═══════════════════════════════════════════════════════════


def test_add_multiple_joints(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CO1")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    j1 = ctx.create_joint(client, "J1")
    j2 = ctx.create_joint(client, "J2")
    assert ctx.add_op(client, batch_id, j1).status_code == 201
    assert ctx.add_op(client, batch_id, j2).status_code == 201
    r = client.get(
        f"{URL}/heat-treatment-batches/{batch_id}/operations", headers=ctx.h(ctx.master)
    )
    assert len(r.json()) == 2


def test_duplicate_joint_rejected(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CO2")
    batch_id = ctx.create_batch(client)
    j1 = ctx.create_joint(client, "J1")
    assert ctx.add_op(client, batch_id, j1).status_code == 201
    r = ctx.add_op(client, batch_id, j1)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == htw.HT_DUPLICATE_JOINT


def test_joint_other_project_rejected(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CO3")
    other = HtCtx(db, "CO3B")
    batch_id = ctx.create_batch(client)
    foreign_joint = other.create_joint(client, "JX")
    r = ctx.add_op(client, batch_id, foreign_joint)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_PROJECT_SCOPE_VIOLATION


def test_weld_operation_link_wrong_joint(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CO4")
    batch_id = ctx.create_batch(client)
    j1 = ctx.create_joint(client, "J1")
    j2 = ctx.create_joint(client, "J2")
    weld_op = ctx.create_completed_weld_op(client, j2)
    r = ctx.add_op(client, batch_id, j1, weld_operation_id=weld_op)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_WELD_OPERATION_MISMATCH


def test_composition_locked_after_start(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CO5")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    j1 = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, j1)
    assert ctx.plan(client, batch_id).status_code == 200
    assert ctx.start(client, batch_id).status_code == 200
    j2 = ctx.create_joint(client, "J2")
    r = ctx.add_op(client, batch_id, j2)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == htw.HT_COMPOSITION_LOCKED


def test_exclude_after_start(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "CO6")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    j1 = ctx.create_joint(client, "J1")
    j2 = ctx.create_joint(client, "J2")
    op1 = _op_id(ctx.add_op(client, batch_id, j1))
    ctx.add_op(client, batch_id, j2)
    ctx.plan(client, batch_id)
    ctx.start(client, batch_id)
    r = client.post(
        f"{URL}/heat-treatment-operations/{op1}/exclude",
        json={"reason": "стык снят с нагрева"}, headers=ctx.h(ctx.master),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EXCLUDED"


# ══ 3. Workflow ═══════════════════════════════════════════════════════════════


def _full_to_completed(ctx: HtCtx, client: TestClient, code: str):
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1", heat_treatment_required=True)
    weld_op = ctx.create_completed_weld_op(client, joint)
    op = _op_id(ctx.add_op(client, batch_id, joint, weld_operation_id=weld_op))
    assert ctx.plan(client, batch_id).status_code == 200
    assert ctx.start(client, batch_id).status_code == 200
    ctx.upload_chart(client, batch_id, verify=False)
    ctx.set_actuals(client, batch_id)
    assert ctx.complete(client, batch_id).status_code == 200
    return batch_id, op, joint


def test_full_happy_path(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "WF1")
    batch_id, op, joint = _full_to_completed(ctx, client, "WF1")
    # verify chart, evaluate operation, review, close.
    ctx.upload_chart(client, batch_id, verify=True)
    assert ctx.evaluate(client, op, result="ACCEPTED").status_code == 200
    rr = ctx.review(client, batch_id, result="ACCEPTED")
    assert rr.status_code == 200, rr.text
    assert rr.json()["status"] == "REVIEWED"
    assert rr.json()["review_result"] == "ACCEPTED"
    rc = ctx.close(client, batch_id)
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "CLOSED"


def test_invalid_transition_draft_to_completed(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "WF2")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    r = ctx.complete(client, batch_id)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == htw.HT_INVALID_TRANSITION


def test_cancel_draft(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "WF3")
    batch_id = ctx.create_batch(client)
    r = client.post(
        f"{URL}/heat-treatment-batches/{batch_id}/cancel",
        json={"reason": "ошибочный цикл"}, headers=ctx.h(ctx.master),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"


def test_reject_after_completed(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "WF4")
    batch_id, op, joint = _full_to_completed(ctx, client, "WF4")
    r = ctx.review(client, batch_id, result="REJECTED", comment="режим нарушен")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED"
    assert r.json()["review_result"] == "REJECTED"


def test_reject_requires_comment(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "WF5")
    batch_id, op, joint = _full_to_completed(ctx, client, "WF5")
    r = ctx.review(client, batch_id, result="REJECTED")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_JUSTIFICATION_REQUIRED


def test_closed_batch_immutable(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "WF6")
    batch_id, op, joint = _full_to_completed(ctx, client, "WF6")
    ctx.upload_chart(client, batch_id, verify=True)
    ctx.evaluate(client, op, result="ACCEPTED")
    ctx.review(client, batch_id, result="ACCEPTED")
    ctx.close(client, batch_id)
    r = client.patch(
        f"{URL}/heat-treatment-batches/{batch_id}",
        json={"equipment_text": "x"}, headers=ctx.h(ctx.master),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == htw.HT_BATCH_LOCKED


# ══ 4. Карта ══════════════════════════════════════════════════════════════════


def test_only_approved_procedure_allowed(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "PR1")
    # DRAFT-редакция (не утверждена).
    r = client.post(
        f"{URL}/heat-treatment-procedures",
        json={
            "project_id": str(ctx.project.id),
            "procedure_no": "HT-DRAFT", "revision_no": "1",
        },
        headers=ctx.h(ctx.master),
    )
    proc_id = r.json()["id"]
    batch_id = ctx.create_batch(client, procedure_id=proc_id)
    joint = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, joint)
    rp = ctx.plan(client, batch_id)
    assert rp.status_code == 409
    assert rp.json()["detail"]["code"] == htw.HT_PROCEDURE_NOT_APPROVED


def test_snapshot_created_on_start(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "PR2")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, joint)
    ctx.plan(client, batch_id)
    ctx.start(client, batch_id)
    r = client.get(f"{URL}/heat-treatment-batches/{batch_id}", headers=ctx.h(ctx.master))
    snap = r.json()["procedure_snapshot"]
    assert snap is not None
    assert snap["min_temperature"] == "600"
    assert snap["soak_duration_minutes"] == 60


def test_procedure_change_after_start_forbidden(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "PR3")
    proc = ctx.approved_procedure(client)
    proc2 = ctx.approved_procedure(client, code="P2")
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, joint)
    ctx.plan(client, batch_id)
    ctx.start(client, batch_id)
    r = client.patch(
        f"{URL}/heat-treatment-batches/{batch_id}",
        json={"procedure_revision_id": proc2}, headers=ctx.h(ctx.master),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == htw.HT_BATCH_LOCKED


def test_inapplicable_procedure_rejected(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "PR4")
    # Карта ограничена другой линией (несуществующей в составе) → неприменима.
    from uuid import uuid4

    proc = ctx.approved_procedure(client, applicable_line_ids=[str(uuid4())])
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1")
    r = ctx.add_op(client, batch_id, joint)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_PROCEDURE_NOT_APPLICABLE


# ══ 5. Фактические параметры и автоматическая проверка ════════════════════════


def test_complete_blocked_without_actuals(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "AC1")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, joint)
    ctx.plan(client, batch_id)
    ctx.start(client, batch_id)
    ctx.upload_chart(client, batch_id)
    r = ctx.complete(client, batch_id)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_INSUFFICIENT_ACTUAL_DATA


def test_auto_check_compliant(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "AC2")
    batch_id, op, joint = _full_to_completed(ctx, client, "AC2")
    r = client.get(f"{URL}/heat-treatment-batches/{batch_id}", headers=ctx.h(ctx.master))
    assert r.json()["auto_check_result"] == "COMPLIANT"


def test_auto_check_deviation(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "AC3")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, joint)
    ctx.plan(client, batch_id)
    ctx.start(client, batch_id)
    ctx.upload_chart(client, batch_id)
    # Температура выше максимума снимка (700).
    ctx.set_actuals(client, batch_id, actual_soak_temperature="750")
    ctx.complete(client, batch_id)
    r = client.get(f"{URL}/heat-treatment-batches/{batch_id}", headers=ctx.h(ctx.master))
    assert r.json()["auto_check_result"] == "DEVIATION_DETECTED"


def test_auto_check_pure_function() -> None:
    snap = {
        "min_temperature": "600", "max_temperature": "700",
        "soak_duration_minutes": 60, "max_heating_rate": "100",
        "max_cooling_rate": "100",
    }
    ok, dev = htw.evaluate_auto_check(
        snap, actual_soak_temperature=Decimal("650"),
        actual_min_temperature=None, actual_max_temperature=None,
        actual_soak_duration_minutes=70, actual_heating_rate=Decimal("80"),
        actual_cooling_rate=Decimal("80"), has_required_document=True,
    )
    assert ok == "COMPLIANT" and dev == []
    bad, dev2 = htw.evaluate_auto_check(
        snap, actual_soak_temperature=Decimal("800"),
        actual_min_temperature=None, actual_max_temperature=None,
        actual_soak_duration_minutes=30, actual_heating_rate=Decimal("200"),
        actual_cooling_rate=Decimal("80"), has_required_document=True,
    )
    assert bad == "DEVIATION_DETECTED"
    assert "TEMPERATURE_ABOVE_MAX" in dev2 and "SOAK_DURATION_TOO_SHORT" in dev2
    insuf, _ = htw.evaluate_auto_check(
        snap, actual_soak_temperature=None, actual_min_temperature=None,
        actual_max_temperature=None, actual_soak_duration_minutes=None,
        actual_heating_rate=None, actual_cooling_rate=None,
        has_required_document=False,
    )
    assert insuf == "INSUFFICIENT_DATA"


# ══ 6. Документы ══════════════════════════════════════════════════════════════


def test_review_requires_verified_chart(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "DC1")
    batch_id, op, joint = _full_to_completed(ctx, client, "DC1")
    # Диаграмма только UPLOADED (не проверена).
    ctx.evaluate(client, op, result="ACCEPTED")
    r = ctx.review(client, batch_id, result="ACCEPTED")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_NO_VERIFIED_CHART


def test_verify_chart(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "DC2")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    joint = ctx.create_joint(client, "J1")
    ctx.add_op(client, batch_id, joint)
    ctx.plan(client, batch_id)
    ctx.start(client, batch_id)
    rec = ctx.upload_chart(client, batch_id)
    r = client.post(
        f"{URL}/heat-treatment-records/{rec}/verify", headers=ctx.h(ctx.ogs)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "VERIFIED"


# ══ 7. Решение ОГС ════════════════════════════════════════════════════════════


def test_ogs_review_rights(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "OG1")
    batch_id, op, joint = _full_to_completed(ctx, client, "OG1")
    ctx.upload_chart(client, batch_id, verify=True)
    ctx.evaluate(client, op, result="ACCEPTED")
    # Мастер (обычный исполнитель) не имеет прав ОГС.
    denied = ctx.review(client, batch_id, result="ACCEPTED", worker=ctx.master)
    assert denied.status_code == 403
    # Главный сварщик имеет доступ.
    ok = ctx.review(client, batch_id, result="ACCEPTED", worker=ctx.chief)
    assert ok.status_code == 200, ok.text


def test_individual_result_justification_required(client, db) -> None:
    ctx = HtCtx(db, "OG2")
    batch_id, op, joint = _full_to_completed(ctx, client, "OG2")
    r = ctx.evaluate(
        client, op, result="ACCEPTED_WITH_JUSTIFICATION", evidence="PARTIALLY_SUFFICIENT"
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_JUSTIFICATION_REQUIRED


def test_accept_forbidden_when_insufficient(client, db) -> None:
    ctx = HtCtx(db, "OG3")
    batch_id, op, joint = _full_to_completed(ctx, client, "OG3")
    r = ctx.evaluate(client, op, result="ACCEPTED", evidence="INSUFFICIENT")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_ACCEPT_INSUFFICIENT_EVIDENCE


def test_review_blocked_with_pending_operation(client, db) -> None:
    ctx = HtCtx(db, "OG4")
    batch_id, op, joint = _full_to_completed(ctx, client, "OG4")
    ctx.upload_chart(client, batch_id, verify=True)
    # Операция не оценена (result PENDING).
    r = ctx.review(client, batch_id, result="ACCEPTED")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_PENDING_OPERATION_RESULTS


# ══ 8. Повторная термообработка ═══════════════════════════════════════════════


def test_repeat_requires_previous(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "RP1")
    batch_id = ctx.create_batch(client)
    joint = ctx.create_joint(client, "J1")
    r = ctx.add_op(client, batch_id, joint, reason="REPEAT_AFTER_REJECTION")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == htw.HT_REPEAT_WITHOUT_PREVIOUS


def test_repeat_after_rejection_new_record(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "RP2")
    # Первый цикл: операция отклонена.
    proc = ctx.approved_procedure(client)
    batch1 = ctx.create_batch(client, batch_no="B1", procedure_id=proc)
    joint = ctx.create_joint(client, "J1", heat_treatment_required=True)
    weld_op = ctx.create_completed_weld_op(client, joint)
    op1 = _op_id(ctx.add_op(client, batch1, joint, weld_operation_id=weld_op))
    ctx.plan(client, batch1)
    ctx.start(client, batch1)
    ctx.upload_chart(client, batch1, verify=True)
    ctx.set_actuals(client, batch1)
    ctx.complete(client, batch1)
    assert ctx.evaluate(client, op1, result="REJECTED").status_code == 200
    ctx.review(client, batch1, result="ACCEPTED")  # цикл проверен, стык отклонён

    # Второй цикл — повтор со ссылкой на предыдущую операцию.
    batch2 = ctx.create_batch(client, batch_no="B2", procedure_id=proc)
    r = ctx.add_op(
        client, batch2, joint, reason="REPEAT_AFTER_REJECTION",
        previous_heat_treatment_operation_id=op1,
    )
    assert r.status_code == 201, r.text
    # Предыдущая операция не изменилась.
    prev = client.get(
        f"{URL}/heat-treatment-operations/{op1}", headers=ctx.h(ctx.master)
    )
    assert prev.json()["result"] == "REJECTED"


# ══ 9. Интеграция с Joint ═════════════════════════════════════════════════════


def test_joint_state_not_required(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "JS1")
    joint = ctx.create_joint(client, "J1", heat_treatment_required=False)
    r = client.get(
        f"{URL}/joints/{joint}/heat-treatment-state", headers=ctx.h(ctx.master)
    )
    assert r.json()["state"] == "NOT_REQUIRED"
    assert r.json()["dependent_steps_ready"] is True


def test_accepted_unblocks_readiness(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "JS2")
    batch_id, op, joint = _full_to_completed(ctx, client, "JS2")
    ctx.upload_chart(client, batch_id, verify=True)
    ctx.evaluate(client, op, result="ACCEPTED")
    ctx.review(client, batch_id, result="ACCEPTED")
    r = client.get(
        f"{URL}/joints/{joint}/heat-treatment-state", headers=ctx.h(ctx.master)
    )
    assert r.json()["state"] == "ACCEPTED"
    assert r.json()["dependent_steps_ready"] is True


def test_new_welding_invalidates_prior_result(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "JS3")
    batch_id, op, joint = _full_to_completed(ctx, client, "JS3")
    ctx.upload_chart(client, batch_id, verify=True)
    ctx.evaluate(client, op, result="ACCEPTED")
    ctx.review(client, batch_id, result="ACCEPTED")
    # Новая сварочная операция после принятой ТО делает прежний результат неактуальным.
    ctx.create_completed_weld_op(client, joint)
    r = client.get(
        f"{URL}/joints/{joint}/heat-treatment-state", headers=ctx.h(ctx.master)
    )
    assert r.json()["state"] == "NOT_STARTED"
    assert r.json()["dependent_steps_ready"] is False
    # История прежней операции сохранена.
    prev = client.get(
        f"{URL}/heat-treatment-operations/{op}", headers=ctx.h(ctx.master)
    )
    assert prev.status_code == 200
    assert prev.json()["result"] == "ACCEPTED"


# ══ 10. Журнал ════════════════════════════════════════════════════════════════


def test_journal_one_row_per_operation(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "JR1")
    proc = ctx.approved_procedure(client)
    batch_id = ctx.create_batch(client, procedure_id=proc)
    j1 = ctx.create_joint(client, "J1")
    j2 = ctx.create_joint(client, "J2")
    ctx.add_op(client, batch_id, j1)
    ctx.add_op(client, batch_id, j2)
    r = client.get(
        f"{URL}/heat-treatment-journal?project_id={ctx.project.id}",
        headers=ctx.h(ctx.master),
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2
    assert {row["joint_no"] for row in r.json()["items"]} == {"J1", "J2"}


def test_journal_filter_by_result(client: TestClient, db: Session) -> None:
    ctx = HtCtx(db, "JR2")
    batch_id, op, joint = _full_to_completed(ctx, client, "JR2")
    ctx.upload_chart(client, batch_id, verify=True)
    ctx.evaluate(client, op, result="ACCEPTED")
    ctx.review(client, batch_id, result="ACCEPTED")
    r = client.get(
        f"{URL}/heat-treatment-journal?project_id={ctx.project.id}&result=ACCEPTED",
        headers=ctx.h(ctx.master),
    )
    assert r.json()["total"] == 1
    rej = client.get(
        f"{URL}/heat-treatment-journal?project_id={ctx.project.id}&result=REJECTED",
        headers=ctx.h(ctx.master),
    )
    assert rej.json()["total"] == 0


# ══ Модульные тесты доменной политики ═════════════════════════════════════════


def test_evidence_result_policy() -> None:
    assert htw.result_allowed_for_evidence("SUFFICIENT", "ACCEPTED")
    assert not htw.result_allowed_for_evidence("PARTIALLY_SUFFICIENT", "ACCEPTED")
    assert htw.result_allowed_for_evidence(
        "PARTIALLY_SUFFICIENT", "ACCEPTED_WITH_JUSTIFICATION"
    )
    assert not htw.result_allowed_for_evidence("INSUFFICIENT", "ACCEPTED")
    assert not htw.result_allowed_for_evidence(
        "INSUFFICIENT", "ACCEPTED_WITH_JUSTIFICATION"
    )


def test_batch_transitions_policy() -> None:
    assert htw.batch_transition_allowed("DRAFT", "PLANNED")
    assert htw.batch_transition_allowed("COMPLETED", "REJECTED")
    assert not htw.batch_transition_allowed("DRAFT", "IN_PROGRESS")
    assert not htw.batch_transition_allowed("CLOSED", "REVIEWED")


def test_joint_state_policy() -> None:
    assert htw.joint_state_from_current(
        heat_treatment_required=False, has_current_operation=False,
        batch_status=None, operation_status=None, operation_result=None,
    ) == "NOT_REQUIRED"
    assert htw.joint_state_from_current(
        heat_treatment_required=True, has_current_operation=False,
        batch_status=None, operation_status=None, operation_result=None,
    ) == "NOT_STARTED"
    assert htw.joint_state_from_current(
        heat_treatment_required=True, has_current_operation=True,
        batch_status="REVIEWED", operation_status="EVALUATED",
        operation_result="ACCEPTED",
    ) == "ACCEPTED"
