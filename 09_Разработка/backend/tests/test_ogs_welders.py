"""Интеграционные тесты API ОГС: оформление сварщика (welding.welders)."""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hr.models import Worker

from .conftest import API_PREFIX, AUTH_HEADERS, TEST_COMPANY_ID


def test_create_welder_success(
    client: TestClient,
    worker_with_welder_role: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={
            "worker_id": worker_with_welder_role.id,
            "stamp_code": "W-001",
            "notes": "оформлен ОГС",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["worker_id"] == worker_with_welder_role.id
    assert body["stamp_code"] == "W-001"
    assert body["status"] == "active"
    assert body["notes"] == "оформлен ОГС"


def test_create_welder_unknown_worker(client: TestClient) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": 999_999, "stamp_code": "W-404"},
    )
    assert response.status_code == 404
    assert "Работник" in response.json()["detail"]


def test_create_welder_without_welder_role(
    client: TestClient,
    worker_without_welder_role: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={
            "worker_id": worker_without_welder_role.id,
            "stamp_code": "W-NOROLE",
        },
    )
    assert response.status_code == 409
    assert "WELDER" in response.json()["detail"]


def test_create_second_welder_same_worker(
    client: TestClient,
    worker_with_welder_role: Worker,
) -> None:
    first = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": worker_with_welder_role.id, "stamp_code": "W-A"},
    )
    assert first.status_code == 201

    second = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": worker_with_welder_role.id, "stamp_code": "W-B"},
    )
    assert second.status_code == 409
    assert "worker_id" in second.json()["detail"]


def test_create_welder_duplicate_stamp_code(
    client: TestClient,
    db: Session,
    worker_with_welder_role: Worker,
) -> None:
    other = Worker(
        last_name="Другой",
        first_name="Пётр",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
    )
    db.add(other)
    db.flush()
    from app.hr.models import WorkerRole
    from datetime import date

    db.add(
        WorkerRole(
            worker_id=other.id,
            role_code="WELDER",
            scope_type="GLOBAL",
            is_active=True,
            valid_from=date.today(),
        )
    )
    db.commit()

    first = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": worker_with_welder_role.id, "stamp_code": "STAMP-X"},
    )
    assert first.status_code == 201

    second = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": other.id, "stamp_code": "STAMP-X"},
    )
    assert second.status_code == 409
    assert "stamp_code" in second.json()["detail"]


def test_list_welders(
    client: TestClient,
    worker_with_welder_role: Worker,
) -> None:
    created = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": worker_with_welder_role.id, "stamp_code": "W-LIST"},
    )
    assert created.status_code == 201

    response = client.get(API_PREFIX, headers=AUTH_HEADERS)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["stamp_code"] == "W-LIST"


def test_get_welder_by_id(
    client: TestClient,
    worker_with_welder_role: Worker,
) -> None:
    created = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": worker_with_welder_role.id, "stamp_code": "W-GET"},
    )
    welder_id = created.json()["id"]

    response = client.get(f"{API_PREFIX}/{welder_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["id"] == welder_id


def test_patch_welder_status_notes_stamp_code(
    client: TestClient,
    worker_with_welder_role: Worker,
) -> None:
    created = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json={"worker_id": worker_with_welder_role.id, "stamp_code": "W-PATCH"},
    )
    welder_id = created.json()["id"]

    response = client.patch(
        f"{API_PREFIX}/{welder_id}",
        headers=AUTH_HEADERS,
        json={
            "status": "suspended",
            "notes": "временно отстранён",
            "stamp_code": "W-PATCH-NEW",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "suspended"
    assert body["notes"] == "временно отстранён"
    assert body["stamp_code"] == "W-PATCH-NEW"
