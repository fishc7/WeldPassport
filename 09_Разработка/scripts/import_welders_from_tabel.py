"""Импорт сварщиков из табеля ОК (Excel) в РАБОТНИКИ + СВАРЩИКИ.

Использование:
    python scripts/import_welders_from_tabel.py file1.xlsx file2.xlsx ...
    python scripts/import_welders_from_tabel.py --dry-run file1.xlsx
    python scripts/import_welders_from_tabel.py          # файлы введёт интерактивно
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from importers.tabel_importer import analyze, apply, load_from_files
from config import settings
from db import get_connection


def _ask_duplicate(fio_new: str, fio_db: str) -> str:
    print(f"\n  ⚠  Похожее имя уже есть в базе:")
    print(f"     В табеле:  {fio_new}")
    print(f"     В базе:    {fio_db}")
    while True:
        ans = input("     Добавить как нового? [y=добавить / n=пропустить]: ").strip().lower()
        if ans in ("y", "д"):
            return "add"
        if ans in ("n", "н", ""):
            return "skip"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    file_args = [a for a in sys.argv[1:] if not a.startswith("--")]

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

    print()
    unique, errors, file_counts = load_from_files(paths)
    for name, count in file_counts.items():
        print(f"  {name}: найдено {count} сварщиков")
    for e in errors:
        print(f"  ОШИБКА: {e}")

    print(f"\nНайдено уникальных: {len(unique)}")
    if not unique:
        print("Нечего импортировать.")
        return 0

    with get_connection() as conn:
        analysis = analyze(unique, conn)

    # ── Отчёт ──
    if analysis["dismissed_in_tabel"]:
        print(f"\n⚠  В ТАБЕЛЕ ЕСТЬ УВОЛЕННЫЕ ({len(analysis['dismissed_in_tabel'])} чел.) — проверьте с ОК:")
        for x in analysis["dismissed_in_tabel"]:
            print(f"  ! {x['fio']}")

    if analysis["exact"]:
        active = [x for x in analysis["exact"] if not x["need_svar"]]
        need_svar = [x for x in analysis["exact"] if x["need_svar"]]
        if active:
            print(f"\nУже в базе ({len(active)} чел.) — пропускаем:")
            for x in active:
                print(f"  = {x['fio']}")
        if need_svar:
            print(f"\nЕсть в РАБОТНИКИ, нет в СВАРЩИКИ ({len(need_svar)} чел.) — дозапишем:")
            for x in need_svar:
                print(f"  + {x['fio']}")

    if analysis["fuzzy"]:
        print(f"\nПохожие имена ({len(analysis['fuzzy'])} чел.) — нужно решить:")
        for x in analysis["fuzzy"]:
            print(f"  ? {x['fio_new']!r}  <->  {x['fio_db']!r}")

    if analysis["new"]:
        print(f"\nНовых для добавления ({len(analysis['new'])} чел.):")
        for x in analysis["new"]:
            print(f"  + {x['fio']} ({x['dolzhnost']})")

    if dry_run:
        print("\n[--dry-run] В БД не записывалось.")
        return 0

    has_changes = (
        analysis["new"]
        or any(x["need_svar"] for x in analysis["exact"])
        or analysis["fuzzy"]
    )
    if not has_changes:
        print("\nНовых записей нет.")
        return 0

    confirm = input("\nПродолжить импорт? [y/N]: ").strip().lower()
    if confirm not in ("y", "д"):
        print("Отменено.")
        return 0

    # Решения по нечётким
    fuzzy_decisions: dict[str, str] = {}
    for x in analysis["fuzzy"]:
        fuzzy_decisions[x["fio_new"]] = _ask_duplicate(x["fio_new"], x["fio_db"])

    with get_connection() as conn:
        result = apply(organizatsiya, analysis, fuzzy_decisions, conn)

    parts = []
    if result["inserted"]:        parts.append(f"добавлено: {result['inserted']}")
    if result["svar_backfilled"]: parts.append(f"профили сварщика: {result['svar_backfilled']}")
    if result["skipped"]:         parts.append(f"пропущено: {result['skipped']}")
    print(f"\nГотово. {', '.join(parts) or 'Изменений нет'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
