"""API-тесты слоя Quality Execution и LaboratoryConclusion (Task 9C, блок 9C-6B).

Проверяют транспортный слой поверх сервисов через TestClient: успешные сценарии,
404 (скрытый scope), 403 (нет роли), 409 (optimistic lock), 422 (schema validation)
и проброс DomainError (detail.code). Бизнес-логику проверяют сервисные тесты.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality.execution_models import QualityExternalPerson

from .test_inspection_method_assignments import Ctx

API = "/api/v1"
TODAY = date.today()


def _person(db: Session, ctx: Ctx) -> QualityExternalPerson:
    p = QualityExternalPerson(
        full_name="API лицо",
        organization_company_id=ctx.lab.id,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _assignment_id(client: TestClient, ctx: Ctx, joint_no: str) -> str:
    iid = ctx.inspection(client, joint_no)
    return ctx.assign(client, ctx.otk, iid, method="UT")["id"]


def _confirm_execution(client: TestClient, db: Session, ctx: Ctx, joint_no: str):
    """Полный путь выполнения до LAB_CONFIRMED через API. Возвращает JSON."""
    h = ctx.h(ctx.otk)
    person = _person(db, ctx)
    aid = _assignment_id(client, ctx, joint_no)
    r = client.post(f"{API}/method-assignments/{aid}/executions", json={}, headers=h)
    assert r.status_code == 201, r.text
    ex = r.json()
    eid = ex["id"]
    r = client.post(
        f"{API}/method-executions/{eid}/participants",
        json={"person_id": str(person.id), "participant_role": "LEAD_INSPECTOR"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{API}/method-executions/{eid}/result-items",
        json={"controlled_object_type": "WHOLE_JOINT", "evaluation": "CONFORMING"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]
    r = client.post(f"{API}/method-result-items/{item_id}/complete", headers=h)
    assert r.status_code == 200, r.text

    v = ex["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/start",
        json={"expected_version": v}, headers=h,
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/mark-performed",
        json={"expected_version": v, "performed_date": str(TODAY)}, headers=h,
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/record-result",
        json={"expected_version": v}, headers=h,
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/confirm",
        json={"expected_version": v, "laboratory_evaluation": "CONFORMING"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Успешные сценарии ───────────────────────────────────────────────────────────


def test_execution_full_flow(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "API1")
    ex = _confirm_execution(client, db, ctx, "J-api1")
    assert ex["status"] == "LAB_CONFIRMED"
    assert ex["is_current"] is True

    r = client.get(
        f"{API}/method-executions/{ex['id']}", headers=ctx.h(ctx.otk)
    )
    assert r.status_code == 200
    assert r.json()["id"] == ex["id"]

    r = client.get(
        f"{API}/method-assignments/{ex['inspection_method_assignment_id']}/executions",
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 200
    assert any(item["id"] == ex["id"] for item in r.json())


def test_conclusion_full_flow(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "API2")
    h = ctx.h(ctx.otk)
    ex = _confirm_execution(client, db, ctx, "J-api2")
    approver = _person(db, ctx)
    r = client.post(
        f"{API}/laboratory-conclusions",
        json={
            "project_id": str(ctx.project.id),
            "laboratory_company_id": ctx.lab.id,
            "inspection_method_id": "UT",
            "lab_approver_person_id": str(approver.id),
            "issued_by_person_id": str(approver.id),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    c = r.json()
    cid = c["id"]
    assert c["status"] == "DRAFT"

    r = client.post(
        f"{API}/laboratory-conclusions/{cid}/executions",
        json={"method_execution_id": ex["id"]}, headers=h,
    )
    assert r.status_code == 201, r.text

    v = c["version"]
    r = client.post(
        f"{API}/laboratory-conclusions/{cid}/prepare",
        json={"expected_version": v}, headers=h,
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    r = client.post(
        f"{API}/laboratory-conclusions/{cid}/approve",
        json={"expected_version": v}, headers=h,
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    r = client.post(
        f"{API}/laboratory-conclusions/{cid}/issue",
        json={"expected_version": v, "conclusion_number": "API-1", "conclusion_year": 2026},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ISSUED"

    # Редакция + список редакций через API.
    issued = r.json()
    r = client.post(
        f"{API}/laboratory-conclusions/{cid}/revisions",
        json={"expected_version": issued["version"], "correction_reason": "правка"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["revision_no"] == 2
    r = client.get(
        f"{API}/laboratory-conclusions/{cid}/revisions", headers=h
    )
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── 404 скрытый scope ───────────────────────────────────────────────────────────


def test_get_execution_hidden_scope_404(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "API3")
    ex = _confirm_execution(client, db, ctx, "J-api3")
    r = client.get(
        f"{API}/method-executions/{ex['id']}", headers=ctx.h(ctx.norole)
    )
    assert r.status_code == 404


# ── 403 нет роли ────────────────────────────────────────────────────────────────


def test_create_execution_role_denied_403(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "API4")
    aid = _assignment_id(client, ctx, "J-api4")
    r = client.post(
        f"{API}/method-assignments/{aid}/executions",
        json={}, headers=ctx.h(ctx.pto),  # PTO: read, но не write
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "EXECUTION_ROLE_DENIED"


# ── 409 optimistic lock ─────────────────────────────────────────────────────────


def test_optimistic_lock_409(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "API5")
    aid = _assignment_id(client, ctx, "J-api5")
    h = ctx.h(ctx.otk)
    r = client.post(f"{API}/method-assignments/{aid}/executions", json={}, headers=h)
    eid = r.json()["id"]
    r = client.post(
        f"{API}/method-executions/{eid}/start",
        json={"expected_version": 999}, headers=h,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EXECUTION_VERSION_CONFLICT"


# ── 422 schema validation ───────────────────────────────────────────────────────


def test_schema_validation_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "API6")
    aid = _assignment_id(client, ctx, "J-api6")
    h = ctx.h(ctx.otk)
    r = client.post(
        f"{API}/method-assignments/{aid}/executions",
        json={"time_precision": "BOGUS"}, headers=h,
    )
    assert r.status_code == 422
    # Команда без обязательного expected_version.
    r2 = client.post(f"{API}/laboratory-conclusions", json={}, headers=h)
    assert r2.status_code == 422


# ── DomainError mapping (detail.code) ───────────────────────────────────────────


def test_domain_error_mapping_no_result_items(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "API7")
    aid = _assignment_id(client, ctx, "J-api7")
    h = ctx.h(ctx.otk)
    r = client.post(f"{API}/method-assignments/{aid}/executions", json={}, headers=h)
    ex = r.json()
    eid, v = ex["id"], ex["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/start",
        json={"expected_version": v}, headers=h,
    )
    v = r.json()["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/mark-performed",
        json={"expected_version": v, "performed_date": str(TODAY)}, headers=h,
    )
    v = r.json()["version"]
    r = client.post(
        f"{API}/method-executions/{eid}/record-result",
        json={"expected_version": v}, headers=h,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EXECUTION_NO_RESULT_ITEMS"


def test_domain_error_mapping_conclusion_no_executions(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "API8")
    h = ctx.h(ctx.otk)
    person = _person(db, ctx)
    r = client.post(
        f"{API}/laboratory-conclusions",
        json={
            "project_id": str(ctx.project.id),
            "laboratory_company_id": ctx.lab.id,
            "inspection_method_id": "UT",
            "lab_approver_person_id": str(person.id),
            "issued_by_person_id": str(person.id),
        },
        headers=h,
    )
    c = r.json()
    r = client.post(
        f"{API}/laboratory-conclusions/{c['id']}/prepare",
        json={"expected_version": c["version"]}, headers=h,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CONCLUSION_NO_EXECUTIONS"
