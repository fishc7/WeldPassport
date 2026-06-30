"""JS-API мост для десктоп-приложения ОК (отдел кадров).

Логика не дублируется: мост переиспользует слой сервисов backend
(`WorkforceService`) и работает с PostgreSQL через SQLAlchemy. HTTP не
используется — методы вызываются напрямую из фронтенда через
`window.pywebview.api.*`.

Каждый метод открывает свою сессию БД и закрывает её по завершении.
Ответ всегда обёрнут в конверт {"ok": bool, "data"/"error"} — так фронту
проще единообразно обрабатывать ошибки.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

# Куда переносить обработанные табели после применения импорта.
# Раскладываем по подпапкам организаций: <архив>/<Организация>/<файл>.
TABEL_ARCHIVE_DIR = Path(r"D:\WeldPassport\Работники\Табеля")

# backend — сервис-слой (SQLAlchemy / WorkforceService)
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# src — config, db (psycopg), importers
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from app.shared.db import SessionLocal  # noqa: E402
from app.workforce.models import DolzhnostETKS  # noqa: E402
from app.workforce.schemas import (  # noqa: E402
    RabotnikCreate,
    RabotnikUpdate,
)
from app.workforce.services import WorkforceService  # noqa: E402


def _envelope(func: Callable[..., Any]) -> Callable[..., dict]:
    """Оборачивает результат метода в {"ok": ..., "data"/"error": ...}."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            return {"ok": True, "data": func(*args, **kwargs)}
        except Exception as exc:  # noqa: BLE001 — на фронт уходит текст
            detail = getattr(exc, "detail", None) or str(exc)
            return {"ok": False, "error": detail}

    return wrapper


