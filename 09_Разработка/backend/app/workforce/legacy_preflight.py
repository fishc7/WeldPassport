from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.shared.runtime_profile import RuntimeContractError
from app.workforce.legacy_contract import (
    LegacyColumnContract,
    LegacyExecutableContract,
    LegacyForeignKeyContract,
    LegacySequencePrivilegeContract,
    LegacyTableContract,
    LegacyUniqueContract,
    build_legacy_executable_contract,
    normalize_postgresql_type,
)


_SCHEMA_SQL = text(
    """
    SELECT
        to_regnamespace(:schema_name) IS NOT NULL AS schema_exists,
        COALESCE(
            has_schema_privilege(
                current_user,
                to_regnamespace(:schema_name),
                'USAGE'
            ),
            false
        ) AS has_usage
    """
)

_COLUMNS_SQL = text(
    """
    SELECT
        relation.relname AS table_name,
        attribute.attname AS column_name,
        format_type(attribute.atttypid, attribute.atttypmod) AS type_name,
        NOT attribute.attnotnull AS nullable
    FROM pg_namespace AS namespace
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = relation.oid
    WHERE namespace.nspname = :schema_name
      AND relation.relkind IN ('r', 'p')
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    ORDER BY relation.relname, attribute.attname
    """
)

_CONSTRAINTS_SQL = text(
    """
    WITH constraint_columns AS (
        SELECT
            constraint_row.oid AS constraint_oid,
            relation.relname AS table_name,
            constraint_row.contype AS constraint_type,
            source_key.ordinality AS column_position,
            source_attribute.attname AS column_name,
            target_namespace.nspname AS target_schema,
            target_relation.relname AS target_table,
            target_attribute.attname AS target_column
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation
          ON relation.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN LATERAL unnest(constraint_row.conkey)
             WITH ORDINALITY AS source_key(attnum, ordinality)
          ON true
        JOIN pg_attribute AS source_attribute
          ON source_attribute.attrelid = relation.oid
         AND source_attribute.attnum = source_key.attnum
        LEFT JOIN pg_class AS target_relation
          ON target_relation.oid = constraint_row.confrelid
        LEFT JOIN pg_namespace AS target_namespace
          ON target_namespace.oid = target_relation.relnamespace
        LEFT JOIN LATERAL unnest(constraint_row.confkey)
             WITH ORDINALITY AS target_key(attnum, ordinality)
          ON target_key.ordinality = source_key.ordinality
        LEFT JOIN pg_attribute AS target_attribute
          ON target_attribute.attrelid = target_relation.oid
         AND target_attribute.attnum = target_key.attnum
        WHERE namespace.nspname = :schema_name
          AND constraint_row.contype IN ('p', 'u', 'f')
    )
    SELECT
        table_name,
        constraint_type,
        array_agg(column_name ORDER BY column_position) AS columns,
        target_schema,
        target_table,
        array_agg(target_column ORDER BY column_position)
            FILTER (WHERE target_column IS NOT NULL) AS target_columns
    FROM constraint_columns
    GROUP BY
        constraint_oid,
        table_name,
        constraint_type,
        target_schema,
        target_table
    ORDER BY table_name, constraint_type, columns
    """
)

_TABLE_PRIVILEGES_SQL = text(
    """
    SELECT
        relation.relname AS table_name,
        has_table_privilege(current_user, relation.oid, 'SELECT') AS has_select,
        has_table_privilege(current_user, relation.oid, 'INSERT') AS has_insert,
        has_table_privilege(current_user, relation.oid, 'UPDATE') AS has_update
    FROM pg_namespace AS namespace
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
    WHERE namespace.nspname = :schema_name
      AND relation.relkind IN ('r', 'p')
    ORDER BY relation.relname
    """
)

