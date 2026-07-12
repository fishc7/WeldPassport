"""Интеграционные тесты Bulk Joint Import (Task 7, ADR-010).

Массовое атомарное создание Joint из одной DocumentRevision:
структура запроса, полная предварительная бизнес-валидация со сбором всех ошибок,
атомарность (нет частичного импорта), отсутствие расхода system_code при неуспехе,
идемпотентность (replay / конфликт ключа) и безопасность при конкурентном
UNIQUE-конфликте.

Каждый успешный Joint пакета создаётся по тем же правилам, что одиночный
POST /joints: DRAFT, origin==current, автоматическая ORIGIN/PRIMARY-связь со
снимком, без автозапуска согласования.
"""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.engineering.joint_bulk import (
    JointBulkService,
    calculate_bulk_request_hash,
)
from app.engineering.models import (
    ENGINEERING_SCHEMA,
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointSequence,
)
from app.engineering.repository import EngineeringRepo
from app.engineering.schemas import JointBulkCreate
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"
BULK_URL = f"{ENGINEERING_URL}/joints/bulk"
TODAY = date.today()

READY_FIELDS: dict = {
    "geometry_type": "BUTT",
    "weld_joint_type": "BW",
    "dn_1": 100,
    "thickness_1": 6,
    "required_root_method": "141",
    "required_fill_method": "111",
    "required_cap_method": "111",
}


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Blk{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=TODAY,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _assign_role(
    db: Session,
    worker_id: int,
    role_code: str,
    *,
    scope_type: str = "GLOBAL",
    scope_id: str | None = None,
) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=True,
        valid_from=TODAY,
    )
    db.add(role)
    db.commit()
    return role


def _role_worker(db: Session, suffix: str, role_code: str, **scope) -> Worker:
    w = _worker(db, suffix)
    _assign_role(db, w.id, role_code, **scope)
    return w


class Ctx:
    """Проект/линия/документ(APPROVED)/ревизия(APPROVED) + creator с GLOBAL FOREMAN."""

    def __init__(self, db: Session, code: str, *, doc_has_line: bool = True) -> None:
        self.db = db
        self.creator = _worker(db, f"{code}Creator")
        _assign_role(db, self.creator.id, "FOREMAN")
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
            project_id=self.project.id,
            line_id=self.line.id if doc_has_line else None,
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

    def headers(self, worker: Worker | None = None) -> dict[str, str]:
        return {"X-User-Id": str((worker or self.creator).id)}

    def payload(self, *, items: list[dict] | None = None, key: str = "K-1", **over):
        body: dict = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "created_by": self.creator.id,
            "idempotency_key": key,
            "items": items if items is not None else [{"joint_no": "J-1"}],
        }
        body.update(over)
        return body

    def revision2(self, code: str = "R1") -> DocumentRevision:
        rev = DocumentRevision(
            engineering_document_id=self.document.id, revision_code=code,
            status="APPROVED", created_by=self.creator.id,
        )
        self.db.add(rev)
        self.db.commit()
        self.db.refresh(rev)
        return rev


def _bulk(client: TestClient, ctx: Ctx, worker: Worker | None = None, **over):
    return client.post(
        BULK_URL, json=ctx.payload(**over), headers=ctx.headers(worker)
    )


