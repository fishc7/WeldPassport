from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import settings
from db import get_connection


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.table_name,
                    c.ordinal_position,
                    c.column_name,
                    c.data_type,
                    c.udt_name,
                    c.is_nullable,
                    c.column_default
                FROM information_schema.columns AS c
                WHERE c.table_schema = %s
                ORDER BY c.table_name, c.ordinal_position
                """,
                (settings.db_schema,),
            )
            columns = cur.fetchall()

            cur.execute(
                """
                SELECT
                    tc.table_name,
                    tc.constraint_name,
                    tc.constraint_type,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                LEFT JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_catalog = kcu.constraint_catalog
                    AND tc.constraint_schema = kcu.constraint_schema
                    AND tc.constraint_name = kcu.constraint_name
                LEFT JOIN information_schema.constraint_column_usage AS ccu
                    ON tc.constraint_catalog = ccu.constraint_catalog
                    AND tc.constraint_schema = ccu.constraint_schema
                    AND tc.constraint_name = ccu.constraint_name
                WHERE tc.table_schema = %s
                ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name,
                         kcu.ordinal_position
                """,
                (settings.db_schema,),
            )
            constraints = cur.fetchall()

            cur.execute(
                """
                SELECT
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = %s
                ORDER BY tablename, indexname
                """,
                (settings.db_schema,),
            )
            indexes = cur.fetchall()

    tables = sorted({row["table_name"] for row in columns})
    for table in tables:
        print(f"\n=== {table} ===")
        print("Columns:")
        for row in columns:
            if row["table_name"] != table:
                continue
            data_type = row["data_type"]
            if data_type == "USER-DEFINED":
                data_type = row["udt_name"]
            nullable = "NULL" if row["is_nullable"] == "YES" else "NOT NULL"
            default = (
                f" DEFAULT {row['column_default']}"
                if row["column_default"] is not None
                else ""
            )
            print(
                f"  {row['ordinal_position']:>2}. {row['column_name']}: "
                f"{data_type} {nullable}{default}"
            )

        print("Constraints:")
        seen = set()
        for row in constraints:
            if row["table_name"] != table:
                continue
            key = (
                row["constraint_name"],
                row["constraint_type"],
                row["column_name"],
                row["foreign_table_name"],
                row["foreign_column_name"],
            )
            if key in seen:
                continue
            seen.add(key)
            target = ""
            if row["constraint_type"] == "FOREIGN KEY":
                target = (
                    f" -> {row['foreign_table_name']}."
                    f"{row['foreign_column_name']}"
                )
            column = (
                f" ({row['column_name']})" if row["column_name"] else ""
            )
            print(
                f"  {row['constraint_type']}: "
                f"{row['constraint_name']}{column}{target}"
            )

        print("Indexes:")
        for row in indexes:
            if row["tablename"] == table:
                print(f"  {row['indexname']}: {row['indexdef']}")


if __name__ == "__main__":
    main()