_SEQUENCE_PRIVILEGES_SQL = text(
    """
    SELECT
        owner_relation.relname AS table_name,
        owner_attribute.attname AS column_name,
        has_sequence_privilege(
            current_user,
            sequence_relation.oid,
            'USAGE'
        ) AS has_usage
    FROM pg_namespace AS owner_namespace
    JOIN pg_class AS owner_relation
      ON owner_relation.relnamespace = owner_namespace.oid
    JOIN pg_attribute AS owner_attribute
      ON owner_attribute.attrelid = owner_relation.oid
    JOIN pg_depend AS dependency
      ON dependency.refobjid = owner_relation.oid
     AND dependency.refobjsubid = owner_attribute.attnum
     AND dependency.deptype IN ('a', 'i')
    JOIN pg_class AS sequence_relation
      ON sequence_relation.oid = dependency.objid
     AND sequence_relation.relkind = 'S'
    WHERE owner_namespace.nspname = :schema_name
      AND owner_relation.relkind IN ('r', 'p')
    ORDER BY owner_relation.relname, owner_attribute.attname
    """
)


@dataclass(frozen=True)
class ObservedLegacyContract:
    schema: str
    schema_exists: bool
    schema_privileges: tuple[str, ...]
    tables: tuple[LegacyTableContract, ...]


def _rows(connection: Connection, statement, schema: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            statement,
            {"schema_name": schema},
        ).mappings()
    ]


def _new_table_snapshot() -> dict[str, Any]:
    return {
        "columns": [],
        "primary_key": (),
        "unique_constraints": [],
        "foreign_keys": [],
        "required_privileges": [],
        "sequence_privileges": [],
    }


def read_observed_legacy_contract(
    connection: Connection,
    schema: str,
) -> ObservedLegacyContract:
    schema_row = dict(
        connection.execute(
            _SCHEMA_SQL,
            {"schema_name": schema},
        ).mappings().one()
    )
    schema_exists = bool(schema_row["schema_exists"])
    schema_privileges = ("USAGE",) if schema_row["has_usage"] else ()
    if not schema_exists:
        return ObservedLegacyContract(
            schema=schema,
            schema_exists=False,
            schema_privileges=schema_privileges,
            tables=(),
        )

    snapshots: dict[str, dict[str, Any]] = {}

    for row in _rows(connection, _COLUMNS_SQL, schema):
        snapshot = snapshots.setdefault(row["table_name"], _new_table_snapshot())
        snapshot["columns"].append(
            LegacyColumnContract(
                name=row["column_name"],
                type_name=normalize_postgresql_type(row["type_name"]),
                nullable=bool(row["nullable"]),
            )
        )

    for row in _rows(connection, _CONSTRAINTS_SQL, schema):
        snapshot = snapshots.setdefault(row["table_name"], _new_table_snapshot())
        columns = tuple(row["columns"])
        if row["constraint_type"] == "p":
            snapshot["primary_key"] = columns
        elif row["constraint_type"] == "u":
            snapshot["unique_constraints"].append(
                LegacyUniqueContract(columns=columns)
            )
        elif row["constraint_type"] == "f":
            snapshot["foreign_keys"].append(
                LegacyForeignKeyContract(
                    columns=columns,
                    target_schema=row["target_schema"],
                    target_table=row["target_table"],
                    target_columns=tuple(row["target_columns"]),
                )
            )

    for row in _rows(connection, _TABLE_PRIVILEGES_SQL, schema):
        snapshot = snapshots.setdefault(row["table_name"], _new_table_snapshot())
        snapshot["required_privileges"] = [
            privilege
            for privilege, granted in (
                ("INSERT", row["has_insert"]),
                ("SELECT", row["has_select"]),
                ("UPDATE", row["has_update"]),
            )
            if granted
        ]

    for row in _rows(connection, _SEQUENCE_PRIVILEGES_SQL, schema):
        snapshot = snapshots.setdefault(row["table_name"], _new_table_snapshot())
        privileges = ("USAGE",) if row["has_usage"] else ()
        snapshot["sequence_privileges"].append(
            LegacySequencePrivilegeContract(
                column=row["column_name"],
                required_privileges=privileges,
            )
        )

    tables = tuple(
        LegacyTableContract(
            name=table_name,
            columns=tuple(
                sorted(snapshot["columns"], key=lambda column: column.name)
            ),
            primary_key=tuple(snapshot["primary_key"]),
            unique_constraints=tuple(sorted(snapshot["unique_constraints"])),
            foreign_keys=tuple(sorted(snapshot["foreign_keys"])),
            required_privileges=tuple(sorted(snapshot["required_privileges"])),
            sequence_privileges=tuple(sorted(snapshot["sequence_privileges"])),
        )
        for table_name, snapshot in sorted(snapshots.items())
    )
    return ObservedLegacyContract(
        schema=schema,
        schema_exists=True,
        schema_privileges=schema_privileges,
        tables=tables,
    )


