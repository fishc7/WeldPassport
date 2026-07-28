"""Pure contracts for the B-04A source cut and migration freeze."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.shared.canonical_metadata import (
    CANONICAL_MODEL_MODULES,
    canonical_metadata,
)
from migrations.b04.source_contract import (
    CANONICAL_MODEL_MODULE_COUNT,
    CANONICAL_TABLE_COUNT,
    HISTORICAL_HEAD,
    HISTORICAL_REVISION_COUNT,
    HISTORICAL_ROOT,
    SCHEMA_SOURCE_COMMIT,
)


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RevisionNode:
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
    return RevisionNode(revision=revision, parents=parents)


def _revisions() -> list[RevisionNode]:
    return [_parse_revision(path) for path in sorted(VERSIONS_DIR.glob("*.py"))]


def _source_commit_provenance() -> tuple[tuple[str, ...], str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "show",
            "-s",
            "--format=%P%x00%s",
            SCHEMA_SOURCE_COMMIT,
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    parents, subject = result.stdout.rstrip("\n").split("\x00", maxsplit=1)
    return tuple(parents.split()), subject


def test_b04_cut_001_constants_match_accepted_snapshot() -> None:
    assert SCHEMA_SOURCE_COMMIT == "6c56f99edbd4e7346264ee14658d2076b5fd0775"
    assert len(SCHEMA_SOURCE_COMMIT) == 40
    assert HISTORICAL_ROOT == "20260702_02_hr_core"
    assert HISTORICAL_HEAD == "20260724_27_qd_rbac_sod"
    assert HISTORICAL_REVISION_COUNT == 31


def test_b04_cut_002_source_commit_has_accepted_provenance() -> None:
    parents, subject = _source_commit_provenance()

    assert parents == (
        "24790bc5c3d1b118bf23b76753e4015dc2510541",
        "5a99b96097ed0c3a3bfc7765c7685e2e119a745f",
    )
    assert subject == "Merge pull request #4 from fishc7/codex/test-db-safety"


def test_b04_cut_003_active_graph_matches_accepted_snapshot() -> None:
    revisions = _revisions()
    revision_ids = [node.revision for node in revisions]
    parent_ids = {parent for node in revisions for parent in node.parents}
    roots = {node.revision for node in revisions if not node.parents}
    heads = set(revision_ids) - parent_ids

    assert roots == {HISTORICAL_ROOT}
    assert heads == {HISTORICAL_HEAD}
    assert len(revision_ids) == HISTORICAL_REVISION_COUNT
    assert len(revision_ids) == len(set(revision_ids))


def test_b04_cut_004_canonical_metadata_matches_accepted_snapshot() -> None:
    assert len(CANONICAL_MODEL_MODULES) == CANONICAL_MODEL_MODULE_COUNT
    assert len(canonical_metadata.tables) == CANONICAL_TABLE_COUNT
