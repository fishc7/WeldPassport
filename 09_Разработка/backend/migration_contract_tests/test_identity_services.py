from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.identity.constants import (
    ACTOR_WORKER_INACTIVE,
    AUTHENTICATION_FAILED,
    CSRF_VALIDATION_FAILED,
    PASSWORD_CHANGE_REQUIRED,
    SESSION_EXPIRED,
)
from app.identity.domain import AuthenticatedActor
from app.identity.models import IdentitySession, UserAccount
from app.shared.errors import DomainError


NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self, account: UserAccount | None = None) -> None:
        self.account = account
        self.sessions: list[IdentitySession] = []
        self.events: list[object] = []

    def get_account_by_normalized_login(self, login: str):
        if self.account and self.account.normalized_login == login:
            return self.account
        return None

    def get_account(self, account_id):
        if self.account and self.account.id == account_id:
            return self.account
        return None

    def get_session_by_hash(self, token_hash: str):
        return next(
            (item for item in self.sessions if item.token_hash == token_hash),
            None,
        )

    def get_session(self, session_id):
        return next((item for item in self.sessions if item.id == session_id), None)

    def add_session(self, session):
        self.sessions.append(session)

    def revoke_session(self, session, reason, now):
        session.revoked_at = now
        session.revocation_reason = reason

    def revoke_account_sessions(self, account_id, reason, now):
        count = 0
        for session in self.sessions:
            if session.account_id == account_id and session.revoked_at is None:
                self.revoke_session(session, reason, now)
                count += 1
        return count

    def add_event(self, event):
        self.events.append(event)


class FakeHasher:
    def hash_password(self, password: str) -> str:
        return f"hash:{password}"

    def verify_password(self, password: str, encoded: str) -> bool:
        return encoded == f"hash:{password}"


def _account(**overrides) -> UserAccount:
    values = {
        "id": uuid4(),
        "login": "Operator",
        "normalized_login": "operator",
        "password_hash": "hash:correct-password",
        "status": "ACTIVE",
        "worker_id": 17,
        "must_change_password": False,
        "failed_login_count": 0,
        "record_version": 1,
    }
    values.update(overrides)
    return UserAccount(**values)


def _service(repository: FakeRepository):
    from app.identity.services import IdentityService

    return IdentityService(repository, password_hasher=FakeHasher())


def _code(exc_info) -> str:
    return exc_info.value.code


@pytest.mark.parametrize(
    "account,password",
    [(None, "wrong"), (_account(), "wrong")],
)
def test_identity_service_001_uses_generic_login_failure(account, password) -> None:
    service = _service(FakeRepository(account))

    with pytest.raises(DomainError) as exc_info:
        service.login("operator", password, NOW)

    assert _code(exc_info) == AUTHENTICATION_FAILED


def test_identity_service_002_fifth_failure_locks_account() -> None:
    account = _account(failed_login_count=4)
    service = _service(FakeRepository(account))

    with pytest.raises(DomainError):
        service.login("operator", "wrong", NOW)

    assert account.failed_login_count == 5
    assert account.locked_until == NOW + timedelta(minutes=15)


def test_identity_service_003_login_persists_only_hashes() -> None:
    repository = FakeRepository(_account(failed_login_count=2))
    issued = _service(repository).login(" Operator ", "correct-password", NOW)

    persisted = repository.sessions[0]
    assert persisted.token_hash != issued.session_token
    assert persisted.csrf_token_hash != issued.csrf_token
    assert len(persisted.token_hash) == 64
    assert len(persisted.csrf_token_hash) == 64
    assert repository.account.failed_login_count == 0
    assert repository.account.locked_until is None


@pytest.mark.parametrize(
    "account",
    [
        _account(status="DISABLED"),
        _account(locked_until=NOW + timedelta(minutes=1)),
    ],
)
def test_identity_service_004_disabled_or_locked_is_generic(account) -> None:
    with pytest.raises(DomainError) as exc_info:
        _service(FakeRepository(account)).login(
            "operator", "correct-password", NOW
        )

    assert _code(exc_info) == AUTHENTICATION_FAILED


def test_identity_service_005_expired_or_revoked_session_is_stable() -> None:
    repository = FakeRepository(_account())
    issued = _service(repository).login("operator", "correct-password", NOW)
    repository.sessions[0].revoked_at = NOW

    with pytest.raises(DomainError) as exc_info:
        _service(repository).resolve_actor(
            issued.session_token, NOW + timedelta(seconds=1)
        )

    assert _code(exc_info) == SESSION_EXPIRED


def test_identity_service_006_csrf_mismatch_is_rejected() -> None:
    repository = FakeRepository(_account())
    issued = _service(repository).login("operator", "correct-password", NOW)

    with pytest.raises(DomainError) as exc_info:
        _service(repository).logout(issued.session_token, "wrong", NOW)

    assert _code(exc_info) == CSRF_VALIDATION_FAILED


def test_identity_service_007_password_change_revokes_all_sessions() -> None:
    repository = FakeRepository(_account())
    service = _service(repository)
    first = service.login("operator", "correct-password", NOW)
    service.login("operator", "correct-password", NOW)

    service.change_password(
        first.actor,
        "correct-password",
        "a-new-password",
        first.csrf_token,
        NOW,
    )

    assert repository.account.password_hash == "hash:a-new-password"
    assert all(item.revoked_at == NOW for item in repository.sessions)


def test_identity_service_008_touch_is_throttled() -> None:
    repository = FakeRepository(_account())
    service = _service(repository)
    issued = service.login("operator", "correct-password", NOW)
    persisted = repository.sessions[0]

    service.resolve_actor(issued.session_token, NOW + timedelta(minutes=4))
    assert persisted.last_seen_at == NOW
    service.resolve_actor(issued.session_token, NOW + timedelta(minutes=6))
    assert persisted.last_seen_at == NOW + timedelta(minutes=6)


def test_identity_service_009_hr_adapter_is_fail_closed() -> None:
    from app.hr.actor_port import HrActorPort

    class MissingSession:
        def get(self, _model, _worker_id):
            return None

    with pytest.raises(DomainError) as exc_info:
        HrActorPort(MissingSession()).require_active_worker(17)

    assert _code(exc_info) == ACTOR_WORKER_INACTIVE


def test_identity_service_010_business_actor_requires_password_change() -> None:
    from app.hr.actor_port import HrActorPort

    actor = AuthenticatedActor(
        account_id=uuid4(),
        session_id=uuid4(),
        worker_id=17,
        authenticated_at=NOW,
        auth_method="LOCAL_PASSWORD",
        must_change_password=True,
    )

    with pytest.raises(DomainError) as exc_info:
        HrActorPort(object()).require_business_actor(actor)

    assert _code(exc_info) == PASSWORD_CHANGE_REQUIRED
