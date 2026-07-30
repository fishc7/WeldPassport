from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.shared.database_bootstrap import get_or_bind_working_target
from app.shared.config import settings
from app.shared.orm import Base

SCHEMA = settings.postgres_schema

database_target = get_or_bind_working_target(settings.database_url)
engine = create_engine(
    database_target.url.render_as_string(hide_password=False)
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute(
        f'SET search_path TO "{SCHEMA}", identity, project, engineering, hr, welding, quality, public'
    )
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
