"""Static, socket-free contracts for the B-04A candidate Alembic context."""

from __future__ import annotations

import ast
from configparser import ConfigParser
import json
from pathlib import Path
import subprocess
import sys
import textwrap


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_ROOT = BACKEND_ROOT / "migrations"
B04_ROOT = MIGRATIONS_ROOT / "b04"
INI_PATH = B04_ROOT / "candidate_alembic.ini"
ENV_PATH = B04_ROOT / "candidate_context" / "env.py"
TEMPLATE_PATH = B04_ROOT / "candidate_context" / "script.py.mako"
CANDIDATES_DIR = MIGRATIONS_ROOT / "baseline_candidates"
ACTIVE_VERSIONS_DIR = MIGRATIONS_ROOT / "versions"


def _tree() -> ast.Module:
    return ast.parse(ENV_PATH.read_text(encoding="utf-8"), filename=str(ENV_PATH))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _run_isolated_python(source: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_b04_context_001_candidate_ini_has_exact_isolated_locations() -> None:
    parser = ConfigParser()
    parser.read(INI_PATH, encoding="utf-8")

    assert parser.get("alembic", "script_location") == "migrations/b04/candidate_context"
    assert parser.get("alembic", "version_locations") == "migrations/versions"
    assert parser.get("alembic", "path_separator") == "os"
    assert parser.get("alembic", "file_template") == "%(rev)s"
    assert not parser.has_option("alembic", "recursive_version_locations")
    assert ACTIVE_VERSIONS_DIR.is_dir()
    assert (
        ACTIVE_VERSIONS_DIR / "canonical_baseline_v1.py"
    ).is_file()
    assert not list(CANDIDATES_DIR.glob("*.py"))


def test_b04_context_002_uses_only_explicit_b04_environment_contract() -> None:
    source = ENV_PATH.read_text(encoding="utf-8")
    expected = {
        "WELDPASSPORT_B04_DATABASE_URL",
        "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE",
        "WELDPASSPORT_B04_OWNERSHIP_TOKEN",
        "WELDPASSPORT_B04_EXPECTED_DATABASE",
    }

    found = {
        node.value
        for node in ast.walk(_tree())
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("WELDPASSPORT_B04_")
    }
    assert found == expected
    assert ".env" not in {
        node.value
        for node in ast.walk(_tree())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "settings" not in source
    assert "migrations.versions" not in source
    assert "wp_b04_r18_baseline_disposable" in source


def test_b04_context_003_has_no_socket_settings_revision_or_secret_output_paths() -> None:
    tree = _tree()
    imported_modules = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert not any("socket" in module or "dotenv" in module for module in imported_modules)
    assert "app.shared.config" not in imported_modules
    assert "print" not in called_names
    assert "logging" not in imported_modules
    assert "POSTGRES_" not in ENV_PATH.read_text(encoding="utf-8")


def test_b04_context_006_uses_canonical_boundary_and_public_marker_contract() -> None:
    source = ENV_PATH.read_text(encoding="utf-8")
    tree = _tree()

    assert "canonical_metadata" in source
    assert "include_name" in source
    assert "include_object" in source
    assert "make_include_object" in source
    assert "pool.NullPool" in source

    configure_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "configure"
    ]
    assert len(configure_calls) == 2
    for call in configure_calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert isinstance(keywords["include_schemas"], ast.Constant)
        assert keywords["include_schemas"].value is True
        assert isinstance(keywords["version_table_schema"], ast.Constant)
        assert keywords["version_table_schema"].value == "public"
        assert isinstance(keywords["version_table_pk"], ast.Constant)
        assert keywords["version_table_pk"].value is True


def test_b04_context_007_offline_mode_uses_validated_url_without_engine() -> None:
    function = _function(_tree(), "run_migrations_offline")
    source = ast.get_source_segment(ENV_PATH.read_text(encoding="utf-8"), function)

    assert source is not None
    assert "assert_disposable_database" in source
    assert "create_engine" not in source
    assert "context.configure" in source


def test_b04_context_008_template_has_only_candidate_revision_shape() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "revision = ${repr(up_revision)}" in source
    assert "down_revision = ${repr(down_revision)}" in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "migrations.versions" not in source
    assert "from app" not in source


def test_b04_context_009_imports_canonical_metadata_without_runtime_database_stack() -> None:
    result = _run_isolated_python(
        """
        import builtins
        import importlib.abc
        import json
        import sys
        import sqlalchemy
        import sqlalchemy.engine.create

        blocked = {"app.shared.db", "app.shared.config", "dotenv"}
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked:
                raise AssertionError(f"forbidden import: {name}")
            return original_import(name, globals, locals, fromlist, level)

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in blocked:
                    raise AssertionError(f"forbidden module: {fullname}")
                return None

        builtins.__import__ = guarded_import
        sys.meta_path.insert(0, Blocker())
        def forbidden_engine_factory(*args, **kwargs):
            raise AssertionError("canonical metadata must not create an engine")
        sqlalchemy.create_engine = forbidden_engine_factory
        sqlalchemy.engine.create.create_engine = forbidden_engine_factory

        from app.shared import canonical_metadata

        assert len(canonical_metadata.CANONICAL_MODEL_MODULES) == 12
        assert all(name in sys.modules for name in canonical_metadata.CANONICAL_MODEL_MODULES)
        print(json.dumps({"tables": len(canonical_metadata.canonical_metadata.tables)}))
        """
    )

    assert result == {"tables": 73}


def test_b04_context_010_runtime_db_reuses_orm_base_without_creating_an_engine() -> None:
    result = _run_isolated_python(
        """
        import json
        import sys
        import types
        import sqlalchemy

        class FakeEngine:
            pass

        fake_engine = FakeEngine()
        sqlalchemy.create_engine = lambda url: fake_engine
        sqlalchemy.event.listens_for = lambda *args: lambda function: function

        config = types.ModuleType("app.shared.config")
        config.settings = types.SimpleNamespace(
            database_url="postgresql+psycopg://safe:password@host:5432/wp_b04_r18_baseline_disposable",
            postgres_schema="test",
        )
        sys.modules["app.shared.config"] = config

        from app.shared import db, orm

        assert db.Base is orm.Base
        assert db.Base.metadata is orm.Base.metadata
        assert db.engine is fake_engine
        print(json.dumps({"same_base": True, "same_metadata": True}))
        """
    )

    assert result == {"same_base": True, "same_metadata": True}


def test_b04_context_011_executes_online_safety_and_major_checks_in_order() -> None:
    result = _run_isolated_python(
        f"""
        import importlib.util
        import json
        import os
        import sys
        import types
        import sqlalchemy

        events = []
        database_url = "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable"
        os.environ.update({{
            "WELDPASSPORT_B04_DATABASE_URL": database_url,
            "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE": "YES",
            "WELDPASSPORT_B04_OWNERSHIP_TOKEN": "B04-owner-token-2026",
            "WELDPASSPORT_B04_EXPECTED_DATABASE": "wp_b04_r18_baseline_disposable",
        }})

        class Result:
            def scalar_one(self):
                return "180003"

        class Connection:
            def exec_driver_sql(self, statement):
                events.append(["show", statement])
                return Result()
            def commit(self):
                events.append(["commit"])

        connection = Connection()

        class ConnectionContext:
            def __enter__(self):
                events.append(["connect"])
                return connection
            def __exit__(self, *args):
                return False

        class Engine:
            def connect(self):
                return ConnectionContext()

        def create_engine(url, *, poolclass, connect_args):
            events.append(["engine", url, poolclass.__name__, connect_args])
            return Engine()

        inspector_sentinel = object()
        include_object_sentinel = object()

        def inspect(value):
            assert value is connection
            events.append(["inspect"])
            return inspector_sentinel

        sqlalchemy.create_engine = create_engine
        sqlalchemy.inspect = inspect

        import migrations.canonical_boundary as boundary
        def make_include_object(value):
            assert value is inspector_sentinel
            events.append(["make_include_object"])
            return include_object_sentinel
        boundary.make_include_object = make_include_object

        class Transaction:
            def __enter__(self):
                events.append(["begin"])
            def __exit__(self, *args):
                return False

        class Context:
            def is_offline_mode(self):
                return False
            def configure(self, **kwargs):
                from app.shared.canonical_metadata import canonical_metadata
                from migrations.canonical_boundary import include_name
                assert set(kwargs) == {{
                    "connection", "target_metadata", "include_schemas",
                    "version_table_schema", "version_table_pk", "include_name",
                    "include_object",
                }}
                assert kwargs["connection"] is connection
                assert kwargs["target_metadata"] is canonical_metadata
                assert kwargs["include_name"] is include_name
                assert kwargs["include_object"] is include_object_sentinel
                assert kwargs["include_schemas"] is True
                assert kwargs["version_table_schema"] == "public"
                assert kwargs["version_table_pk"] is True
                events.append(["configure"])
            def begin_transaction(self):
                return Transaction()
            def run_migrations(self):
                events.append(["run"])

        alembic = types.ModuleType("alembic")
        alembic.context = Context()
        sys.modules["alembic"] = alembic

        import migrations.b04.disposable as disposable
        original_safety = disposable.assert_disposable_database
        original_version = disposable.assert_postgresql_18

        def safety(*args, **kwargs):
            events.append(["safety", args[0], kwargs["opt_in"], kwargs["expected_database"]])
            return original_safety(*args, **kwargs)

        def version(value):
            events.append(["version"])
            return original_version(value)

        disposable.assert_disposable_database = safety
        disposable.assert_postgresql_18 = version

        spec = importlib.util.spec_from_file_location("candidate_online", r"{ENV_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(json.dumps(events))
        """
    )

    assert result == [
        ["safety", "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable", "YES", "wp_b04_r18_baseline_disposable"],
        ["engine", "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable", "NullPool", {"connect_timeout": 10}],
        ["connect"],
        ["version"],
        ["show", "SHOW server_version_num"],
        ["inspect"],
        ["make_include_object"],
        ["commit"],
        ["configure"],
        ["begin"],
        ["run"],
    ]


def test_b04_context_011a_does_not_commit_when_include_object_preflight_fails() -> None:
    result = _run_isolated_python(
        f"""
        import importlib.util
        import json
        import os
        import sys
        import types
        import sqlalchemy

        events = []
        database_url = "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable"
        os.environ.update({{
            "WELDPASSPORT_B04_DATABASE_URL": database_url,
            "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE": "YES",
            "WELDPASSPORT_B04_OWNERSHIP_TOKEN": "B04-owner-token-2026",
            "WELDPASSPORT_B04_EXPECTED_DATABASE": "wp_b04_r18_baseline_disposable",
        }})

        class Result:
            def scalar_one(self):
                return "180003"

        class Connection:
            def exec_driver_sql(self, statement):
                events.append(["show", statement])
                return Result()
            def commit(self):
                events.append(["commit"])

        connection = Connection()

        class ConnectionContext:
            def __enter__(self):
                events.append(["connect"])
                return connection
            def __exit__(self, *args):
                return False

        class Engine:
            def connect(self):
                return ConnectionContext()

        def create_engine(url, *, poolclass, connect_args):
            events.append(["engine", url, poolclass.__name__, connect_args])
            return Engine()

        def inspect(value):
            assert value is connection
            events.append(["inspect"])
            return object()

        sqlalchemy.create_engine = create_engine
        sqlalchemy.inspect = inspect

        import migrations.canonical_boundary as boundary
        def make_include_object(value):
            events.append(["make_include_object"])
            raise RuntimeError("preflight failed")
        boundary.make_include_object = make_include_object

        class Context:
            def is_offline_mode(self):
                return False
            def configure(self, **kwargs):
                events.append(["configure"])
            def begin_transaction(self):
                events.append(["begin"])
                raise AssertionError("Alembic transaction must not start after failed preflight")
            def run_migrations(self):
                events.append(["run"])

        alembic = types.ModuleType("alembic")
        alembic.context = Context()
        sys.modules["alembic"] = alembic

        spec = importlib.util.spec_from_file_location("candidate_online", r"{ENV_PATH}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except RuntimeError as error:
            assert str(error) == "preflight failed"
        else:
            raise AssertionError("failed preflight must propagate")

        print(json.dumps(events))
        """
    )

    assert result == [
        ["engine", "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable", "NullPool", {"connect_timeout": 10}],
        ["connect"],
        ["show", "SHOW server_version_num"],
        ["inspect"],
        ["make_include_object"],
    ]


def test_b04_context_012_executes_offline_with_validated_url_and_no_engine() -> None:
    result = _run_isolated_python(
        f"""
        import importlib.util
        import json
        import os
        import sys
        import types
        import sqlalchemy

        events = []
        database_url = "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable"
        os.environ.update({{
            "WELDPASSPORT_B04_DATABASE_URL": database_url,
            "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE": "YES",
            "WELDPASSPORT_B04_OWNERSHIP_TOKEN": "B04-owner-token-2026",
            "WELDPASSPORT_B04_EXPECTED_DATABASE": "wp_b04_r18_baseline_disposable",
        }})
        sqlalchemy.create_engine = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("engine forbidden"))

        import migrations.canonical_boundary as boundary
        include_object_sentinel = object()
        boundary.include_object = include_object_sentinel

        class Transaction:
            def __enter__(self):
                events.append(["begin"])
            def __exit__(self, *args):
                return False

        class Context:
            def is_offline_mode(self):
                return True
            def configure(self, **kwargs):
                from app.shared.canonical_metadata import canonical_metadata
                from migrations.canonical_boundary import include_name
                assert set(kwargs) == {{
                    "url", "target_metadata", "literal_binds", "dialect_opts",
                    "include_schemas", "version_table_schema", "version_table_pk",
                    "include_name", "include_object",
                }}
                assert kwargs["url"] == database_url
                assert kwargs["target_metadata"] is canonical_metadata
                assert kwargs["include_name"] is include_name
                assert kwargs["include_object"] is include_object_sentinel
                assert kwargs["literal_binds"] is True
                assert kwargs["dialect_opts"] == {{"paramstyle": "named"}}
                assert kwargs["include_schemas"] is True
                assert kwargs["version_table_schema"] == "public"
                assert kwargs["version_table_pk"] is True
                events.append(["configure"])
            def begin_transaction(self):
                return Transaction()
            def run_migrations(self):
                events.append(["run"])

        alembic = types.ModuleType("alembic")
        alembic.context = Context()
        sys.modules["alembic"] = alembic

        import migrations.b04.disposable as disposable
        original_safety = disposable.assert_disposable_database

        def safety(*args, **kwargs):
            events.append(["safety", args[0], kwargs["opt_in"], kwargs["expected_database"]])
            return original_safety(*args, **kwargs)

        disposable.assert_disposable_database = safety

        spec = importlib.util.spec_from_file_location("candidate_offline", r"{ENV_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(json.dumps(events))
        """
    )

    assert result == [
        ["safety", "postgresql+psycopg://runner:password@127.0.0.1:5432/wp_b04_r18_baseline_disposable", "YES", "wp_b04_r18_baseline_disposable"],
        ["configure"],
        ["begin"],
        ["run"],
    ]


def test_b04_context_013_template_renders_imports_and_postgresql_specific_body() -> None:
    from mako.template import Template

    rendered = Template(filename=str(TEMPLATE_PATH)).render(
        message="candidate",
        imports="from sqlalchemy.dialects import postgresql",
        up_revision="canonical_baseline_v1",
        down_revision=None,
        branch_labels=None,
        depends_on=None,
        upgrades="op.create_table('example', sa.Column('id', postgresql.UUID(as_uuid=True)))",
        downgrades="op.drop_table('example')",
    )

    assert "from sqlalchemy.dialects import postgresql" in rendered
    assert "postgresql.UUID(as_uuid=True)" in rendered
    ast.parse(rendered)
