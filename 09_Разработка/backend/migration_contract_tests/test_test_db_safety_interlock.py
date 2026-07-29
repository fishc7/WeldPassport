from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_db_safety import assert_safe_test_database


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFTEST_PATH = BACKEND_ROOT / "tests" / "conftest.py"


@pytest.mark.parametrize(
    ("database_name", "destructive_opt_in", "confirmed_database_name"),
    [
        ("weldpassport_test", None, "weldpassport_test"),
        ("weldpassport_test", "NO", "weldpassport_test"),
        ("weldpassport_test", "YES", None),
        ("weldpassport_test", "YES", "another_test"),
        ("weldpassport_test", "YES", "WeldPassport_Test"),
        ("weldpassport", "YES", "weldpassport"),
        ("postgres", "YES", "postgres"),
        ("weldpassport_dev", "YES", "weldpassport_dev"),
    ],
)
def test_guard_rejects_unsafe_database_selection(
    database_name: str,
    destructive_opt_in: str | None,
    confirmed_database_name: str | None,
) -> None:
    with pytest.raises(pytest.UsageError, match="TEST DB SAFETY"):
        assert_safe_test_database(
            database_name,
            destructive_opt_in=destructive_opt_in,
            confirmed_database_name=confirmed_database_name,
        )


def test_guard_accepts_explicit_test_database() -> None:
    assert_safe_test_database(
        "weldpassport_test",
        destructive_opt_in="YES",
        confirmed_database_name="weldpassport_test",
    )


def test_conftest_orders_interlock_before_migrations_without_import_probe() -> None:
    source = CONFTEST_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_db_available" not in functions
    assert "pytestmark" not in {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    interlock = functions["_test_database_safety_interlock"]
    apply_migrations = functions["_apply_migrations"]

    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "fixture"
        for decorator in interlock.decorator_list
    )
    assert any(
        argument.arg == "_test_database_safety_interlock"
        for argument in apply_migrations.args.args
    )
