"""Интеграционные тесты корректировок WeldOperation (Task 8D, §21).

Покрывают создание корректировки со снимками и diff, матрицу типов и согласований,
lifecycle (submit/approve/return/reject/cancel), атомарное применение с переводом
исходной операции в SUPERSEDED/CANCELLED, неизменяемость завершённого факта,
запрет параллельных корректировок, ошибку применения и права/scope."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering import services as eng_services
from app.engineering.models import Joint, WeldOperation, WeldOperationCorrection
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project
from app.welding.models import Welder

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"
TODAY = date.today()
PERFORMED_ON = TODAY.isoformat()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"CR{suffix}", first_name="Тест", company_id=TEST_COMPANY_ID,
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
        from app.engineering.models import DocumentRevision, EngineeringDocument

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
        self.welder = _welder(db, f"{code}W1", f"ST1-{code}")
        self.welder2 = _welder(db, f"{code}W2", f"ST2-{code}")

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

    def completed_op(self, client: TestClient, **over) -> dict:
        resp = client.post(
            f"{ENGINEERING_URL}/weld-operations", json=self.op_payload(**over),
            headers=self.headers(self.master),
        )
        assert resp.status_code == 201, resp.text
        op_id = resp.json()["id"]
        resp = client.post(
            f"{ENGINEERING_URL}/weld-operations/{op_id}/complete", json={},
            headers=self.headers(self.master),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()


# ── Endpoint helpers ──────────────────────────────────────────────────────────


def _create_corr(client, ctx: Ctx, op: dict, worker=None, **body):
    payload = {
        "correction_type": "DATA_CORRECTION",
        "reason": "Исправление реквизита",
        "expected_source_record_version": op["record_version"],
    }
    payload.update(body)
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/corrections",
        json=payload, headers=ctx.headers(worker or ctx.master),
    )


def _cmd(client, ctx, corr_id, action, worker, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operation-corrections/{corr_id}/{action}",
        json=body, headers=ctx.headers(worker),
    )


def _get_op(client, ctx, op_id) -> dict:
    resp = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op_id}", headers=ctx.headers(ctx.master)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _drive_to_ready(client, ctx: Ctx, corr: dict) -> dict:
    """Проводит корректировку через submit + SMR approve (+ OGS accept при
    необходимости) до APPROVED/READY_TO_APPLY. Возвращает текущий JSON."""
    corr_id = corr["id"]
    resp = _cmd(client, ctx, corr_id, "submit", ctx.master,
                expected_record_version=corr["record_version"])
    assert resp.status_code == 200, resp.text
    corr = resp.json()
    resp = _cmd(client, ctx, corr_id, "smr-approve", ctx.master,
                expected_record_version=corr["record_version"],
                comment="Подтверждаю")
    assert resp.status_code == 200, resp.text
    corr = resp.json()
    if corr["ogs_review_status"] == "PENDING":
        resp = _cmd(client, ctx, corr_id, "ogs-accept", ctx.ogs,
                    expected_record_version=corr["record_version"],
                    decision="ACCEPTED", comment="Принято")
        assert resp.status_code == 200, resp.text
        corr = resp.json()
    return corr


# ── 21.1 Создание корректировки ───────────────────────────────────────────────


def test_correction_only_for_completed_operation(client, db):
    ctx = Ctx(db, "C01")
    ctx.prepare_joint(client)
    # DRAFT-операция ещё не завершена — корректировка запрещена.
    resp = client.post(
        f"{ENGINEERING_URL}/weld-operations", json=ctx.op_payload(),
        headers=ctx.headers(ctx.master),
    )
    op = resp.json()
    resp = _create_corr(client, ctx, op)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SOURCE_OPERATION_NOT_COMPLETED"


def test_before_snapshot_built_by_server(client, db):
    ctx = Ctx(db, "C02")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(client, ctx, op, patch={"operation_note": "новое"})
    assert resp.status_code == 201, resp.text
    corr = resp.json()
    assert corr["before_snapshot"]["id"] == op["id"]
    assert corr["before_snapshot"]["welding_method"] == "RAD"
    assert corr["before_snapshot"]["lifecycle_status"] == "COMPLETED"


def test_client_cannot_supply_before_snapshot(client, db):
    ctx = Ctx(db, "C03")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/corrections",
        json={
            "correction_type": "DATA_CORRECTION", "reason": "x",
            "expected_source_record_version": op["record_version"],
            "patch": {"operation_note": "n"},
            "before_snapshot": {"welding_method": "HACK"},
        },
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 422


def test_replacement_created_for_data_welder_tech_supersede(client, db):
    ctx = Ctx(db, "C04")
    ctx.prepare_joint(client)
    cases = [
        ("DATA_CORRECTION", {"operation_note": "n"}),
        ("WELDER_CORRECTION", {"actual_welder_id": str(ctx.welder2.id)}),
        ("TECHNOLOGY_CORRECTION", {"welding_method": "MMA"}),
        ("SUPERSEDE_RECORD", {"welding_position": "PA"}),
    ]
    for corr_type, patch in cases:
        op = ctx.completed_op(client)
        resp = _create_corr(
            client, ctx, op, correction_type=corr_type, patch=patch,
        )
        assert resp.status_code == 201, resp.text
        corr = resp.json()
        assert corr["replacement_operation_id"] is not None, corr_type
        assert corr["after_snapshot"] is not None
        repl = _get_op(client, ctx, corr["replacement_operation_id"])
        assert repl["lifecycle_status"] == "DRAFT"
        assert repl["supersedes_operation_id"] == op["id"]


def test_cancel_false_record_has_no_replacement(client, db):
    ctx = Ctx(db, "C05")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(
        client, ctx, op, correction_type="CANCEL_FALSE_RECORD",
        reason="Сварка не выполнялась",
    )
    assert resp.status_code == 201, resp.text
    corr = resp.json()
    assert corr["replacement_operation_id"] is None
    assert corr["after_snapshot"] is None


def test_changed_fields_and_field_changes(client, db):
    ctx = Ctx(db, "C06")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder2.id)},
    )
    corr = resp.json()
    assert corr["changed_fields"] == ["actual_welder_id"]
    assert corr["field_changes"]["actual_welder_id"]["before"] == str(ctx.welder.id)
    assert corr["field_changes"]["actual_welder_id"]["after"] == str(ctx.welder2.id)


def test_critical_field_gives_technological(client, db):
    ctx = Ctx(db, "C07")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(
        client, ctx, op, correction_type="SUPERSEDE_RECORD",
        patch={"welding_method": "MMA"},
    )
    assert resp.json()["impact_level"] == "TECHNOLOGICAL"


def test_data_correction_cannot_change_critical_field(client, db):
    ctx = Ctx(db, "C08")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(
        client, ctx, op, correction_type="DATA_CORRECTION",
        patch={"welding_method": "MMA"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "CORRECTION_CRITICAL_FIELD_NOT_ALLOWED"


def test_correction_without_changes_rejected(client, db):
    ctx = Ctx(db, "C09")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "CORRECTION_NO_EFFECTIVE_CHANGES"


def test_reason_required(client, db):
    ctx = Ctx(db, "C10")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = client.post(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/corrections",
        json={
            "correction_type": "DATA_CORRECTION", "reason": "   ",
            "expected_source_record_version": op["record_version"],
            "patch": {"operation_note": "n"},
        },
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 422


def test_source_version_conflict(client, db):
    ctx = Ctx(db, "C11")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(
        client, ctx, op, expected_source_record_version=op["record_version"] + 5,
        patch={"operation_note": "n"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SOURCE_OPERATION_VERSION_CONFLICT"


# ── 21.2 Параллельные корректировки ───────────────────────────────────────────


def test_second_active_correction_forbidden(client, db):
    ctx = Ctx(db, "C12")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    r1 = _create_corr(client, ctx, op, patch={"operation_note": "a"})
    assert r1.status_code == 201
    r2 = _create_corr(client, ctx, op, patch={"operation_note": "b"})
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "ACTIVE_CORRECTION_EXISTS"


def test_new_correction_allowed_after_cancel(client, db):
    ctx = Ctx(db, "C13")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    resp = _cmd(client, ctx, corr["id"], "cancel", ctx.master,
                expected_record_version=corr["record_version"], reason="передумали")
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "CANCELLED"
    r2 = _create_corr(client, ctx, op, patch={"operation_note": "b"})
    assert r2.status_code == 201


def test_partial_unique_index_blocks_race(client, db):
    ctx = Ctx(db, "C14")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    _create_corr(client, ctx, op, patch={"operation_note": "a"})
    # Обходим сервисную проверку и вставляем вторую активную напрямую — partial
    # unique index должен защитить гонку на уровне БД.
    from sqlalchemy.exc import IntegrityError

    dup = WeldOperationCorrection(
        source_operation_id=UUID(op["id"]),
        correction_type="DATA_CORRECTION", impact_level="NON_TECHNICAL",
        reason="dup", changed_fields=[], before_snapshot={}, field_changes={},
        source_type="MANUAL", lifecycle_status="DRAFT",
        smr_approval_status="PENDING", ogs_review_status="NOT_REQUIRED",
        application_status="NOT_READY", record_version=1,
        application_attempts=0, created_by=ctx.master.id, updated_by=ctx.master.id,
    )
    db.add(dup)
    raised = False
    try:
        db.commit()
    except IntegrityError:
        raised = True
        db.rollback()
    assert raised


# ── 21.3 Lifecycle ────────────────────────────────────────────────────────────


def test_submit_sets_pending_approvals(client, db):
    ctx = Ctx(db, "C15")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder2.id)},
    ).json()
    resp = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["lifecycle_status"] == "SUBMITTED"
    assert body["smr_approval_status"] == "PENDING"
    assert body["ogs_review_status"] == "PENDING"
    assert body["application_status"] == "NOT_READY"


def test_smr_return_reopens_draft(client, db):
    ctx = Ctx(db, "C16")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    resp = _cmd(client, ctx, corr["id"], "smr-return", ctx.master,
                expected_record_version=corr["record_version"], comment="уточните")
    assert resp.status_code == 200
    body = resp.json()
    assert body["smr_approval_status"] == "RETURNED_FOR_CLARIFICATION"
    assert body["lifecycle_status"] == "DRAFT"


def test_smr_reject_cancels_replacement(client, db):
    ctx = Ctx(db, "C17")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    repl_id = corr["replacement_operation_id"]
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    resp = _cmd(client, ctx, corr["id"], "smr-reject", ctx.master,
                expected_record_version=corr["record_version"], comment="нет")
    assert resp.status_code == 200
    assert resp.json()["lifecycle_status"] == "REJECTED"
    assert _get_op(client, ctx, repl_id)["lifecycle_status"] == "CANCELLED"


def test_ogs_accept_with_remark_requires_comment(client, db):
    ctx = Ctx(db, "C18")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder2.id)},
    ).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    corr = _cmd(client, ctx, corr["id"], "smr-approve", ctx.master,
                expected_record_version=corr["record_version"]).json()
    resp = _cmd(client, ctx, corr["id"], "ogs-accept", ctx.ogs,
                expected_record_version=corr["record_version"],
                decision="ACCEPTED_WITH_REMARK", comment="  ")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "CORRECTION_COMMENT_REQUIRED"


def test_cancel_after_apply_forbidden(client, db):
    ctx = Ctx(db, "C19")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    corr = _drive_to_ready(client, ctx, corr)
    resp = _cmd(client, ctx, corr["id"], "apply", ctx.master,
                expected_record_version=corr["record_version"],
                expected_source_record_version=op["record_version"])
    assert resp.status_code == 200
    applied = resp.json()
    resp = _cmd(client, ctx, corr["id"], "cancel", ctx.master,
                expected_record_version=applied["record_version"], reason="поздно")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CORRECTION_ALREADY_APPLIED"


def test_status_not_changed_by_plain_patch(client, db):
    ctx = Ctx(db, "C20")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    resp = client.patch(
        f"{ENGINEERING_URL}/weld-operation-corrections/{corr['id']}",
        json={"expected_record_version": corr["record_version"],
              "lifecycle_status": "APPROVED"},
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 422


def test_version_conflict_on_submit(client, db):
    ctx = Ctx(db, "C21")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    resp = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"] + 3)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CORRECTION_VERSION_CONFLICT"


def test_patch_resets_prior_approvals(client, db):
    ctx = Ctx(db, "C22")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    # WELDER требует SMR+ОГС: после SMR approve остаётся SUBMITTED (ОГС ещё PENDING).
    corr = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder2.id)},
    ).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    corr = _cmd(client, ctx, corr["id"], "smr-approve", ctx.master,
                expected_record_version=corr["record_version"]).json()
    assert corr["smr_approval_status"] == "APPROVED"
    # ОГС возвращает на доработку → DRAFT, но SMR ещё APPROVED.
    corr = _cmd(client, ctx, corr["id"], "ogs-return", ctx.ogs,
                expected_record_version=corr["record_version"], comment="уточните").json()
    assert corr["lifecycle_status"] == "DRAFT"
    assert corr["smr_approval_status"] == "APPROVED"
    # Правка черновика сбрасывает прежнее согласование СМР (§14).
    resp = client.patch(
        f"{ENGINEERING_URL}/weld-operation-corrections/{corr['id']}",
        json={"expected_record_version": corr["record_version"],
              "patch": {"actual_welder_id": str(ctx.welder.id),
                        "entered_stamp_code": "NEWSTAMP"}},
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["smr_approval_status"] == "PENDING"


# ── 21.4 Матрица согласований ─────────────────────────────────────────────────


def test_data_correction_ready_after_smr_only(client, db):
    ctx = Ctx(db, "C23")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    assert corr["ogs_review_status"] == "NOT_REQUIRED"
    resp = _cmd(client, ctx, corr["id"], "smr-approve", ctx.master,
                expected_record_version=corr["record_version"])
    body = resp.json()
    assert body["lifecycle_status"] == "APPROVED"
    assert body["application_status"] == "READY_TO_APPLY"


def test_welder_correction_needs_both_approvals(client, db):
    ctx = Ctx(db, "C24")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder2.id)},
    ).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    corr = _cmd(client, ctx, corr["id"], "smr-approve", ctx.master,
                expected_record_version=corr["record_version"]).json()
    # Только SMR — ещё не готова.
    assert corr["lifecycle_status"] == "SUBMITTED"
    assert corr["application_status"] == "NOT_READY"
    resp = _cmd(client, ctx, corr["id"], "ogs-accept", ctx.ogs,
                expected_record_version=corr["record_version"],
                decision="ACCEPTED", comment="ок")
    body = resp.json()
    assert body["lifecycle_status"] == "APPROVED"
    assert body["application_status"] == "READY_TO_APPLY"


def test_ogs_command_rejected_when_not_required(client, db):
    ctx = Ctx(db, "C25")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    resp = _cmd(client, ctx, corr["id"], "ogs-accept", ctx.ogs,
                expected_record_version=corr["record_version"], decision="ACCEPTED")
    assert resp.status_code == 409


# ── 21.5 Атомарное применение ─────────────────────────────────────────────────


def test_apply_supersedes_source_and_activates_replacement(client, db):
    ctx = Ctx(db, "C26")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="SUPERSEDE_RECORD",
        patch={"welding_position": "PA"},
    ).json()
    repl_id = corr["replacement_operation_id"]
    before_after = corr["after_snapshot"]
    corr = _drive_to_ready(client, ctx, corr)
    resp = _cmd(client, ctx, corr["id"], "apply", ctx.master,
                expected_record_version=corr["record_version"],
                expected_source_record_version=op["record_version"])
    assert resp.status_code == 200, resp.text
    applied = resp.json()
    assert applied["lifecycle_status"] == "APPLIED"
    assert applied["application_status"] == "APPLIED"
    assert applied["after_snapshot"] == before_after  # snapshots не меняются
    src = _get_op(client, ctx, op["id"])
    repl = _get_op(client, ctx, repl_id)
    assert src["lifecycle_status"] == "SUPERSEDED"
    assert src["superseded_by_operation_id"] == repl_id
    assert repl["lifecycle_status"] == "COMPLETED"
    assert repl["supersedes_operation_id"] == op["id"]


def test_cancel_false_record_apply_cancels_source(client, db):
    ctx = Ctx(db, "C27")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="CANCEL_FALSE_RECORD",
        reason="ложная запись",
    ).json()
    corr = _drive_to_ready(client, ctx, corr)
    resp = _cmd(client, ctx, corr["id"], "apply", ctx.master,
                expected_record_version=corr["record_version"],
                expected_source_record_version=op["record_version"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["replacement_operation_id"] is None
    src = _get_op(client, ctx, op["id"])
    assert src["lifecycle_status"] == "CANCELLED"


def test_failed_apply_preserves_source(client, db, monkeypatch):
    ctx = Ctx(db, "C28")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="SUPERSEDE_RECORD",
        patch={"welding_position": "PA"},
    ).json()
    repl_id = corr["replacement_operation_id"]
    corr = _drive_to_ready(client, ctx, corr)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        eng_services.WeldOperationService, "_link_supersede", staticmethod(boom)
    )
    resp = _cmd(client, ctx, corr["id"], "apply", ctx.master,
                expected_record_version=corr["record_version"],
                expected_source_record_version=op["record_version"])
    assert resp.status_code == 200, resp.text
    applied = resp.json()
    assert applied["application_status"] == "FAILED"
    assert applied["application_attempts"] == 3
    assert applied["lifecycle_status"] == "APPROVED"
    assert applied["smr_approval_status"] == "APPROVED"
    # Источник и замена не тронуты.
    assert _get_op(client, ctx, op["id"])["lifecycle_status"] == "COMPLETED"
    assert _get_op(client, ctx, repl_id)["lifecycle_status"] == "DRAFT"


def test_reapply_is_idempotent(client, db):
    ctx = Ctx(db, "C29")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    repl_id = corr["replacement_operation_id"]
    corr = _drive_to_ready(client, ctx, corr)
    r1 = _cmd(client, ctx, corr["id"], "apply", ctx.master,
              expected_record_version=corr["record_version"],
              expected_source_record_version=op["record_version"])
    assert r1.status_code == 200
    applied = r1.json()
    r2 = _cmd(client, ctx, corr["id"], "apply", ctx.master,
              expected_record_version=applied["record_version"],
              expected_source_record_version=op["record_version"])
    assert r2.status_code == 200
    assert r2.json()["lifecycle_status"] == "APPLIED"
    assert r2.json()["replacement_operation_id"] == repl_id


def test_stale_correction_version_on_apply(client, db):
    ctx = Ctx(db, "C30")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    corr = _drive_to_ready(client, ctx, corr)
    resp = _cmd(client, ctx, corr["id"], "apply", ctx.master,
                expected_record_version=corr["record_version"] + 9,
                expected_source_record_version=op["record_version"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CORRECTION_VERSION_CONFLICT"


# ── 21.6 Неизменяемость ───────────────────────────────────────────────────────


def test_completed_operation_cannot_be_patched(client, db):
    ctx = Ctx(db, "C31")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = client.patch(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}",
        json={"expected_record_version": op["record_version"],
              "operation_note": "прямое редактирование"},
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_COMPLETED"


def test_superseded_operation_cannot_be_corrected(client, db):
    ctx = Ctx(db, "C32")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    corr = _drive_to_ready(client, ctx, corr)
    _cmd(client, ctx, corr["id"], "apply", ctx.master,
         expected_record_version=corr["record_version"],
         expected_source_record_version=op["record_version"])
    src = _get_op(client, ctx, op["id"])
    resp = _create_corr(
        client, ctx, src, patch={"operation_note": "снова"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SOURCE_OPERATION_NOT_CORRECTABLE"


def test_correction_history_preserved(client, db):
    ctx = Ctx(db, "C33")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(client, ctx, op, patch={"operation_note": "a"}).json()
    _cmd(client, ctx, corr["id"], "submit", ctx.master,
         expected_record_version=corr["record_version"])
    corr2 = _cmd(client, ctx, corr["id"], "smr-reject", ctx.master,
                 expected_record_version=corr["record_version"] + 1, comment="нет")
    # После REJECTED создаём новую и убеждаемся, что история содержит обе.
    _create_corr(client, ctx, op, patch={"operation_note": "b"})
    resp = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}/corrections",
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ── 21.8 Права и scope ────────────────────────────────────────────────────────


def test_foreman_can_create_correction(client, db):
    ctx = Ctx(db, "C34")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(client, ctx, op, worker=ctx.foreman,
                        patch={"operation_note": "a"})
    assert resp.status_code == 201


def test_foreign_project_scope_denied(client, db):
    ctx = Ctx(db, "C35")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    other = _role_worker(db, "C35Other", "MASTER",
                         scope_type="PROJECT", scope_id=str(uuid4()))
    resp = _create_corr(client, ctx, op, worker=other, patch={"operation_note": "a"})
    assert resp.status_code == 403


def test_master_cannot_ogs_review(client, db):
    ctx = Ctx(db, "C36")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    corr = _create_corr(
        client, ctx, op, correction_type="WELDER_CORRECTION",
        patch={"actual_welder_id": str(ctx.welder2.id)},
    ).json()
    corr = _cmd(client, ctx, corr["id"], "submit", ctx.master,
                expected_record_version=corr["record_version"]).json()
    corr = _cmd(client, ctx, corr["id"], "smr-approve", ctx.master,
                expected_record_version=corr["record_version"]).json()
    resp = _cmd(client, ctx, corr["id"], "ogs-accept", ctx.master,
                expected_record_version=corr["record_version"], decision="ACCEPTED")
    assert resp.status_code == 403


def test_chief_welder_admin_access(client, db):
    ctx = Ctx(db, "C37")
    ctx.prepare_joint(client)
    op = ctx.completed_op(client)
    resp = _create_corr(client, ctx, op, worker=ctx.chief,
                        patch={"operation_note": "a"})
    assert resp.status_code == 201
