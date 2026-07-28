"""Isolated B-04A context for replaying only the frozen historical revisions."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import URL, create_engine, event, pool


_REQUIRED_ENVIRONMENT = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_SCHEMA",
)
_SEARCH_PATH = "SET search_path TO test, project, engineering, hr, welding, quality, public"


def _database_url() -> URL:
    values = {name: os.environ.get(name) for name in _REQUIRED_ENVIRONMENT}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise RuntimeError("B04-HISTORICAL-ENVIRONMENT")
    if values["POSTGRES_SCHEMA"] != "test":
        raise RuntimeError("B04-HISTORICAL-SCHEMA")
    try:
        port = int(str(values["POSTGRES_PORT"]))
    except ValueError as exc:
        raise RuntimeError("B04-HISTORICAL-PORT") from exc
    return URL.create(
        "postgresql+psycopg",
        username=str(values["POSTGRES_USER"]),
        password=str(values["POSTGRES_PASSWORD"]),
        host=str(values["POSTGRES_HOST"]),
        port=port,
        database=str(values["POSTGRES_DB"]),
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="test",
        version_table_pk=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _bootstrap_test_schema(connection: object) -> None:
    """Create the disposable historical marker schema exactly once, or fail closed."""
    connection.exec_driver_sql('CREATE SCHEMA "test"')  # type: ignore[union-attr]
    connection.commit()  # type: ignore[union-attr]


def run_migrations_online() -> None:
    connectable = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )

    @event.listens_for(connectable, "connect")
    def _set_search_path(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
        cursor.execute(_SEARCH_PATH)
        cursor.close()

    with connectable.connect() as connection:
        _bootstrap_test_schema(connection)
        context.configure(
            connection=connection,
            version_table_schema="test",
            version_table_pk=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
