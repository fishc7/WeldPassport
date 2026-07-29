"""Pure AST contracts for imports used by historical migrations."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
ALLOWED_IMPORT_ROOTS = frozenset(
    set(sys.stdlib_module_names) | {"__future__", "alembic", "sqlalchemy"}
)


@dataclass(frozen=True, order=True)
class ImportFinding:
    path: str
    line: int
    module: str
    rule: str

    def diagnostic(self) -> str:
        return f"{self.path}:{self.line}:{self.module}:{self.rule}"


# Историческое исключение принято осознанно и не должно расширяться.
HISTORICAL_IMPORT_DEBT = frozenset(
    {
        ImportFinding(
            "migrations/versions/20260713_14_heat_treatment.py",
            26,
            "app.engineering.heat_treatment_workflow",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260713_15_inspection_core.py",
            28,
            "app.quality.inspection_workflow",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260713_16_method_assignments.py",
            36,
            "app.quality.method_assignment_workflow",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260719_19_quality_finding_core.py",
            30,
            "app.quality.quality_finding_workflow",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260719_20_eng_evaluation_core.py",
            29,
            "app.quality.engineering_evaluation_workflow",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260720_21_defect_model.py",
            27,
            "app.quality.defect_seed",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260720_21_defect_model.py",
            28,
            "app.quality.defect_workflow",
            "forbidden-runtime-import",
        ),
        ImportFinding(
            "migrations/versions/20260721_22_defect_dispositions.py",
            29,
            "app.quality.defect_disposition_models",
            "forbidden-runtime-import",
        ),
    }
)


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


def _dynamic_import_module(
    node: ast.Call, aliases: dict[str, str]
) -> str | None:
    is_dunder_import = isinstance(node.func, ast.Name) and node.func.id == "__import__"
    is_importlib = _qualified_name(node.func, aliases) == "importlib.import_module"
    if not (is_dunder_import or is_importlib):
        return None
    if node.args and isinstance(node.args[0], ast.Constant):
        return str(node.args[0].value)
    return "<dynamic>"


def _scan_source(source: str, path: str) -> list[ImportFinding]:
    findings: list[ImportFinding] = []
    tree = ast.parse(source, filename=path)
    aliases = _import_aliases(tree)

    for node in ast.walk(tree):
        imports: list[tuple[str, str]] = []
        if isinstance(node, ast.Import):
            imports = [(alias.name, "") for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                imports = [(f"{'.' * node.level}{module}", "relative-import")]
            else:
                imports = [(module, "")]
        elif isinstance(node, ast.Call):
            module = _dynamic_import_module(node, aliases)
            if module is not None:
                findings.append(
                    ImportFinding(path, node.lineno, module, "dynamic-import")
                )

        for module, preset_rule in imports:
            root = module.lstrip(".").split(".", 1)[0]
            if preset_rule:
                rule = preset_rule
            elif root in {"app", "migrations"}:
                rule = "forbidden-runtime-import"
            elif root not in ALLOWED_IMPORT_ROOTS:
                rule = "unknown-import-root"
            else:
                continue
            findings.append(ImportFinding(path, node.lineno, module, rule))

    return findings


def _migration_path(path: Path) -> str:
    return f"migrations/versions/{path.name}"


def _scan_migrations() -> frozenset[ImportFinding]:
    return frozenset(
        finding
        for path in sorted(VERSIONS_DIR.glob("*.py"))
        for finding in _scan_source(
            path.read_text(encoding="utf-8"), _migration_path(path)
        )
    )


def test_import_001_blocks_forbidden_and_unknown_import_forms() -> None:
    """TEST-B03-IMPORT-001."""
    source = """\
import app.services as services
from migrations import helpers
from .local import helper
import requests
import importlib
__import__("app.dynamic")
importlib.import_module("sqlalchemy")
from sqlalchemy.dialects import postgresql
from alembic import op
from typing import Sequence
"""

    findings = _scan_source(source, "migrations/versions/future.py")

    assert {(item.module, item.rule) for item in findings} == {
        ("app.services", "forbidden-runtime-import"),
        ("migrations", "forbidden-runtime-import"),
        (".local", "relative-import"),
        ("requests", "unknown-import-root"),
        ("app.dynamic", "dynamic-import"),
        ("sqlalchemy", "dynamic-import"),
    }


def test_import_002_diagnostic_contains_path_line_module_and_rule() -> None:
    """TEST-B03-IMPORT-002."""
    finding = _scan_source(
        "from app.quality import runtime\n",
        "migrations/versions/future.py",
    )[0]

    assert finding.diagnostic() == (
        "migrations/versions/future.py:1:app.quality:forbidden-runtime-import"
    )


def test_import_003_historical_debt_is_exactly_seven_files_eight_statements() -> None:
    """TEST-B03-IMPORT-003."""
    actual = _scan_migrations()

    assert actual == HISTORICAL_IMPORT_DEBT, "\n".join(
        item.diagnostic() for item in sorted(actual ^ HISTORICAL_IMPORT_DEBT)
    )
    assert len(actual) == 8
    assert len({item.path for item in actual}) == 7


def test_import_004_blocks_importlib_module_alias() -> None:
    """TEST-B03-IMPORT-004."""
    source = """\
import importlib as il

il.import_module("app.runtime")
"""

    findings = _scan_source(source, "migrations/versions/future.py")

    assert {(item.module, item.rule) for item in findings} == {
        ("app.runtime", "dynamic-import"),
    }


def test_import_005_blocks_import_module_symbol_alias() -> None:
    """TEST-B03-IMPORT-005."""
    source = """\
from importlib import import_module

import_module("app.runtime")
"""

    findings = _scan_source(source, "migrations/versions/future.py")

    assert {(item.module, item.rule) for item in findings} == {
        ("app.runtime", "dynamic-import"),
    }
