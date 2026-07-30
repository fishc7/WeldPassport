from __future__ import annotations

from datetime import datetime, timedelta
from hmac import compare_digest
from uuid import uuid4

from app.identity.constants import (
    ACCOUNT_ACTIVE,
    AUTHENTICATION_FAILED,
    AUTH_METHOD_LOCAL_PASSWORD,
    CSRF_VALIDATION_FAILED,
    SESSION_EXPIRED,
)
from app.identity.domain import (
    AuthenticatedActor,
    AuthenticatedPrincipal,
    IssuedSession,
)
from app.identity.models import AuthenticationEvent, IdentitySession, UserAccount
from app.identity.security import (
    PasswordHasher,
    digest_secret,
    generate_secret,
    validate_new_password,
)
from app.shared.config import settings
from app.shared.errors import DomainError


_DEFAULT_PASSWORD_HASHER = PasswordHasher()
_DEFAULT_DUMMY_HASH = _DEFAULT_PASSWORD_HASHER.hash_password(generate_secret())


def normalize_login(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise _authentication_failed()
    return normalized


def _authentication_failed() -> DomainError:
    return DomainError(
        401,
        AUTHENTICATION_FAILED,
        "Неверные учётные данные",
    )


def _session_expired() -> DomainError:
    return DomainError(
        401,
        SESSION_EXPIRED,
        "Сессия отсутствует или завершена",
    )


class LocalPasswordAuthenticationProvider:
    def __init__(
        self,
        repository,
        *,
        password_hasher: PasswordHasher,
        max_failed_logins: int,
        lock_minutes: int,
        dummy_hash: str | None = None,
    ) -> None:
        self.repository = repository
        self.password_hasher = password_hasher
        self.max_failed_logins = max_failed_logins
        self.lock_minutes = lock_minutes
        self._dummy_hash = (
            password_hasher.hash_password(generate_secret())
            if dummy_hash is None
            else dummy_hash
        )

    def authenticate(
        self,
        login: str,
        password: str,
        now: datetime,
    ) -> AuthenticatedPrincipal:
        normalized = normalize_login(login)
        account = self.repository.get_account_by_normalized_login(normalized)
        encoded = account.password_hash if account is not None else self._dummy_hash
        password_matches = self.password_hasher.verify_password(password, encoded)

        if account is None:
            raise _authentication_failed()
        if (
            account.status != ACCOUNT_ACTIVE
            or (account.locked_until is not None and account.locked_until > now)
        ):
            raise _authentication_failed()
        if not password_matches:
            account.failed_login_count += 1
            if account.failed_login_count >= self.max_failed_logins:
                account.locked_until = now + timedelta(
                    minutes=self.lock_minutes
                )
            self.repository.add_event(
                AuthenticationEvent(
                    id=uuid4(),
                    account_id=account.id,
                    event_type="LOGIN_FAILED",
                    occurred_at=now,
                    safe_context={},
                )
            )
            raise _authentication_failed()

        account.failed_login_count = 0
        account.locked_until = None
        return AuthenticatedPrincipal(
            account_id=account.id,
            auth_method=AUTH_METHOD_LOCAL_PASSWORD,
        )


class IdentityService:
    def __init__(
        self,
        repository,
        *,
        password_hasher: PasswordHasher | None = None,
        max_failed_logins: int = settings.auth_max_failed_logins,
        lock_minutes: int = settings.auth_lock_minutes,
        idle_minutes: int = settings.auth_session_idle_minutes,
        absolute_hours: int = settings.auth_session_absolute_hours,
        touch_minutes: int = settings.auth_session_touch_minutes,
        password_min_length: int = settings.auth_password_min_length,
    ) -> None:
        self.repository = repository
        self.password_hasher = password_hasher or _DEFAULT_PASSWORD_HASHER
        self.idle_minutes = idle_minutes
        self.absolute_hours = absolute_hours
        self.touch_minutes = touch_minutes
        self.password_min_length = password_min_length
        self.provider = LocalPasswordAuthenticationProvider(
            repository,
            password_hasher=self.password_hasher,
            max_failed_logins=max_failed_logins,
            lock_minutes=lock_minutes,
            dummy_hash=(
                None
                if password_hasher is not None
                else _DEFAULT_DUMMY_HASH
            ),
        )

    def login(
        self,
        login: str,
        password: str,
        now: datetime,
    ) -> IssuedSession:
        principal = self.provider.authenticate(login, password, now)
        account = self.repository.get_account(principal.account_id)
        if account is None:
            raise _authentication_failed()

        session_token = generate_secret()
        csrf_token = generate_secret()
        idle_expires_at = now + timedelta(minutes=self.idle_minutes)
        absolute_expires_at = now + timedelta(hours=self.absolute_hours)
        session = IdentitySession(
            id=uuid4(),
            account_id=account.id,
            token_hash=digest_secret(session_token),
            csrf_token_hash=digest_secret(csrf_token),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )
        self.repository.add_session(session)
        self.repository.add_event(
            AuthenticationEvent(
                id=uuid4(),
                account_id=account.id,
                session_id=session.id,
                event_type="LOGIN_SUCCEEDED",
                occurred_at=now,
                safe_context={},
            )
        )
        actor = self._actor(account, session, now)
        return IssuedSession(
            actor=actor,
            session_token=session_token,
            csrf_token=csrf_token,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )

    def resolve_actor(
        self,
        session_token: str,
        now: datetime,
    ) -> AuthenticatedActor:
        session = self.repository.get_session_by_hash(
            digest_secret(session_token)
        )
        if (
            session is None
            or session.revoked_at is not None
            or session.idle_expires_at <= now
            or session.absolute_expires_at <= now
        ):
            raise _session_expired()
        account = self.repository.get_account(session.account_id)
        if account is None or account.status != ACCOUNT_ACTIVE:
            raise _session_expired()

        if session.last_seen_at + timedelta(minutes=self.touch_minutes) <= now:
            session.last_seen_at = now
            session.idle_expires_at = min(
                now + timedelta(minutes=self.idle_minutes),
                session.absolute_expires_at,
            )
        return self._actor(account, session, now)

    def logout(
        self,
        session_token: str,
        csrf_token: str,
        now: datetime,
    ) -> None:
        session = self._require_session(session_token, now)
        self._require_csrf(session, csrf_token)
        self.repository.revoke_session(session, "LOGOUT", now)
        self._event("LOGOUT", session, now)

    def logout_all(
        self,
        actor: AuthenticatedActor,
        csrf_token: str,
        now: datetime,
    ) -> int:
        session = self._require_actor_session(actor, now)
        self._require_csrf(session, csrf_token)
        count = self.repository.revoke_account_sessions(
            actor.account_id, "LOGOUT_ALL", now
        )
        self._event("SESSIONS_REVOKED", session, now)
        return count

    def change_password(
        self,
        actor: AuthenticatedActor,
        current_password: str,
        new_password: str,
        csrf_token: str,
        now: datetime,
    ) -> None:
        session = self._require_actor_session(actor, now)
        self._require_csrf(session, csrf_token)
        account = self.repository.get_account(actor.account_id)
        if account is None or not self.password_hasher.verify_password(
            current_password, account.password_hash
        ):
            raise _authentication_failed()
        validate_new_password(
            new_password,
            minimum_length=self.password_min_length,
        )
        account.password_hash = self.password_hasher.hash_password(new_password)
        account.password_changed_at = now
        account.must_change_password = False
        account.record_version += 1
        self.repository.revoke_account_sessions(
            account.id, "PASSWORD_CHANGED", now
        )
        self.repository.add_event(
            AuthenticationEvent(
                id=uuid4(),
                account_id=account.id,
                session_id=session.id,
                event_type="PASSWORD_CHANGED",
                occurred_at=now,
                safe_context={},
            )
        )

    def _require_session(
        self,
        session_token: str,
        now: datetime,
    ) -> IdentitySession:
        session = self.repository.get_session_by_hash(
            digest_secret(session_token)
        )
        if (
            session is None
            or session.revoked_at is not None
            or session.idle_expires_at <= now
            or session.absolute_expires_at <= now
        ):
            raise _session_expired()
        return session

    def _require_actor_session(
        self,
        actor: AuthenticatedActor,
        now: datetime,
    ) -> IdentitySession:
        session = self.repository.get_session(actor.session_id)
        if (
            session is None
            or session.account_id != actor.account_id
            or session.revoked_at is not None
            or session.idle_expires_at <= now
            or session.absolute_expires_at <= now
        ):
            raise _session_expired()
        return session

    @staticmethod
    def _require_csrf(
        session: IdentitySession,
        csrf_token: str,
    ) -> None:
        if not compare_digest(
            session.csrf_token_hash,
            digest_secret(csrf_token),
        ):
            raise DomainError(
                403,
                CSRF_VALIDATION_FAILED,
                "Проверка CSRF не пройдена",
            )

    def _event(
        self,
        event_type: str,
        session: IdentitySession,
        now: datetime,
    ) -> None:
        self.repository.add_event(
            AuthenticationEvent(
                id=uuid4(),
                account_id=session.account_id,
                session_id=session.id,
                event_type=event_type,
                occurred_at=now,
                safe_context={},
            )
        )

    @staticmethod
    def _actor(
        account: UserAccount,
        session: IdentitySession,
        now: datetime,
    ) -> AuthenticatedActor:
        return AuthenticatedActor(
            account_id=account.id,
            session_id=session.id,
            worker_id=account.worker_id,
            authenticated_at=now,
            auth_method=AUTH_METHOD_LOCAL_PASSWORD,
            must_change_password=account.must_change_password,
        )


__all__ = [
    "IdentityService",
    "LocalPasswordAuthenticationProvider",
    "normalize_login",
]
