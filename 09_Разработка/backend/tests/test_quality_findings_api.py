"""Интеграционные тесты ядра QualityFinding (Task 9D-1, ADR-019 / Session 008-07).

Покрывают: создание черновика, проектную нумерацию `<CODE>-QF-<SEQUENCE>` при
регистрации, базовый lifecycle (DRAFT → REGISTERED → UNDER_EVALUATION, отмена,
удаление DRAFT), неизменяемость наблюдения после регистрации, валидацию источника
контроля (joint-match), RBAC (создание/подтверждение/отмена), optimistic locking,
scope-видимость, журнал событий и список по стыку.

EngineeringEvaluation, Defect, disposition, holds и дочерние сущности finding
(блоки 9D-2 … 9D-6) здесь не моделируются.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project
from app.quality.models import Inspection, QualityFinding
from app.engineering.models import DocumentRevision, EngineeringDocument

from .conftest import TEST_COMPANY_ID

ENG = "/api/v1/engineering"
API = "/api/v1"
FINDINGS = f"{API}/quality/findings"
TODAY = date.today()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Qf{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=TODAY,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _role_worker(
    db: Session,
    suffix: str,
    role_code: str,
    *,
    scope_type: str = "GLOBAL",
    scope_id: str | None = None,
) -> Worker:
    w = _worker(db, suffix)
    role = WorkerRole(
        worker_id=w.id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=True,
        valid_from=TODAY,
    )
    db.add(role)
    db.commit()
    return w


class FindCtx:
    """Проект/линия/документ/ревизия, роли и стык для тестов finding."""

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

        self.pto = _role_worker(db, f"{code}P", "PTO_ENGINEER")
        self.ogs = _role_worker(db, f"{code}O", "OGS_ENGINEER")
        self.chief = _role_worker(db, f"{code}C", "CHIEF_WELDER")
        self.otk = _role_worker(db, f"{code}K", "OTK_INSPECTOR")
        self.ndt = _role_worker(db, f"{code}N", "NDT_SPECIALIST")
        self.norole = _worker(db, f"{code}Z")

    def h(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def create_joint(self, client: TestClient, joint_no: str) -> str:
        payload = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": joint_no,
            "created_by": self.creator.id,
        }
        resp = client.post(f"{ENG}/joints", json=payload, headers=self.h(self.pto))
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def make_inspection(self, joint_id: str, code: str) -> Inspection:
        """Прямая вставка Inspection (для проверки source joint-match)."""
        ins = Inspection(
            project_id=self.project.id,
            joint_id=joint_id,
            system_code=f"{self.project.code}-INS-{code}",
            status="DRAFT",
            request_reason="источник для finding",
            created_by_worker_id=self.creator.id,
            updated_by_worker_id=self.creator.id,
            version=1,
        )
        self.db.add(ins)
        self.db.commit()
        self.db.refresh(ins)
        return ins


def _finding_payload(ctx: FindCtx, joint_id: str, **over) -> dict:
    payload = {
        "project_id": str(ctx.project.id),
        "joint_id": joint_id,
        "origin_type": "INSPECTION_RESULT",
        "initial_risk": "HIGH",
        "observation": "Обнаружена недопустимая индикация в корне шва",
    }
    payload.update(over)
    return payload


def _create(ctx: FindCtx, client: TestClient, joint_id: str, actor=None, **over):
    actor = actor or ctx.ogs
    return client.post(
        FINDINGS, json=_finding_payload(ctx, joint_id, **over), headers=ctx.h(actor)
    )


def _register(ctx: FindCtx, client: TestClient, fid: str, version: int, actor=None):
    actor = actor or ctx.ogs
    return client.post(
        f"{FINDINGS}/{fid}/register",
        json={"expected_version": version},
        headers=ctx.h(actor),
    )


# ── Создание и базовый lifecycle ──────────────────────────────────────────────


def test_create_finding_is_draft_without_number(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFA")
    joint = ctx.create_joint(client, "J-1")
    r = _create(ctx, client, joint, actor=ctx.ndt)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["system_code"] is None
    assert body["origin_type"] == "INSPECTION_RESULT"
    assert body["initial_risk"] == "HIGH"
    assert body["version"] == 1


def test_register_assigns_project_number_and_increments(
    client: TestClient, db: Session
):
    ctx = FindCtx(db, "QFB")
    joint = ctx.create_joint(client, "J-1")
    f1 = _create(ctx, client, joint).json()
    r1 = _register(ctx, client, f1["id"], f1["version"])
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["status"] == "REGISTERED"
    assert b1["system_code"] == "QFB-QF-1"
    assert b1["registered_by_worker_id"] == ctx.ogs.id
    assert b1["version"] == 2

    f2 = _create(ctx, client, joint).json()
    b2 = _register(ctx, client, f2["id"], f2["version"]).json()
    assert b2["system_code"] == "QFB-QF-2"


def test_full_lifecycle_register_acknowledge(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFC")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    ack = client.post(
        f"{FINDINGS}/{f['id']}/acknowledge",
        json={"expected_version": reg["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert ack.status_code == 200, ack.text
    body = ack.json()
    assert body["status"] == "UNDER_EVALUATION"
    assert body["acknowledged_by_worker_id"] == ctx.ogs.id


def test_cancel_from_registered(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFD")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    r = client.post(
        f"{FINDINGS}/{f['id']}/cancel",
        json={"expected_version": reg["version"], "reason": "дубль записи"},
        headers=ctx.h(ctx.chief),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELLED"
    assert r.json()["cancellation_reason"] == "дубль записи"


def test_cancel_from_under_evaluation(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFE")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    ack = client.post(
        f"{FINDINGS}/{f['id']}/acknowledge",
        json={"expected_version": reg["version"]},
        headers=ctx.h(ctx.ogs),
    ).json()
    r = client.post(
        f"{FINDINGS}/{f['id']}/cancel",
        json={"expected_version": ack["version"], "reason": "ошибочно заведён"},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELLED"


def test_delete_draft(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFF")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    r = client.delete(
        f"{FINDINGS}/{f['id']}",
        params={"expected_version": f["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 204, r.text
    assert db.query(QualityFinding).filter(
        QualityFinding.id == f["id"]
    ).first() is None


# ── Источник контроля (joint-match) ───────────────────────────────────────────


def test_source_inspection_same_joint_ok(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFG")
    joint = ctx.create_joint(client, "J-1")
    ins = ctx.make_inspection(joint, "1")
    r = _create(ctx, client, joint, inspection_id=str(ins.id))
    assert r.status_code == 201, r.text
    assert r.json()["inspection_id"] == str(ins.id)


def test_source_inspection_other_joint_rejected(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFH")
    joint_a = ctx.create_joint(client, "J-A")
    joint_b = ctx.create_joint(client, "J-B")
    ins_b = ctx.make_inspection(joint_b, "1")
    r = _create(ctx, client, joint_a, inspection_id=str(ins_b.id))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "FINDING_SOURCE_JOINT_MISMATCH"


def test_source_inspection_not_found(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFI")
    joint = ctx.create_joint(client, "J-1")
    r = _create(ctx, client, joint, inspection_id=str(uuid4()))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "FINDING_SOURCE_NOT_FOUND"


# ── Негативные переходы и неизменяемость ──────────────────────────────────────


def test_cancel_from_draft_invalid_transition(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFJ")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    r = client.post(
        f"{FINDINGS}/{f['id']}/cancel",
        json={"expected_version": f["version"], "reason": "нельзя"},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_INVALID_TRANSITION"


def test_register_non_draft_invalid_transition(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFK")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    r = _register(ctx, client, f["id"], reg["version"])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_INVALID_TRANSITION"


def test_acknowledge_non_registered_rejected(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFL")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    r = client.post(
        f"{FINDINGS}/{f['id']}/acknowledge",
        json={"expected_version": f["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_NOT_REGISTERED"


def test_observation_immutable_after_register(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFM")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    r = client.patch(
        f"{FINDINGS}/{f['id']}",
        json={"observation": "правка", "expected_version": reg["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_NOT_DRAFT"


def test_update_draft_ok(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFN")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    r = client.patch(
        f"{FINDINGS}/{f['id']}",
        json={
            "observation": "уточнённое наблюдение",
            "initial_risk": "CRITICAL",
            "expected_version": f["version"],
        },
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200, r.text
    assert r.json()["observation"] == "уточнённое наблюдение"
    assert r.json()["initial_risk"] == "CRITICAL"
    assert r.json()["version"] == 2


def test_delete_non_draft_rejected(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFO")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    r = client.delete(
        f"{FINDINGS}/{f['id']}",
        params={"expected_version": reg["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_NOT_DRAFT"


def test_cancel_already_cancelled(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFP")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    c1 = client.post(
        f"{FINDINGS}/{f['id']}/cancel",
        json={"expected_version": reg["version"], "reason": "дубль"},
        headers=ctx.h(ctx.ogs),
    ).json()
    r = client.post(
        f"{FINDINGS}/{f['id']}/cancel",
        json={"expected_version": c1["version"], "reason": "ещё раз"},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_ALREADY_CANCELLED"


def test_version_conflict(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFQ")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    r = _register(ctx, client, f["id"], f["version"] + 5)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "FINDING_VERSION_CONFLICT"


def test_project_mismatch(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFR")
    joint = ctx.create_joint(client, "J-1")
    r = client.post(
        FINDINGS,
        json=_finding_payload(ctx, joint, project_id=str(uuid4())),
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "FINDING_PROJECT_MISMATCH"


def test_duplicate_external_no(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFS")
    joint = ctx.create_joint(client, "J-1")
    r1 = _create(ctx, client, joint, external_no="EXT-1")
    assert r1.status_code == 201, r1.text
    r2 = _create(ctx, client, joint, external_no="EXT-1")
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "FINDING_DUPLICATE_EXTERNAL_NO"


# ── RBAC ───────────────────────────────────────────────────────────────────────


def test_create_denied_without_role(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFT")
    joint = ctx.create_joint(client, "J-1")
    r = _create(ctx, client, joint, actor=ctx.norole)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FINDING_ROLE_DENIED"


def test_acknowledge_denied_for_ndt(client: TestClient, db: Session):
    """НК может создать/зарегистрировать finding, но подтверждение получения —
    только контур ОГС (CHIEF_WELDER / OGS_ENGINEER)."""
    ctx = FindCtx(db, "QFU")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint, actor=ctx.ndt).json()
    reg = _register(ctx, client, f["id"], f["version"], actor=ctx.ndt).json()
    r = client.post(
        f"{FINDINGS}/{f['id']}/acknowledge",
        json={"expected_version": reg["version"]},
        headers=ctx.h(ctx.ndt),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FINDING_ROLE_DENIED"


def test_otk_can_create(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFV")
    joint = ctx.create_joint(client, "J-1")
    r = _create(ctx, client, joint, actor=ctx.otk)
    assert r.status_code == 201, r.text


def test_hidden_by_scope_returns_404(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFW")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    r = client.get(f"{FINDINGS}/{f['id']}", headers=ctx.h(ctx.norole))
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "FINDING_NOT_FOUND"


# ── Список, стык, события ─────────────────────────────────────────────────────


def test_list_by_joint(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFX")
    joint_a = ctx.create_joint(client, "J-A")
    joint_b = ctx.create_joint(client, "J-B")
    _create(ctx, client, joint_a)
    _create(ctx, client, joint_a)
    _create(ctx, client, joint_b)
    r = client.get(
        f"{API}/joints/{joint_a}/quality-findings", headers=ctx.h(ctx.ogs)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert all(item["joint_id"] == joint_a for item in body["items"])


def test_list_with_status_filter(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFY")
    joint = ctx.create_joint(client, "J-1")
    f1 = _create(ctx, client, joint).json()
    _register(ctx, client, f1["id"], f1["version"])
    _create(ctx, client, joint)  # остаётся DRAFT
    r = client.get(
        FINDINGS,
        params={"joint_id": joint, "status": "REGISTERED"},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["status"] == "REGISTERED"


def test_events_journal(client: TestClient, db: Session):
    ctx = FindCtx(db, "QFZ")
    joint = ctx.create_joint(client, "J-1")
    f = _create(ctx, client, joint).json()
    reg = _register(ctx, client, f["id"], f["version"]).json()
    client.post(
        f"{FINDINGS}/{f['id']}/acknowledge",
        json={"expected_version": reg["version"]},
        headers=ctx.h(ctx.ogs),
    )
    r = client.get(f"{FINDINGS}/{f['id']}/events", headers=ctx.h(ctx.ogs))
    assert r.status_code == 200, r.text
    types = [e["event_type"] for e in r.json()]
    assert types == ["CREATED", "REGISTERED", "ACKNOWLEDGED"]


def test_reject_unknown_field(client: TestClient, db: Session):
    ctx = FindCtx(db, "QF0")
    joint = ctx.create_joint(client, "J-1")
    r = client.post(
        FINDINGS,
        json=_finding_payload(ctx, joint, status="REGISTERED"),
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 422
