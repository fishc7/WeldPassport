from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import traceback

import pytest

from app.shared.database_target import DatabaseTargetError
from test_support.ci_database_lifecycle import (
    CiDatabaseLifecycle,
    EphemeralDatabaseLease,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_PATH = BACKEND_ROOT / "test_support" / "ci_database_lifecycle.py"


class _FakeAdminAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.existing = False
        self.marker: str | None = None
        self.fail_operation: str | None = None

    def _record(self, operation: str, *values: str) -> None:
        self.calls.append((operation, *values))
        if self.fail_operation == operation:
            raise RuntimeError("external adapter details")

    def database_exists(self, database_name: str) -> bool:
        self._record("exists", database_name)
        return self.existing

    def create_database(self, database_name: str) -> None:
        self._record("create", database_name)

    def write_marker(self, database_name: str, marker: str) -> None:
        self._record("write_marker", database_name, marker)
        self.marker = marker

    def read_marker(self, database_name: str) -> str | None:
        self._record("read_marker", database_name)
        return self.marker

    def drop_database(self, database_name: str) -> None:
        self._record("drop", database_name)


def _lifecycle(
    adapter: _FakeAdminAdapter | None = None,
) -> tuple[CiDatabaseLifecycle, _FakeAdminAdapter]:
    exact_adapter = adapter or _FakeAdminAdapter()
    return (
        CiDatabaseLifecycle(
            exact_adapter,
            ownership_token_factory=lambda: "owner-token-001",
        ),
        exact_adapter,
    )


def test_ci_lifecycle_provisions_exact_name_and_verifies_marker() -> None:
    lifecycle, adapter = _lifecycle()

    lease = lifecycle.provision(run_id="4815", nonce="a1b2c3d4")

    assert lease.database_name == "wp_test_4815_a1b2c3d4"
    assert lease.ownership_token == "owner-token-001"
    assert lease.marker == "weldpassport-test-db:owner-token-001"
    assert adapter.calls == [
        ("exists", lease.database_name),
        ("create", lease.database_name),
        ("write_marker", lease.database_name, lease.marker),
        ("read_marker", lease.database_name),
    ]
    rendered = repr(lease)
    assert "owner-token-001" not in rendered
    assert "weldpassport-test-db" not in rendered


def test_ci_lifecycle_drops_only_the_exact_lease_after_marker_recheck() -> None:
    lifecycle, adapter = _lifecycle()
    lease = lifecycle.provision(run_id="4815", nonce="a1b2c3d4")
    adapter.calls.clear()

    lifecycle.cleanup(lease)

    assert adapter.calls == [
        ("read_marker", lease.database_name),
        ("drop", lease.database_name),
    ]


@pytest.mark.parametrize(
    ("run_id", "nonce"),
    [
        ("", "a1b2c3d4"),
        ("4815", ""),
        ("run-id", "a1b2c3d4"),
        ("4815", "nonce.value"),
        ("UPPER", "a1b2c3d4"),
        ("x" * 50, "y" * 20),
    ],
)
def test_ci_lifecycle_rejects_invalid_or_oversized_identifiers(
    run_id: str,
    nonce: str,
) -> None:
    lifecycle, adapter = _lifecycle()

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.provision(run_id=run_id, nonce=nonce)

    assert caught.value.code == "TEST-DB-LIFECYCLE-UNSAFE"
    assert adapter.calls == []


def test_ci_lifecycle_rejects_a_preexisting_generated_database() -> None:
    adapter = _FakeAdminAdapter()
    adapter.existing = True
    lifecycle, _ = _lifecycle(adapter)

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.provision(run_id="4815", nonce="a1b2c3d4")

    assert caught.value.code == "TEST-DB-LIFECYCLE-UNSAFE"
    assert [call[0] for call in adapter.calls] == ["exists"]


def test_ci_lifecycle_refuses_cleanup_when_marker_publication_mismatches() -> None:
    adapter = _FakeAdminAdapter()
    lifecycle, _ = _lifecycle(adapter)

    original_write = adapter.write_marker

    def write_foreign_marker(database_name: str, marker: str) -> None:
        original_write(database_name, marker)
        adapter.marker = "weldpassport-test-db:foreign-token"

    adapter.write_marker = write_foreign_marker  # type: ignore[method-assign]

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.provision(run_id="4815", nonce="a1b2c3d4")

    assert caught.value.code == "TEST-DB-OWNERSHIP-MISMATCH"
    assert all(call[0] != "drop" for call in adapter.calls)


def test_ci_lifecycle_refuses_cleanup_for_an_altered_lease() -> None:
    lifecycle, adapter = _lifecycle()
    lease = lifecycle.provision(run_id="4815", nonce="a1b2c3d4")
    adapter.calls.clear()

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.cleanup(replace(lease, ownership_token="foreign-token"))

    assert caught.value.code == "TEST-DB-LIFECYCLE-UNSAFE"
    assert adapter.calls == []


def test_ci_lifecycle_refuses_cleanup_for_a_foreign_database_name() -> None:
    lifecycle, adapter = _lifecycle()
    lease = EphemeralDatabaseLease(
        database_name="weldpassport",
        ownership_token="owner-token-001",
        marker="weldpassport-test-db:owner-token-001",
    )

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.cleanup(lease)

    assert caught.value.code == "TEST-DB-LIFECYCLE-UNSAFE"
    assert adapter.calls == []


def test_ci_lifecycle_refuses_a_second_cleanup() -> None:
    lifecycle, adapter = _lifecycle()
    lease = lifecycle.provision(run_id="4815", nonce="a1b2c3d4")
    lifecycle.cleanup(lease)
    adapter.calls.clear()

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.cleanup(lease)

    assert caught.value.code == "TEST-DB-LIFECYCLE-UNSAFE"
    assert adapter.calls == []


def test_ci_lifecycle_sanitizes_adapter_failures() -> None:
    adapter = _FakeAdminAdapter()
    adapter.fail_operation = "create"
    lifecycle, _ = _lifecycle(adapter)

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.provision(run_id="4815", nonce="a1b2c3d4")

    assert caught.value.code == "TEST-DB-LIFECYCLE-FAILED"
    assert "external adapter details" not in str(caught.value)
    assert all(call[0] != "drop" for call in adapter.calls)


def test_ci_lifecycle_sanitizes_token_factory_failure() -> None:
    adapter = _FakeAdminAdapter()

    def fail_token_factory() -> str:
        raise RuntimeError("external token factory details")

    lifecycle = CiDatabaseLifecycle(
        adapter,
        ownership_token_factory=fail_token_factory,
    )

    try:
        lifecycle.provision(run_id="4815", nonce="a1b2c3d4")
    except DatabaseTargetError as exc:
        assert exc.code == "TEST-DB-LIFECYCLE-FAILED"
        assert exc.__cause__ is None
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).lower()
    else:
        raise AssertionError("token factory failure unexpectedly accepted")

    assert "external token factory details" not in rendered
    assert adapter.calls == []


