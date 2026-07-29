"""Разбор канонического XLSX и нормализация строк (Task 8E, §4 задания).

Чистый модуль без БД и HTTP: загрузка книги через openpyxl, структурная проверка
(ZIP/XML, версия шаблона, обязательные колонки, лимиты строк/групп), нормализация
значений строк и row-level валидация типов/обязательности. Прямой записи в БД нет —
результат передаётся сервису для формирования staging.

Канонический макет книги:
* лист `meta` — метаданные key→value в колонках A/B, обязателен ключ
  `template_version`;
* лист данных (первый лист, не `meta`) — строка 1 = технические ключи колонок,
  строки 2..N — данные (одна строка = Joint + одна WeldOperation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

from app.engineering import import_workflow as iw
from app.engineering.services import normalize_joint_no
from app.engineering.weld_operation_workflow import WELD_STAGES

META_SHEET = "meta"
DATA_SHEET = "joints"
TEMPLATE_VERSION_KEY = "template_version"

# ── Row-level коды валидации (в error_codes строки) ───────────────────────────
ROW_REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"  # + ":<field>"
ROW_INVALID_WELD_STAGE = "INVALID_WELD_STAGE"
ROW_INVALID_PERFORMED_ON = "INVALID_PERFORMED_ON"
ROW_INVALID_TIMESTAMP = "INVALID_TIMESTAMP"  # + ":<field>"

_UPPERCASE_FIELDS = ("weld_stage", "welding_method")


class ParseStructureError(Exception):
    """Структурная ошибка книги: staging-строки не создаются (§4)."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass
class ParsedRow:
    row_number: int
    raw: dict[str, str | None]
    normalized: dict[str, str | None]
    normalized_joint_no: str | None
    error_codes: list[str]
    is_empty: bool
    # Ключ-основа для оценки количества групп (project/line/isometric/revision/joint).
    group_basis: tuple[str, str, str, str] | None


@dataclass
class ParseResult:
    template_version: str
    present_columns: list[str]
    unknown_columns: list[str]
    rows: list[ParsedRow] = field(default_factory=list)
    rows_read: int = 0
    rows_empty: int = 0

    @property
    def rows_error(self) -> int:
        return sum(1 for r in self.rows if r.error_codes)


