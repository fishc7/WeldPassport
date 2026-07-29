"""Settings-free SQLAlchemy ORM registry shared by canonical models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The sole declarative registry for the application ORM models."""
