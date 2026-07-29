"""Pure AST contracts for migration offline safety."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


@dataclass(frozen=True, order=True)
class OfflineFinding:
    path: str
    line: int
    call: str
    rule: str

    def diagnostic(self) -> str:
        return f"{self.path}:{self.line}:{self.call}:{self.rule}"


HISTORICAL_OFFLINE_DEBT = frozenset()


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                aliases[local_name] = alias.name if alias.asname else local_name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                aliases[local_name] = f"{node.module}.{alias.name}"
    return aliases


def _qualified_name(node: ast.expr, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value, aliases)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _runtime_rule(call_name: str) -> str | None:
    leaf = call_name.rsplit(".", 1)[-1]
    if call_name in {"op.get_bind", "alembic.op.get_bind"}:
        return "runtime-bind"
    if leaf in {"inspect", "get_inspector"}:
        return "connection-inspection"
    if leaf in {"connect", "exec_driver_sql"}:
        return "runtime-connection"
    if leaf == "execute" and call_name not in {"op.execute", "alembic.op.execute"}:
        return "runtime-execute"
    if leaf in {"scalar", "scalars", "scalar_one", "scalar_one_or_none"}:
        return "runtime-result-read"
    return None


def _scan_source(source: str, path: str) -> list[OfflineFinding]:
    tree = ast.parse(source, filename=path)
    aliases = _import_aliases(tree)
    findings: list[OfflineFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _qualified_name(node.func, {})
        resolved_call_name = _qualified_name(node.func, aliases)
        rule = _runtime_rule(resolved_call_name)
        if rule is not None:
            line = node.end_lineno if rule == "runtime-result-read" else node.lineno
            findings.append(
                OfflineFinding(path, line, call_name, rule)
            )
    return findings


def _migration_path(path: Path) -> str:
    return f"migrations/versions/{path.name}"


def _scan_migrations() -> frozenset[OfflineFinding]:
    return frozenset(
        finding
        for path in sorted(VERSIONS_DIR.glob("*.py"))
        for finding in _scan_source(
            path.read_text(encoding="utf-8"), _migration_path(path)
        )
    )


def test_offline_001_active_graph_has_no_offline_debt() -> None:
    """TEST-B03-OFFLINE-001."""
    actual = _scan_migrations()

    assert actual == HISTORICAL_OFFLINE_DEBT, "\n".join(
        item.diagnostic() for item in sorted(actual ^ HISTORICAL_OFFLINE_DEBT)
    )


def test_offline_002_new_runtime_calls_fail_but_op_execute_is_allowed() -> None:
    """TEST-B03-OFFLINE-002."""
    source = """\
op.execute("CREATE TABLE example (id integer)")
bind = op.get_bind()
bind.execute(statement).scalar_one()
inspector = sa.inspect(bind)
connection.exec_driver_sql("SELECT 1")
"""

    findings = _scan_source(source, "migrations/versions/future.py")

    assert {(item.call, item.rule) for item in findings} == {
        ("op.get_bind", "runtime-bind"),
        ("bind.execute", "runtime-execute"),
        ("scalar_one", "runtime-result-read"),
        ("sa.inspect", "connection-inspection"),
        ("connection.exec_driver_sql", "runtime-connection"),
    }
    assert all(item.call != "op.execute" for item in findings)


def test_offline_003_blocks_alembic_op_alias() -> None:
    """TEST-B03-OFFLINE-003."""
    source = """\
from alembic import op as operations

operations.get_bind()
"""

    findings = _scan_source(source, "migrations/versions/future.py")

    assert {(item.call, item.rule) for item in findings} == {
        ("operations.get_bind", "runtime-bind"),
    }


def test_offline_004_blocks_sqlalchemy_inspect_alias() -> None:
    """TEST-B03-OFFLINE-004."""
    source = """\
from sqlalchemy import inspect as db_inspect

db_inspect(bind)
"""

    findings = _scan_source(source, "migrations/versions/future.py")

    assert {(item.call, item.rule) for item in findings} == {
        ("db_inspect", "connection-inspection"),
    }
