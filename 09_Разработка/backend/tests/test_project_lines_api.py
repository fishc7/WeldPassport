"""Интеграционные тесты модуля projects (Task 3): project.lines.

Владелец Line — ПТО (технический role_code `PTO_ENGINEER`, IP-07/IP-08).

- POST Line: `PTO_ENGINEER` с GLOBAL или соответствующим PROJECT scope; LINE scope
  для создания не допускается; FOREMAN/MASTER не создают Line.
- PATCH Line: `PTO_ENGINEER` с GLOBAL, соответствующим PROJECT или соответствующим
  LINE scope; FOREMAN/MASTER не изменяют Line.
- GET (list/get) — существующий authenticated pattern: активный `X-User-Id`;
  отсутствие заголовка → 401.

`required_inspection_types` — снимок требуемых видов контроля (ADR-009 004-25);
пустой перечень хранится как пустой массив, не NULL; неизвестные значения и
дубликаты отклоняются (422).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hr.models import Worker, WorkerRole
from app.projects.models import Project

from .conftest import TEST_COMPANY_ID

PROJECTS_URL = "/api/v1/projects"


# ── Хелперы данных ────────────────────────────────────────────────────────────


def _create_worker(db: Session, *, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Line{suffix}",
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


def _headers(worker: Worker) -> dict[str, str]:
    return {"X-User-Id": str(worker.id)}


def _line_payload(**overrides) -> dict:
    payload: dict = {"line_no": "TL-001"}
    payload.update(overrides)
    return payload


# ── Данные: базовые сценарии ──────────────────────────────────────────────────


def test_create_line_for_project(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="GlobalPto", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-CREATE-1")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-100"),
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    UUID(body["id"])  # id — валидный UUID
    assert body["line_no"] == "TL-100"
    assert body["status"] == "draft"


def test_create_line_missing_project_404(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="MissProj", role_code="PTO_ENGINEER")
    missing = uuid4()

    resp = client.post(
        f"{PROJECTS_URL}/{missing}/lines",
        json=_line_payload(),
        headers=_headers(pto),
    )
    assert resp.status_code == 404


def test_duplicate_line_no_conflict(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="DupNo", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-DUP-1")

    first = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-DUP"),
        headers=_headers(pto),
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-DUP"),
        headers=_headers(pto),
    )
    assert second.status_code == 409


def test_same_line_no_allowed_in_different_projects(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="TwoProj", role_code="PTO_ENGINEER")
    p1 = _make_project(db, author_id=pto.id, code="LN-SAME-1")
    p2 = _make_project(db, author_id=pto.id, code="LN-SAME-2")

    for project in (p1, p2):
        resp = client.post(
            f"{PROJECTS_URL}/{project.id}/lines",
            json=_line_payload(line_no="TL-SAME"),
            headers=_headers(pto),
        )
        assert resp.status_code == 201, resp.text


def test_nominal_dn_positive_accepted(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="DnPos", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-DN-POS")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-DN", nominal_dn=100),
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text
    assert float(resp.json()["nominal_dn"]) == 100.0


def test_nominal_dn_zero_rejected(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="DnZero", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-DN-ZERO")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-DN0", nominal_dn=0),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_nominal_dn_negative_rejected(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="DnNeg", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-DN-NEG")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-DNn", nominal_dn=-5),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_invalid_status_rejected(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="BadStatus", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-STATUS")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-ST", status="frozen"),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_required_inspection_types_default_empty(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RitDefault", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-RIT-DEF")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-RITD"),
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["required_inspection_types"] == []


def test_required_inspection_types_persisted(
    client: TestClient, db: Session
) -> None:
    pto = _make_worker_with_role(db, suffix="RitSave", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-RIT-SAVE")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-RIT", required_inspection_types=["VT", "RT"]),
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["required_inspection_types"] == ["VT", "RT"]

    line_id = resp.json()["id"]
    got = client.get(f"{PROJECTS_URL}/lines/{line_id}", headers=_headers(pto))
    assert got.status_code == 200
    assert got.json()["required_inspection_types"] == ["VT", "RT"]


def test_unknown_inspection_type_rejected(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RitUnknown", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-RIT-UNK")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-U", required_inspection_types=["VT", "XX"]),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_duplicate_inspection_types_rejected(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="RitDup", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-RIT-DUP")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-D", required_inspection_types=["VT", "VT"]),
        headers=_headers(pto),
    )
    assert resp.status_code == 422


def test_get_line(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="GetOne", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-GET")
    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-GET"),
        headers=_headers(pto),
    ).json()

    resp = client.get(f"{PROJECTS_URL}/lines/{created['id']}", headers=_headers(pto))
    assert resp.status_code == 200
    assert resp.json()["line_no"] == "TL-GET"


def test_list_lines_of_project(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="ListP", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-LIST")
    for no in ("TL-L1", "TL-L2"):
        client.post(
            f"{PROJECTS_URL}/{project.id}/lines",
            json=_line_payload(line_no=no),
            headers=_headers(pto),
        )

    resp = client.get(f"{PROJECTS_URL}/{project.id}/lines", headers=_headers(pto))
    assert resp.status_code == 200
    nos = {line["line_no"] for line in resp.json()}
    assert {"TL-L1", "TL-L2"} <= nos


def test_line_of_other_project_not_listed(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="OtherList", role_code="PTO_ENGINEER")
    p1 = _make_project(db, author_id=pto.id, code="LN-OL-1")
    p2 = _make_project(db, author_id=pto.id, code="LN-OL-2")
    client.post(
        f"{PROJECTS_URL}/{p1.id}/lines",
        json=_line_payload(line_no="TL-P1"),
        headers=_headers(pto),
    )

    resp = client.get(f"{PROJECTS_URL}/{p2.id}/lines", headers=_headers(pto))
    assert resp.status_code == 200
    nos = {line["line_no"] for line in resp.json()}
    assert "TL-P1" not in nos


def test_get_missing_line_404(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="MissLine", role_code="PTO_ENGINEER")
    resp = client.get(f"{PROJECTS_URL}/lines/{uuid4()}", headers=_headers(pto))
    assert resp.status_code == 404


def test_patch_draft_line(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="PatchDraft", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-PATCH-D")
    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-PD", name="Старое"),
        headers=_headers(pto),
    ).json()

    resp = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"name": "Новое", "medium": "Пар"},
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Новое"
    assert resp.json()["medium"] == "Пар"


def test_patch_active_line(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="PatchActive", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-PATCH-A")
    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-PA", status="active"),
        headers=_headers(pto),
    ).json()

    resp = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"required_inspection_types": ["UT"]},
        headers=_headers(pto),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["required_inspection_types"] == ["UT"]


def test_cancelled_line_not_editable_409(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(db, suffix="Cancelled", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=pto.id, code="LN-CANCEL")
    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-CX", status="cancelled"),
        headers=_headers(pto),
    ).json()

    resp = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"name": "Нельзя"},
        headers=_headers(pto),
    )
    assert resp.status_code == 409


# ── Права (IP-08) ─────────────────────────────────────────────────────────────


def test_global_pto_creates_line(client: TestClient, db: Session) -> None:
    pto = _make_worker_with_role(
        db, suffix="PermGlobal", role_code="PTO_ENGINEER", scope_type="GLOBAL"
    )
    project = _make_project(db, author_id=pto.id, code="LN-PERM-G")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-PG"),
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text


def test_project_scope_pto_creates_line(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="PermProjAuthor")
    project = _make_project(db, author_id=author.id, code="LN-PERM-P")
    pto = _make_worker_with_role(
        db,
        suffix="PermProj",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(project.id),
    )

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-PP"),
        headers=_headers(pto),
    )
    assert resp.status_code == 201, resp.text


def test_foreign_project_scope_pto_403(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="PermForeignAuthor")
    project = _make_project(db, author_id=author.id, code="LN-PERM-FP")
    other_project_id = uuid4()
    pto = _make_worker_with_role(
        db,
        suffix="PermForeign",
        role_code="PTO_ENGINEER",
        scope_type="PROJECT",
        scope_id=str(other_project_id),
    )

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-FP"),
        headers=_headers(pto),
    )
    assert resp.status_code == 403


def test_foreman_cannot_create_or_patch_line(client: TestClient, db: Session) -> None:
    foreman = _make_worker_with_role(
        db, suffix="Foreman", role_code="FOREMAN", scope_type="GLOBAL"
    )
    author = _make_author(db, suffix="ForemanAuthor")
    pto = _make_worker_with_role(db, suffix="ForemanPto", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=author.id, code="LN-FOREMAN")

    post = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-FM"),
        headers=_headers(foreman),
    )
    assert post.status_code == 403

    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-FM2"),
        headers=_headers(pto),
    ).json()
    patch = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"name": "Нельзя"},
        headers=_headers(foreman),
    )
    assert patch.status_code == 403


def test_master_cannot_create_or_patch_line(client: TestClient, db: Session) -> None:
    master = _make_worker_with_role(
        db, suffix="Master", role_code="MASTER", scope_type="GLOBAL"
    )
    author = _make_author(db, suffix="MasterAuthor")
    pto = _make_worker_with_role(db, suffix="MasterPto", role_code="PTO_ENGINEER")
    project = _make_project(db, author_id=author.id, code="LN-MASTER")

    post = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-MS"),
        headers=_headers(master),
    )
    assert post.status_code == 403

    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-MS2"),
        headers=_headers(pto),
    ).json()
    patch = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"name": "Нельзя"},
        headers=_headers(master),
    )
    assert patch.status_code == 403


def test_line_scope_pto_updates_line(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="LineScopeAuthor")
    project = _make_project(db, author_id=author.id, code="LN-SCOPE-U")
    creator = _make_worker_with_role(
        db, suffix="LineScopeCreator", role_code="PTO_ENGINEER"
    )
    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-LS"),
        headers=_headers(creator),
    ).json()

    line_pto = _make_worker_with_role(
        db,
        suffix="LineScope",
        role_code="PTO_ENGINEER",
        scope_type="LINE",
        scope_id=created["id"],
    )
    resp = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"name": "Обновлено LINE-scope"},
        headers=_headers(line_pto),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Обновлено LINE-scope"


def test_line_scope_cannot_create_line_403(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="LineNoCreateAuthor")
    project = _make_project(db, author_id=author.id, code="LN-SCOPE-C")
    line_pto = _make_worker_with_role(
        db,
        suffix="LineNoCreate",
        role_code="PTO_ENGINEER",
        scope_type="LINE",
        scope_id=str(uuid4()),
    )

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-LSC"),
        headers=_headers(line_pto),
    )
    assert resp.status_code == 403


def test_foreign_line_scope_cannot_update_403(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="ForeignLineAuthor")
    project = _make_project(db, author_id=author.id, code="LN-SCOPE-FL")
    creator = _make_worker_with_role(
        db, suffix="ForeignLineCreator", role_code="PTO_ENGINEER"
    )
    created = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-FL"),
        headers=_headers(creator),
    ).json()

    other_line_pto = _make_worker_with_role(
        db,
        suffix="ForeignLine",
        role_code="PTO_ENGINEER",
        scope_type="LINE",
        scope_id=str(uuid4()),
    )
    resp = client.patch(
        f"{PROJECTS_URL}/lines/{created['id']}",
        json={"name": "Нельзя"},
        headers=_headers(other_line_pto),
    )
    assert resp.status_code == 403


def test_create_line_without_user_id_401(client: TestClient, db: Session) -> None:
    author = _make_author(db, suffix="NoAuth")
    project = _make_project(db, author_id=author.id, code="LN-NOAUTH")

    resp = client.post(
        f"{PROJECTS_URL}/{project.id}/lines",
        json=_line_payload(line_no="TL-NA"),
    )
    assert resp.status_code == 401
