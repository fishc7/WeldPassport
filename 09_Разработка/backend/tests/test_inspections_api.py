"""Интеграционные тесты ядра Inspection (Task 9A, ADR-015 / Session 007).

Покрывают: создание черновика с проверкой готовности, проектную нумерацию,
идемпотентность, внешний номер, PATCH, подтверждение готовности СМР, отправку в
REQUESTED (в т.ч. override главного сварщика), отмену, чтение и scope-фильтрацию,
журнал событий, вычисляемое Joint.inspection_state. Назначение методов,
лаборатории, результаты, решения ОГС и дефекты (Tasks 9B–9G) здесь не
моделируются.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering.models import Joint, WeldOperation
from app.hr.models import Worker, WorkerRole
from app.projects.models import Company, Line, Project, ProjectCompany
from app.quality.models import Inspection
from app.quality.repository import QualityRepo
from app.shared.db import SessionLocal
from app.welding.models import Welder

from .conftest import TEST_COMPANY_ID

ENG = "/api/v1/engineering"
API = "/api/v1"
TODAY = date.today()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Ins{suffix}",
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
) -> Worker:
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


class InsCtx:
    """Полный контекст: проект/линия/документ/ревизия, роли и профиль сварщика."""

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

        self.pto = _role_worker(db, f"{code}P", "PTO_ENGINEER")
        self.master = _role_worker(db, f"{code}M", "MASTER")
        self.foreman = _role_worker(db, f"{code}F", "FOREMAN")
        self.ogs = _role_worker(db, f"{code}O", "OGS_ENGINEER")
        self.chief = _role_worker(db, f"{code}C", "CHIEF_WELDER")
        self.otk = _role_worker(db, f"{code}K", "OTK_INSPECTOR")
        self.ndt = _role_worker(db, f"{code}N", "NDT_SPECIALIST")
        self.norole = _worker(db, f"{code}Z")

        welder_worker = _worker(db, f"{code}Wk")
        self.welder = Welder(
            worker_id=welder_worker.id, stamp_code=f"ST-{code}", status="active"
        )
        db.add(self.welder)
        db.commit()
        db.refresh(self.welder)

    def h(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    # -- Joint / weld operation --

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

    def complete_weld_op(self, client: TestClient, joint_id: str) -> str:
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
            f"{ENG}/weld-operations", json=payload, headers=self.h(self.master)
        )
        assert r.status_code == 201, r.text
        op_id = r.json()["id"]
        rc = client.post(
            f"{ENG}/weld-operations/{op_id}/complete", json={},
            headers=self.h(self.master),
        )
        assert rc.status_code == 200, rc.text
        return op_id

    def activate(self, joint_id: str) -> None:
        joint = self.db.query(Joint).filter(Joint.id == UUID(joint_id)).first()
        joint.status = "ACTIVE"
        self.db.commit()

    def ready_joint(self, client: TestClient, joint_no: str) -> str:
        """ACTIVE-стык с актуальной завершённой сварочной операцией (готов)."""
        joint_id = self.create_joint(client, joint_no)
        self.complete_weld_op(client, joint_id)
        self.activate(joint_id)
        return joint_id

    # -- Inspection --

    def create_inspection(
        self,
        client: TestClient,
        worker: Worker,
        joint_id: str,
        *,
        reason: str = "Контроль после завершения сварки",
        external_no: str | None = None,
        notes: str | None = None,
        idempotency_key: str | None = None,
    ):
        body = {
            "project_id": str(self.project.id),
            "joint_id": joint_id,
            "request_reason": reason,
        }
        if external_no is not None:
            body["external_request_no"] = external_no
        if notes is not None:
            body["notes"] = notes
        headers = self.h(worker)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return client.post(f"{API}/inspections", json=body, headers=headers)

    def draft(self, client: TestClient, worker: Worker, joint_id: str, **kw) -> dict:
        r = self.create_inspection(client, worker, joint_id, **kw)
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
def ctx(db: Session) -> InsCtx:
    return InsCtx(db, "EP600")


# ── 21.1 Создание ──────────────────────────────────────────────────────────────


def test_ogs_creates_draft(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    body = ctx.draft(client, ctx.ogs, joint_id)
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    assert body["system_code"] == "EP600-INS-1"
    assert body["created_by_worker_id"] == ctx.ogs.id
    assert body["readiness"]["ready_for_inspection"] is True


def test_chief_creates_draft(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    r = ctx.create_inspection(client, ctx.chief, joint_id)
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("role_attr", ["pto", "master", "foreman", "otk", "ndt"])
def test_other_roles_cannot_create(
    ctx: InsCtx, client: TestClient, role_attr: str
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    r = ctx.create_inspection(client, getattr(ctx, role_attr), joint_id)
    assert r.status_code == 403, r.text


def test_no_role_cannot_create(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    r = ctx.create_inspection(client, ctx.norole, joint_id)
    assert r.status_code == 403


def test_inactive_role_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(ctx.db, "InactOgs", "OGS_ENGINEER", is_active=False)
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 403


def test_expired_role_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(
        ctx.db, "ExpOgs", "OGS_ENGINEER", valid_to=TODAY - timedelta(days=1)
    )
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 403


def test_foreign_project_scope_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(
        ctx.db, "PrjOgs", "OGS_ENGINEER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 403


def test_foreign_line_scope_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(
        ctx.db, "LnOgs", "OGS_ENGINEER", scope_type="LINE", scope_id=str(uuid4())
    )
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 403


def test_foreign_document_scope_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(
        ctx.db, "DocOgs", "OGS_ENGINEER",
        scope_type="ENGINEERING_DOCUMENT", scope_id=str(uuid4()),
    )
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 403


def test_project_scope_ok(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(
        ctx.db, "PrjOkOgs", "OGS_ENGINEER",
        scope_type="PROJECT", scope_id=str(ctx.project.id),
    )
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 201, r.text


def test_document_scope_ok(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _role_worker(
        ctx.db, "DocOkOgs", "OGS_ENGINEER",
        scope_type="ENGINEERING_DOCUMENT", scope_id=str(ctx.document.id),
    )
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 201, r.text


def test_joint_must_be_active(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.create_joint(client, "J-1")
    ctx.complete_weld_op(client, joint_id)  # но НЕ активируем
    r = ctx.create_inspection(client, ctx.ogs, joint_id)
    assert r.status_code == 409
    codes = [b["code"] for b in r.json()["detail"]["blocking_reasons"]]
    assert "JOINT_NOT_ACTIVE" in codes


def test_requires_completed_weld_operation(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.create_joint(client, "J-1")
    ctx.activate(joint_id)  # активен, но нет завершённой сварки
    r = ctx.create_inspection(client, ctx.ogs, joint_id)
    assert r.status_code == 409
    codes = [b["code"] for b in r.json()["detail"]["blocking_reasons"]]
    assert "NO_COMPLETED_WELD_OPERATION" in codes


def test_superseded_weld_operation_not_current(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    op = (
        ctx.db.query(WeldOperation)
        .filter(WeldOperation.joint_id == UUID(joint_id))
        .first()
    )
    op.lifecycle_status = "SUPERSEDED"
    ctx.db.commit()
    r = ctx.create_inspection(client, ctx.ogs, joint_id)
    assert r.status_code == 409
    codes = [b["code"] for b in r.json()["detail"]["blocking_reasons"]]
    assert "WELD_OPERATION_NOT_CURRENT" in codes


def test_required_heat_treatment_blocks(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    joint = ctx.db.query(Joint).filter(Joint.id == UUID(joint_id)).first()
    joint.heat_treatment_required = True
    ctx.db.commit()
    r = ctx.create_inspection(client, ctx.ogs, joint_id)
    assert r.status_code == 409
    codes = [b["code"] for b in r.json()["detail"]["blocking_reasons"]]
    assert "HEAT_TREATMENT_NOT_ACCEPTED" in codes


def test_project_must_match_joint(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    body = {
        "project_id": str(uuid4()),
        "joint_id": joint_id,
        "request_reason": "x",
    }
    r = client.post(f"{API}/inspections", json=body, headers=ctx.h(ctx.ogs))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSPECTION_PROJECT_MISMATCH"


def test_client_cannot_set_status_or_system_code(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    body = {
        "project_id": str(ctx.project.id),
        "joint_id": joint_id,
        "request_reason": "x",
        "status": "REQUESTED",
    }
    r = client.post(f"{API}/inspections", json=body, headers=ctx.h(ctx.ogs))
    assert r.status_code == 422  # extra=forbid


def test_create_records_created_event(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    body = ctx.draft(client, ctx.ogs, joint_id)
    r = client.get(f"{API}/inspections/{body['id']}/events", headers=ctx.h(ctx.ogs))
    assert r.status_code == 200
    events = r.json()
    assert [e["event_type"] for e in events] == ["CREATED"]
    assert events[0]["inspection_version"] == 1
    assert events[0]["to_status"] == "DRAFT"


# ── 21.2 Нумерация ──────────────────────────────────────────────────────────────


def test_sequence_increments_within_project(ctx: InsCtx, client: TestClient) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    b1 = ctx.draft(client, ctx.ogs, j1)
    b2 = ctx.draft(client, ctx.ogs, j2)
    assert b1["system_code"] == "EP600-INS-1"
    assert b2["system_code"] == "EP600-INS-2"


def test_sequences_independent_per_project(ctx: InsCtx, client: TestClient) -> None:
    other = InsCtx(ctx.db, "AB700")
    j1 = ctx.ready_joint(client, "J-1")
    j2 = other.ready_joint(client, "J-1")
    b1 = ctx.draft(client, ctx.ogs, j1)
    b2 = other.draft(client, other.ogs, j2)
    assert b1["system_code"] == "EP600-INS-1"
    assert b2["system_code"] == "AB700-INS-1"


def test_cancelled_number_not_reused(ctx: InsCtx, client: TestClient) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    b1 = ctx.draft(client, ctx.ogs, j1)
    rc = client.post(
        f"{API}/inspections/{b1['id']}/cancel",
        json={"expected_version": 1, "reason": "ошибочный стык"},
        headers=ctx.h(ctx.ogs),
    )
    assert rc.status_code == 200, rc.text
    b2 = ctx.draft(client, ctx.ogs, j2)
    assert b2["system_code"] == "EP600-INS-2"


def test_failed_create_does_not_consume_number(
    ctx: InsCtx, client: TestClient
) -> None:
    bad_joint = ctx.create_joint(client, "J-bad")  # не активен → блок
    r = ctx.create_inspection(client, ctx.ogs, bad_joint)
    assert r.status_code == 409
    assert ctx.db.query(Inspection).count() == 0
    good = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, good)
    assert b["system_code"] == "EP600-INS-1"


def test_system_code_immutable_via_patch(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={"system_code": "HACK-INS-9", "expected_version": 1},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 422  # extra=forbid


def test_concurrent_sequence_allocation_atomic(ctx: InsCtx) -> None:
    """Параллельная выдача номеров не даёт дублей (реальная конкуренция, §21.2.5)."""
    project_id = ctx.project.id

    def allocate() -> int:
        session = SessionLocal()
        try:
            value = QualityRepo(session).next_inspection_sequence(project_id)
            session.commit()
            return value
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: allocate(), range(4)))
    assert sorted(results) == [1, 2, 3, 4]
    assert len(set(results)) == 4


# ── 21.3 Идемпотентность создания ──────────────────────────────────────────────


def test_idempotent_repeat_returns_same(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    r1 = ctx.create_inspection(client, ctx.ogs, joint_id, idempotency_key="K1")
    r2 = ctx.create_inspection(client, ctx.ogs, joint_id, idempotency_key="K1")
    assert r1.status_code == 201
    assert r2.status_code in (200, 201)
    assert r1.json()["id"] == r2.json()["id"]
    assert ctx.db.query(Inspection).count() == 1


def test_idempotent_repeat_no_extra_sequence_or_event(
    ctx: InsCtx, client: TestClient
) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    ctx.create_inspection(client, ctx.ogs, j1, idempotency_key="K1")
    ctx.create_inspection(client, ctx.ogs, j1, idempotency_key="K1")
    # Следующая новая заявка получает INS-2 (счётчик не израсходован повтором).
    b = ctx.draft(client, ctx.ogs, j2)
    assert b["system_code"] == "EP600-INS-2"
    first = ctx.db.query(Inspection).filter(
        Inspection.joint_id == UUID(j1)
    ).first()
    ev = client.get(
        f"{API}/inspections/{first.id}/events", headers=ctx.h(ctx.ogs)
    ).json()
    assert [e["event_type"] for e in ev] == ["CREATED"]


def test_idempotent_same_key_different_body_conflict(
    ctx: InsCtx, client: TestClient
) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    ctx.create_inspection(client, ctx.ogs, j1, idempotency_key="K1")
    r = ctx.create_inspection(client, ctx.ogs, j2, idempotency_key="K1")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_IDEMPOTENCY_CONFLICT"


def test_idempotent_key_per_worker(ctx: InsCtx, client: TestClient) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    r1 = ctx.create_inspection(client, ctx.ogs, j1, idempotency_key="K1")
    r2 = ctx.create_inspection(client, ctx.chief, j2, idempotency_key="K1")
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


def test_no_key_creates_independent(ctx: InsCtx, client: TestClient) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    r1 = ctx.create_inspection(client, ctx.ogs, j1)
    r2 = ctx.create_inspection(client, ctx.ogs, j2)
    assert r1.json()["id"] != r2.json()["id"]


# ── 21.4 Внешний номер ─────────────────────────────────────────────────────────


def test_external_no_optional(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    assert b["external_request_no"] is None


def test_external_no_empty_normalized_to_null(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id, external_no="   ")
    assert b["external_request_no"] is None


def test_external_no_unique_within_project(ctx: InsCtx, client: TestClient) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    j2 = ctx.ready_joint(client, "J-2")
    ctx.draft(client, ctx.ogs, j1, external_no="ЗНК-1")
    r = ctx.create_inspection(client, ctx.ogs, j2, external_no="ЗНК-1")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_DUPLICATE_EXTERNAL_NO"


def test_external_no_same_allowed_across_projects(
    ctx: InsCtx, client: TestClient
) -> None:
    other = InsCtx(ctx.db, "AB700")
    j1 = ctx.ready_joint(client, "J-1")
    j2 = other.ready_joint(client, "J-1")
    r1 = ctx.create_inspection(client, ctx.ogs, j1, external_no="ЗНК-1")
    r2 = other.create_inspection(client, other.ogs, j2, external_no="ЗНК-1")
    assert r1.status_code == 201
    assert r2.status_code == 201


# ── 21.5 PATCH ──────────────────────────────────────────────────────────────────


def test_patch_allowed_fields(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={
            "external_request_no": "ЗНК-9",
            "request_reason": "Уточнённое основание",
            "notes": "обновлено",
            "expected_version": 1,
        },
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["external_request_no"] == "ЗНК-9"
    assert body["request_reason"] == "Уточнённое основание"
    assert body["version"] == 2


def test_patch_requires_expected_version(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.patch(
        f"{API}/inspections/{b['id']}", json={"notes": "x"}, headers=ctx.h(ctx.ogs)
    )
    assert r.status_code == 422


def test_patch_stale_version_conflict(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={"notes": "x", "expected_version": 99},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_VERSION_CONFLICT"


def test_patch_creates_updated_event(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    client.patch(
        f"{API}/inspections/{b['id']}",
        json={"notes": "x", "expected_version": 1}, headers=ctx.h(ctx.ogs),
    )
    ev = client.get(
        f"{API}/inspections/{b['id']}/events", headers=ctx.h(ctx.ogs)
    ).json()
    assert [e["event_type"] for e in ev] == ["CREATED", "UPDATED"]


def test_patch_immutable_field_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={"joint_id": str(uuid4()), "expected_version": 1},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 422


def test_patch_forbidden_after_requested(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm_and_request(ctx, client, b["id"])
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={"notes": "x", "expected_version": 3}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_NOT_DRAFT"


def test_patch_forbidden_after_cancelled(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "ошибка"}, headers=ctx.h(ctx.ogs),
    )
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={"notes": "x", "expected_version": 2}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409


# ── 21.7 Подтверждение СМР ──────────────────────────────────────────────────────


def _confirm(ctx: InsCtx, client: TestClient, inspection_id: str, worker, version):
    return client.post(
        f"{API}/inspections/{inspection_id}/confirm-production-readiness",
        json={"expected_version": version}, headers=ctx.h(worker),
    )


def _confirm_and_request(ctx: InsCtx, client: TestClient, inspection_id: str):
    rc = _confirm(ctx, client, inspection_id, ctx.foreman, 1)
    assert rc.status_code == 200, rc.text
    rr = client.post(
        f"{API}/inspections/{inspection_id}/request",
        json={"expected_version": 2}, headers=ctx.h(ctx.ogs),
    )
    assert rr.status_code == 200, rr.text
    return rr.json()


@pytest.mark.parametrize("role_attr", ["foreman", "master"])
def test_smr_can_confirm(
    ctx: InsCtx, client: TestClient, role_attr: str
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = _confirm(ctx, client, b["id"], getattr(ctx, role_attr), 1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["production_ready_confirmed_by_worker_id"] == getattr(ctx, role_attr).id
    assert body["version"] == 2


@pytest.mark.parametrize("role_attr", ["ogs", "pto", "otk", "ndt"])
def test_non_smr_cannot_confirm(
    ctx: InsCtx, client: TestClient, role_attr: str
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = _confirm(ctx, client, b["id"], getattr(ctx, role_attr), 1)
    assert r.status_code == 403


def test_confirm_foreign_scope_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _role_worker(
        ctx.db, "PrjFore", "FOREMAN", scope_type="PROJECT", scope_id=str(uuid4())
    )
    r = _confirm(ctx, client, b["id"], w, 1)
    assert r.status_code in (403, 404)


def test_confirm_only_in_draft(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm_and_request(ctx, client, b["id"])
    r = _confirm(ctx, client, b["id"], ctx.master, 3)
    assert r.status_code == 409


def test_confirm_idempotent(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r1 = _confirm(ctx, client, b["id"], ctx.foreman, 1)
    assert r1.status_code == 200
    # Повтор с текущей версией — идемпотентно, без второго события и без bump.
    r2 = _confirm(ctx, client, b["id"], ctx.foreman, 2)
    assert r2.status_code == 200
    assert r2.json()["version"] == 2
    ev = client.get(
        f"{API}/inspections/{b['id']}/events", headers=ctx.h(ctx.ogs)
    ).json()
    types = [e["event_type"] for e in ev]
    assert types.count("PRODUCTION_READINESS_CONFIRMED") == 1


def test_confirm_author_not_replaced_by_other(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm(ctx, client, b["id"], ctx.foreman, 1)
    r2 = _confirm(ctx, client, b["id"], ctx.master, 2)
    assert r2.status_code == 200
    assert r2.json()["production_ready_confirmed_by_worker_id"] == ctx.foreman.id


# ── 21.8 REQUESTED ──────────────────────────────────────────────────────────────


def test_ogs_cannot_request_without_smr(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 1}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_SMR_NOT_CONFIRMED"


def test_request_success_after_confirm(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    body = _confirm_and_request(ctx, client, b["id"])
    assert body["status"] == "REQUESTED"
    assert body["requested_by_worker_id"] == ctx.ogs.id
    assert body["ogs_readiness_confirmed_by_worker_id"] == ctx.ogs.id
    assert body["requested_at"] is not None
    assert body["ogs_readiness_confirmed_at"] is not None
    assert body["version"] == 3


def test_request_blocked_when_readiness_regresses(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm(ctx, client, b["id"], ctx.foreman, 1)
    # Регрессия: сварочная операция стала неактуальной.
    op = ctx.db.query(WeldOperation).filter(
        WeldOperation.joint_id == UUID(joint_id)
    ).first()
    op.lifecycle_status = "SUPERSEDED"
    ctx.db.commit()
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 2}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_NOT_READY"


def test_ordinary_ogs_cannot_override(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 1, "readiness_override_reason": "срочно"},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "INSPECTION_OVERRIDE_NOT_ALLOWED"


def test_chief_override_without_smr(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={
            "expected_version": 1,
            "readiness_override_reason": "по распоряжению главного сварщика",
        },
        headers=ctx.h(ctx.chief),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "REQUESTED"
    assert body["readiness_override_reason"]
    assert body["version"] == 2  # одна команда → +1, несмотря на два события
    ev = client.get(
        f"{API}/inspections/{b['id']}/events", headers=ctx.h(ctx.chief)
    ).json()
    types = [e["event_type"] for e in ev]
    assert "READINESS_OVERRIDDEN" in types
    assert "REQUESTED" in types


def test_chief_override_empty_reason_rejected(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 1, "readiness_override_reason": "  "},
        headers=ctx.h(ctx.chief),
    )
    assert r.status_code == 422


def test_override_does_not_bypass_weld_operation(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.create_joint(client, "J-1")
    ctx.activate(joint_id)  # активен, но нет завершённой сварки
    # Заявку-черновик здесь создать нельзя (блок), поэтому создаём на готовом
    # стыке, затем ломаем готовность и пробуем override.
    ready = ctx.ready_joint(client, "J-2")
    b = ctx.draft(client, ctx.ogs, ready)
    op = ctx.db.query(WeldOperation).filter(
        WeldOperation.joint_id == UUID(ready)
    ).first()
    op.lifecycle_status = "SUPERSEDED"
    ctx.db.commit()
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 1, "readiness_override_reason": "срочно"},
        headers=ctx.h(ctx.chief),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_NOT_READY"


def test_override_does_not_bypass_heat_treatment(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    joint = ctx.db.query(Joint).filter(Joint.id == UUID(joint_id)).first()
    joint.heat_treatment_required = True
    ctx.db.commit()
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 1, "readiness_override_reason": "срочно"},
        headers=ctx.h(ctx.chief),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_NOT_READY"


# ── 21.9 Отмена ────────────────────────────────────────────────────────────────


def test_ogs_cancels_draft(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "ошибочный стык"},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "CANCELLED"
    assert body["cancelled_by_worker_id"] == ctx.ogs.id
    assert body["cancellation_reason"] == "ошибочный стык"


def test_ogs_cancels_requested(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm_and_request(ctx, client, b["id"])
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 3, "reason": "отзыв"}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200, r.text


def test_chief_cancels(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "ошибка"}, headers=ctx.h(ctx.chief),
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("role_attr", ["foreman", "master", "pto", "otk", "ndt"])
def test_other_roles_cannot_cancel(
    ctx: InsCtx, client: TestClient, role_attr: str
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "x"},
        headers=ctx.h(getattr(ctx, role_attr)),
    )
    assert r.status_code == 403


def test_cancel_reason_required(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "   "}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 422


def test_cancel_version_conflict(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 99, "reason": "x"}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409


def test_double_cancel_rejected(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "x"}, headers=ctx.h(ctx.ogs),
    )
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 2, "reason": "y"}, headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INSPECTION_ALREADY_CANCELLED"


def test_no_delete_endpoint(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.delete(f"{API}/inspections/{b['id']}", headers=ctx.h(ctx.ogs))
    assert r.status_code in (404, 405)


def test_new_inspection_after_cancel_allowed(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b1 = ctx.draft(client, ctx.ogs, joint_id)
    client.post(
        f"{API}/inspections/{b1['id']}/cancel",
        json={"expected_version": 1, "reason": "x"}, headers=ctx.h(ctx.ogs),
    )
    r2 = ctx.create_inspection(client, ctx.ogs, joint_id)
    assert r2.status_code == 201


# ── 21.10 Чтение и scope ────────────────────────────────────────────────────────


def test_global_chief_sees_all(ctx: InsCtx, client: TestClient) -> None:
    j1 = ctx.ready_joint(client, "J-1")
    ctx.draft(client, ctx.ogs, j1)
    r = client.get(f"{API}/inspections", headers=ctx.h(ctx.chief))
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_project_scope_list_filtered(ctx: InsCtx, client: TestClient) -> None:
    other = InsCtx(ctx.db, "AB700")
    j1 = ctx.ready_joint(client, "J-1")
    j2 = other.ready_joint(client, "J-1")
    ctx.draft(client, ctx.ogs, j1)
    other.draft(client, other.ogs, j2)
    w = _role_worker(
        ctx.db, "PrjView", "OGS_ENGINEER",
        scope_type="PROJECT", scope_id=str(ctx.project.id),
    )
    r = client.get(f"{API}/inspections", headers=ctx.h(w))
    assert r.status_code == 200
    data = r.json()
    project_ids = {i["project_id"] for i in data["items"]}
    assert project_ids == {str(ctx.project.id)}


def test_foreign_inspection_returns_404(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _role_worker(
        ctx.db, "PrjOther", "OGS_ENGINEER",
        scope_type="PROJECT", scope_id=str(uuid4()),
    )
    r = client.get(f"{API}/inspections/{b['id']}", headers=ctx.h(w))
    assert r.status_code == 404


def test_forbidden_command_on_visible_returns_403(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    # PTO видит заявку (роль чтения), но не может отменить (нужна OGS/CHIEF).
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "x"}, headers=ctx.h(ctx.pto),
    )
    assert r.status_code == 403


def test_ndt_reads_inspection(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    r = client.get(f"{API}/inspections/{b['id']}", headers=ctx.h(ctx.ndt))
    assert r.status_code == 200


def test_ndt_cannot_read_readiness(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    r = client.get(
        f"{API}/joints/{joint_id}/inspection-readiness", headers=ctx.h(ctx.ndt)
    )
    assert r.status_code == 403


def test_events_hidden_with_inspection(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _role_worker(
        ctx.db, "PrjEv", "OGS_ENGINEER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    r = client.get(f"{API}/inspections/{b['id']}/events", headers=ctx.h(w))
    assert r.status_code == 404


def test_inactive_role_no_read(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _role_worker(ctx.db, "InactRead", "OTK_INSPECTOR", is_active=False)
    r = client.get(f"{API}/inspections/{b['id']}", headers=ctx.h(w))
    assert r.status_code == 404


# ── COMPANY scope: только чтение, без изменяющих действий Task 9A (§15.2) ────────


def _company_scoped_ogs(ctx: InsCtx, suffix: str) -> Worker:
    """OGS с ролью в COMPANY-scope организации, действующей в проекте."""
    company = Company(
        name=f"ООО {suffix}", status="active", created_by=ctx.creator.id
    )
    ctx.db.add(company)
    ctx.db.commit()
    ctx.db.refresh(company)
    link = ProjectCompany(
        project_id=ctx.project.id, company_id=company.id,
        role_code="INSPECTION", valid_from=TODAY,
    )
    ctx.db.add(link)
    ctx.db.commit()
    return _role_worker(
        ctx.db, suffix, "OGS_ENGINEER",
        scope_type="COMPANY", scope_id=str(company.id),
    )


def test_company_scope_cannot_create(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    w = _company_scoped_ogs(ctx, "CoCreate")
    r = ctx.create_inspection(client, w, joint_id)
    assert r.status_code == 403


def test_company_scope_cannot_patch(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _company_scoped_ogs(ctx, "CoPatch")
    r = client.patch(
        f"{API}/inspections/{b['id']}",
        json={"notes": "x", "expected_version": 1}, headers=ctx.h(w),
    )
    assert r.status_code == 403


def test_company_scope_cannot_request(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm(ctx, client, b["id"], ctx.foreman, 1)
    w = _company_scoped_ogs(ctx, "CoReq")
    r = client.post(
        f"{API}/inspections/{b['id']}/request",
        json={"expected_version": 2}, headers=ctx.h(w),
    )
    assert r.status_code == 403


def test_company_scope_cannot_cancel(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _company_scoped_ogs(ctx, "CoCancel")
    r = client.post(
        f"{API}/inspections/{b['id']}/cancel",
        json={"expected_version": 1, "reason": "x"}, headers=ctx.h(w),
    )
    assert r.status_code == 403


def test_company_scope_can_read(ctx: InsCtx, client: TestClient) -> None:
    """COMPANY-scope исключён только из действий: чтение остаётся доступным."""
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    w = _company_scoped_ogs(ctx, "CoRead")
    r = client.get(f"{API}/inspections/{b['id']}", headers=ctx.h(w))
    assert r.status_code == 200


# ── 21.11 События ──────────────────────────────────────────────────────────────


def test_events_stable_order_and_fields(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    _confirm_and_request(ctx, client, b["id"])
    ev = client.get(
        f"{API}/inspections/{b['id']}/events", headers=ctx.h(ctx.ogs)
    ).json()
    types = [e["event_type"] for e in ev]
    assert types == ["CREATED", "PRODUCTION_READINESS_CONFIRMED", "REQUESTED"]
    last = ev[-1]
    assert last["actor_worker_id"] == ctx.ogs.id
    assert last["from_status"] == "DRAFT"
    assert last["to_status"] == "REQUESTED"
    assert last["inspection_version"] == 3


def test_no_event_mutation_endpoints(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    # Нет POST/DELETE над событиями.
    r = client.post(
        f"{API}/inspections/{b['id']}/events", json={}, headers=ctx.h(ctx.ogs)
    )
    assert r.status_code in (404, 405)


def test_failed_command_creates_no_event(ctx: InsCtx, client: TestClient) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    b = ctx.draft(client, ctx.ogs, joint_id)
    # Конфликт версии не должен оставить события.
    client.patch(
        f"{API}/inspections/{b['id']}",
        json={"notes": "x", "expected_version": 77}, headers=ctx.h(ctx.ogs),
    )
    ev = client.get(
        f"{API}/inspections/{b['id']}/events", headers=ctx.h(ctx.ogs)
    ).json()
    assert [e["event_type"] for e in ev] == ["CREATED"]


# ── 21.12 Joint.inspection_state ────────────────────────────────────────────────


def _joint_state(ctx: InsCtx, client: TestClient, joint_id: str) -> str:
    r = client.get(f"{ENG}/joints/{joint_id}", headers=ctx.h(ctx.ogs))
    assert r.status_code == 200, r.text
    return r.json()["inspection_state"]


def _insert_inspection(ctx: InsCtx, joint_id: str, status: str) -> None:
    """Прямая вставка заявки в нужном статусе (для недоступных через API, §21.12)."""
    now = datetime.now(timezone.utc)
    seq = QualityRepo(ctx.db).next_inspection_sequence(ctx.project.id)
    fields = dict(
        project_id=ctx.project.id,
        joint_id=UUID(joint_id),
        system_code=f"{ctx.project.code}-INS-{seq}",
        status=status,
        request_reason="прямая вставка",
        created_by_worker_id=ctx.ogs.id,
        updated_by_worker_id=ctx.ogs.id,
        version=1,
    )
    if status in (
        "REQUESTED", "ASSIGNED", "IN_PROGRESS", "COMPLETED",
        "REVIEWED", "CLOSED", "SUSPENDED", "TERMINATED",
    ):
        fields.update(
            requested_at=now, requested_by_worker_id=ctx.ogs.id,
            ogs_readiness_confirmed_at=now,
            ogs_readiness_confirmed_by_worker_id=ctx.ogs.id,
        )
    if status == "CANCELLED":
        fields.update(
            cancelled_at=now, cancelled_by_worker_id=ctx.ogs.id,
            cancellation_reason="x",
        )
    ctx.db.add(Inspection(**fields))
    ctx.db.commit()


def test_state_not_required_without_inspections(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    assert _joint_state(ctx, client, joint_id) == "NOT_REQUIRED"


@pytest.mark.parametrize(
    "status,expected",
    [
        ("DRAFT", "PENDING"),
        ("REQUESTED", "PENDING"),
        ("ASSIGNED", "PENDING"),
        ("IN_PROGRESS", "IN_PROGRESS"),
        ("COMPLETED", "IN_PROGRESS"),
        ("REVIEWED", "IN_PROGRESS"),
        ("CANCELLED", "NOT_REQUIRED"),
        ("TERMINATED", "NOT_REQUIRED"),
        ("CLOSED", "NOT_REQUIRED"),
    ],
)
def test_state_by_single_inspection(
    ctx: InsCtx, client: TestClient, status: str, expected: str
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    _insert_inspection(ctx, joint_id, status)
    assert _joint_state(ctx, client, joint_id) == expected


def test_state_priority_in_progress_over_pending(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    _insert_inspection(ctx, joint_id, "DRAFT")
    _insert_inspection(ctx, joint_id, "IN_PROGRESS")
    assert _joint_state(ctx, client, joint_id) == "IN_PROGRESS"


def test_joint_list_includes_inspection_state(
    ctx: InsCtx, client: TestClient
) -> None:
    joint_id = ctx.ready_joint(client, "J-1")
    _insert_inspection(ctx, joint_id, "DRAFT")
    r = client.get(
        f"{ENG}/joints", params={"project_id": str(ctx.project.id)},
        headers=ctx.h(ctx.ogs),
    )
    assert r.status_code == 200
    states = {i["id"]: i["inspection_state"] for i in r.json()["items"]}
    assert states[joint_id] == "PENDING"


def test_inspection_state_not_stored_column(ctx: InsCtx) -> None:
    from sqlalchemy import text as sa_text

    cols = ctx.db.execute(
        sa_text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='engineering' AND table_name='joints'"
        )
    ).scalars().all()
    assert "inspection_state" not in cols
