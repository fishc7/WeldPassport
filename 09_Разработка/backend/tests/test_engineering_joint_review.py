"""Интеграционные тесты Joint Review Lifecycle (Task 5B, ADR-011).

Покрывают: статусы жизненного цикла, независимые согласования ПТО/ОГС, три версии
(record/approval/workflow) и коды 409, выборочный сброс согласований, блокировки
(отдельные записи, §20), отмену, атомарную замену, иерархический scope, роли ПТО/
ОГС/CHIEF_WELDER/AUDITOR, историю. Канон статусов — DRAFT/PENDING_REVIEW/ACTIVE/
CANCELLED/SUPERSEDED (решение владельца 2026-07-11); BLOCKED — не статус.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument
from app.hr.models import Worker, WorkerRole
from app.hr.services import HrService
from app.hr.schemas import WorkerRoleCreate
from app.projects.models import Company, Line, Project, ProjectCompany
from app.shared.errors import ConflictError

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"
TODAY = date.today()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Rev{suffix}",
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
    is_active: bool = True,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=is_active,
        valid_from=valid_from or TODAY,
        valid_to=valid_to,
    )
    db.add(role)
    db.commit()
    return role


def _role_worker(
    db: Session, suffix: str, role_code: str, **scope
) -> Worker:
    w = _worker(db, suffix)
    _assign_role(db, w.id, role_code, **scope)
    return w


class Ctx:
    """Полный контекст: проект/линия/документ/ревизия + типовые ролевые работники."""

    def __init__(self, db: Session, code: str) -> None:
        self.db = db
        self.creator = _worker(db, f"{code}Creator")
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
        # Типовые ролевые работники (GLOBAL).
        self.pto = _role_worker(db, f"{code}Pto", "PTO_ENGINEER")
        self.ogs = _role_worker(db, f"{code}Ogs", "OGS_ENGINEER")
        self.chief = _role_worker(db, f"{code}Chief", "CHIEF_WELDER")
        self.auditor = _role_worker(db, f"{code}Aud", "AUDITOR")

    def headers(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def create_joint(self, client: TestClient, joint_no: str = "J-1", **overrides):
        payload = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": joint_no,
            "created_by": self.creator.id,
        }
        payload.update(overrides)
        resp = client.post(
            f"{ENGINEERING_URL}/joints", json=payload,
            headers=self.headers(self.creator),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()


def _post(client, url, worker_headers, json=None):
    return client.post(url, json=json or {}, headers=worker_headers)


def _submit(client, ctx: Ctx, jid: str, worker: Worker | None = None):
    worker = worker or ctx.pto
    return _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/submit-for-review",
        ctx.headers(worker),
    )


def _approve_pto(client, ctx: Ctx, jid: str, worker: Worker | None = None, **body):
    return _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/approve-pto",
        ctx.headers(worker or ctx.pto), body,
    )


def _approve_ogs(client, ctx: Ctx, jid: str, worker: Worker | None = None, **body):
    return _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/approve-ogs",
        ctx.headers(worker or ctx.ogs), body,
    )


def _make_active(client, ctx: Ctx, joint_no: str = "J-1") -> dict:
    body = ctx.create_joint(client, joint_no=joint_no)
    jid = body["id"]
    assert _submit(client, ctx, jid).status_code == 200
    assert _approve_pto(client, ctx, jid).status_code == 200
    resp = _approve_ogs(client, ctx, jid)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ACTIVE"
    return data


def _get(client, ctx: Ctx, jid: str, worker: Worker | None = None):
    return client.get(
        f"{ENGINEERING_URL}/joints/{jid}",
        headers=ctx.headers(worker or ctx.pto),
    )


# ══ A. Миграция и обратная совместимость ══════════════════════════════════════


def test_new_joint_has_three_versions_at_one(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AVER")
    body = ctx.create_joint(client)
    assert body["record_version"] == 1
    assert body["approval_version"] == 1
    assert body["workflow_version"] == 1
    # version — зеркало record_version (обратная совместимость Task 5A).
    assert body["version"] == 1
    assert body["status"] == "DRAFT"
    assert body["pto_status"] == "NOT_SUBMITTED"
    assert body["ogs_status"] == "NOT_SUBMITTED"


# ══ B. Статусы и терминальность ═══════════════════════════════════════════════


def test_submit_moves_draft_to_pending_review(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BSUB")
    jid = ctx.create_joint(client)["id"]
    body = _submit(client, ctx, jid).json()
    assert body["status"] == "PENDING_REVIEW"
    assert body["pto_status"] == "PENDING"
    assert body["ogs_status"] == "PENDING"
    assert body["pto_pending_reason"] == "INITIAL_REVIEW"
    assert body["ogs_pending_reason"] == "INITIAL_REVIEW"


def test_cancelled_is_terminal(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCAN")
    jid = ctx.create_joint(client)["id"]
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/cancel",
        ctx.headers(ctx.pto), {"reason": "ошибка"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    # Повторная команда запрещена.
    again = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/cancel",
        ctx.headers(ctx.pto), {"reason": "ещё"},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "TERMINAL_JOINT"


def test_superseded_is_terminal(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BSUP")
    source = _make_active(client, ctx, joint_no="SRC")
    successor = _make_active(client, ctx, joint_no="SUC")
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{source['id']}/supersede",
        ctx.headers(ctx.pto), {"successor_joint_id": successor["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "SUPERSEDED"
    # Терминальный: правка запрещена.
    patch = client.patch(
        f"{ENGINEERING_URL}/joints/{source['id']}",
        json={"expected_version": 99, "updated_by": ctx.pto.id, "dn_1": "5"},
        headers=ctx.headers(ctx.pto),
    )
    assert patch.status_code == 409
    assert patch.json()["detail"]["code"] == "TERMINAL_JOINT"


# ══ C. Submit ═════════════════════════════════════════════════════════════════


def test_submit_twice_from_pending_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "CSUB")
    jid = ctx.create_joint(client)["id"]
    assert _submit(client, ctx, jid).status_code == 200
    resp = _submit(client, ctx, jid)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "INVALID_TRANSITION"


def test_resubmit_after_reject_reopens(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "CREO")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/reject-pto",
        ctx.headers(ctx.pto), {"reason": "замечание"},
    )
    resp = _submit(client, ctx, jid)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pto_status"] == "PENDING"
    assert body["pto_pending_reason"] == "REVIEW_REOPENED"


# ══ D. PTO approval ═══════════════════════════════════════════════════════════


def test_pto_engineer_in_scope_can_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DPTO")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    resp = _approve_pto(client, ctx, jid)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pto_status"] == "APPROVED"
    assert body["pto_decision_method"] == "MANUAL"
    assert body["pto_approval_version"] == body["approval_version"]


def test_pto_out_of_scope_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DOUT")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    # ПТО с ролью в чужом проекте.
    foreign = _role_worker(
        db, "DForeign", "PTO_ENGINEER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = _approve_pto(client, ctx, jid, worker=foreign)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ROLE_DENIED"


def test_no_role_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DNOR")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    plain = _worker(db, "DPlain")  # активный работник без ролей
    resp = _approve_pto(client, ctx, jid, worker=plain)
    assert resp.status_code == 403


def test_inactive_and_expired_role_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DINA")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    inactive = _role_worker(db, "DInact", "PTO_ENGINEER", is_active=False)
    assert _approve_pto(client, ctx, jid, worker=inactive).status_code == 403
    expired = _role_worker(
        db, "DExp", "PTO_ENGINEER", valid_to=TODAY - timedelta(days=1)
    )
    assert _approve_pto(client, ctx, jid, worker=expired).status_code == 403


def test_wrong_approval_version_conflict(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DVER")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    resp = _approve_pto(client, ctx, jid, expected_approval_version=999)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "APPROVAL_VERSION_CONFLICT"


# ══ E. OGS approval ═══════════════════════════════════════════════════════════


def test_ogs_engineer_in_scope_can_approve(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "EOGS")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    resp = _approve_ogs(client, ctx, jid)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ogs_status"] == "APPROVED"


def test_ogs_engineer_cannot_do_pto(client: TestClient, db: Session) -> None:
    """OGS_ENGINEER не получает общесистемных прав: ПТО-действие → 403."""
    ctx = Ctx(db, "EOSYS")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    resp = _approve_pto(client, ctx, jid, worker=ctx.ogs)
    assert resp.status_code == 403


def test_chief_welder_global_can_approve_ogs(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ECHF")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    resp = _approve_ogs(client, ctx, jid, worker=ctx.chief)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ogs_status"] == "APPROVED"


def test_chief_welder_non_global_scope_rejected(db: Session) -> None:
    worker = _worker(db, "EChiefBad")
    service = HrService(db)
    with pytest.raises(ConflictError):
        service.assign_worker_role(
            worker.id,
            WorkerRoleCreate(
                role_code="CHIEF_WELDER", scope_type="PROJECT", scope_id=str(uuid4())
            ),
        )


def test_override_only_chief_welder(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "EOVR")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    # OGS_ENGINEER с OVERRIDE — запрещено.
    denied = _approve_ogs(client, ctx, jid, worker=ctx.ogs, method="OVERRIDE")
    assert denied.status_code == 403
    # CHIEF_WELDER с OVERRIDE — разрешено.
    ok = _approve_ogs(client, ctx, jid, worker=ctx.chief, method="OVERRIDE")
    assert ok.status_code == 200, ok.text
    assert ok.json()["ogs_decision_method"] == "OVERRIDE"


def test_ogs_automatic_method_recorded(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "EAUTO")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    resp = _approve_ogs(client, ctx, jid, method="AUTOMATIC")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ogs_decision_method"] == "AUTOMATIC"


# ══ F. Активация ══════════════════════════════════════════════════════════════


def test_single_approval_does_not_activate(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "FONE")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    body = _approve_pto(client, ctx, jid).json()
    assert body["status"] == "PENDING_REVIEW"


def test_both_approvals_activate(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "FBOTH")
    data = _make_active(client, ctx)
    assert data["status"] == "ACTIVE"
    assert data["requires_review"] is False


def test_stale_approval_does_not_activate(client: TestClient, db: Session) -> None:
    """Значимая правка после согласования сбрасывает сторону — активации нет."""
    ctx = Ctx(db, "FSTALE")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    _approve_pto(client, ctx, jid)
    body = _approve_ogs(client, ctx, jid).json()
    assert body["status"] == "ACTIVE"
    # Значимая правка ПТО-поля → approval_version растёт, ПТО сброшен.
    rv = body["record_version"]
    patch = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": rv, "updated_by": ctx.pto.id,
              "component_text_1": "новое"},
        headers=ctx.headers(ctx.pto),
    )
    assert patch.status_code == 200, patch.text
    pb = patch.json()
    assert pb["status"] == "PENDING_REVIEW"
    assert pb["pto_status"] == "PENDING"
    assert pb["ogs_status"] == "APPROVED"  # незатронутая сторона сохранена


# ══ G. Revoke ═════════════════════════════════════════════════════════════════


def test_revoke_reason_required(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "GREAS")
    data = _make_active(client, ctx)
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{data['id']}/revoke-pto",
        ctx.headers(ctx.pto), {"reason": "   "},
    )
    assert resp.status_code == 422


def test_revoke_removes_from_active(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "GACT")
    data = _make_active(client, ctx)
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{data['id']}/revoke-pto",
        ctx.headers(ctx.pto), {"reason": "отзыв"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pto_status"] == "REVOKED"
    assert body["status"] == "PENDING_REVIEW"


def test_direct_restore_of_revoked_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "GRES")
    data = _make_active(client, ctx)
    jid = data["id"]
    _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/revoke-pto",
        ctx.headers(ctx.pto), {"reason": "отзыв"},
    )
    # Прямое approve REVOKED без повторной отправки — запрещено.
    resp = _approve_pto(client, ctx, jid)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "INVALID_APPROVAL_STATE"


# ══ H. Блокировки (отдельные записи, §20) ═════════════════════════════════════


def test_block_records_actor_and_reason(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "HBLK")
    data = _make_active(client, ctx)
    jid = data["id"]
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/block",
        ctx.headers(ctx.pto), {"reason": "ждём WPS", "scope": "PRODUCTION"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Joint остаётся ACTIVE — блокировка не статус (§20).
    assert body["status"] == "ACTIVE"
    assert body["is_blocked"] is True
    blocks = client.get(
        f"{ENGINEERING_URL}/joints/{jid}/blocks", headers=ctx.headers(ctx.pto)
    ).json()
    assert len(blocks) == 1
    assert blocks[0]["created_by"] == ctx.pto.id
    assert blocks[0]["reason"] == "ждём WPS"
    assert blocks[0]["released_at"] is None


def test_block_reason_required(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "HREAS")
    data = _make_active(client, ctx)
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{data['id']}/block",
        ctx.headers(ctx.pto), {"reason": ""},
    )
    assert resp.status_code == 422


def test_unblock_releases(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "HUNB")
    data = _make_active(client, ctx)
    jid = data["id"]
    _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/block",
        ctx.headers(ctx.pto), {"reason": "hold"},
    )
    blocks = client.get(
        f"{ENGINEERING_URL}/joints/{jid}/blocks", headers=ctx.headers(ctx.pto)
    ).json()
    block_id = blocks[0]["id"]
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/unblock",
        ctx.headers(ctx.pto), {"block_id": block_id, "reason": "снято"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_blocked"] is False
    # Повторное снятие → 409.
    again = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/unblock",
        ctx.headers(ctx.pto), {"block_id": block_id},
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "CANNOT_UNBLOCK"


def test_approval_block_prevents_activation(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "HAPP")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    # Блокировка области APPROVAL до согласований.
    _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/block",
        ctx.headers(ctx.pto), {"reason": "hold", "scope": "APPROVAL"},
    )
    _approve_pto(client, ctx, jid)
    body = _approve_ogs(client, ctx, jid).json()
    # Оба APPROVED, но блокировка APPROVAL не даёт активироваться.
    assert body["status"] == "PENDING_REVIEW"
    blocks = client.get(
        f"{ENGINEERING_URL}/joints/{jid}/blocks", headers=ctx.headers(ctx.pto)
    ).json()
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/unblock",
        ctx.headers(ctx.pto), {"block_id": blocks[0]["id"]},
    )
    # После снятия — автоматическая активация (§11).
    assert resp.json()["status"] == "ACTIVE"


# ══ I. Cancel ═════════════════════════════════════════════════════════════════


def test_cancel_reason_required(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ICAN")
    jid = ctx.create_joint(client)["id"]
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/cancel", ctx.headers(ctx.pto),
        {"reason": ""},
    )
    assert resp.status_code == 422


def test_cancel_preserves_joint_and_blocks_edits(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "IPRE")
    jid = ctx.create_joint(client)["id"]
    _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/cancel", ctx.headers(ctx.pto),
        {"reason": "ошибка"},
    )
    # Joint сохраняется (чтение доступно).
    got = _get(client, ctx, jid)
    assert got.status_code == 200
    assert got.json()["status"] == "CANCELLED"
    # Правка после отмены запрещена.
    patch = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": 1, "updated_by": ctx.pto.id, "dn_1": "5"},
        headers=ctx.headers(ctx.pto),
    )
    assert patch.status_code == 409


def test_cancel_requires_pto_role(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "IROLE")
    jid = ctx.create_joint(client)["id"]
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/cancel", ctx.headers(ctx.ogs),
        {"reason": "нельзя ОГС"},
    )
    assert resp.status_code == 403


# ══ J. Supersede ══════════════════════════════════════════════════════════════


def test_supersede_atomic(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "JATO")
    source = _make_active(client, ctx, joint_no="SRC")
    successor = _make_active(client, ctx, joint_no="SUC")
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{source['id']}/supersede",
        ctx.headers(ctx.pto), {"successor_joint_id": successor["id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "SUPERSEDED"
    assert body["superseded_by_joint_id"] == successor["id"]


def test_supersede_self_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "JSELF")
    source = _make_active(client, ctx, joint_no="SRC")
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{source['id']}/supersede",
        ctx.headers(ctx.pto), {"successor_joint_id": source["id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CANNOT_SUPERSEDE"


def test_supersede_wrong_source_version(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "JSRCV")
    source = _make_active(client, ctx, joint_no="SRC")
    successor = _make_active(client, ctx, joint_no="SUC")
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{source['id']}/supersede",
        ctx.headers(ctx.pto),
        {"successor_joint_id": successor["id"], "expected_source_version": 999},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SOURCE_JOINT_VERSION_CONFLICT"


def test_supersede_wrong_successor_version(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "JSUCV")
    source = _make_active(client, ctx, joint_no="SRC")
    successor = _make_active(client, ctx, joint_no="SUC")
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{source['id']}/supersede",
        ctx.headers(ctx.pto),
        {"successor_joint_id": successor["id"], "expected_successor_version": 999},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SUCCESSOR_JOINT_VERSION_CONFLICT"


def test_supersede_terminal_successor_forbidden(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "JTERM")
    source = _make_active(client, ctx, joint_no="SRC")
    successor = ctx.create_joint(client, joint_no="SUC")  # DRAFT, не ACTIVE
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{source['id']}/supersede",
        ctx.headers(ctx.pto), {"successor_joint_id": successor["id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CANNOT_SUPERSEDE"


# ══ K. Версии ═════════════════════════════════════════════════════════════════


def test_record_version_conflict(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "KREC")
    jid = ctx.create_joint(client)["id"]
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": 99, "updated_by": ctx.creator.id, "dn_1": "5"},
        headers=ctx.headers(ctx.creator),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "RECORD_VERSION_CONFLICT"


def test_workflow_version_conflict(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "KWF")
    jid = ctx.create_joint(client)["id"]
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/submit-for-review",
        ctx.headers(ctx.pto), {"expected_workflow_version": 999},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WORKFLOW_VERSION_CONFLICT"


def test_service_edit_bumps_only_record(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "KSVC")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    before = _get(client, ctx, jid).json()
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": before["record_version"],
              "updated_by": ctx.pto.id, "location_note": "примечание"},
        headers=ctx.headers(ctx.pto),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["record_version"] == before["record_version"] + 1
    assert body["approval_version"] == before["approval_version"]
    assert body["workflow_version"] == before["workflow_version"]
    # Согласования не сброшены.
    assert body["pto_status"] == "PENDING"


def test_significant_edit_bumps_record_and_approval(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "KSIG")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    before = _get(client, ctx, jid).json()
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": before["record_version"],
              "updated_by": ctx.pto.id, "dn_1": "80"},
        headers=ctx.headers(ctx.pto),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["record_version"] == before["record_version"] + 1
    assert body["approval_version"] == before["approval_version"] + 1
    assert body["workflow_version"] == before["workflow_version"]


def test_workflow_command_bumps_record_and_workflow(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "KCMD")
    jid = ctx.create_joint(client)["id"]
    before = _get(client, ctx, jid).json()
    body = _submit(client, ctx, jid).json()
    assert body["record_version"] == before["record_version"] + 1
    assert body["workflow_version"] == before["workflow_version"] + 1
    assert body["approval_version"] == before["approval_version"]


# ══ L. Выборочный сброс согласований ══════════════════════════════════════════


def test_pto_field_resets_only_pto(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LPTO")
    data = _make_active(client, ctx)
    jid = data["id"]
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": data["record_version"],
              "updated_by": ctx.pto.id, "component_text_1": "x"},
        headers=ctx.headers(ctx.pto),
    )
    body = resp.json()
    assert body["pto_status"] == "PENDING"
    assert body["pto_pending_reason"] == "REVALIDATION"
    assert body["ogs_status"] == "APPROVED"
    assert body["status"] == "PENDING_REVIEW"


def test_ogs_field_resets_only_ogs(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LOGS")
    data = _make_active(client, ctx)
    jid = data["id"]
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": data["record_version"],
              "updated_by": ctx.pto.id, "required_root_method": "141"},
        headers=ctx.headers(ctx.pto),
    )
    body = resp.json()
    assert body["ogs_status"] == "PENDING"
    assert body["pto_status"] == "APPROVED"


def test_common_field_resets_both(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LBOTH")
    data = _make_active(client, ctx)
    jid = data["id"]
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": data["record_version"],
              "updated_by": ctx.pto.id, "dn_1": "150"},
        headers=ctx.headers(ctx.pto),
    )
    body = resp.json()
    assert body["pto_status"] == "PENDING"
    assert body["ogs_status"] == "PENDING"
    assert body["status"] == "PENDING_REVIEW"


# ══ M. Иерархия scope ═════════════════════════════════════════════════════════


def test_project_scope_covers_joint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "MPRJ")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    w = _role_worker(
        db, "MPrj", "PTO_ENGINEER", scope_type="PROJECT",
        scope_id=str(ctx.project.id),
    )
    assert _approve_pto(client, ctx, jid, worker=w).status_code == 200


def test_line_scope_covers_joint_not_neighbor(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "MLINE")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    # Роль на линию стыка — покрывает.
    good = _role_worker(
        db, "MLineOk", "PTO_ENGINEER", scope_type="LINE", scope_id=str(ctx.line.id)
    )
    assert _approve_pto(client, ctx, jid, worker=good).status_code == 200
    # Роль на другую линию — не покрывает.
    other_line = Line(
        project_id=ctx.project.id, line_no="L-OTHER", status="active",
        required_inspection_types=[], created_by=ctx.creator.id,
    )
    db.add(other_line)
    db.commit()
    db.refresh(other_line)
    jid2 = ctx.create_joint(client, joint_no="J-2")["id"]
    _submit(client, ctx, jid2)
    bad = _role_worker(
        db, "MLineBad", "PTO_ENGINEER", scope_type="LINE",
        scope_id=str(other_line.id),
    )
    assert _approve_pto(client, ctx, jid2, worker=bad).status_code == 403


def test_engineering_document_scope(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "MDOC")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    good = _role_worker(
        db, "MDocOk", "PTO_ENGINEER", scope_type="ENGINEERING_DOCUMENT",
        scope_id=str(ctx.document.id),
    )
    assert _approve_pto(client, ctx, jid, worker=good).status_code == 200
    bad = _role_worker(
        db, "MDocBad", "PTO_ENGINEER", scope_type="ENGINEERING_DOCUMENT",
        scope_id=str(uuid4()),
    )
    jid2 = ctx.create_joint(client, joint_no="J-2")["id"]
    _submit(client, ctx, jid2)
    assert _approve_pto(client, ctx, jid2, worker=bad).status_code == 403


def test_company_scope_restricts_by_participation(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "MCOMP")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    company = Company(name="ООО Подрядчик", created_by=ctx.creator.id)
    db.add(company)
    db.commit()
    db.refresh(company)
    db.add(ProjectCompany(
        project_id=ctx.project.id, company_id=company.id,
        role_code="WELDING_CONTRACTOR", valid_from=TODAY,
    ))
    db.commit()
    # COMPANY-роль организации, участвующей в проекте — покрывает.
    good = _role_worker(
        db, "MCompOk", "PTO_ENGINEER", scope_type="COMPANY",
        scope_id=str(company.id),
    )
    assert _approve_pto(client, ctx, jid, worker=good).status_code == 200
    # COMPANY-роль организации не в проекте — не покрывает.
    bad = _role_worker(
        db, "MCompBad", "PTO_ENGINEER", scope_type="COMPANY", scope_id="987654",
    )
    jid2 = ctx.create_joint(client, joint_no="J-2")["id"]
    _submit(client, ctx, jid2)
    assert _approve_pto(client, ctx, jid2, worker=bad).status_code == 403


def test_multiple_roles_union_scope(client: TestClient, db: Session) -> None:
    """Несколько активных ролей объединяют разрешённые scope."""
    ctx = Ctx(db, "MUNI")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    w = _worker(db, "MUnion")
    # Чужой проект + нужная линия — доступ по второй роли.
    _assign_role(db, w.id, "PTO_ENGINEER", scope_type="PROJECT", scope_id=str(uuid4()))
    _assign_role(db, w.id, "PTO_ENGINEER", scope_type="LINE", scope_id=str(ctx.line.id))
    assert _approve_pto(client, ctx, jid, worker=w).status_code == 200


def test_unit_and_isometric_literals_rejected() -> None:
    for bad in ("UNIT", "ISOMETRIC"):
        with pytest.raises(Exception):
            WorkerRoleCreate(role_code="PTO_ENGINEER", scope_type=bad)  # type: ignore[arg-type]


# ══ N. Аудитор ════════════════════════════════════════════════════════════════


def test_auditor_can_read_but_not_command(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "NAUD")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    # Чтение Joint и истории — разрешено.
    got = _get(client, ctx, jid, worker=ctx.auditor)
    assert got.status_code == 200
    assert got.json()["available_actions"] == []
    events = client.get(
        f"{ENGINEERING_URL}/joints/{jid}/events", headers=ctx.headers(ctx.auditor)
    )
    assert events.status_code == 200
    # Изменяющие команды — запрещены.
    assert _approve_pto(client, ctx, jid, worker=ctx.auditor).status_code == 403
    assert _submit(client, ctx, jid, worker=ctx.auditor).status_code == 403


# ══ O. История ════════════════════════════════════════════════════════════════


def test_history_records_events_with_before_after(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "OHIST")
    jid = ctx.create_joint(client)["id"]
    _submit(client, ctx, jid)
    _approve_pto(client, ctx, jid)
    events = client.get(
        f"{ENGINEERING_URL}/joints/{jid}/events", headers=ctx.headers(ctx.pto)
    ).json()
    types = [e["event_type"] for e in events]
    assert "SUBMITTED_FOR_REVIEW" in types
    assert "PTO_APPROVED" in types
    submit_ev = next(e for e in events if e["event_type"] == "SUBMITTED_FOR_REVIEW")
    assert submit_ev["previous_status"] == "DRAFT"
    assert submit_ev["new_status"] == "PENDING_REVIEW"
    approve_ev = next(e for e in events if e["event_type"] == "PTO_APPROVED")
    assert approve_ev["previous_pto_status"] == "PENDING"
    assert approve_ev["new_pto_status"] == "APPROVED"
    assert approve_ev["actor_worker_id"] == ctx.pto.id
    assert approve_ev["actor_role_code"] == "PTO_ENGINEER"
    assert approve_ev["decision_method"] == "MANUAL"


def test_history_has_no_delete_endpoint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ONODEL")
    jid = ctx.create_joint(client)["id"]
    resp = client.delete(
        f"{ENGINEERING_URL}/joints/{jid}/events", headers=ctx.headers(ctx.pto)
    )
    assert resp.status_code == 405