def _contract_mismatch(detail: str) -> None:
    raise RuntimeContractError("LEGACY-CONTRACT-MISMATCH", detail)


def _privilege_mismatch(detail: str) -> None:
    raise RuntimeContractError("LEGACY-PRIVILEGE-MISSING", detail)


def compare_legacy_contract(
    expected: LegacyExecutableContract,
    observed: ObservedLegacyContract,
) -> None:
    if not observed.schema_exists:
        raise RuntimeContractError(
            "LEGACY-SCHEMA-MISSING",
            "legacy schema is missing",
        )
    if observed.schema != expected.schema:
        _contract_mismatch("legacy schema identity does not match")
    if not set(expected.schema_privileges).issubset(observed.schema_privileges):
        _privilege_mismatch("legacy schema privilege is missing")

    observed_tables = {table.name: table for table in observed.tables}
    for expected_table in expected.tables:
        observed_table = observed_tables.get(expected_table.name)
        if observed_table is None:
            _contract_mismatch(
                f"legacy relation {expected_table.name} is missing"
            )

        observed_columns = {
            column.name: column for column in observed_table.columns
        }
        for expected_column in expected_table.columns:
            observed_column = observed_columns.get(expected_column.name)
            if observed_column is None:
                _contract_mismatch(
                    f"legacy column {expected_table.name}.{expected_column.name} "
                    "is missing"
                )
            if observed_column.type_name != expected_column.type_name:
                _contract_mismatch(
                    f"legacy column {expected_table.name}.{expected_column.name} "
                    "type does not match"
                )
            if observed_column.nullable is not expected_column.nullable:
                _contract_mismatch(
                    f"legacy column {expected_table.name}.{expected_column.name} "
                    "nullability does not match"
                )

        if observed_table.primary_key != expected_table.primary_key:
            _contract_mismatch(
                f"legacy relation {expected_table.name} primary key does not match"
            )
        if not set(expected_table.unique_constraints).issubset(
            observed_table.unique_constraints
        ):
            _contract_mismatch(
                f"legacy relation {expected_table.name} unique constraint is missing"
            )
        if not set(expected_table.foreign_keys).issubset(
            observed_table.foreign_keys
        ):
            _contract_mismatch(
                f"legacy relation {expected_table.name} foreign key is missing"
            )
        if not set(expected_table.required_privileges).issubset(
            observed_table.required_privileges
        ):
            _privilege_mismatch(
                f"legacy relation {expected_table.name} privilege is missing"
            )

        observed_sequences = {
            sequence.column: sequence
            for sequence in observed_table.sequence_privileges
        }
        for expected_sequence in expected_table.sequence_privileges:
            observed_sequence = observed_sequences.get(expected_sequence.column)
            if observed_sequence is None or not set(
                expected_sequence.required_privileges
            ).issubset(observed_sequence.required_privileges):
                _privilege_mismatch(
                    f"legacy sequence for {expected_table.name}."
                    f"{expected_sequence.column} privilege is missing"
                )


def run_legacy_preflight(connection: Connection, schema: str) -> None:
    try:
        expected = build_legacy_executable_contract()
        observed = read_observed_legacy_contract(connection, schema)
        compare_legacy_contract(expected, observed)
    except RuntimeContractError:
        raise
    except Exception:
        raise RuntimeContractError(
            "LEGACY-CONTRACT-MISMATCH",
            "legacy catalog preflight failed",
        ) from None
