"""Единый формат отчёта импорта для ОК."""
from __future__ import annotations

from typing import Any


def empty_import_report() -> dict[str, Any]:
    return {
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "svar_backfilled": 0,
        "errors": [],
        "warnings": [],
    }


def format_import_report_summary(report: dict[str, Any]) -> str:
    parts: list[str] = []
    if report.get("added"):
        parts.append(f"добавлено: {report['added']}")
    if report.get("updated"):
        parts.append(f"обновлено: {report['updated']}")
    if report.get("skipped"):
        parts.append(f"пропущено: {report['skipped']}")
    if report.get("svar_backfilled"):
        parts.append(f"профили сварщика: {report['svar_backfilled']}")
    if not parts:
        parts.append("изменений нет")
    return ", ".join(parts)

