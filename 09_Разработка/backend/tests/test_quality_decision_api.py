"""HTTP contract tests for Task 10A-3 QualityDecision command API."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality.engineering_evaluation_models import EngineeringEvaluationRevision

from ._defect_support import DefectCtx


def test_openapi_exposes_only_approved_quality_decision_commands(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    prefix = "/api/v1/quality/quality-decisions"

    assert set(path for path in paths if path.startswith(prefix)) == {
        prefix,
        f"{prefix}/{{decision_id}}",
        f"{prefix}/{{decision_id}}/bases",
        f"{prefix}/{{decision_id}}/events",
        f"{prefix}/{{decision_id}}/draft",
        f"{prefix}/{{decision_id}}/submit-for-review",
        f"{prefix}/{{decision_id}}/return",
        f"{prefix}/{{decision_id}}/decide",
    }
    assert "patch" not in paths[f"{prefix}/{{decision_id}}"]
    assert f"{prefix}/{{decision_id}}/transition" not in paths


def _effective_revision(ctx: DefectCtx, joint) -> EngineeringEvaluationRevision:
    evaluation = ctx.new_confirmed_evaluation(joint)
    return ctx.db.get(
        EngineeringEvaluationRevision,
        evaluation.effective_revision_id,
    )


def test_mutating_route_requires_idempotency_key(client: TestClient) -> None:
    response = client.post(
        "/api/v1/quality/quality-decisions",
        headers={"X-User-Id": "1"},
        json={
            "joint_id": "00000000-0000-0000-0000-000000000001",
            "basis_revision_ids": [
                "00000000-0000-0000-0000-000000000002",
            ],
        },
    )

    assert response.status_code == 422


def test_draft_contract_rejects_direct_status_mutation(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/quality/quality-decisions/"
        "00000000-0000-0000-0000-000000000001/draft",
        headers={"X-User-Id": "1", "Idempotency-Key": "forbidden-status"},
        json={"expected_version": 1, "status": "DECIDED"},
    )

    assert response.status_code == 422


def test_api_preserves_auth_not_found_and_role_errors(
    client: TestClient,
    db: Session,
) -> None:
    unauthenticated = client.get(
        "/api/v1/quality/quality-decisions/"
        "00000000-0000-0000-0000-000000000001"
    )
    missing = client.get(
        "/api/v1/quality/quality-decisions/"
        "00000000-0000-0000-0000-000000000001",
        headers={"X-User-Id": "1"},
    )

    ctx = DefectCtx(db, "Qar")
    joint = ctx.new_joint("J-QD-API-ROLE")
    revision = _effective_revision(ctx, joint)
    denied = client.post(
        "/api/v1/quality/quality-decisions",
        headers={
            "X-User-Id": str(ctx.norole.id),
            "Idempotency-Key": "role-denied",
        },
        json={
            "joint_id": str(joint.id),
            "basis_revision_ids": [str(revision.id)],
        },
    )

    assert unauthenticated.status_code == 401
    assert missing.status_code == 404
    assert denied.status_code == 403


def test_create_replay_and_payload_conflict(
    client: TestClient,
    db: Session,
) -> None:
    ctx = DefectCtx(db, "Qa")
    joint = ctx.new_joint("J-QD-API-IDEM")
    revision = _effective_revision(ctx, joint)
    headers = {
        "X-User-Id": str(ctx.ogs.id),
        "Idempotency-Key": "api-create-replay",
    }
    body = {
        "joint_id": str(joint.id),
        "basis_revision_ids": [str(revision.id)],
        "summary": "Итог API",
    }

    first = client.post(
        "/api/v1/quality/quality-decisions",
        headers=headers,
        json=body,
    )
    replay = client.post(
        "/api/v1/quality/quality-decisions",
        headers=headers,
        json=body,
    )
    conflict = client.post(
        "/api/v1/quality/quality-decisions",
        headers=headers,
        json={**body, "summary": "Другой итог"},
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "QD_IDEMPOTENCY_CONFLICT"


def test_command_api_runs_full_quality_decision_lifecycle(
    client: TestClient,
    db: Session,
) -> None:
    ctx = DefectCtx(db, "Qal")
    joint = ctx.new_joint("J-QD-API-LIFECYCLE")
    revision = _effective_revision(ctx, joint)
    base = "/api/v1/quality/quality-decisions"

    created_response = client.post(
        base,
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-create",
        },
        json={
            "joint_id": str(joint.id),
            "basis_revision_ids": [str(revision.id)],
            "summary": "Первая редакция",
        },
    )
    assert created_response.status_code == 201, created_response.text
    decision = created_response.json()
    decision_id = decision["id"]

    submitted_response = client.post(
        f"{base}/{decision_id}/submit-for-review",
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-submit-1",
        },
        json={"expected_version": decision["version"]},
    )
    assert submitted_response.status_code == 200, submitted_response.text
    submitted = submitted_response.json()
    assert submitted["status"] == "UNDER_REVIEW"
    submit_replay = client.post(
        f"{base}/{decision_id}/submit-for-review",
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-submit-1",
        },
        json={"expected_version": decision["version"]},
    )
    assert submit_replay.json() == submitted

    returned_response = client.post(
        f"{base}/{decision_id}/return",
        headers={
            "X-User-Id": str(ctx.otk.id),
            "Idempotency-Key": "lifecycle-return",
        },
        json={
            "expected_version": submitted["version"],
            "return_reason": "Уточнить формулировку",
        },
    )
    assert returned_response.status_code == 200, returned_response.text
    returned = returned_response.json()
    assert returned["status"] == "DRAFT"
    return_replay = client.post(
        f"{base}/{decision_id}/return",
        headers={
            "X-User-Id": str(ctx.otk.id),
            "Idempotency-Key": "lifecycle-return",
        },
        json={
            "expected_version": submitted["version"],
            "return_reason": "Уточнить формулировку",
        },
    )
    assert return_replay.json() == returned

    updated_response = client.patch(
        f"{base}/{decision_id}/draft",
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-update",
        },
        json={
            "expected_version": returned["version"],
            "summary": "Итоговая редакция",
            "basis_revision_ids": [str(revision.id)],
        },
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    assert updated["summary"] == "Итоговая редакция"
    update_replay = client.patch(
        f"{base}/{decision_id}/draft",
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-update",
        },
        json={
            "expected_version": returned["version"],
            "summary": "Итоговая редакция",
            "basis_revision_ids": [str(revision.id)],
        },
    )
    assert update_replay.json() == updated

    resubmitted_response = client.post(
        f"{base}/{decision_id}/submit-for-review",
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-submit-2",
        },
        json={"expected_version": updated["version"]},
    )
    assert resubmitted_response.status_code == 200, resubmitted_response.text
    resubmitted = resubmitted_response.json()
    resubmit_replay = client.post(
        f"{base}/{decision_id}/submit-for-review",
        headers={
            "X-User-Id": str(ctx.ogs.id),
            "Idempotency-Key": "lifecycle-submit-2",
        },
        json={"expected_version": updated["version"]},
    )
    assert resubmit_replay.json() == resubmitted

    decided_response = client.post(
        f"{base}/{decision_id}/decide",
        headers={
            "X-User-Id": str(ctx.otk.id),
            "Idempotency-Key": "lifecycle-decide",
        },
        json={
            "expected_version": resubmitted["version"],
            "decision_result": "ACCEPTED",
        },
    )
    assert decided_response.status_code == 200, decided_response.text
    decided = decided_response.json()
    assert decided["status"] == "DECIDED"
    assert decided["decision_result"] == "ACCEPTED"
    decide_replay = client.post(
        f"{base}/{decision_id}/decide",
        headers={
            "X-User-Id": str(ctx.otk.id),
            "Idempotency-Key": "lifecycle-decide",
        },
        json={
            "expected_version": resubmitted["version"],
            "decision_result": "ACCEPTED",
        },
    )
    assert decide_replay.json() == decided

    read_response = client.get(
        f"{base}/{decision_id}",
        headers={"X-User-Id": str(ctx.ogs.id)},
    )
    bases_response = client.get(
        f"{base}/{decision_id}/bases",
        headers={"X-User-Id": str(ctx.ogs.id)},
    )
    events_response = client.get(
        f"{base}/{decision_id}/events",
        headers={"X-User-Id": str(ctx.ogs.id)},
    )

    assert read_response.status_code == 200
    assert read_response.json()["status"] == "DECIDED"
    assert bases_response.status_code == 200
    assert len(bases_response.json()) == 1
    assert events_response.status_code == 200
    assert [
        event["event_type"] for event in events_response.json()
    ] == [
        "QUALITY_DECISION_CREATED",
        "QUALITY_DECISION_SUBMITTED",
        "QUALITY_DECISION_RETURNED",
        "QUALITY_DECISION_SUBMITTED",
        "QUALITY_DECISION_DECIDED",
    ]
