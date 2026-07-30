from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.shared.runtime_profile import RuntimeContractError


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    account_id: UUID
    auth_method: str


@dataclass(frozen=True)
class AuthenticatedActor:
    account_id: UUID
    session_id: UUID
    worker_id: int | None
    authenticated_at: datetime
    auth_method: str
    must_change_password: bool


@dataclass(frozen=True)
class IssuedSession:
    actor: AuthenticatedActor
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    idle_expires_at: datetime
    absolute_expires_at: datetime


class AuthenticationProvider(Protocol):
    def authenticate(
        self,
        login: str,
        password: str,
        now: datetime,
    ) -> AuthenticatedPrincipal: ...


def validate_auth_configuration(
    *,
    deployment_environment: str,
    cookie_secure: bool,
) -> None:
    if deployment_environment == "production" and cookie_secure is not True:
        raise RuntimeContractError(
            "AUTH-CONFIG-UNSAFE",
            "production authentication cookies must be Secure",
        )
