from __future__ import annotations
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from config import settings
from db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:

        # FK relations
        cur.execute("""
            SELECT
                tc.table_name AS from_table,
                kcu.column_name AS from_col,
                ccu.table_name AS to_table,
                ccu.column_name AS to_col,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
            ORDER BY tc.table_name, kcu.column_name
        """, (settings.db_schema,))
        fks = cur.fetchall()

        # Check PK on every table
        cur.execute("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s
            ORDER BY tc.table_name
        """, (settings.db_schema,))
        pks = cur.fetchall()

        # Row counts
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, (settings.db_schema,))
        tables = [r["table_name"] for r in cur.fetchall()]
        counts = {}
        for t in tables:
            cur.execute(f'SELECT COUNT(*) AS n FROM "{settings.db_schema}"."{t}"')
            counts[t] = cur.fetchone()["n"]

result = {
    "primary_keys": [{"table": r["table_name"], "pk_col": r["column_name"]} for r in pks],
    "foreign_keys": [
        {
            "from": f"{r['from_table']}.{r['from_col']}",
            "to": f"{r['to_table']}.{r['to_col']}",
        }
        for r in fks
    ],
    "row_counts": counts,
}

out = pathlib.Path(__file__).parent / "_relations.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("OK")
