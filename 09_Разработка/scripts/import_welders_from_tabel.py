"""Импорт сварщиков из табеля ОК (Excel) в РАБОТНИКИ + СВАРЩИКИ.

Использование:
    python scripts/import_welders_from_tabel.py file1.xlsx file2.xlsx ...
    python scripts/import_welders_from_tabel.py file1.xlsx --dry-run
    python scripts/import_welders_from_tabel.py          # файлы введёт интерактивно
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


def _first_two_words(fio: str) -> str:
    """Фамилия + Имя (первые два слова) для нечёткого сравнения."""
    parts = fio.strip().split()
    return " ".join(parts[:2]).lower()


def _find_similar(fio: str, existing: set[str]) -> list[str]:
    """Вернуть существующие ФИО с той же фамилией и именем."""
    key = _first_two_words(fio)
    return [e for e in existing if _first_two_words(e) == key and e != fio]


def _extract_from_sheet(df: pd.DataFrame) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        cells = [str(v).strip() if pd.notna(v) else "" for v in row]
        if not any(cells):
            continue

        # Формат 1: col[0] — порядковый номер, col[1] — ФИО, col[2] — Должность
        if len(cells) >= 3 and cells[0].isdigit():
            fio, dol = cells[1], cells[2]
            if _looks_like_name(fio) and _is_welder(dol):
                results.append((fio, dol))
            continue

        # Формат 2: col[0] — ФИО, col[1] — Должность (без номера)
        if len(cells) >= 2 and _looks_like_name(cells[0]):
            fio, dol = cells[0], cells[1]
            if _is_welder(dol):
                results.append((fio, dol))

    return results


def _load_from_file(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
        sheet_rows = _extract_from_sheet(df)
        if sheet_rows:
            print(f"    Лист «{sheet}»: найдено {len(sheet_rows)}")
        rows.extend(sheet_rows)
    return rows


def _get_existing(conn) -> dict[str, int]:
    """Вернуть {ФИО: ID_Работника} из таблицы РАБОТНИКИ."""
    with conn.cursor() as cur:
        cur.execute(
            f'SELECT "ID_Работника", "ФИО" FROM "{settings.db_schema}"."РАБОТНИКИ"'
        )
        return {row["ФИО"]: row["ID_Работника"] for row in cur.fetchall()}


def _get_svarshchik_ids(conn) -> set[int]:
    """Вернуть множество ID_Работника у которых уже есть запись СВАРЩИКИ."""
    with conn.cursor() as cur:
        cur.execute(f'SELECT "ID_Работника" FROM "{settings.db_schema}"."СВАРЩИКИ"')
        return {row["ID_Работника"] for row in cur.fetchall()}


def _insert_rabotnik(conn, fio: str, dolzhnost: str, organizatsiya: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO "{settings.db_schema}"."РАБОТНИКИ"
                ("ФИО", "Должность", "Организация", "Статус")
            VALUES (%s, %s, %s, 'активный')
            RETURNING "ID_Работника"
            """,
            (fio, dolzhnost, organizatsiya),
        )
        return cur.fetchone()["ID_Работника"]


