from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_ROOT / "migrations" / "env.py"


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_alembic_env_uses_one_bound_target_for_offline_and_online_urls() -> None:
    tree = ast.parse(ENV_PATH.read_text(encoding="utf-8"))
    assignments = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    target_assignment = assignments["database_target"]
    assert isinstance(target_assignment, ast.Call)
    assert _call_name(target_assignment) == "get_or_bind_working_target"

    database_url_assignment = assignments["database_url"]
    assert isinstance(database_url_assignment, ast.Call)
    assert _call_name(database_url_assignment) == "render_as_string"
    assert isinstance(database_url_assignment.func, ast.Attribute)
    assert isinstance(database_url_assignment.func.value, ast.Attribute)
    assert database_url_assignment.func.value.attr == "url"
    assert isinstance(database_url_assignment.func.value.value, ast.Name)
    assert database_url_assignment.func.value.value.id == "database_target"

    set_url_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _call_name(node) == "set_main_option"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "sqlalchemy.url"
    ]
    assert len(set_url_calls) == 1
    assert isinstance(set_url_calls[0].args[1], ast.Call)
    assert _call_name(set_url_calls[0].args[1]) == "replace"
    assert isinstance(set_url_calls[0].args[1].func, ast.Attribute)
    assert isinstance(set_url_calls[0].args[1].func.value, ast.Name)
    assert set_url_calls[0].args[1].func.value.id == "database_url"

    engine_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "create_engine"
    ]
    assert len(engine_calls) == 1
    assert isinstance(engine_calls[0].args[0], ast.Name)
    assert engine_calls[0].args[0].id == "database_url"


def test_alembic_target_routing_preserves_canonical_boundary() -> None:
    source = ENV_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "TEST_DATABASE_URL" not in source
    assert "create_database" not in source

    configure_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "configure"
    ]
    assert len(configure_calls) == 2
    for call in configure_calls:
        keywords = {item.arg: item.value for item in call.keywords}
        assert isinstance(keywords["version_table_schema"], ast.Constant)
        assert keywords["version_table_schema"].value == "public"
        assert isinstance(keywords["version_table_pk"], ast.Constant)
        assert keywords["version_table_pk"].value is True
        assert isinstance(keywords["include_schemas"], ast.Constant)
        assert keywords["include_schemas"].value is True

    assert "canonical_metadata" in source
    assert "include_name" in source
    assert "include_object" in source
