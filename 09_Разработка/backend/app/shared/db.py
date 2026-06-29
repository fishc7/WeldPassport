from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.shared.config import settings

SCHEMA = settings.postgres_schema

engine = create_engine(settings.database_url)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute(f'SET search_path TO "{SCHEMA}", public')
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
