from __future__ import annotations

import traceback

import pytest

from app.shared.database_target import (
    DatabasePurpose,
    DatabaseTargetError,
    authorize_test_database,
    parse_database_target,
)


WORKING_URL = (
    "postgresql+psycopg://worker:working-secret@db.example:5432/weldpassport"
)
TEST_URL = (
    "postgresql+psycopg://tester:test-secret@DB.EXAMPLE/wp_test_run_001"
)


def test_parse_database_target_normalizes_identity_without_exposing_coordinates() -> None:
    target = parse_database_target(TEST_URL, DatabasePurpose.TEST)

    assert target.purpose is DatabasePurpose.TEST
    assert target.database_name == "wp_test_run_001"
    assert target.identity.drivername == "postgresql+psycopg"
    assert target.identity.host == "db.example"
    assert target.identity.port == 5432
    assert target.identity.database == "wp_test_run_001"

    rendered = repr(target)
    assert "working-secret" not in rendered
    assert "test-secret" not in rendered
    assert "db.example" not in rendered.lower()
    assert "worker" not in rendered
    assert "tester" not in rendered


@pytest.mark.parametrize(
    ("test_url", "opt_in", "confirmation", "token", "expected_code"),
    [
        (None, "YES", "wp_test_run_001", "owner-token", "TEST-DB-URL-MISSING"),
        ("", "YES", "wp_test_run_001", "owner-token", "TEST-DB-URL-MISSING"),
        (
            "sqlite:///wp_test_run_001",
            "YES",
            "wp_test_run_001",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg2://tester:x@db.example/wp_test_run_001",
            "YES",
            "wp_test_run_001",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@/wp_test_run_001",
            "YES",
            "wp_test_run_001",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@db.example",
            "YES",
            "wp_test_run_001",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@db.example/postgres",
            "YES",
            "postgres",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@db.example/template0",
            "YES",
            "template0",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@db.example/template1",
            "YES",
            "template1",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@db.example/weldpassport",
            "YES",
            "weldpassport",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (
            "postgresql+psycopg://tester:x@db.example/weldpassport_dev",
            "YES",
            "weldpassport_dev",
            "owner-token",
            "TEST-DB-TARGET-UNSAFE",
        ),
        (TEST_URL, None, "wp_test_run_001", "owner-token", "TEST-DB-TARGET-UNSAFE"),
        (TEST_URL, "NO", "wp_test_run_001", "owner-token", "TEST-DB-TARGET-UNSAFE"),
        (TEST_URL, "YES", None, "owner-token", "TEST-DB-TARGET-UNSAFE"),
        (TEST_URL, "YES", "another_test", "owner-token", "TEST-DB-TARGET-UNSAFE"),
        (TEST_URL, "YES", "wp_test_run_001", None, "TEST-DB-TARGET-UNSAFE"),
        (TEST_URL, "YES", "wp_test_run_001", "   ", "TEST-DB-TARGET-UNSAFE"),
    ],
)
def test_authorize_test_database_rejects_each_unsafe_input(
    test_url: str | None,
    opt_in: str | None,
    confirmation: str | None,
    token: str | None,
    expected_code: str,
) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        authorize_test_database(
            test_database_url=test_url,
            working_database_url=WORKING_URL,
            destructive_opt_in=opt_in,
            confirmed_database_name=confirmation,
            ownership_token=token,
        )

    assert caught.value.code == expected_code
    rendered = str(caught.value).lower()
    for forbidden in (
        "working-secret",
        "test-secret",
        "owner-token",
        "db.example",
        "worker",
        "tester",
    ):
        assert forbidden not in rendered


def test_authorize_test_database_rejects_normalized_target_collision() -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        authorize_test_database(
            test_database_url=(
                "postgresql+psycopg://tester:test-secret@DB.EXAMPLE/"
                "wp_test_run_001"
            ),
            working_database_url=(
                "postgresql+psycopg://worker:working-secret@db.example:5432/"
                "wp_test_run_001"
            ),
            destructive_opt_in="YES",
            confirmed_database_name="wp_test_run_001",
            ownership_token="owner-token",
        )

    assert caught.value.code == "TEST-DB-TARGET-COLLISION"


def test_authorize_test_database_rejects_same_database_name_on_another_host() -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        authorize_test_database(
            test_database_url=(
                "postgresql+psycopg://tester:test-secret@test-db.example/"
                "shared_test"
            ),
            working_database_url=(
                "postgresql+psycopg://worker:working-secret@work-db.example/"
                "shared_test"
            ),
            destructive_opt_in="YES",
            confirmed_database_name="shared_test",
            ownership_token="owner-token",
        )

    assert caught.value.code == "TEST-DB-TARGET-COLLISION"


def test_authorize_test_database_returns_redacted_immutable_authorization() -> None:
    authorization = authorize_test_database(
        test_database_url=TEST_URL,
        working_database_url=WORKING_URL,
        destructive_opt_in="YES",
        confirmed_database_name="wp_test_run_001",
        ownership_token="owner-token",
    )

    assert authorization.target.database_name == "wp_test_run_001"
    assert authorization.ownership_token == "owner-token"
    assert "owner-token" not in repr(authorization)
    with pytest.raises(AttributeError):
        authorization.ownership_token = "replacement"  # type: ignore[misc]


def test_invalid_url_traceback_does_not_chain_raw_parser_details() -> None:
    raw_value = "://tester:working-secret@db.example/wp_test_x"

    try:
        parse_database_target(raw_value, DatabasePurpose.TEST)
    except DatabaseTargetError as exc:
        assert exc.__cause__ is None
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).lower()
    else:
        raise AssertionError("invalid URL unexpectedly accepted")

    for forbidden in ("working-secret", "db.example", "tester"):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "query",
    [
        "host=working.example",
        "port=6543",
        "dbname=weldpassport",
        "host=working.example&port=6543&dbname=weldpassport",
        "sslmode=require",
    ],
)
def test_parse_database_target_rejects_query_parameters_before_connection(
    query: str,
) -> None:
    with pytest.raises(DatabaseTargetError) as caught:
        parse_database_target(
            f"{TEST_URL}?{query}",
            DatabasePurpose.TEST,
        )

    assert caught.value.code == "TEST-DB-TARGET-UNSAFE"


