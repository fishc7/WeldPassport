"""HTTP-тесты reference API Defect (Task 9D-3C-4A; Spec §10, §13).

Auth, active_only, inactive detail, 404/422/405, response schema, empty list,
порядок и отсутствие дублей. Service-level проверки — в test_defect_reference_service.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import defect_workflow as dw
from app.quality.defect_models import DefectLocationType, DefectType

from ._defect_support import DefectCtx

API = "/api/v1"
TYPES = f"{API}/quality/defect-types"
LOCATIONS = f"{API}/quality/defect-location-types"

SCHEMA_FLAGS = (
    "requires_description",
    "requires_length",
    "requires_width",
    "requires_height",
    "requires_depth",
    "requires_area",
    "requires_quantity",
    "requires_known_indication_location",
)

TYPE_CASE = pytest.param(
    {
        "list_path": TYPES,
        "detail_prefix": TYPES,
        "model": DefectType,
        "not_found": dw.DEFECT_TYPE_NOT_FOUND,
        "seed_code": "CRACK",
        "list_keys": ("id", "code", "name", "is_active", *SCHEMA_FLAGS),
    },
    id="defect-types",
)
LOCATION_CASE = pytest.param(
    {
        "list_path": LOCATIONS,
        "detail_prefix": LOCATIONS,
        "model": DefectLocationType,
        "not_found": dw.DEFECT_LOCATION_TYPE_NOT_FOUND,
        "seed_code": "WELD_METAL",
        "list_keys": ("id", "code", "name", "description", "is_active"),
    },
    id="defect-location-types",
)
CASES = [TYPE_CASE, LOCATION_CASE]


def _uid() -> str:
    return uuid4().hex[:8].upper()


def _add_row(db: Session, case: dict, *, code: str, is_active: bool):
    model = case["model"]
    obj = model(code=code, name=f"Ref {code}", is_active=is_active)
    db.add(obj)
    db.flush()
    return obj


@pytest.fixture
def catalog_row(db: Session):
    """Вставка временной строки справочника с удалением после теста (без загрязнения seed)."""
    created: list[tuple[type, object]] = []

    def _add(case: dict, *, code: str, is_active: bool):
        obj = _add_row(db, case, code=code, is_active=is_active)
        created.append((case["model"], obj.id))
        return obj

    yield _add

    for model, oid in created:
        db.query(model).filter(model.id == oid).delete(synchronize_session=False)
    db.flush()


@pytest.fixture
def any_auth(db: Session) -> dict[str, str]:
    from app.hr.models import Worker

    worker = Worker(
        last_name="RefAuth",
        first_name="Тест",
        company_id=99_999,
        employment_status="active",
        hire_date=date.today(),
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return {"X-User-Id": str(worker.id)}


# ── Auth ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_reference_list_requires_auth(client: TestClient, case: dict) -> None:
    assert client.get(case["list_path"]).status_code == 401


@pytest.mark.parametrize("case", CASES)
def test_reference_detail_requires_auth(client: TestClient, case: dict) -> None:
    assert client.get(f"{case['detail_prefix']}/{uuid4()}").status_code == 401


@pytest.mark.parametrize("case", CASES)
def test_reference_list_authenticated_returns_200(
    client: TestClient, case: dict, any_auth: dict[str, str]
) -> None:
    resp = client.get(case["list_path"], headers=any_auth)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── active_only ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_reference_list_active_only_default_hides_inactive(
    client: TestClient, case: dict, any_auth: dict[str, str], catalog_row
) -> None:
    active = catalog_row(case, code=f"ZACT_{_uid()}", is_active=True)
    inactive = catalog_row(case, code=f"ZINA_{_uid()}", is_active=False)
    resp = client.get(case["list_path"], headers=any_auth)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert str(active.id) in ids
    assert str(inactive.id) not in ids
    assert all(row["is_active"] for row in resp.json())


@pytest.mark.parametrize("case", CASES)
def test_reference_list_active_only_false_includes_inactive(
    client: TestClient, case: dict, any_auth: dict[str, str], catalog_row
) -> None:
    active = catalog_row(case, code=f"ZACT_{_uid()}", is_active=True)
    inactive = catalog_row(case, code=f"ZINA_{_uid()}", is_active=False)
    resp = client.get(
        case["list_path"], params={"active_only": "false"}, headers=any_auth
    )
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert str(active.id) in ids
    assert str(inactive.id) in ids


# ── Detail: inactive доступен; missing → 404 ───────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_reference_detail_inactive_record_returns_200(
    client: TestClient, case: dict, any_auth: dict[str, str], catalog_row
) -> None:
    inactive = catalog_row(case, code=f"ZINA_{_uid()}", is_active=False)
    resp = client.get(f"{case['detail_prefix']}/{inactive.id}", headers=any_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(inactive.id)
    assert body["is_active"] is False


@pytest.mark.parametrize("case", CASES)
def test_reference_detail_missing_returns_404(
    client: TestClient, case: dict, any_auth: dict[str, str]
) -> None:
    resp = client.get(f"{case['detail_prefix']}/{uuid4()}", headers=any_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == case["not_found"]


# ── 422 / 405 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_reference_detail_bad_uuid_returns_422(
    client: TestClient, case: dict, any_auth: dict[str, str]
) -> None:
    resp = client.get(f"{case['detail_prefix']}/not-a-uuid", headers=any_auth)
    assert resp.status_code == 422


@pytest.mark.parametrize("case", CASES)
def test_reference_mutation_methods_return_405(
    client: TestClient, case: dict, any_auth: dict[str, str]
) -> None:
    rid = str(uuid4())
    assert client.post(case["list_path"], json={}, headers=any_auth).status_code == 405
    assert (
        client.patch(f"{case['detail_prefix']}/{rid}", json={}, headers=any_auth).status_code
        == 405
    )
    assert client.delete(f"{case['detail_prefix']}/{rid}", headers=any_auth).status_code == 405


# ── Response schema, order, no duplicates ──────────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_reference_list_response_schema(
    client: TestClient, case: dict, any_auth: dict[str, str]
) -> None:
    resp = client.get(case["list_path"], headers=any_auth)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    sample = next(r for r in rows if r["code"] == case["seed_code"])
    for key in case["list_keys"]:
        assert key in sample


@pytest.mark.parametrize("case", CASES)
def test_reference_list_sorted_by_code_no_duplicates(
    client: TestClient, case: dict, any_auth: dict[str, str]
) -> None:
    resp = client.get(
        case["list_path"], params={"active_only": "false"}, headers=any_auth
    )
    assert resp.status_code == 200
    rows = resp.json()
    codes = [r["code"] for r in rows]
    assert codes == sorted(codes)
    assert len(codes) == len(set(codes))


@pytest.mark.parametrize("case", CASES)
def test_reference_list_empty_subset_still_returns_list(
    client: TestClient, case: dict, any_auth: dict[str, str], catalog_row
) -> None:
    """Временная неактивная строка не попадает в active_only=true — ответ остаётся list."""
    catalog_row(case, code=f"ZINA_{_uid()}", is_active=False)
    resp = client.get(case["list_path"], headers=any_auth)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_reference_read_does_not_expose_hidden_defect(
    client: TestClient, db: Session
) -> None:
    """Изоляция: справочник доступен без Joint-scope; скрытый Defect не раскрывается."""
    ctx = DefectCtx(db, "REFISO")
    joint = ctx.new_joint("J-iso")
    ev = ctx.new_confirmed_evaluation(joint)
    from ._defect_support import create_defect_http, valid_active_fields

    hidden = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=valid_active_fields(db),
    ).json()
    resp = client.get(TYPES, headers=ctx.h(ctx.norole))
    assert resp.status_code == 200
    payload = resp.text
    assert hidden["id"] not in payload
    assert hidden["defect_root_id"] not in payload
