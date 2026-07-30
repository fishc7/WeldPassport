from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import re
from typing import Protocol, TypeVar

from app.shared.database_target import DatabaseTargetError


_CI_DATABASE_NAME = re.compile(r"^wp_test_[a-z0-9]+_[a-z0-9]+$")
_POSTGRESQL_IDENTIFIER_LIMIT = 63
_T = TypeVar("_T")


class CiAdminAdapter(Protocol):
    def database_exists(self, database_name: str) -> bool: ...

    def create_database(self, database_name: str) -> None: ...

    def write_marker(self, database_name: str, marker: str) -> None: ...

    def read_marker(self, database_name: str) -> str | None: ...

    def drop_database(self, database_name: str) -> None: ...


@dataclass(frozen=True)
class EphemeralDatabaseLease:
    database_name: str
    ownership_token: str = field(repr=False)
    marker: str = field(repr=False)


class CiDatabaseLifecycle:
    def __init__(
        self,
        adapter: CiAdminAdapter,
        *,
        ownership_token_factory: Callable[[], str],
    ) -> None:
        self._adapter = adapter
        self._ownership_token_factory = ownership_token_factory
        self._active_leases: set[EphemeralDatabaseLease] = set()
        self._cleaned_leases: set[EphemeralDatabaseLease] = set()

    @staticmethod
    def _validate_database_name(database_name: str) -> None:
        if (
            _CI_DATABASE_NAME.fullmatch(database_name) is None
            or len(database_name.encode("ascii", errors="ignore"))
            != len(database_name)
            or len(database_name.encode("ascii")) > _POSTGRESQL_IDENTIFIER_LIMIT
        ):
            raise DatabaseTargetError(
                "TEST-DB-LIFECYCLE-UNSAFE",
                "CI test database target is unsafe",
            )

    @staticmethod
    def _adapter_call(operation: Callable[[], _T]) -> _T:
        try:
            return operation()
        except Exception:
            raise DatabaseTargetError(
                "TEST-DB-LIFECYCLE-FAILED",
                "CI test database adapter failed",
            ) from None

    def provision(
        self,
        *,
        run_id: str,
        nonce: str,
    ) -> EphemeralDatabaseLease:
        database_name = f"wp_test_{run_id}_{nonce}"
        self._validate_database_name(database_name)

        try:
            ownership_token = self._ownership_token_factory()
        except Exception:
            raise DatabaseTargetError(
                "TEST-DB-LIFECYCLE-FAILED",
                "CI ownership token generation failed",
            ) from None
        if (
            not isinstance(ownership_token, str)
            or not ownership_token
            or not ownership_token.strip()
            or ownership_token != ownership_token.strip()
        ):
            raise DatabaseTargetError(
                "TEST-DB-LIFECYCLE-UNSAFE",
                "CI ownership token is unsafe",
            )
        marker = f"weldpassport-test-db:{ownership_token}"

        exists = self._adapter_call(
            lambda: self._adapter.database_exists(database_name)
        )
        if exists:
            raise DatabaseTargetError(
                "TEST-DB-LIFECYCLE-UNSAFE",
                "CI test database target already exists",
            )

        self._adapter_call(lambda: self._adapter.create_database(database_name))
        self._adapter_call(
            lambda: self._adapter.write_marker(database_name, marker)
        )
        observed_marker = self._adapter_call(
            lambda: self._adapter.read_marker(database_name)
        )
        if observed_marker != marker:
            raise DatabaseTargetError(
                "TEST-DB-OWNERSHIP-MISMATCH",
                "CI test database ownership marker does not match",
            )

        lease = EphemeralDatabaseLease(
            database_name=database_name,
            ownership_token=ownership_token,
            marker=marker,
        )
        self._active_leases.add(lease)
        return lease

    def cleanup(self, lease: EphemeralDatabaseLease) -> None:
        self._validate_database_name(lease.database_name)
        expected_marker = f"weldpassport-test-db:{lease.ownership_token}"
        if (
            lease in self._cleaned_leases
            or lease not in self._active_leases
            or lease.marker != expected_marker
        ):
            raise DatabaseTargetError(
                "TEST-DB-LIFECYCLE-UNSAFE",
                "CI test database lease is not active",
            )

        observed_marker = self._adapter_call(
            lambda: self._adapter.read_marker(lease.database_name)
        )
        if observed_marker != lease.marker:
            raise DatabaseTargetError(
                "TEST-DB-OWNERSHIP-MISMATCH",
                "CI test database ownership marker does not match",
            )

        self._adapter_call(
            lambda: self._adapter.drop_database(lease.database_name)
        )
        self._active_leases.remove(lease)
        self._cleaned_leases.add(lease)
