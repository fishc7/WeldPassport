from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from sqlalchemy import MetaData

from app.workforce.legacy_contract import (
    LegacyColumnContract,
    LegacyExecutableContract,
    LegacySequencePrivilegeContract,
    build_legacy_executable_contract,
    normalize_postgresql_type,
)
from app.workforce.legacy_orm import LegacyBase
import app.workforce.models  # noqa: F401


BACKEND_DIR = Path(__file__).resolve().parents[1]
EXPECTED_TABLE_NAMES = (
    "АТТЕСТАЦИИ_СВАРЩИКОВ",
    "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ",
    "ДОКУМЕНТЫ_СВАРЩИКА",
    "ДОПУСКИ_К_ОБЪЕКТУ",
    "РАБОТНИКИ",
    "СВАРЩИКИ",
    "СПРАВОЧНИК_ДОЛЖНОСТЕЙ",
)


def _table(contract: LegacyExecutableContract, name: str):
    return next(table for table in contract.tables if table.name == name)


def test_legacy_contract_001_has_exact_relations_and_operation_policy() -> None:
    contract = build_legacy_executable_contract()

    assert contract.schema == "test"
    assert contract.schema_privileges == ("USAGE",)
    assert tuple(table.name for table in contract.tables) == EXPECTED_TABLE_NAMES
    assert all("SELECT" in table.required_privileges for table in contract.tables)

    writable = tuple(
        table.name
        for table in contract.tables
        if "INSERT" in table.required_privileges
    )
    assert writable == ("РАБОТНИКИ", "СВАРЩИКИ")
    assert all(
        table.required_privileges == ("INSERT", "SELECT", "UPDATE")
        for table in contract.tables
        if table.name in writable
    )
    assert all(
        table.required_privileges == ("SELECT",)
        for table in contract.tables
        if table.name not in writable
    )


def test_legacy_contract_002_derives_columns_and_constraints_from_metadata() -> None:
    contract = build_legacy_executable_contract()
    workers = _table(contract, "РАБОТНИКИ")
    positions = _table(contract, "СПРАВОЧНИК_ДОЛЖНОСТЕЙ")
    object_admissions = _table(contract, "ДОПУСКИ_К_ОБЪЕКТУ")

    assert workers.primary_key == ("ID_Работника",)
    assert tuple(column.name for column in workers.columns) == tuple(
        sorted(
            (
                "ID_Должности",
                "ID_Работника",
                "Дата_Приема",
                "Дата_Увольнения",
                "Должность",
                "Организация",
                "Статус",
                "Табельный_Номер",
                "ФИО",
            )
        )
    )
    assert next(
        column for column in workers.columns if column.name == "ФИО"
    ) == LegacyColumnContract(
        name="ФИО",
        type_name="character varying(255)",
        nullable=False,
    )
    assert tuple(unique.columns for unique in positions.unique_constraints) == (
        ("Наименование",),
    )
    assert any(
        foreign_key.columns == ("ID_Объекта",)
        and foreign_key.target_schema == "test"
        and foreign_key.target_table == "ОБЪЕКТЫ"
        and foreign_key.target_columns == ("ID_Объекта",)
        for foreign_key in object_admissions.foreign_keys
    )
    assert next(
        column
        for column in object_admissions.columns
        if column.name == "ID_Объекта"
    ) == LegacyColumnContract(
        name="ID_Объекта",
        type_name="integer",
        nullable=False,
    )


def test_legacy_contract_003_owned_pk_sequences_are_derived_for_writes() -> None:
    contract = build_legacy_executable_contract()

    assert _table(contract, "РАБОТНИКИ").sequence_privileges == (
        LegacySequencePrivilegeContract(
            column="ID_Работника",
            required_privileges=("USAGE",),
        ),
    )
    assert _table(contract, "СВАРЩИКИ").sequence_privileges == (
        LegacySequencePrivilegeContract(
            column="ID_Сварщика",
            required_privileges=("USAGE",),
        ),
    )
    assert all(
        not table.sequence_privileges
        for table in contract.tables
        if table.name not in {"РАБОТНИКИ", "СВАРЩИКИ"}
    )


def test_legacy_contract_004_is_deterministic_and_tuple_serializable() -> None:
    first = build_legacy_executable_contract()
    second = build_legacy_executable_contract()

    assert first == second
    assert isinstance(first.tables, tuple)
    assert all(isinstance(table.columns, tuple) for table in first.tables)
    assert tuple(table.name for table in first.tables) == tuple(
        sorted(table.name for table in first.tables)
    )
    assert all(
        tuple(column.name for column in table.columns)
        == tuple(sorted(column.name for column in table.columns))
        for table in first.tables
    )


def test_legacy_contract_005_normalizes_postgresql_type_aliases() -> None:
    assert normalize_postgresql_type("VARCHAR(150)") == "character varying(150)"
    assert (
        normalize_postgresql_type("character varying(150)")
        == "character varying(150)"
    )
    assert normalize_postgresql_type("int4") == "integer"
    assert normalize_postgresql_type("INT2") == "smallint"
    assert normalize_postgresql_type("BOOL") == "boolean"


def test_legacy_contract_006_one_metadata_mutation_changes_one_table(
    monkeypatch,
) -> None:
    baseline = build_legacy_executable_contract()
    copied = MetaData()
    for table in LegacyBase.metadata.tables.values():
        table.to_metadata(copied)
    copied.tables["test.РАБОТНИКИ"].c["ФИО"].nullable = True
    monkeypatch.setattr(LegacyBase, "metadata", copied)

    changed = build_legacy_executable_contract()

    differing_tables = tuple(
        before.name
        for before, after in zip(baseline.tables, changed.tables, strict=True)
        if before != after
    )
    assert differing_tables == ("РАБОТНИКИ",)
    assert next(
        column
        for column in _table(changed, "РАБОТНИКИ").columns
        if column.name == "ФИО"
    ).nullable is True


def test_legacy_contract_007_does_not_import_or_mutate_canonical_metadata() -> None:
    code = """
import sys
from app.shared.orm import Base
before = tuple(sorted(Base.metadata.tables))
from app.workforce.legacy_contract import build_legacy_executable_contract
contract = build_legacy_executable_contract()
assert len(contract.tables) == 7
assert tuple(sorted(Base.metadata.tables)) == before
assert "app.shared.canonical_metadata" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
