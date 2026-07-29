"""Pure contracts for the B-04A disposable PostgreSQL boundary."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from sqlalchemy.exc import ArgumentError

from migrations.b04.disposable import (
    DatabaseIdentity,
    PostgresVersion,
    assert_disposable_database,
    assert_postgresql_18,
)


VALID_URL = (
    "postgresql+psycopg://b04_runner:database-password@"
    "127.0.0.1:5432/wp_b04_r18_baseline_disposable"
)
VALID_TOKEN = "B04-owner-token-2026"
VALID_DATABASE = "wp_b04_r18_baseline_disposable"


def _assert_rejected(**overrides: object) -> None:
    arguments: dict[str, object] = {
        "database_url": VALID_URL,
        "opt_in": "YES",
        "ownership_token": VALID_TOKEN,
        "expected_database": VALID_DATABASE,
    }
    arguments.update(overrides)

    with pytest.raises(ValueError) as error:
        assert_disposable_database(**arguments)  # type: ignore[arg-type]

    rendered = str(error.value)
    assert "database-password" not in rendered
    assert VALID_TOKEN not in rendered


@pytest.mark.parametrize("opt_in", [None, "", " ", "NO", "yes", "YES "])
def test_b04_disposable_001_rejects_every_non_exact_opt_in(
    opt_in: str | None,
) -> None:
    _assert_rejected(opt_in=opt_in)


@pytest.mark.parametrize(
    "ownership_token",
    [None, "", "   ", "short", "onlylowercasecharacters", "1234567890123456"],
)
def test_b04_disposable_002_rejects_missing_or_non_secret_like_token(
    ownership_token: str | None,
) -> None:
    _assert_rejected(ownership_token=ownership_token)


@pytest.mark.parametrize(
    "expected_database",
    [None, "", "  ", "wp_b04_other_disposable", "WP_B04_R18_BASELINE_DISPOSABLE"],
)
def test_b04_disposable_003_rejects_missing_or_mismatched_expected_database(
    expected_database: str | None,
) -> None:
    _assert_rejected(expected_database=expected_database)


@pytest.mark.parametrize(
    "database_name",
    [
        "postgres",
        "template0",
        "template1",
        "weldpassport",
        "wp_b04_r18_baseline",
        "wp_b04__disposable",
        "wp_b04_r18_baseline_disposable_extra",
        "WP_B04_R18_BASELINE_DISPOSABLE",
        "wp_b04_r18_baseline-disposable",
        "ordinary_application_database",
    ],
)
def test_b04_disposable_004_rejects_system_production_and_non_disposable_names(
    database_name: str,
) -> None:
    _assert_rejected(
        database_url=(
            "postgresql+psycopg://b04_runner:database-password@"
            f"127.0.0.1:5432/{database_name}"
        ),
        expected_database=database_name,
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+pymysql://b04_runner:database-password@127.0.0.1:5432/wp_b04_r18_baseline_disposable",
        "postgresql://b04_runner:database-password@127.0.0.1:5432/wp_b04_r18_baseline_disposable",
        "postgresql+psycopg2://b04_runner:database-password@127.0.0.1:5432/wp_b04_r18_baseline_disposable",
        "postgresql+psycopg://b04_runner:database-password@db1,db2:5432/wp_b04_r18_baseline_disposable",
        "postgresql+psycopg://b04_runner:database-password@/wp_b04_r18_baseline_disposable?host=/tmp",
        "postgresql+psycopg://b04_runner:database-password@127.0.0.1:5432/wp_b04_r18_baseline_disposable#fragment",
        "postgresql+psycopg://:database-password@127.0.0.1:5432/wp_b04_r18_baseline_disposable",
        "postgresql+psycopg://b04_runner:database-password@127.0.0.1/wp_b04_r18_baseline_disposable",
        "postgresql+psycopg://b04_runner:database-password@127.0.0.1:5432/",
    ],
)
def test_b04_disposable_005_rejects_non_postgresql_or_ambiguous_urls(
    database_url: str,
) -> None:
    _assert_rejected(database_url=database_url)


def test_b04_disposable_006_accepts_exact_name_and_returns_sanitized_identity() -> None:
    identity = assert_disposable_database(
        VALID_URL,
        opt_in="YES",
        ownership_token=VALID_TOKEN,
        expected_database=VALID_DATABASE,
    )

    assert identity == DatabaseIdentity(
        database=VALID_DATABASE,
        host="127.0.0.1",
        port=5432,
        username="b04_runner",
    )
    assert asdict(identity) == {
        "database": VALID_DATABASE,
        "host": "127.0.0.1",
        "port": 5432,
        "username": "b04_runner",
    }
    assert "database-password" not in repr(identity)
    assert VALID_TOKEN not in repr(identity)


@pytest.mark.parametrize(
    "database_name",
    [
        "wp_b04_r18_restore_first_disposable",
        "wp_b04_r18_restore_second_disposable",
    ],
)
def test_b04r_disposable_001_accepts_only_exact_restore_names(
    database_name: str,
) -> None:
    url = (
        "postgresql+psycopg://b04_runner:database-password@"
        f"127.0.0.1:5432/{database_name}"
    )
    assert assert_disposable_database(
        url,
        opt_in="YES",
        ownership_token=VALID_TOKEN,
        expected_database=database_name,
    ) == DatabaseIdentity(
        database=database_name,
        host="127.0.0.1",
        port=5432,
        username="b04_runner",
    )


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


class _FakeConnection:
    def __init__(self, server_version_num: object) -> None:
        self.server_version_num = server_version_num
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> _ScalarResult:
        self.statements.append(statement)
        return _ScalarResult(self.server_version_num)


def test_b04_r18_version_001_accepts_postgresql_18() -> None:
    connection = _FakeConnection("180003")

    assert assert_postgresql_18(connection) == PostgresVersion(
        server_version_num=180003,
        major=18,
    )
    assert connection.statements == ["SHOW server_version_num"]


@pytest.mark.parametrize("server_version_num", ["160014", "170009", "190001"])
def test_b04_r18_version_002_rejects_every_non_18_major(
    server_version_num: object,
) -> None:
    connection = _FakeConnection(server_version_num)

    with pytest.raises(ValueError, match="B04-DISPOSABLE-POSTGRESQL-18"):
        assert_postgresql_18(connection)


@pytest.mark.parametrize("server_version_num", ["invalid", None, True, "18003"])
def test_b04_r18_version_003_rejects_malformed_version(
    server_version_num: object,
) -> None:
    connection = _FakeConnection(server_version_num)

    with pytest.raises(ValueError, match="B04-DISPOSABLE-POSTGRESQL-VERSION"):
        assert_postgresql_18(connection)


@pytest.mark.parametrize(
    "query",
    [
        "dbname=wp_b04_other_disposable",
        "user=other_user",
        "port=6543",
        "hostaddr=127.0.0.1",
        "host=db1.example.test&host=db2.example.test",
        "host=/tmp/postgresql",
    ],
)
def test_b04_disposable_009_rejects_every_url_query_override(query: str) -> None:
    _assert_rejected(database_url=f"{VALID_URL}?{query}")


@pytest.mark.parametrize(
    "database_name",
    [
        "wp_b04_prod_disposable",
        "wp_b04_production_disposable",
        "wp_b04_live_disposable",
        "wp_b04_primary_disposable",
        "wp_b04_system_disposable",
    ],
)
def test_b04_disposable_010_rejects_production_alias_name_segments(
    database_name: str,
) -> None:
    _assert_rejected(
        database_url=VALID_URL.replace(VALID_DATABASE, database_name),
        expected_database=database_name,
    )


@pytest.mark.parametrize(
    "database_name",
    [
        "wp_b04_product_review_disposable",
        "wp_b04_reproduction_review_disposable",
        "wp_b04_livewire_review_disposable",
        "wp_b04_primaryish_review_disposable",
        "wp_b04_systematic_review_disposable",
    ],
)
def test_b04_r18_disposable_011_rejects_every_other_well_shaped_name(
    database_name: str,
) -> None:
    _assert_rejected(
        database_url=VALID_URL.replace(VALID_DATABASE, database_name),
        expected_database=database_name,
    )


def test_b04_disposable_012_hides_sqlalchemy_parse_canary_from_error_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "CANARY-PASSWORD-DO-NOT-RENDER"

    def _raise_argument_error(_: str) -> None:
        raise ArgumentError(canary)

    monkeypatch.setattr("migrations.b04.disposable.make_url", _raise_argument_error)

    with pytest.raises(ValueError) as error:
        assert_disposable_database(
            VALID_URL,
            opt_in="YES",
            ownership_token=VALID_TOKEN,
            expected_database=VALID_DATABASE,
        )

    exceptions = [error.value]
    rendered_surface: list[str] = []
    while exceptions:
        current = exceptions.pop()
        rendered_surface.extend(
            [
                str(current),
                repr(current),
                repr(current.args),
                str(type(current)),
                repr(type(current)),
                *(str(cls) for cls in type(current).__mro__),
            ]
        )
        if current.__cause__ is not None:
            exceptions.append(current.__cause__)
        if current.__context__ is not None:
            exceptions.append(current.__context__)

    assert canary not in "\n".join(rendered_surface)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize("suffix", ["?", "?dbname", "?sslmode="])
def test_b04_disposable_013_rejects_literal_query_marker_before_parsing(
    suffix: str,
) -> None:
    _assert_rejected(database_url=f"{VALID_URL}{suffix}")


@pytest.mark.parametrize(
    "host",
    ["localhost", "[::1]", "db.example.test", "192.0.2.10"],
)
def test_b04_r18_disposable_014_rejects_every_non_exact_loopback_host(
    host: str,
) -> None:
    _assert_rejected(
        database_url=VALID_URL.replace("127.0.0.1", host),
    )
