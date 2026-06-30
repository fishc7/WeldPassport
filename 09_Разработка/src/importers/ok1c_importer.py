"""Логика импорта / периодического обновления из 1С-выгрузки ОК.

Используется и CLI-скриптом (tools/import_ok1c_all.py), и desktop_ok/api.py —
логика не дублируется.

Из 1С берётся: ФИО, Должность, Дата приёма, Дата увольнения.
Статус вычисляется: 'уволен' если есть Дата_Увольнения ≤ сегодня, иначе 'активный'.

Поля, управляемые 1С (перезаписываются при изменении):
  РАБОТНИКИ: Должность, Дата_Приема, Дата_Увольнения, Статус
  СВАРЩИКИ:  Статус_Сварщика
Поля, управляемые вручную (не трогаются):
  РАБОТНИКИ: Табельный_Номер, Организация
  СВАРЩИКИ:  Клеймо, Разряд, Основной_Способ_Сварки
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

_PATRONYMIC_RE = re.compile(
    r"(о|е)в(ич|на)$|ич$|(ин)а$|овна$|евна$|ична$|иевна$|ьевич$|ьевна$",
    re.IGNORECASE,
)


def _clean_fio(raw: str) -> str:
    s = str(raw).strip()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\bЭТК\b", "", s)
    s = re.sub(r"\bвн\.?\s*совм\.?\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bс\s+\d[\d/\.]+", "", s)
    s = re.sub(r"\bпо\s+\d[\d/\.]+\b", "", s)
    s = re.sub(r"\bдо\s+\d+/\d+\b", "", s)
    s = re.sub(r"\b\d+\b", "", s)
    s = re.sub(r"\bТобольск\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s).strip()
    parts = s.split()
    if not parts:
        return ""
    if len(parts) <= 2:
        return s
    return " ".join(parts[:3]) if _PATRONYMIC_RE.search(parts[2]) else " ".join(parts[:2])


def _parse_date(val) -> date | None:
    try:
        d, m, y = str(val).strip().split(".")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _normalize(s: str) -> str:
    return s.lower().replace("ё", "е")


def _first_two(fio: str) -> str:
    return _normalize(" ".join(fio.strip().split()[:2]))


def _status_from_uv(uv: date | None) -> str:
    return "уволен" if (uv and uv <= date.today()) else "активный"


def load_1c(path: Path) -> dict[str, dict]:
    """Читает 1С-файл → {clean_fio: {raw, dolzhnost, data_priema, data_uv}}.

    Для людей с несколькими периодами берём период с наибольшей Дата_Приема.
    """
    xl = pd.ExcelFile(path)
    sheet = "Лист_1" if "Лист_1" in xl.sheet_names else xl.sheet_names[0]
    df = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)

    header_row = next(
        (
            i
            for i, row in df.iterrows()
            if row.astype(str).str.contains("Сотрудник", na=False).any()
        ),
        None,
    )
    if header_row is None:
        raise ValueError(
            "Не найден заголовок «Сотрудник» — это точно выгрузка 1С по сотрудникам?"
        )

    data = df.iloc[header_row + 1:].copy()
    data.columns = range(len(data.columns))
    rows = data[data[1].notna() & (data[1] != "nan")]

    periods: dict[str, list[dict]] = {}
    for _, row in rows.iterrows():
        raw = str(row[1]).strip()
        clean = _clean_fio(raw)
        if not clean or len(clean) < 4:
            continue
        dol = str(row[5]).strip() if pd.notna(row[5]) and str(row[5]) != "nan" else ""
        priema = _parse_date(row[11]) if pd.notna(row[11]) and str(row[11]) != "nan" else None
        uv = _parse_date(row[13]) if pd.notna(row[13]) and str(row[13]) != "nan" else None
        periods.setdefault(clean, []).append(
            {"raw": raw, "dolzhnost": dol, "data_priema": priema, "data_uv": uv}
        )

    ok1c: dict[str, dict] = {}
    for clean, ps in periods.items():
        with_date = [p for p in ps if p["data_priema"] is not None]
        latest = max(with_date, key=lambda p: p["data_priema"]) if with_date else ps[0]
        if not latest["dolzhnost"]:
            for p in ps:
                if p["dolzhnost"]:
                    latest["dolzhnost"] = p["dolzhnost"]
                    break
        ok1c[clean] = latest

    return ok1c


def analyze(ok1c: dict[str, dict], conn) -> dict:
    """Сравнивает 1С-снимок с БД. Возвращает категоризированный diff.

    Структура (даты — объекты date, сериализуются на уровне api.py):
        update          — есть в БД, изменились 1С-поля (или нет профиля СВАРЩИКИ)
        add             — новых, совпадений нет
        missing_from_1c — активные в БД, которых нет в выгрузке (предупреждение)
    """
    from config import settings

    with conn.cursor() as cur:
        cur.execute(
            f'SELECT "ID_Работника", "ФИО", "Должность", "Дата_Приема", '
            f'"Дата_Увольнения", "Статус" '
            f'FROM "{settings.db_schema}"."РАБОТНИКИ"'
        )
        db_all = {row["ФИО"]: dict(row) for row in cur.fetchall()}

        cur.execute(
            f'SELECT "ID_Работника", "Статус_Сварщика" '
            f'FROM "{settings.db_schema}"."СВАРЩИКИ"'
        )
        svar_map = {row["ID_Работника"]: row["Статус_Сварщика"] for row in cur.fetchall()}

    db_by_two: dict[str, list[str]] = {}
    for fio in db_all:
        db_by_two.setdefault(_first_two(fio), []).append(fio)

    to_update: list[dict] = []
    to_add: list[dict] = []
    matched_db: set[str] = set()

    for clean_fio, info in ok1c.items():
        computed_status = _status_from_uv(info["data_uv"])

        # Матчинг: точное → нечёткое (единственный кандидат)
        db_fio = clean_fio if clean_fio in db_all else None
        if db_fio is None:
            key = _first_two(clean_fio)
            cands = [f for f in db_by_two.get(key, []) if f not in matched_db]
            if len(cands) == 1:
                db_fio = cands[0]

        if db_fio:
            matched_db.add(db_fio)
            db_rec = db_all[db_fio]
            worker_id = db_rec["ID_Работника"]
            need_svar = worker_id not in svar_map

            fields: dict[str, object] = {}
            if info["dolzhnost"] and info["dolzhnost"] != (db_rec["Должность"] or ""):
                fields["Должность"] = info["dolzhnost"]
            if info["data_priema"] and info["data_priema"] != db_rec["Дата_Приема"]:
                fields["Дата_Приема"] = info["data_priema"]
            if info["data_uv"] != db_rec["Дата_Увольнения"]:
                fields["Дата_Увольнения"] = info["data_uv"]
            if computed_status != db_rec["Статус"]:
                fields["Статус"] = computed_status

            need_svar_status_upd = (
                not need_svar and svar_map.get(worker_id) != computed_status
            )

            if fields or need_svar or need_svar_status_upd:
                to_update.append({
                    "fio_db": db_fio,
                    "fio_ok": clean_fio,
                    "matched": "exact" if db_fio == clean_fio else "fuzzy",
                    "id": worker_id,
                    "need_svar": need_svar,
                    "need_svar_status_upd": need_svar_status_upd,
                    "computed_status": computed_status,
                    "fields": fields,
                })
        else:
            to_add.append({
                "fio": clean_fio,
                "raw": info["raw"],
                "dolzhnost": info["dolzhnost"],
                "data_priema": info["data_priema"],
                "data_uv": info["data_uv"],
                "status": computed_status,
            })

    missing_from_1c = sorted(
        fio
        for fio, rec in db_all.items()
        if fio not in matched_db and rec["Статус"] == "активный"
    )

    return {
        "update": sorted(to_update, key=lambda x: x["fio_db"]),
        "add": sorted(to_add, key=lambda x: x["fio"]),
        "missing_from_1c": missing_from_1c,
    }


def apply(organizatsiya: str, analysis: dict, conn) -> dict:
    """Применяет diff к БД. Возвращает счётчики."""
    from config import settings

    updated = 0
    svar_created = 0
    added = 0
    today = date.today()

    with conn.cursor() as cur:
        for u in analysis["update"]:
            if u["fields"]:
                set_parts = [f'"{k}" = %s' for k in u["fields"]]
                params = list(u["fields"].values()) + [u["id"]]
                cur.execute(
                    f'UPDATE "{settings.db_schema}"."РАБОТНИКИ" '
                    f'SET {", ".join(set_parts)} WHERE "ID_Работника" = %s',
                    params,
                )
            if u["need_svar"]:
                cur.execute(
                    f'INSERT INTO "{settings.db_schema}"."СВАРЩИКИ" '
                    f'("ID_Работника","Статус_Сварщика") VALUES (%s,%s)',
                    (u["id"], u["computed_status"]),
                )
                svar_created += 1
            elif u["need_svar_status_upd"]:
                cur.execute(
                    f'UPDATE "{settings.db_schema}"."СВАРЩИКИ" '
                    f'SET "Статус_Сварщика" = %s WHERE "ID_Работника" = %s',
                    (u["computed_status"], u["id"]),
                )
            if u["fields"] or u["need_svar"] or u["need_svar_status_upd"]:
                updated += 1

        for a in analysis["add"]:
            cur.execute(
                f'INSERT INTO "{settings.db_schema}"."РАБОТНИКИ" '
                f'("ФИО","Должность","Организация","Дата_Приема","Дата_Увольнения","Статус") '
                f'VALUES (%s,%s,%s,%s,%s,%s) RETURNING "ID_Работника"',
                (a["fio"], a["dolzhnost"], organizatsiya,
                 a["data_priema"], a["data_uv"], a["status"]),
            )
            id_rab = cur.fetchone()["ID_Работника"]
            svar_status = "уволен" if (a["data_uv"] and a["data_uv"] <= today) else "активный"
            cur.execute(
                f'INSERT INTO "{settings.db_schema}"."СВАРЩИКИ" '
                f'("ID_Работника","Статус_Сварщика") VALUES (%s,%s)',
                (id_rab, svar_status),
            )
            added += 1

    return {"updated": updated, "added": added, "svar_created": svar_created}
