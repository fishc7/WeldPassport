from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
import re

import pytest

from app.shared.runtime_profile import RuntimeContractError
from app.workforce.legacy_contract import (
    LegacyColumnContract,
    LegacyTableContract,
    build_legacy_executable_contract,
)
from app.workforce.legacy_preflight import (
    ObservedLegacyContract,
    compare_legacy_contract,
    read_observed_legacy_contract,
    run_legacy_preflight,
)


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "workforce"
    / "legacy_preflight.py"
)
FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COMMENT)\b",
    re.IGNORECASE,
)


def _observed_from_expected() -> ObservedLegacyContract:
    expected = build_legacy_executable_contract()
    return ObservedLegacyContract(
        schema=expected.schema,
        schema_exists=True,
        schema_privileges=expected.schema_privileges,
        tables=expected.tables,
    )


def _replace_table(
    observed: ObservedLegacyContract,
    name: str,
    replacement: LegacyTableContract,
) -> ObservedLegacyContract:
    return replace(
        observed,
        tables=tuple(
            replacement if table.name == name else table
            for table in observed.tables
        ),
    )


def _assert_contract_error(
    observed: ObservedLegacyContract,
    expected_code: str,
) -> RuntimeContractError:
    with pytest.raises(RuntimeContractError) as exc_info:
        compare_legacy_contract(build_legacy_executable_contract(), observed)
    assert exc_info.value.code == expected_code
    return exc_info.value


def test_legacy_preflight_001_missing_schema_fails_with_stable_code() -> None:
    observed = replace(_observed_from_expected(), schema_exists=False)

    error = _assert_contract_error(observed, "LEGACY-SCHEMA-MISSING")

    assert error.safe_detail == "legacy schema is missing"


def test_legacy_preflight_002_missing_relation_fails_contract() -> None:
    observed = _observed_from_expected()
    observed = replace(
        observed,
        tables=tuple(
            table for table in observed.tables if table.name != "РАБОТНИКИ"
        ),
    )

    _assert_contract_error(observed, "LEGACY-CONTRACT-MISMATCH")


@pytest.mark.parametrize("mutation", ["missing", "type", "nullable"])
def test_legacy_preflight_003_column_mismatch_fails_contract(
    mutation: str,
) -> None:
    observed = _observed_from_expected()
    workers = next(table for table in observed.tables if table.name == "РАБОТНИКИ")
    fio = next(column for column in workers.columns if column.name == "ФИО")
    if mutation == "missing":
        columns = tuple(column for column in workers.columns if column.name != "ФИО")
    elif mutation == "type":
        columns = tuple(
            replace(column, type_name="text") if column.name == "ФИО" else column
            for column in workers.columns
        )
    else:
        columns = tuple(
            replace(column, nullable=not fio.nullable)
            if column.name == "ФИО"
            else column
            for column in workers.columns
        )

    observed = _replace_table(observed, workers.name, replace(workers, columns=columns))

    _assert_contract_error(observed, "LEGACY-CONTRACT-MISMATCH")


@pytest.mark.parametrize("field", ["primary_key", "unique_constraints", "foreign_keys"])
def test_legacy_preflight_004_missing_constraint_fails_contract(
    field: str,
) -> None:
    observed = _observed_from_expected()
    table_name = {
        "primary_key": "РАБОТНИКИ",
        "unique_constraints": "СПРАВОЧНИК_ДОЛЖНОСТЕЙ",
        "foreign_keys": "ДОПУСКИ_К_ОБЪЕКТУ",
    }[field]
    table = next(table for table in observed.tables if table.name == table_name)
    replacement = replace(table, **{field: ()})
    observed = _replace_table(observed, table_name, replacement)

    _assert_contract_error(observed, "LEGACY-CONTRACT-MISMATCH")


def test_legacy_preflight_005_missing_schema_privilege_fails() -> None:
    observed = replace(_observed_from_expected(), schema_privileges=())

    _assert_contract_error(observed, "LEGACY-PRIVILEGE-MISSING")


def test_legacy_preflight_006_missing_table_privilege_fails() -> None:
    observed = _observed_from_expected()
    workers = next(table for table in observed.tables if table.name == "РАБОТНИКИ")
    observed = _replace_table(
        observed,
        workers.name,
        replace(workers, required_privileges=("INSERT", "SELECT")),
    )

    _assert_contract_error(observed, "LEGACY-PRIVILEGE-MISSING")


