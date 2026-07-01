"""HTTP-обёртка над JS-API десктоп-модуля ОК — чтобы тот же интерфейс
открывался внутри веб-фронтенда (React) во вкладке «ОК», а не как отдельное
окно pywebview.

Переиспользует тот же класс ``Api`` из ``api.py`` (логика и слой сервисов не
дублируются). Методы работы с данными вызываются через единый диспетчер
``POST /api/call/{method}`` и возвращают тот же конверт ``{"ok", "data"/"error"}``,
который уже ждёт ``web/app.js`` — поэтому сам ``app.js`` не меняется.

Нативные файловые диалоги (``pick_tabel_files`` / ``pick_1c_file``) в браузере
недоступны: вместо них фронт открывает обычный ``<input type=file>``, грузит
файлы на ``POST /api/upload``, а уже серверные пути попадают в
``preview_import_*``. Подмену делает ``web/_webshim.js`` (см. там же).

Запуск из каталога ``09_Разработка``::

    python desktop_ok/server.py

Конфигурация БД читается backend-слоем из ``.env`` — как и в ``main.py``,
поэтому каталог меняем на ``09_Разработка`` ДО импорта ``api``.
"""

from __future__ import annotations

import os
from pathlib import Path

# api.py (через backend.app.shared.config и src/config) читает .env из текущего
# каталога уже на этапе импорта. Меняем cwd до импорта api — иначе пароль к БД
# не подхватится, как и в desktop_ok/main.py.
os.chdir(Path(__file__).resolve().parents[1])

import tempfile  # noqa: E402

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from api import Api  # noqa: E402

_WEB = Path(__file__).resolve().parent / "web"

# Папка под загруженные через браузер файлы импорта. Файлы табелей отсюда
# забирает apply_import_tabel и переносит в архив; имя сохраняем исходным.
_UPLOADS = Path(tempfile.gettempdir()) / "weldpassport_ok_uploads"
_UPLOADS.mkdir(parents=True, exist_ok=True)

# Один общий экземпляр Api на процесс. Он хранит состояние между preview и apply
# (self._tabel_analysis и т.п.) — ровно как в десктопе, где Api() живёт всё время
# работы окна. Расчёт на одного локального пользователя; для многопользовательского
# режима это состояние нужно будет вынести из экземпляра.
_api = Api()

# Методы, которые НЕЛЬЗЯ вызывать по HTTP: открывают нативные диалоги ОС и без
# окна pywebview работать не будут. Их роль на фронте берёт на себя _webshim.js.
_BLOCKED = {"pick_tabel_files", "pick_1c_file"}

app = FastAPI(title="WeldPassport — ОК (web)", version="0.1.0")

# Документ iframe грузится с того же origin (:8077), поэтому /api/* для него —
# same-origin и CORS не требуется. Заголовки оставлены на случай прямых fetch
# с dev-сервера Vite (:5173).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CallBody(BaseModel):
    args: list = []


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Отдаёт тот же index.html, что и десктоп, но с подключённым _webshim.js.

    Десктопный web/index.html не трогаем — шим подмешиваем на лету только в
    веб-режиме, прямо перед app.js."""
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '<script src="app.js"></script>',
        '<script src="_webshim.js"></script>\n  <script src="app.js"></script>',
    )
    return HTMLResponse(html)


@app.post("/api/call/{method}")
def call(method: str, body: CallBody):
    """Единый диспетчер: вызывает Api.<method>(*args) и возвращает его конверт."""
    if method in _BLOCKED:
        raise HTTPException(400, f"Метод {method} недоступен в веб-режиме")
    if method.startswith("_"):
        raise HTTPException(404, f"Неизвестный метод: {method}")
    fn = getattr(_api, method, None)
    if not callable(fn):
        raise HTTPException(404, f"Неизвестный метод: {method}")
    return fn(*body.args)  # уже {"ok": ..., "data"/"error": ...} через @_envelope


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Сохраняет выбранные в браузере файлы во временную папку, возвращает пути.

    Имя файла оставляем исходным (только отбрасываем каталожную часть), чтобы
    архивация табелей в apply_import_tabel клала их под тем же именем."""
    saved: list[str] = []
    for uf in files:
        name = Path(uf.filename or "file").name
        dest = _UPLOADS / name
        if dest.exists():  # не перезаписываем при совпадении имени
            i = 1
            while (cand := _UPLOADS / f"{dest.stem}_{i}{dest.suffix}").exists():
                i += 1
            dest = cand
        dest.write_bytes(await uf.read())
        saved.append(str(dest))
    return {"ok": True, "data": saved}


# Статика OK-модуля (app.js, styles.css, _webshim.js). Монтируем последней, чтобы
# явные маршруты выше (/, /api/*) имели приоритет.
app.mount("/", StaticFiles(directory=str(_WEB)), name="web")


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8077)


if __name__ == "__main__":
    main()