def _serialize_dolzhnost(d: DolzhnostETKS | None) -> dict | None:
    if d is None:
        return None
    return {
        "id": d.id,
        "nazvanie": d.nazvanie,
        "professiya": d.professiya,
        "razryad": d.razryad,
        "etks_kod": d.etks_kod,
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _worker_list_item(w: Any) -> dict:
    """Лёгкое представление работника для таблицы-реестра."""
    dolzhnost = w.dolzhnost_ref.nazvanie if w.dolzhnost_ref else w.dolzhnost
    return {
        "id_rabotnika": w.id_rabotnika,
        "fio": w.fio,
        "tabelynyy_nomer": w.tabelynyy_nomer,
        "dolzhnost": dolzhnost,
        "organizatsiya": w.organizatsiya,
        "data_priema": _iso(w.data_priema),
        "data_uvolneniya": _iso(w.data_uvolneniya),
        "status": w.status,
        "is_welder": len(w.svarshchiki) > 0,
    }


def _worker_detail(w: Any) -> dict:
    """Полная карточка работника + профили сварщика, если есть."""
    return {
        "id_rabotnika": w.id_rabotnika,
        "fio": w.fio,
        "tabelynyy_nomer": w.tabelynyy_nomer,
        "id_dolzhnosti": w.id_dolzhnosti,
        "dolzhnost_stroka": w.dolzhnost,  # переходный период
        "dolzhnost_ref": _serialize_dolzhnost(w.dolzhnost_ref),
        "organizatsiya": w.organizatsiya,
        "data_priema": _iso(w.data_priema),
        "data_uvolneniya": _iso(w.data_uvolneniya),
        "status": w.status,
        "svarshchiki": [
            {
                "id_svarshchika": s.id_svarshchika,
                "kleymo": s.kleymo,
                "razryad": s.razryad,
                "osnovnoy_sposob_svarки": s.osnovnoy_sposob_svarки,
                "status_svarshchika": s.status_svarshchika,
            }
            for s in w.svarshchiki
        ],
    }


class Api:
    """Объект, который pywebview выставляет как `window.pywebview.api`."""

    def __init__(self) -> None:
        # Временное состояние между preview и apply
        self._tabel_unique: dict = {}
        self._tabel_org: str = ""
        self._tabel_analysis: dict = {}
        self._tabel_paths: list[str] = []
        self._ok1c_analysis: dict = {}
        self._ok1c_org: str = ""

    # ── Справочники ───────────────────────────────────────────────────────

    @_envelope
    def list_dolzhnosti(self) -> list[dict]:
        db = SessionLocal()
        try:
            rows = (
                db.query(DolzhnostETKS)
                .order_by(DolzhnostETKS.professiya, DolzhnostETKS.razryad)
                .all()
            )
            return [_serialize_dolzhnost(d) for d in rows]
        finally:
            db.close()

    # ── Работники ─────────────────────────────────────────────────────────

    @_envelope
    def list_workers(self, limit: int = 1000) -> list[dict]:
        db = SessionLocal()
        try:
            svc = WorkforceService(db)
            return [_worker_list_item(w) for w in svc.list_workers(0, limit)]
        finally:
            db.close()

    @_envelope
    def get_worker(self, worker_id: int) -> dict:
        db = SessionLocal()
        try:
            svc = WorkforceService(db)
            return _worker_detail(svc.get_worker(int(worker_id)))
        finally:
            db.close()

    @_envelope
    def create_worker(self, payload: dict) -> dict:
        db = SessionLocal()
        try:
            svc = WorkforceService(db)
            data = RabotnikCreate(**_clean_worker_payload(payload))
            return _worker_detail(svc.create_worker(data))
        finally:
            db.close()

    @_envelope
    def update_worker(self, worker_id: int, payload: dict) -> dict:
        db = SessionLocal()
        try:
            svc = WorkforceService(db)
            data = RabotnikUpdate(**_clean_worker_payload(payload))
            return _worker_detail(svc.update_worker(int(worker_id), data))
        finally:
            db.close()


    # ── Импорт табеля ─────────────────────────────────────────────────────

    @_envelope
    def pick_tabel_files(self) -> list[str]:
        """Открыть нативный диалог выбора Excel-файлов."""
        import webview  # noqa: PLC0415
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Excel файлы (*.xlsx;*.xls)",),
        )
        return list(result) if result else []

    @_envelope
    def preview_import_tabel(self, paths: list[str], organizatsiya: str) -> dict:
        """Проанализировать файлы табелей, вернуть diff без записи в БД."""
        from pathlib import Path as P
        from importers.tabel_importer import load_from_files, analyze
        from db import get_connection

        unique, errors, file_counts = load_from_files([P(p) for p in paths])
        if not unique:
            return {
                "unique_count": 0, "errors": errors, "file_counts": file_counts,
                "exact": [], "dismissed_in_tabel": [], "fuzzy": [], "new": [],
            }

        with get_connection() as conn:
            analysis = analyze(unique, conn)

        self._tabel_unique = unique
        self._tabel_org = organizatsiya
        self._tabel_analysis = analysis
        self._tabel_paths = list(paths)

        return {
            "unique_count": len(unique),
            "errors": errors,
            "file_counts": file_counts,
            **analysis,
        }

    @_envelope
    def apply_import_tabel(self, fuzzy_decisions: dict) -> dict:
        """Применить импорт табеля. fuzzy_decisions: {fio_new: 'add'|'skip'}."""
        from importers.tabel_importer import apply
        from db import get_connection

        with get_connection() as conn:
            result = apply(
                self._tabel_org,
                self._tabel_analysis,
                fuzzy_decisions,
                conn,
            )

        # Импорт зафиксирован в БД (commit при выходе из with) — теперь
        # переносим исходные файлы в архив. Сбой переноса не должен
        # «отменять» успешный импорт, поэтому ошибки только сообщаем.
        archive = _archive_tabel_files(self._tabel_paths, self._tabel_org)
        result["archived"] = archive["archived"]
        result["archive_errors"] = archive["errors"]

        self._tabel_unique = {}
        self._tabel_analysis = {}
        self._tabel_paths = []
        return result

    # ── Импорт из 1С ──────────────────────────────────────────────────────

    @_envelope
    def pick_1c_file(self) -> str | None:
        """Открыть нативный диалог выбора одного файла 1С-выгрузки."""
        import webview  # noqa: PLC0415
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Excel файлы (*.xlsx;*.xls)",),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    @_envelope
    def preview_import_ok1c(self, path: str, organizatsiya: str) -> dict:
        """Проанализировать 1С-выгрузку, вернуть diff без записи в БД."""
        from pathlib import Path as P
        from importers.ok1c_importer import load_1c, analyze
        from db import get_connection

        ok1c = load_1c(P(path))
        with get_connection() as conn:
            analysis = analyze(ok1c, conn)

        self._ok1c_analysis = analysis
        self._ok1c_org = organizatsiya

        return {"unique_count": len(ok1c), **_serialize_ok1c(analysis)}

    @_envelope
    def apply_import_ok1c(self) -> dict:
        """Применить ранее проанализированную 1С-выгрузку."""
        from importers.ok1c_importer import apply
        from db import get_connection

        if not self._ok1c_analysis:
            raise ValueError("Сначала выполните анализ файла")

        with get_connection() as conn:
            result = apply(self._ok1c_org, self._ok1c_analysis, conn)

        self._ok1c_analysis = {}
        return result