def test_legacy_preflight_007_missing_sequence_privilege_fails() -> None:
    observed = _observed_from_expected()
    workers = next(table for table in observed.tables if table.name == "РАБОТНИКИ")
    observed = _replace_table(
        observed,
        workers.name,
        replace(workers, sequence_privileges=()),
    )

    _assert_contract_error(observed, "LEGACY-PRIVILEGE-MISSING")


def test_legacy_preflight_008_extra_objects_are_allowed() -> None:
    observed = _observed_from_expected()
    first = observed.tables[0]
    extra_column = LegacyColumnContract(
        name="EXTRA_SAFE_COLUMN",
        type_name="text",
        nullable=True,
    )
    observed = _replace_table(
        observed,
        first.name,
        replace(first, columns=first.columns + (extra_column,)),
    )
    extra_table = LegacyTableContract(
        name="EXTRA_SAFE_TABLE",
        columns=(extra_column,),
        primary_key=(),
        unique_constraints=(),
        foreign_keys=(),
        required_privileges=("SELECT",),
        sequence_privileges=(),
    )
    observed = replace(observed, tables=observed.tables + (extra_table,))

    compare_legacy_contract(build_legacy_executable_contract(), observed)


def _assert_read_only_sql(sql_literals: list[str]) -> None:
    assert sql_literals
    for sql in sql_literals:
        first_keyword = sql.lstrip().split(maxsplit=1)[0].upper()
        assert first_keyword in {"SELECT", "WITH"}
        sql_without_string_literals = re.sub(r"'(?:''|[^'])*'", "''", sql)
        assert FORBIDDEN_SQL.search(sql_without_string_literals) is None
        assert ":schema_name" in sql


def test_legacy_preflight_009_all_catalog_sql_is_read_only() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    sql_literals = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "text"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ]

    _assert_read_only_sql(sql_literals)


def test_legacy_preflight_010_sql_governance_rejects_mutation() -> None:
    with pytest.raises(AssertionError):
        _assert_read_only_sql(
            ["SELECT * FROM pg_class WHERE nspname = :schema_name; UPDATE x SET y=1"]
        )


class _BrokenConnection:
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("secret-host.example/password=must-not-leak")


def test_legacy_preflight_011_raw_adapter_error_is_redacted() -> None:
    with pytest.raises(RuntimeContractError) as exc_info:
        run_legacy_preflight(_BrokenConnection(), "test")

    assert exc_info.value.code == "LEGACY-CONTRACT-MISMATCH"
    assert exc_info.value.safe_detail == "legacy catalog preflight failed"
    assert "secret-host" not in str(exc_info.value)
    assert "must-not-leak" not in str(exc_info.value)


class _MappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def one(self):
        assert len(self._rows) == 1
        return self._rows[0]

    def __iter__(self):
        return iter(self._rows)


class _SnapshotConnection:
    def __init__(self, responses: list[list[dict]]) -> None:
        self._responses = list(responses)
        self.parameters: list[dict] = []

    def execute(self, _statement, parameters):
        self.parameters.append(parameters)
        return _MappingResult(self._responses.pop(0))


def test_legacy_preflight_012_catalog_rows_become_ordered_snapshot() -> None:
    connection = _SnapshotConnection(
        [
            [{"schema_exists": True, "has_usage": True}],
            [
                {
                    "table_name": "РАБОТНИКИ",
                    "column_name": "ID_Работника",
                    "type_name": "int4",
                    "nullable": False,
                }
            ],
            [
                {
                    "table_name": "РАБОТНИКИ",
                    "constraint_type": "p",
                    "columns": ["ID_Работника"],
                    "target_schema": None,
                    "target_table": None,
                    "target_columns": None,
                }
            ],
            [
                {
                    "table_name": "РАБОТНИКИ",
                    "has_select": True,
                    "has_insert": True,
                    "has_update": True,
                }
            ],
            [
                {
                    "table_name": "РАБОТНИКИ",
                    "column_name": "ID_Работника",
                    "has_usage": True,
                }
            ],
        ]
    )

    observed = read_observed_legacy_contract(connection, "legacy_fixture")

    assert observed.schema == "legacy_fixture"
    assert observed.schema_exists is True
    assert observed.schema_privileges == ("USAGE",)
    assert len(observed.tables) == 1
    table = observed.tables[0]
    assert table.name == "РАБОТНИКИ"
    assert table.columns == (
        LegacyColumnContract(
            name="ID_Работника",
            type_name="integer",
            nullable=False,
        ),
    )
    assert table.primary_key == ("ID_Работника",)
    assert table.required_privileges == ("INSERT", "SELECT", "UPDATE")
    assert all(
        parameters == {"schema_name": "legacy_fixture"}
        for parameters in connection.parameters
    )
    assert len(connection.parameters) == 5
