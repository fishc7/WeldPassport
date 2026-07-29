"""Pure, strict B-04 PostgreSQL 18 fingerprint-v2 contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from migrations.b04.fingerprint import (
    CANONICAL_SCHEMAS,
    FINGERPRINT_FORMAT_VERSION,
    FingerprintError,
    SUPPORTED_POSTGRES_MAJOR,
    assert_supported_catalog,
    canonicalize_fingerprint,
    extract_fingerprint,
    fingerprint_digest,
    normalize_deparsed_expression,
)
from migrations.b04.seeds import seed_manifest


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


class _RowsResult:
    def __init__(self, rows: list[Mapping[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> _RowsResult:
        return self

    def all(self) -> list[Mapping[str, object]]:
        return self.rows


class StrictFakeConnection:
    """A route-exact catalog fixture: unmatched, duplicate, and unused routes fail."""

    def __init__(self, routes: Mapping[str, list[Mapping[str, object]]], *, version: str = "180003") -> None:
        self.routes = {key: list(value) for key, value in routes.items()}
        self.version = version
        self.used: list[str] = []
        self.statements: dict[str, str] = {}

    def exec_driver_sql(self, statement: str) -> _ScalarResult:
        assert statement == "SHOW server_version_num"
        return _ScalarResult(self.version)

    def execute(self, statement: object, params: Mapping[str, object]) -> _RowsResult:
        sql = str(statement)
        route = next((key for key in self.routes if f"b04:{key}" in sql), None)
        if route is None or route in self.used:
            raise AssertionError(f"unexpected or duplicate catalog query: {sql}")
        assert params == {"schemas": list(CANONICAL_SCHEMAS)}
        self.used.append(route)
        self.statements[route] = sql
        return _RowsResult(self.routes[route])

    def assert_consumed(self) -> None:
        assert set(self.used) == set(self.routes)


def _base_routes() -> dict[str, list[Mapping[str, object]]]:
    seeds = seed_manifest()["tables"]
    return {
        "namespaces": [{"name": schema} for schema in reversed(CANONICAL_SCHEMAS)],
        "classes": [
            {"schema": "hr", "name": "workers", "kind": "r", "rls": False, "force_rls": False, "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_table": None, "partition_key": None, "bound": None},
            {"schema": "hr", "name": "workers_pkey", "kind": "i", "rls": False, "force_rls": False, "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_table": None, "partition_key": None, "bound": None},
            {"schema": "hr", "name": "worker_id_seq", "kind": "S", "rls": False, "force_rls": False, "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_table": None, "partition_key": None, "bound": None},
        ],
        "columns": [
            {"schema": "hr", "table": "workers", "ordinal": 1, "name": "id", "format_type": "bigint", "nullable": False, "collation": None, "default": " nextval('hr.worker_id_seq'::regclass) ", "identity": "a", "generated": ""},
            {"schema": "hr", "table": "workers", "ordinal": 2, "name": "manager_id", "format_type": "uuid", "nullable": True, "collation": None, "default": None, "identity": "", "generated": ""},
        ],
        "constraints": [
            {"schema": "hr", "table": "workers", "name": "workers_id_not_null", "kind": "n", "columns": ["id"], "target_schema": None, "target_table": None, "target_columns": [], "match_type": None, "update_action": None, "delete_action": None, "deferrable": False, "deferred": False, "validated": True, "enforced": True, "nulls_not_distinct": False, "definition": "NOT NULL id", "no_inherit": False},
            {"schema": "hr", "table": "workers", "name": "workers_pkey", "kind": "p", "columns": ["id"], "target_schema": None, "target_table": None, "target_columns": [], "match_type": None, "update_action": None, "delete_action": None, "deferrable": False, "deferred": False, "validated": True, "enforced": True, "nulls_not_distinct": False, "definition": "PRIMARY KEY (id)", "no_inherit": False},
            {"schema": "hr", "table": "workers", "name": "workers_manager_key", "kind": "u", "columns": ["manager_id"], "target_schema": None, "target_table": None, "target_columns": [], "match_type": None, "update_action": None, "delete_action": None, "deferrable": True, "deferred": True, "validated": True, "enforced": True, "nulls_not_distinct": True, "definition": "UNIQUE NULLS NOT DISTINCT (manager_id)", "no_inherit": False},
            {"schema": "hr", "table": "workers", "name": "workers_manager_fkey", "kind": "f", "columns": ["manager_id"], "target_schema": "hr", "target_table": "workers", "target_columns": ["id"], "match_type": "s", "update_action": "a", "delete_action": "n", "deferrable": True, "deferred": False, "validated": True, "enforced": True, "nulls_not_distinct": False, "definition": "FOREIGN KEY (manager_id) REFERENCES hr.workers(id)", "no_inherit": False},
            {"schema": "hr", "table": "workers", "name": "workers_manager_second_fkey", "kind": "f", "columns": ["manager_id"], "target_schema": "hr", "target_table": "workers", "target_columns": ["id"], "match_type": "s", "update_action": "a", "delete_action": "n", "deferrable": True, "deferred": False, "validated": True, "enforced": True, "nulls_not_distinct": False, "definition": "FOREIGN KEY (manager_id) REFERENCES hr.workers(id)", "no_inherit": False},
            {"schema": "hr", "table": "workers", "name": "workers_id_check", "kind": "c", "columns": [], "target_schema": None, "target_table": None, "target_columns": [], "match_type": None, "update_action": None, "delete_action": None, "deferrable": False, "deferred": False, "validated": True, "enforced": True, "nulls_not_distinct": False, "definition": "CHECK ( id <> '00000000-0000-0000-0000-000000000000'::uuid )", "no_inherit": True},
        ],
        "indexes": [
            {"schema": "hr", "table": "workers", "name": "workers_pkey", "kind": "i", "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_name": None, "method": "btree", "keys": [" id "], "key_columns": ["id"], "include": [], "unique": True, "nulls_not_distinct": False, "predicate": None, "valid": True, "ready": True, "backing_constraint": "workers_pkey"},
            {"schema": "hr", "table": "workers", "name": "workers_manager_key", "kind": "i", "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_name": None, "method": "btree", "keys": [" manager_id "], "key_columns": ["manager_id"], "include": [], "unique": True, "nulls_not_distinct": True, "predicate": None, "valid": True, "ready": True, "backing_constraint": "workers_manager_key"},
            {"schema": "hr", "table": "workers", "name": "workers_manager_expression_ix", "kind": "i", "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_name": None, "method": "btree", "keys": [" manager_id :: text "], "key_columns": [None], "include": [" id "], "unique": False, "nulls_not_distinct": False, "predicate": " manager_id IS NOT NULL ", "valid": True, "ready": True, "backing_constraint": None},
        ],
        "sequences": [
            {"schema": "hr", "name": "standalone_seq", "numeric_type": "bigint", "start": 1, "minimum": 1, "maximum": 9223372036854775807, "increment": 1, "cache": 1, "cycle": False, "owned_schema": None, "owned_table": None, "owned_column": None, "identity_kind": ""},
            {"schema": "hr", "name": "worker_id_seq", "numeric_type": "bigint", "start": 1, "minimum": 1, "maximum": 9223372036854775807, "increment": 1, "cache": 1, "cycle": False, "owned_schema": "hr", "owned_table": "workers", "owned_column": "id", "identity_kind": "a"},
        ],
        "triggers": [],
        "policies": [],
        "routines": [],
        "types": [],
        "defect_types": list(reversed(seeds[0]["rows"])),
        "defect_location_types": list(reversed(seeds[1]["rows"])),
    }


def _extract(routes: Mapping[str, list[Mapping[str, object]]], *, version: str = "180003") -> tuple[dict[str, object], StrictFakeConnection]:
    connection = StrictFakeConnection(routes, version=version)
    value = extract_fingerprint(connection)  # type: ignore[arg-type]
    connection.assert_consumed()
    return value, connection


def test_b04_r18_fingerprint_001_emits_v2_on_postgresql_18() -> None:
    value, _ = _extract(_base_routes(), version="180003")

    assert FINGERPRINT_FORMAT_VERSION == 2
    assert SUPPORTED_POSTGRES_MAJOR == 18
    assert value["format_version"] == 2


def test_b04_r18_fingerprint_002_rejects_pg16() -> None:
    with pytest.raises(FingerprintError, match="B04-FP-POSTGRES-MAJOR"):
        _extract(_base_routes(), version="160014")


def test_b04_r18_fingerprint_003_is_deterministic_for_named_collection_order() -> None:
    value, _ = _extract(_base_routes())
    reordered = json.loads(json.dumps(value))
    reordered["sequences"].reverse()
    for key in ("not_nulls", "primary_keys_uniques", "foreign_keys", "checks", "indexes"):
        reordered["tables"][0][key].reverse()

    assert canonicalize_fingerprint(reordered) == canonicalize_fingerprint(value)


def test_b04_r18_fingerprint_004_is_canonicalization_idempotent() -> None:
    value, _ = _extract(_base_routes())
    canonical = canonicalize_fingerprint(value)

    assert canonicalize_fingerprint(json.loads(canonical)) == canonical


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  a  = 'two   spaces'  ", "a = 'two   spaces'"),
        (r" E'a\\\'  x'  ||  \"kept  id\" ", r"E'a\\\'  x' || \"kept  id\""),
        (" $tag$ keep   this $tag$  :: text ", "$tag$ keep   this $tag$ :: text"),
        ("a  -- keep   comment\n  + b", "a -- keep   comment\n+ b"),
        ("a /* outer /* inner */ keep */  + b", "a /* outer /* inner */ keep */ + b"),
    ],
)
def test_b04_fp_001_normalizes_only_safe_whitespace(source: str, expected: str) -> None:
    assert normalize_deparsed_expression(source) == expected


@pytest.mark.parametrize("source", ["'unclosed", '"unclosed', "$$unclosed", "/* unclosed"])
def test_b04_fp_002_expression_lexer_fails_closed_when_unclosed(source: str) -> None:
    with pytest.raises(FingerprintError, match="B04-FP-EXPRESSION"):
        normalize_deparsed_expression(source)


def test_b04_fp_003_digest_sorts_only_named_collections_and_keeps_semantic_order() -> None:
    left, _ = _extract(_base_routes())
    right = dict(left)
    right["tables"] = list(reversed(left["tables"]))
    assert fingerprint_digest(left) == fingerprint_digest(right)
    changed = dict(left)
    converted = dict(left["tables"][0], kind="p", partition_key="RANGE (id)")
    converted["indexes"] = [dict(index, kind="I") for index in converted["indexes"]]
    changed["tables"] = [converted]
    assert fingerprint_digest(left) != fingerprint_digest(changed)
    changed_index = dict(left)
    table = dict(left["tables"][0])
    table["indexes"] = [dict(index, predicate="manager_id IS NULL") if index["name"] == "workers_manager_expression_ix" else dict(index) for index in table["indexes"]]
    changed_index["tables"] = [table]
    assert fingerprint_digest(left) != fingerprint_digest(changed_index)


def test_b04_fp_004_realistic_fixture_assembles_constraints_indexes_and_sequences() -> None:
    fingerprint, connection = _extract(_base_routes())
    table = fingerprint["tables"][0]
    assert table["kind"] == "r"
    assert {item["kind"] for item in table["primary_keys_uniques"]} == {"p", "u"}
    assert table["foreign_keys"][0]["target_schema"] == "hr"
    assert table["checks"][0]["no_inherit"] is True
    expression_index = next(item for item in table["indexes"] if item["name"] == "workers_manager_expression_ix")
    assert expression_index["keys"] == ["manager_id :: text"]
    assert expression_index["key_columns"] == [None]
    assert expression_index["include"] == ["id"]
    assert [row["name"] for row in fingerprint["sequences"]] == ["standalone_seq", "worker_id_seq"]
    assert fingerprint["sequences"][1]["owned_by"] == {"schema": "hr", "table": "workers", "column": "id"}
    for route, sql in connection.statements.items():
        assert f"b04:{route}" in sql
    assert "con.connullsnotdistinct" not in connection.statements["constraints"]
    assert "ix.indnullsnotdistinct" in connection.statements["constraints"]
    assert "d.classid = 'pg_class'::regclass" in connection.statements["sequences"]
    assert "d.refobjsubid > 0" in connection.statements["sequences"]
    assert "COALESCE(oa.attidentity,'')" in connection.statements["sequences"]
    assert "con.contype IN ('p','u')" in connection.statements["indexes"]
    assert "con.conindid=ix.indexrelid AND con.conrelid=ix.indrelid" in connection.statements["indexes"]


@pytest.mark.parametrize("kind", ["v", "m", "f", "c", "x"])
def test_b04_fp_005_pg_class_fails_closed_for_unsupported_relation_kind(kind: str) -> None:
    routes = _base_routes()
    routes["classes"][0] = {"schema": "hr", "name": "unsupported", "kind": kind, "rls": False, "force_rls": False}
    with pytest.raises(FingerprintError, match="B04-FP-UNSUPPORTED-RELKIND"):
        _extract(routes)


@pytest.mark.parametrize(
    ("route", "row"),
    [
        ("triggers", {"schema": "hr", "table": "workers", "name": "user_trigger"}),
        ("policies", {"schema": "hr", "table": "workers", "name": "worker_policy"}),
        ("routines", {"schema": "hr", "name": "do_work", "kind": "f"}),
        ("routines", {"schema": "hr", "name": "do_work", "kind": "p"}),
        ("types", {"schema": "hr", "name": "worker_state", "kind": "e"}),
        ("types", {"schema": "hr", "name": "worker_domain", "kind": "d"}),
    ],
)
def test_b04_fp_006_typed_unsupported_objects_fail_closed(route: str, row: Mapping[str, object]) -> None:
    routes = _base_routes()
    routes[route] = [row]
    with pytest.raises(FingerprintError, match="B04-FP-UNSUPPORTED-OBJECT"):
        _extract(routes)


def test_b04_fp_007_internal_trigger_and_automatic_types_are_not_reported_as_unsupported() -> None:
    fingerprint, _ = _extract(_base_routes())
    assert fingerprint["tables"][0]["name"] == "workers"


def test_b04_fp_008_seed_comparison_is_order_independent_but_rejects_duplicate_extra_missing_and_drift() -> None:
    assert _extract(_base_routes())[0]["seeds"] == seed_manifest()
    for mutation in ("duplicate", "extra", "missing", "drift"):
        routes = _base_routes()
        rows = routes["defect_types"]
        if mutation == "duplicate":
            rows[-1] = rows[0]
        elif mutation == "extra":
            rows.append(dict(rows[0], code="EXTRA"))
        elif mutation == "missing":
            rows.pop()
        else:
            rows[0] = dict(rows[0], name="drift")
        with pytest.raises(FingerprintError, match="B04-FP-SEED-DRIFT"):
            _extract(routes)


def test_b04_fp_009_rejects_duplicate_sequence_ownership_and_catalog_shape_errors() -> None:
    routes = _base_routes()
    routes["sequences"].append(dict(routes["sequences"][1]))
    with pytest.raises(FingerprintError, match="B04-FP-SEQUENCE-OWNERSHIP"):
        _extract(routes)
    fingerprint, _ = _extract(_base_routes())
    bad = dict(fingerprint)
    bad["schemas"] = []
    with pytest.raises(FingerprintError, match="B04-FP-SCHEMAS"):
        assert_supported_catalog(bad)
    bad = dict(fingerprint)
    bad["unknown"] = True
    with pytest.raises(FingerprintError, match="B04-FP-UNKNOWN"):
        assert_supported_catalog(bad)
    bad = dict(fingerprint)
    bad["tables"] = [dict(fingerprint["tables"][0], columns=[dict(fingerprint["tables"][0]["columns"][0], ordinal=True)])]
    with pytest.raises(FingerprintError, match="B04-FP-COLUMN"):
        canonicalize_fingerprint(bad)


def test_b04_fp_010_queries_are_fixed_and_parameterized_with_required_catalog_contracts() -> None:
    _, connection = _extract(_base_routes())
    query_text = "\n".join(connection.statements.values())
    for catalog in ("pg_namespace", "pg_class", "pg_inherits", "pg_attribute", "pg_constraint", "pg_index", "pg_sequence", "pg_depend", "pg_trigger", "pg_policy", "pg_proc", "pg_type"):
        assert catalog in query_text
    for function in ("pg_get_expr", "pg_get_constraintdef", "pg_get_indexdef"):
        assert function in query_text
    assert ":schemas" in query_text
    assert "NOT t.tgisinternal" in connection.statements["triggers"]
    assert "t.typrelid=0 AND t.typelem=0" in connection.statements["types"]


def test_b04_fp_011_namespace_set_is_exact_and_standalone_sequence_is_coalesced() -> None:
    routes = _base_routes()
    routes["namespaces"] = routes["namespaces"][:-1]
    with pytest.raises(FingerprintError, match="B04-FP-SCHEMAS"):
        _extract(routes)
    routes = _base_routes()
    routes["namespaces"].append({"name": "public"})
    with pytest.raises(FingerprintError, match="B04-FP-SCHEMAS"):
        _extract(routes)
    routes = _base_routes()
    routes["namespaces"][0] = {"name": CANONICAL_SCHEMAS[0]}
    with pytest.raises(FingerprintError, match="B04-FP-SCHEMAS"):
        _extract(routes)
    value, _ = _extract(_base_routes())
    assert value["sequences"][0]["identity_kind"] == ""


def test_b04_fp_012_partition_and_partitioned_index_semantics_change_digest() -> None:
    routes = _base_routes()
    routes["classes"].append({"schema": "hr", "name": "workers_2026", "kind": "r", "rls": False, "force_rls": False, "is_partition": True, "detach_pending": False, "parent_schema": "hr", "parent_table": "workers", "partition_key": None, "bound": " FOR VALUES FROM (1) TO (2) "})
    routes["columns"].append({"schema": "hr", "table": "workers_2026", "ordinal": 1, "name": "id", "format_type": "bigint", "nullable": False, "collation": None, "default": None, "identity": "", "generated": ""})
    routes["constraints"].append(dict(routes["constraints"][0], table="workers_2026", name="workers_2026_id_not_null"))
    routes["classes"][0] = dict(routes["classes"][0], kind="p", partition_key=" RANGE (id) ")
    routes["indexes"] = [dict(index, kind="I") for index in routes["indexes"]]
    routes["indexes"].append({"schema": "hr", "table": "workers_2026", "name": "workers_2026_pkey", "kind": "i", "is_partition": True, "detach_pending": False, "parent_schema": "hr", "parent_name": "workers_pkey", "method": "btree", "keys": [" id "], "key_columns": ["id"], "include": [], "unique": True, "nulls_not_distinct": False, "predicate": None, "valid": True, "ready": True, "backing_constraint": None})
    value, _ = _extract(routes)
    partition = next(row for row in value["tables"] if row["name"] == "workers_2026")
    assert partition["is_partition"] is True
    assert partition["parent"] == {"schema": "hr", "table": "workers"}
    assert partition["bound"] == "FOR VALUES FROM (1) TO (2)"
    assert fingerprint_digest(value) != fingerprint_digest(_extract(_base_routes())[0])
    routes["classes"][-1] = dict(routes["classes"][-1], parent_table=None)
    with pytest.raises(FingerprintError, match="B04-FP-PARTITION"):
        _extract(routes)


def test_b04_fp_013_unknown_constraint_and_duplicate_index_identity_fail_closed() -> None:
    routes = _base_routes()
    routes["constraints"].append(dict(routes["constraints"][0], name="workers_exclude", kind="x"))
    with pytest.raises(FingerprintError, match="B04-FP-UNSUPPORTED-CONSTRAINT"):
        _extract(routes)
    routes = _base_routes()
    routes["indexes"].append(dict(routes["indexes"][0]))
    with pytest.raises(FingerprintError, match="B04-FP-DUPLICATE-INDEX"):
        _extract(routes)


def test_b04_fp_014_strict_semantics_reject_bad_attributes_and_unicode_dollar_tag_is_preserved() -> None:
    assert normalize_deparsed_expression(" $тег$  сохраняй   это  $тег$ ") == "$тег$  сохраняй   это  $тег$"
    with pytest.raises(FingerprintError, match="B04-FP-EXPRESSION"):
        normalize_deparsed_expression("$тег$ no close")
    value, _ = _extract(_base_routes())
    bad = dict(value)
    table = dict(value["tables"][0])
    columns = [dict(column) for column in table["columns"]]
    columns[0]["identity"] = "x"
    table["columns"] = columns
    bad["tables"] = [table]
    with pytest.raises(FingerprintError, match="B04-FP-COLUMN"):
        canonicalize_fingerprint(bad)
    with pytest.raises(FingerprintError, match="B04-FP-POSTGRES-MAJOR"):
        _extract(_base_routes(), version="170009")
    routes = _base_routes()
    routes["columns"][0] = dict(routes["columns"][0], default="'unclosed")
    with pytest.raises(FingerprintError, match="B04-FP-EXPRESSION"):
        _extract(routes)
    routes = _base_routes()
    routes["sequences"][0] = dict(routes["sequences"][0], identity_kind=None)
    with pytest.raises(FingerprintError, match="B04-FP-SEQUENCE"):
        _extract(routes)


def test_b04_fp_015_partition_topology_requires_parent_table_and_parent_index_contracts() -> None:
    routes = _base_routes()
    routes["classes"][0] = dict(routes["classes"][0], kind="p", partition_key="RANGE (id)")
    routes["indexes"] = [dict(index, kind="I") for index in routes["indexes"]]
    routes["classes"].append({"schema": "hr", "name": "workers_child", "kind": "r", "rls": False, "force_rls": False, "is_partition": True, "detach_pending": False, "parent_schema": "hr", "parent_table": "workers", "partition_key": None, "bound": "FOR VALUES FROM (1) TO (2)"})
    routes["columns"].append({"schema": "hr", "table": "workers_child", "ordinal": 1, "name": "id", "format_type": "uuid", "nullable": False, "collation": None, "default": None, "identity": "", "generated": ""})
    routes["constraints"].append(dict(routes["constraints"][0], table="workers_child", name="workers_child_id_not_null"))
    routes["indexes"].append({"schema": "hr", "table": "workers_child", "name": "workers_child_pkey", "kind": "i", "is_partition": True, "detach_pending": False, "parent_schema": "hr", "parent_name": "workers_pkey", "method": "btree", "keys": ["id"], "key_columns": ["id"], "include": [], "unique": True, "nulls_not_distinct": False, "predicate": None, "valid": True, "ready": True, "backing_constraint": None})
    routes["indexes"].append({"schema": "hr", "table": "workers_child", "name": "workers_child_local_ix", "kind": "i", "is_partition": False, "detach_pending": False, "parent_schema": None, "parent_name": None, "method": "btree", "keys": ["id"], "key_columns": ["id"], "include": [], "unique": False, "nulls_not_distinct": False, "predicate": None, "valid": True, "ready": True, "backing_constraint": None})
    value, _ = _extract(routes)
    assert any(row["name"] == "workers_child" for row in value["tables"])
    for bad in ("missing_parent", "wrong_parent_kind", "detach"):
        broken = _base_routes()
        broken["classes"][0] = dict(broken["classes"][0], kind="p", partition_key="RANGE (id)")
        broken["indexes"] = [dict(index, kind="I") for index in broken["indexes"]]
        child = {"schema": "hr", "name": "workers_child", "kind": "r", "rls": False, "force_rls": False, "is_partition": True, "detach_pending": bad == "detach", "parent_schema": "hr", "parent_table": "workers" if bad != "missing_parent" else "absent", "partition_key": None, "bound": "FOR VALUES FROM (1) TO (2)"}
        broken["classes"].append(child)
        broken["columns"].append({"schema": "hr", "table": "workers_child", "ordinal": 1, "name": "id", "format_type": "uuid", "nullable": False, "collation": None, "default": None, "identity": "", "generated": ""})
        broken["constraints"].append(dict(broken["constraints"][0], table="workers_child", name="workers_child_id_not_null"))
        if bad == "wrong_parent_kind":
            broken["classes"][0] = dict(broken["classes"][0], kind="r", partition_key=None)
        with pytest.raises(FingerprintError, match="B04-FP-(PARTITION|UNSUPPORTED-OBJECT)"):
            _extract(broken)


def test_b04_fp_016_cross_invariants_and_each_sql_route_are_explicit() -> None:
    _, connection = _extract(_base_routes())
    required = {
        "namespaces": ("pg_namespace", "n.nspname AS name", "ANY(:schemas)"),
        "classes": ("pg_inherits", "inhdetachpending", "pg_get_partkeydef", "pg_get_expr", "ANY(:schemas)"),
        "columns": ("row_number() over (partition by c.oid order by a.attnum)", "ORDER BY n.nspname,c.relname,a.attnum", "pg_get_expr", "ANY(:schemas)"),
        "constraints": ("pg_constraint", "pg_get_constraintdef", "LEFT JOIN pg_index", "ANY(:schemas)"),
        "indexes": ("pg_am", "pg_inherits", "inhdetachpending", "unnest(ix.indkey)", "CASE WHEN k.attnum=0 THEN NULL ELSE a.attname END", "con.conindid=ix.indexrelid AND con.conrelid=ix.indrelid", "ANY(:schemas)"),
        "sequences": ("pg_sequence", "pg_depend", "d.refobjsubid > 0", "COALESCE(oa.attidentity,'')", "ANY(:schemas)"),
        "triggers": ("pg_trigger", "NOT t.tgisinternal", "ANY(:schemas)"),
        "policies": ("pg_policy", "polrelid", "ANY(:schemas)"),
        "routines": ("pg_proc", "pronamespace", "ANY(:schemas)"),
        "types": ("pg_type", "t.typrelid=0 AND t.typelem=0", "ANY(:schemas)"),
        "defect_types": ("quality.defect_types", "id::text AS id", "requires_description", "ANY(:schemas)"),
        "defect_location_types": ("quality.defect_location_types", "id::text AS id", "ANY(:schemas)"),
    }
    for route, tokens in required.items():
        assert all(token in connection.statements[route] for token in tokens), route
    assert "con.contype IN" not in connection.statements["constraints"].split("WHERE", 1)[1]
    assert normalize_deparsed_expression("$тег$ ok $тег$$next$") == "$тег$ ok $тег$$next$"


def test_b04_fp_017_forbidden_cross_domain_strings_fail_closed() -> None:
    value, _ = _extract(_base_routes())
    cases: list[tuple[str, object]] = [
        ("identity", "x"), ("generated", "x"), ("sequence_identity", "x"),
        ("empty_index_method", ""), ("empty_index_keys", []), ("empty_fk_columns", []),
    ]
    for field, replacement in cases:
        bad = json.loads(json.dumps(value))
        if field == "identity": bad["tables"][0]["columns"][0]["identity"] = replacement
        elif field == "generated": bad["tables"][0]["columns"][0]["generated"] = replacement
        elif field == "sequence_identity": bad["sequences"][0]["identity_kind"] = replacement
        elif field == "empty_index_method": bad["tables"][0]["indexes"][0]["method"] = replacement
        elif field == "empty_index_keys": bad["tables"][0]["indexes"][0]["keys"] = replacement
        else: bad["tables"][0]["foreign_keys"][0]["columns"] = replacement
        with pytest.raises(FingerprintError):
            canonicalize_fingerprint(bad)


def test_b04_fp_018_cross_object_registries_reject_bad_references_and_sequence_bounds() -> None:
    value, _ = _extract(_base_routes())
    mutations = {
        "owner_table": lambda data: data["sequences"][1].update({"owned_by": {"schema": "hr", "table": "absent", "column": "id"}}),
        "owner_identity": lambda data: data["sequences"][1].update({"identity_kind": "d"}),
        "fk_target": lambda data: data["tables"][0]["foreign_keys"][0].update({"target_table": "absent"}),
        "fk_column": lambda data: data["tables"][0]["foreign_keys"][0].update({"target_columns": ["absent"]}),
        "backing": lambda data: data["tables"][0]["indexes"][0].update({"backing_constraint": "absent"}),
        "nonunique_nulls": lambda data: data["tables"][0]["indexes"][0].update({"unique": False, "nulls_not_distinct": True}),
        "increment": lambda data: data["sequences"][0].update({"increment": 0}),
        "range": lambda data: data["sequences"][0].update({"minimum": 2}),
        "numeric_type": lambda data: data["sequences"][0].update({"numeric_type": "numeric"}),
        "check": lambda data: data["tables"][0]["checks"][0].update({"definition": "  "}),
        "predicate": lambda data: data["tables"][0]["indexes"][0].update({"predicate": "  "}),
    }
    for name, mutate in mutations.items():
        bad = json.loads(json.dumps(value))
        mutate(bad)
        try:
            canonicalize_fingerprint(bad)
        except FingerprintError:
            continue
        pytest.fail(name)


def test_b04_fp_019_identity_sequence_and_constraint_index_bijections_fail_closed() -> None:
    value, _ = _extract(_base_routes())
    mutations = {
        "identity_missing": lambda data: data["sequences"].pop(),
        "identity_kind": lambda data: data["sequences"][1].update({"identity_kind": "d"}),
        "identity_owner_type": lambda data: data["sequences"][1].update({"numeric_type": "integer"}),
        "duplicate_owner": lambda data: data["sequences"].append(dict(data["sequences"][1], name="worker_id_seq_copy")),
        "identity_range": lambda data: data["sequences"][1].update({"maximum": 9223372036854775808}),
        "missing_backing": lambda data: data["tables"][0]["indexes"].pop(),
        "duplicate_backing": lambda data: data["tables"][0]["indexes"].append(dict(next(index for index in data["tables"][0]["indexes"] if index["backing_constraint"] == "workers_pkey"), name="workers_pkey_copy")),
        "nulls_mismatch": lambda data: next(index for index in data["tables"][0]["indexes"] if index["backing_constraint"] == "workers_manager_key").update({"nulls_not_distinct": False}),
        "pk_nulls": lambda data: next(item for item in data["tables"][0]["primary_keys_uniques"] if item["kind"] == "p").update({"nulls_not_distinct": True}),
    }
    for name, mutate in mutations.items():
        bad = json.loads(json.dumps(value))
        mutate(bad)
        try:
            canonicalize_fingerprint(bad)
        except FingerprintError:
            continue
        pytest.fail(name)


def test_b04_fp_020_normalized_expressions_must_remain_nonempty() -> None:
    value, _ = _extract(_base_routes())
    mutations = {
        "key": lambda data: data["tables"][0]["indexes"][0]["keys"].__setitem__(0, "  \t"),
        "check": lambda data: data["tables"][0]["checks"][0].update({"definition": " \n "}),
        "partition_key": lambda data: data["tables"][0].update({"kind": "p", "partition_key": " ", "indexes": [dict(index, kind="I") for index in data["tables"][0]["indexes"]]}),
    }
    for mutate in mutations.values():
        bad = json.loads(json.dumps(value))
        mutate(bad)
        with pytest.raises(FingerprintError):
            canonicalize_fingerprint(bad)


def test_b04_fp_021_backing_index_requires_simple_btree_constraint_columns_and_default_is_nonempty() -> None:
    value, _ = _extract(_base_routes())
    mutations = {
        "method": lambda data: next(index for index in data["tables"][0]["indexes"] if index["backing_constraint"] == "workers_manager_key").update({"method": "hash"}),
        "predicate": lambda data: next(index for index in data["tables"][0]["indexes"] if index["backing_constraint"] == "workers_manager_key").update({"predicate": "manager_id IS NOT NULL"}),
        "expression": lambda data: next(index for index in data["tables"][0]["indexes"] if index["backing_constraint"] == "workers_manager_key").update({"key_columns": [None]}),
        "order": lambda data: next(index for index in data["tables"][0]["indexes"] if index["backing_constraint"] == "workers_manager_key").update({"key_columns": ["id"]}),
        "default": lambda data: data["tables"][0]["columns"][0].update({"default": "  \t"}),
    }
    for mutate in mutations.values():
        bad = json.loads(json.dumps(value))
        mutate(bad)
        with pytest.raises(FingerprintError):
            canonicalize_fingerprint(bad)


def test_b04_fp_022_standalone_index_key_columns_must_be_local_or_expression() -> None:
    value, _ = _extract(_base_routes())
    bad = json.loads(json.dumps(value))
    expression_index = next(item for item in bad["tables"][0]["indexes"] if item["name"] == "workers_manager_expression_ix")
    expression_index["key_columns"] = ["absent_column"]
    with pytest.raises(FingerprintError):
        canonicalize_fingerprint(bad)


def test_b04_fp_023_pg18_named_not_null_constraint_is_fingerprinted() -> None:
    routes = _base_routes()

    value, connection = _extract(routes)

    assert value["tables"][0]["not_nulls"] == [
        {
            "kind": "n",
            "column": "id",
            "validated": True,
            "enforced": True,
            "no_inherit": False,
        }
    ]
    assert "con.conenforced AS enforced" in connection.statements["constraints"]


@pytest.mark.parametrize(
    "mutation",
    ["missing", "nullable", "duplicate_column", "not_validated", "not_enforced", "no_inherit"],
)
def test_b04_fp_024_not_null_catalog_and_column_nullability_must_agree(mutation: str) -> None:
    value, _ = _extract(_base_routes())
    bad = json.loads(json.dumps(value))
    table = bad["tables"][0]
    not_null = table["not_nulls"][0]

    if mutation == "missing":
        table["not_nulls"] = []
    elif mutation == "nullable":
        table["columns"][0]["nullable"] = True
    elif mutation == "duplicate_column":
        table["not_nulls"].append(dict(not_null))
    elif mutation == "not_validated":
        not_null["validated"] = False
    elif mutation == "not_enforced":
        not_null["enforced"] = False
    else:
        not_null["no_inherit"] = True

    with pytest.raises(FingerprintError, match="B04-FP-NOT-NULL"):
        canonicalize_fingerprint(bad)


def test_b04_fp_025_not_null_order_is_canonical_and_semantics_change_digest() -> None:
    routes = _base_routes()
    routes["columns"][1] = dict(routes["columns"][1], nullable=False)
    routes["constraints"].append(
        dict(
            routes["constraints"][0],
            name="workers_manager_id_not_null",
            columns=["manager_id"],
            definition="NOT NULL manager_id",
        )
    )
    value, _ = _extract(routes)
    reordered = json.loads(json.dumps(value))
    reordered["tables"][0]["not_nulls"].reverse()
    base, _ = _extract(_base_routes())

    assert canonicalize_fingerprint(reordered) == canonicalize_fingerprint(value)
    assert fingerprint_digest(base) != fingerprint_digest(value)


def test_b04_fp_026_not_null_constraint_name_is_not_part_of_fingerprint() -> None:
    original, _ = _extract(_base_routes())
    renamed_routes = _base_routes()
    renamed_routes["constraints"][0] = dict(
        renamed_routes["constraints"][0],
        name="historical_path_dependent_name",
    )
    renamed, _ = _extract(renamed_routes)

    assert original["tables"][0]["not_nulls"] == [
        {
            "kind": "n",
            "column": "id",
            "validated": True,
            "enforced": True,
            "no_inherit": False,
        }
    ]
    assert fingerprint_digest(original) == fingerprint_digest(renamed)
