from __future__ import annotations

from uuid import uuid4

from app.identity.models import UserAccount


class FakeRepository:
    def __init__(self, account: UserAccount | None = None) -> None:
        self.account = account
        self.accounts: list[UserAccount] = []
        self.events: list[object] = []
        self.revocations: list[tuple] = []
        self.lookups: list[str] = []

    def get_account_by_normalized_login(self, login):
        self.lookups.append(login)
        if self.account and self.account.normalized_login == login:
            return self.account
        return None

    def add_account(self, account):
        self.account = account
        self.accounts.append(account)

    def add_event(self, event):
        self.events.append(event)

    def revoke_account_sessions(self, account_id, reason, now):
        self.revocations.append((account_id, reason, now))
        return 2


class FakeHasher:
    def hash_password(self, password):
        return f"hash:{password}"


def _account() -> UserAccount:
    return UserAccount(
        id=uuid4(),
        login="Operator",
        normalized_login="operator",
        password_hash="hash:old",
        status="ACTIVE",
        worker_id=17,
        must_change_password=False,
        failed_login_count=3,
        record_version=1,
    )


def _execute(argv, repository, password="temporary-secret"):
    from app.identity.operator_cli import execute

    return execute(
        argv,
        repository=repository,
        password_reader=lambda _prompt: password,
        password_hasher=FakeHasher(),
    )


def test_identity_operator_001_help_has_no_password_option() -> None:
    from app.identity.operator_cli import build_parser

    help_text = build_parser().format_help().lower()

    assert "--password" not in help_text
    assert "create-account" in help_text
    assert "set-temporary-password" in help_text


def test_identity_operator_002_wrong_confirmation_has_no_repository_calls() -> None:
    repository = FakeRepository()

    result = _execute(
        [
            "create-account",
            "--login",
            "Operator",
            "--confirm-login",
            "operator",
        ],
        repository,
    )

    assert result == {"status": "error", "code": "IDENTITY_OPERATOR_FAILED"}
    assert repository.lookups == []
    assert repository.accounts == []


def test_identity_operator_003_create_normalizes_and_forces_change() -> None:
    repository = FakeRepository()

    result = _execute(
        [
            "create-account",
            "--login",
            " Operator ",
            "--confirm-login",
            " Operator ",
            "--worker-id",
            "17",
        ],
        repository,
    )

    account = repository.accounts[0]
    assert account.normalized_login == "operator"
    assert account.password_hash == "hash:temporary-secret"
    assert account.must_change_password is True
    assert set(result) == {"status", "account_id", "event_code"}
    assert "temporary-secret" not in str(result)


def test_identity_operator_004_disable_revokes_sessions() -> None:
    account = _account()
    repository = FakeRepository(account)

    result = _execute(
        [
            "disable-account",
            "--login",
            "Operator",
            "--confirm-login",
            "Operator",
        ],
        repository,
    )

    assert account.status == "DISABLED"
    assert repository.revocations
    assert result["event_code"] == "ACCOUNT_DISABLED"


def test_identity_operator_005_reset_is_hidden_and_revokes() -> None:
    account = _account()
    repository = FakeRepository(account)

    result = _execute(
        [
            "set-temporary-password",
            "--login",
            "Operator",
            "--confirm-login",
            "Operator",
        ],
        repository,
        password="new-temporary",
    )

    assert account.password_hash == "hash:new-temporary"
    assert account.must_change_password is True
    assert repository.revocations
    assert "new-temporary" not in str(result)


def test_identity_operator_006_raw_exception_is_redacted() -> None:
    class BrokenRepository(FakeRepository):
        def get_account_by_normalized_login(self, login):
            raise RuntimeError("password=must-not-leak")

    result = _execute(
        [
            "disable-account",
            "--login",
            "Operator",
            "--confirm-login",
            "Operator",
        ],
        BrokenRepository(),
    )

    assert result == {"status": "error", "code": "IDENTITY_OPERATOR_FAILED"}
