"""Fail-closed, socket-free validation for B-04A disposable databases."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


_DISPOSABLE_DATABASE_RE = re.compile(
    r"^wp_b04_[a-z0-9][a-z0-9_]*_disposable$"
)
_PROHIBITED_DATABASES = frozenset(
    {"postgres", "template0", "template1", "weldpassport"}
)
_PRODUCTION_ALIAS_SEGMENTS = frozenset(
    {"prod", "production", "live", "primary", "system"}
)
_SECRET_CLASS_RE = re.compile(r"[a-zA-Z]|[0-9]|[^a-zA-Z0-9\s]")


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    """Sanitized database identity suitable for diagnostics and assertions."""

    database: str
    host: str
    port: int
    username: str


def _is_secret_like(value: str | None) -> bool:
    if value is None or len(value.strip()) < 16:
        return False
    character_classes = {
        "letter" if character.isalpha() else "digit" if character.isdigit() else "other"
        for character in value
        if not character.isspace()
    }
    return len(character_classes) >= 2 and bool(_SECRET_CLASS_RE.search(value))


def _reject(code: str) -> None:
    raise ValueError(f"B04-DISPOSABLE-{code}")


def _parse_url_without_exception_context(
    database_url: str,
) -> tuple[Any, int | None] | None:
    """Parse URL identity without retaining a parser exception on the caller."""
    try:
        url = make_url(database_url)
        port = url.port
    except (ArgumentError, TypeError, ValueError):
        return None
    return url, port


def assert_disposable_database(
    database_url: str,
    *,
    opt_in: str | None,
    ownership_token: str | None,
    expected_database: str | None,
) -> DatabaseIdentity:
    """Validate an explicit B-04A URL without opening a database connection."""
    if opt_in != "YES":
        _reject("OPT-IN")
    if not _is_secret_like(ownership_token):
        _reject("OWNERSHIP")
    if expected_database is None or not expected_database.strip():
        _reject("EXPECTED-DATABASE")
    if (
        not isinstance(database_url, str)
        or not database_url.strip()
        or "#" in database_url
        or "?" in database_url
    ):
        _reject("URL")

    parsed_url = _parse_url_without_exception_context(database_url)
    if parsed_url is None:
        raise ValueError("B04-DISPOSABLE-URL")
    url, port = parsed_url

    if url.drivername != "postgresql+psycopg":
        _reject("DRIVER")
    if url.query:
        _reject("URL-QUERY")

    host = url.host
    username = url.username
    database = url.database
    if (
        not isinstance(host, str)
        or not host.strip()
        or "," in host
        or "/" in host
        or not isinstance(port, int)
        or not 1 <= port <= 65535
        or not isinstance(username, str)
        or not username.strip()
        or not isinstance(database, str)
    ):
        _reject("URL-IDENTITY")

    if database != expected_database:
        _reject("DATABASE-MISMATCH")
    if (
        database in _PROHIBITED_DATABASES
        or not _DISPOSABLE_DATABASE_RE.fullmatch(database)
        or _PRODUCTION_ALIAS_SEGMENTS.intersection(database.split("_"))
    ):
        _reject("DATABASE-NAME")

    return DatabaseIdentity(
        database=database,
        host=host,
        port=port,
        username=username,
    )


def assert_postgresql_16(connection: Any) -> int:
    """Require PostgreSQL 16 from an already-open, injected connection."""
    try:
        raw_version = connection.exec_driver_sql("SHOW server_version_num").scalar_one()
        if isinstance(raw_version, bool):
            raise ValueError
        version = str(raw_version)
        if not re.fullmatch(r"[0-9]{6,}", version):
            raise ValueError
        major = int(version) // 10_000
    except (AttributeError, TypeError, ValueError):
        raise ValueError("B04-DISPOSABLE-POSTGRESQL-VERSION") from None

    if major != 16:
        _reject("POSTGRESQL-16")
    return major
