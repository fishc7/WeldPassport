"""Точка входа десктоп-приложения ОК (отдел кадров) на pywebview.

Запуск из каталога 09_Разработка:

    python desktop_ok/main.py

Конфигурация БД читается backend-слоем из .env (см. app.shared.config).
"""

from __future__ import annotations

import os
from pathlib import Path

# backend.app.shared.config читает .env из текущего каталога, причём уже на
# этапе импорта (settings = Settings(), create_engine(...)). Поэтому смену
# каталога на 09_Разработка (где лежит .env) нужно сделать ДО импорта api,
# иначе при запуске из папки desktop_ok пароль к БД не подхватится.
os.chdir(Path(__file__).resolve().parents[1])

import webview  # noqa: E402

from api import Api  # noqa: E402

_WEB = Path(__file__).resolve().parent / "web" / "index.html"


def main() -> None:
    webview.create_window(
        title="WeldPassport — ОК · Персонал",
        url=str(_WEB),
        js_api=Api(),
        width=1280,
        height=820,
        min_size=(960, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
