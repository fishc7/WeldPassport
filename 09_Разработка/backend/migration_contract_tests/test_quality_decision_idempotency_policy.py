"""Pure tests for Task 10A Q-D5 idempotency policy."""

from __future__ import annotations

from uuid import UUID

from app.quality import quality_decision_workflow as qdw


def test_idempotency_key_is_required_trimmed_and_bounded() -> None:
    assert qdw.validate_idempotency_key(None) == qdw.QD_IDEMPOTENCY_KEY_REQUIRED
    assert qdw.validate_idempotency_key("   ") == qdw.QD_IDEMPOTENCY_KEY_REQUIRED
    assert (
        qdw.validate_idempotency_key("x" * 256)
        == qdw.QD_IDEMPOTENCY_KEY_INVALID
    )
    assert qdw.validate_idempotency_key("  request-1  ") is None
    assert qdw.normalize_idempotency_key("  request-1  ") == "request-1"


def test_request_hash_is_stable_and_sorts_basis_ids() -> None:
    target = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    basis_a = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    basis_b = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    first = qdw.idempotency_request_hash(
        command=qdw.ACTION_CREATE,
        target_type=qdw.IDEMPOTENCY_TARGET_JOINT,
        target_id=target,
        actor_worker_id=17,
        payload={
            "summary": "Решение",
            "basis_revision_ids": [basis_b, basis_a],
        },
    )
    second = qdw.idempotency_request_hash(
        command=qdw.ACTION_CREATE,
        target_type=qdw.IDEMPOTENCY_TARGET_JOINT,
        target_id=target,
        actor_worker_id=17,
        payload={
            "basis_revision_ids": [basis_a, basis_b],
            "summary": "Решение",
        },
    )

    assert first == second
    assert len(first) == 64


def test_request_hash_changes_for_actor_command_target_or_payload() -> None:
    target = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    base = {
        "command": qdw.ACTION_UPDATE_DRAFT,
        "target_type": qdw.IDEMPOTENCY_TARGET_QUALITY_DECISION,
        "target_id": target,
        "actor_worker_id": 17,
        "payload": {"summary": "A", "expected_version": 1},
    }
    original = qdw.idempotency_request_hash(**base)

    for changed in (
        {**base, "actor_worker_id": 18},
        {**base, "command": qdw.ACTION_SUBMIT_FOR_REVIEW},
        {**base, "target_id": UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")},
        {**base, "payload": {"summary": "B", "expected_version": 1}},
        {**base, "payload": {"summary": "A", "expected_version": 2}},
    ):
        assert qdw.idempotency_request_hash(**changed) != original

