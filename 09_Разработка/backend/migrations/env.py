import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import context
from sqlalchemy import create_engine, event, pool

from app.shared.config import settings
from app.shared.db import Base
import app.engineering.models  # noqa: F401
import app.hr.models  # noqa: F401
import app.projects.models  # noqa: F401
import app.welding.models  # noqa: F401
import app.workforce.models  # noqa: F401

config = context.config
# ConfigParser трактует '%' как синтаксис интерполяции, поэтому экранируем его.
# Без этого любой alembic-вызов падает, если в пароле БД есть '%'.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata

WORKFORCE_MANAGED_TABLES = {
    "СПРАВОЧНИК_ДОЛЖНОСТЕЙ",
    "РАБОТНИКИ",
    "СВАРЩИКИ",
    "ДОКУМЕНТЫ_СВАРЩИКА",
    "АТТЕСТАЦИИ_СВАРЩИКОВ",
    "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ",
    "ДОПУСКИ_К_ОБЪЕКТУ",
}

HR_MANAGED_TABLES = {
    "departments",
    "positions",
    "workers",
    "worker_roles",
}

WELDING_MANAGED_TABLES = {
    "welders",
    "welder_admissions",
}

PROJECT_MANAGED_TABLES = {
    "companies",
    "projects",
    "project_companies",
    "lines",
}

ENGINEERING_MANAGED_TABLES = {
    "engineering_documents",
    "document_revisions",
}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        schema = getattr(obj, "schema", None)
        if schema == "hr":
            return name in HR_MANAGED_TABLES
        if schema == "welding":
            return name in WELDING_MANAGED_TABLES
        if schema == "project":
            return name in PROJECT_MANAGED_TABLES
        if schema == "engineering":
            return name in ENGINEERING_MANAGED_TABLES
        return name in WORKFORCE_MANAGED_TABLES
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

    # search_path выставляем на сыром DBAPI-соединении при подключении, а не через
    # connection.execute(): иначе SQLAlchemy 2.0 открывает транзакцию до
    # context.begin_transaction(), Alembic считает её внешней, не коммитит, и на
    # выходе миграции откатываются (upgrade проходит, но таблицы не создаются).
    @event.listens_for(connectable, "connect")
    def _set_search_path(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute(
            f'SET search_path TO "{settings.postgres_schema}", '
            "project, engineering, hr, welding, public"
        )
        cursor.close()

    with connectable.connect() as connection:
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