def _cell_to_str(value: object) -> str | None:
    """Приводит значение ячейки к очищенной строке; пусто → None."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, datetime):
        # Дата+время без микросекунд; голая дата — ISO-день.
        if value.hour or value.minute or value.second:
            return value.isoformat()
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() or None


def _normalize_date(raw: str | None) -> str | None:
    if raw is None:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    # ISO с временем → берём дату.
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


def _normalize_timestamp(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _load_workbook(data: bytes):
    try:
        from openpyxl import load_workbook  # noqa: PLC0415 - ленивый импорт

        return load_workbook(BytesIO(data), read_only=True, data_only=True)
    except ParseStructureError:
        raise
    except Exception as exc:  # noqa: BLE001 - любая ошибка чтения = повреждённый XLSX
        raise ParseStructureError(
            iw.IMPORT_FILE_CORRUPT, "Файл повреждён или не является корректным XLSX"
        ) from exc


def _read_template_version(wb) -> str:
    if META_SHEET not in wb.sheetnames:
        raise ParseStructureError(
            iw.IMPORT_TEMPLATE_VERSION_UNSUPPORTED,
            "В книге отсутствует лист meta с template_version",
        )
    meta = wb[META_SHEET]
    version: str | None = None
    for row in meta.iter_rows(values_only=True):
        if not row:
            continue
        key = _cell_to_str(row[0]) if len(row) >= 1 else None
        val = _cell_to_str(row[1]) if len(row) >= 2 else None
        if key == TEMPLATE_VERSION_KEY:
            version = val
            break
    if version is None:
        raise ParseStructureError(
            iw.IMPORT_TEMPLATE_VERSION_UNSUPPORTED,
            "В листе meta не задан template_version",
        )
    if version not in iw.SUPPORTED_TEMPLATE_VERSIONS:
        raise ParseStructureError(
            iw.IMPORT_TEMPLATE_VERSION_UNSUPPORTED,
            f"Версия шаблона {version} не поддерживается",
            template_version=version,
        )
    return version


def _data_sheet(wb):
    for name in wb.sheetnames:
        if name != META_SHEET:
            return wb[name]
    raise ParseStructureError(
        iw.IMPORT_MISSING_REQUIRED_COLUMN, "В книге нет листа данных"
    )


def _read_headers(sheet) -> list[str]:
    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if header_row is None:
        return []
    return [_cell_to_str(c) or "" for c in header_row]


def _normalize_row(
    row_number: int, raw: dict[str, str | None]
) -> ParsedRow:
    normalized: dict[str, str | None] = {}
    errors: list[str] = []
    for field_name in iw.NORMALIZED_FIELDS:
        value = raw.get(field_name)
        if value is not None and field_name in _UPPERCASE_FIELDS:
            value = value.upper()
        normalized[field_name] = value

    # Типизация даты/времени.
    if normalized.get("performed_on") is not None:
        iso = _normalize_date(normalized["performed_on"])
        if iso is None:
            errors.append(ROW_INVALID_PERFORMED_ON)
        normalized["performed_on"] = iso if iso is not None else normalized["performed_on"]
    for ts_field in ("started_at", "finished_at"):
        if normalized.get(ts_field) is not None:
            iso = _normalize_timestamp(normalized[ts_field])
            if iso is None:
                errors.append(f"{ROW_INVALID_TIMESTAMP}:{ts_field}")
            else:
                normalized[ts_field] = iso

    # Обязательные нормализованные поля.
    for req in iw.REQUIRED_NORMALIZED_FIELDS:
        if not normalized.get(req):
            errors.append(f"{ROW_REQUIRED_FIELD_MISSING}:{req}")

    # Валидность классифицированного этапа.
    stage = normalized.get("weld_stage")
    if stage is not None and stage not in WELD_STAGES:
        errors.append(ROW_INVALID_WELD_STAGE)

    joint_no = normalized.get("joint_no")
    normalized_joint_no = normalize_joint_no(joint_no) if joint_no else None

    line = normalized.get("line_code") or ""
    iso_no = normalized.get("isometric_no") or ""
    rev = normalized.get("revision_code") or ""
    basis = (
        (line, iso_no, rev, normalized_joint_no)
        if normalized_joint_no
        else None
    )
    return ParsedRow(
        row_number=row_number,
        raw=raw,
        normalized=normalized,
        normalized_joint_no=normalized_joint_no,
        error_codes=errors,
        is_empty=False,
        group_basis=basis,
    )


def parse_workbook(
    data: bytes, *, max_rows: int, max_groups: int
) -> ParseResult:
    """Полный разбор книги с структурной проверкой (§4).

    Бросает `ParseStructureError` при нарушении структуры/лимитов — тогда staging
    не создаётся. Пустые строки не создают записи, но учитываются в отчёте."""
    wb = _load_workbook(data)
    try:
        template_version = _read_template_version(wb)
        sheet = _data_sheet(wb)
        headers = _read_headers(sheet)
        present = [h for h in headers if h]

        missing = [c for c in iw.REQUIRED_COLUMNS if c not in present]
        if missing:
            raise ParseStructureError(
                iw.IMPORT_MISSING_REQUIRED_COLUMN,
                "Отсутствуют обязательные колонки: " + ", ".join(missing),
                missing_columns=missing,
            )
        unknown = [h for h in present if h not in iw.KNOWN_COLUMNS]

        result = ParseResult(
            template_version=template_version,
            present_columns=present,
            unknown_columns=unknown,
        )
        group_bases: set[tuple[str, str, str, str]] = set()
        excel_row = 1
        for row_values in sheet.iter_rows(min_row=2, values_only=True):
            excel_row += 1
            raw: dict[str, str | None] = {}
            for idx, header in enumerate(headers):
                if not header:
                    continue
                value = row_values[idx] if idx < len(row_values) else None
                raw[header] = _cell_to_str(value)
            # Полностью пустая строка: не создаёт staging, учитывается отдельно (§4).
            if all(v is None for v in raw.values()):
                result.rows_empty += 1
                continue
            result.rows_read += 1
            if result.rows_read > max_rows:
                raise ParseStructureError(
                    iw.IMPORT_TOO_MANY_ROWS,
                    f"Превышен лимит непустых строк ({max_rows})",
                    max_rows=max_rows,
                )
            parsed = _normalize_row(excel_row, raw)
            if parsed.group_basis is not None:
                group_bases.add(parsed.group_basis)
                if len(group_bases) > max_groups:
                    raise ParseStructureError(
                        iw.IMPORT_TOO_MANY_GROUPS,
                        f"Превышен лимит создаваемых групп ({max_groups})",
                        max_groups=max_groups,
                    )
            result.rows.append(parsed)
        return result
    finally:
        wb.close()


# ══════════════════════════════════════════════════════════════════════════════
# Построение канонической книги (для тестов и будущего экспорта шаблона)
# ══════════════════════════════════════════════════════════════════════════════
def build_workbook(
    rows: list[dict[str, object]],
    *,
    template_version: str = "1.0",
    columns: tuple[str, ...] | None = None,
    extra_columns: tuple[str, ...] = (),
    omit_columns: tuple[str, ...] = (),
) -> bytes:
    """Собирает канонический XLSX в память (bytes).

    `columns` по умолчанию — обязательные + необязательные распознаваемые. Через
    `extra_columns` добавляются неизвестные колонки, через `omit_columns` — можно
    исключить обязательную (для теста отсутствующей колонки)."""
    from openpyxl import Workbook  # noqa: PLC0415

    base = columns or (iw.REQUIRED_COLUMNS + iw.OPTIONAL_COLUMNS)
    headers = [c for c in base if c not in omit_columns] + list(extra_columns)

    wb = Workbook()
    meta = wb.active
    meta.title = META_SHEET
    meta.append([TEMPLATE_VERSION_KEY, template_version])

    data = wb.create_sheet(DATA_SHEET)
    data.append(headers)
    for row in rows:
        data.append([row.get(h) for h in headers])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
