"""Интеграционные тесты модуля engineering (Task 4): engineering_documents и
document_revisions.

Владелец инженерных документов — ПТО (технический role_code `PTO_ENGINEER`,
IP-07). Создание и переходы (approve/cancel/supersede) выполняет `PTO_ENGINEER`
в допустимом scope:

- GLOBAL — всегда;
- PROJECT — scope_id совпадает с project_id документа;
- LINE — только если документ привязан к line_id и scope_id совпадает с line_id.

Для DocumentRevision scope наследуется от родительского EngineeringDocument.
Физического DELETE подтверждённых сущностей нет (история вместо перезаписи).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"


# ── Хелперы данных ────────────────────────────────────────────────────────────


def _create_worker(db: Session, *, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Eng{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=date.today(),
    )
    db.add(worker)
    db.flush()
    return worker


def _assign_role(
    db: Session,
    *,
    worker_id: int,
    role_code: str,
    scope_type: str = "GLOBAL",
    scope_id: str | None = None,
) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=True,
        valid_from=date.today(),
    )
    db.add(role)
    db.flush()
    return role


def _make_worker_with_role(
    db: Session,
    *,
    suffix: str,
    role_code: str,
    scope_type: str = "GLOBAL",
    scope_id: str | None = None,
) -> Worker:
    worker = _create_worker(db, suffix=suffix)
    _assign_role(
        db,
        worker_id=worker.id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    db.commit()
    db.refresh(worker)
    return worker


def _make_author(db: Session, *, suffix: str) -> Worker:
    worker = _create_worker(db, suffix=suffix)
    db.commit()
    db.refresh(worker)
    return worker


def _make_project(db: Session, *, author_id: int, code: str) -> Project:
    project = Project(
        code=code,
        name=f"Проект {code}",
        status="active",
        created_by=author_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _make_line(db: Session, *, project_id: UUID, author_id: int, line_no: str) -> Line:
    line = Line(
        project_id=project_id,
        line_no=line_no,
        status="active",
        required_inspection_types=[],
        created_by=author_id,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _headers(worker: Worker) -> dict[str, str]:
    return {"X-User-Id": str(worker.id)}


def _doc_payload(project_id: UUID, **overrides) -> dict:
    payload: dict = {
        "project_id": str(project_id),
        "document_no": "DOC-001",
        "document_type": "ISOMETRIC",
    }
    payload.update(overrides)
    return payload


def _create_document(
    client: TestClient, worker: Worker, project_id: UUID, **overrides
) -> dict:
    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project_id, **overrides),
        headers=_headers(worker),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Первый failing test (план 4.1) ────────────────────────────────────────────


def test_pto_engineer_creates_and_approves_document(
    client: TestClient, db: Session
) -> None:
    author = _make_author(db, suffix="MainAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-MAIN")
    pto = _make_worker_with_role(
        db,
        suffix="MainPto",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(project.id),
    )

    doc = _create_document(client, pto, project.id, document_no="DOC-MAIN")
    assert doc["status"] == "DRAFT"
    UUID(doc["id"])

    # Ревизия внутри документа.
    rev_resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        json={"revision_code": "R0"},
        headers=_headers(pto),
    )
    assert rev_resp.status_code == 201, rev_resp.text
    rev = rev_resp.json()
    assert rev["status"] == "DRAFT"

    # approve документа.
    appr_doc = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/approve",
        headers=_headers(pto),
    )
    assert appr_doc.status_code == 200, appr_doc.text
    body = appr_doc.json()
    assert body["status"] == "APPROVED"
    assert body["approved_by"] == pto.id
    assert body["approved_at"] is not None

    # approve ревизии.
    appr_rev = client.post(
        f"{ENGINEERING_URL}/revisions/{rev['id']}/approve",
        headers=_headers(pto),
    )
    assert appr_rev.status_code == 200, appr_rev.text
    assert appr_rev.json()["status"] == "APPROVED"


# ── Создание документа: scope ─────────────────────────────────────────────────


def test_global_pto_creates_document(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="GlobalPto", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-GLOB")

    doc = _create_document(client, pto, project.id, document_no="DOC-G")
    assert doc["project_id"] == str(project.id)


def test_project_scope_pto_creates_document(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="ProjScopeAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-PROJ")
    pto = _make_worker_with_role(
        db,
        suffix="ProjScope",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(project.id),
    )

    _create_document(client, pto, project.id, document_no="DOC-P")


def test_line_scope_pto_creates_document_with_line(
    client: TestClient, db: Session
) -> None:
    author = _make_author(db, suffix="LineScopeAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-LINE")
    line = _make_line(db, project_id=project.id, author_id=author.id, line_no="L-1")
    pto = _make_worker_with_role(
        db,
        suffix="LineScope",
        role_code="PTO_ENGINEER",
        scope_type="LINE",
        scope_id=str(line.id),
    )

    doc = _create_document(
        client, pto, project.id, document_no="DOC-L", line_id=str(line.id)
    )
    assert doc["line_id"] == str(line.id)


def test_line_scope_cannot_create_without_line_403(
    client: TestClient, db: Session
) -> None:
    author = _make_author(db, suffix="LineNoLineAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-LINE-NO")
    line = _make_line(db, project_id=project.id, author_id=author.id, line_no="L-2")
    pto = _make_worker_with_role(
        db,
        suffix="LineNoLine",
        role_code="PTO_ENGINEER",
        scope_type="LINE",
        scope_id=str(line.id),
    )

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-NL"),
        headers=_headers(pto),
    )
    assert resp.status_code == 403


def test_foreign_project_scope_pto_403(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="ForeignProjAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-FP")
    pto = _make_worker_with_role(
        db,
        suffix="ForeignProj",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(uuid4()),
    )

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-FP"),
        headers=_headers(pto),
    )
    assert resp.status_code == 403


def test_foreign_line_scope_pto_403(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="ForeignLineAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-FL")
    line = _make_line(db, project_id=project.id, author_id=author.id, line_no="L-3")
    pto = _make_worker_with_role(
        db,
        suffix="ForeignLine",
        role_code="PTO_ENGINEER",
        scope_type="LINE",
        scope_id=str(uuid4()),
    )

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-FL", line_id=str(line.id)),
        headers=_headers(pto),
    )
    assert resp.status_code == 403


def test_foreman_cannot_create_document_403(client: TestClient, db: Session) -> None:
    foreman = _make_worker_with_role(db, suffix="Foreman", role_code="FOREMAN")
    project = _make_project(db, author_id=foreman.id, code="ENG-FM")

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-FM"),
        headers=_headers(foreman),
    )
    assert resp.status_code == 403


def test_master_cannot_create_document_403(client: TestClient, db: Session) -> None:
    master = _make_worker_with_role(db, suffix="Master", role_code="MASTER")
    project = _make_project(db, author_id=master.id, code="ENG-MS")

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-MS"),
        headers=_headers(master),
    )
    assert resp.status_code == 403


# ── Создание документа: консистентность и валидация ───────────────────────────


def test_unknown_project_404(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="UnkProj", role_code="PTO_ENGINEER")

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(uuid4(), document_no="DOC-UP"),
        headers=_headers(pto),
    )
    assert resp.status_code == 404


def test_line_of_other_project_422(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="CrossLine", role_code="PTO_ENGINEER")
    p1 = _make_project(db, author_id=pto.id, code="ENG-XL-1")
    p2 = _make_project(db, author_id=pto.id, code="ENG-XL-2")
    other_line = _make_line(db, project_id=p2.id, author_id=pto.id, line_no="L-X")

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(p1.id, document_no="DOC-XL", line_id=str(other_line.id)),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_document_no_required_not_empty_422(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="EmptyNo", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-EMPTY")

    for bad in ("", "   "):
        resp = client.post(
            f"{ENGINEERING_URL}/documents",
            json=_doc_payload(project.id, document_no=bad),
            headers=_headers(pto),
        )
        assert resp.status_code == 422, resp.text


def test_duplicate_document_no_conflict_409(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="DupNo", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-DUP")

    _create_document(client, pto, project.id, document_no="DOC-DUP")
    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-DUP"),
        headers=_headers(pto),
    )
    assert resp.status_code == 409


def test_same_document_no_allowed_in_different_projects(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="SameNo", role_code="PTO_ENGINEER")
    p1 = _make_project(db, author_id=pto.id, code="ENG-SAME-1")
    p2 = _make_project(db, author_id=pto.id, code="ENG-SAME-2")

    _create_document(client, pto, p1.id, document_no="DOC-SAME")
    _create_document(client, pto, p2.id, document_no="DOC-SAME")


def test_invalid_document_type_422(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="BadType", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-BT")

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-BT", document_type="SKETCH"),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_document_types_accepted(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="AllTypes", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-AT")

    for i, dtype in enumerate(("ISOMETRIC", "DRAWING", "WELD_MAP", "OTHER")):
        _create_document(
            client, pto, project.id, document_no=f"DOC-AT-{i}", document_type=dtype
        )


def test_document_initial_status_draft(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="InitStatus", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-INIT")

    doc = _create_document(client, pto, project.id, document_no="DOC-INIT")
    assert doc["status"] == "DRAFT"
    assert doc["approved_by"] is None
    assert doc["approved_at"] is None


# ── Чтение и фильтры ──────────────────────────────────────────────────────────


def test_get_document(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="GetOne", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-GET")
    doc = _create_document(client, pto, project.id, document_no="DOC-GET")

    resp = client.get(
        f"{ENGINEERING_URL}/documents/{doc['id']}", headers=_headers(pto)
    )
    assert resp.status_code == 200
    assert resp.json()["document_no"] == "DOC-GET"


def test_get_missing_document_404(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="MissDoc", role_code="PTO_ENGINEER")
    resp = client.get(
        f"{ENGINEERING_URL}/documents/{uuid4()}", headers=_headers(pto)
    )
    assert resp.status_code == 404


def test_list_and_filter_documents(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="ListFilter", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-LF")
    line = _make_line(db, project_id=project.id, author_id=pto.id, line_no="L-LF")

    _create_document(
        client, pto, project.id, document_no="DOC-LF-ISO", document_type="ISOMETRIC"
    )
    _create_document(
        client,
        pto,
        project.id,
        document_no="DOC-LF-DRW",
        document_type="DRAWING",
        line_id=str(line.id),
    )

    # Фильтр по project_id.
    by_project = client.get(
        f"{ENGINEERING_URL}/documents",
        params={"project_id": str(project.id)},
        headers=_headers(pto),
    )
    assert by_project.status_code == 200
    nos = {d["document_no"] for d in by_project.json()}
    assert {"DOC-LF-ISO", "DOC-LF-DRW"} <= nos

    # Фильтр по document_type.
    by_type = client.get(
        f"{ENGINEERING_URL}/documents",
        params={"project_id": str(project.id), "document_type": "DRAWING"},
        headers=_headers(pto),
    )
    assert by_type.status_code == 200
    type_nos = {d["document_no"] for d in by_type.json()}
    assert "DOC-LF-DRW" in type_nos
    assert "DOC-LF-ISO" not in type_nos

    # Фильтр по line_id.
    by_line = client.get(
        f"{ENGINEERING_URL}/documents",
        params={"line_id": str(line.id)},
        headers=_headers(pto),
    )
    assert by_line.status_code == 200
    line_nos = {d["document_no"] for d in by_line.json()}
    assert line_nos == {"DOC-LF-DRW"}

    # Фильтр по status.
    by_status = client.get(
        f"{ENGINEERING_URL}/documents",
        params={"project_id": str(project.id), "status": "DRAFT"},
        headers=_headers(pto),
    )
    assert by_status.status_code == 200
    assert {"DOC-LF-ISO", "DOC-LF-DRW"} <= {
        d["document_no"] for d in by_status.json()
    }


def test_create_document_without_user_id_401(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="NoAuthDoc")
    project = _make_project(db, author_id=author.id, code="ENG-NOAUTH")

    resp = client.post(
        f"{ENGINEERING_URL}/documents",
        json=_doc_payload(project.id, document_no="DOC-NA"),
    )
    assert resp.status_code == 401


# ── DocumentRevision ──────────────────────────────────────────────────────────


def test_revision_requires_existing_document_404(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RevNoDoc", role_code="PTO_ENGINEER")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{uuid4()}/revisions",
        json={"revision_code": "R0"},
        headers=_headers(pto),
    )
    assert resp.status_code == 404


def test_revision_code_required_not_empty_422(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RevEmpty", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-REV-E")
    doc = _create_document(client, pto, project.id, document_no="DOC-RE")

    for bad in ("", "  "):
        resp = client.post(
            f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
            json={"revision_code": bad},
            headers=_headers(pto),
        )
        assert resp.status_code == 422, resp.text


def test_duplicate_revision_code_conflict_409(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RevDup", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-REV-D")
    doc = _create_document(client, pto, project.id, document_no="DOC-RD")

    first = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        json={"revision_code": "R1"},
        headers=_headers(pto),
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        json={"revision_code": "R1"},
        headers=_headers(pto),
    )
    assert second.status_code == 409


def test_same_revision_code_allowed_in_different_documents(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RevSame", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-REV-S")
    doc1 = _create_document(client, pto, project.id, document_no="DOC-RS-1")
    doc2 = _create_document(client, pto, project.id, document_no="DOC-RS-2")

    for doc in (doc1, doc2):
        resp = client.post(
            f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
            json={"revision_code": "R0"},
            headers=_headers(pto),
        )
        assert resp.status_code == 201, resp.text


def test_revision_initial_status_draft(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RevInit", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-REV-I")
    doc = _create_document(client, pto, project.id, document_no="DOC-RI")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        json={"revision_code": "R0", "issued_at": "2026-07-10"},
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert body["issued_at"] == "2026-07-10"
    assert body["approved_by"] is None


def test_list_revisions_of_document(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RevList", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-REV-L")
    doc = _create_document(client, pto, project.id, document_no="DOC-RL")

    for code in ("R0", "R1"):
        client.post(
            f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
            json={"revision_code": code},
            headers=_headers(pto),
        )

    resp = client.get(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        headers=_headers(pto),
    )
    assert resp.status_code == 200
    codes = {r["revision_code"] for r in resp.json()}
    assert {"R0", "R1"} <= codes


def test_revision_scope_inherited_from_document(
    client: TestClient, db: Session
) -> None:
    author = _make_author(db, suffix="RevScopeAuthor")
    project = _make_project(db, author_id=author.id, code="ENG-REV-SC")
    global_pto = _make_worker_with_role(
        db, suffix="RevScopeGlobal", role_code="PTO_ENGINEER"
    )
    doc = _create_document(client, global_pto, project.id, document_no="DOC-RSC")

    # PTO с PROJECT scope того же проекта может создать ревизию.
    proj_pto = _make_worker_with_role(
        db,
        suffix="RevScopeProj",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(project.id),
    )
    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        json={"revision_code": "R0"},
        headers=_headers(proj_pto),
    )
    assert resp.status_code == 201, resp.text


def test_foreign_scope_cannot_create_revision_403(
    client: TestClient, db: Session
) -> None:
    global_pto = _make_worker_with_role(
        db, suffix="RevForeignGlobal", role_code="PTO_ENGINEER"
    )
    project = _make_project(db, author_id=global_pto.id, code="ENG-REV-FS")
    doc = _create_document(client, global_pto, project.id, document_no="DOC-RFS")

    foreign_pto = _make_worker_with_role(
        db,
        suffix="RevForeign",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(uuid4()),
    )
    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/revisions",
        json={"revision_code": "R0"},
        headers=_headers(foreign_pto),
    )
    assert resp.status_code == 403


# ── Переходы: документ ────────────────────────────────────────────────────────


def _approved_document(client: TestClient, worker: Worker, project_id: UUID, **kw):
    doc = _create_document(client, worker, project_id, **kw)
    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/approve",
        headers=_headers(worker),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_approve_document_draft_to_approved(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="ApprDoc", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-APP")

    body = _approved_document(client, pto, project.id, document_no="DOC-APP")
    assert body["status"] == "APPROVED"
    assert body["approved_by"] == pto.id
    assert body["approved_at"] is not None


def test_cancel_draft_document(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="CancDraft", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-CD")
    doc = _create_document(client, pto, project.id, document_no="DOC-CD")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/cancel",
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CANCELLED"
    assert body["approved_by"] is None


def test_cancel_approved_document_keeps_approval(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="CancAppr", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-CA")
    approved = _approved_document(client, pto, project.id, document_no="DOC-CA")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{approved['id']}/cancel",
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "CANCELLED"
    # approved_by/at не стираются при отмене ранее утверждённого документа.
    assert body["approved_by"] == pto.id
    assert body["approved_at"] is not None


def test_supersede_approved_document(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="SupAppr", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-SUP")
    approved = _approved_document(client, pto, project.id, document_no="DOC-SUP")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{approved['id']}/supersede",
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "SUPERSEDED"


def test_supersede_draft_document_invalid_409(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="SupDraft", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-SD")
    doc = _create_document(client, pto, project.id, document_no="DOC-SD")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/supersede",
        headers=_headers(pto),
    )
    assert resp.status_code == 409


def test_double_approve_document_409(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="DblAppr", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-DA")
    approved = _approved_document(client, pto, project.id, document_no="DOC-DA")

    resp = client.post(
        f"{ENGINEERING_URL}/documents/{approved['id']}/approve",
        headers=_headers(pto),
    )
    assert resp.status_code == 409


def test_cancelled_document_not_changeable_409(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="CancFrozen", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-CF")
    doc = _create_document(client, pto, project.id, document_no="DOC-CF")
    client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/cancel", headers=_headers(pto)
    )

    for action in ("approve", "cancel", "supersede"):
        resp = client.post(
            f"{ENGINEERING_URL}/documents/{doc['id']}/{action}",
            headers=_headers(pto),
        )
        assert resp.status_code == 409, action


def test_superseded_document_not_changeable_409(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="SupFrozen", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-SF")
    approved = _approved_document(client, pto, project.id, document_no="DOC-SF")
    client.post(
        f"{ENGINEERING_URL}/documents/{approved['id']}/supersede",
        headers=_headers(pto),
    )

    for action in ("approve", "cancel", "supersede"):
        resp = client.post(
            f"{ENGINEERING_URL}/documents/{approved['id']}/{action}",
            headers=_headers(pto),
        )
        assert resp.status_code == 409, action


def test_foreign_scope_cannot_approve_document_403(
    client: TestClient, db: Session
) -> None:
    global_pto = _make_worker_with_role(
        db, suffix="ApprForeignGlobal", role_code="PTO_ENGINEER"
    )
    project = _make_project(db, author_id=global_pto.id, code="ENG-AF")
    doc = _create_document(client, global_pto, project.id, document_no="DOC-AF")

    foreign_pto = _make_worker_with_role(
        db,
        suffix="ApprForeign",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(uuid4()),
    )
    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc['id']}/approve",
        headers=_headers(foreign_pto),
    )
    assert resp.status_code == 403


def test_transition_missing_document_404(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="TransMiss", role_code="PTO_ENGINEER")
    resp = client.post(
        f"{ENGINEERING_URL}/documents/{uuid4()}/approve",
        headers=_headers(pto),
    )
    assert resp.status_code == 404


def test_approve_document_without_user_id_401(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="ApprNoAuth", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-APP-NA")
    doc = _create_document(client, pto, project.id, document_no="DOC-APNA")

    resp = client.post(f"{ENGINEERING_URL}/documents/{doc['id']}/approve")
    assert resp.status_code == 401


# ── Переходы: ревизия ─────────────────────────────────────────────────────────


def _create_revision(client: TestClient, worker: Worker, doc_id: str, **kw) -> dict:
    payload = {"revision_code": "R0"}
    payload.update(kw)
    resp = client.post(
        f"{ENGINEERING_URL}/documents/{doc_id}/revisions",
        json=payload,
        headers=_headers(worker),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_approve_revision_draft_to_approved(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="ApprRev", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-RAPP")
    doc = _create_document(client, pto, project.id, document_no="DOC-RAPP")
    rev = _create_revision(client, pto, doc["id"])

    resp = client.post(
        f"{ENGINEERING_URL}/revisions/{rev['id']}/approve",
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert body["approved_by"] == pto.id


def test_cancel_and_supersede_revision(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RevLifecycle", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-RLC")
    doc = _create_document(client, pto, project.id, document_no="DOC-RLC")

    # cancel из DRAFT.
    r_cancel = _create_revision(client, pto, doc["id"], revision_code="RC")
    resp = client.post(
        f"{ENGINEERING_URL}/revisions/{r_cancel['id']}/cancel",
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"

    # supersede из APPROVED.
    r_sup = _create_revision(client, pto, doc["id"], revision_code="RS")
    client.post(
        f"{ENGINEERING_URL}/revisions/{r_sup['id']}/approve", headers=_headers(pto)
    )
    resp = client.post(
        f"{ENGINEERING_URL}/revisions/{r_sup['id']}/supersede",
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "SUPERSEDED"


def test_double_approve_revision_409(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RevDblAppr", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-RDA")
    doc = _create_document(client, pto, project.id, document_no="DOC-RDA")
    rev = _create_revision(client, pto, doc["id"])
    client.post(
        f"{ENGINEERING_URL}/revisions/{rev['id']}/approve", headers=_headers(pto)
    )

    resp = client.post(
        f"{ENGINEERING_URL}/revisions/{rev['id']}/approve",
        headers=_headers(pto),
    )
    assert resp.status_code == 409


def test_cancelled_revision_not_changeable_409(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RevFrozen", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-RF")
    doc = _create_document(client, pto, project.id, document_no="DOC-RF")
    rev = _create_revision(client, pto, doc["id"])
    client.post(
        f"{ENGINEERING_URL}/revisions/{rev['id']}/cancel", headers=_headers(pto)
    )

    for action in ("approve", "cancel", "supersede"):
        resp = client.post(
            f"{ENGINEERING_URL}/revisions/{rev['id']}/{action}",
            headers=_headers(pto),
        )
        assert resp.status_code == 409, action


def test_supersede_draft_revision_invalid_409(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RevSupDraft", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-RSD")
    doc = _create_document(client, pto, project.id, document_no="DOC-RSD")
    rev = _create_revision(client, pto, doc["id"])

    resp = client.post(
        f"{ENGINEERING_URL}/revisions/{rev['id']}/supersede",
        headers=_headers(pto),
    )
    assert resp.status_code == 409


def test_transition_missing_revision_404(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RevMiss", role_code="PTO_ENGINEER")
    resp = client.post(
        f"{ENGINEERING_URL}/revisions/{uuid4()}/approve",
        headers=_headers(pto),
    )
    assert resp.status_code == 404


# ── Отсутствие физического DELETE ─────────────────────────────────────────────


def test_no_delete_document_endpoint(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="NoDelDoc", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="ENG-NODEL")
    doc = _create_document(client, pto, project.id, document_no="DOC-NODEL")

    resp = client.delete(
        f"{ENGINEERING_URL}/documents/{doc['id']}", headers=_headers(pto)
    )
    # Метод DELETE не реализован: маршрут существует только для GET → 405.
    assert resp.status_code == 405
