from __future__ import annotations

import re

import pytest


_DENIED_DATABASE_NAMES = frozenset(
    {"postgres", "template0", "template1", "weldpassport"}
)
_TEST_DATABASE_NAME = re.compile(r"^(?:test_.+|.+_test|.+_test_.+)$")
_ERROR = (
    "TEST DB SAFETY: integration tests are blocked. "
    "Set POSTGRES_DB to a disposable test database, "
    "WELDPASSPORT_TEST_DB_CONFIRM to the same database name, and "
    "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES."
)


def assert_safe_test_database(
    database_name: str,
    *,
    destructive_opt_in: str | None,
    confirmed_database_name: str | None,
) -> None:
    exact_name = database_name.strip()
    exact_confirmation = (confirmed_database_name or "").strip()
    normalized_name = exact_name.lower()

    if (
        destructive_opt_in != "YES"
        or not exact_confirmation
        or exact_confirmation != exact_name
        or normalized_name in _DENIED_DATABASE_NAMES
        or _TEST_DATABASE_NAME.fullmatch(normalized_name) is None
    ):
        raise pytest.UsageError(_ERROR)
