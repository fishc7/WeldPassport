"""Pure contract for Task 10A-1R idempotency migration.

The test parses the revision as source and never imports or executes migration code.
"""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "20260724_26_qd_idempotency.py"
)


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        target_name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            target_name = target.id if isinstance(target, ast.Name) else None
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target_name = node.target.id if isinstance(node.target, ast.Name) else None
            value = node.value
        if target_name == name and value is not None:
            return ast.literal_eval(value)
    raise AssertionError(f"Assignment {name!r} not found")


def test_qd_idempotency_revision_contract() -> None:
    assert REVISION_PATH.is_file(), "Task 10A-1R revision 26 is missing"

    source = REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REVISION_PATH))

    assert _literal_assignment(tree, "revision") == "20260724_26_qd_idempotency"
    assert _literal_assignment(tree, "down_revision") == "20260723_25_qd_core"

    required_fragments = {
        "quality_decision_idempotency_records",
        "actor_worker_id",
        "command_type",
        "target_type",
        "target_id",
        "idempotency_key",
        "request_hash",
        "quality_decision_id",
        "response_status",
        "response_snapshot",
        "created_at",
        "ck_qd_idem_command_type",
        "ck_qd_idem_target_type",
        "ck_qd_idem_key_not_empty",
        "ck_qd_idem_response_status",
        "uq_qd_idem_command_target_key",
        "ix_qd_idem_quality_decision_id",
    }
    missing = sorted(fragment for fragment in required_fragments if fragment not in source)
    assert not missing, f"Revision 26 misses contract fragments: {missing}"

    assert "op.create_table(" in source
    assert "op.drop_table(" in source
    assert "postgresql.JSONB" in source
    assert "ondelete=\"CASCADE\"" in source
    assert "from app." not in source

