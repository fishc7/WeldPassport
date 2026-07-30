"""Pure contracts for the additive identity authentication migration."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260730_28_identity.py"
)
EXPECTED_TABLES = (
    "user_accounts",
    "sessions",
    "authentication_events",
)


def _source() -> str:
    assert MIGRATION_PATH.is_file(), "identity migration is missing"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _static_assignments() -> dict[str, object]:
    tree = ast.parse(_source(), filename=str(MIGRATION_PATH))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = (
            node.target
            if isinstance(node, ast.AnnAssign)
            else node.targets[0]
            if len(node.targets) == 1
            else None
        )
        if isinstance(target, ast.Name) and target.id in {
            "revision",
            "down_revision",
        }:
            values[target.id] = ast.literal_eval(node.value)
    return values


def test_identity_migration_001_extends_canonical_baseline() -> None:
    values = _static_assignments()

    assert values == {
        "revision": "20260730_28_identity",
        "down_revision": "canonical_baseline_v1",
    }


def test_identity_migration_002_is_additive_and_unseeded() -> None:
    source = _source()
    tree = ast.parse(source, filename=str(MIGRATION_PATH))
    created_tables = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
        and node.func.attr == "create_table"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }

    assert 'CREATE SCHEMA "identity"' in source
    assert created_tables == set(EXPECTED_TABLES)
    assert "bulk_insert" not in source
    assert "INSERT INTO" not in source.upper()


def test_identity_migration_003_has_fail_closed_downgrade() -> None:
    source = _source()
    guard = "identity downgrade refused: tables are not empty"

    guard_position = source.index(guard)
    drop_positions = [
        source.index(f'op.drop_table("{table_name}"')
        for table_name in reversed(EXPECTED_TABLES)
    ]
    schema_drop_position = source.index('DROP SCHEMA "identity"')

    assert guard_position < min(drop_positions)
    assert drop_positions == sorted(drop_positions)
    assert max(drop_positions) < schema_drop_position
    for table_name in EXPECTED_TABLES:
        assert f"identity.{table_name}" in source


def test_identity_migration_004_routes_identity_schema() -> None:
    env_source = (BACKEND_DIR / "migrations" / "env.py").read_text(
        encoding="utf-8"
    )
    db_source = (BACKEND_DIR / "app" / "shared" / "db.py").read_text(
        encoding="utf-8"
    )
    compact_env = " ".join(env_source.split())
    compact_db = " ".join(db_source.split())

    assert (
        "identity, project, engineering, hr, welding, quality, public"
        in compact_env
    )
    assert (
        "identity, project, engineering, hr, welding, quality, public"
        in compact_db
    )
