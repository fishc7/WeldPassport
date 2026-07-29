"""Focused smoke/integration тесты Defect API router и wiring (Task 9D-3C-3).

Проверяют регистрацию маршрутов, request-валидацию, границу аутентификации, корректную
маршрутизацию к `DefectService` (извлечение полей, сохранение явного null) и проброс
`DomainError` без ручного remapping. Полная RBAC/scope-матрица и hardening — Task 9D-3C-4.

Маршрутизация к сервису проверяется подменой методов `DefectService` (class-level spy),
чтобы не зависеть от доменной валидации и RBAC; happy-path справочников — реальная
интеграция (seed из миграции). Актор передаётся заголовком `X-User-Id`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.quality.defect_models import DefectType
from app.quality.defect_services import DefectService
from app.shared.errors import DomainError

from ._defect_support import (
    DEFECTS_API,
    DefectCtx,
    create_defect_http,
    make_defect,
    make_root,
    valid_active_fields,
)

API = "/api/v1"
DEFECTS = f"{API}/quality/defects"
TYPES = f"{API}/quality/defect-types"
LOCATIONS = f"{API}/quality/defect-location-types"
AUTH = {"X-User-Id": "7"}


# Полный контракт из 12 операций (Spec 9D-3C §7).
DEFECT_OPS = {
    ("post", "/api/v1/quality/defects"),
    ("get", "/api/v1/quality/defects"),
    ("get", "/api/v1/quality/defects/{defect_id}"),
    ("patch", "/api/v1/quality/defects/{defect_id}"),
    ("post", "/api/v1/quality/defects/{defect_id}/activate"),
    ("post", "/api/v1/quality/defects/{defect_id}/supersede"),
    ("post", "/api/v1/quality/defects/{defect_id}/cancel"),
    ("get", "/api/v1/quality/defects/{defect_id}/history"),
    ("get", "/api/v1/quality/defect-types"),
    ("get", "/api/v1/quality/defect-types/{defect_type_id}"),
    ("get", "/api/v1/quality/defect-location-types"),
    ("get", "/api/v1/quality/defect-location-types/{defect_location_type_id}"),
}


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _spy(monkeypatch, method_name, *, returns=None, raises=None) -> dict:
    """Подменяет метод DefectService, записывая args/kwargs вызова."""
    captured: dict = {}

    def fake(self, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setattr(DefectService, method_name, fake)
    return captured


@pytest.fixture
def sample_defect(db: Session):
    """Полноценная ORM-ревизия Defect (DRAFT) как возвращаемое значение подменённого сервиса."""
    ctx = DefectCtx(db, "APIRT")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    return make_defect(ctx, root=root, revision_no=1, status="DRAFT")


# ── 1–3. Router registration ─────────────────────────────────────────────────────


def test_openapi_contains_all_endpoints(client):
    spec = client.get("/openapi.json").json()
    present = {
        (method, path)
        for path, ops in spec["paths"].items()
        for method in ops
        if path.startswith("/api/v1/quality/defect")
    }
    assert DEFECT_OPS.issubset(present)
    assert len(DEFECT_OPS) == 12


def test_prefix_applied_exactly_once(client):
    spec = client.get("/openapi.json").json()
    for path in spec["paths"]:
        assert "/api/v1/api/v1" not in path
    # каждый defect-путь присутствует ровно под одним /api/v1-префиксом
    for _method, path in DEFECT_OPS:
        assert path in spec["paths"]


def test_no_defect_endpoint_without_prefix(client):
    spec = client.get("/openapi.json").json()
    for path in spec["paths"]:
        if "quality/defect" in path:
            assert path.startswith("/api/v1/")


# ── 4–7. Request validation ──────────────────────────────────────────────────────


def test_list_requires_joint_id(client):
    assert client.get(DEFECTS, headers=AUTH).status_code == 422


def test_bad_uuid_path_returns_422(client):
    assert client.get(f"{DEFECTS}/not-a-uuid", headers=AUTH).status_code == 422


def test_create_extra_field_returns_422(client):
    body = {
        "joint_id": str(uuid4()),
        "engineering_evaluation_id": str(uuid4()),
        "status": "ACTIVE",  # служебное поле запрещено (extra=forbid)
    }
    assert client.post(DEFECTS, json=body, headers=AUTH).status_code == 422


def test_cancel_empty_reason_returns_422(client):
    body = {"expected_version": 1, "reason": "   "}
    assert client.post(f"{DEFECTS}/{uuid4()}/cancel", json=body, headers=AUTH).status_code == 422


# ── 8–10. Authentication boundary ────────────────────────────────────────────────


def test_defect_endpoint_requires_header(client):
    assert client.get(DEFECTS, params={"joint_id": str(uuid4())}).status_code == 401


def test_reference_endpoint_requires_header(client):
    assert client.get(TYPES).status_code == 401
    assert client.get(LOCATIONS).status_code == 401


def test_valid_header_reaches_dependency(client, monkeypatch):
    _spy(monkeypatch, "list_defect_types", returns=[])
    assert client.get(TYPES, headers=AUTH).status_code == 200


# ── 11–21. Service routing & field extraction ────────────────────────────────────


def test_create_draft_routing_and_field_extraction(client, sample_defect, monkeypatch):
    cap = _spy(monkeypatch, "create_draft", returns=sample_defect)
    cap_active = _spy(monkeypatch, "create_active", returns=sample_defect)
    body = {
        "joint_id": str(uuid4()),
        "engineering_evaluation_id": str(uuid4()),
        "length_mm": "3.5",  # передано
        "width_mm": None,  # явный null
    }
    resp = client.post(DEFECTS, json=body, headers=AUTH)
    assert resp.status_code == 201
    assert not cap_active  # create_active не вызывался
    kw = cap["kwargs"]
    assert kw["joint_id"] == UUID(body["joint_id"])
    assert kw["engineering_evaluation_id"] == UUID(body["engineering_evaluation_id"])
    assert kw["actor_worker_id"] == 7
    fields = kw["fields"]
    # context/control keys не попадают в fields
    assert "joint_id" not in fields
    assert "engineering_evaluation_id" not in fields
    assert "activate" not in fields
    # explicit null сохранён, непереданное отсутствует
    assert "length_mm" in fields
    assert fields["width_mm"] is None
    assert "depth_mm" not in fields


def test_create_active_routing(client, sample_defect, monkeypatch):
    cap_active = _spy(monkeypatch, "create_active", returns=sample_defect)
    cap_draft = _spy(monkeypatch, "create_draft", returns=sample_defect)
    body = {
        "joint_id": str(uuid4()),
        "engineering_evaluation_id": str(uuid4()),
        "activate": True,
    }
    resp = client.post(DEFECTS, json=body, headers=AUTH)
    assert resp.status_code == 201
    assert cap_active  # create_active вызван
    assert not cap_draft  # create_draft не вызван
    assert "activate" not in cap_active["kwargs"]["fields"]


def test_update_excludes_version_and_reason(client, sample_defect, monkeypatch):
    cap = _spy(monkeypatch, "update_draft", returns=sample_defect)
    did = uuid4()
    body = {
        "expected_version": 2,
        "reason": "правка",
        "orientation": "LONGITUDINAL",
        "surface": None,
    }
    resp = client.patch(f"{DEFECTS}/{did}", json=body, headers=AUTH)
    assert resp.status_code == 200
    assert cap["args"][0] == did
    kw = cap["kwargs"]
    assert kw["expected_version"] == 2
    assert kw["reason"] == "правка"
    assert kw["actor_worker_id"] == 7
    fields = kw["fields"]
    assert "expected_version" not in fields
    assert "reason" not in fields
    assert fields["surface"] is None  # explicit null сохранён
    assert "orientation" in fields


def test_activate_passes_only_expected_args(client, sample_defect, monkeypatch):
    cap = _spy(monkeypatch, "activate", returns=sample_defect)
    did = uuid4()
    resp = client.post(f"{DEFECTS}/{did}/activate", json={"expected_version": 1}, headers=AUTH)
    assert resp.status_code == 200
    assert cap["args"][0] == did
    assert cap["kwargs"] == {"expected_version": 1, "actor_worker_id": 7}


def test_supersede_excludes_and_returns_draft_without_second_call(
    client, sample_defect, monkeypatch
):
    cap = _spy(monkeypatch, "supersede", returns=sample_defect)
    cap_activate = _spy(monkeypatch, "activate", returns=sample_defect)
    did = uuid4()
    body = {"expected_version": 3, "reason": "исправление", "depth_mm": "1.2"}
    resp = client.post(f"{DEFECTS}/{did}/supersede", json=body, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DRAFT"  # новая ревизия — DRAFT
    assert not cap_activate  # авто-активации нет
    fields = cap["kwargs"]["fields"]
    assert "expected_version" not in fields
    assert "reason" not in fields
    assert "depth_mm" in fields


def test_cancel_passes_reason(client, sample_defect, monkeypatch):
    cap = _spy(monkeypatch, "cancel", returns=sample_defect)
    did = uuid4()
    resp = client.post(
        f"{DEFECTS}/{did}/cancel",
        json={"expected_version": 1, "reason": "дубль"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    kw = cap["kwargs"]
    assert kw["reason"] == "дубль"
    assert kw["expected_version"] == 1
    assert kw["actor_worker_id"] == 7


def test_get_calls_service(client, sample_defect, monkeypatch):
    cap = _spy(monkeypatch, "get", returns=sample_defect)
    did = uuid4()
    resp = client.get(f"{DEFECTS}/{did}", headers=AUTH)
    assert resp.status_code == 200
    assert cap["args"][0] == did
    assert cap["kwargs"] == {"actor_worker_id": 7}


def test_list_calls_list_by_joint(client, sample_defect, monkeypatch):
    cap = _spy(monkeypatch, "list_by_joint", returns=[sample_defect])
    jid = uuid4()
    resp = client.get(DEFECTS, params={"joint_id": str(jid)}, headers=AUTH)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list) and len(resp.json()) == 1
    assert cap["args"][0] == jid
    assert cap["kwargs"] == {"actor_worker_id": 7}


def test_history_calls_service(client, monkeypatch):
    cap = _spy(monkeypatch, "history", returns=[])
    did = uuid4()
    resp = client.get(f"{DEFECTS}/{did}/history", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == []
    assert cap["args"][0] == did


# ── 22–23, 26. Reference endpoints ───────────────────────────────────────────────


def test_reference_types_list_real_integration(client):
    resp = client.get(TYPES, headers=AUTH)
    assert resp.status_code == 200
    rows = resp.json()
    codes = {r["code"] for r in rows}
    assert "CRACK" in codes
    sample = rows[0]
    for flag in (
        "requires_description",
        "requires_length",
        "requires_width",
        "requires_height",
        "requires_depth",
        "requires_area",
        "requires_quantity",
        "requires_known_indication_location",
    ):
        assert flag in sample


def test_reference_locations_list_real_integration(client):
    resp = client.get(LOCATIONS, headers=AUTH)
    assert resp.status_code == 200
    assert "WELD_METAL" in {r["code"] for r in resp.json()}


def test_reference_type_detail_real_integration(client, db):
    tid = db.execute(select(DefectType.id).where(DefectType.code == "CRACK")).scalar_one()
    resp = client.get(f"{TYPES}/{tid}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["code"] == "CRACK"


def test_reference_methods_receive_no_actor(client, monkeypatch):
    cap = _spy(monkeypatch, "list_defect_types", returns=[])
    resp = client.get(TYPES, headers=AUTH)
    assert resp.status_code == 200
    assert "actor_worker_id" not in cap["kwargs"]
    assert cap["kwargs"] == {"active_only": True}


def test_reference_active_only_false_passed(client, monkeypatch):
    cap = _spy(monkeypatch, "list_defect_location_types", returns=[])
    resp = client.get(LOCATIONS, params={"active_only": "false"}, headers=AUTH)
    assert resp.status_code == 200
    assert cap["kwargs"] == {"active_only": False}


def test_reference_has_no_mutation_methods(client):
    """Reference — read-only: mutation-методов на путях нет (405)."""
    tid = str(uuid4())
    assert client.post(TYPES, json={}, headers=AUTH).status_code == 405
    assert client.patch(f"{TYPES}/{tid}", json={}, headers=AUTH).status_code == 405
    assert client.delete(f"{TYPES}/{tid}", headers=AUTH).status_code == 405


# ── 28. DomainError passthrough ──────────────────────────────────────────────────


def test_domain_error_passes_through_without_remapping(client, monkeypatch):
    _spy(
        monkeypatch,
        "get",
        raises=DomainError(409, "DEFECT_VERSION_CONFLICT", "конфликт версии"),
    )
    resp = client.get(f"{DEFECTS}/{uuid4()}", headers=AUTH)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DEFECT_VERSION_CONFLICT"


def test_domain_error_404_passes_through(client, monkeypatch):
    _spy(monkeypatch, "get", raises=DomainError(404, "DEFECT_NOT_FOUND", "не найден"))
    resp = client.get(f"{DEFECTS}/{uuid4()}", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEFECT_NOT_FOUND"


# ── Real-DB HTTP integration (Task 9D-3C-4A) ───────────────────────────────────


@pytest.fixture
def api_ctx(db):
    return DefectCtx(db, "API4A")


@pytest.fixture
def api_joint(db, api_ctx):
    joint = api_ctx.new_joint("J-4A")
    ev = api_ctx.new_confirmed_evaluation(joint)
    return api_ctx, joint, ev


def _active_fields(db):
    return valid_active_fields(db)


def test_http_create_draft_returns_201_and_draft_status(client, api_joint):
    ctx, joint, ev = api_joint
    resp = create_defect_http(
        client, ctx.ogs, joint_id=joint.id, engineering_evaluation_id=ev.id
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    assert body["revision_no"] == 1


def test_http_create_active_returns_201_and_active_status(client, api_joint, db):
    ctx, joint, ev = api_joint
    resp = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=_active_fields(db),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "ACTIVE"


def test_http_lifecycle_draft_activate_supersede_activate_cancel(client, api_joint, db):
    ctx, joint, ev = api_joint
    fields = _active_fields(db)
    draft = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        extra_fields=fields,
    ).json()
    assert draft["status"] == "DRAFT"

    active = client.post(
        f"{DEFECTS_API}/{draft['id']}/activate",
        json={"expected_version": draft["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert active.status_code == 200
    active_body = active.json()
    assert active_body["status"] == "ACTIVE"

    superseded = client.post(
        f"{DEFECTS_API}/{active_body['id']}/supersede",
        json={"expected_version": active_body["version"], "reason": "уточнение"},
        headers=ctx.h(ctx.chief),
    )
    assert superseded.status_code == 200
    new_draft = superseded.json()
    assert new_draft["status"] == "DRAFT"
    assert new_draft["revision_no"] == active_body["revision_no"] + 1

    reactivated = client.post(
        f"{DEFECTS_API}/{new_draft['id']}/activate",
        json={"expected_version": new_draft["version"]},
        headers=ctx.h(ctx.ogs),
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "ACTIVE"

    cancelled = client.post(
        f"{DEFECTS_API}/{reactivated.json()['id']}/cancel",
        json={"expected_version": reactivated.json()["version"], "reason": "ошибка"},
        headers=ctx.h(ctx.ogs),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_http_history_returns_chain_events_in_order(client, api_joint, db):
    ctx, joint, ev = api_joint
    fields = _active_fields(db)
    draft = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        extra_fields=fields,
    ).json()
    active = client.post(
        f"{DEFECTS_API}/{draft['id']}/activate",
        json={"expected_version": draft["version"]},
        headers=ctx.h(ctx.ogs),
    ).json()

    resp = client.get(
        f"{DEFECTS_API}/{active['id']}/history", headers=ctx.h(ctx.otk)
    )
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 2
    types = [e["event_type"] for e in events]
    assert "DEFECT_ACTIVATED" in types
    assert events == sorted(events, key=lambda e: e["created_at"])
    sample = events[0]
    assert "metadata" in sample
    assert "event_metadata" not in sample


def test_http_list_returns_only_active_revisions(client, api_joint, db):
    ctx, joint, ev = api_joint
    fields = _active_fields(db)
    draft = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        extra_fields=fields,
    ).json()

    empty = client.get(
        DEFECTS_API, params={"joint_id": str(joint.id)}, headers=ctx.h(ctx.otk)
    )
    assert empty.status_code == 200
    assert empty.json() == []

    active = client.post(
        f"{DEFECTS_API}/{draft['id']}/activate",
        json={"expected_version": draft["version"]},
        headers=ctx.h(ctx.ogs),
    ).json()
    listed = client.get(
        DEFECTS_API, params={"joint_id": str(joint.id)}, headers=ctx.h(ctx.otk)
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == active["id"]
    assert rows[0]["status"] == "ACTIVE"

    superseded = client.post(
        f"{DEFECTS_API}/{active['id']}/supersede",
        json={"expected_version": active["version"]},
        headers=ctx.h(ctx.ogs),
    ).json()
    assert superseded["status"] == "DRAFT"
    after_supersede = client.get(
        DEFECTS_API, params={"joint_id": str(joint.id)}, headers=ctx.h(ctx.otk)
    )
    assert after_supersede.json() == []


def test_http_list_empty_for_joint_without_active_defects(client, api_ctx):
    ctx = api_ctx
    joint = ctx.new_joint("J-empty")
    resp = client.get(
        DEFECTS_API, params={"joint_id": str(joint.id)}, headers=ctx.h(ctx.ogs)
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_http_get_response_contract(client, api_joint, db):
    ctx, joint, ev = api_joint
    created = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=_active_fields(db),
    ).json()
    resp = client.get(f"{DEFECTS_API}/{created['id']}", headers=ctx.h(ctx.otk))
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "id",
        "defect_root_id",
        "revision_no",
        "status",
        "defect_type_id",
        "location_type_id",
        "version",
        "created_by_worker_id",
        "created_at",
        "updated_at",
        "standard_reference_display",
    ):
        assert key in body
    assert isinstance(body["id"], str)
    assert body["status"] == "ACTIVE"
    assert body["version"] >= 1


def test_http_update_draft_increments_version(client, api_joint):
    ctx, joint, ev = api_joint
    draft = create_defect_http(
        client, ctx.ogs, joint_id=joint.id, engineering_evaluation_id=ev.id
    ).json()
    resp = client.patch(
        f"{DEFECTS_API}/{draft['id']}",
        json={
            "expected_version": draft["version"],
            "technical_description": "поверхностная трещина",
        },
        headers=ctx.h(ctx.ogs),
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == draft["version"] + 1
    assert resp.json()["technical_description"] == "поверхностная трещина"


def test_http_stale_expected_version_returns_409(client, api_joint):
    ctx, joint, ev = api_joint
    draft = create_defect_http(
        client, ctx.ogs, joint_id=joint.id, engineering_evaluation_id=ev.id
    ).json()
    resp = client.patch(
        f"{DEFECTS_API}/{draft['id']}",
        json={"expected_version": draft["version"] + 99, "technical_note": "x"},
        headers=ctx.h(ctx.ogs),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DEFECT_VERSION_CONFLICT"


def test_http_patch_active_returns_409_immutable(client, api_joint, db):
    ctx, joint, ev = api_joint
    active = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=_active_fields(db),
    ).json()
    resp = client.patch(
        f"{DEFECTS_API}/{active['id']}",
        json={"expected_version": active["version"], "technical_note": "x"},
        headers=ctx.h(ctx.ogs),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DEFECT_ACTIVE_IMMUTABLE"
