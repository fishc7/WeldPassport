import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import context
from sqlalchemy import create_engine, event, inspect, pool

from app.shared.canonical_metadata import canonical_metadata
from app.shared.config import settings
from migrations.canonical_boundary import (
    include_name,
    include_object,
    make_include_object,
)

config = context.config
# ConfigParser трактует '%' как синтаксис интерполяции, поэтому экранируем его.
# Без этого любой alembic-вызов падает, если в пароле БД есть '%'.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = canonical_metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=settings.postgres_schema,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)

    # search_path выставляем на сыром DBAPI-соединении при подключении, а не через
    # connection.execute(): иначе SQLAlchemy 2.0 открывает транзакцию до
    # context.begin_transaction(), Alembic считает её внешней, не коммитит, и на
    # выходе миграции откатываются (upgrade проходит, но таблицы не создаются).
    @event.listens_for(connectable, "connect")
    def _set_search_path(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute(
            f'SET search_path TO "{settings.postgres_schema}", '
            "project, engineering, hr, welding, quality, public"
        )
        cursor.close()

    with connectable.connect() as connection:
        fk_aware_include_object = make_include_object(inspect(connection))
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=settings.postgres_schema,
            include_name=include_name,
            include_object=fk_aware_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
