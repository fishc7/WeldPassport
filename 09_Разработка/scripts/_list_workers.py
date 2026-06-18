from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import settings
from db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'РАБОТНИКИ'
            ORDER BY ordinal_position
            """,
            (settings.db_schema,),
        )
        columns = [row["column_name"] for row in cur.fetchall()]

        cur.execute(f'SELECT * FROM "{settings.db_schema}"."РАБОТНИКИ" ORDER BY 1')
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM "{settings.db_schema}"."СВАРЩИКИ" s
            JOIN "{settings.db_schema}"."РАБОТНИКИ" r
              ON r."ID_Работника" = s."ID_Работника"
            """
        )
        welders_linked = cur.fetchone()["cnt"]

out = Path(__file__).parent / "_workers.json"
out.write_text(
    json.dumps(
        {"columns": columns, "count": len(rows), "welders_linked": welders_linked, "rows": rows},
        ensure_ascii=False,
        indent=2,
        default=str,
    ),
    encoding="utf-8",
)
print(f"workers={len(rows)}, welders_linked={welders_linked}")