def test_ci_lifecycle_rejects_non_string_token_without_raw_attribute_error() -> None:
    adapter = _FakeAdminAdapter()
    lifecycle = CiDatabaseLifecycle(
        adapter,
        ownership_token_factory=lambda: 42,  # type: ignore[arg-type,return-value]
    )

    with pytest.raises(DatabaseTargetError) as caught:
        lifecycle.provision(run_id="4815", nonce="a1b2c3d4")

    assert caught.value.code == "TEST-DB-LIFECYCLE-UNSAFE"
    assert caught.value.__cause__ is None
    assert adapter.calls == []


def _assert_no_broad_cleanup_primitive(source: str) -> None:
    normalized_source = source.lower()
    forbidden = (
        "list_databases",
        "startswith(",
        " like ",
        " ilike ",
        "pg_database",
        "re.findall(",
        "re.finditer(",
        "re.search(",
        "fnmatch.",
        " similar to ",
        "drop_by_prefix",
        "drop_matching",
    )
    matches = [token for token in forbidden if token in normalized_source]
    assert matches == []


def test_ci_lifecycle_source_has_no_broad_cleanup_primitive() -> None:
    _assert_no_broad_cleanup_primitive(
        LIFECYCLE_PATH.read_text(encoding="utf-8")
    )


def test_broad_cleanup_guard_detects_a_prefix_deletion_mutation() -> None:
    mutated_source = """
def drop_by_prefix(prefix):
    for name in list_databases():
        if name.startswith(prefix):
            drop_database(name)
"""

    with pytest.raises(AssertionError):
        _assert_no_broad_cleanup_primitive(mutated_source)


@pytest.mark.parametrize(
    "mutated_source",
    [
        "SELECT datname FROM pg_database",
        "matches = re.findall(r'wp_test_.*', database_names)",
        "matches = fnmatch.filter(database_names, 'wp_test_*')",
        "WHERE datname SIMILAR TO 'wp_test_%'",
    ],
)
def test_broad_cleanup_guard_detects_catalog_and_pattern_mutations(
    mutated_source: str,
) -> None:
    with pytest.raises(AssertionError):
        _assert_no_broad_cleanup_primitive(mutated_source)
