"""Static isolation contract for the B-04 historical replay context."""

from __future__ import annotations

import ast
from pathlib import Path

from migrations.b04.verify_baseline import VerificationConfig


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND_ROOT / "migrations" / "b04" / "historical_alembic.ini"
CONTEXT_PATH = BACKEND_ROOT / "migrations" / "b04" / "historical_context" / "env.py"


def _import_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None


def test_b04_historical_context_001_is_isolated_to_frozen_history_and_test_marker() -> None:
    assert VerificationConfig.__dataclass_fields__["historical_alembic_ini"].default == Path(
        "migrations/b04/historical_alembic.ini"
    )
    config = CONFIG_PATH.read_text(encoding="utf-8")
    assert "script_location = migrations/b04/historical_context" in config
    assert (
        "version_locations = "
        "migrations/archive/canonical_baseline_v1/revisions"
    ) in config
    assert "path_separator = os" in config

    tree = ast.parse(CONTEXT_PATH.read_text(encoding="utf-8"))
    imports = {_import_name(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
    assert imports <= {"__future__", "os", "alembic", "sqlalchemy"}
    assert all(not (name or "").startswith(("app", "migrations")) for name in imports)
    source = CONTEXT_PATH.read_text(encoding="utf-8")
    for name in (
        "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_SCHEMA",
    ):
        assert name in source
    assert "version_table_schema=\"test\"" in source
    assert "SET search_path TO test, project, engineering, hr, welding, quality, public" in source
    assert "dotenv" not in source
    assert "load_dotenv" not in source


def test_b04_historical_context_002_bootstraps_test_schema_once_before_configuring_alembic() -> None:
    tree = ast.parse(CONTEXT_PATH.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_bootstrap_test_schema")
    isolated = ast.Module(body=[function], type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(ast.fix_missing_locations(isolated), str(CONTEXT_PATH), "exec"), namespace)
    bootstrap = namespace["_bootstrap_test_schema"]

    class Connection:
        def __init__(self, fail: bool = False) -> None:
            self.events: list[str] = []
            self.fail = fail

        def exec_driver_sql(self, statement: str) -> None:
            self.events.append(statement)
            if self.fail:
                raise RuntimeError("already exists")

        def commit(self) -> None:
            self.events.append("COMMIT")

    connection = Connection()
    bootstrap(connection)
    assert connection.events == ['CREATE SCHEMA "test"', "COMMIT"]

    existing = Connection(fail=True)
    try:
        bootstrap(existing)
    except RuntimeError:
        pass
    else:
        raise AssertionError("existing test schema must fail closed")
    assert existing.events == ['CREATE SCHEMA "test"']

    online = CONTEXT_PATH.read_text(encoding="utf-8").split("def run_migrations_online", 1)[1]
    assert online.index("_bootstrap_test_schema(connection)") < online.index("context.configure(")


def test_b04_historical_context_003_online_engine_has_a_ten_second_connect_timeout() -> None:
    tree = ast.parse(CONTEXT_PATH.read_text(encoding="utf-8"), filename=str(CONTEXT_PATH))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_migrations_online")
    engine_call = next(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_engine"
    )
    keywords = {keyword.arg: keyword.value for keyword in engine_call.keywords}

    assert isinstance(keywords["connect_args"], ast.Dict)
    assert ast.literal_eval(keywords["connect_args"]) == {"connect_timeout": 10}
