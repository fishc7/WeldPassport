import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.shared.config import settings
from app.shared.db import Base
import app.workforce.models  # noqa: F401 — регистрирует модели в Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata

# Таблицы, которыми управляет Alembic (только workforce на первом этапе).
# Остальные таблицы в схеме (СТЫКИ, ОБЪЕКТЫ и т.д.) не трогаем.
_MANAGED_TABLES = {
    "СПРАВОЧНИК_ДОЛЖНОСТЕЙ",
    "РАБОТНИКИ",
    "СВАРЩИКИ",
    "ДОКУМЕНТЫ_СВАРЩИКА",
    "АТТЕСТАЦИИ_СВАРЩИКОВ",
    "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ",
    "ДОПУСКИ_К_ОБЪЕКТУ",
}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in _MANAGED_TABLES
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=settings.postgres_schema,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.execute(
            text(f'SET search_path TO "{settings.postgres_schema}", public')
        )
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=settings.postgres_schema,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
