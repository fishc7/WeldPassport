from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_interface
import socket
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.shared.database_target import (
    DatabaseTargetError,
    TestDatabaseAuthorization,
)


_LIVE_IDENTITY_SQL = text(
    """
    SELECT
        current_database() AS database_name,
        inet_server_addr()::text AS server_address,
        inet_server_port() AS server_port,
        shobj_description(d.oid, 'pg_database') AS database_comment
    FROM pg_catalog.pg_database AS d
    WHERE d.datname = current_database()
    """
)


@dataclass(frozen=True, repr=False)
class LiveDatabaseIdentity:
    database_name: str
    server_address: str
    server_port: int
    database_comment: str | None

    def __repr__(self) -> str:
        return "<LiveDatabaseIdentity redacted>"


def read_live_database_identity(
    connection: Connection,
) -> LiveDatabaseIdentity:
    try:
        row: Any = connection.execute(_LIVE_IDENTITY_SQL).mappings().one()
        return LiveDatabaseIdentity(
            database_name=str(row["database_name"]),
            server_address=str(
                ip_interface(str(row["server_address"])).ip
            ),
            server_port=int(row["server_port"]),
            database_comment=(
                None
                if row["database_comment"] is None
                else str(row["database_comment"])
            ),
        )
    except Exception:
        raise DatabaseTargetError(
            "TEST-DB-TARGET-UNSAFE",
            "live database identity could not be verified",
        ) from None


def _resolve_host_addresses(host: str, port: int) -> frozenset[str]:
    try:
        return frozenset(
            str(sockaddr[0])
            for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        )
    except OSError:
        raise DatabaseTargetError(
            "TEST-DB-TARGET-UNSAFE",
            "test database endpoint could not be verified",
        ) from None


def verify_test_database_ownership(
    connection: Connection,
    authorization: TestDatabaseAuthorization,
    *,
    resolved_host_addresses: frozenset[str] | None = None,
) -> None:
    live = read_live_database_identity(connection)
    target = authorization.target
    addresses = (
        _resolve_host_addresses(target.identity.host, target.identity.port)
        if resolved_host_addresses is None
        else resolved_host_addresses
    )

    if (
        live.database_name != target.database_name
        or live.server_port != target.identity.port
        or live.server_address not in addresses
    ):
        raise DatabaseTargetError(
            "TEST-DB-TARGET-UNSAFE",
            "live database target does not match authorization",
        )

    expected_marker = f"weldpassport-test-db:{authorization.ownership_token}"
    if live.database_comment != expected_marker:
        raise DatabaseTargetError(
            "TEST-DB-OWNERSHIP-MISMATCH",
            "test database ownership marker does not match",
        )
