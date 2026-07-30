import ast
from pathlib import Path
import sys

from app.testing.f2_contract import F2Role
from app.testing.f2_role_adapters import build_role_plan


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_f2_governance_001_command_plans_use_python_modules_without_shell() -> None:
    for role in F2Role:
        plan = build_role_plan(role, sys.executable)
        assert plan
        for step in plan:
            if step.argv is None:
                continue
            assert step.argv[0] == sys.executable
            assert step.argv[1] == "-m"
            assert step.argv[2] in {"alembic", "pytest"}
            rendered = " ".join(step.argv).casefold()
            assert "create database" not in rendered
            assert "drop database" not in rendered
            assert "secret" not in rendered


def test_f2_governance_002_runner_sources_have_no_db_lifecycle_or_shell() -> None:
    files = [
        BACKEND_ROOT / "app" / "testing" / name
        for name in (
            "f2_contract.py",
            "f2_evidence.py",
            "f2_preflight.py",
            "f2_process.py",
            "f2_coordinator.py",
            "f2_worker.py",
            "f2_role_adapters.py",
        )
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    folded = combined.casefold()
    for forbidden in (
        "create database",
        "drop database",
        "reset database",
        "rename database",
        "shell=true",
    ):
        assert forbidden not in folded

    for path in files:
        ast.parse(path.read_text(encoding="utf-8"))


def test_f2_governance_003_worker_has_no_eager_db_import() -> None:
    worker_path = BACKEND_ROOT / "app" / "testing" / "f2_worker.py"
    tree = ast.parse(worker_path.read_text(encoding="utf-8"))
    eager_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and "app.shared.db" in ast.unparse(node)
    ]
    assert eager_imports == []

    source = worker_path.read_text(encoding="utf-8")
    run_worker_source = source[source.index("def run_worker("):]
    assert run_worker_source.index("os.chdir(artifact_path.parent)") < (
        run_worker_source.index("_default_dependencies()")
    )
