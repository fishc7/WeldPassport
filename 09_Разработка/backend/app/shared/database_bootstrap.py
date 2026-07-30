from __future__ import annotations

from threading import Lock

from app.shared.database_target import (
    DatabasePurpose,
    DatabaseTarget,
    DatabaseTargetError,
    parse_database_target,
)


class DatabaseTargetRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._target: DatabaseTarget | None = None

    def bind(self, target: DatabaseTarget) -> DatabaseTarget:
        with self._lock:
            if self._target is not None:
                raise DatabaseTargetError(
                    "DATABASE-TARGET-ALREADY-BOUND",
                    "database target is already bound",
                )
            self._target = target
            return target

    def require_bound(self) -> DatabaseTarget:
        with self._lock:
            if self._target is None:
                raise DatabaseTargetError(
                    "DATABASE-TARGET-NOT-BOUND",
                    "database target is not bound",
                )
            return self._target

    def get_or_bind_working(self, working_url: str) -> DatabaseTarget:
        with self._lock:
            if self._target is not None:
                return self._target
            self._target = parse_database_target(
                working_url,
                DatabasePurpose.WORKING,
            )
            return self._target


_database_target_registry = DatabaseTargetRegistry()


def bind_database_target(target: DatabaseTarget) -> DatabaseTarget:
    return _database_target_registry.bind(target)


def get_bound_database_target() -> DatabaseTarget:
    return _database_target_registry.require_bound()


def get_or_bind_working_target(working_url: str) -> DatabaseTarget:
    return _database_target_registry.get_or_bind_working(working_url)
