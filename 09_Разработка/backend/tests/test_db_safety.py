from __future__ import annotations

import pytest

from app.shared.database_target import (
    DatabaseTargetError,
    authorize_test_database,
)
_ERROR = (
    "TEST DB SAFETY: integration tests are blocked. "
    "Use an explicitly authorized disposable test database."
)


def assert_safe_test_database(
    database_name: str,
    *,
    destructive_opt_in: str | None,
    confirmed_database_name: str | None,
) -> None:
    try:
        authorize_test_database(
            test_database_url=(
                "postgresql+psycopg://test:test@test.invalid/"
                f"{database_name}"
            ),
            working_database_url=(
                "postgresql+psycopg://working:working@working.invalid/"
                "weldpassport"
            ),
            destructive_opt_in=destructive_opt_in,
            confirmed_database_name=confirmed_database_name,
            ownership_token="compatibility-only-token",
        )
    except DatabaseTargetError:
        raise pytest.UsageError(_ERROR) from None
