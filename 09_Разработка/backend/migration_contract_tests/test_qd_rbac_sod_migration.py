"""Pure source contract for AS-02 QualityDecision RBAC migration.

The revision is parsed as text/AST and is never imported or executed.
"""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "archive"
    / "canonical_baseline_v1"
    / "revisions"
    / "20260724_27_qd_rbac_sod.py"
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


def test_qd_rbac_sod_revision_contract() -> None:
    assert REVISION_PATH.is_file(), "AS-02 revision 27 is missing"

    source = REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REVISION_PATH))

    assert _literal_assignment(tree, "revision") == "20260724_27_qd_rbac_sod"
    assert _literal_assignment(tree, "down_revision") == (
        "20260724_26_qd_idempotency"
    )

    required_fragments = {
        "review_submitted_by_worker_id",
        "authorization_context",
        "QUALITY_DECISION_SUBMITTED",
        "LEGACY_AUTHORIZATION_SNAPSHOT",
        "ck_quality_decisions_review_submitter_state",
        "ck_quality_audit_qd_authorization_context",
        "jsonb_strip_nulls",
        "new_values ->> 'version'",
        "AS-02 migration cannot prove review submitter",
    }
    missing = sorted(fragment for fragment in required_fragments if fragment not in source)
    assert not missing, f"Revision 27 misses contract fragments: {missing}"

    assert source.count("op.add_column(") == 2
    assert source.count("op.create_check_constraint(") == 2
    assert source.count("op.drop_constraint(") == 2
    assert source.count("op.drop_column(") == 2
    assert "op.execute(" in source
    assert "op.get_bind" not in source
    assert "from app." not in source

