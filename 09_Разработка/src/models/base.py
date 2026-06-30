from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(DeclarativeBase):
    pass


SCHEMA = settings.db_schema