def _get_joint(client: TestClient, ctx: Ctx, joint_id: str) -> dict:
    resp = client.get(
        f"{ENGINEERING_URL}/joints/{joint_id}", headers=ctx.headers()
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _links(client: TestClient, ctx: Ctx, joint_id: str) -> list[dict]:
    resp = client.get(
        f"{ENGINEERING_URL}/joints/{joint_id}/document-revisions",
        headers=ctx.headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Схема и структура запроса ─────────────────────────────────────────────────


def test_empty_items_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BEMPT")
    resp = _bulk(client, ctx, items=[])
    assert resp.status_code == 422


def test_501_items_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "B501")
    items = [{"joint_no": f"J-{i}"} for i in range(501)]
    resp = _bulk(client, ctx, items=items)
    assert resp.status_code == 422


def test_500_items_accepted(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "B500")
    items = [{"joint_no": f"J-{i}"} for i in range(500)]
    resp = _bulk(client, ctx, items=items, key="K-500")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created_count"] == 500
    assert len(body["items"]) == 500


def test_unknown_top_level_field_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BTOP")
    resp = _bulk(client, ctx, extra_field="x")
    assert resp.status_code == 422


def test_unknown_item_field_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BITM")
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1", "bogus": 1}])
    assert resp.status_code == 422


def test_common_field_inside_item_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCOM")
    for bad in ("project_id", "line_id", "document_revision_id", "created_by"):
        resp = _bulk(
            client, ctx, items=[{"joint_no": "J-1", bad: str(uuid4())}]
        )
        assert resp.status_code == 422, f"{bad}: {resp.text}"


def test_blank_idempotency_key_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BKEY")
    for bad in ("", "   "):
        resp = _bulk(client, ctx, key=bad)
        assert resp.status_code == 422, resp.text


def test_idempotency_key_too_long_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BKLN")
    resp = _bulk(client, ctx, key="x" * 101)
    assert resp.status_code == 422


def test_created_by_not_positive_422(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCB0")
    resp = _bulk(client, ctx, created_by=0)
    assert resp.status_code == 422


# ── Успешный импорт ───────────────────────────────────────────────────────────


def test_bulk_success_multiple(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BOK")
    items = [{"joint_no": "J-001"}, {"joint_no": "J-002"}, {"joint_no": "J-003"}]
    resp = _bulk(client, ctx, items=items, key="K-ok")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created_count"] == 3
    assert body["project_id"] == str(ctx.project.id)
    assert body["line_id"] == str(ctx.line.id)
    assert body["document_revision_id"] == str(ctx.revision.id)
    assert body["created_by"] == ctx.creator.id
    UUID(body["bulk_request_id"])

    # row_index начинается с 0, порядок исходный.
    assert [it["row_index"] for it in body["items"]] == [0, 1, 2]
    assert [it["joint_no"] for it in body["items"]] == ["J-001", "J-002", "J-003"]
    for it in body["items"]:
        UUID(it["id"])
        assert it["system_code"].startswith(f"{ctx.project.code}-JNT-")


def test_bulk_joint_matches_single_creation(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BMATCH")
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-m")
    it = resp.json()["items"][0]
    joint = _get_joint(client, ctx, it["id"])
    assert joint["status"] == "DRAFT"
    assert joint["origin_document_revision_id"] == str(ctx.revision.id)
    assert joint["current_document_revision_id"] == str(ctx.revision.id)
    # Согласование не запущено автоматически.
    assert joint["pto_status"] == "NOT_SUBMITTED"
    assert joint["ogs_status"] == "NOT_SUBMITTED"
    # Начальные версии — как при одиночном создании.
    assert joint["version"] == 1
    assert joint["record_version"] == 1
    assert joint["approval_version"] == 1
    assert joint["workflow_version"] == 1


def test_bulk_creates_origin_primary_snapshot(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "BSNAP")
    resp = _bulk(
        client, ctx, items=[{"joint_no": "J-1", **READY_FIELDS}], key="K-s"
    )
    it = resp.json()["items"][0]
    links = _links(client, ctx, it["id"])
    active_primary = [
        ln for ln in links
        if ln["link_status"] == "ACTIVE" and ln["document_role"] == "PRIMARY"
    ]
    assert len(active_primary) == 1
    link = active_primary[0]
    assert link["revision_role"] == "ORIGIN"
    assert link["document_revision_id"] == str(ctx.revision.id)
    # Снимок соответствует созданному Joint.
    assert link["snapshot_joint_no"] == "J-1"
    assert link["snapshot_geometry_type"] == "BUTT"
    assert str(link["snapshot_dn_1"]) in ("100", "100.0", "100.00000")


def test_bulk_persists_single_request_row(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BROW")
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-r")
    body = resp.json()
    rows = db.execute(
        text(
            f"SELECT id, response_payload, status FROM {ENGINEERING_SCHEMA}."
            "joint_bulk_requests WHERE project_id = :pid"
        ),
        {"pid": str(ctx.project.id)},
    ).fetchall()
    assert len(rows) == 1
    assert str(rows[0][0]) == body["bulk_request_id"]
    assert rows[0][1] == body  # response_payload равен телу ответа
    assert rows[0][2] == "COMPLETED"


# ── Общий контекст ────────────────────────────────────────────────────────────


def _bulk_error_codes(resp) -> set[str]:
    return {e["code"] for e in resp.json()["detail"]["errors"]}


def test_created_by_mismatch(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCBM")
    other = _role_worker(db, "BCBMother", "FOREMAN")
    # created_by (creator) != X-User-Id (other).
    resp = client.post(
        BULK_URL, json=ctx.payload(), headers=ctx.headers(other)
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "BULK_VALIDATION_FAILED"
    assert "CREATED_BY_MISMATCH" in _bulk_error_codes(resp)


def test_unknown_project(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BUPRJ")
    resp = _bulk(client, ctx, project_id=str(uuid4()))
    assert resp.status_code == 422
    assert "PROJECT_NOT_FOUND" in _bulk_error_codes(resp)


def test_unknown_line(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BULN")
    resp = _bulk(client, ctx, line_id=str(uuid4()))
    assert resp.status_code == 422
    assert "LINE_NOT_FOUND" in _bulk_error_codes(resp)


def test_line_of_other_project(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BLXP")
    other = Ctx(db, "BLXP2")
    resp = _bulk(client, ctx, line_id=str(other.line.id))
    assert resp.status_code == 422
    codes = _bulk_error_codes(resp)
    assert "LINE_PROJECT_MISMATCH" in codes
    # Ошибка общего контекста — без row_index.
    for e in resp.json()["detail"]["errors"]:
        if e["code"] == "LINE_PROJECT_MISMATCH":
            assert "row_index" not in e


def test_unknown_revision(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BUREV")
    resp = _bulk(client, ctx, document_revision_id=str(uuid4()))
    assert resp.status_code == 422
    assert "DOCUMENT_REVISION_NOT_FOUND" in _bulk_error_codes(resp)


def test_revision_of_other_project(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BRXP")
    other = Ctx(db, "BRXP2")
    resp = _bulk(client, ctx, document_revision_id=str(other.revision.id))
    assert resp.status_code == 422
    assert "DOCUMENT_PROJECT_MISMATCH" in _bulk_error_codes(resp)


def test_document_of_other_line(client: TestClient, db: Session) -> None:
    # Документ привязан к другой линии того же проекта → DOCUMENT_LINE_MISMATCH.
    ctx = Ctx(db, "BDLN", doc_has_line=False)
    other_line = Line(
        project_id=ctx.project.id, line_no="L-OTHER", status="active",
        required_inspection_types=[], created_by=ctx.creator.id,
    )
    db.add(other_line)
    db.commit()
    db.refresh(other_line)
    doc = EngineeringDocument(
        project_id=ctx.project.id, line_id=other_line.id,
        document_no="DOC-DLN2", document_type="ISOMETRIC",
        status="APPROVED", created_by=ctx.creator.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    rev = DocumentRevision(
        engineering_document_id=doc.id, revision_code="R0",
        status="APPROVED", created_by=ctx.creator.id,
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)
    resp = _bulk(client, ctx, document_revision_id=str(rev.id))
    assert resp.status_code == 422
    assert "DOCUMENT_LINE_MISMATCH" in _bulk_error_codes(resp)


def test_document_without_line_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BNOLN", doc_has_line=False)
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-nl")
    assert resp.status_code == 201, resp.text


# Единое правило источника Joint: только APPROVED document + APPROVED revision.


def test_draft_document_not_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDRD")
    ctx.document.status = "DRAFT"
    db.add(ctx.document)
    db.commit()
    resp = _bulk(client, ctx)
    assert resp.status_code == 422
    assert "DOCUMENT_REVISION_NOT_ALLOWED" in _bulk_error_codes(resp)


def test_draft_revision_not_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDRR")
    ctx.revision.status = "DRAFT"
    db.add(ctx.revision)
    db.commit()
    resp = _bulk(client, ctx)
    assert resp.status_code == 422
    assert "DOCUMENT_REVISION_NOT_ALLOWED" in _bulk_error_codes(resp)


def test_cancelled_document_not_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDST")
    ctx.document.status = "CANCELLED"
    db.add(ctx.document)
    db.commit()
    resp = _bulk(client, ctx)
    assert resp.status_code == 422
    assert "DOCUMENT_REVISION_NOT_ALLOWED" in _bulk_error_codes(resp)


def test_superseded_revision_not_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BRST")
    ctx.revision.status = "SUPERSEDED"
    db.add(ctx.revision)
    db.commit()
    resp = _bulk(client, ctx)
    assert resp.status_code == 422
    assert "DOCUMENT_REVISION_NOT_ALLOWED" in _bulk_error_codes(resp)


def test_approved_document_and_revision_allowed(
    client: TestClient, db: Session
) -> None:
    # APPROVED + APPROVED (по умолчанию в Ctx) → пакет создаётся.
    ctx = Ctx(db, "BAPRV")
    assert ctx.document.status == "APPROVED"
    assert ctx.revision.status == "APPROVED"
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-apr")
    assert resp.status_code == 201, resp.text


# ── Права и scope ─────────────────────────────────────────────────────────────


def test_insufficient_role(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BNOROLE")
    # Работник без релевантной роли (WELDER не входит в BULK_CREATE_ROLES).
    w = _role_worker(db, "BNOR", "WELDER")
    resp = client.post(
        BULK_URL,
        json=ctx.payload(created_by=w.id),
        headers=ctx.headers(w),
    )
    assert resp.status_code == 422
    assert "INSUFFICIENT_SCOPE" in _bulk_error_codes(resp)


def test_foreign_project_scope(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BFPS")
    w = _role_worker(
        db, "BFPS", "FOREMAN", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = client.post(
        BULK_URL, json=ctx.payload(created_by=w.id), headers=ctx.headers(w)
    )
    assert resp.status_code == 422
    assert "INSUFFICIENT_SCOPE" in _bulk_error_codes(resp)


def test_foreign_line_scope(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BFLS")
    w = _role_worker(
        db, "BFLS", "MASTER", scope_type="LINE", scope_id=str(uuid4())
    )
    resp = client.post(
        BULK_URL, json=ctx.payload(created_by=w.id), headers=ctx.headers(w)
    )
    assert resp.status_code == 422
    assert "INSUFFICIENT_SCOPE" in _bulk_error_codes(resp)


def test_global_scope_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BGS")
    w = _role_worker(db, "BGS", "MASTER", scope_type="GLOBAL")
    resp = client.post(
        BULK_URL,
        json=ctx.payload(created_by=w.id, key="K-g"),
        headers=ctx.headers(w),
    )
    assert resp.status_code == 201, resp.text


def test_project_scope_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BPS")
    w = _role_worker(
        db, "BPS", "FOREMAN", scope_type="PROJECT", scope_id=str(ctx.project.id)
    )
    resp = client.post(
        BULK_URL,
        json=ctx.payload(created_by=w.id, key="K-p"),
        headers=ctx.headers(w),
    )
    assert resp.status_code == 201, resp.text


def test_line_scope_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BLS")
    w = _role_worker(
        db, "BLS", "FOREMAN", scope_type="LINE", scope_id=str(ctx.line.id)
    )
    resp = client.post(
        BULK_URL,
        json=ctx.payload(created_by=w.id, key="K-l"),
        headers=ctx.headers(w),
    )
    assert resp.status_code == 201, resp.text


def test_admin_role_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BADM")
    w = _role_worker(db, "BADM", "CHIEF_WELDER", scope_type="GLOBAL")
    resp = client.post(
        BULK_URL,
        json=ctx.payload(created_by=w.id, key="K-a"),
        headers=ctx.headers(w),
    )
    assert resp.status_code == 201, resp.text


# ── Ошибки строк ──────────────────────────────────────────────────────────────


def test_duplicate_joint_no_in_batch(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDUP")
    items = [{"joint_no": "J-1"}, {"joint_no": "J-2"}, {"joint_no": "J-1"}]
    resp = _bulk(client, ctx, items=items)
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    dup = [e for e in errors if e["code"] == "DUPLICATE_JOINT_NO_IN_BATCH"]
    # Ошибка для ВСЕХ конфликтующих строк (0 и 2), не только для второй.
    assert {e["row_index"] for e in dup} == {0, 2}


def test_duplicate_normalized_variants(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDNV")
    # 'j–1' (en dash, lower) нормализуется в 'J-1'.
    items = [{"joint_no": "J-1"}, {"joint_no": "j–1"}]
    resp = _bulk(client, ctx, items=items)
    assert resp.status_code == 422
    dup = [
        e for e in resp.json()["detail"]["errors"]
        if e["code"] == "DUPLICATE_JOINT_NO_IN_BATCH"
    ]
    assert {e["row_index"] for e in dup} == {0, 1}


def test_conflict_with_existing_joint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BEXIST")
    # Создаём Joint J-1 в этой ревизии одиночно.
    single = client.post(
        f"{ENGINEERING_URL}/joints",
        json={
            "project_id": str(ctx.project.id),
            "line_id": str(ctx.line.id),
            "document_revision_id": str(ctx.revision.id),
            "joint_no": "J-1",
            "created_by": ctx.creator.id,
        },
        headers=ctx.headers(),
    )
    assert single.status_code == 201
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-x")
    assert resp.status_code == 422
    codes = _bulk_error_codes(resp)
    assert "JOINT_NO_ALREADY_EXISTS_IN_REVISION" in codes


def test_same_no_other_revision_ok(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BOTHREV")
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-r0")
    assert resp.status_code == 201
    rev2 = ctx.revision2()
    resp2 = client.post(
        BULK_URL,
        json=ctx.payload(
            items=[{"joint_no": "J-1"}],
            document_revision_id=str(rev2.id),
            key="K-r1",
        ),
        headers=ctx.headers(),
    )
    assert resp2.status_code == 201, resp2.text


def test_multiple_errors_one_response(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BMULTI")
    # Общая ошибка (чужая линия) + строковая (дубль в пакете) в одном ответе.
    other = Ctx(db, "BMULTI2")
    items = [{"joint_no": "J-1"}, {"joint_no": "J-1"}]
    resp = client.post(
        BULK_URL,
        json=ctx.payload(items=items, line_id=str(other.line.id)),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    codes = {e["code"] for e in errors}
    assert "LINE_PROJECT_MISMATCH" in codes
    assert "DUPLICATE_JOINT_NO_IN_BATCH" in codes
    # Общие ошибки идут перед строковыми; общие без row_index, строковые с ним.
    general = [e for e in errors if "row_index" not in e]
    rows = [e for e in errors if "row_index" in e]
    assert general and rows
    first_row_pos = next(
        i for i, e in enumerate(errors) if "row_index" in e
    )
    last_general_pos = max(
        i for i, e in enumerate(errors) if "row_index" not in e
    )
    assert last_general_pos < first_row_pos
    # row_index соответствует позиции; сортировка по возрастанию.
    row_indexes = [e["row_index"] for e in rows]
    assert row_indexes == sorted(row_indexes)


# ── Атомарность ───────────────────────────────────────────────────────────────


def _count_joints(db: Session, project_id) -> int:
    return db.query(Joint).filter(Joint.project_id == project_id).count()


def test_no_partial_import_on_row_error(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BNOPART")
    items = [{"joint_no": "J-1"}, {"joint_no": "J-1"}]  # дубль
    resp = _bulk(client, ctx, items=items)
    assert resp.status_code == 422
    # Ни один Joint / bulk-request не создан.
    assert _count_joints(db, ctx.project.id) == 0
    rows = db.execute(
        text(
            f"SELECT count(*) FROM {ENGINEERING_SCHEMA}.joint_bulk_requests "
            "WHERE project_id = :pid"
        ),
        {"pid": str(ctx.project.id)},
    ).scalar()
    assert rows == 0


def test_error_in_last_row_rolls_back_all(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BLASTROW")
    items = [{"joint_no": f"J-{i}"} for i in range(5)]
    items.append({"joint_no": "J-0"})  # дубль последней строки
    resp = _bulk(client, ctx, items=items)
    assert resp.status_code == 422
    assert _count_joints(db, ctx.project.id) == 0


def test_system_code_not_consumed_on_validation_error(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "BSCV")
    bad = _bulk(client, ctx, items=[{"joint_no": "J-1"}, {"joint_no": "J-1"}])
    assert bad.status_code == 422
    # Следующее одиночное создание получает -0001 (последовательность не тронута).
    single = client.post(
        f"{ENGINEERING_URL}/joints",
        json={
            "project_id": str(ctx.project.id),
            "line_id": str(ctx.line.id),
            "document_revision_id": str(ctx.revision.id),
            "joint_no": "J-ok",
            "created_by": ctx.creator.id,
        },
        headers=ctx.headers(),
    )
    assert single.status_code == 201, single.text
    assert single.json()["system_code"] == f"{ctx.project.code}-JNT-0001"


def test_artificial_phase2_error_rolls_back(
    client: TestClient, db: Session, monkeypatch
) -> None:
    ctx = Ctx(db, "BART")
    svc = JointBulkService(db)

    original_add_link = EngineeringRepo.add_link
    state = {"calls": 0}

    def failing_add_link(self, link):
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("искусственная ошибка фазы 2")
        return original_add_link(self, link)

    monkeypatch.setattr(EngineeringRepo, "add_link", failing_add_link)

    payload = JointBulkCreate(**ctx.payload(
        items=[{"joint_no": "J-1"}, {"joint_no": "J-2"}], key="K-art"
    ))
    try:
        svc.create_bulk(payload=payload, actor_worker_id=ctx.creator.id)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    # Полный rollback: ни один Joint, ни один счётчик, ни один bulk-request.
    assert _count_joints(db, ctx.project.id) == 0
    seq = db.query(JointSequence).filter(
        JointSequence.project_id == ctx.project.id
    ).one_or_none()
    assert seq is None
    # Сессия остаётся пригодной для последующих операций.
    assert db.execute(text("SELECT 1")).scalar() == 1


# ── Идемпотентность ───────────────────────────────────────────────────────────


def test_replay_returns_stored_payload(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BREPLAY")
    first = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-rep")
    assert first.status_code == 201
    body1 = first.json()

    second = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-rep")
    assert second.status_code == 200
    assert second.json() == body1
    # Повтор не создаёт второй Joint и вторую bulk-запись.
    assert _count_joints(db, ctx.project.id) == 1
    rows = db.execute(
        text(
            f"SELECT count(*) FROM {ENGINEERING_SCHEMA}.joint_bulk_requests "
            "WHERE project_id = :pid"
        ),
        {"pid": str(ctx.project.id)},
    ).scalar()
    assert rows == 1


def test_replay_does_not_create_links(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BREPL2")
    first = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-rl")
    jid = first.json()["items"][0]["id"]
    _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-rl")
    assert len(_links(client, ctx, jid)) == 1


def test_conflict_same_key_other_body(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCONF")
    assert _bulk(
        client, ctx, items=[{"joint_no": "J-1"}], key="K-c"
    ).status_code == 201
    resp = _bulk(client, ctx, items=[{"joint_no": "J-2"}], key="K-c")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_hash_row_order_changes(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BHRO")
    assert _bulk(
        client, ctx,
        items=[{"joint_no": "J-1"}, {"joint_no": "J-2"}], key="K-h",
    ).status_code == 201
    # Тот же ключ, но переставленные строки → другой hash → конфликт.
    resp = _bulk(
        client, ctx,
        items=[{"joint_no": "J-2"}, {"joint_no": "J-1"}], key="K-h",
    )
    assert resp.status_code == 409


def test_hash_common_field_changes(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BHCF")
    rev2 = ctx.revision2()
    assert _bulk(
        client, ctx, items=[{"joint_no": "J-1"}], key="K-cf"
    ).status_code == 201
    resp = client.post(
        BULK_URL,
        json=ctx.payload(
            items=[{"joint_no": "J-1"}],
            document_revision_id=str(rev2.id),
            key="K-cf",
        ),
        headers=ctx.headers(),
    )
    assert resp.status_code == 409


def test_hash_item_field_changes(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BHIF")
    assert _bulk(
        client, ctx, items=[{"joint_no": "J-1", "dn_1": 100}], key="K-if"
    ).status_code == 201
    resp = _bulk(client, ctx, items=[{"joint_no": "J-1", "dn_1": 200}], key="K-if")
    assert resp.status_code == 409


def test_hash_key_order_stable(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BHKO")
    assert _bulk(
        client, ctx,
        items=[{"joint_no": "J-1", "dn_1": 100, "thickness_1": 6}],
        key="K-ko",
    ).status_code == 201
    # Те же данные, другой порядок ключей в JSON → тот же hash → replay 200.
    resp = _bulk(
        client, ctx,
        items=[{"thickness_1": 6, "dn_1": 100, "joint_no": "J-1"}],
        key="K-ko",
    )
    assert resp.status_code == 200


def test_hash_excludes_idempotency_key(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BHEK")
    base = ctx.payload(items=[{"joint_no": "J-1"}], key="A")
    other = ctx.payload(items=[{"joint_no": "J-1"}], key="B")
    h1 = calculate_bulk_request_hash(JointBulkCreate(**base))
    h2 = calculate_bulk_request_hash(JointBulkCreate(**other))
    assert h1 == h2


def test_key_normalized_by_trim(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BTRIM")
    first = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="  K-t  ")
    assert first.status_code == 201
    # Тот же ключ без пробелов и то же тело → replay.
    second = _bulk(client, ctx, items=[{"joint_no": "J-1"}], key="K-t")
    assert second.status_code == 200
    # В БД ключ сохранён обрезанным.
    stored = db.execute(
        text(
            f"SELECT idempotency_key FROM {ENGINEERING_SCHEMA}."
            "joint_bulk_requests WHERE project_id = :pid"
        ),
        {"pid": str(ctx.project.id)},
    ).scalar()
    assert stored == "K-t"


def test_key_case_sensitive(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCASE")
    assert _bulk(
        client, ctx, items=[{"joint_no": "J-1"}], key="Key"
    ).status_code == 201
    # Другой регистр — другой ключ → новый запрос (не replay, не конфликт).
    resp = _bulk(client, ctx, items=[{"joint_no": "J-2"}], key="key")
    assert resp.status_code == 201


def test_same_key_different_projects(client: TestClient, db: Session) -> None:
    ctx_a = Ctx(db, "BKPA")
    ctx_b = Ctx(db, "BKPB")
    assert _bulk(
        client, ctx_a, items=[{"joint_no": "J-1"}], key="SHARED"
    ).status_code == 201
    assert _bulk(
        client, ctx_b, items=[{"joint_no": "J-1"}], key="SHARED"
    ).status_code == 201


# ── Конкурентность (эмуляция гонки pre-check) ─────────────────────────────────


def _race_skip_precheck(monkeypatch):
    """Эмулирует гонку: pre-check idempotency один раз «не видит» запись (как две
    параллельные транзакции, не увидевшие друг друга), но повторное чтение после
    IntegrityError работает штатно (2-й вызов — реальный)."""
    original = EngineeringRepo.get_joint_bulk_request
    state = {"skipped": False}

    def racing(self, project_id, idempotency_key):
        if not state["skipped"]:
            state["skipped"] = True
            return None
        return original(self, project_id, idempotency_key)

    monkeypatch.setattr(EngineeringRepo, "get_joint_bulk_request", racing)


def _insert_bulk_request(
    db: Session, ctx: Ctx, *, key: str, request_hash: str, payload: dict
) -> None:
    """Заранее вставляет запись пакета (без создания Joint) — фиксирует состояние,
    которое конкурентная транзакция закоммитила первой."""
    db.execute(
        text(
            f"INSERT INTO {ENGINEERING_SCHEMA}.joint_bulk_requests "
            "(id, project_id, idempotency_key, request_hash, status, "
            "response_payload, created_by, created_at) VALUES "
            "(:id, :pid, :key, :hash, 'COMPLETED', CAST(:payload AS jsonb), "
            ":cb, now())"
        ),
        {
            "id": str(uuid4()),
            "pid": str(ctx.project.id),
            "key": key,
            "hash": request_hash,
            "payload": json.dumps(payload),
            "cb": ctx.creator.id,
        },
    )
    db.commit()


def _valid_stored_payload(ctx: Ctx) -> dict:
    return {
        "bulk_request_id": str(uuid4()),
        "project_id": str(ctx.project.id),
        "line_id": str(ctx.line.id),
        "document_revision_id": str(ctx.revision.id),
        "created_by": ctx.creator.id,
        "created_count": 1,
        "items": [
            {
                "row_index": 0,
                "id": str(uuid4()),
                "system_code": f"{ctx.project.code}-JNT-0001",
                "joint_no": "J-1",
            }
        ],
    }


def test_concurrent_conflict_same_hash_replays(
    client: TestClient, db: Session, monkeypatch
) -> None:
    ctx = Ctx(db, "BRACE1")
    body = ctx.payload(items=[{"joint_no": "J-1"}], key="K-race")
    request_hash = calculate_bulk_request_hash(JointBulkCreate(**body))
    stored = _valid_stored_payload(ctx)
    # Конкурентная транзакция уже зафиксировала запись пакета с тем же hash.
    _insert_bulk_request(db, ctx, key="K-race", request_hash=request_hash, payload=stored)

    _race_skip_precheck(monkeypatch)
    # pre-check «пропущен» → фаза 2 → UNIQUE(project,key) → rollback → replay.
    resp = client.post(BULK_URL, json=body, headers=ctx.headers())
    assert resp.status_code == 200
    assert resp.json() == stored
    # Наш пакет полностью откатан: Joint не создан.
    assert _count_joints(db, ctx.project.id) == 0


def test_concurrent_conflict_other_hash_409(
    client: TestClient, db: Session, monkeypatch
) -> None:
    ctx = Ctx(db, "BRACE2")
    body = ctx.payload(items=[{"joint_no": "J-1"}], key="K-race2")
    # Заранее вставленная запись с ДРУГИМ hash.
    _insert_bulk_request(
        db, ctx, key="K-race2", request_hash="deadbeef" * 8,
        payload=_valid_stored_payload(ctx),
    )
    _race_skip_precheck(monkeypatch)
    resp = client.post(BULK_URL, json=body, headers=ctx.headers())
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    # Сессия пригодна после IntegrityError + rollback.
    assert db.execute(text("SELECT 1")).scalar() == 1
    assert _count_joints(db, ctx.project.id) == 0


def test_session_usable_after_integrity_error(
    client: TestClient, db: Session, monkeypatch
) -> None:
    ctx = Ctx(db, "BRACE3")
    body = ctx.payload(items=[{"joint_no": "J-1"}], key="K-race3")
    request_hash = calculate_bulk_request_hash(JointBulkCreate(**body))
    _insert_bulk_request(
        db, ctx, key="K-race3", request_hash=request_hash,
        payload=_valid_stored_payload(ctx),
    )
    _race_skip_precheck(monkeypatch)
    replay = client.post(BULK_URL, json=body, headers=ctx.headers())
    assert replay.status_code == 200
    # Последующая штатная операция после IntegrityError+rollback работает.
    resp = _bulk(client, ctx, items=[{"joint_no": "J-9"}], key="K-after")
    assert resp.status_code == 201


# ── Regression: одиночное создание не изменено ────────────────────────────────


def test_single_create_still_works(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BSINGLE")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json={
            "project_id": str(ctx.project.id),
            "line_id": str(ctx.line.id),
            "document_revision_id": str(ctx.revision.id),
            "joint_no": "J-1",
            "created_by": ctx.creator.id,
        },
        headers=ctx.headers(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert body["system_code"] == f"{ctx.project.code}-JNT-0001"