def _serialize_ok1c(analysis: dict) -> dict:
    """Готовит diff 1С для фронта: даты → ISO-строки, поля — в читаемый вид."""
    update = [
        {
            "fio_db": u["fio_db"],
            "fio_ok": u["fio_ok"],
            "matched": u["matched"],
            "need_svar": u["need_svar"],
            "changes": [
                {"field": k, "value": _iso(v) if hasattr(v, "isoformat") else v}
                for k, v in u["fields"].items()
            ]
            + (
                [{"field": "Статус_Сварщика", "value": u["computed_status"]}]
                if u["need_svar_status_upd"]
                else []
            )
            + ([{"field": "профиль СВАРЩИКИ", "value": "создать"}] if u["need_svar"] else []),
        }
        for u in analysis["update"]
    ]
    add = [
        {
            "fio": a["fio"],
            "raw": a["raw"] if a["raw"] != a["fio"] else None,
            "dolzhnost": a["dolzhnost"],
            "data_priema": _iso(a["data_priema"]),
            "data_uv": _iso(a["data_uv"]),
            "status": a["status"],
        }
        for a in analysis["add"]
    ]
    return {
        "update": update,
        "add": add,
        "missing_from_1c": analysis["missing_from_1c"],
    }


def _safe_folder_name(name: str) -> str:
    """Готовит имя организации для использования как имя папки."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip())
    cleaned = cleaned.rstrip(". ")  # Windows не любит хвостовые точки/пробелы
    return cleaned or "Без организации"


def _archive_tabel_files(paths: list[str], organizatsiya: str) -> dict:
    """Переносит обработанные файлы табелей в архив по организациям.

    <TABEL_ARCHIVE_DIR>/<Организация>/<файл>. При конфликте имени к имени
    добавляется метка даты-времени, чтобы ничего не перезаписать.
    Возвращает {"archived": [...], "errors": [...]}.
    """
    archived: list[str] = []
    errors: list[str] = []

    target_dir = TABEL_ARCHIVE_DIR / _safe_folder_name(organizatsiya)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"archived": [], "errors": [f"Не удалось создать папку архива: {exc}"]}

    for raw in paths:
        src = Path(raw)
        if not src.exists():
            errors.append(f"Файл не найден, пропущен: {src.name}")
            continue

        dest = target_dir / src.name
        if dest.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = target_dir / f"{src.stem}_{stamp}{src.suffix}"

        try:
            _move_file(src, dest)
            archived.append(str(dest))
        except OSError as exc:
            errors.append(
                f"Не удалось перенести {src.name} "
                f"(возможно, файл открыт в Excel): {exc}"
            )

    return {"archived": archived, "errors": errors}


def _move_file(src: Path, dest: Path) -> None:
    """Переносит файл, не оставляя дубликатов при блокировке.

    Сначала пробуем атомарное переименование (один диск). Если не вышло
    (другой диск или временная блокировка) — копируем и удаляем оригинал;
    если оригинал удалить не удалось (файл занят), убираем копию и
    поднимаем ошибку, чтобы в архиве не оставалось «полуперенесённых» файлов.
    """
    try:
        os.replace(src, dest)
        return
    except OSError:
        pass

    shutil.copy2(src, dest)
    try:
        os.remove(src)
    except OSError:
        # откатываем копию — иначе получим дубль (и в архиве, и в источнике)
        try:
            os.remove(dest)
        except OSError:
            pass
        raise


def _clean_worker_payload(payload: dict) -> dict:
    """Приводит пустые строки из формы к None, чтобы не писать '' в БД."""
    cleaned: dict = {}
    for key, value in (payload or {}).items():
        if isinstance(value, str):
            value = value.strip()
            value = value or None
        if key == "id_dolzhnosti" and value is not None:
            value = int(value)
        cleaned[key] = value
    return cleaned
