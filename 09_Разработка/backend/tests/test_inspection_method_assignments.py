"""Интеграционные тесты назначения методов контроля (Task 9B, ADR-015 / Session 007).

Покрывают: создание назначения (методы, лаборатория, actor-поля, дубли), чтение и
scope, ограниченный PATCH примечаний, отмену, атомарную замену, RBAC/scope и
сводку готовности Inspection. Выполнение метода и результаты контроля (Tasks 9C–9G)
здесь не моделируются.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.projects.models import Company, Line, Project, ProjectCompany
from app.quality.models import Inspection, InspectionMethodAssignment
from app.quality.repository import QualityRepo
from app.shared.db import SessionLocal

from .conftest import TEST_COMPANY_ID

ENG = "/api/v1/engineering"
API = "/api/v1"
TODAY = date.today()


def _worker(db: Session, suffix: str):
    from app.hr.models import Worker

    worker = Worker(
        last_name=f"Ima{suffix}",
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
    is_active: bool = True,
    valid_to: date | None = None,
):
    from app.hr.models import WorkerRole

    w = _worker(db, suffix)
    role = WorkerRole(
        worker_id=w.id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=is_active,
        valid_from=TODAY,
        valid_to=valid_to,
    )
    db.add(role)
    db.commit()
    return w


class Ctx:
    """Проект/линия/документ/ревизия, роли и лаборатории для назначений."""

    def __init__(self, db: Session, code: str) -> None:
        from app.engineering.models import DocumentRevision, EngineeringDocument

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
        self.foreman = _role_worker(db, f"{code}F", "FOREMAN")
        self.master = _role_worker(db, f"{code}M", "MASTER")
        self.norole = _worker(db, f"{code}Z")

        # Лаборатория НК проекта (действующая связь role_code NDT_LAB).
        self.lab = self._company(f"Лаб {code}")
        self._link(self.lab, "NDT_LAB")
        # Вторая лаборатория проекта (для замены лаборатории).
        self.lab2 = self._company(f"Лаб2 {code}")
        self._link(self.lab2, "NDT_LAB")
        # Компания проекта с иной ролью (не лаборатория).
        self.nonlab = self._company(f"Подрядчик {code}")
        self._link(self.nonlab, "WELDING_CONTRACTOR")

    def _company(self, name: str) -> Company:
        c = Company(name=name, status="active", created_by=self.creator.id)
        self.db.add(c)
        self.db.commit()
        self.db.refresh(c)
        return c

    def _link(self, company: Company, role_code: str) -> None:
        self.db.add(
            ProjectCompany(
                project_id=self.project.id, company_id=company.id,
                role_code=role_code, valid_from=TODAY,
            )
        )
        self.db.commit()

    def h(self, worker) -> dict[str, str]:
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

    def inspection(
        self, client: TestClient, joint_no: str, *, status: str = "REQUESTED"
    ) -> str:
        """Заявка нужного статуса напрямую (назначение не зависит от readiness)."""
        joint_id = self.create_joint(client, joint_no)
        now = datetime.now(timezone.utc)
        seq = QualityRepo(self.db).next_inspection_sequence(self.project.id)
        fields = dict(
            project_id=self.project.id,
            joint_id=UUID(joint_id),
            system_code=f"{self.project.code}-INS-{seq}",
            status=status,
            request_reason="прямая вставка (Task 9B тесты)",
            created_by_worker_id=self.ogs.id,
            updated_by_worker_id=self.ogs.id,
            version=1,
        )
        if status not in ("DRAFT", "CANCELLED"):
            fields.update(
                requested_at=now, requested_by_worker_id=self.ogs.id,
                ogs_readiness_confirmed_at=now,
                ogs_readiness_confirmed_by_worker_id=self.ogs.id,
            )
        if status == "CANCELLED":
            fields.update(
                cancelled_at=now, cancelled_by_worker_id=self.ogs.id,
                cancellation_reason="отменена",
            )
        ins = Inspection(**fields)
        self.db.add(ins)
        self.db.commit()
        self.db.refresh(ins)
        return str(ins.id)

    def create_assignment(
        self,
        client: TestClient,
        worker,
        inspection_id: str,
        *,
        method: str = "UT",
        lab_id: int | None = None,
        **extra,
    ):
        body: dict = {
            "method_code": method,
            "laboratory_company_id": lab_id if lab_id is not None else self.lab.id,
        }
        body.update(extra)
        return client.post(
            f"{API}/inspections/{inspection_id}/method-assignments",
            json=body, headers=self.h(worker),
        )

    def assign(self, client: TestClient, worker, inspection_id: str, **kw) -> dict:
        r = self.create_assignment(client, worker, inspection_id, **kw)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def ctx(db: Session) -> Ctx:
    return Ctx(db, "MA600")


# ── Создание ────────────────────────────────────────────────────────────────────


def test_create_assignment_success(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.otk, iid, method="UT")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["inspection_id"] == iid
    assert body["method_code"] == "UT"
    assert body["laboratory_company_id"] == ctx.lab.id
    assert body["status"] == "ASSIGNED"
    assert body["version"] == 1
    assert body["assigned_by_worker_id"] == ctx.otk.id
    assert body["assigned_at"] is not None
    assert body["is_active"] is True
    assert body["laboratory_company_name"] == ctx.lab.name
    assert body["replaced_by_assignment_id"] is None


@pytest.mark.parametrize("method", ["VT", "RT", "UT", "PT", "MT", "LT"])
def test_create_each_method(ctx: Ctx, client: TestClient, method: str) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.ndt, iid, method=method)
    assert r.status_code == 201, r.text
    assert r.json()["method_code"] == method


def test_create_invalid_method_rejected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.otk, iid, method="XX")
    assert r.status_code == 422  # enum


def test_create_notes_stored(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    body = ctx.assign(
        client, ctx.otk, iid,
        laboratory_note="снаружи", assignment_note="срочно",
    )
    assert body["laboratory_note"] == "снаружи"
    assert body["assignment_note"] == "срочно"


def test_create_company_not_a_lab(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.otk, iid, lab_id=ctx.nonlab.id)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ASSIGNMENT_COMPANY_NOT_PROJECT_LABORATORY"


def test_create_lab_from_other_project(ctx: Ctx, client: TestClient) -> None:
    other = Ctx(ctx.db, "MA700")
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.otk, iid, lab_id=other.lab.id)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ASSIGNMENT_COMPANY_NOT_PROJECT_LABORATORY"


def test_create_nonexistent_company(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.otk, iid, lab_id=987654321)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "ASSIGNMENT_LABORATORY_NOT_FOUND"


def test_create_inactive_lab(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    ctx.lab.status = "inactive"
    ctx.db.commit()
    r = ctx.create_assignment(client, ctx.otk, iid, lab_id=ctx.lab.id)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_LABORATORY_INACTIVE"


def test_create_nonexistent_inspection(ctx: Ctx, client: TestClient) -> None:
    r = client.post(
        f"{API}/inspections/{uuid4()}/method-assignments",
        json={"method_code": "UT", "laboratory_company_id": ctx.lab.id},
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "INSPECTION_NOT_FOUND"


def test_create_on_cancelled_inspection(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1", status="CANCELLED")
    r = ctx.create_assignment(client, ctx.otk, iid)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_INSPECTION_NOT_ASSIGNABLE"


def test_duplicate_active_method_rejected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    ctx.assign(client, ctx.otk, iid, method="UT")
    r = ctx.create_assignment(client, ctx.otk, iid, method="UT")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_DUPLICATE_ACTIVE_METHOD"


def test_different_methods_same_inspection(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    ctx.assign(client, ctx.otk, iid, method="UT")
    r = ctx.create_assignment(client, ctx.otk, iid, method="RT")
    assert r.status_code == 201, r.text


def test_same_method_different_inspections(ctx: Ctx, client: TestClient) -> None:
    i1 = ctx.inspection(client, "J-1")
    i2 = ctx.inspection(client, "J-2")
    ctx.assign(client, ctx.otk, i1, method="UT")
    r = ctx.create_assignment(client, ctx.otk, i2, method="UT")
    assert r.status_code == 201, r.text


def test_client_cannot_set_status(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    r = client.post(
        f"{API}/inspections/{iid}/method-assignments",
        json={
            "method_code": "UT", "laboratory_company_id": ctx.lab.id,
            "status": "REPLACED",
        },
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 422  # extra=forbid


def test_concurrent_duplicate_active_method_db_guarded(
    ctx: Ctx, client: TestClient
) -> None:
    """Параллельное создание одного метода — только одно ASSIGNED (partial index)."""
    iid = ctx.inspection(client, "J-1")
    lab_id = ctx.lab.id
    otk_id = ctx.otk.id
    project_id = ctx.project.id

    def attempt() -> int:
        session = SessionLocal()
        try:
            from app.quality.method_assignment_services import (
                MethodAssignmentService,
            )
            from app.quality.schemas import MethodAssignmentCreate

            svc = MethodAssignmentService(session)
            try:
                svc.create_assignment(
                    UUID(iid),
                    MethodAssignmentCreate(
                        method_code="UT", laboratory_company_id=lab_id
                    ),
                    actor_worker_id=otk_id,
                )
                return 201
            except Exception as exc:  # noqa: BLE001
                return getattr(exc, "status_code", 500)
        finally:
            session.close()

    assert project_id is not None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    assert results.count(201) == 1
    active = (
        ctx.db.query(InspectionMethodAssignment)
        .filter(
            InspectionMethodAssignment.inspection_id == UUID(iid),
            InspectionMethodAssignment.status == "ASSIGNED",
        )
        .count()
    )
    assert active == 1


# ── Чтение и scope ────────────────────────────────────────────────────────────


def test_get_by_id(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.get(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(ctx.otk)
    )
    assert r.status_code == 200
    assert r.json()["id"] == a["id"]


def test_list_and_summary(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    ctx.assign(client, ctx.otk, iid, method="UT")
    ctx.assign(client, ctx.otk, iid, method="RT")
    r = client.get(
        f"{API}/inspections/{iid}/method-assignments", headers=ctx.h(ctx.otk)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["inspection_id"] == iid
    assert len(body["items"]) == 2
    assert body["has_method_assignments"] is True
    assert body["active_method_assignment_count"] == 2
    assert sorted(body["assigned_method_codes"]) == ["RT", "UT"]
    assert body["all_assignments_have_laboratory"] is True
    assert body["ready_for_execution"] is True


def test_summary_empty(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    r = client.get(
        f"{API}/inspections/{iid}/method-assignments", headers=ctx.h(ctx.otk)
    )
    body = r.json()
    assert body["has_method_assignments"] is False
    assert body["active_method_assignment_count"] == 0
    assert body["ready_for_execution"] is False


def test_list_active_only_filter(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT")
    client.post(
        f"{API}/inspection-method-assignments/{a['id']}/cancel",
        json={"expected_version": 1, "reason": "не нужен"}, headers=ctx.h(ctx.otk),
    )
    ctx.assign(client, ctx.otk, iid, method="RT")
    # active_only=true → только RT
    r = client.get(
        f"{API}/inspections/{iid}/method-assignments",
        params={"active_only": "true"}, headers=ctx.h(ctx.otk),
    )
    codes = [i["method_code"] for i in r.json()["items"]]
    assert codes == ["RT"]
    # Полный список сохраняет историю отменённого UT.
    r_all = client.get(
        f"{API}/inspections/{iid}/method-assignments", headers=ctx.h(ctx.otk)
    )
    all_codes = sorted(i["method_code"] for i in r_all.json()["items"])
    assert all_codes == ["RT", "UT"]


def test_list_status_filter(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT")
    client.post(
        f"{API}/inspection-method-assignments/{a['id']}/cancel",
        json={"expected_version": 1, "reason": "x"}, headers=ctx.h(ctx.otk),
    )
    r = client.get(
        f"{API}/inspections/{iid}/method-assignments",
        params={"status": "CANCELLED"}, headers=ctx.h(ctx.otk),
    )
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["status"] == "CANCELLED"


def test_get_scope_protected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    w = _role_worker(
        ctx.db, "OtherPrj", "OTK_INSPECTOR",
        scope_type="PROJECT", scope_id=str(uuid4()),
    )
    r = client.get(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(w)
    )
    assert r.status_code == 404


def test_get_nonexistent_assignment(ctx: Ctx, client: TestClient) -> None:
    r = client.get(
        f"{API}/inspection-method-assignments/{uuid4()}", headers=ctx.h(ctx.otk)
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "ASSIGNMENT_NOT_FOUND"


def test_read_role_can_view(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    # PTO имеет право чтения Inspection → видит назначение.
    r = client.get(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(ctx.pto)
    )
    assert r.status_code == 200


# ── Ограниченное обновление (§11) ──────────────────────────────────────────────


def test_patch_note(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.patch(
        f"{API}/inspection-method-assignments/{a['id']}",
        json={"assignment_note": "обновлено", "expected_version": 1},
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignment_note"] == "обновлено"
    assert body["version"] == 2


def test_patch_cannot_change_method(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.patch(
        f"{API}/inspection-method-assignments/{a['id']}",
        json={"method_code": "RT", "expected_version": 1},
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 422  # extra=forbid


def test_patch_cannot_change_laboratory(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.patch(
        f"{API}/inspection-method-assignments/{a['id']}",
        json={"laboratory_company_id": ctx.lab2.id, "expected_version": 1},
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 422


def test_patch_cannot_change_actor_or_status(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    for payload in (
        {"assigned_by_worker_id": 1, "expected_version": 1},
        {"status": "CANCELLED", "expected_version": 1},
        {"assigned_at": "2020-01-01T00:00:00Z", "expected_version": 1},
    ):
        r = client.patch(
            f"{API}/inspection-method-assignments/{a['id']}",
            json=payload, headers=ctx.h(ctx.otk),
        )
        assert r.status_code == 422, payload


def test_patch_version_conflict(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.patch(
        f"{API}/inspection-method-assignments/{a['id']}",
        json={"assignment_note": "x", "expected_version": 99},
        headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_VERSION_CONFLICT"


def test_patch_requires_expected_version(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.patch(
        f"{API}/inspection-method-assignments/{a['id']}",
        json={"assignment_note": "x"}, headers=ctx.h(ctx.otk),
    )
    assert r.status_code == 422


# ── Отмена (§12) ──────────────────────────────────────────────────────────────


def _cancel(ctx: Ctx, client: TestClient, aid: str, version: int, reason="не нужен"):
    return client.post(
        f"{API}/inspection-method-assignments/{aid}/cancel",
        json={"expected_version": version, "reason": reason},
        headers=ctx.h(ctx.otk),
    )


def test_cancel_success(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = _cancel(ctx, client, a["id"], 1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "CANCELLED"
    assert body["cancelled_by_worker_id"] == ctx.otk.id
    assert body["cancelled_at"] is not None
    assert body["cancellation_reason"] == "не нужен"
    assert body["is_active"] is False


def test_cancel_reason_required(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = _cancel(ctx, client, a["id"], 1, reason="   ")
    assert r.status_code == 422


def test_double_cancel_rejected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    _cancel(ctx, client, a["id"], 1)
    r = _cancel(ctx, client, a["id"], 2)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_ALREADY_CANCELLED"


def test_cancel_version_conflict(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = _cancel(ctx, client, a["id"], 99)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_VERSION_CONFLICT"


def test_reassign_same_method_after_cancel(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT")
    _cancel(ctx, client, a["id"], 1)
    r = ctx.create_assignment(client, ctx.otk, iid, method="UT")
    assert r.status_code == 201, r.text


def test_no_delete_endpoint(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.delete(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(ctx.otk)
    )
    assert r.status_code in (404, 405)


# ── Замена (§13) ──────────────────────────────────────────────────────────────


def _replace(ctx: Ctx, client: TestClient, aid: str, payload: dict):
    return client.post(
        f"{API}/inspection-method-assignments/{aid}/replace",
        json=payload, headers=ctx.h(ctx.otk),
    )


def test_replace_laboratory(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT", lab_id=ctx.lab.id)
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 1, "laboratory_company_id": ctx.lab2.id,
         "reason": "замена лаборатории"},
    )
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["status"] == "ASSIGNED"
    assert new["method_code"] == "UT"
    assert new["laboratory_company_id"] == ctx.lab2.id
    assert new["id"] != a["id"]
    # Старая запись → REPLACED со ссылкой на новую.
    old = client.get(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(ctx.otk)
    ).json()
    assert old["status"] == "REPLACED"
    assert old["replaced_by_assignment_id"] == new["id"]


def test_replace_method(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT")
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 1, "method_code": "RT", "reason": "смена метода"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["method_code"] == "RT"
    old = client.get(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(ctx.otk)
    ).json()
    assert old["status"] == "REPLACED"


def test_replace_reason_required(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 1, "laboratory_company_id": ctx.lab2.id, "reason": " "},
    )
    assert r.status_code == 422


def test_replace_no_change_rejected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT", lab_id=ctx.lab.id)
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 1, "method_code": "UT",
         "laboratory_company_id": ctx.lab.id, "reason": "ничего"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_NO_CHANGE"


def test_replace_cancelled_rejected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    _cancel(ctx, client, a["id"], 1)
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 2, "laboratory_company_id": ctx.lab2.id, "reason": "x"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_ALREADY_CANCELLED"


def test_replace_conflicts_with_existing_active_method(
    ctx: Ctx, client: TestClient
) -> None:
    iid = ctx.inspection(client, "J-1")
    a_ut = ctx.assign(client, ctx.otk, iid, method="UT")
    ctx.assign(client, ctx.otk, iid, method="RT")
    # Пытаемся заменить UT на RT — активный RT уже есть.
    r = _replace(
        ctx, client, a_ut["id"],
        {"expected_version": 1, "method_code": "RT", "reason": "конфликт"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_DUPLICATE_ACTIVE_METHOD"
    # Старое назначение не тронуто.
    old = client.get(
        f"{API}/inspection-method-assignments/{a_ut['id']}", headers=ctx.h(ctx.otk)
    ).json()
    assert old["status"] == "ASSIGNED"


def test_replace_invalid_lab_keeps_old(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid, method="UT", lab_id=ctx.lab.id)
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 1, "laboratory_company_id": ctx.nonlab.id,
         "reason": "недопустимая лаборатория"},
    )
    assert r.status_code == 422
    old = client.get(
        f"{API}/inspection-method-assignments/{a['id']}", headers=ctx.h(ctx.otk)
    ).json()
    assert old["status"] == "ASSIGNED"
    assert old["laboratory_company_id"] == ctx.lab.id
    # Новая запись не создана.
    count = (
        ctx.db.query(InspectionMethodAssignment)
        .filter(InspectionMethodAssignment.inspection_id == UUID(iid))
        .count()
    )
    assert count == 1


def test_replace_version_conflict(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = _replace(
        ctx, client, a["id"],
        {"expected_version": 99, "laboratory_company_id": ctx.lab2.id, "reason": "x"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ASSIGNMENT_VERSION_CONFLICT"


# ── RBAC и scope ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role_attr", ["otk", "ndt", "chief"])
def test_allowed_roles_can_create(
    ctx: Ctx, client: TestClient, role_attr: str
) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, getattr(ctx, role_attr), iid)
    assert r.status_code == 201, r.text


# Роли чтения без права записи (видят заявку, но не могут назначать) → 403.
@pytest.mark.parametrize("role_attr", ["ogs", "pto", "foreman", "master"])
def test_forbidden_read_roles_cannot_create(
    ctx: Ctx, client: TestClient, role_attr: str
) -> None:
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, getattr(ctx, role_attr), iid)
    assert r.status_code == 403, r.text


def test_norole_cannot_create(ctx: Ctx, client: TestClient) -> None:
    """Без единой роли чтения заявка скрыта по scope → 404 (канон Task 9A)."""
    iid = ctx.inspection(client, "J-1")
    r = ctx.create_assignment(client, ctx.norole, iid)
    assert r.status_code == 404


def test_ogs_cannot_cancel(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    a = ctx.assign(client, ctx.otk, iid)
    r = client.post(
        f"{API}/inspection-method-assignments/{a['id']}/cancel",
        json={"expected_version": 1, "reason": "x"}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 403


def test_project_scope_can_create(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    w = _role_worker(
        ctx.db, "PrjOtk", "OTK_INSPECTOR",
        scope_type="PROJECT", scope_id=str(ctx.project.id),
    )
    r = ctx.create_assignment(client, w, iid)
    assert r.status_code == 201, r.text


def test_foreign_project_scope_rejected(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    w = _role_worker(
        ctx.db, "FrnOtk", "OTK_INSPECTOR",
        scope_type="PROJECT", scope_id=str(uuid4()),
    )
    r = ctx.create_assignment(client, w, iid)
    assert r.status_code in (403, 404)


def test_line_scope_can_create(ctx: Ctx, client: TestClient) -> None:
    iid = ctx.inspection(client, "J-1")
    w = _role_worker(
        ctx.db, "LnOtk", "OTK_INSPECTOR",
        scope_type="LINE", scope_id=str(ctx.line.id),
    )
    r = ctx.create_assignment(client, w, iid)
    assert r.status_code == 201, r.text


def test_inspection_of_other_project_not_accessible(
    ctx: Ctx, client: TestClient
) -> None:
    iid = ctx.inspection(client, "J-1")
    w = _role_worker(
        ctx.db, "OtherOtk", "OTK_INSPECTOR",
        scope_type="PROJECT", scope_id=str(uuid4()),
    )
    r = client.get(
        f"{API}/inspections/{iid}/method-assignments", headers=ctx.h(w)
    )
    assert r.status_code == 404


def test_expired_role_rejected(ctx: Ctx, client: TestClient) -> None:
    """Просроченная роль не действует → заявка скрыта по scope → 404."""
    iid = ctx.inspection(client, "J-1")
    w = _role_worker(
        ctx.db, "ExpOtk", "OTK_INSPECTOR", valid_to=TODAY - timedelta(days=1)
    )
    r = ctx.create_assignment(client, w, iid)
    assert r.status_code in (403, 404)


def test_company_scope_cannot_create(ctx: Ctx, client: TestClient) -> None:
    """COMPANY-scope исключён из изменяющих действий (канон Task 9A §15.2)."""
    iid = ctx.inspection(client, "J-1")
    company = Company(
        name="ООО Скоуп", status="active", created_by=ctx.creator.id
    )
    ctx.db.add(company)
    ctx.db.commit()
    ctx.db.refresh(company)
    ctx.db.add(
        ProjectCompany(
            project_id=ctx.project.id, company_id=company.id,
            role_code="INSPECTION", valid_from=TODAY,
        )
    )
    ctx.db.commit()
    w = _role_worker(
        ctx.db, "CoOtk", "OTK_INSPECTOR",
        scope_type="COMPANY", scope_id=str(company.id),
    )
    r = ctx.create_assignment(client, w, iid)
    assert r.status_code == 403
