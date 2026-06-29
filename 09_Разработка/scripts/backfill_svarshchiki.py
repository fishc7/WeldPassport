"""Дозаполнение СВАРЩИКИ для работников без записи.

Читает все табели из указанного каталога, извлекает сварщиков (по Должности),
проверяет — есть ли уже СВАРЩИКИ для этого ID_Работника.
Если нет — создаёт запись СВАРЩИКИ со статусом 'активный'.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from config import settings
from db import get_connection

WELDER_TITLES = {"эл/сварщик", "эл/сварщик тт"}
TABELI_DIR = Path(r"D:\WeldPassport\Работники\Табеля")


def _normalize(s: str) -> str:
    return s.strip().lower()


def _is_welder(title: str) -> bool:
    return _normalize(title) in WELDER_TITLES


def _looks_like_name(value: str) -> bool:
    v = value.strip()
    parts = v.split()
    return (
        len(parts) >= 2
        and bool(re.search(r"[А-ЯЁа-яё]", v))
        and not any(c.isdigit() for c in v)
        and len(v) > 5
    )


def _extract_from_sheet(df: pd.DataFrame) -> list[str]:
    results = []
    for _, row in df.iterrows():
        cells = [str(v).strip() if pd.notna(v) else "" for v in row]
        if not any(cells):
            continue
        if len(cells) >= 3 and cells[0].isdigit():
            fio, dol = cells[1], cells[2]
            if _looks_like_name(fio) and _is_welder(dol):
                results.append(fio)
            continue
        if len(cells) >= 2 and _looks_like_name(cells[0]):
            fio, dol = cells[0], cells[1]
            if _is_welder(dol):
                results.append(fio)
    return results


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    files = list(TABELI_DIR.glob("*.xlsx")) + list(TABELI_DIR.glob("*.xls"))
    if not files:
        print(f"Нет файлов в {TABELI_DIR}")
        return 1

    welder_fio: set[str] = set()
    for p in sorted(files):
        xl = pd.ExcelFile(p)
        for sheet in xl.sheet_names:
            df = pd.read_excel(p, sheet_name=sheet, header=None, dtype=str)
            welder_fio.update(_extract_from_sheet(df))

    print(f"Уникальных ФИО сварщиков в табелях: {len(welder_fio)}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT "ID_Работника", "ФИО" FROM "{settings.db_schema}"."РАБОТНИКИ"')
            all_workers = {row["ФИО"]: row["ID_Работника"] for row in cur.fetchall()}

            cur.execute(
                f'SELECT r."ФИО" FROM "{settings.db_schema}"."РАБОТНИКИ" r '
                f'JOIN "{settings.db_schema}"."СВАРЩИКИ" s ON s."ID_Работника" = r."ID_Работника"'
            )
            already_svar = {row["ФИО"] for row in cur.fetchall()}

        to_backfill = [
            (fio, all_workers[fio])
            for fio in welder_fio
            if fio in all_workers and fio not in already_svar
        ]

        not_in_db = [fio for fio in welder_fio if fio not in all_workers]

    print(f"Уже есть СВАРЩИКИ: {len(already_svar)}")
    print(f"Нет в РАБОТНИКИ:   {len(not_in_db)}")
    print(f"Нужно дозаписать:  {len(to_backfill)}")

    if not to_backfill:
        print("Ничего делать не нужно.")
        return 0

    print()
    for fio, id_rab in sorted(to_backfill, key=lambda x: x[0]):
        print(f"  {'[dry]' if dry_run else '    '} {fio} (ID_Работника={id_rab})")

    if dry_run:
        print("\n[--dry-run] Запись в БД не выполнялась.")
        return 0

    confirm = input(f"\nСоздать {len(to_backfill)} записей СВАРЩИКИ? [y/N]: ").strip().lower()
    if confirm not in ("y", "д"):
        print("Отменено.")
        return 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            for fio, id_rab in to_backfill:
                cur.execute(
                    f'INSERT INTO "{settings.db_schema}"."СВАРЩИКИ" '
                    f'("ID_Работника", "Статус_Сварщика") VALUES (%s, \'активный\')',
                    (id_rab,),
                )
                print(f"  СОЗДАН: {fio}")

    print(f"\nГотово. Создано записей СВАРЩИКИ: {len(to_backfill)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
