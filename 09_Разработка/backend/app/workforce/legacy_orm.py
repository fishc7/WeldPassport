from threading import Lock

from sqlalchemy.orm import DeclarativeBase

from app.shared.runtime_profile import (
    RuntimeContractError,
    validate_legacy_schema_identifier,
)


class LegacyBase(DeclarativeBase):
    """Declarative registry used only by deprecated workforce compatibility."""


_schema_lock = Lock()
_bound_schema: str | None = None


def bind_legacy_schema(schema: str) -> str:
    validate_legacy_schema_identifier(schema)

    global _bound_schema
    with _schema_lock:
        if _bound_schema is None:
            _bound_schema = schema
        elif _bound_schema != schema:
            raise RuntimeContractError(
                "LEGACY-CONTRACT-MISMATCH",
                "legacy schema is already bound",
            )
        return _bound_schema


def get_or_bind_legacy_schema(default: str = "test") -> str:
    with _schema_lock:
        bound_schema = _bound_schema
    if bound_schema is not None:
        return bound_schema
    return bind_legacy_schema(default)


def get_bound_legacy_schema() -> str:
    with _schema_lock:
        bound_schema = _bound_schema
    if bound_schema is None:
        raise RuntimeContractError(
            "LEGACY-CONTRACT-MISMATCH",
            "legacy schema is not bound",
        )
    return bound_schema
