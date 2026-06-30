from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import inspect

import models  # noqa: F401 — регистрация всех ORM-классов
from config import settings
from database import engine
from models.base import Base


def main() -> int:
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names(schema=settings.db_schema))
    model_tables = {
        table.name
        for table in Base.metadata.sorted_tables
        if table.schema == settings.db_schema
    }

    missing_in_models = sorted(db_tables - model_tables)
    extra_in_models = sorted(model_tables - db_tables)
    errors: list[str] = []

    if missing_in_models:
        errors.append(f"Таблицы в БД без модели: {', '.join(missing_in_models)}")
    if extra_in_models:
        errors.append(f"Модели без таблицы в БД: {', '.join(extra_in_models)}")

    for table_name in sorted(db_tables & model_tables):
        db_cols = {col["name"] for col in inspector.get_columns(table_name, schema=settings.db_schema)}
        model_table = Base.metadata.tables[f"{settings.db_schema}.{table_name}"]
        model_cols = {col.name for col in model_table.columns}
        if db_cols != model_cols:
            only_db = sorted(db_cols - model_cols)
            only_model = sorted(model_cols - db_cols)
            errors.append(
                f"{table_name}: в БД {only_db or '-'}, в модели {only_model or '-'}"
            )

    if errors:
        print("Проверка моделей: ОШИБКИ")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Проверка моделей: OK ({len(model_tables)} таблиц, схема {settings.db_schema})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
