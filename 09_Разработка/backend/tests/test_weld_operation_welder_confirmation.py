"""Интеграционные тесты подтверждения сварщика (Task 8C, §17.1, §17.3).

Проверяют команды confirm/dispute поверх завершённого производственного факта:
доступ MASTER/FOREMAN/CHIEF_WELDER по scope, запрет для ОГС, actor только из
X-User-Id, переходы статуса, неизменяемую историю, optimistic concurrency,
маршрутизацию спора в review ОГС и ограничения БД. Ось подтверждения независима
от lifecycle и validation Task 8B (§2-3 задания)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    WeldOperation,
    WeldOperationWelderConfirmation,
)
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project
from app.welding.models import Welder, WelderAdmission

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"
TODAY = date.today()
PERFORMED_ON = TODAY.isoformat()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"WC{suffix}", first_name="Тест", company_id=TEST_COMPANY_ID,
        employment_status="active", hire_date=TODAY,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _assign_role(db: Session, worker_id: int, role_code: str, **scope) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id, role_code=role_code,
        scope_type=scope.get("scope_type", "GLOBAL"),
        scope_id=scope.get("scope_id"), is_active=scope.get("is_active", True),
        valid_from=scope.get("valid_from", TODAY), valid_to=scope.get("valid_to"),
    )
    db.add(role)
    db.commit()
    return role


def _role_worker(db: Session, suffix: str, role_code: str, **scope) -> Worker:
    w = _worker(db, suffix)
    _assign_role(db, w.id, role_code, **scope)
    return w


def _welder(db: Session, suffix: str, stamp: str) -> Welder:
    worker = _worker(db, f"{suffix}Wkr")
    welder = Welder(worker_id=worker.id, stamp_code=stamp, status="active")
    db.add(welder)
    db.commit()
    db.refresh(welder)
    return welder


def _add_admission(db: Session, welder: Welder, **over) -> WelderAdmission:
    params = dict(
        worker_id=welder.worker_id, stamp_code=welder.stamp_code,
        admission_status="active", welding_methods=["RAD"], material_groups=[],
        diameter_min=Decimal("15"), diameter_max=Decimal("150"),
        thickness_min=Decimal("2"), thickness_max=Decimal("12"),
        valid_from=date(2020, 1, 1), valid_until=date(2035, 1, 1),
    )
    params.update(over)
    admission = WelderAdmission(**params)
    db.add(admission)
    db.commit()
    return admission


class Ctx:
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
        self.master = _role_worker(db, f"{code}Ma", "MASTER")
        self.foreman = _role_worker(db, f"{code}Fo", "FOREMAN")
        self.ogs = _role_worker(db, f"{code}Og", "OGS_ENGINEER")
        self.welder = _welder(db, f"{code}W", f"ST-{code}")

    def headers(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def prepare_joint(self, client: TestClient) -> str:
        payload = {
            "project_id": str(self.project.id), "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id), "joint_no": "J-1",
            "created_by": self.creator.id,
        }
        pto = _role_worker(self.db, f"{self.project.code}Pto", "PTO_ENGINEER")
        resp = client.post(
            f"{ENGINEERING_URL}/joints", json=payload, headers=self.headers(pto)
        )
        assert resp.status_code == 201, resp.text
        self.joint_id = resp.json()["id"]
        return self.joint_id

    def op_payload(self, **overrides) -> dict:
        payload = {
            "joint_id": self.joint_id, "responsible_worker_id": self.master.id,
            "actual_welder_id": str(self.welder.id),
            "entered_stamp_code": self.welder.stamp_code,
            "weld_stage": "ROOT", "welding_method": "RAD",
            "performed_on": PERFORMED_ON,
        }
        payload.update(overrides)
        return payload


def _create_op(client, ctx: Ctx, worker: Worker | None = None, **over):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations", json=ctx.op_payload(**over),
        headers=ctx.headers(worker or ctx.master),
    )


def _complete(client, ctx: Ctx, op_id, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/complete", json=body,
        headers=ctx.headers(worker or ctx.master),
    )


def _completed_op(client, ctx: Ctx, **over) -> dict:
    op = _create_op(client, ctx, **over).json()
    return _complete(client, ctx, op["id"]).json()


def _confirm(client, ctx: Ctx, op_id, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/welder-confirmation/confirm",
        json=body, headers=ctx.headers(worker or ctx.master),
    )


def _dispute(client, ctx: Ctx, op_id, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/welder-confirmation/dispute",
        json=body, headers=ctx.headers(worker or ctx.master),
    )


def _confirm_body(op: dict, **over) -> dict:
    body = {
        "expected_record_version": op["record_version"],
        "expected_confirmation_version": op["welder_confirmation_version"],
    }
    body.update(over)
    return body


# ══ 1-7, позитивные и статусные ═══════════════════════════════════════════════


def test_new_operation_confirmation_pending(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP1")
    ctx.prepare_joint(client)
    body = _create_op(client, ctx).json()
    assert body["welder_confirmation_status"] == "PENDING"
    assert body["welder_confirmation_version"] == 1
    assert body["welder_confirmed_at"] is None
    assert body["welder_confirmed_by"] is None


def test_draft_cannot_be_confirmed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP2")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _confirm(client, ctx, op["id"], **_confirm_body(op))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_NOT_COMPLETED"


def test_draft_cannot_be_disputed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP3")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _dispute(client, ctx, op["id"], **_confirm_body(op, comment="спор"))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_NOT_COMPLETED"


def test_cancelled_cannot_be_confirmed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP4")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/cancel",
        json={"reason": "ошибка"}, headers=ctx.headers(ctx.master),
    )
    resp = _confirm(client, ctx, op["id"], **_confirm_body(op))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_NOT_COMPLETED"


def test_master_can_confirm(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP5")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _confirm(client, ctx, op["id"], **_confirm_body(op))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["welder_confirmation_status"] == "CONFIRMED"
    assert body["welder_confirmation_version"] == 2
    assert body["welder_confirmed_by"] == ctx.master.id
    assert body["welder_confirmed_at"] is not None


def test_foreman_can_confirm(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP6")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _confirm(client, ctx, op["id"], ctx.foreman, **_confirm_body(op))
    assert resp.status_code == 200, resp.text
    assert resp.json()["welder_confirmed_by"] == ctx.foreman.id


def test_chief_welder_can_confirm(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCP7")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    chief = _role_worker(db, "WCP7Ch", "CHIEF_WELDER")
    resp = _confirm(client, ctx, op["id"], chief, **_confirm_body(op))
    assert resp.status_code == 200, resp.text
    assert resp.json()["welder_confirmed_by"] == chief.id


# ══ 8-11, роли и scope ════════════════════════════════════════════════════════


def test_ogs_engineer_cannot_confirm(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCR8")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _confirm(client, ctx, op["id"], ctx.ogs, **_confirm_body(op))
    assert resp.status_code == 403


def test_foreign_project_scope_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCR9")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    other = _role_worker(
        db, "WCR9Ot", "MASTER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = _confirm(client, ctx, op["id"], other, **_confirm_body(op))
    assert resp.status_code == 403


def test_foreign_line_scope_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCRA")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    other = _role_worker(
        db, "WCRAOt", "FOREMAN", scope_type="LINE", scope_id=str(uuid4())
    )
    resp = _confirm(client, ctx, op["id"], other, **_confirm_body(op))
    assert resp.status_code == 403


def test_line_scope_grants_access(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCRB")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    scoped = _role_worker(
        db, "WCRBLn", "MASTER", scope_type="LINE", scope_id=str(ctx.line.id)
    )
    resp = _confirm(client, ctx, op["id"], scoped, **_confirm_body(op))
    assert resp.status_code == 200, resp.text


# ══ 12-14, история и actor ════════════════════════════════════════════════════


def test_confirm_creates_history_row(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCH1")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    _confirm(client, ctx, op["id"], **_confirm_body(op))
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmations",
        headers=ctx.headers(ctx.master),
    ).json()
    assert len(hist) == 1
    assert hist[0]["decision"] == "CONFIRMED"
    assert hist[0]["previous_status"] == "PENDING"
    assert hist[0]["confirmation_version"] == 2


def test_confirm_stores_actor_from_header(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCH2")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    body = _confirm(client, ctx, op["id"], ctx.foreman, **_confirm_body(op)).json()
    assert body["welder_confirmed_by"] == ctx.foreman.id


def test_actor_in_body_rejected_by_schema(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCH3")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _confirm(
        client, ctx, op["id"], **_confirm_body(op, confirmed_by=999)
    )
    assert resp.status_code == 422


# ══ 15-19, dispute ════════════════════════════════════════════════════════════


def test_dispute_requires_comment(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCD1")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _dispute(client, ctx, op["id"], **_confirm_body(op, comment="   "))
    assert resp.status_code == 422


def test_dispute_creates_history_and_status(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCD2")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    body = _dispute(
        client, ctx, op["id"], **_confirm_body(op, comment="другой исполнитель")
    ).json()
    assert body["welder_confirmation_status"] == "DISPUTED"
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmations",
        headers=ctx.headers(ctx.master),
    ).json()
    assert hist[-1]["decision"] == "DISPUTED"


def test_dispute_routes_unreviewed_to_pending(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WCD3")
    ctx.prepare_joint(client)
    # PASS/PASS → изначально NOT_REQUIRED; спор направляет в PENDING.
    _set_pass_pass(db, ctx)
    op = _completed_pass(client, ctx)
    assert op["ogs_review_status"] == "NOT_REQUIRED"
    body = _dispute(
        client, ctx, op["id"], **_confirm_body(op, comment="спор")
    ).json()
    assert body["ogs_review_status"] == "PENDING"


def test_confirm_after_dispute_new_history_version(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WCD4")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    disputed = _dispute(
        client, ctx, op["id"], **_confirm_body(op, comment="спор")
    ).json()
    confirmed = _confirm(
        client, ctx, op["id"], **_confirm_body(disputed)
    ).json()
    assert confirmed["welder_confirmation_status"] == "CONFIRMED"
    assert confirmed["welder_confirmation_version"] == 3
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmations",
        headers=ctx.headers(ctx.master),
    ).json()
    assert [h["confirmation_version"] for h in hist] == [2, 3]


# ══ 20-24, concurrency и повторы ══════════════════════════════════════════════


def test_repeat_confirmed_conflicts(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCC1")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    confirmed = _confirm(client, ctx, op["id"], **_confirm_body(op)).json()
    resp = _confirm(client, ctx, op["id"], **_confirm_body(confirmed))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELDER_ALREADY_CONFIRMED"


def test_repeat_disputed_conflicts(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCC2")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    disputed = _dispute(
        client, ctx, op["id"], **_confirm_body(op, comment="спор")
    ).json()
    resp = _dispute(
        client, ctx, op["id"], **_confirm_body(disputed, comment="снова")
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELDER_ALREADY_DISPUTED"


def test_wrong_confirmation_version_conflicts(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WCC3")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _confirm(
        client, ctx, op["id"],
        **_confirm_body(op, expected_confirmation_version=99),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELDER_CONFIRMATION_VERSION_CONFLICT"


def test_wrong_record_version_conflicts(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCC4")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    resp = _confirm(
        client, ctx, op["id"], **_confirm_body(op, expected_record_version=99)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "RECORD_VERSION_CONFLICT"


def test_conflict_leaves_no_history(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCC5")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    _confirm(
        client, ctx, op["id"],
        **_confirm_body(op, expected_confirmation_version=99),
    )
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmations",
        headers=ctx.headers(ctx.master),
    ).json()
    assert hist == []


# ══ 25-27, история и неизменяемость факта ═════════════════════════════════════


def test_history_sorted_by_version(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCS1")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    confirmed = _confirm(client, ctx, op["id"], **_confirm_body(op)).json()
    _dispute(
        client, ctx, op["id"], **_confirm_body(confirmed, comment="спор")
    )
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmations",
        headers=ctx.headers(ctx.master),
    ).json()
    assert [h["confirmation_version"] for h in hist] == [2, 3]


def test_history_has_no_update_delete(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "WCS2")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    _confirm(client, ctx, op["id"], **_confirm_body(op))
    url = f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmations"
    headers = ctx.headers(ctx.master)
    assert client.put(url, json={}, headers=headers).status_code == 405
    assert client.delete(url, headers=headers).status_code == 405


def test_confirmation_keeps_production_fields(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WCS3")
    ctx.prepare_joint(client)
    op = _completed_op(client, ctx)
    confirmed = _confirm(client, ctx, op["id"], **_confirm_body(op)).json()
    # record_version — версия производственных данных — не меняется командой 8C.
    assert confirmed["record_version"] == op["record_version"]
    assert confirmed["weld_stage"] == op["weld_stage"]
    assert confirmed["welding_method"] == op["welding_method"]
    assert confirmed["actual_welder_id"] == op["actual_welder_id"]
    assert confirmed["lifecycle_status"] == "COMPLETED"


# ══ 17.3, ограничения БД (прямой flush) ═══════════════════════════════════════


def _persisted_completed(client, ctx: Ctx) -> WeldOperation:
    op = _completed_op(client, ctx)
    return db_get_op(ctx.db, op["id"])


def db_get_op(db: Session, op_id: str) -> WeldOperation:
    from uuid import UUID
    return db.query(WeldOperation).filter(WeldOperation.id == UUID(op_id)).one()


def test_db_unknown_confirmation_status_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WDB1")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.welder_confirmation_status = "BOGUS"
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_confirmation_version_zero_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WDB2")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.welder_confirmation_version = 0
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_confirmed_without_actor_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WDB3")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.welder_confirmation_status = "CONFIRMED"  # actor/time остаются NULL
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_disputed_without_actor_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "WDB4")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.welder_confirmation_status = "DISPUTED"
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_duplicate_confirmation_version_rejected(
    client: TestClient, db: Session
) -> None:
    from datetime import datetime, timezone
    ctx = Ctx(db, "WDB5")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    now = datetime.now(timezone.utc)
    for _ in range(2):
        db.add(
            WeldOperationWelderConfirmation(
                weld_operation_id=op.id, decision="CONFIRMED",
                previous_status="PENDING", confirmation_version=5,
                decided_by=ctx.master.id, decided_at=now,
            )
        )
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_history_fk_to_missing_operation_rejected(
    client: TestClient, db: Session
) -> None:
    from datetime import datetime, timezone
    ctx = Ctx(db, "WDB6")
    ctx.prepare_joint(client)
    db.add(
        WeldOperationWelderConfirmation(
            weld_operation_id=uuid4(), decision="CONFIRMED",
            previous_status="PENDING", confirmation_version=1,
            decided_by=ctx.master.id, decided_at=datetime.now(timezone.utc),
        )
    )
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


# ── helpers PASS/PASS (для маршрутизации спора) ──────────────────────────────


def _set_pass_pass(db: Session, ctx: Ctx) -> None:
    from uuid import UUID
    from app.engineering.models import Joint
    planned = uuid4()
    ctx._planned_wps = planned
    joint = db.query(Joint).filter(Joint.id == UUID(ctx.joint_id)).one()
    joint.dn_1 = Decimal("100")
    joint.thickness_1 = Decimal("8")
    joint.planned_wps_id = planned
    joint.required_root_method = "RAD"
    db.commit()
    _add_admission(db, ctx.welder)


def _completed_pass(client, ctx: Ctx) -> dict:
    op = _create_op(client, ctx, actual_wps_id=str(ctx._planned_wps)).json()
    return _complete(client, ctx, op["id"]).json()
