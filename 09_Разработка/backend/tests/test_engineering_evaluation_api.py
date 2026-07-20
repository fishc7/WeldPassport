"""API-тесты команд lifecycle EngineeringEvaluation (Task 9D-2D, ADR-021; Spec §13).

Покрывают: полный lifecycle create→update→sources/criteria→prepare→fix→set-effective;
инвариант C01/C04 (finding.status не меняется, объекты исполнения не создаются); RBAC
(prepare — OGS, fix/set-effective — CHIEF_WELDER; `EVAL_SAME_ACTOR_PREPARE_FIX`);
optimistic locking; запрет правки не-DRAFT; проверку комплектности на prepare;
возврат PREPARED→DRAFT; withdraw; создание ревизии-пересмотра + supersede; сверку
источников на fix (`EVAL_SOURCE_STALE`); reverify-sources; двухролевой review-workflow
(§7.8); события в журнале.

`recommended_disposition` необязывающая: ни одна команда не переводит finding и не
создаёт FindingDisposition (проверяется по неизменности finding.status).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_workflow as eew

from .test_engineering_evaluation_core import EvalCtx, _role_worker

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
REV = "/api/v1/quality/engineering-evaluation-revisions"


class Api:
    """Хелпер: EvalCtx + CHIEF_WELDER + короткие обёртки над HTTP-командами."""

    def __init__(self, db: Session, client: TestClient, code: str) -> None:
        self.ctx = EvalCtx(db, client, code)
        self.db = db
        self.client = client
        self.ogs = self.ctx.ogs
        self.chief = _role_worker(db, f"{code}CW", "CHIEF_WELDER")

    def h(self, worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def new_finding(self):
        return self.ctx.make_finding()

    def create_eval(self, finding, worker=None):
        w = worker or self.ogs
        return self.client.post(
            f"/api/v1/quality/findings/{finding.id}/engineering-evaluation",
            headers=self.h(w),
        )

    def rev_version(self, rid) -> int:
        r = self.client.get(f"{REV}/{rid}", headers=self.h(self.ogs))
        assert r.status_code == 200, r.text
        return r.json()["version"]

    def add_source(self, rid, finding, worker=None):
        w = worker or self.ogs
        return self.client.post(
            f"{REV}/{rid}/sources",
            json={
                "expected_version": self.rev_version(rid),
                "source_role": "PRIMARY_EVIDENCE",
                "source_entity_type": "QUALITY_FINDING",
                "source_entity_id": str(finding.id),
            },
            headers=self.h(w),
        )

    def add_criterion(self, rid, result="COMPLIES", worker=None, **extra):
        w = worker or self.ogs
        body = {
            "expected_version": self.rev_version(rid),
            "requirement_ref": "ГОСТ 16037",
            "parameter": "смещение кромок",
            "comparison_result": result,
        }
        body.update(extra)
        return self.client.post(f"{REV}/{rid}/criteria", json=body, headers=self.h(w))

    def add_exception(self, rid, criterion_id, worker=None):
        w = worker or self.ogs
        return self.client.post(
            f"{REV}/{rid}/exceptions",
            json={
                "expected_version": self.rev_version(rid),
                "criterion_id": str(criterion_id),
                "basis": "п.5.2",
                "justification": "локальное отступление допустимо",
                "residual_risk": "контролируемый",
            },
            headers=self.h(w),
        )

    def update_rev(self, rid, worker=None, **fields):
        w = worker or self.ogs
        body = {"expected_version": self.rev_version(rid), **fields}
        return self.client.post(f"{REV}/{rid}/update", json=body, headers=self.h(w))

    def cmd(self, rid, name, worker, **body):
        body.setdefault("expected_version", self.rev_version(rid))
        return self.client.post(
            f"{REV}/{rid}/{name}", json=body, headers=self.h(worker)
        )

    def fill_acceptable(self, rid, finding):
        """Готовит корректную ACCEPTABLE-ревизию (все COMPLIES, без исключений)."""
        assert self.add_source(rid, finding).status_code == 201
        assert self.add_criterion(rid, "COMPLIES").status_code == 201
        assert self.update_rev(
            rid,
            evaluation_outcome="ACCEPTABLE",
            classification="NOT_CONFIRMED",
            recommended_disposition="NONE",
            confirmed_severity="NOT_APPLICABLE",
            impact_scope="NO_OPERATIONAL_IMPACT",
            rationale="соответствует применимым критериям",
        ).status_code == 200

    def to_effective(self, rid, finding):
        """Проводит DRAFT-ревизию до EFFECTIVE (prepare OGS → fix/set-effective chief)."""
        self.fill_acceptable(rid, finding)
        assert self.cmd(rid, "prepare", self.ogs).status_code == 200
        assert self.cmd(rid, "fix", self.chief).status_code == 200
        r = self.cmd(rid, "set-effective", self.chief)
        assert r.status_code == 200, r.text
        return r


def _mk(client, db, code):
    api = Api(db, client, code)
    finding = api.new_finding()
    r = api.create_eval(finding)
    assert r.status_code == 201, r.text
    return api, finding, r.json()["id"]


# ── Полный lifecycle + C04 ────────────────────────────────────────────────────


def test_full_lifecycle_and_finding_unchanged(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL1")
    api.to_effective(rid, finding)

    detail = client.get(f"{REV}/{rid}", headers=api.h(api.ogs)).json()
    assert detail["status"] == "EFFECTIVE"
    assert detail["effective_at"] is not None

    # C04/C01: статус finding не изменился, оценка finding не переводила.
    db.refresh(finding)
    assert finding.status == "UNDER_EVALUATION"

    # Оценка помечена действующей ревизией.
    ev = client.get(
        f"/api/v1/quality/findings/{finding.id}/engineering-evaluation",
        headers=api.h(api.ogs),
    ).json()
    assert ev["effective_revision_id"] == rid

    # События покрывают весь переход.
    events = client.get(
        f"/api/v1/quality/engineering-evaluations/{ev['id']}/events",
        headers=api.h(api.ogs),
    ).json()
    types = [e["event_type"] for e in events]
    for expected in (
        "EVALUATION_CREATED",
        "EVALUATION_PREPARED",
        "EVALUATION_FIXED",
        "EVALUATION_BECAME_EFFECTIVE",
    ):
        assert expected in types


# ── RBAC / same-actor ─────────────────────────────────────────────────────────


def test_prepare_requires_welding_engineer(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL2")
    api.fill_acceptable(rid, finding)
    # CHIEF_WELDER не готовит (роль OGS/WELDING_ENGINEER).
    r = api.cmd(rid, "prepare", api.chief)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == eew.EVAL_ROLE_DENIED


def test_fix_requires_chief_welder(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL3")
    api.fill_acceptable(rid, finding)
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    r = api.cmd(rid, "fix", api.ogs)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == eew.EVAL_ROLE_DENIED


def test_same_actor_prepare_fix_rejected(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL4")
    api.fill_acceptable(rid, finding)
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    # Дать chief также роль OGS, чтобы он мог prepare — но здесь наоборот: prepare
    # выполнил OGS; дадим OGS роль CHIEF_WELDER и попробуем fix тем же актором.
    from app.hr.models import WorkerRole  # локальный импорт: только для этого теста

    db.add(
        WorkerRole(
            worker_id=api.ogs.id, role_code="CHIEF_WELDER", scope_type="GLOBAL",
            is_active=True, valid_from=api.ogs.hire_date,
        )
    )
    db.commit()
    r = api.cmd(rid, "fix", api.ogs)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == eew.EVAL_SAME_ACTOR_PREPARE_FIX


# ── Optimistic locking / правка не-DRAFT ──────────────────────────────────────


def test_version_conflict_on_update(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL5")
    r = api.client.post(
        f"{REV}/{rid}/update",
        json={"expected_version": 999, "rationale": "x"},
        headers=api.h(api.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == eew.EVAL_VERSION_CONFLICT


def test_edit_blocked_when_not_draft(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL6")
    api.fill_acceptable(rid, finding)
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    # Добавление критерия после PREPARED запрещено.
    r = api.add_criterion(rid, "COMPLIES")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == eew.EVAL_REVISION_NOT_DRAFT


# ── Проверка комплектности на prepare ─────────────────────────────────────────


def test_prepare_incomplete_aggregates(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL7")
    r = api.cmd(rid, "prepare", api.ogs)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == eew.EVAL_PREPARE_INCOMPLETE
    codes = {v["code"] for v in detail["violations"]}
    assert eew.EVAL_OUTCOME_REQUIRED in codes
    assert eew.EVAL_SOURCE_REQUIRED in codes


# ── Возврат PREPARED → DRAFT и повторная подготовка ───────────────────────────


def test_return_then_reprepare(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL8")
    api.fill_acceptable(rid, finding)
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    r = api.cmd(rid, "return", api.chief, reason="уточнить критерий")
    assert r.status_code == 200
    assert r.json()["status"] == "DRAFT"
    # Возврат не создал новую ревизию.
    ev = client.get(
        f"/api/v1/quality/findings/{finding.id}/engineering-evaluation",
        headers=api.h(api.ogs),
    ).json()
    assert len(ev["revisions"]) == 1
    # Повторная подготовка снова возможна.
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200


# ── Withdraw ──────────────────────────────────────────────────────────────────


def test_withdraw_terminal(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "AL9")
    api.fill_acceptable(rid, finding)
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    r = api.cmd(rid, "withdraw", api.chief, reason="дубликат оценки")
    assert r.status_code == 200
    assert r.json()["status"] == "WITHDRAWN"
    # Из WITHDRAWN переходов нет.
    assert api.cmd(rid, "prepare", api.ogs).status_code == 409


# ── Ревизия-пересмотр + supersede ─────────────────────────────────────────────


def test_new_revision_and_supersede(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALA")
    api.to_effective(rid, finding)
    # Новая ревизия-пересмотр после EFFECTIVE.
    r = client.post(
        f"/api/v1/quality/findings/{finding.id}/engineering-evaluation/revisions",
        json={"revision_reason": "получены новые данные НК"},
        headers=api.h(api.ogs),
    )
    assert r.status_code == 201, r.text
    rid2 = r.json()["id"]
    assert r.json()["revision_no"] == 2
    api.to_effective(rid2, finding)
    # Предыдущая ревизия замещена.
    prev = client.get(f"{REV}/{rid}", headers=api.h(api.ogs)).json()
    assert prev["status"] == "SUPERSEDED"


def test_new_revision_blocked_while_open(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALB")
    # Текущая ревизия ещё DRAFT (открыта) → новую создать нельзя.
    r = client.post(
        f"/api/v1/quality/findings/{finding.id}/engineering-evaluation/revisions",
        json={"revision_reason": "рано"},
        headers=api.h(api.ogs),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == eew.EVAL_INVALID_TRANSITION


# ── Validation matrix через API ───────────────────────────────────────────────


def test_conditionally_acceptable_needs_exception(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALC")
    assert api.add_source(rid, finding).status_code == 201
    assert api.add_criterion(rid, "DOES_NOT_COMPLY").status_code == 201
    assert api.update_rev(
        rid,
        evaluation_outcome="CONDITIONALLY_ACCEPTABLE",
        classification="CONFIRMED_DEFECT",
        recommended_disposition="REPAIR",
        confirmed_severity="MAJOR",
        impact_scope="FULL_JOINT_BLOCK",
        rationale="условно приемлемо",
        confidence_level="HIGH",
        residual_risk="остаточный риск",
        application_conditions="ограничение давления",
        review_due_at=FUTURE,
    ).status_code == 200
    r = api.cmd(rid, "prepare", api.ogs)
    assert r.status_code == 422
    codes = {v["code"] for v in r.json()["detail"]["violations"]}
    assert eew.EVAL_ACCEPT_WITHOUT_EXCEPTION in codes


def test_conditionally_acceptable_with_exception_ok(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALD")
    assert api.add_source(rid, finding).status_code == 201
    crit = api.add_criterion(rid, "DOES_NOT_COMPLY").json()
    assert api.add_exception(rid, crit["id"]).status_code == 201
    assert api.update_rev(
        rid,
        evaluation_outcome="CONDITIONALLY_ACCEPTABLE",
        classification="CONFIRMED_DEFECT",
        recommended_disposition="REPAIR",
        confirmed_severity="MAJOR",
        impact_scope="FULL_JOINT_BLOCK",
        rationale="условно приемлемо",
        confidence_level="HIGH",
        residual_risk="остаточный риск",
        application_conditions="ограничение давления",
        review_due_at=FUTURE,
    ).status_code == 200
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200


# ── Источники: сверка на fix и reverify ───────────────────────────────────────


def test_stale_source_blocks_fix(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALE")
    api.fill_acceptable(rid, finding)
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    # Значимое поле профиля QUALITY_FINDING меняется → источник устаревает.
    finding.initial_risk = "LOW"
    db.commit()
    r = api.cmd(rid, "fix", api.chief)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == eew.EVAL_SOURCE_STALE


def test_reverify_sources_after_change(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALF")
    assert api.add_source(rid, finding).status_code == 201
    finding.initial_risk = "LOW"
    db.commit()
    # Источник устарел → reverify падает staleness (автоподмены хэша нет).
    r = api.cmd(rid, "reverify-sources", api.ogs)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == eew.EVAL_SOURCE_STALE


# ── Review-workflow (§7.8) ────────────────────────────────────────────────────


def test_review_confirmation_two_roles(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALG")
    api.to_effective(rid, finding)
    assert api.cmd(
        rid, "request-review-confirmation", api.ogs, proposed_review_due_at=FUTURE
    ).status_code == 200
    # confirm срок отдельно не передаёт — применяется proposed из запроса (C20).
    r = api.cmd(rid, "confirm-review", api.chief)
    assert r.status_code == 200, r.text
    assert r.json()["review_due_at"] is not None


def test_review_confirm_same_actor_rejected(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "ALH")
    api.to_effective(rid, finding)
    # Дать chief роль OGS, чтобы он мог инициировать, затем сам подтверждает.
    from app.hr.models import WorkerRole

    db.add(
        WorkerRole(
            worker_id=api.chief.id, role_code="OGS_ENGINEER", scope_type="GLOBAL",
            is_active=True, valid_from=api.chief.hire_date,
        )
    )
    db.commit()
    assert api.cmd(
        rid, "request-review-confirmation", api.chief, proposed_review_due_at=FUTURE
    ).status_code == 200
    r = api.cmd(rid, "confirm-review", api.chief)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == eew.EVAL_SAME_ACTOR_REVIEW
