"""Fail-closed PostgreSQL 18 catalog fingerprint v2 for B-04 verification only."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import text

from migrations.b04.seeds import SeedManifestError, canonical_seed_manifest_bytes, seed_manifest

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


CANONICAL_SCHEMAS = ("engineering", "hr", "project", "quality", "welding")
FINGERPRINT_FORMAT_VERSION = 2
SUPPORTED_POSTGRES_MAJOR = 18
_PARAMS = {"schemas": list(CANONICAL_SCHEMAS)}
_FORBIDDEN = frozenset({"oid", "owner", "acl", "statistics", "stats", "row_count", "storage", "last_value", "is_called", "created_at", "updated_at"})
_DOLLAR = re.compile(r"\$(?:[^\W\d]\w*)?\$", re.UNICODE)


class FingerprintError(ValueError):
    """Observed data is outside the frozen B-04 PostgreSQL 18 contract."""


def normalize_deparsed_expression(value: str | None) -> str | None:
    """Collapse only whitespace outside SQL literals, identifiers, and comments."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise FingerprintError("B04-FP-EXPRESSION-TYPE")
    out: list[str] = []
    index = 0
    pending_space = False

    def emit_token(token: str) -> None:
        nonlocal pending_space
        if pending_space and out:
            out.append(" ")
        pending_space = False
        out.append(token)

    while index < len(value):
        char = value[index]
        if char.isspace():
            pending_space = bool(out) and not out[-1].endswith("\n")
            index += 1
            continue
        if value.startswith("--", index):
            end = value.find("\n", index + 2)
            if end == -1:
                emit_token(value[index:])
                break
            emit_token(value[index : end + 1])
            index = end + 1
            continue
        if value.startswith("/*", index):
            end, depth = index + 2, 1
            while end < len(value) and depth:
                if value.startswith("/*", end):
                    depth += 1
                    end += 2
                elif value.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise FingerprintError("B04-FP-EXPRESSION-UNCLOSED")
            emit_token(value[index:end])
            index = end
            continue
        if char == "'":
            escaped = index > 0 and value[index - 1] in "Ee" and (index < 2 or not (value[index - 2].isalnum() or value[index - 2] == "_"))
            end = index + 1
            while end < len(value):
                if escaped and value[end] == "\\":
                    end += 2
                    continue
                if value[end] == "'":
                    if end + 1 < len(value) and value[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            else:
                raise FingerprintError("B04-FP-EXPRESSION-UNCLOSED")
            emit_token(value[index:end])
            index = end
            continue
        if char == '"':
            end = index + 1
            while end < len(value):
                if value[end] == '"':
                    if end + 1 < len(value) and value[end + 1] == '"':
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            else:
                raise FingerprintError("B04-FP-EXPRESSION-UNCLOSED")
            emit_token(value[index:end])
            index = end
            continue
        if char == "$":
            delimiter = None if index and (value[index - 1] in "_$" or value[index - 1].isalnum()) else _DOLLAR.match(value, index)
            if delimiter is not None:
                marker = delimiter.group(0)
                end = value.find(marker, delimiter.end())
                if end == -1:
                    raise FingerprintError("B04-FP-EXPRESSION-UNCLOSED")
                end += len(marker)
                emit_token(value[index:end])
                index = end
                continue
        emit_token(char)
        index += 1
    return "".join(out).strip()


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FingerprintError(code)
    return value


def _exact_fields(value: Mapping[str, object], fields: frozenset[str], code: str) -> None:
    if set(value) & _FORBIDDEN or set(value) != fields:
        raise FingerprintError(code)


def _str(value: object, code: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        raise FingerprintError(code)
    return value


def _bool(value: object, code: str) -> bool:
    if not isinstance(value, bool):
        raise FingerprintError(code)
    return value


def _integer(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FingerprintError(code)
    return value


def _ordered_strings(value: object, code: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FingerprintError(code)
    return list(value)


def _key_columns(value: object, code: str) -> list[str | None]:
    if not isinstance(value, list) or any(item is not None and (not isinstance(item, str) or not item) for item in value):
        raise FingerprintError(code)
    return list(value)


def _validate_column(value: object) -> None:
    record = _mapping(value, "B04-FP-COLUMN")
    _exact_fields(record, frozenset({"ordinal", "name", "format_type", "nullable", "collation", "default", "identity", "generated"}), "B04-FP-COLUMN")
    _integer(record["ordinal"], "B04-FP-COLUMN")
    if not _str(record["name"], "B04-FP-COLUMN") or not _str(record["format_type"], "B04-FP-COLUMN"):
        raise FingerprintError("B04-FP-COLUMN")
    _bool(record["nullable"], "B04-FP-COLUMN")
    _str(record["collation"], "B04-FP-COLUMN", nullable=True)
    default = _str(record["default"], "B04-FP-COLUMN", nullable=True)
    if default is not None and not normalize_deparsed_expression(default): raise FingerprintError("B04-FP-COLUMN")
    if record["identity"] not in {"", "a", "d"} or not isinstance(record["identity"], str): raise FingerprintError("B04-FP-COLUMN")
    if record["generated"] not in {"", "s"} or not isinstance(record["generated"], str): raise FingerprintError("B04-FP-COLUMN")


def _validate_named(record: Mapping[str, object], code: str) -> None:
    if _str(record["schema"], code) not in CANONICAL_SCHEMAS or not _str(record["name"], code):
        raise FingerprintError("B04-FP-SCHEMAS")


def _validate_table(value: object) -> None:
    table = _mapping(value, "B04-FP-TABLE")
    _exact_fields(table, frozenset({"schema", "name", "kind", "is_partition", "parent", "partition_key", "bound", "columns", "primary_keys_uniques", "foreign_keys", "checks", "indexes"}), "B04-FP-UNKNOWN")
    _validate_named(table, "B04-FP-TABLE")
    if table["kind"] not in {"r", "p"} or not isinstance(table["kind"], str):
        raise FingerprintError("B04-FP-TABLE")
    _bool(table["is_partition"], "B04-FP-PARTITION")
    if table["is_partition"]:
        parent = _mapping(table["parent"], "B04-FP-PARTITION")
        _exact_fields(parent, frozenset({"schema", "table"}), "B04-FP-PARTITION")
        if _str(parent["schema"], "B04-FP-PARTITION") not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-SCHEMAS")
        if not _str(parent["table"], "B04-FP-PARTITION") or not isinstance(table["bound"], str) or not normalize_deparsed_expression(table["bound"]): raise FingerprintError("B04-FP-PARTITION")
    else:
        if table["parent"] is not None or table["bound"] is not None: raise FingerprintError("B04-FP-PARTITION")
    if table["kind"] == "p":
        if not isinstance(table["partition_key"], str) or not normalize_deparsed_expression(table["partition_key"]): raise FingerprintError("B04-FP-PARTITION")
    elif table["partition_key"] is not None: raise FingerprintError("B04-FP-PARTITION")
    if not isinstance(table["columns"], list):
        raise FingerprintError("B04-FP-COLUMN")
    for column in table["columns"]:
        _validate_column(column)
    if [column["ordinal"] for column in table["columns"]] != list(range(1, len(table["columns"]) + 1)):
        raise FingerprintError("B04-FP-COLUMN")
    specs = {
        "primary_keys_uniques": frozenset({"name", "kind", "columns", "deferrable", "deferred", "validated", "nulls_not_distinct"}),
        "foreign_keys": frozenset({"name", "kind", "columns", "target_schema", "target_table", "target_columns", "match_type", "update_action", "delete_action", "deferrable", "deferred", "validated"}),
        "checks": frozenset({"name", "kind", "definition", "validated", "no_inherit"}),
        "indexes": frozenset({"name", "kind", "is_partition", "parent", "method", "keys", "key_columns", "include", "unique", "nulls_not_distinct", "predicate", "valid", "ready", "backing_constraint"}),
    }
    constraint_ids: set[str] = set()
    index_ids: set[str] = set()
    for collection, fields in specs.items():
        rows = table[collection]
        if not isinstance(rows, list):
            raise FingerprintError("B04-FP-OBJECT")
        for value in rows:
            item = _mapping(value, "B04-FP-OBJECT")
            _exact_fields(item, fields, "B04-FP-UNKNOWN")
            names = index_ids if collection == "indexes" else constraint_ids
            if not _str(item["name"], "B04-FP-OBJECT") or item["name"] in names: raise FingerprintError("B04-FP-DUPLICATE-INDEX" if collection == "indexes" else "B04-FP-DUPLICATE-CONSTRAINT")
            names.add(item["name"])
            if collection == "primary_keys_uniques":
                if item["kind"] not in {"p", "u"} or not isinstance(item["kind"], str): raise FingerprintError("B04-FP-OBJECT")
                if not _ordered_strings(item["columns"], "B04-FP-OBJECT"): raise FingerprintError("B04-FP-OBJECT")
                for field in ("deferrable", "deferred", "validated", "nulls_not_distinct"): _bool(item[field], "B04-FP-OBJECT")
            elif collection == "foreign_keys":
                if item["kind"] != "f": raise FingerprintError("B04-FP-OBJECT")
                source_columns = _ordered_strings(item["columns"], "B04-FP-OBJECT"); target_columns = _ordered_strings(item["target_columns"], "B04-FP-OBJECT")
                if not source_columns or not target_columns or len(source_columns) != len(target_columns): raise FingerprintError("B04-FP-OBJECT")
                if _str(item["target_schema"], "B04-FP-OBJECT") not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-SCHEMAS")
                if not _str(item["target_table"], "B04-FP-OBJECT"): raise FingerprintError("B04-FP-OBJECT")
                if item["match_type"] not in {"f", "p", "s"}: raise FingerprintError("B04-FP-OBJECT")
                if item["update_action"] not in {"a", "r", "c", "n", "d"} or item["delete_action"] not in {"a", "r", "c", "n", "d"}: raise FingerprintError("B04-FP-OBJECT")
                for field in ("deferrable", "deferred", "validated"): _bool(item[field], "B04-FP-OBJECT")
            elif collection == "checks":
                if item["kind"] != "c": raise FingerprintError("B04-FP-OBJECT")
                if not normalize_deparsed_expression(_str(item["definition"], "B04-FP-OBJECT")): raise FingerprintError("B04-FP-OBJECT")
                _bool(item["validated"], "B04-FP-OBJECT"); _bool(item["no_inherit"], "B04-FP-OBJECT")
            else:
                if item["kind"] not in {"i", "I"} or not isinstance(item["kind"], str): raise FingerprintError("B04-FP-OBJECT")
                _bool(item["is_partition"], "B04-FP-OBJECT")
                if item["is_partition"]:
                    parent = _mapping(item["parent"], "B04-FP-OBJECT")
                    _exact_fields(parent, frozenset({"schema", "name"}), "B04-FP-OBJECT")
                    if _str(parent["schema"], "B04-FP-OBJECT") not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-SCHEMAS")
                    if not _str(parent["name"], "B04-FP-OBJECT"): raise FingerprintError("B04-FP-OBJECT")
                elif item["parent"] is not None: raise FingerprintError("B04-FP-OBJECT")
                keys = _ordered_strings(item["keys"], "B04-FP-OBJECT")
                if not _str(item["method"], "B04-FP-OBJECT") or not keys or any(not normalize_deparsed_expression(key) for key in keys): raise FingerprintError("B04-FP-OBJECT")
                if len(_key_columns(item["key_columns"], "B04-FP-OBJECT")) != len(keys): raise FingerprintError("B04-FP-OBJECT")
                _ordered_strings(item["include"], "B04-FP-OBJECT")
                for field in ("unique", "nulls_not_distinct", "valid", "ready"): _bool(item[field], "B04-FP-OBJECT")
                if item["nulls_not_distinct"] and not item["unique"]: raise FingerprintError("B04-FP-OBJECT")
                predicate = _str(item["predicate"], "B04-FP-OBJECT", nullable=True)
                if predicate is not None and not normalize_deparsed_expression(predicate): raise FingerprintError("B04-FP-OBJECT")
                backing = _str(item["backing_constraint"], "B04-FP-OBJECT", nullable=True)
                if backing is not None and not backing: raise FingerprintError("B04-FP-OBJECT")


def _validate_sequence(value: object) -> None:
    record = _mapping(value, "B04-FP-SEQUENCE")
    _exact_fields(record, frozenset({"schema", "name", "numeric_type", "start", "minimum", "maximum", "increment", "cache", "cycle", "owned_by", "identity_kind"}), "B04-FP-SEQUENCE")
    _validate_named(record, "B04-FP-SEQUENCE")
    if not _str(record["numeric_type"], "B04-FP-SEQUENCE"): raise FingerprintError("B04-FP-SEQUENCE")
    for field in ("start", "minimum", "maximum", "increment", "cache"): _integer(record[field], "B04-FP-SEQUENCE")
    _bool(record["cycle"], "B04-FP-SEQUENCE")
    if record["identity_kind"] not in {"", "a", "d"} or not isinstance(record["identity_kind"], str): raise FingerprintError("B04-FP-SEQUENCE")
    if record["owned_by"] is not None:
        owner = _mapping(record["owned_by"], "B04-FP-SEQUENCE")
        _exact_fields(owner, frozenset({"schema", "table", "column"}), "B04-FP-SEQUENCE")
        if _str(owner["schema"], "B04-FP-SEQUENCE") not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-SCHEMAS")
        if not _str(owner["table"], "B04-FP-SEQUENCE") or not _str(owner["column"], "B04-FP-SEQUENCE"): raise FingerprintError("B04-FP-SEQUENCE")
    elif record["identity_kind"] != "":
        raise FingerprintError("B04-FP-SEQUENCE")


def assert_supported_catalog(fingerprint: Mapping[str, object]) -> None:
    data = _mapping(fingerprint, "B04-FP-TOPLEVEL")
    _exact_fields(data, frozenset({"format_version", "schemas", "tables", "sequences", "seeds"}), "B04-FP-UNKNOWN")
    if not isinstance(data["format_version"], int) or isinstance(data["format_version"], bool) or data["format_version"] != FINGERPRINT_FORMAT_VERSION: raise FingerprintError("B04-FP-FORMAT")
    if data["schemas"] != list(CANONICAL_SCHEMAS): raise FingerprintError("B04-FP-SCHEMAS")
    if not isinstance(data["tables"], list) or not isinstance(data["sequences"], list): raise FingerprintError("B04-FP-TOPLEVEL")
    table_ids: set[tuple[str, str]] = set()
    for table in data["tables"]:
        _validate_table(table)
        identity = (table["schema"], table["name"])
        if identity in table_ids: raise FingerprintError("B04-FP-DUPLICATE-TABLE")
        table_ids.add(identity)
    tables_by_id = {(table["schema"], table["name"]): table for table in data["tables"]}
    indexes_by_id: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for table in data["tables"]:
        if table["is_partition"]:
            parent = table["parent"]
            parent_table = tables_by_id.get((parent["schema"], parent["table"]))
            if parent_table is None or parent_table["kind"] != "p": raise FingerprintError("B04-FP-PARTITION")
        for index in table["indexes"]:
            if (index["kind"] == "I") != (table["kind"] == "p"):
                raise FingerprintError("B04-FP-PARTITION")
            if index["is_partition"] and not table["is_partition"]:
                raise FingerprintError("B04-FP-PARTITION")
            identity = (table["schema"], table["name"], index["name"])
            indexes_by_id[identity] = index
    for table in data["tables"]:
        for index in table["indexes"]:
            if index["is_partition"]:
                if not table["is_partition"]: raise FingerprintError("B04-FP-PARTITION")
                parent_table = table["parent"]
                parent_index = index["parent"]
                if parent_index["schema"] != parent_table["schema"]: raise FingerprintError("B04-FP-PARTITION")
                candidate = indexes_by_id.get((parent_index["schema"], parent_table["table"], parent_index["name"]))
                if candidate is None or candidate["kind"] != "I": raise FingerprintError("B04-FP-PARTITION")
    for table in data["tables"]:
        local_columns = {column["name"] for column in table["columns"]}
        constraints = {row["name"]: row for row in table["primary_keys_uniques"]}
        for constraint in table["primary_keys_uniques"]:
            if not set(constraint["columns"]).issubset(local_columns): raise FingerprintError("B04-FP-CATALOG-ORPHAN")
        for foreign_key in table["foreign_keys"]:
            if not set(foreign_key["columns"]).issubset(local_columns): raise FingerprintError("B04-FP-CATALOG-ORPHAN")
            target = tables_by_id.get((foreign_key["target_schema"], foreign_key["target_table"]))
            if target is None: raise FingerprintError("B04-FP-CATALOG-ORPHAN")
            target_columns = {column["name"] for column in target["columns"]}
            if not set(foreign_key["target_columns"]).issubset(target_columns): raise FingerprintError("B04-FP-CATALOG-ORPHAN")
        for index in table["indexes"]:
            if not set(index["include"]).issubset(local_columns): raise FingerprintError("B04-FP-CATALOG-ORPHAN")
            if any(column is not None and column not in local_columns for column in index["key_columns"]): raise FingerprintError("B04-FP-CATALOG-ORPHAN")
            if index["backing_constraint"] is not None:
                backing = constraints.get(index["backing_constraint"])
                if backing is None or backing["kind"] not in {"p", "u"} or not index["unique"]: raise FingerprintError("B04-FP-CATALOG-ORPHAN")
                if index["method"] != "btree" or index["predicate"] is not None or index["key_columns"] != backing["columns"] or any(column is None for column in index["key_columns"]): raise FingerprintError("B04-FP-CATALOG-ORPHAN")
        backing_indexes: dict[str, list[Mapping[str, object]]] = {}
        for index in table["indexes"]:
            if index["backing_constraint"] is not None:
                backing_indexes.setdefault(index["backing_constraint"], []).append(index)
        for constraint in table["primary_keys_uniques"]:
            backed = backing_indexes.get(constraint["name"], [])
            if len(backed) != 1: raise FingerprintError("B04-FP-CATALOG-ORPHAN")
            index = backed[0]
            if not index["unique"] or index["nulls_not_distinct"] != constraint["nulls_not_distinct"]: raise FingerprintError("B04-FP-CATALOG-ORPHAN")
            if constraint["kind"] == "p" and constraint["nulls_not_distinct"]: raise FingerprintError("B04-FP-CATALOG-ORPHAN")
    sequence_ids: set[tuple[str, str]] = set()
    owners: dict[tuple[str, str, str], Mapping[str, object]] = {}
    numeric_bounds = {
        "smallint": (-32768, 32767),
        "integer": (-2147483648, 2147483647),
        "bigint": (-9223372036854775808, 9223372036854775807),
    }
    for sequence in data["sequences"]:
        _validate_sequence(sequence)
        identity = (sequence["schema"], sequence["name"])
        if identity in sequence_ids: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
        sequence_ids.add(identity)
        if sequence["numeric_type"] not in numeric_bounds: raise FingerprintError("B04-FP-SEQUENCE")
        lower, upper = numeric_bounds[sequence["numeric_type"]]
        if sequence["increment"] == 0 or sequence["cache"] <= 0 or sequence["minimum"] >= sequence["maximum"] or not (lower <= sequence["minimum"] <= sequence["start"] <= sequence["maximum"] <= upper): raise FingerprintError("B04-FP-SEQUENCE")
        if sequence["owned_by"] is not None:
            owner = sequence["owned_by"]
            table = tables_by_id.get((owner["schema"], owner["table"]))
            if table is None: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
            column = next((item for item in table["columns"] if item["name"] == owner["column"]), None)
            if column is None: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
            owner_key = (owner["schema"], owner["table"], owner["column"])
            if owner_key in owners: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
            owners[owner_key] = sequence
            if sequence["numeric_type"] != column["format_type"]: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
            if column["identity"] in {"a", "d"}:
                if sequence["identity_kind"] != column["identity"]: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
            elif sequence["identity_kind"] != "":
                raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
    for table in data["tables"]:
        for column in table["columns"]:
            if column["identity"] in {"a", "d"}:
                owner = owners.get((table["schema"], table["name"], column["name"]))
                if owner is None or owner["identity_kind"] != column["identity"]: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
    try:
        canonical_seed_manifest_bytes(_mapping(data["seeds"], "B04-FP-SEEDS"))
    except SeedManifestError as exc:
        raise FingerprintError("B04-FP-SEEDS") from exc


def _normal(value: object) -> object:
    if isinstance(value, Mapping): return {str(key): _normal(item) for key, item in value.items()}
    if isinstance(value, list): return [_normal(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value): raise FingerprintError("B04-FP-VALUE")
    if value is None or isinstance(value, (str, bool, int, float)): return value
    raise FingerprintError("B04-FP-VALUE")


def _table_normal(table: Mapping[str, object]) -> dict[str, object]:
    result = dict(table)
    result["columns"] = [{**dict(column), "default": normalize_deparsed_expression(_mapping(column, "B04-FP-COLUMN")["default"])} for column in result["columns"]]
    result["checks"] = sorted([{**dict(row), "definition": normalize_deparsed_expression(_mapping(row, "B04-FP-OBJECT")["definition"])} for row in result["checks"]], key=lambda row: str(row["name"]))
    result["partition_key"] = normalize_deparsed_expression(result["partition_key"])
    result["bound"] = normalize_deparsed_expression(result["bound"])
    result["indexes"] = sorted([{**dict(row), "keys": [normalize_deparsed_expression(item) for item in _mapping(row, "B04-FP-OBJECT")["keys"]], "include": [normalize_deparsed_expression(item) for item in _mapping(row, "B04-FP-OBJECT")["include"]], "predicate": normalize_deparsed_expression(_mapping(row, "B04-FP-OBJECT")["predicate"])} for row in result["indexes"]], key=lambda row: str(row["name"]))
    for key in ("primary_keys_uniques", "foreign_keys"):
        result[key] = sorted([dict(row) for row in result[key]], key=lambda row: str(row["name"]))
    return _normal(result)  # type: ignore[return-value]


def canonicalize_fingerprint(value: Mapping[str, object]) -> bytes:
    assert_supported_catalog(value)
    data = dict(value)
    data["tables"] = sorted([_table_normal(_mapping(table, "B04-FP-TABLE")) for table in data["tables"]], key=lambda row: (str(row["schema"]), str(row["name"])))
    data["sequences"] = sorted([dict(row) for row in data["sequences"]], key=lambda row: (str(row["schema"]), str(row["name"])))
    return (json.dumps(_normal(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def fingerprint_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonicalize_fingerprint(value)).hexdigest()


_NAMESPACES_SQL = """/* b04:namespaces */ SELECT n.nspname AS name FROM pg_namespace n WHERE n.nspname=ANY(:schemas) ORDER BY n.nspname"""
_CLASSES_SQL = """/* b04:classes */
SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind,c.relrowsecurity AS rls,c.relforcerowsecurity AS force_rls,c.relispartition AS is_partition,COALESCE(inh.inhdetachpending,false) AS detach_pending,pn.nspname AS parent_schema,pc.relname AS parent_table,CASE WHEN c.relkind='p' THEN pg_get_partkeydef(c.oid) END AS partition_key,CASE WHEN c.relispartition THEN pg_get_expr(c.relpartbound,c.oid) END AS bound
FROM pg_namespace n JOIN pg_class c ON c.relnamespace=n.oid LEFT JOIN pg_inherits inh ON inh.inhrelid=c.oid LEFT JOIN pg_class pc ON pc.oid=inh.inhparent LEFT JOIN pg_namespace pn ON pn.oid=pc.relnamespace
WHERE n.nspname=ANY(:schemas) ORDER BY n.nspname,c.relname"""
_COLUMNS_SQL = """/* b04:columns */
SELECT n.nspname AS schema, c.relname AS table, row_number() over (partition by c.oid order by a.attnum) AS ordinal, a.attname AS name, format_type(a.atttypid, a.atttypmod) AS format_type, NOT a.attnotnull AS nullable, coll.collname AS collation, pg_get_expr(ad.adbin, ad.adrelid) AS default, a.attidentity AS identity, a.attgenerated AS generated
FROM pg_attribute AS a JOIN pg_class AS c ON c.oid=a.attrelid JOIN pg_namespace AS n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef AS ad ON ad.adrelid=a.attrelid AND ad.adnum=a.attnum LEFT JOIN pg_collation AS coll ON coll.oid=a.attcollation AND a.attcollation<>0
WHERE n.nspname=ANY(:schemas) AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped ORDER BY n.nspname,c.relname,a.attnum"""
_CONSTRAINTS_SQL = """/* b04:constraints */
SELECT n.nspname AS schema,c.relname AS table,con.conname AS name,con.contype AS kind,ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum ORDER BY k.ord) AS columns,tn.nspname AS target_schema,tc.relname AS target_table,ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=tc.oid AND a.attnum=k.attnum ORDER BY k.ord) AS target_columns,con.confmatchtype AS match_type,con.confupdtype AS update_action,con.confdeltype AS delete_action,con.condeferrable AS deferrable,con.condeferred AS deferred,con.convalidated AS validated,COALESCE(ix.indnullsnotdistinct,false) AS nulls_not_distinct,pg_get_constraintdef(con.oid,true) AS definition,con.connoinherit AS no_inherit
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_class tc ON tc.oid=con.confrelid LEFT JOIN pg_namespace tn ON tn.oid=tc.relnamespace LEFT JOIN pg_index ix ON ix.indexrelid=con.conindid
WHERE n.nspname=ANY(:schemas) ORDER BY n.nspname,c.relname,con.conname"""
_INDEXES_SQL = """/* b04:indexes */
SELECT n.nspname AS schema,c.relname AS table,i.relname AS name,i.relkind AS kind,(iinh.inhparent IS NOT NULL) AS is_partition,COALESCE(iinh.inhdetachpending,false) AS detach_pending,pn.nspname AS parent_schema,pi.relname AS parent_name,am.amname AS method,ARRAY(SELECT pg_get_indexdef(ix.indexrelid,k,true) FROM generate_series(1,ix.indnkeyatts) k ORDER BY k) AS keys,ARRAY(SELECT CASE WHEN k.attnum=0 THEN NULL ELSE a.attname END FROM unnest(ix.indkey) WITH ORDINALITY k(attnum,ord) LEFT JOIN pg_attribute a ON a.attrelid=ix.indrelid AND a.attnum=k.attnum WHERE k.ord<=ix.indnkeyatts ORDER BY k.ord) AS key_columns,ARRAY(SELECT pg_get_indexdef(ix.indexrelid,k,true) FROM generate_series(ix.indnkeyatts+1,ix.indnatts) k ORDER BY k) AS include,ix.indisunique AS unique,ix.indnullsnotdistinct AS nulls_not_distinct,pg_get_expr(ix.indpred,ix.indrelid) AS predicate,ix.indisvalid AS valid,ix.indisready AS ready,con.conname AS backing_constraint
FROM pg_index ix JOIN pg_class c ON c.oid=ix.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_class i ON i.oid=ix.indexrelid JOIN pg_am am ON am.oid=i.relam LEFT JOIN pg_inherits iinh ON iinh.inhrelid=i.oid LEFT JOIN pg_class pi ON pi.oid=iinh.inhparent LEFT JOIN pg_namespace pn ON pn.oid=pi.relnamespace LEFT JOIN pg_constraint con ON con.conindid=ix.indexrelid AND con.conrelid=ix.indrelid AND con.contype IN ('p','u')
WHERE n.nspname=ANY(:schemas) ORDER BY n.nspname,c.relname,i.relname"""
_SEQUENCES_SQL = """/* b04:sequences */
SELECT n.nspname AS schema,c.relname AS name,format_type(s.seqtypid,NULL) AS numeric_type,s.seqstart AS start,s.seqmin AS minimum,s.seqmax AS maximum,s.seqincrement AS increment,s.seqcache AS cache,s.seqcycle AS cycle,onsp.nspname AS owned_schema,oc.relname AS owned_table,oa.attname AS owned_column,COALESCE(oa.attidentity,'') AS identity_kind
FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_depend d ON d.classid = 'pg_class'::regclass AND d.objid=c.oid AND d.objsubid=0 AND d.refclassid = 'pg_class'::regclass AND d.refobjsubid > 0 AND d.deptype IN ('a','i') LEFT JOIN pg_class oc ON oc.oid=d.refobjid LEFT JOIN pg_namespace onsp ON onsp.oid=oc.relnamespace LEFT JOIN pg_attribute oa ON oa.attrelid=oc.oid AND oa.attnum=d.refobjsubid
WHERE n.nspname=ANY(:schemas) ORDER BY n.nspname,c.relname"""
_TRIGGERS_SQL = """/* b04:triggers */ SELECT n.nspname AS schema,c.relname AS table,t.tgname AS name FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(:schemas) AND NOT t.tgisinternal"""
_POLICIES_SQL = """/* b04:policies */ SELECT n.nspname AS schema,c.relname AS table,p.polname AS name FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(:schemas)"""
_ROUTINES_SQL = """/* b04:routines */ SELECT n.nspname AS schema,p.proname AS name,p.prokind AS kind FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=ANY(:schemas)"""
_TYPES_SQL = """/* b04:types */ SELECT n.nspname AS schema,t.typname AS name,t.typtype AS kind FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname=ANY(:schemas) AND t.typrelid=0 AND t.typelem=0"""
_DEFECT_TYPES_SQL = """/* b04:defect_types */ SELECT id::text AS id,code,name,category,requires_length,requires_width,requires_height,requires_depth,requires_area,requires_quantity,requires_known_indication_location,requires_description FROM quality.defect_types WHERE 'quality'=ANY(:schemas)"""
_LOCATION_TYPES_SQL = """/* b04:defect_location_types */ SELECT id::text AS id,code,name FROM quality.defect_location_types WHERE 'quality'=ANY(:schemas)"""


def _rows(connection: Connection, sql: str) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(text(sql), dict(_PARAMS)).mappings().all()]


def _catalog_strings(value: object, code: str) -> list[str]:
    return _ordered_strings(value, code)


def _catalog_optional_text(value: object, code: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise FingerprintError(code)
    return value


def _catalog_text(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise FingerprintError(code)
    return value


def _table_for(tables: Mapping[tuple[str, str], dict[str, object]], row: Mapping[str, object]) -> dict[str, object]:
    key = (row.get("schema"), row.get("table"))
    if not isinstance(key[0], str) or not isinstance(key[1], str) or key not in tables: raise FingerprintError("B04-FP-CATALOG-ORPHAN")
    return tables[key]


def _seed_rows(observed: list[dict[str, object]], expected: list[Mapping[str, object]]) -> None:
    if len(observed) != len(expected): raise FingerprintError("B04-FP-SEED-DRIFT")
    def rows_key(rows: Sequence[Mapping[str, object]]) -> set[str]:
        return {json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) for row in rows}
    expected_keys, observed_keys = rows_key(expected), rows_key(observed)
    if len(observed_keys) != len(observed) or observed_keys != expected_keys: raise FingerprintError("B04-FP-SEED-DRIFT")


def _sequences(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        schema, name = row.get("schema"), row.get("name")
        if not isinstance(schema, str) or not isinstance(name, str) or schema not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-CATALOG-SEQUENCE")
        key = (schema, name)
        if key in result: raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
        owned = None
        owner_values = (row.get("owned_schema"), row.get("owned_table"), row.get("owned_column"))
        if any(value is not None for value in owner_values):
            if not all(isinstance(value, str) and value for value in owner_values): raise FingerprintError("B04-FP-SEQUENCE-OWNERSHIP")
            if owner_values[0] not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-SCHEMAS")
            owned = {"schema": owner_values[0], "table": owner_values[1], "column": owner_values[2]}
        result[key] = {"schema": schema, "name": name, "numeric_type": row.get("numeric_type"), "start": row.get("start"), "minimum": row.get("minimum"), "maximum": row.get("maximum"), "increment": row.get("increment"), "cache": row.get("cache"), "cycle": row.get("cycle"), "owned_by": owned, "identity_kind": row.get("identity_kind")}
    return list(result.values())


def extract_fingerprint(connection: Connection) -> dict[str, object]:
    major = int(connection.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000
    if major != SUPPORTED_POSTGRES_MAJOR: raise FingerprintError("B04-FP-POSTGRES-MAJOR")
    namespaces = _rows(connection, _NAMESPACES_SQL)
    names = [row.get("name") for row in namespaces]
    if len(names) != len(CANONICAL_SCHEMAS) or any(not isinstance(name, str) for name in names) or set(names) != set(CANONICAL_SCHEMAS):
        raise FingerprintError("B04-FP-SCHEMAS")
    tables: dict[tuple[str, str], dict[str, object]] = {}
    for row in _rows(connection, _CLASSES_SQL):
        schema, name, kind = row.get("schema"), row.get("name"), row.get("kind")
        if not isinstance(schema, str) or not isinstance(name, str) or schema not in CANONICAL_SCHEMAS: raise FingerprintError("B04-FP-CATALOG-TABLE")
        if kind in {"i", "I", "S"}: continue
        if kind not in {"r", "p"}: raise FingerprintError("B04-FP-UNSUPPORTED-RELKIND")
        if row.get("rls") is not False or row.get("force_rls") is not False or row.get("detach_pending") is not False: raise FingerprintError("B04-FP-UNSUPPORTED-OBJECT")
        is_partition = row.get("is_partition")
        if not isinstance(is_partition, bool): raise FingerprintError("B04-FP-PARTITION")
        parent = None
        if is_partition:
            if not isinstance(row.get("parent_schema"), str) or row.get("parent_schema") not in CANONICAL_SCHEMAS or not isinstance(row.get("parent_table"), str) or not isinstance(row.get("bound"), str): raise FingerprintError("B04-FP-PARTITION")
            parent = {"schema": row["parent_schema"], "table": row["parent_table"]}
        elif row.get("parent_schema") is not None or row.get("parent_table") is not None or row.get("bound") is not None:
            raise FingerprintError("B04-FP-PARTITION")
        partition_key = row.get("partition_key")
        if kind == "p":
            if not isinstance(partition_key, str): raise FingerprintError("B04-FP-PARTITION")
        elif partition_key is not None: raise FingerprintError("B04-FP-PARTITION")
        if (schema, name) in tables: raise FingerprintError("B04-FP-DUPLICATE-TABLE")
        tables[(schema, name)] = {"schema": schema, "name": name, "kind": kind, "is_partition": is_partition, "parent": parent, "partition_key": partition_key, "bound": row.get("bound"), "columns": [], "primary_keys_uniques": [], "foreign_keys": [], "checks": [], "indexes": []}
    for row in _rows(connection, _COLUMNS_SQL):
        table = _table_for(tables, row)
        table["columns"].append({"ordinal": row.get("ordinal"), "name": row.get("name"), "format_type": row.get("format_type"), "nullable": row.get("nullable"), "collation": _catalog_optional_text(row.get("collation"), "B04-FP-CATALOG-COLUMN"), "default": normalize_deparsed_expression(_catalog_optional_text(row.get("default"), "B04-FP-CATALOG-COLUMN")), "identity": row.get("identity"), "generated": row.get("generated")})
    for row in _rows(connection, _CONSTRAINTS_SQL):
        table, kind = _table_for(tables, row), row.get("kind")
        if kind in {"p", "u"}:
            table["primary_keys_uniques"].append({"name": row.get("name"), "kind": kind, "columns": _catalog_strings(row.get("columns"), "B04-FP-CATALOG-ARRAY"), "deferrable": row.get("deferrable"), "deferred": row.get("deferred"), "validated": row.get("validated"), "nulls_not_distinct": row.get("nulls_not_distinct")})
        elif kind == "f":
            table["foreign_keys"].append({"name": row.get("name"), "kind": kind, "columns": _catalog_strings(row.get("columns"), "B04-FP-CATALOG-ARRAY"), "target_schema": row.get("target_schema"), "target_table": row.get("target_table"), "target_columns": _catalog_strings(row.get("target_columns"), "B04-FP-CATALOG-ARRAY"), "match_type": row.get("match_type"), "update_action": row.get("update_action"), "delete_action": row.get("delete_action"), "deferrable": row.get("deferrable"), "deferred": row.get("deferred"), "validated": row.get("validated")})
        elif kind == "c":
            table["checks"].append({"name": row.get("name"), "kind": kind, "definition": normalize_deparsed_expression(_catalog_text(row.get("definition"), "B04-FP-CATALOG-CONSTRAINT")), "validated": row.get("validated"), "no_inherit": row.get("no_inherit")})
        else: raise FingerprintError("B04-FP-UNSUPPORTED-CONSTRAINT")
    index_ids: set[tuple[str, str, str]] = set()
    for row in _rows(connection, _INDEXES_SQL):
        table = _table_for(tables, row)
        schema, table_name, name = row.get("schema"), row.get("table"), row.get("name")
        if not all(isinstance(value, str) and value for value in (schema, table_name, name)): raise FingerprintError("B04-FP-CATALOG-INDEX")
        identity = (schema, table_name, name)
        if identity in index_ids: raise FingerprintError("B04-FP-DUPLICATE-INDEX")
        index_ids.add(identity)
        is_partition = row.get("is_partition")
        if row.get("kind") not in {"i", "I"} or not isinstance(is_partition, bool) or row.get("detach_pending") is not False: raise FingerprintError("B04-FP-CATALOG-INDEX")
        parent = None
        if is_partition:
            if not isinstance(row.get("parent_schema"), str) or row.get("parent_schema") not in CANONICAL_SCHEMAS or not isinstance(row.get("parent_name"), str): raise FingerprintError("B04-FP-PARTITION")
            parent = {"schema": row["parent_schema"], "name": row["parent_name"]}
        elif row.get("parent_schema") is not None or row.get("parent_name") is not None: raise FingerprintError("B04-FP-PARTITION")
        keys = [normalize_deparsed_expression(item) for item in _catalog_strings(row.get("keys"), "B04-FP-CATALOG-ARRAY")]
        key_columns = _key_columns(row.get("key_columns"), "B04-FP-CATALOG-INDEX")
        if len(key_columns) != len(keys): raise FingerprintError("B04-FP-CATALOG-INDEX")
        table["indexes"].append({"name": name, "kind": row.get("kind"), "is_partition": is_partition, "parent": parent, "method": row.get("method"), "keys": keys, "key_columns": key_columns, "include": [normalize_deparsed_expression(item) for item in _catalog_strings(row.get("include"), "B04-FP-CATALOG-ARRAY")], "unique": row.get("unique"), "nulls_not_distinct": row.get("nulls_not_distinct"), "predicate": normalize_deparsed_expression(_catalog_optional_text(row.get("predicate"), "B04-FP-CATALOG-INDEX")), "valid": row.get("valid"), "ready": row.get("ready"), "backing_constraint": _catalog_optional_text(row.get("backing_constraint"), "B04-FP-CATALOG-INDEX")})
    sequences = _sequences(_rows(connection, _SEQUENCES_SQL))
    for sql in (_TRIGGERS_SQL, _POLICIES_SQL, _ROUTINES_SQL, _TYPES_SQL):
        if _rows(connection, sql): raise FingerprintError("B04-FP-UNSUPPORTED-OBJECT")
    expected = seed_manifest()
    _seed_rows(_rows(connection, _DEFECT_TYPES_SQL), expected["tables"][0]["rows"])
    _seed_rows(_rows(connection, _LOCATION_TYPES_SQL), expected["tables"][1]["rows"])
    value = {"format_version": FINGERPRINT_FORMAT_VERSION, "schemas": list(CANONICAL_SCHEMAS), "tables": list(tables.values()), "sequences": sequences, "seeds": expected}
    assert_supported_catalog(value)
    return json.loads(canonicalize_fingerprint(value))
