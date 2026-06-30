from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import settings
from db import get_connection

EXPECTED_TABLES = [
    "ПРОЕКТЫ",
    "ОБЪЕКТЫ",
    "ИЗОМЕТРИИ",
    "СТЫКИ",
    "РАБОТНИКИ",
    "СВАРЩИКИ",
    "ДОКУМЕНТЫ_СВАРЩИКА",
    "АТТЕСТАЦИИ_СВАРЩИКОВ",
    "ДОПУСКИ_К_ОБЪЕКТУ",
    "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ",
    "ФАКТЫ_СВАРКИ",
    "УЧАСТНИКИ_СВАРКИ",
    "КОНТРОЛЬ",
]


def main() -> int:
    if not settings.db_password:
        print("Укажите POSTGRES_PASSWORD в файле .env")
        return 1

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_database() AS db, current_user AS usr, current_schema() AS schema"
                )
                info = cur.fetchone()
                print(
                    f"Подключено: {info['db']} / {info['usr']} / схема {info['schema']}"
                )

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """,
                    (settings.db_schema,),
                )
                tables = [row["table_name"] for row in cur.fetchall()]
                print(f"\nТаблицы ({len(tables)}):")
                for name in tables:
                    cur.execute(
                        f'SELECT COUNT(*) AS cnt FROM "{settings.db_schema}"."{name}"'
                    )
                    count = cur.fetchone()["cnt"]
                    marker = " " if name in EXPECTED_TABLES else "?"
                    print(f"  {marker} {name}: {count} строк")

    except Exception as exc:
        print(f"Ошибка: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
