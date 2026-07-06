"""Интеграционные тесты API ОГС: допуски сварщика (welding.welder_admissions)."""

from datetime import date, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hr.models import Worker

from .conftest import AUTH_HEADERS, create_welder_profile, _assign_welder_role, _create_worker

API_PREFIX = "/api/v1/ogs/welder-admissions"


def _payload(**overrides) -> dict:
    data = {
        "stamp_code": "W-001",
        "welding_methods": ["111", "141"],
        "material_groups": ["09Г2С"],
        "valid_from": date.today().isoformat(),
    }
    data.update(overrides)
    return data


def test_create_admission_success(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_with_welder_profile.id),
    )
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["worker_id"] == worker_with_welder_profile.id
    assert body["stamp_code"] == "W-001"
    assert body["admission_status"] == "draft"
    assert body["welding_methods"] == ["111", "141"]
    assert body["material_groups"] == ["09Г2С"]


def test_create_admission_without_welder_role_rejected(
    client: TestClient,
    worker_without_welder_role: Worker,
    db: Session,
) -> None:
    create_welder_profile(db, worker_without_welder_role.id, "W-NOROLE")
    db.commit()

    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_without_welder_role.id, stamp_code="W-NOROLE"),
    )
    assert response.status_code == 409
    assert "WELDER" in response.json()["detail"]


def test_create_admission_without_welder_profile_rejected(
    client: TestClient,
    worker_with_welder_role: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_with_welder_role.id),
    )
    assert response.status_code == 409
    assert "профиль" in response.json()["detail"].lower()


def test_create_admission_stamp_mismatch_rejected(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_with_welder_profile.id, stamp_code="W-OTHER"),
    )
    assert response.status_code == 409
    assert "stamp_code" in response.json()["detail"]


def test_list_admissions(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    created = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_with_welder_profile.id),
    )
    assert created.status_code == 201

    response = client.get(API_PREFIX, headers=AUTH_HEADERS)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["stamp_code"] == "W-001"


def test_filter_by_stamp_code(
    client: TestClient,
    db: Session,
) -> None:
    worker_a = _create_worker(db, suffix="StampA")
    _assign_welder_role(db, worker_a.id)
    create_welder_profile(db, worker_a.id, "W-A")
    worker_b = _create_worker(db, suffix="StampB")
    _assign_welder_role(db, worker_b.id)
    create_welder_profile(db, worker_b.id, "W-B")
    db.commit()

    client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_a.id, stamp_code="W-A"),
    )
    client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_b.id, stamp_code="W-B"),
    )

    response = client.get(
        API_PREFIX, headers=AUTH_HEADERS, params={"stamp_code": "W-A"}
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["stamp_code"] == "W-A"


def test_get_admission_by_id(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    created = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_with_welder_profile.id),
    )
    admission_id = created.json()["id"]

    response = client.get(f"{API_PREFIX}/{admission_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["id"] == admission_id


def test_patch_admission_status(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    created = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(worker_id=worker_with_welder_profile.id),
    )
    admission_id = created.json()["id"]

    response = client.patch(
        f"{API_PREFIX}/{admission_id}",
        headers=AUTH_HEADERS,
        json={"admission_status": "active"},
    )
    assert response.status_code == 200
    assert response.json()["admission_status"] == "active"


def test_create_admission_invalid_status_rejected(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(
            worker_id=worker_with_welder_profile.id, admission_status="not_a_status"
        ),
    )
    assert response.status_code == 422


def test_create_admission_diameter_min_gt_max_rejected(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(
            worker_id=worker_with_welder_profile.id,
            diameter_min=100,
            diameter_max=50,
        ),
    )
    assert response.status_code == 422


def test_create_admission_valid_until_before_valid_from_rejected(
    client: TestClient,
    worker_with_welder_profile: Worker,
) -> None:
    today = date.today()
    response = client.post(
        API_PREFIX,
        headers=AUTH_HEADERS,
        json=_payload(
            worker_id=worker_with_welder_profile.id,
            valid_from=today.isoformat(),
            valid_until=(today - timedelta(days=1)).isoformat(),
        ),
    )
    assert response.status_code == 422
