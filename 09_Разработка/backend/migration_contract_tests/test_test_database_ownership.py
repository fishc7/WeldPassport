from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.shared.database_target import (
    DatabaseTargetError,
    authorize_test_database,
)
from app.shared.test_database_ownership import (
    LiveDatabaseIdentity,
    read_live_database_identity,
    verify_test_database_ownership,
)


WORKING_URL = (
    "postgresql+psycopg://worker:working-secret@work-db.example/weldpassport"
)
TEST_URL = (
    "postgresql+psycopg://tester:test-secret@test-db.example/wp_test_run_001"
)


class _FakeMappingResult:
    def __init__(self, row: Mapping[str, Any]) -> None:
        self._row = row

    def mappings(self) -> _FakeMappingResult:
        return self

    def one(self) -> Mapping[str, Any]:
        return self._row


class _FakeConnection:
    def __init__(self, row: Mapping[str, Any]) -> None:
        self._row = row

    def execute(self, _statement: object) -> _FakeMappingResult:
        return _FakeMappingResult(self._row)


def _authorization():
    return authorize_test_database(
        test_database_url=TEST_URL,
        working_database_url=WORKING_URL,
        destructive_opt_in="YES",
        confirmed_database_name="wp_test_run_001",
        ownership_token="owner-token-001",
    )


def _row(**overrides: Any) -> dict[str, Any]:
    value = {
        "database_name": "wp_test_run_001",
        "server_address": "127.0.0.1",
        "server_port": 5432,
        "database_comment": "weldpassport-test-db:owner-token-001",
    }
    value.update(overrides)
    return value


def test_read_live_database_identity_maps_the_complete_catalog_row() -> None:
    identity = read_live_database_identity(_FakeConnection(_row()))  # type: ignore[arg-type]

    assert identity == LiveDatabaseIdentity(
        database_name="wp_test_run_001",
        server_address="127.0.0.1",
        server_port=5432,
        database_comment="weldpassport-test-db:owner-token-001",
    )


def test_verify_test_database_ownership_accepts_exact_identity_and_marker() -> None:
    verify_test_database_ownership(
        _FakeConnection(_row()),  # type: ignore[arg-type]
        _authorization(),
        resolved_host_addresses=frozenset({"127.0.0.1", "::1"}),
    )


@pytest.mark.parametrize(
    ("overrides", "resolved_addresses", "expected_code"),
    [
        (
            {"database_name": "foreign_test"},
            frozenset({"127.0.0.1"}),
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            {"server_port": 6432},
            frozenset({"127.0.0.1"}),
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            {"server_address": "10.20.30.40"},
            frozenset({"127.0.0.1"}),
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            {"database_comment": None},
            frozenset({"127.0.0.1"}),
            "TEST-DB-OWNERSHIP-MISMATCH",
        ),
        (
            {"database_comment": "another-system:owner-token-001"},
            frozenset({"127.0.0.1"}),
            "TEST-DB-OWNERSHIP-MISMATCH",
        ),
        (
            {"database_comment": "weldpassport-test-db:foreign-token"},
            frozenset({"127.0.0.1"}),
            "TEST-DB-OWNERSHIP-MISMATCH",
        ),
    ],
)
def test_verify_test_database_ownership_rejects_each_live_mismatch(
    overrides: dict[str, Any],
    resolved_addresses: frozenset[str],
    expected_code: str,
) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        verify_test_database_ownership(
            _FakeConnection(_row(**overrides)),  # type: ignore[arg-type]
            _authorization(),
            resolved_host_addresses=resolved_addresses,
        )

    assert caught.value.code == expected_code
    rendered = str(caught.value).lower()
    for forbidden in (
        "127.0.0.1",
        "10.20.30.40",
        "5432",
        "6432",
        "test-db.example",
        "owner-token-001",
        "foreign-token",
    ):
        assert forbidden not in rendered
