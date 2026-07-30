from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


_POSTGRESQL_DRIVER = "postgresql+psycopg"
_DEFAULT_POSTGRESQL_PORT = 5432
_DENIED_DATABASE_NAMES = frozenset(
    {"postgres", "template0", "template1", "weldpassport"}
)
_TEST_DATABASE_NAME = re.compile(r"^(?:test_.+|.+_test|.+_test_.+)$")


class DatabasePurpose(StrEnum):
    WORKING = "working"
    TEST = "test"


@dataclass(frozen=True, repr=False)
class DatabaseIdentity:
    drivername: str
    host: str
    port: int
    database: str

    def __repr__(self) -> str:
        return "<DatabaseIdentity redacted>"


@dataclass(frozen=True)
class DatabaseTarget:
    purpose: DatabasePurpose
    url: URL = field(repr=False)
    identity: DatabaseIdentity = field(repr=False)
    database_name: str


@dataclass(frozen=True)
class TestDatabaseAuthorization:
    target: DatabaseTarget
    ownership_token: str = field(repr=False)


class DatabaseTargetError(RuntimeError):
    def __init__(self, code: str, safe_detail: str) -> None:
        self.code = code
        self.safe_detail = safe_detail
        super().__init__(f"{code}: {safe_detail}")


def _unsafe_target() -> DatabaseTargetError:
    return DatabaseTargetError(
        "TEST-DB-TARGET-UNSAFE",
        "test database authorization failed",
    )


def parse_database_target(
    raw_url: str,
    purpose: DatabasePurpose,
) -> DatabaseTarget:
    if not raw_url or not raw_url.strip():
        code = (
            "TEST-DB-URL-MISSING"
            if purpose is DatabasePurpose.TEST
            else "TEST-DB-TARGET-UNSAFE"
        )
        raise DatabaseTargetError(code, "database URL is not available")

    try:
        url = make_url(raw_url)
        parsed_port = url.port
        port = (
            _DEFAULT_POSTGRESQL_PORT
            if parsed_port is None
            else parsed_port
        )
    except (ArgumentError, TypeError, ValueError):
        raise _unsafe_target() from None

    host = url.host
    database_name = url.database
    if (
        url.drivername != _POSTGRESQL_DRIVER
        or bool(url.query)
        or host is None
        or not host.strip()
        or database_name is None
        or not database_name.strip()
        or not 1 <= port <= 65535
    ):
        raise _unsafe_target()

    identity = DatabaseIdentity(
        drivername=url.drivername,
        host=host.casefold(),
        port=port,
        database=database_name.casefold(),
    )
    return DatabaseTarget(
        purpose=purpose,
        url=url,
        identity=identity,
        database_name=database_name,
    )


def authorize_test_database(
    *,
    test_database_url: str | None,
    working_database_url: str,
    destructive_opt_in: str | None,
    confirmed_database_name: str | None,
    ownership_token: str | None,
) -> TestDatabaseAuthorization:
    if test_database_url is None or not test_database_url.strip():
        raise DatabaseTargetError(
            "TEST-DB-URL-MISSING",
            "TEST_DATABASE_URL is required",
        )

    test_target = parse_database_target(test_database_url, DatabasePurpose.TEST)
    working_target = parse_database_target(
        working_database_url,
        DatabasePurpose.WORKING,
    )
    normalized_name = test_target.database_name.casefold()

    if (
        destructive_opt_in != "YES"
        or confirmed_database_name != test_target.database_name
        or normalized_name in _DENIED_DATABASE_NAMES
        or _TEST_DATABASE_NAME.fullmatch(normalized_name) is None
        or ownership_token is None
        or not ownership_token.strip()
        or ownership_token != ownership_token.strip()
    ):
        raise _unsafe_target()

    if (
        test_target.identity == working_target.identity
        or normalized_name == working_target.database_name.casefold()
    ):
        raise DatabaseTargetError(
            "TEST-DB-TARGET-COLLISION",
            "test and working database targets collide",
        )

    return TestDatabaseAuthorization(
        target=test_target,
        ownership_token=ownership_token,
    )
