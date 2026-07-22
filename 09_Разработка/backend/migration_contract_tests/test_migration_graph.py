"""Pure AST contracts for the active historical migration graph."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
EXPECTED_ROOT = "20260702_02_hr_core"
EXPECTED_HEAD = "20260721_24_disp_supersede"
EXPECTED_REVISION_COUNT = 28


@dataclass(frozen=True)
class RevisionNode:
    path: Path
    revision: str
    parents: tuple[str, ...]


def _assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    if isinstance(node, ast.AnnAssign):
        return node.target.id if isinstance(node.target, ast.Name) else None
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _parse_revision(path: Path) -> RevisionNode:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        name = _assignment_name(node)
        if name in {"revision", "down_revision"}:
            values[name] = ast.literal_eval(node.value)

    revision = values.get("revision")
    down_revision = values.get("down_revision")
    assert isinstance(revision, str), f"{path}: missing static revision id"
    if down_revision is None:
        parents: tuple[str, ...] = ()
    elif isinstance(down_revision, str):
        parents = (down_revision,)
    else:
        assert isinstance(down_revision, (tuple, list)), (
            f"{path}: down_revision must be a static string, sequence, or None"
        )
        assert all(isinstance(parent, str) for parent in down_revision)
        parents = tuple(down_revision)
    return RevisionNode(path, revision, parents)


def _revisions() -> list[RevisionNode]:
    return [_parse_revision(path) for path in sorted(VERSIONS_DIR.glob("*.py"))]


def _assert_acyclic(nodes: dict[str, RevisionNode]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(revision: str) -> None:
        if revision in visiting:
            raise AssertionError(f"migration cycle includes {revision}")
        if revision in visited:
            return
        visiting.add(revision)
        for parent in nodes[revision].parents:
            visit(parent)
        visiting.remove(revision)
        visited.add(revision)

    for revision in nodes:
        visit(revision)


def test_graph_001_has_exactly_one_expected_root() -> None:
    """TEST-B03-GRAPH-001."""
    roots = {node.revision for node in _revisions() if not node.parents}

    assert roots == {EXPECTED_ROOT}


def test_graph_002_has_exactly_one_expected_head() -> None:
    """TEST-B03-GRAPH-002."""
    revisions = _revisions()
    parent_ids = {parent for node in revisions for parent in node.parents}
    heads = {node.revision for node in revisions} - parent_ids

    assert heads == {EXPECTED_HEAD}


def test_graph_003_has_28_unique_revision_ids() -> None:
    """TEST-B03-GRAPH-003."""
    revisions = _revisions()
    revision_ids = [node.revision for node in revisions]

    assert len(revisions) == EXPECTED_REVISION_COUNT
    assert len(revision_ids) == len(set(revision_ids))


def test_graph_004_is_closed_acyclic_and_reachable_from_root() -> None:
    """TEST-B03-GRAPH-004."""
    revisions = _revisions()
    nodes = {node.revision: node for node in revisions}
    missing_parents = {
        parent
        for node in revisions
        for parent in node.parents
        if parent not in nodes
    }
    assert not missing_parents
    _assert_acyclic(nodes)

    children: dict[str, set[str]] = {revision: set() for revision in nodes}
    for node in revisions:
        for parent in node.parents:
            children[parent].add(node.revision)
    reachable: set[str] = set()
    pending = [EXPECTED_ROOT]
    while pending:
        revision = pending.pop()
        if revision not in reachable:
            reachable.add(revision)
            pending.extend(children[revision])

    assert reachable == set(nodes)