def _insert_svarshchik(conn, id_rabotnika: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO "{settings.db_schema}"."СВАРЩИКИ"
                ("ID_Работника", "Статус_Сварщика")
            VALUES (%s, 'активный')
            """,
            (id_rabotnika,),
        )


def _ask_duplicate(fio_new: str, similar: list[str]) -> str:
    """Спросить пользователя что делать с похожим именем.

    Возвращает: 'add' | 'skip'
    """
    print(f"\n  ⚠  Похожее имя уже есть в базе:")
    print(f"     Новый:      {fio_new}")
    for s in similar:
        print(f"     В базе:     {s}")
    while True:
        ans = input("     Добавить как нового? [y=добавить / n=пропустить]: ").strip().lower()
        if ans in ("y", "д"):
            return "add"
        if ans in ("n", "н", ""):
            return "skip"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    file_args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # --- Получить пути к файлам ---
    if file_args:
        paths = [Path(p.strip('"')) for p in file_args]
    else:
        print("Введите пути к файлам Excel (пустая строка — конец):")
        paths = []
        while True:
            line = input("  Файл: ").strip().strip('"')
            if not line:
                break
            paths.append(Path(line))

    if not paths:
        print("Файлы не указаны.")
        return 1

    organizatsiya = input("Организация (подрядчик): ").strip()
    if not organizatsiya:
        print("Организация не указана.")
        return 1

    # --- Разобрать файлы ---
    print()
    found: list[tuple[str, str]] = []
    for p in paths:
        if not p.exists():
            print(f"  ПРОПУСК — файл не найден: {p}")
            continue
        print(f"  Читаю: {p.name}")
        rows = _load_from_file(p)
        found.extend(rows)

    # Дедупликация внутри загруженных данных
    unique: dict[str, str] = {}
    for fio, dol in found:
        if fio not in unique:
            unique[fio] = dol

    print(f"\nНайдено уникальных сварщиков в файлах: {len(unique)}")
    if not unique:
        print("Нечего импортировать.")
        return 0

    # --- Сравнить с БД ---
    with get_connection() as conn:
        existing = _get_existing(conn)
        existing_svar_ids = _get_svarshchik_ids(conn)

    existing_fio = set(existing.keys())

    # Точные совпадения: уже в РАБОТНИКИ. Среди них — кому нужна СВАРЩИКИ
    exact_dupes = {fio for fio in unique if fio in existing_fio}
    need_svar_only = {
        fio: existing[fio]
        for fio in exact_dupes
        if existing[fio] not in existing_svar_ids
    }
    to_add = {fio: dol for fio, dol in unique.items() if fio not in existing_fio}

    # Найти похожие (возможные дубли из-за опечаток)
    similar_warnings: dict[str, list[str]] = {}
    for fio in to_add:
        hits = _find_similar(fio, existing_fio)
        if hits:
            similar_warnings[fio] = hits

    # --- Вывод отчёта ---
    if exact_dupes:
        print(f"\nТочные совпадения в базе ({len(exact_dupes)} чел.) — РАБОТНИКИ уже есть:")
        for fio in sorted(exact_dupes):
            marker = "+" if fio in need_svar_only else "="
            suffix = " (нет СВАРЩИКИ — создадим)" if fio in need_svar_only else ""
            print(f"  {marker} {fio}{suffix}")

    if similar_warnings:
        print(f"\nПохожие имена — возможные опечатки ({len(similar_warnings)} чел.):")
        for fio, hits in similar_warnings.items():
            print(f"  ? {fio!r}  <->  {hits}")

    print(f"\nКандидаты на добавление: {len(to_add)} чел.")
    for fio, dol in sorted(to_add.items()):
        marker = "⚠" if fio in similar_warnings else "+"
        print(f"  {marker} {fio} ({dol})")

    if need_svar_only:
        print(f"\nДозаписать СВАРЩИКИ (уже в РАБОТНИКИ): {len(need_svar_only)} чел.")

    if dry_run:
        print("\n[--dry-run] Запись в БД не выполнялась.")
        return 0

    if not to_add and not need_svar_only:
        print("Новых записей нет.")
        return 0

    confirm = input("\nПродолжить импорт? [y/N]: ").strip().lower()
    if confirm not in ("y", "д"):
        print("Отменено.")
        return 0

    # --- Запись в БД ---
    inserted = 0
    svar_backfilled = 0
    skipped_by_user = 0

    with get_connection() as conn:
        # Дозаполнить СВАРЩИКИ для тех кто уже в РАБОТНИКИ
        for fio, id_rab in need_svar_only.items():
            _insert_svarshchik(conn, id_rab)
            print(f"  СВАРЩИКИ дозаписан: {fio}")
            svar_backfilled += 1

        # Добавить новых работников + сварщиков
        for fio, dol in to_add.items():
            if fio in similar_warnings:
                decision = _ask_duplicate(fio, similar_warnings[fio])
                if decision == "skip":
                    print(f"  ПРОПУЩЕН: {fio}")
                    skipped_by_user += 1
                    continue

            id_rab = _insert_rabotnik(conn, fio, dol, organizatsiya)
            _insert_svarshchik(conn, id_rab)
            print(f"  ДОБАВЛЕН: {fio}")
            inserted += 1

    parts = [f"добавлено новых: {inserted}"]
    if svar_backfilled:
        parts.append(f"СВАРЩИКИ дозаписано: {svar_backfilled}")
    if skipped_by_user:
        parts.append(f"пропущено вами: {skipped_by_user}")
    print(f"\nГотово. {', '.join(parts)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