@pytest.mark.parametrize("port", ["bad", "0", "-1", "65536"])
def test_parse_database_target_rejects_invalid_ports_with_redacted_error(
    port: str,
) -> None:
    raw_value = (
        "postgresql+psycopg://tester:port-secret@db.example:"
        f"{port}/wp_test_run_001"
    )

    try:
        parse_database_target(raw_value, DatabasePurpose.TEST)
    except DatabaseTargetError as exc:
        assert exc.code == "TEST-DB-TARGET-UNSAFE"
        assert exc.__cause__ is None
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).lower()
    else:
        raise AssertionError("invalid port unexpectedly accepted")

    for forbidden in ("port-secret", "db.example", "tester"):
        assert forbidden not in rendered


def test_authorize_test_database_sanitizes_invalid_working_url() -> None:
    raw_working_url = (
        "postgresql+psycopg://worker:working-secret@work-db.example:"
        "bad/weldpassport"
    )

    try:
        authorize_test_database(
            test_database_url=TEST_URL,
            working_database_url=raw_working_url,
            destructive_opt_in="YES",
            confirmed_database_name="wp_test_run_001",
            ownership_token="owner-token",
        )
    except DatabaseTargetError as exc:
        assert exc.code == "TEST-DB-TARGET-UNSAFE"
        assert exc.__cause__ is None
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).lower()
    else:
        raise AssertionError("invalid working URL unexpectedly accepted")

    for forbidden in ("working-secret", "work-db.example", "worker"):
        assert forbidden not in rendered
