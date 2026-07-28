"""Isolated Alembic context for the B-04A baseline candidate only."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from alembic import context
from sqlalchemy import create_engine, inspect, pool

from app.shared.canonical_metadata import canonical_metadata
from migrations.b04.disposable import assert_disposable_database, assert_postgresql_16
from migrations.canonical_boundary import include_name, include_object, make_include_object


DATABASE_URL_ENV = "WELDPASSPORT_B04_DATABASE_URL"
ALLOW_DESTRUCTIVE_ENV = "WELDPASSPORT_B04_ALLOW_DESTRUCTIVE"
OWNERSHIP_TOKEN_ENV = "WELDPASSPORT_B04_OWNERSHIP_TOKEN"
EXPECTED_DATABASE_ENV = "WELDPASSPORT_B04_EXPECTED_DATABASE"


def run_migrations_offline() -> None:
    database_url = os.environ.get(DATABASE_URL_ENV, "")
    assert_disposable_database(
        database_url,
        opt_in=os.environ.get(ALLOW_DESTRUCTIVE_ENV),
        ownership_token=os.environ.get(OWNERSHIP_TOKEN_ENV),
        expected_database=os.environ.get(EXPECTED_DATABASE_ENV),
    )
    context.configure(
        url=database_url,
        target_metadata=canonical_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="public",
        version_table_pk=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = os.environ.get(DATABASE_URL_ENV, "")
    assert_disposable_database(
        database_url,
        opt_in=os.environ.get(ALLOW_DESTRUCTIVE_ENV),
        ownership_token=os.environ.get(OWNERSHIP_TOKEN_ENV),
        expected_database=os.environ.get(EXPECTED_DATABASE_ENV),
    )
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )

    with connectable.connect() as connection:
        assert_postgresql_16(connection)
        fk_aware_include_object = make_include_object(inspect(connection))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=canonical_metadata,
            include_schemas=True,
            version_table_schema="public",
            version_table_pk=True,
            include_name=include_name,
            include_object=fk_aware_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
