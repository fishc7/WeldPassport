from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import getpass
import json
import sys
from uuid import uuid4

from app.identity.constants import ACCOUNT_DISABLED, IDENTITY_CONFLICT
from app.identity.models import AuthenticationEvent, UserAccount
from app.identity.repository import IdentityRepository
from app.identity.security import PasswordHasher, validate_new_password
from app.identity.services import normalize_login
from app.shared.config import settings
from app.shared.db import SessionLocal


_OPERATOR_FAILED = {"status": "error", "code": "IDENTITY_OPERATOR_FAILED"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Безопасное управление локальными учётными записями"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def target(name: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name)
        command.add_argument("--login", required=True)
        command.add_argument("--confirm-login", required=True)
        return command

    create = target("create-account")
    create.add_argument("--worker-id", type=int)
    bind = target("bind-worker")
    bind.add_argument("--worker-id", type=int, required=True)
    target("disable-account")
    target("unlock-account")
    target("set-temporary-password")
    target("revoke-sessions")
    return parser


def _event(account_id, event_code: str, now: datetime) -> AuthenticationEvent:
    return AuthenticationEvent(
        id=uuid4(),
        account_id=account_id,
        event_type=event_code,
        occurred_at=now,
        safe_context={},
    )


def _success(account: UserAccount, event_code: str) -> dict[str, str]:
    return {
        "status": "ok",
        "account_id": str(account.id),
        "event_code": event_code,
    }


def execute(
    argv: Sequence[str],
    *,
    repository,
    password_reader: Callable[[str], str] = getpass.getpass,
    password_hasher: PasswordHasher | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    try:
        args = build_parser().parse_args(list(argv))
        if args.login != args.confirm_login:
            return dict(_OPERATOR_FAILED)

        operation_time = now or datetime.now(UTC)
        hasher = password_hasher or PasswordHasher()
        normalized_login = normalize_login(args.login)

        if args.command == "create-account":
            if repository.get_account_by_normalized_login(normalized_login):
                raise ValueError(IDENTITY_CONFLICT)
            password = password_reader("Временный пароль: ")
            validate_new_password(
                password,
                minimum_length=settings.auth_password_min_length,
            )
            account = UserAccount(
                id=uuid4(),
                login=args.login.strip(),
                normalized_login=normalized_login,
                password_hash=hasher.hash_password(password),
                status="ACTIVE",
                worker_id=args.worker_id,
                must_change_password=True,
                failed_login_count=0,
                password_changed_at=operation_time,
                created_at=operation_time,
                updated_at=operation_time,
                record_version=1,
            )
            event_code = "ACCOUNT_CREATED"
            repository.add_account(account)
        else:
            account = repository.get_account_by_normalized_login(
                normalized_login
            )
            if account is None:
                raise ValueError(IDENTITY_CONFLICT)

            if args.command == "bind-worker":
                account.worker_id = args.worker_id
                event_code = "WORKER_BOUND"
            elif args.command == "disable-account":
                account.status = ACCOUNT_DISABLED
                repository.revoke_account_sessions(
                    account.id, "ACCOUNT_DISABLED", operation_time
                )
                event_code = "ACCOUNT_DISABLED"
            elif args.command == "unlock-account":
                account.failed_login_count = 0
                account.locked_until = None
                event_code = "ACCOUNT_UNLOCKED"
            elif args.command == "set-temporary-password":
                password = password_reader("Новый временный пароль: ")
                validate_new_password(
                    password,
                    minimum_length=settings.auth_password_min_length,
                )
                account.password_hash = hasher.hash_password(password)
                account.password_changed_at = operation_time
                account.must_change_password = True
                repository.revoke_account_sessions(
                    account.id,
                    "TEMPORARY_PASSWORD_SET",
                    operation_time,
                )
                event_code = "TEMPORARY_PASSWORD_SET"
            elif args.command == "revoke-sessions":
                repository.revoke_account_sessions(
                    account.id, "OPERATOR_REVOKED", operation_time
                )
                event_code = "SESSIONS_REVOKED"
            else:
                raise ValueError("unsupported command")

            account.updated_at = operation_time
            account.record_version += 1

        repository.add_event(_event(account.id, event_code, operation_time))
        return _success(account, event_code)
    except (KeyboardInterrupt, SystemExit):
        return dict(_OPERATOR_FAILED)
    except Exception:
        return dict(_OPERATOR_FAILED)


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory=SessionLocal,
    output: Callable[[str], None] = print,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(item in {"-h", "--help"} for item in arguments):
        build_parser().print_help()
        return 0

    db = session_factory()
    try:
        result = execute(
            arguments,
            repository=IdentityRepository(db),
        )
        if result["status"] == "ok":
            db.commit()
            exit_code = 0
        else:
            db.rollback()
            exit_code = 1
        output(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return exit_code
    except Exception:
        db.rollback()
        output(json.dumps(_OPERATOR_FAILED, sort_keys=True))
        return 1
    finally:
        db.close()


__all__ = ["build_parser", "execute", "main"]
