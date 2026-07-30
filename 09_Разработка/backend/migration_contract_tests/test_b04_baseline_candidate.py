"""Closed pure-AST allowlist for the isolated B-04 baseline candidate."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.shared.canonical_metadata import canonical_metadata
from migrations.b04.seeds import EXPECTED_DEFECT_LOCATION_TYPES, EXPECTED_DEFECT_TYPES
from migrations.b04.source_contract import BASELINE_REVISION, CANONICAL_TABLE_COUNT


BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "canonical_baseline_v1.py"
)
CANONICAL_SCHEMAS = ("hr", "welding", "project", "engineering", "quality")
EXPECTED_TABLES = tuple(
    (table.schema, table.name)
    for table in canonical_metadata.sorted_tables
    if table.schema in CANONICAL_SCHEMAS
)
EXPECTED_INDEXES = tuple(
    (table.schema, table.name, index.name)
    for table in canonical_metadata.sorted_tables
    if table.schema in CANONICAL_SCHEMAS
    for index in sorted(table.indexes, key=lambda item: item.name or "")
)
_CREATE_SCHEMAS = tuple(f'CREATE SCHEMA "{schema}"' for schema in CANONICAL_SCHEMAS)
_DROP_SCHEMAS = tuple(f'DROP SCHEMA "{schema}"' for schema in reversed(CANONICAL_SCHEMAS))
_GOVERNED_INDEX = """
CREATE UNIQUE INDEX uq_hr_worker_roles_active_scope
ON "hr".worker_roles (worker_id, role_code, scope_type, COALESCE(scope_id, ''))
WHERE is_active = true
"""
_NONCANONICAL_REFERENCE = re.compile(r'(?i)(?<![A-Za-z0-9_])(?:"(?:public|test)"|public|test)\s*\.')
_CONSTRUCTORS = {
    "sa.Boolean", "sa.CheckConstraint", "sa.Column", "sa.Date", "sa.DateTime", "sa.ForeignKey",
    "sa.ForeignKeyConstraint", "sa.Integer", "sa.Numeric", "sa.PrimaryKeyConstraint", "sa.String", "sa.Text",
    "sa.UniqueConstraint", "sa.column", "sa.table", "sa.text",
    "postgresql.ARRAY", "postgresql.JSONB", "postgresql.UUID",
}
_HISTORICAL_COLUMN_ORDER = {
    ("engineering", "joints"): (
        "id",
        "project_id",
        "line_id",
        "origin_document_revision_id",
        "current_document_revision_id",
        "system_code",
        "joint_no",
        "joint_no_normalized",
        "status",
        "record_version",
        "dn_1",
        "dn_2",
        "thickness_1",
        "thickness_2",
        "material_id_1",
        "material_id_2",
        "material_text_1",
        "material_text_2",
        "component_type_1",
        "component_type_2",
        "component_item_id_1",
        "component_item_id_2",
        "component_text_1",
        "component_text_2",
        "geometry_type",
        "weld_joint_type",
        "connection_code",
        "required_root_method",
        "required_fill_method",
        "required_cap_method",
        "planned_wps_id",
        "heat_treatment_required",
        "heat_treatment_type",
        "heat_treatment_note",
        "sheet_no",
        "drawing_zone",
        "position_x",
        "position_y",
        "coordinate_system",
        "location_note",
        "document_note",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
        "approval_version",
        "workflow_version",
        "pto_status",
        "pto_pending_reason",
        "pto_decision_method",
        "pto_approval_version",
        "pto_decided_by",
        "pto_decided_at",
        "pto_comment",
        "ogs_status",
        "ogs_pending_reason",
        "ogs_decision_method",
        "ogs_approval_version",
        "ogs_decided_by",
        "ogs_decided_at",
        "ogs_comment",
        "submitted_by",
        "submitted_at",
        "cancelled_reason",
        "cancelled_by",
        "cancelled_at",
        "superseded_by_joint_id",
        "superseded_by",
        "superseded_at",
    ),
    ("quality", "laboratory_conclusions"): (
        "id",
        "project_id",
        "laboratory_company_id",
        "inspection_method_id",
        "root_conclusion_id",
        "revision_no",
        "supersedes_conclusion_id",
        "is_current",
        "external_revision_label",
        "correction_reason",
        "conclusion_number",
        "conclusion_year",
        "issued_at",
        "request_reference",
        "request_date",
        "requesting_company_id",
        "laboratory_accreditation_id",
        "laboratory_name_snapshot",
        "accreditation_number_snapshot",
        "accreditation_valid_from_snapshot",
        "accreditation_valid_until_snapshot",
        "accreditation_scope_snapshot",
        "lab_approver_person_id",
        "issued_by_person_id",
        "source_type",
        "source_reference",
        "source_received_at",
        "status",
        "lab_approved_by_worker_id",
        "lab_approved_at",
        "registered_by_worker_id",
        "registered_at",
        "cancellation_reason",
        "cancelled_by_worker_id",
        "cancelled_at",
        "revision_review_required",
        "revision_review_reason",
        "created_by_worker_id",
        "created_at",
        "updated_by_worker_id",
        "updated_at",
        "version",
        "normalized_conclusion_number",
    ),
    ("quality", "quality_audit_events"): (
        "id",
        "entity_type",
        "entity_id",
        "event_type",
        "changed_fields",
        "previous_values",
        "new_values",
        "reason",
        "actor_worker_id",
        "occurred_at",
        "authorization_context",
    ),
    ("quality", "quality_decisions"): (
        "id",
        "project_id",
        "joint_id",
        "system_code",
        "status",
        "decision_result",
        "summary",
        "return_reason",
        "supersedes_quality_decision_id",
        "created_by_worker_id",
        "created_at",
        "approved_by_worker_id",
        "approved_at",
        "approved_role",
        "version",
        "review_submitted_by_worker_id",
    ),
}
_HISTORICAL_SERVER_DEFAULTS = {
    ("hr", "departments", "is_active"): "true",
    ("hr", "positions", "is_active"): "true",
    ("hr", "worker_roles", "is_active"): "true",
    ("hr", "workers", "employment_status"): "active",
    ("welding", "welder_admissions", "admission_status"): "draft",
    ("welding", "welders", "status"): "active",
}
_JOINT_SELF_FK_NAME = "fk_engineering_joints_superseded_by_joint"


def _normal_sql(value: str) -> str:
    return " ".join(value.split())


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _literal_string(node: ast.AST) -> str:
    assert isinstance(node, ast.Constant) and isinstance(node.value, str), "B04-CANDIDATE-NONLITERAL-STRING"
    return node.value


def _keyword_literal(call: ast.Call, name: str) -> str:
    values = [keyword.value for keyword in call.keywords if keyword.arg == name]
    assert len(values) == 1, f"B04-CANDIDATE-MISSING-{name.upper()}"
    return _literal_string(values[0])


def _parse() -> ast.Module:
    return ast.parse(
        BASELINE_PATH.read_text(encoding="utf-8"),
        filename=str(BASELINE_PATH),
    )


def _assignment(node: ast.AST) -> tuple[str, object] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, ast.literal_eval(node.value)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, ast.literal_eval(node.value)
    return None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(functions) == 1, f"B04-CANDIDATE-{name.upper()}-FUNCTION"
    assert not functions[0].decorator_list and not functions[0].args.args and not functions[0].args.kwonlyargs
    return functions[0]


def _assert_top_level(tree: ast.Module) -> None:
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body.pop(0)
    imports: list[ast.AST] = []
    while body and isinstance(body[0], (ast.Import, ast.ImportFrom)):
        imports.append(body.pop(0))
    seen: set[str] = set()
    for node in imports:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            assert [(alias.name, alias.asname) for alias in node.names] == [("annotations", None)]
            seen.add("future")
        elif isinstance(node, ast.ImportFrom) and node.module == "typing":
            assert [(alias.name, alias.asname) for alias in node.names] == [("Sequence", None), ("Union", None)]
            seen.add("typing")
        elif isinstance(node, ast.ImportFrom) and node.module == "alembic":
            assert [(alias.name, alias.asname) for alias in node.names] == [("op", None)]
            seen.add("alembic")
        elif isinstance(node, ast.Import):
            assert [(alias.name, alias.asname) for alias in node.names] == [("sqlalchemy", "sa")]
            seen.add("sqlalchemy")
        elif isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy.dialects":
            assert [(alias.name, alias.asname) for alias in node.names] == [("postgresql", None)]
            seen.add("postgresql")
        else:
            raise AssertionError("B04-CANDIDATE-IMPORT-ALLOWLIST")
    assert {"future", "alembic", "sqlalchemy"} <= seen
    assert len(imports) == len(seen), "B04-CANDIDATE-DUPLICATE-IMPORT"
    assignments = [_assignment(node) for node in body[:4]]
    assert all(item is not None for item in assignments) and len(assignments) == 4, "B04-CANDIDATE-REVISION-ASSIGNMENTS"
    assert dict(item for item in assignments if item is not None) == {
        "revision": BASELINE_REVISION, "down_revision": None, "branch_labels": None, "depends_on": None,
    }
    assert [node.name for node in body[4:] if isinstance(node, ast.FunctionDef)] == ["upgrade", "downgrade"]
    assert len(body[4:]) == 2 and all(isinstance(node, ast.FunctionDef) for node in body[4:]), "B04-CANDIDATE-TOPLEVEL"


def _assert_static_value(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        return
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            _assert_static_value(element)
        return
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            assert key is not None, "B04-CANDIDATE-DYNAMIC-DICT"
            _assert_static_value(key)
            _assert_static_value(value)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        _assert_static_value(node.operand)
        return
    if isinstance(node, ast.Call):
        assert _name(node.func) in _CONSTRUCTORS, f"B04-CANDIDATE-CONSTRUCTOR:{_name(node.func)}"
        for argument in node.args:
            _assert_static_value(argument)
        for keyword in node.keywords:
            assert keyword.arg is not None, "B04-CANDIDATE-DYNAMIC-KEYWORD"
            _assert_static_value(keyword.value)
        return
    raise AssertionError(f"B04-CANDIDATE-DYNAMIC-VALUE:{type(node).__name__}")


def _direct_ops(function: ast.FunctionDef, allowed: set[str]) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for statement in function.body:
        assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call), "B04-CANDIDATE-NONDIRECT-OP"
        call = statement.value
        assert _name(call.func) in allowed, "B04-CANDIDATE-UNKNOWN-OP"
        for argument in call.args:
            _assert_static_value(argument)
        for keyword in call.keywords:
            assert keyword.arg is not None, "B04-CANDIDATE-DYNAMIC-KEYWORD"
            _assert_static_value(keyword.value)
        calls.append(call)
    all_ops = [node for node in ast.walk(function) if isinstance(node, ast.Call) and (_name(node.func) or "").startswith("op.")]
    assert all_ops == calls, "B04-CANDIDATE-NESTED-OP"
    for call in ast.walk(function):
        if isinstance(call, ast.Call) and call not in calls:
            _assert_static_value(call)
    return calls


def _execute(call: ast.Call) -> str:
    assert len(call.args) == 1 and not call.keywords, "B04-CANDIDATE-EXECUTE-SHAPE"
    value = call.args[0]
    if isinstance(value, ast.Call):
        assert _name(value.func) == "sa.text" and len(value.args) == 1 and not value.keywords, "B04-CANDIDATE-EXECUTE-DYNAMIC"
        value = value.args[0]
    return _literal_string(value)


def _bulk_insert(call: ast.Call) -> tuple[tuple[str, str], list[dict[object, object]]]:
    assert len(call.args) == 2 and not call.keywords and isinstance(call.args[0], ast.Call), "B04-CANDIDATE-BULK-INSERT-SHAPE"
    table = call.args[0]
    assert _name(table.func) == "sa.table" and table.args, "B04-CANDIDATE-BULK-INSERT-TABLE"
    assert isinstance(call.args[1], ast.List), "B04-CANDIDATE-BULK-INSERT-ROWS"
    rows = [ast.literal_eval(row) for row in call.args[1].elts]
    assert all(isinstance(row, dict) for row in rows), "B04-CANDIDATE-BULK-INSERT-ROWS"
    return (_keyword_literal(table, "schema"), _literal_string(table.args[0])), rows


def _seed_table_columns(call: ast.Call) -> tuple[tuple[str, str], ...]:
    table = call.args[0]
    assert isinstance(table, ast.Call) and _name(table.func) == "sa.table"
    columns: list[tuple[str, str]] = []
    for column in table.args[1:]:
        assert isinstance(column, ast.Call) and _name(column.func) == "sa.column" and len(column.args) == 2 and not column.keywords, "B04-CANDIDATE-SEED-COLUMN-SHAPE"
        assert isinstance(column.args[1], ast.Call), "B04-CANDIDATE-SEED-COLUMN-TYPE"
        columns.append((_literal_string(column.args[0]), _name(column.args[1].func) or ""))
    return tuple(columns)


def _table_target(call: ast.Call) -> tuple[str, str]:
    return _keyword_literal(call, "schema"), _literal_string(call.args[0])


def _index_target(call: ast.Call, *, drop: bool) -> tuple[str, str, str]:
    return _keyword_literal(call, "schema"), _keyword_literal(call, "table_name") if drop else _literal_string(call.args[1]), _literal_string(call.args[0])


def _create_tables(tree: ast.Module) -> dict[tuple[str, str], ast.Call]:
    calls = _direct_ops(
        _function(tree, "upgrade"),
        {"op.execute", "op.create_table", "op.create_index", "op.bulk_insert"},
    )
    tables = {
        _table_target(call): call
        for call in calls
        if _name(call.func) == "op.create_table"
    }
    assert len(tables) == CANONICAL_TABLE_COUNT, "B04-CANDIDATE-DUPLICATE-TABLE"
    return tables


def _columns(table: ast.Call) -> tuple[ast.Call, ...]:
    return tuple(
        argument
        for argument in table.args[1:]
        if isinstance(argument, ast.Call) and _name(argument.func) == "sa.Column"
    )


def _column(table: ast.Call, name: str) -> ast.Call:
    matches = [
        column
        for column in _columns(table)
        if _literal_string(column.args[0]) == name
    ]
    assert len(matches) == 1, f"B04-CANDIDATE-COLUMN:{name}"
    return matches[0]


def _optional_keyword_literal_string(call: ast.Call, name: str) -> str | None:
    values = [keyword.value for keyword in call.keywords if keyword.arg == name]
    assert len(values) <= 1, f"B04-CANDIDATE-DUPLICATE-{name.upper()}"
    return _literal_string(values[0]) if values else None


def test_b04_candidate_000_active_baseline_exists_before_ast_contracts() -> None:
    assert len(EXPECTED_TABLES) == CANONICAL_TABLE_COUNT == 73
    assert BASELINE_PATH.is_file(), (
        "B04-BASELINE-ABSENT: canonical_baseline_v1.py must be active"
    )


def test_b04_candidate_001_has_only_exact_top_level_and_static_constructors() -> None:
    tree = _parse()
    _assert_top_level(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not _NONCANONICAL_REFERENCE.search(node.value), "B04-CANDIDATE-NONCANONICAL-REFERENCE"


def test_b04_candidate_002_upgrade_has_exact_order_and_frozen_literals() -> None:
    calls = _direct_ops(_function(_parse(), "upgrade"), {"op.execute", "op.create_table", "op.create_index", "op.bulk_insert"})
    assert [_name(call.func) for call in calls[:5]] == ["op.execute"] * 5
    assert [_normal_sql(_execute(call)) for call in calls[:5]] == [_normal_sql(sql) for sql in _CREATE_SCHEMAS]
    tables = [_table_target(call) for call in calls if _name(call.func) == "op.create_table"]
    assert tuple(tables) == EXPECTED_TABLES, "B04-CANDIDATE-TABLE-ORDER"
    indexes = [_index_target(call, drop=False) for call in calls if _name(call.func) == "op.create_index"]
    assert tuple(indexes) == EXPECTED_INDEXES, "B04-CANDIDATE-INDEXES"
    positions = {_table_target(call): index for index, call in enumerate(calls) if _name(call.func) == "op.create_table"}
    assert all(positions[_index_target(call, drop=False)[:2]] < index for index, call in enumerate(calls) if _name(call.func) == "op.create_index"), "B04-CANDIDATE-INDEX-ORDER"
    governed = [index for index, call in enumerate(calls) if _name(call.func) == "op.execute" and index >= 5]
    assert len(governed) == 1 and _normal_sql(_execute(calls[governed[0]])) == _normal_sql(_GOVERNED_INDEX), "B04-CANDIDATE-GOVERNED-INDEX"
    assert governed[0] == len(calls) - 3, "B04-CANDIDATE-GOVERNED-INDEX-ORDER"
    assert all(_name(call.func) in {"op.create_table", "op.create_index"} for call in calls[5:governed[0]])
    inserts = [_bulk_insert(call) for call in calls if _name(call.func) == "op.bulk_insert"]
    seed_calls = [call for call in calls if _name(call.func) == "op.bulk_insert"]
    assert calls[-2:] == [call for call in calls if _name(call.func) == "op.bulk_insert"], "B04-CANDIDATE-SEEDS-NOT-FINAL"
    assert inserts == [(("quality", "defect_types"), [dict(row) for row in EXPECTED_DEFECT_TYPES]), (("quality", "defect_location_types"), [dict(row) for row in EXPECTED_DEFECT_LOCATION_TYPES])]
    assert _seed_table_columns(seed_calls[0]) == (
        ("id", "postgresql.UUID"), ("code", "sa.String"), ("name", "sa.String"),
        ("category", "sa.String"), ("requires_length", "sa.Boolean"),
        ("requires_width", "sa.Boolean"), ("requires_height", "sa.Boolean"),
        ("requires_depth", "sa.Boolean"), ("requires_area", "sa.Boolean"),
        ("requires_quantity", "sa.Boolean"),
        ("requires_known_indication_location", "sa.Boolean"), ("requires_description", "sa.Boolean"),
    ), "B04-CANDIDATE-DEFECT-TYPE-SEED-COLUMNS"
    assert _seed_table_columns(seed_calls[1]) == (
        ("id", "postgresql.UUID"), ("code", "sa.String"), ("name", "sa.String"),
    ), "B04-CANDIDATE-DEFECT-LOCATION-SEED-COLUMNS"
    assert len([node for node in ast.walk(_function(_parse(), "upgrade")) if isinstance(node, ast.Dict)]) == 15, "B04-CANDIDATE-DEAD-SEEDS"


def test_b04_candidate_003_downgrade_has_exact_reverse_operation_sequence() -> None:
    tree = _parse()
    upgrade = _direct_ops(_function(tree, "upgrade"), {"op.execute", "op.create_table", "op.create_index", "op.bulk_insert"})
    calls = _direct_ops(_function(tree, "downgrade"), {"op.execute", "op.drop_index", "op.drop_table"})
    indexes_by_table: dict[tuple[str, str], list[str]] = {}
    for schema, table, name in (_index_target(call, drop=False) for call in upgrade if _name(call.func) == "op.create_index"):
        indexes_by_table.setdefault((schema, table), []).append(name)
    expected: list[tuple[str, object]] = []
    for schema, table in reversed(EXPECTED_TABLES):
        if (schema, table) == ("hr", "worker_roles"):
            expected.append(("op.drop_index", ("hr", "worker_roles", "uq_hr_worker_roles_active_scope")))
        expected.extend(("op.drop_index", (schema, table, name)) for name in reversed(indexes_by_table.get((schema, table), [])))
        expected.append(("op.drop_table", (schema, table)))
    expected.extend(("op.execute", _normal_sql(sql)) for sql in _DROP_SCHEMAS)
    actual: list[tuple[str, object]] = []
    for call in calls:
        operation = _name(call.func)
        if operation == "op.drop_index": actual.append((operation, _index_target(call, drop=True)))
        elif operation == "op.drop_table": actual.append((operation, _table_target(call)))
        else: actual.append((operation, _normal_sql(_execute(call))))
    assert actual == expected, "B04-CANDIDATE-DOWNGRADE-SEQUENCE"
    dropped = [value for operation, value in actual if operation == "op.drop_index"]
    assert len(dropped) == len(set(dropped)), "B04-CANDIDATE-DUPLICATE-DROP-INDEX"


def test_b04_candidate_004_has_no_op_calls_outside_the_two_allowed_functions() -> None:
    tree = _parse()
    allowed = set(ast.walk(_function(tree, "upgrade"))) | set(ast.walk(_function(tree, "downgrade")))
    assert all(node in allowed for node in ast.walk(tree) if isinstance(node, ast.Call) and (_name(node.func) or "").startswith("op."))


@pytest.mark.parametrize(("target", "expected"), _HISTORICAL_COLUMN_ORDER.items())
def test_b04_candidate_005_preserves_historical_column_order(
    target: tuple[str, str],
    expected: tuple[str, ...],
) -> None:
    table = _create_tables(_parse())[target]

    assert tuple(_literal_string(column.args[0]) for column in _columns(table)) == expected


@pytest.mark.parametrize(
    ("schema", "table_name", "column_name", "expected"),
    tuple((*target, expected) for target, expected in _HISTORICAL_SERVER_DEFAULTS.items()),
)
def test_b04_candidate_006_preserves_historical_server_default(
    schema: str,
    table_name: str,
    column_name: str,
    expected: str,
) -> None:
    table = _create_tables(_parse())[(schema, table_name)]

    assert _optional_keyword_literal_string(_column(table, column_name), "server_default") == expected


def test_b04_candidate_007_preserves_named_joint_self_foreign_key() -> None:
    table = _create_tables(_parse())[("engineering", "joints")]
    matches = [
        constraint
        for constraint in table.args[1:]
        if (
            isinstance(constraint, ast.Call)
            and _name(constraint.func) == "sa.ForeignKeyConstraint"
            and len(constraint.args) >= 2
            and ast.literal_eval(constraint.args[0]) == ["superseded_by_joint_id"]
            and ast.literal_eval(constraint.args[1]) == ["engineering.joints.id"]
        )
    ]

    assert len(matches) == 1, "B04-CANDIDATE-JOINT-SELF-FK"
    assert _optional_keyword_literal_string(matches[0], "name") == _JOINT_SELF_FK_NAME
