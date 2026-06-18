from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import settings
from db import get_connection


def main() -> int:
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
                    c.column_default,
                    c.character_maximum_length
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
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.constraint_schema = kcu.constraint_schema
                LEFT JOIN information_schema.constraint_column_usage AS ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.constraint_schema = ccu.constraint_schema
                WHERE tc.table_schema = %s
                  AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
                ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name
                """,
                (settings.db_schema,),
            )
            constraints = cur.fetchall()

    out = Path(__file__).parent / "_schema_snapshot.json"
    out.write_text(
        json.dumps(
            {
                "schema": settings.db_schema,
                "columns": columns,
                "constraints": constraints,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tables = sorted({row["table_name"] for row in columns})
    print(f"Схема {settings.db_schema}: {len(tables)} таблиц -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
