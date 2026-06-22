"""Создание новых таблиц в БД (только отсутствующих, существующие не трогает)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import settings
from database import engine
from models import Base  # импортирует все модели, включая DolzhnostETKS


def main() -> None:
    print(f"БД: {settings.db_name}, схема: {settings.db_schema}")
    print("Создание таблиц (checkfirst=True — существующие пропускаются)...")
    Base.metadata.create_all(engine, checkfirst=True)
    print("Готово.")


if __name__ == "__main__":
    main()
