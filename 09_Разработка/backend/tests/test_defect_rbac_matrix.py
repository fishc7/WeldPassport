"""RBAC/scope-матрица Defect API (Task 9D-3C-4A; решение A1).

7 ролей × ключевые операции; scope: PROJECT, LINE, ENGINEERING_DOCUMENT, COMPANY, SITE.
Явно фиксирует allowed, 403 (DEFECT_PERMISSION_DENIED) и hidden-resource 404.
Create без применимой роли на существующем Joint → 403 (не 404).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality import defect_workflow as dw

from ._defect_support import DEFECTS_API, DefectCtx, create_defect_http, valid_active_fields

READ_ROLES = (
    "PTO_ENGINEER",
    "OTK_INSPECTOR",
    "FOREMAN",
    "MASTER",
    "NDT_SPECIALIST",
)
# OGS допускает scoped-роли; CHIEF_WELDER — только GLOBAL (CHECK hr.worker_roles).
SCOPED_WRITE_ROLE = "OGS_ENGINEER"
MATCHING_SCOPES = ("PROJECT", "LINE", "ENGINEERING_DOCUMENT")
READ_OPS = ("get", "list", "history")
WRITE_OPS = ("patch", "activate", "supersede", "cancel")


def _rbac_ctx(db: Session) -> DefectCtx:
    return DefectCtx(db, f"RB{uuid4().hex[:6]}")


def _seed_active(client: TestClient, ctx: DefectCtx, db: Session):
    joint = ctx.new_joint("J-rbac")
    ev = ctx.new_confirmed_evaluation(joint)
    resp = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=valid_active_fields(db),
    )
    assert resp.status_code == 201, resp.text
    return joint, ev, resp.json()


def _worker_in_scope(ctx: DefectCtx, suffix: str, role_code: str, scope_type: str):
    scope_id = ctx.scope_id_for(scope_type)
    return ctx.scoped_role_worker(suffix, role_code, scope_type, scope_id)


def _draft_only(client: TestClient, ctx: DefectCtx, joint, ev, db: Session):
    resp = create_defect_http(
        client,
        ctx.ogs,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        extra_fields=valid_active_fields(db),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Явные тесты A1: create → 403, hidden → 404 ─────────────────────────────────


def test_create_draft_without_applicable_role_on_joint_returns_403(
    client: TestClient, db: Session
) -> None:
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-403d")
    ev = ctx.new_confirmed_evaluation(joint)
    resp = create_defect_http(
        client, ctx.norole, joint_id=joint.id, engineering_evaluation_id=ev.id
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


def test_create_active_without_applicable_role_on_joint_returns_403(
    client: TestClient, db: Session
) -> None:
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-403a")
    ev = ctx.new_confirmed_evaluation(joint)
    resp = create_defect_http(
        client,
        ctx.norole,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=valid_active_fields(db),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


def test_get_hidden_defect_returns_404_not_403(client: TestClient, db: Session) -> None:
    ctx = _rbac_ctx(db)
    _, _, defect = _seed_active(client, ctx, db)
    resp = client.get(f"{DEFECTS_API}/{defect['id']}", headers=ctx.h(ctx.norole))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == dw.DEFECT_NOT_FOUND


def test_list_hidden_joint_returns_404_not_empty_list(
    client: TestClient, db: Session
) -> None:
    ctx = _rbac_ctx(db)
    joint, _, _ = _seed_active(client, ctx, db)
    resp = client.get(
        DEFECTS_API, params={"joint_id": str(joint.id)}, headers=ctx.h(ctx.norole)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == dw.DEFECT_NOT_FOUND


def test_history_hidden_defect_returns_404(client: TestClient, db: Session) -> None:
    ctx = _rbac_ctx(db)
    _, _, defect = _seed_active(client, ctx, db)
    resp = client.get(
        f"{DEFECTS_API}/{defect['id']}/history", headers=ctx.h(ctx.norole)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == dw.DEFECT_NOT_FOUND


# ── Write: matching scope → allowed (OGS scoped; CHIEF — отдельно GLOBAL) ─────


@pytest.mark.parametrize("scope_type", MATCHING_SCOPES)
def test_ogs_in_matching_scope_can_create_draft(
    client: TestClient, db: Session, scope_type: str
) -> None:
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-wd")
    ev = ctx.new_confirmed_evaluation(joint)
    actor = _worker_in_scope(ctx, "W", SCOPED_WRITE_ROLE, scope_type)
    resp = create_defect_http(
        client, actor, joint_id=joint.id, engineering_evaluation_id=ev.id
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "DRAFT"


@pytest.mark.parametrize("scope_type", MATCHING_SCOPES)
def test_ogs_in_matching_scope_can_create_active(
    client: TestClient, db: Session, scope_type: str
) -> None:
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-wa")
    ev = ctx.new_confirmed_evaluation(joint)
    actor = _worker_in_scope(ctx, "W", SCOPED_WRITE_ROLE, scope_type)
    resp = create_defect_http(
        client,
        actor,
        joint_id=joint.id,
        engineering_evaluation_id=ev.id,
        activate=True,
        extra_fields=valid_active_fields(db),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "ACTIVE"


def test_chief_welder_global_can_create_draft_and_active(
    client: TestClient, db: Session
) -> None:
    """CHIEF_WELDER допускается только с GLOBAL-scope (CHECK hr.worker_roles)."""
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-chief")
    ev = ctx.new_confirmed_evaluation(joint)
    draft = create_defect_http(
        client, ctx.chief, joint_id=joint.id, engineering_evaluation_id=ev.id
    )
    assert draft.status_code == 201
    joint2 = ctx.new_joint("J-chief2")
    ev2 = ctx.new_confirmed_evaluation(joint2)
    active = create_defect_http(
        client,
        ctx.chief,
        joint_id=joint2.id,
        engineering_evaluation_id=ev2.id,
        activate=True,
        extra_fields=valid_active_fields(db),
    )
    assert active.status_code == 201
    assert active.json()["status"] == "ACTIVE"


# ── Write: COMPANY-scope исключён для мутаций → 403 ──────────────────────────


@pytest.mark.parametrize("role_code", (SCOPED_WRITE_ROLE,))
def test_company_scope_write_role_create_draft_returns_403(
    client: TestClient, db: Session, role_code: str
) -> None:
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-cd")
    ev = ctx.new_confirmed_evaluation(joint)
    actor = _worker_in_scope(ctx, "C", role_code, "COMPANY")
    resp = create_defect_http(
        client, actor, joint_id=joint.id, engineering_evaluation_id=ev.id
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


@pytest.mark.parametrize("role_code", (SCOPED_WRITE_ROLE,))
def test_company_scope_write_role_patch_returns_403(
    client: TestClient, db: Session, role_code: str
) -> None:
    ctx = _rbac_ctx(db)
    joint, ev, defect = _seed_active(client, ctx, db)
    actor = _worker_in_scope(ctx, "C", role_code, "COMPANY")
    resp = client.patch(
        f"{DEFECTS_API}/{defect['id']}",
        json={"expected_version": defect["version"], "technical_note": "x"},
        headers=ctx.h(actor),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


# ── Write: SITE-scope не резолвится → create 403 ─────────────────────────────


def test_chief_welder_cannot_be_assigned_company_scope(db: Session) -> None:
    """CHIEF_WELDER не может быть назначен на COMPANY-scope (CHECK БД)."""
    ctx = _rbac_ctx(db)
    with pytest.raises(IntegrityError):
        ctx.scoped_role_worker(
            "ChC", "CHIEF_WELDER", "COMPANY", ctx.scope_id_for("COMPANY")
        )
    db.rollback()


@pytest.mark.parametrize("role_code", (SCOPED_WRITE_ROLE,))
def test_site_scope_write_role_create_draft_returns_403(
    client: TestClient, db: Session, role_code: str
) -> None:
    ctx = _rbac_ctx(db)
    joint = ctx.new_joint("J-sd")
    ev = ctx.new_confirmed_evaluation(joint)
    actor = _worker_in_scope(ctx, "S", role_code, "SITE")
    resp = create_defect_http(
        client, actor, joint_id=joint.id, engineering_evaluation_id=ev.id
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


# ── Read roles: matching scope → read allowed, write denied ────────────────────


@pytest.mark.parametrize("role_code", READ_ROLES)
@pytest.mark.parametrize("scope_type", MATCHING_SCOPES)
@pytest.mark.parametrize("op", READ_OPS)
def test_read_role_in_matching_scope_can_read(
    client: TestClient, db: Session, role_code: str, scope_type: str, op: str
) -> None:
    ctx = _rbac_ctx(db)
    joint, _, defect = _seed_active(client, ctx, db)
    actor = _worker_in_scope(ctx, "R", role_code, scope_type)
    if op == "get":
        resp = client.get(f"{DEFECTS_API}/{defect['id']}", headers=ctx.h(actor))
    elif op == "list":
        resp = client.get(
            DEFECTS_API, params={"joint_id": str(joint.id)}, headers=ctx.h(actor)
        )
    else:
        resp = client.get(
            f"{DEFECTS_API}/{defect['id']}/history", headers=ctx.h(actor)
        )
    assert resp.status_code == 200


@pytest.mark.parametrize("role_code", READ_ROLES)
@pytest.mark.parametrize("scope_type", MATCHING_SCOPES)
@pytest.mark.parametrize("op", WRITE_OPS)
def test_read_role_in_matching_scope_write_denied_403(
    client: TestClient, db: Session, role_code: str, scope_type: str, op: str
) -> None:
    ctx = _rbac_ctx(db)
    joint, ev, defect = _seed_active(client, ctx, db)
    actor = _worker_in_scope(ctx, "D", role_code, scope_type)
    headers = ctx.h(actor)
    if op == "patch":
        resp = client.patch(
            f"{DEFECTS_API}/{defect['id']}",
            json={"expected_version": defect["version"], "technical_note": "x"},
            headers=headers,
        )
    elif op == "activate":
        act_joint = ctx.new_joint("J-act")
        act_ev = ctx.new_confirmed_evaluation(act_joint)
        draft = _draft_only(client, ctx, act_joint, act_ev, db)
        resp = client.post(
            f"{DEFECTS_API}/{draft['id']}/activate",
            json={"expected_version": draft["version"]},
            headers=headers,
        )
    elif op == "supersede":
        resp = client.post(
            f"{DEFECTS_API}/{defect['id']}/supersede",
            json={"expected_version": defect["version"]},
            headers=headers,
        )
    else:
        resp = client.post(
            f"{DEFECTS_API}/{defect['id']}/cancel",
            json={"expected_version": defect["version"], "reason": "test"},
            headers=headers,
        )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


# ── COMPANY-scope: read allowed, write denied ──────────────────────────────────


@pytest.mark.parametrize("role_code", READ_ROLES)
def test_company_scope_read_role_can_get_defect(
    client: TestClient, db: Session, role_code: str
) -> None:
    ctx = _rbac_ctx(db)
    _, _, defect = _seed_active(client, ctx, db)
    actor = _worker_in_scope(ctx, "R", role_code, "COMPANY")
    resp = client.get(f"{DEFECTS_API}/{defect['id']}", headers=ctx.h(actor))
    assert resp.status_code == 200


@pytest.mark.parametrize("role_code", READ_ROLES)
def test_company_scope_read_role_write_denied_403(
    client: TestClient, db: Session, role_code: str
) -> None:
    ctx = _rbac_ctx(db)
    joint, ev, defect = _seed_active(client, ctx, db)
    actor = _worker_in_scope(ctx, "D", role_code, "COMPANY")
    resp = client.patch(
        f"{DEFECTS_API}/{defect['id']}",
        json={"expected_version": defect["version"], "technical_note": "x"},
        headers=ctx.h(actor),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == dw.DEFECT_PERMISSION_DENIED


# ── Out-of-scope: hidden 404 на существующий ресурс ────────────────────────────


@pytest.mark.parametrize("op", READ_OPS)
def test_out_of_scope_read_role_gets_hidden_404(
    client: TestClient, db: Session, op: str
) -> None:
    ctx = _rbac_ctx(db)
    joint, _, defect = _seed_active(client, ctx, db)
    outsider = ctx.scoped_role_worker(
        "Out", "OTK_INSPECTOR", "PROJECT", str(uuid4())
    )
    headers = ctx.h(outsider)
    if op == "get":
        resp = client.get(f"{DEFECTS_API}/{defect['id']}", headers=headers)
    elif op == "list":
        resp = client.get(
            DEFECTS_API, params={"joint_id": str(joint.id)}, headers=headers
        )
    else:
        resp = client.get(f"{DEFECTS_API}/{defect['id']}/history", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == dw.DEFECT_NOT_FOUND


@pytest.mark.parametrize("op", WRITE_OPS)
def test_out_of_scope_write_role_mutation_gets_hidden_404(
    client: TestClient, db: Session, op: str
) -> None:
    ctx = _rbac_ctx(db)
    joint, ev, defect = _seed_active(client, ctx, db)
    outsider = ctx.scoped_role_worker(
        "OutW", "OGS_ENGINEER", "PROJECT", str(uuid4())
    )
    headers = ctx.h(outsider)
    if op == "patch":
        resp = client.patch(
            f"{DEFECTS_API}/{defect['id']}",
            json={"expected_version": defect["version"], "technical_note": "x"},
            headers=headers,
        )
    elif op == "activate":
        act_joint = ctx.new_joint("J-oact")
        act_ev = ctx.new_confirmed_evaluation(act_joint)
        draft = _draft_only(client, ctx, act_joint, act_ev, db)
        resp = client.post(
            f"{DEFECTS_API}/{draft['id']}/activate",
            json={"expected_version": draft["version"]},
            headers=headers,
        )
    elif op == "supersede":
        resp = client.post(
            f"{DEFECTS_API}/{defect['id']}/supersede",
            json={"expected_version": defect["version"]},
            headers=headers,
        )
    else:
        resp = client.post(
            f"{DEFECTS_API}/{defect['id']}/cancel",
            json={"expected_version": defect["version"], "reason": "test"},
            headers=headers,
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == dw.DEFECT_NOT_FOUND
