"""Populate РАБОТНИКИ in PostgreSQL from ФИО_свар in SQLite."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import settings
from db import get_connection

SQLITE_DB = Path("D:/МК_Кран/script_M_Kran/database/BD_Kingisepp/M_Kran_Kingesepp.db")


def load_names() -> list[str]:
    conn = sqlite3.connect(SQLITE_DB)
    try:
        cur = conn.cursor()
        cur.execute('SELECT "ФИО" FROM "ФИО_свар" ORDER BY id_fio')
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def seed(names: list[str], dry_run: bool = False) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) AS cnt FROM "{settings.db_schema}"."РАБОТНИКИ"')
            existing = cur.fetchone()["cnt"]
            if existing > 0:
                print(f"Таблица РАБОТНИКИ уже содержит {existing} записей. Прерываем.")
                return

            if dry_run:
                print(f"Dry-run: будет вставлено {len(names)} записей.")
                for name in names:
                    print(f"  {name!r}")
                return

            cur.executemany(
                f'INSERT INTO "{settings.db_schema}"."РАБОТНИКИ" ("ФИО") VALUES (%s)',
                [(name,) for name in names],
            )
        conn.commit()
    print(f"Вставлено {len(names)} записей в РАБОТНИКИ.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    names = load_names()
    print(f"Загружено из SQLite: {len(names)} имён")
    seed(names, dry_run=dry)
