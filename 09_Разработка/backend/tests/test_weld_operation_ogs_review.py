"""Интеграционные тесты review ОГС (Task 8C, §17.2, §17.3).

Проверяют первичную маршрутизацию NOT_REQUIRED/PENDING при завершении, команды
approve/reject ОГС, доступ OGS_ENGINEER/CHIEF_WELDER по scope и запрет для
производственных/ПТО ролей, обязательность обоснования при принятии исключения,
неизменяемую review-историю со снимком validation Task 8B, optimistic concurrency
и list-фильтры. Reject не создаёт корректировку/переварку/ремонт (§10.4)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    Joint,
    WeldOperation,
    WeldOperationOgsReview,
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
        last_name=f"OR{suffix}", first_name="Тест", company_id=TEST_COMPANY_ID,
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
        scope_id=scope.get("scope_id"), is_active=True, valid_from=TODAY,
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


def _add_admission(db: Session, welder: Welder) -> WelderAdmission:
    admission = WelderAdmission(
        worker_id=welder.worker_id, stamp_code=welder.stamp_code,
        admission_status="active", welding_methods=["RAD"], material_groups=[],
        diameter_min=Decimal("15"), diameter_max=Decimal("150"),
        thickness_min=Decimal("2"), thickness_max=Decimal("12"),
        valid_from=date(2020, 1, 1), valid_until=date(2035, 1, 1),
    )
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
        self.ogs = _role_worker(
            db, f"{code}Og", "OGS_ENGINEER",
            scope_type="PROJECT", scope_id=str(self.project.id),
        )
        self.chief = _role_worker(db, f"{code}Ch", "CHIEF_WELDER")
        self.welder = _welder(db, f"{code}W", f"ST-{code}")
        self._planned_wps: UUID | None = None

    def headers(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def prepare_joint(self, client: TestClient) -> str:
        pto = _role_worker(self.db, f"{self.project.code}Pto", "PTO_ENGINEER")
        payload = {
            "project_id": str(self.project.id), "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id), "joint_no": "J-1",
            "created_by": self.creator.id,
        }
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

    def joint(self) -> Joint:
        return self.db.query(Joint).filter(Joint.id == UUID(self.joint_id)).one()


def _create_op(client, ctx: Ctx, **over):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations", json=ctx.op_payload(**over),
        headers=ctx.headers(ctx.master),
    )


def _complete(client, ctx: Ctx, op_id):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/complete", json={},
        headers=ctx.headers(ctx.master),
    )


def _approve(client, ctx: Ctx, op_id, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/ogs-review/approve",
        json=body, headers=ctx.headers(worker or ctx.ogs),
    )


def _reject(client, ctx: Ctx, op_id, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/ogs-review/reject",
        json=body, headers=ctx.headers(worker or ctx.ogs),
    )


def _review_body(op: dict, **over) -> dict:
    body = {
        "expected_record_version": op["record_version"],
        "expected_review_version": op["ogs_review_version"],
    }
    body.update(over)
    return body


# ── setup validation-состояний ───────────────────────────────────────────────


def _completed_fail(client, ctx: Ctx) -> dict:
    """Нет допуска → qualification FAIL, WPS INDETERMINATE → ogs PENDING."""
    op = _create_op(client, ctx).json()
    return _complete(client, ctx, op["id"]).json()


def _completed_indeterminate(client, ctx: Ctx) -> dict:
    """Допуск есть, но нет DN/толщины → qualification INDETERMINATE (без FAIL)."""
    _add_admission(db=ctx.db, welder=ctx.welder)
    op = _create_op(client, ctx).json()
    return _complete(client, ctx, op["id"]).json()


def _set_qual_pass(ctx: Ctx) -> None:
    joint = ctx.joint()
    joint.dn_1 = Decimal("100")
    joint.thickness_1 = Decimal("8")
    ctx.db.commit()
    _add_admission(db=ctx.db, welder=ctx.welder)


def _completed_pass_pass(client, ctx: Ctx) -> dict:
    planned = uuid4()
    ctx._planned_wps = planned
    joint = ctx.joint()
    joint.dn_1 = Decimal("100")
    joint.thickness_1 = Decimal("8")
    joint.planned_wps_id = planned
    joint.required_root_method = "RAD"
    ctx.db.commit()
    _add_admission(db=ctx.db, welder=ctx.welder)
    op = _create_op(client, ctx, actual_wps_id=str(planned)).json()
    return _complete(client, ctx, op["id"]).json()


def _completed_wps_fail(client, ctx: Ctx) -> dict:
    """qualification PASS, но фактический WPS != проектного → WPS FAIL."""
    _set_qual_pass(ctx)
    planned = uuid4()
    joint = ctx.joint()
    joint.planned_wps_id = planned
    ctx.db.commit()
    op = _create_op(client, ctx, actual_wps_id=str(uuid4())).json()
    return _complete(client, ctx, op["id"]).json()


# ══ 1-7, первичная маршрутизация ══════════════════════════════════════════════


def test_pass_pass_routes_not_required(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR01")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    assert op["qualification_validation_status"] == "PASS"
    assert op["wps_validation_status"] == "PASS"
    assert op["ogs_review_status"] == "NOT_REQUIRED"
    assert op["requires_ogs_review"] is False


def test_qualification_fail_routes_pending(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR02")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    assert op["qualification_validation_status"] == "FAIL"
    assert op["ogs_review_status"] == "PENDING"
    assert op["requires_ogs_review"] is True


def test_qualification_indeterminate_routes_pending(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR03")
    ctx.prepare_joint(client)
    op = _completed_indeterminate(client, ctx)
    assert op["qualification_validation_status"] == "INDETERMINATE"
    assert op["ogs_review_status"] == "PENDING"


def test_wps_fail_routes_pending(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR04")
    ctx.prepare_joint(client)
    op = _completed_wps_fail(client, ctx)
    assert op["wps_validation_status"] == "FAIL"
    assert op["ogs_review_status"] == "PENDING"


def test_wps_indeterminate_routes_pending(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR05")
    ctx.prepare_joint(client)
    # Допуск+DN есть (qual PASS), но WPS не задан → WPS INDETERMINATE.
    _set_qual_pass(ctx)
    op = _create_op(client, ctx).json()
    completed = _complete(client, ctx, op["id"]).json()
    assert completed["qualification_validation_status"] == "PASS"
    assert completed["wps_validation_status"] == "INDETERMINATE"
    assert completed["ogs_review_status"] == "PENDING"


def test_not_checked_treated_as_review_required(
    client: TestClient, db: Session
) -> None:
    # NOT_CHECKED у завершённой операции (legacy/повреждённая запись) считается
    # требующей ручного review: approve обязан нести код-исключение (§5.2).
    ctx = Ctx(db, "OR06")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    orm = db.query(WeldOperation).filter(WeldOperation.id == UUID(op["id"])).one()
    orm.qualification_validation_status = "NOT_CHECKED"
    orm.qualification_validation_codes = []
    orm.wps_validation_status = "NOT_CHECKED"
    orm.wps_validation_codes = []
    orm.validation_checked_at = None
    orm.ogs_review_status = "PENDING"
    db.commit()
    op = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}",
        headers=ctx.headers(ctx.ogs),
    ).json()
    # Без кода-исключения принять нельзя (NOT_CHECKED требует обоснования).
    resp = _approve(client, ctx, op["id"], **_review_body(op, reason_codes=[]))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "OGS_REVIEW_EXCEPTION_REASON_REQUIRED"


def test_disputed_confirmation_requires_pending(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR07")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    assert op["ogs_review_status"] == "NOT_REQUIRED"
    dispute = client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/welder-confirmation/dispute",
        json={
            "expected_record_version": op["record_version"],
            "expected_confirmation_version": op["welder_confirmation_version"],
            "comment": "спор об исполнителе",
        },
        headers=ctx.headers(ctx.master),
    ).json()
    assert dispute["welder_confirmation_status"] == "DISPUTED"
    assert dispute["ogs_review_status"] == "PENDING"


# ══ 8-15, lifecycle, роли, scope ══════════════════════════════════════════════


def test_draft_cannot_be_reviewed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR08")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _approve(
        client, ctx, op["id"],
        **_review_body(op, reason_codes=["OTHER"], comment="x"),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_NOT_COMPLETED"


def test_cancelled_cannot_be_reviewed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR09")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/cancel",
        json={"reason": "ошибка"}, headers=ctx.headers(ctx.master),
    )
    resp = _reject(
        client, ctx, op["id"],
        **_review_body(op, reason_codes=["OTHER"], comment="x"),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_NOT_COMPLETED"


def test_ogs_engineer_scope_can_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR10")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(client, ctx, op["id"], **_review_body(op, reason_codes=[]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["ogs_review_status"] == "APPROVED"
    assert resp.json()["ogs_reviewed_by"] == ctx.ogs.id


def test_chief_welder_can_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR11")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(client, ctx, op["id"], ctx.chief, **_review_body(op))
    assert resp.status_code == 200, resp.text


def test_master_cannot_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR12")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(client, ctx, op["id"], ctx.master, **_review_body(op))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "OGS_REVIEW_NOT_ALLOWED"


def test_foreman_cannot_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR13")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(client, ctx, op["id"], ctx.foreman, **_review_body(op))
    assert resp.status_code == 403


def test_pto_engineer_cannot_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR14")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    pto = _role_worker(db, "OR14Pt", "PTO_ENGINEER")
    resp = _approve(client, ctx, op["id"], pto, **_review_body(op))
    assert resp.status_code == 403


def test_foreign_ogs_scope_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR15")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    other = _role_worker(
        db, "OR15Ot", "OGS_ENGINEER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = _approve(client, ctx, op["id"], other, **_review_body(op))
    assert resp.status_code == 403


# ══ 16-24, approve и обоснование ══════════════════════════════════════════════


def test_approve_pass_pass_allows_empty_reasons(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR16")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(client, ctx, op["id"], **_review_body(op, reason_codes=[]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["ogs_review_reason_codes"] == []


def test_approve_fail_requires_reason(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR17")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    resp = _approve(
        client, ctx, op["id"], **_review_body(op, reason_codes=[], comment="x")
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "OGS_REVIEW_EXCEPTION_REASON_REQUIRED"


def test_approve_indeterminate_requires_reason(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR18")
    ctx.prepare_joint(client)
    op = _completed_indeterminate(client, ctx)
    resp = _approve(
        client, ctx, op["id"], **_review_body(op, reason_codes=[], comment="x")
    )
    assert resp.status_code == 422


def test_approve_exception_requires_comment(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR19")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    resp = _approve(
        client, ctx, op["id"],
        **_review_body(
            op, reason_codes=["QUALIFICATION_EXCEPTION_ACCEPTED"], comment="  "
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "OGS_REVIEW_COMMENT_REQUIRED"


def test_approve_creates_immutable_history(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR20")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    _approve(
        client, ctx, op["id"],
        **_review_body(
            op, reason_codes=["QUALIFICATION_EXCEPTION_ACCEPTED"],
            comment="принято главным сварщиком",
        ),
    )
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/ogs-reviews",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert len(hist) == 1
    assert hist[0]["decision"] == "APPROVED"
    assert hist[0]["review_version"] == 2
    assert hist[0]["previous_status"] == "PENDING"


def test_history_contains_validation_snapshot(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR21")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    _approve(
        client, ctx, op["id"],
        **_review_body(
            op, reason_codes=["QUALIFICATION_EXCEPTION_ACCEPTED"], comment="ok"
        ),
    )
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/ogs-reviews",
        headers=ctx.headers(ctx.ogs),
    ).json()[0]
    assert hist["qualification_validation_status"] == "FAIL"
    assert "NO_ACTIVE_ADMISSION" in hist["qualification_validation_codes"]
    assert hist["wps_validation_status"] == op["wps_validation_status"]
    assert hist["reason_codes"] == ["QUALIFICATION_EXCEPTION_ACCEPTED"]


def test_approve_keeps_validation_status(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR22")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    body = _approve(
        client, ctx, op["id"],
        **_review_body(
            op, reason_codes=["QUALIFICATION_EXCEPTION_ACCEPTED"], comment="ok"
        ),
    ).json()
    # Решение ОГС не переписывает validation-результаты Task 8B (§3.3).
    assert body["qualification_validation_status"] == "FAIL"
    assert body["wps_validation_status"] == op["wps_validation_status"]


def test_approve_keeps_lifecycle(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR23")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    body = _approve(client, ctx, op["id"], **_review_body(op)).json()
    assert body["lifecycle_status"] == "COMPLETED"


def test_approve_keeps_actual_welder(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR24")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    body = _approve(client, ctx, op["id"], **_review_body(op)).json()
    assert body["actual_welder_id"] == op["actual_welder_id"]
    assert body["welder_confirmation_status"] == op["welder_confirmation_status"]


# ══ 25-31, reject ═════════════════════════════════════════════════════════════


def test_reject_requires_reason(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR25")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    resp = _reject(
        client, ctx, op["id"], **_review_body(op, reason_codes=[], comment="x")
    )
    assert resp.status_code == 422


def test_reject_requires_comment(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR26")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    resp = _reject(
        client, ctx, op["id"],
        **_review_body(op, reason_codes=["WPS_NONCOMPLIANCE"], comment="  "),
    )
    assert resp.status_code == 422


def test_reject_creates_history(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR27")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    body = _reject(
        client, ctx, op["id"],
        **_review_body(op, reason_codes=["WPS_NONCOMPLIANCE"], comment="не соответствует"),
    ).json()
    assert body["ogs_review_status"] == "REJECTED"
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/ogs-reviews",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert hist[0]["decision"] == "REJECTED"


def test_reject_keeps_completed_and_no_new_operations(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR28")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    body = _reject(
        client, ctx, op["id"],
        **_review_body(op, reason_codes=["QUALIFICATION_NONCOMPLIANCE"], comment="брак"),
    ).json()
    # Операция остаётся COMPLETED; reject не создаёт correction/reweld/repair (§10.4).
    assert body["lifecycle_status"] == "COMPLETED"
    assert body["actual_welder_id"] == op["actual_welder_id"]
    listing = client.get(
        f"{ENGINEERING_URL}/joints/{ctx.joint_id}/weld-operations",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert listing["total"] == 1


# ══ 32-37, повторные решения и concurrency ════════════════════════════════════


def test_new_decision_creates_next_version(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR32")
    ctx.prepare_joint(client)
    op = _completed_fail(client, ctx)
    approved = _approve(
        client, ctx, op["id"],
        **_review_body(
            op, reason_codes=["QUALIFICATION_EXCEPTION_ACCEPTED"], comment="ok"
        ),
    ).json()
    assert approved["ogs_review_version"] == 2
    rejected = _reject(
        client, ctx, op["id"],
        **_review_body(approved, reason_codes=["QUALIFICATION_NONCOMPLIANCE"], comment="пересмотр"),
    ).json()
    assert rejected["ogs_review_status"] == "REJECTED"
    assert rejected["ogs_review_version"] == 3
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/ogs-reviews",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert [h["review_version"] for h in hist] == [2, 3]


def test_repeat_identical_decision_conflicts(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR33")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    approved = _approve(client, ctx, op["id"], **_review_body(op)).json()
    resp = _approve(client, ctx, op["id"], **_review_body(approved))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "OGS_REVIEW_ALREADY_APPROVED"


def test_wrong_review_version_conflicts(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR34")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(
        client, ctx, op["id"], **_review_body(op, expected_review_version=99)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "OGS_REVIEW_VERSION_CONFLICT"


def test_wrong_record_version_conflicts(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR35")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(
        client, ctx, op["id"], **_review_body(op, expected_record_version=99)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "RECORD_VERSION_CONFLICT"


def test_conflict_leaves_history_and_projection_unchanged(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR36")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    _approve(client, ctx, op["id"], **_review_body(op, expected_review_version=99))
    fresh = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert fresh["ogs_review_status"] == "NOT_REQUIRED"
    assert fresh["ogs_review_version"] == 1
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/ogs-reviews",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert hist == []


def test_history_sorted_by_review_version(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR37")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    approved = _approve(client, ctx, op["id"], **_review_body(op)).json()
    _reject(
        client, ctx, op["id"],
        **_review_body(approved, reason_codes=["OTHER"], comment="пересмотр"),
    )
    hist = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/ogs-reviews",
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert [h["review_version"] for h in hist] == [2, 3]


# ══ 38-40, list-фильтры ═══════════════════════════════════════════════════════


def test_filter_by_ogs_review_status(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR38")
    ctx.prepare_joint(client)
    _completed_fail(client, ctx)  # PENDING
    resp = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"joint_id": ctx.joint_id, "ogs_review_status": "PENDING"},
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert resp["total"] == 1
    assert all(i["ogs_review_status"] == "PENDING" for i in resp["items"])
    empty = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"joint_id": ctx.joint_id, "ogs_review_status": "APPROVED"},
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert empty["total"] == 0


def test_filter_by_welder_confirmation_status(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OR39")
    ctx.prepare_joint(client)
    _completed_fail(client, ctx)
    resp = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"joint_id": ctx.joint_id, "welder_confirmation_status": "PENDING"},
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert resp["total"] == 1


def test_existing_validation_filters_intact(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "OR40")
    ctx.prepare_joint(client)
    _completed_fail(client, ctx)
    resp = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={
            "joint_id": ctx.joint_id,
            "qualification_validation_status": "FAIL",
        },
        headers=ctx.headers(ctx.ogs),
    ).json()
    assert resp["total"] == 1


# ══ 17.3, ограничения БД review ═══════════════════════════════════════════════


def _persisted_completed(client, ctx: Ctx) -> WeldOperation:
    op = _completed_pass_pass(client, ctx)
    return ctx.db.query(WeldOperation).filter(
        WeldOperation.id == UUID(op["id"])
    ).one()


def test_db_unknown_review_status_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ODB1")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.ogs_review_status = "BOGUS"
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_review_version_zero_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ODB2")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.ogs_review_version = 0
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_approved_without_actor_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ODB3")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.ogs_review_status = "APPROVED"  # actor/time NULL
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_rejected_without_actor_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ODB4")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    op.ogs_review_status = "REJECTED"
    op.ogs_review_reason_codes = ["OTHER"]
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_duplicate_review_version_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "ODB5")
    ctx.prepare_joint(client)
    op = _persisted_completed(client, ctx)
    now = datetime.now(timezone.utc)
    for _ in range(2):
        db.add(
            WeldOperationOgsReview(
                weld_operation_id=op.id, decision="APPROVED",
                previous_status="NOT_REQUIRED", review_version=5,
                qualification_validation_status="PASS",
                qualification_validation_codes=[],
                wps_validation_status="PASS", wps_validation_codes=[],
                reason_codes=[], decided_by=ctx.chief.id, decided_at=now,
            )
        )
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_db_review_fk_to_missing_operation_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "ODB6")
    ctx.prepare_joint(client)
    db.add(
        WeldOperationOgsReview(
            weld_operation_id=uuid4(), decision="APPROVED",
            previous_status="NOT_REQUIRED", review_version=1,
            qualification_validation_status="PASS",
            qualification_validation_codes=[],
            wps_validation_status="PASS", wps_validation_codes=[],
            reason_codes=[], decided_by=ctx.chief.id,
            decided_at=datetime.now(timezone.utc),
        )
    )
    try:
        db.flush()
        assert False, "ожидалась IntegrityError"
    except IntegrityError:
        db.rollback()


def test_unknown_reason_code_rejected_by_schema(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "ODB7")
    ctx.prepare_joint(client)
    op = _completed_pass_pass(client, ctx)
    resp = _approve(
        client, ctx, op["id"],
        **_review_body(op, reason_codes=["NOPE_INVALID"], comment="x"),
    )
    assert resp.status_code == 422
