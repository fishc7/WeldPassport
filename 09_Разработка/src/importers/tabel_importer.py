"""Логика импорта сварщиков из Excel-табелей.

Используется и CLI-скриптом, и desktop_ok/api.py — логика не дублируется.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

WELDER_TITLES = {"эл/сварщик", "эл/сварщик тт"}


def _norm(s: str) -> str:
    return s.strip().lower()


def _is_welder(title: str) -> bool:
    return _norm(title) in WELDER_TITLES


def _looks_like_name(value: str) -> bool:
    v = value.strip()
    parts = v.split()
    return (
        len(parts) >= 2
        and bool(re.search(r"[А-ЯЁа-яё]", v))
        and not any(c.isdigit() for c in v)
        and len(v) > 5
    )


def _first_two(fio: str) -> str:
    return " ".join(fio.strip().split()[:2]).lower()


def _extract_from_sheet(df: pd.DataFrame) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        cells = [str(v).strip() if pd.notna(v) else "" for v in row]
        if not any(cells):
            continue
        if len(cells) >= 3 and cells[0].isdigit():
            fio, dol = cells[1], cells[2]
            if _looks_like_name(fio) and _is_welder(dol):
                results.append((fio, dol))
            continue
        if len(cells) >= 2 and _looks_like_name(cells[0]):
            fio, dol = cells[0], cells[1]
            if _is_welder(dol):
                results.append((fio, dol))
    return results


def load_from_files(paths: list[Path]) -> tuple[dict[str, str], list[str]]:
    """Читает Excel-файлы. Возвращает ({fio: dolzhnost}, [ошибки])."""
    found: list[tuple[str, str]] = []
    errors: list[str] = []
    file_counts: dict[str, int] = {}

    for p in paths:
        if not p.exists():
            errors.append(f"Файл не найден: {p.name}")
            continue
        count = 0
        # Контекст-менеджер обязателен: иначе хендл файла висит до сборки
        # мусора и на Windows блокирует последующий перенос/удаление файла.
        with pd.ExcelFile(p) as xl:
            for sheet in xl.sheet_names:
                df = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=str)
                rows = _extract_from_sheet(df)
                found.extend(rows)
                count += len(rows)
        file_counts[p.name] = count

    unique: dict[str, str] = {}
    for fio, dol in found:
        if fio not in unique:
            unique[fio] = dol

    return unique, errors, file_counts


def analyze(unique: dict[str, str], conn) -> dict:
    """Сравнивает со списком БД. Возвращает категоризированный diff.

    Структура результата:
        exact              — уже есть в РАБОТНИКИ (активные)
        dismissed_in_tabel — есть в табеле, но статус 'уволен'
        fuzzy              — похожие имена (нечёткое совпадение)
        new                — новые, совпадений нет
    """
    from config import settings

    with conn.cursor() as cur:
        cur.execute(
            f'SELECT "ID_Работника", "ФИО", "Статус" '
            f'FROM "{settings.db_schema}"."РАБОТНИКИ"'
        )
        db_rows = cur.fetchall()

    with conn.cursor() as cur:
        cur.execute(f'SELECT "ID_Работника" FROM "{settings.db_schema}"."СВАРЩИКИ"')
        svar_ids = {row["ID_Работника"] for row in cur.fetchall()}

    existing = {row["ФИО"]: row["ID_Работника"] for row in db_rows}
    dismissed_fio = {row["ФИО"] for row in db_rows if row["Статус"] == "уволен"}
    existing_fio = set(existing.keys())

    exact_dupes = {fio for fio in unique if fio in existing_fio}

    dismissed_in_tabel = [
        {"fio": fio}
        for fio in sorted(exact_dupes)
        if fio in dismissed_fio
    ]

    exact = [
        {
            "fio": fio,
            "id": existing[fio],
            "need_svar": existing[fio] not in svar_ids,
        }
        for fio in sorted(exact_dupes)
        if fio not in dismissed_fio
    ]

    to_add_fio = {fio for fio in unique if fio not in existing_fio}

    fuzzy: list[dict] = []
    new: list[dict] = []
    for fio in sorted(to_add_fio):
        key = _first_two(fio)
        candidates = [e for e in existing_fio if _first_two(e) == key]
        if candidates:
            for c in candidates:
                fuzzy.append({"fio_new": fio, "fio_db": c, "dolzhnost": unique[fio]})
        else:
            new.append({"fio": fio, "dolzhnost": unique[fio]})

    return {
        "exact": exact,
        "dismissed_in_tabel": dismissed_in_tabel,
        "fuzzy": fuzzy,
        "new": new,
    }


def apply(
    organizatsiya: str,
    analysis: dict,
    fuzzy_decisions: dict[str, str],
    conn,
) -> dict:
    """Применяет импорт. fuzzy_decisions: {fio_new: 'add'|'skip'}."""
    from config import settings

    inserted = 0
    svar_backfilled = 0
    skipped = 0

    with conn.cursor() as cur:
        # Дозаполнить СВАРЩИКИ для тех кто уже в РАБОТНИКИ
        for item in analysis["exact"]:
            if item["need_svar"]:
                cur.execute(
                    f'INSERT INTO "{settings.db_schema}"."СВАРЩИКИ" '
                    f'("ID_Работника","Статус_Сварщика") VALUES (%s,%s)',
                    (item["id"], "активный"),
                )
                svar_backfilled += 1

        # Новые работники без нечётких совпадений
        for item in analysis["new"]:
            cur.execute(
                f'INSERT INTO "{settings.db_schema}"."РАБОТНИКИ" '
                f'("ФИО","Должность","Организация","Статус") VALUES (%s,%s,%s,%s) '
                f'RETURNING "ID_Работника"',
                (item["fio"], item["dolzhnost"], organizatsiya, "активный"),
            )
            id_rab = cur.fetchone()["ID_Работника"]
            cur.execute(
                f'INSERT INTO "{settings.db_schema}"."СВАРЩИКИ" '
                f'("ID_Работника","Статус_Сварщика") VALUES (%s,%s)',
                (id_rab, "активный"),
            )
            inserted += 1

        # Нечёткие совпадения — по решению пользователя
        for item in analysis["fuzzy"]:
            decision = fuzzy_decisions.get(item["fio_new"], "skip")
            if decision == "add":
                cur.execute(
                    f'INSERT INTO "{settings.db_schema}"."РАБОТНИКИ" '
                    f'("ФИО","Должность","Организация","Статус") VALUES (%s,%s,%s,%s) '
                    f'RETURNING "ID_Работника"',
                    (item["fio_new"], item["dolzhnost"], organizatsiya, "активный"),
                )
                id_rab = cur.fetchone()["ID_Работника"]
                cur.execute(
                    f'INSERT INTO "{settings.db_schema}"."СВАРЩИКИ" '
                    f'("ID_Работника","Статус_Сварщика") VALUES (%s,%s)',
                    (id_rab, "активный"),
                )
                inserted += 1
            else:
                skipped += 1

    return {"inserted": inserted, "svar_backfilled": svar_backfilled, "skipped": skipped}
