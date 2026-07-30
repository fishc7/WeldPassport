import ast
from pathlib import Path

from app.testing.f2_operator_preflight import F2OperatorPreflightStatus


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_MODULE = (
    BACKEND_ROOT / "app" / "testing" / "f2_operator_preflight.py"
)
PREFLIGHT_CLI = (
    BACKEND_ROOT / "scripts" / "run_test_db_f2_operator_preflight.py"
)


def _trees() -> tuple[ast.Module, ...]:
    return tuple(
        ast.parse(path.read_text(encoding="utf-8"))
        for path in (PREFLIGHT_MODULE, PREFLIGHT_CLI)
    )


def test_f2_operator_governance_001_has_no_operational_imports_or_calls() -> None:
    forbidden_imports = {
        "alembic",
        "app.main",
        "app.shared.db",
        "socket",
    }
    forbidden_calls = {
        "connect",
        "create_engine",
        "getaddrinfo",
        "run_worker",
    }

    for tree in _trees():
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        calls = {
            (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        assert imports.isdisjoint(forbidden_imports)
        assert calls.isdisjoint(forbidden_calls)


def test_f2_operator_governance_002_subprocess_is_shell_false() -> None:
    tree = ast.parse(PREFLIGHT_MODULE.read_text(encoding="utf-8"))
    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
    ]

    assert len(subprocess_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in subprocess_calls[0].keywords}
    assert isinstance(keywords["shell"], ast.Constant)
    assert keywords["shell"].value is False
    assert isinstance(keywords["check"], ast.Constant)
    assert keywords["check"].value is False


def test_f2_operator_governance_003_produces_only_preflight_statuses() -> None:
    assert set(F2OperatorPreflightStatus) == {
        F2OperatorPreflightStatus.READY,
        F2OperatorPreflightStatus.FAILED,
        F2OperatorPreflightStatus.EVIDENCE_FAILED,
    }
