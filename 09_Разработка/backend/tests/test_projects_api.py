"""Интеграционные тесты модуля projects (Task 2): companies, projects, project_companies.

Изменяющие endpoints требуют валидный X-User-Id активного hr.workers (временное
правило MVP, IP-03). Реального RBAC на этом этапе нет. Связь компаний и проектов —
многие-ко-многим через project_companies (ADR-001), без правила «1 company = 1 project».
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient

from app.hr.models import Worker

COMPANIES_URL = "/api/v1/projects/companies"
PROJECTS_URL = "/api/v1/projects"

ROLE_CODES = [
    "CUSTOMER",
    "GENERAL_CONTRACTOR",
    "WELDING_CONTRACTOR",
    "NDT_LAB",
    "INSPECTION",
    "DESIGNER",
]


def _headers(worker: Worker) -> dict[str, str]:
    return {"X-User-Id": str(worker.id)}


def _create_company(
    client: TestClient,
    worker: Worker,
    *,
    name: str = "ООО Монтаж",
    inn: str | None = None,
    status: str = "active",
) -> dict:
    payload: dict = {"name": name, "status": status}
    if inn is not None:
        payload["inn"] = inn
    resp = client.post(COMPANIES_URL, json=payload, headers=_headers(worker))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_project(
    client: TestClient,
    worker: Worker,
    *,
    code: str,
    name: str = "Проект ТП-1",
    status: str = "draft",
) -> dict:
    payload = {"code": code, "name": name, "status": status}
    resp = client.post(PROJECTS_URL, json=payload, headers=_headers(worker))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Company ───────────────────────────────────────────────────────────────────


def test_create_company_and_project(client: TestClient, active_worker: Worker) -> None:
    company = _create_company(client, active_worker, name="ООО Заказчик")
    assert company["id"] > 0
    assert company["status"] == "active"
    assert company["created_by"] == active_worker.id

    project = _create_project(client, active_worker, code="PRJ-CP-1")
    UUID(project["id"])  # id — валидный UUID
    assert project["code"] == "PRJ-CP-1"


def test_create_company_without_user_id_401(client: TestClient) -> None:
    resp = client.post(COMPANIES_URL, json={"name": "ООО Без-заголовка"})
    assert resp.status_code == 401


def test_create_company_unknown_worker_404(client: TestClient) -> None:
    resp = client.post(
        COMPANIES_URL,
        json={"name": "ООО Неизвестный"},
        headers={"X-User-Id": "999999999"},
    )
    assert resp.status_code == 404


def test_dismissed_worker_cannot_create_company_403(
    client: TestClient, inactive_worker: Worker
) -> None:
    resp = client.post(
        COMPANIES_URL,
        json={"name": "ООО Уволенный"},
        headers=_headers(inactive_worker),
    )
    assert resp.status_code == 403


def test_create_company_null_inn_allowed(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Без-ИНН", inn=None)
    assert company["inn"] is None


def test_two_null_inn_allowed(client: TestClient, active_worker: Worker) -> None:
    first = _create_company(client, active_worker, name="ООО Первая", inn=None)
    second = _create_company(client, active_worker, name="ООО Вторая", inn=None)
    assert first["id"] != second["id"]


def test_duplicate_nonempty_inn_conflict(
    client: TestClient, active_worker: Worker
) -> None:
    _create_company(client, active_worker, name="ООО ИНН-1", inn="7701234567")
    resp = client.post(
        COMPANIES_URL,
        json={"name": "ООО ИНН-дубль", "inn": "7701234567"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 409


def test_company_status_out_of_enum_422(
    client: TestClient, active_worker: Worker
) -> None:
    resp = client.post(
        COMPANIES_URL,
        json={"name": "ООО Статус", "status": "archived"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 422


def test_list_companies(client: TestClient, active_worker: Worker) -> None:
    _create_company(client, active_worker, name="ООО В-списке", inn="7712223334")
    resp = client.get(COMPANIES_URL, headers=_headers(active_worker))
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "ООО В-списке" in names


# ── Project ───────────────────────────────────────────────────────────────────


def test_create_project_id_is_uuid(
    client: TestClient, active_worker: Worker
) -> None:
    project = _create_project(client, active_worker, code="PRJ-UUID-1")
    parsed = UUID(project["id"])
    assert str(parsed) == project["id"]


def test_duplicate_project_code_conflict(
    client: TestClient, active_worker: Worker
) -> None:
    _create_project(client, active_worker, code="PRJ-DUP")
    resp = client.post(
        PROJECTS_URL,
        json={"code": "PRJ-DUP", "name": "Дубль кода"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 409


def test_project_status_out_of_enum_422(
    client: TestClient, active_worker: Worker
) -> None:
    resp = client.post(
        PROJECTS_URL,
        json={"code": "PRJ-BAD-STATUS", "name": "Плохой статус", "status": "frozen"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 422


def test_get_single_project(client: TestClient, active_worker: Worker) -> None:
    project = _create_project(client, active_worker, code="PRJ-GET-1")
    resp = client.get(
        f"{PROJECTS_URL}/{project['id']}", headers=_headers(active_worker)
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == "PRJ-GET-1"


def test_get_missing_project_404(client: TestClient, active_worker: Worker) -> None:
    missing = "550e8400-e29b-41d4-a716-446655440000"
    resp = client.get(f"{PROJECTS_URL}/{missing}", headers=_headers(active_worker))
    assert resp.status_code == 404


# ── project_companies ─────────────────────────────────────────────────────────


def test_company_participates_in_two_projects(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Много-проектов")
    p1 = _create_project(client, active_worker, code="PRJ-M2P-1")
    p2 = _create_project(client, active_worker, code="PRJ-M2P-2")

    for project in (p1, p2):
        resp = client.post(
            f"{PROJECTS_URL}/{project['id']}/companies",
            json={"company_id": company["id"], "role_code": "WELDING_CONTRACTOR"},
            headers=_headers(active_worker),
        )
        assert resp.status_code == 201, resp.text


def test_project_holds_multiple_companies(
    client: TestClient, active_worker: Worker
) -> None:
    customer = _create_company(client, active_worker, name="ООО Заказчик-2")
    contractor = _create_company(client, active_worker, name="ООО Подрядчик-2")
    project = _create_project(client, active_worker, code="PRJ-MULTI-CO")

    r1 = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": customer["id"], "role_code": "CUSTOMER"},
        headers=_headers(active_worker),
    )
    r2 = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": contractor["id"], "role_code": "GENERAL_CONTRACTOR"},
        headers=_headers(active_worker),
    )
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text

    listed = client.get(
        f"{PROJECTS_URL}/{project['id']}/companies", headers=_headers(active_worker)
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 2


def test_all_allowed_role_codes(client: TestClient, active_worker: Worker) -> None:
    project = _create_project(client, active_worker, code="PRJ-ROLES")
    for role in ROLE_CODES:
        company = _create_company(
            client, active_worker, name=f"ООО {role}"
        )
        resp = client.post(
            f"{PROJECTS_URL}/{project['id']}/companies",
            json={"company_id": company["id"], "role_code": role},
            headers=_headers(active_worker),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["role_code"] == role


def test_unknown_role_code_422(client: TestClient, active_worker: Worker) -> None:
    company = _create_company(client, active_worker, name="ООО Плохая-роль")
    project = _create_project(client, active_worker, code="PRJ-BADROLE")
    resp = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": company["id"], "role_code": "SUBCONTRACTOR"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 422


def test_active_link_defined_by_valid_to_null(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Действующая")
    project = _create_project(client, active_worker, code="PRJ-ACTIVE-LINK")
    resp = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": company["id"], "role_code": "INSPECTION"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 201
    assert resp.json()["valid_to"] is None


def test_duplicate_active_participation_conflict(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Дубль-связь")
    project = _create_project(client, active_worker, code="PRJ-DUP-LINK")
    body = {"company_id": company["id"], "role_code": "NDT_LAB"}
    first = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json=body,
        headers=_headers(active_worker),
    )
    assert first.status_code == 201
    second = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json=body,
        headers=_headers(active_worker),
    )
    assert second.status_code == 409


def test_closed_participation_does_not_block_new_active(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО История")
    project = _create_project(client, active_worker, code="PRJ-HIST")
    closed = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={
            "company_id": company["id"],
            "role_code": "DESIGNER",
            "valid_from": "2020-01-01",
            "valid_to": "2020-12-31",
        },
        headers=_headers(active_worker),
    )
    assert closed.status_code == 201, closed.text

    active = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": company["id"], "role_code": "DESIGNER"},
        headers=_headers(active_worker),
    )
    assert active.status_code == 201, active.text
    assert active.json()["valid_to"] is None


def test_valid_to_before_valid_from_422(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Даты")
    project = _create_project(client, active_worker, code="PRJ-DATES")
    resp = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={
            "company_id": company["id"],
            "role_code": "CUSTOMER",
            "valid_from": "2026-05-01",
            "valid_to": "2026-04-01",
        },
        headers=_headers(active_worker),
    )
    assert resp.status_code == 422


def test_add_company_to_missing_project_404(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Нет-проекта")
    missing = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    resp = client.post(
        f"{PROJECTS_URL}/{missing}/companies",
        json={"company_id": company["id"], "role_code": "CUSTOMER"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 404


def test_add_missing_company_to_project_404(
    client: TestClient, active_worker: Worker
) -> None:
    project = _create_project(client, active_worker, code="PRJ-NO-COMPANY")
    resp = client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": 999999999, "role_code": "CUSTOMER"},
        headers=_headers(active_worker),
    )
    assert resp.status_code == 404


def test_filter_projects_by_company_and_role(
    client: TestClient, active_worker: Worker
) -> None:
    company = _create_company(client, active_worker, name="ООО Фильтр")
    project = _create_project(client, active_worker, code="PRJ-FILTER")
    client.post(
        f"{PROJECTS_URL}/{project['id']}/companies",
        json={"company_id": company["id"], "role_code": "WELDING_CONTRACTOR"},
        headers=_headers(active_worker),
    )

    matched = client.get(
        PROJECTS_URL,
        params={"company_id": company["id"], "role_code": "WELDING_CONTRACTOR"},
        headers=_headers(active_worker),
    )
    assert matched.status_code == 200
    codes = [p["code"] for p in matched.json()]
    assert "PRJ-FILTER" in codes

    other = client.get(
        PROJECTS_URL,
        params={"company_id": company["id"], "role_code": "CUSTOMER"},
        headers=_headers(active_worker),
    )
    assert other.status_code == 200
    other_codes = [p["code"] for p in other.json()]
    assert "PRJ-FILTER" not in other_codes
