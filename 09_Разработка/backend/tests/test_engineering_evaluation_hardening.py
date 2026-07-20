"""API-тесты хардненинга EngineeringEvaluation (Task 9D-2E; ADR-021 C18/C19/C20).

Покрывают: копирование содержимого при `create_revision` (C18 — новые id, `is_draft_copy`,
переназначение `criterion_id`, сброс `verified_at`, отсутствие supersede до `set_effective`,
агрегированное событие со счётчиками); идемпотентную команду `check-review-overdue`
(C19 — одно `REVIEW_OVERDUE` на цикл, статусы не меняются); fingerprint подтверждения
пересмотра (C20 — happy path применяет `proposed_review_due_at`, mismatch → `EVAL_REVIEW_CONTENT_CHANGED`,
нет запроса → `EVAL_REVIEW_NOT_REQUESTED`); инвариант C04 (finding не меняется).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_workflow as eew
from app.quality.engineering_evaluation_models import EngineeringEvaluationRevision

from .test_engineering_evaluation_api import REV, Api

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
EE = "/api/v1/quality/findings"


def _mk(client, db, code):
    api = Api(db, client, code)
    finding = api.new_finding()
    r = api.create_eval(finding)
    assert r.status_code == 201, r.text
    return api, finding, r.json()["id"]


def _set_conditional_decision(api, rid, due):
    """Задаёт скалярные поля решения для исхода CONDITIONALLY_ACCEPTABLE."""
    assert api.update_rev(
        rid, evaluation_outcome="CONDITIONALLY_ACCEPTABLE",
        classification="CONFIRMED_DEFECT", recommended_disposition="REPAIR",
        confirmed_severity="MAJOR", impact_scope="FULL_JOINT_BLOCK",
        rationale="условно приемлемо", confidence_level="HIGH",
        residual_risk="остаточный риск", application_conditions="ограничение давления",
        review_due_at=due,
    ).status_code == 200


def _finalize(api, rid):
    assert api.cmd(rid, "prepare", api.ogs).status_code == 200
    assert api.cmd(rid, "fix", api.chief).status_code == 200
    assert api.cmd(rid, "set-effective", api.chief).status_code == 200


def _conditional_effective(api, finding, rid, due):
    """Доводит DRAFT до EFFECTIVE как CONDITIONALLY_ACCEPTABLE (source+deviated+exception)."""
    assert api.add_source(rid, finding).status_code == 201
    crit = api.add_criterion(rid, "DOES_NOT_COMPLY").json()
    assert api.add_exception(rid, crit["id"]).status_code == 201
    _set_conditional_decision(api, rid, due)
    _finalize(api, rid)


def _events(client, api, finding):
    ev = client.get(f"{EE}/{finding.id}/engineering-evaluation", headers=api.h(api.ogs))
    evid = ev.json()["id"]
    r = client.get(
        f"/api/v1/quality/engineering-evaluations/{evid}/events", headers=api.h(api.ogs)
    )
    return evid, r.json()


# ── C18: копирование содержимого при create_revision ──────────────────────────


def test_create_revision_copies_children(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCA")
    _conditional_effective(api, finding, rid, FUTURE)
    src0 = client.get(f"{REV}/{rid}", headers=api.h(api.ogs)).json()
    crit0_id = src0["criteria"][0]["id"]

    r = client.post(
        f"{EE}/{finding.id}/engineering-evaluation/revisions",
        json={"revision_reason": "получены новые данные НК"},
        headers=api.h(api.ogs),
    )
    assert r.status_code == 201, r.text
    new = r.json()
    rid2 = new["id"]

    # Копии присутствуют, с новыми id.
    assert len(new["sources"]) == 1
    assert len(new["criteria"]) == 1
    assert len(new["exceptions"]) == 1
    assert new["criteria"][0]["id"] != crit0_id
    # Исключение — черновая копия, criterion_id переназначен на копию критерия.
    assert new["exceptions"][0]["is_draft_copy"] is True
    assert new["exceptions"][0]["criterion_id"] == new["criteria"][0]["id"]
    # Источник требует повторной сверки.
    assert new["sources"][0]["verified_at"] is None

    # Агрегированное событие со счётчиками.
    _, events = _events(client, api, finding)
    created = [
        e for e in events
        if e["event_type"] == "EVALUATION_CREATED" and e["revision_id"] == rid2
    ][0]
    assert created["metadata"]["criteria_copied"] == 1
    assert created["metadata"]["sources_copied"] == 1
    assert created["metadata"]["exceptions_copied"] == 1
    assert created["metadata"]["source_revision_id"] == rid

    # Предыдущая ревизия НЕ superseded до set_effective новой (C18).
    prev = client.get(f"{REV}/{rid}", headers=api.h(api.ogs)).json()
    assert prev["status"] == "EFFECTIVE"


# ── C19: идемпотентная команда check-review-overdue ───────────────────────────


def _overdue_count(client, api, finding, rid):
    _, events = _events(client, api, finding)
    return len(
        [e for e in events if e["event_type"] == "REVIEW_OVERDUE" and e["revision_id"] == rid]
    )


def test_check_review_overdue_idempotent(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCB")
    _conditional_effective(api, finding, rid, PAST)  # срок уже в прошлом

    r1 = client.post(f"{REV}/{rid}/check-review-overdue", headers=api.h(api.ogs))
    assert r1.status_code == 200, r1.text
    assert _overdue_count(client, api, finding, rid) == 1

    # Повторный вызов — no-op (идемпотентность по циклу review_due_at).
    r2 = client.post(f"{REV}/{rid}/check-review-overdue", headers=api.h(api.chief))
    assert r2.status_code == 200
    assert _overdue_count(client, api, finding, rid) == 1

    # Статус ревизии и finding не изменились (C19/C04).
    assert client.get(f"{REV}/{rid}", headers=api.h(api.ogs)).json()["status"] == "EFFECTIVE"
    db.refresh(finding)
    assert finding.status == "UNDER_EVALUATION"


def test_check_review_overdue_noop_when_not_due(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCC")
    _conditional_effective(api, finding, rid, FUTURE)  # срок в будущем
    r = client.post(f"{REV}/{rid}/check-review-overdue", headers=api.h(api.ogs))
    assert r.status_code == 200
    assert _overdue_count(client, api, finding, rid) == 0


# ── C20: fingerprint подтверждения пересмотра ─────────────────────────────────


def test_review_happy_path_applies_proposed_due(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCD")
    api.to_effective(rid, finding)
    assert api.cmd(
        rid, "request-review-confirmation", api.ogs, proposed_review_due_at=FUTURE
    ).status_code == 200
    r = api.cmd(rid, "confirm-review", api.chief)
    assert r.status_code == 200, r.text
    # Вступил именно предложенный в запросе срок.
    assert r.json()["review_due_at"][:10] == FUTURE[:10]
    # Повторное подтверждение закрытого запроса запрещено.
    r2 = api.cmd(rid, "confirm-review", api.chief)
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == eew.EVAL_REVIEW_NOT_REQUESTED


def test_confirm_without_request(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCE")
    api.to_effective(rid, finding)
    r = api.cmd(rid, "confirm-review", api.chief)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == eew.EVAL_REVIEW_NOT_REQUESTED


def test_fingerprint_mismatch_blocks_confirm(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCF")
    api.to_effective(rid, finding)
    assert api.cmd(
        rid, "request-review-confirmation", api.ogs, proposed_review_due_at=FUTURE
    ).status_code == 200

    # Прямое изменение содержимого действующей ревизии → fingerprint расходится.
    rev = (
        db.query(EngineeringEvaluationRevision)
        .filter(EngineeringEvaluationRevision.id == rid)
        .one()
    )
    rev.rationale = (rev.rationale or "") + " (изменено вне процесса)"
    db.commit()

    r = api.cmd(rid, "confirm-review", api.chief)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == eew.EVAL_REVIEW_CONTENT_CHANGED


# ── C04 regression через полный хардненинг-цикл ───────────────────────────────


def test_c04_finding_unchanged_through_hardening(client: TestClient, db: Session):
    api, finding, rid = _mk(client, db, "HCG")
    _conditional_effective(api, finding, rid, PAST)
    client.post(f"{REV}/{rid}/check-review-overdue", headers=api.h(api.ogs))
    # Новая ревизия-пересмотр с копиями + вступление в силу.
    r = client.post(
        f"{EE}/{finding.id}/engineering-evaluation/revisions",
        json={"revision_reason": "пересмотр после просрочки"},
        headers=api.h(api.ogs),
    )
    rid2 = r.json()["id"]
    # Дочерние сущности скопированы (C18); задаём только скалярное решение и вводим в силу.
    _set_conditional_decision(api, rid2, FUTURE)
    _finalize(api, rid2)

    db.refresh(finding)
    assert finding.status == "UNDER_EVALUATION"
    # Предыдущая действующая ревизия замещена новой (supersede на set_effective).
    assert client.get(f"{REV}/{rid}", headers=api.h(api.ogs)).json()["status"] == "SUPERSEDED"
    # Ни одна ревизия не в APPROVED (термин не используется как статус оценки).
    statuses = {
        rv.status
        for rv in db.query(EngineeringEvaluationRevision)
        .filter(EngineeringEvaluationRevision.evaluation_id
                == client.get(f"{EE}/{finding.id}/engineering-evaluation",
                              headers=api.h(api.ogs)).json()["id"])
        .all()
    }
    assert "APPROVED" not in statuses
    assert statuses <= set(eew.EVALUATION_STATUSES)
