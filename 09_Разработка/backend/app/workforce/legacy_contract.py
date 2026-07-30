from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import ForeignKeyConstraint, MetaData, Table

from app.shared.runtime_profile import RuntimeContractError
from app.workforce.legacy_orm import LegacyBase, get_bound_legacy_schema


@dataclass(frozen=True, order=True)
class LegacyColumnContract:
    name: str
    type_name: str
    nullable: bool


@dataclass(frozen=True, order=True)
class LegacyUniqueContract:
    columns: tuple[str, ...]


@dataclass(frozen=True, order=True)
class LegacyForeignKeyContract:
    columns: tuple[str, ...]
    target_schema: str
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True, order=True)
class LegacySequencePrivilegeContract:
    column: str
    required_privileges: tuple[str, ...]


@dataclass(frozen=True, order=True)
class LegacyTableContract:
    name: str
    columns: tuple[LegacyColumnContract, ...]
    primary_key: tuple[str, ...]
    unique_constraints: tuple[LegacyUniqueContract, ...]
    foreign_keys: tuple[LegacyForeignKeyContract, ...]
    required_privileges: tuple[str, ...]
    sequence_privileges: tuple[LegacySequencePrivilegeContract, ...]


@dataclass(frozen=True)
class LegacyExecutableContract:
    schema: str
    schema_privileges: tuple[str, ...]
    tables: tuple[LegacyTableContract, ...]


_TYPE_ALIASES = {
    "varchar": "character varying",
    "int4": "integer",
    "int2": "smallint",
    "bool": "boolean",
}
_WRITABLE_TABLES = frozenset({"РАБОТНИКИ", "СВАРЩИКИ"})
_READ_PRIVILEGES = ("SELECT",)
_WRITE_PRIVILEGES = ("INSERT", "SELECT", "UPDATE")
_SEQUENCE_PRIVILEGES = ("USAGE",)


def normalize_postgresql_type(raw: str) -> str:
    normalized = " ".join(raw.strip().lower().split())
    normalized = re.sub(r"\s*\(\s*", "(", normalized)
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    normalized = re.sub(r"\s*\)\s*", ")", normalized)
    base, separator, parameters = normalized.partition("(")
    canonical_base = _TYPE_ALIASES.get(base, base)
    if not separator:
        return canonical_base
    return f"{canonical_base}({parameters}"


def _foreign_key_contract(
    constraint: ForeignKeyConstraint,
) -> LegacyForeignKeyContract:
    pairs: list[tuple[str, str, str, str]] = []
    for element in constraint.elements:
        target_parts = element.target_fullname.split(".", maxsplit=2)
        if len(target_parts) != 3:
            raise RuntimeContractError(
                "LEGACY-CONTRACT-MISMATCH",
                "legacy foreign key target is not schema-qualified",
            )
        target_schema, target_table, target_column = target_parts
        pairs.append(
            (
                element.parent.name,
                target_schema,
                target_table,
                target_column,
            )
        )

    ordered_pairs = tuple(sorted(pairs, key=lambda item: item[0]))
    targets = {(item[1], item[2]) for item in ordered_pairs}
    if len(targets) != 1:
        raise RuntimeContractError(
            "LEGACY-CONTRACT-MISMATCH",
            "legacy foreign key has inconsistent targets",
        )
    target_schema, target_table = next(iter(targets))
    return LegacyForeignKeyContract(
        columns=tuple(item[0] for item in ordered_pairs),
        target_schema=target_schema,
        target_table=target_table,
        target_columns=tuple(item[3] for item in ordered_pairs),
    )


def _table_contract(table: Table) -> LegacyTableContract:
    columns = tuple(
        sorted(
            (
                LegacyColumnContract(
                    name=column.name,
                    type_name=normalize_postgresql_type(
                        column.type.compile(dialect=postgresql.dialect())
                    ),
                    nullable=column.nullable,
                )
                for column in table.columns
            ),
            key=lambda column: column.name,
        )
    )
    primary_key = tuple(sorted(column.name for column in table.primary_key.columns))
    unique_constraints = tuple(
        sorted(
            LegacyUniqueContract(
                columns=tuple(sorted(column.name for column in constraint.columns))
            )
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        )
    )
    foreign_keys = tuple(
        sorted(
            _foreign_key_contract(constraint)
            for constraint in table.foreign_key_constraints
        )
    )
    writable = table.name in _WRITABLE_TABLES
    sequence_privileges = tuple(
        LegacySequencePrivilegeContract(
            column=column.name,
            required_privileges=_SEQUENCE_PRIVILEGES,
        )
        for column in sorted(table.primary_key.columns, key=lambda column: column.name)
        if writable and column.autoincrement is not False
    )
    return LegacyTableContract(
        name=table.name,
        columns=columns,
        primary_key=primary_key,
        unique_constraints=unique_constraints,
        foreign_keys=foreign_keys,
        required_privileges=_WRITE_PRIVILEGES if writable else _READ_PRIVILEGES,
        sequence_privileges=sequence_privileges,
    )


def _build_from_metadata(
    metadata: MetaData,
    schema: str,
) -> LegacyExecutableContract:
    tables = tuple(
        sorted(
            (
                _table_contract(table)
                for table in metadata.tables.values()
                if table.schema == schema
            ),
            key=lambda table: table.name,
        )
    )
    return LegacyExecutableContract(
        schema=schema,
        schema_privileges=("USAGE",),
        tables=tables,
    )


def build_legacy_executable_contract() -> LegacyExecutableContract:
    from app.workforce import models as _models  # noqa: F401

    return _build_from_metadata(
        LegacyBase.metadata,
        get_bound_legacy_schema(),
    )
