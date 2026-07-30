from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.identity.models import AuthenticationEvent, IdentitySession, UserAccount


class IdentityRepository:
    """Transactional persistence adapter; commit remains at the outer boundary."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_account_by_normalized_login(
        self, login: str
    ) -> UserAccount | None:
        statement = (
            select(UserAccount)
            .where(UserAccount.normalized_login == login)
            .with_for_update()
        )
        return self.db.scalars(statement).first()

    def get_account(self, account_id: UUID) -> UserAccount | None:
        statement = (
            select(UserAccount)
            .where(UserAccount.id == account_id)
            .with_for_update()
        )
        return self.db.scalars(statement).first()

    def get_session_by_hash(
        self, token_hash: str
    ) -> IdentitySession | None:
        statement = (
            select(IdentitySession)
            .where(IdentitySession.token_hash == token_hash)
            .with_for_update()
        )
        return self.db.scalars(statement).first()

    def get_session(self, session_id: UUID) -> IdentitySession | None:
        statement = (
            select(IdentitySession)
            .where(IdentitySession.id == session_id)
            .with_for_update()
        )
        return self.db.scalars(statement).first()

    def add_account(self, account: UserAccount) -> None:
        self.db.add(account)

    def add_session(self, session: IdentitySession) -> None:
        self.db.add(session)

    def revoke_session(
        self,
        session: IdentitySession,
        reason: str,
        now: datetime,
    ) -> None:
        session.revoked_at = now
        session.revocation_reason = reason

    def revoke_account_sessions(
        self,
        account_id: UUID,
        reason: str,
        now: datetime,
    ) -> int:
        statement = (
            update(IdentitySession)
            .where(
                IdentitySession.account_id == account_id,
                IdentitySession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revocation_reason=reason)
        )
        result = self.db.execute(statement)
        return int(result.rowcount or 0)

    def add_event(self, event: AuthenticationEvent) -> None:
        self.db.add(event)


__all__ = ["IdentityRepository"]
