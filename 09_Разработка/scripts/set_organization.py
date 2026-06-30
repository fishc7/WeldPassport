"""Устанавливает единое значение Организации для всех работников.

Запуск из каталога 09_Разработка:
    python scripts/set_organization.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import settings
from db import get_connection

ORGANIZATION = "ООО М КРАН"


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) AS cnt FROM "{settings.db_schema}"."РАБОТНИКИ"'
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f'UPDATE "{settings.db_schema}"."РАБОТНИКИ" '
                f'SET "Организация" = %s',
                (ORGANIZATION,),
            )
            updated = cur.rowcount

        conn.commit()

    print(f"Всего работников: {total}")
    print(f"Обновлено: {updated}")
    print(f'Организация проставлена: "{ORGANIZATION}"')


if __name__ == "__main__":
    main()
