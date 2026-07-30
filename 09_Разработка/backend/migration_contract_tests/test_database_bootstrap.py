from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.shared.database_bootstrap import DatabaseTargetRegistry
from app.shared.database_target import (
    DatabasePurpose,
    DatabaseTargetError,
    authorize_test_database,
    parse_database_target,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFTEST_PATH = BACKEND_ROOT / "tests" / "conftest.py"
WORKING_URL = (
    "postgresql+psycopg://worker:working-secret@work-db.example/weldpassport"
)
TEST_URL = (
    "postgresql+psycopg://tester:test-secret@test-db.example/wp_test_run_001"
)


def _target(purpose: DatabasePurpose, url: str):
    return parse_database_target(url, purpose)


def test_registry_binds_exactly_one_target() -> None:
    registry = DatabaseTargetRegistry()
    target = _target(DatabasePurpose.TEST, TEST_URL)

    assert registry.bind(target) is target
    assert registry.require_bound() is target

    with pytest.raises(DatabaseTargetError) as caught:
        registry.bind(target)

    assert caught.value.code == "DATABASE-TARGET-ALREADY-BOUND"


def test_registry_rejects_a_different_second_target() -> None:
    registry = DatabaseTargetRegistry()
    registry.bind(_target(DatabasePurpose.TEST, TEST_URL))

    with pytest.raises(DatabaseTargetError) as caught:
        registry.bind(_target(DatabasePurpose.WORKING, WORKING_URL))

    assert caught.value.code == "DATABASE-TARGET-ALREADY-BOUND"


def test_registry_requires_a_bound_target() -> None:
    registry = DatabaseTargetRegistry()

    with pytest.raises(DatabaseTargetError) as caught:
        registry.require_bound()

    assert caught.value.code == "DATABASE-TARGET-NOT-BOUND"


def test_registry_get_or_bind_working_is_stable_after_first_call() -> None:
    registry = DatabaseTargetRegistry()

    first = registry.get_or_bind_working(WORKING_URL)
    second = registry.get_or_bind_working(
        "postgresql+psycopg://other:secret@another.example/another_db"
    )

    assert first is second
    assert first.purpose is DatabasePurpose.WORKING
    assert first.database_name == "weldpassport"


def _run_python(script: str, extra_environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(extra_environment)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_db_import_binds_working_target_before_engine_creation() -> None:
    result = _run_python(
        "\n".join(
            [
                "from app.shared.db import database_target, engine",
                "print(database_target.purpose.value)",
                "print(engine.url.database)",
            ]
        ),
        {
            "POSTGRES_HOST": "work-db.example",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "weldpassport",
            "POSTGRES_USER": "worker",
            "POSTGRES_PASSWORD": "working-secret",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["working", "weldpassport"]
    assert "working-secret" not in result.stderr


def test_prebound_test_target_controls_engine_without_connecting() -> None:
    script = "\n".join(
        [
            "from app.shared.database_bootstrap import bind_database_target",
            "from app.shared.database_target import authorize_test_database",
            "authorization = authorize_test_database(",
            f"    test_database_url={TEST_URL!r},",
            f"    working_database_url={WORKING_URL!r},",
            "    destructive_opt_in='YES',",
            "    confirmed_database_name='wp_test_run_001',",
            "    ownership_token='owner-token',",
            ")",
            "bind_database_target(authorization.target)",
            "from app.shared.db import database_target, engine",
            "print(database_target.purpose.value)",
            "print(engine.url.database)",
        ]
    )

    result = _run_python(
        script,
        {
            "POSTGRES_HOST": "unused.example",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "unused",
            "POSTGRES_USER": "unused",
            "POSTGRES_PASSWORD": "unused",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["test", "wp_test_run_001"]
    for forbidden in ("working-secret", "test-secret", "owner-token"):
        assert forbidden not in result.stderr


def test_conftest_import_binds_test_target_before_application_imports() -> None:
    result = _run_python(
        "\n".join(
            [
                "import tests.conftest as conftest",
                "from app.shared.db import database_target",
                "print(database_target.purpose.value)",
                "print(database_target.database_name)",
                "print(conftest.TEST_DATABASE_AUTHORIZATION.target.database_name)",
            ]
        ),
        {
            "POSTGRES_HOST": "work-db.example",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "weldpassport",
            "POSTGRES_USER": "worker",
            "POSTGRES_PASSWORD": "working-secret",
            "TEST_DATABASE_URL": TEST_URL,
            "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
            "WELDPASSPORT_TEST_DB_CONFIRM": "wp_test_run_001",
            "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN": "owner-token",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "test",
        "wp_test_run_001",
        "wp_test_run_001",
    ]


def test_conftest_missing_test_url_fails_before_db_module_import() -> None:
    script = "\n".join(
        [
            "import sys",
            "import pytest",
            "try:",
            "    import tests.conftest",
            "except pytest.UsageError as exc:",
            "    print(str(exc).split(':', 1)[0])",
            "    print('app.shared.db' in sys.modules)",
            "else:",
            "    raise AssertionError('conftest import unexpectedly succeeded')",
        ]
    )
    environment = {
        "POSTGRES_HOST": "work-db.example",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "weldpassport",
        "POSTGRES_USER": "worker",
        "POSTGRES_PASSWORD": "working-secret",
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
        "WELDPASSPORT_TEST_DB_CONFIRM": "wp_test_run_001",
        "WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN": "owner-token",
    }
    inherited = os.environ.pop("TEST_DATABASE_URL", None)
    try:
        result = _run_python(script, environment)
    finally:
        if inherited is not None:
            os.environ["TEST_DATABASE_URL"] = inherited

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["TEST-DB-URL-MISSING", "False"]


def test_live_ownership_fixture_is_a_dependency_of_alembic_fixture() -> None:
    tree = ast.parse(CONFTEST_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    live_fixture = functions["_verify_test_database_ownership"]
    migration_fixture = functions["_apply_migrations"]

    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "fixture"
        for decorator in live_fixture.decorator_list
    )
    assert any(
        argument.arg == "_verify_test_database_ownership"
        for argument in migration_fixture.args.args
    )
