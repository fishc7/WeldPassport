from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.orm import Base

IDENTITY_SCHEMA = "identity"

_EVENT_TYPES = (
    "LOGIN_SUCCEEDED",
    "LOGIN_FAILED",
    "ACCOUNT_LOCKED",
    "PASSWORD_CHANGED",
    "LOGOUT",
    "SESSION_REVOKED",
    "SESSIONS_REVOKED",
)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint(
            "normalized_login",
            name="uq_identity_user_accounts_normalized_login",
        ),
        UniqueConstraint(
            "worker_id",
            name="uq_identity_user_accounts_worker_id",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="ck_identity_user_accounts_status",
        ),
        CheckConstraint(
            "failed_login_count >= 0",
            name="ck_identity_user_accounts_failed_login_count",
        ),
        CheckConstraint(
            "record_version > 0",
            name="ck_identity_user_accounts_record_version",
        ),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    login: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_login: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACTIVE",
        server_default="ACTIVE",
    )
    worker_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("hr.workers.id", ondelete="RESTRICT"),
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    record_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class IdentitySession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint(
            "token_hash",
            name="uq_identity_sessions_token_hash",
        ),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_identity_sessions_expiry_order",
        ),
        CheckConstraint(
            "revocation_reason IS NULL OR revoked_at IS NOT NULL",
            name="ck_identity_sessions_revocation",
        ),
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_identity_sessions_token_hash",
        ),
        CheckConstraint(
            "length(csrf_token_hash) = 64",
            name="ck_identity_sessions_csrf_hash",
        ),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(100))
    user_agent_digest: Mapped[str | None] = mapped_column(String(64))


class AuthenticationEvent(Base):
    __tablename__ = "authentication_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN (" + ",".join(f"'{item}'" for item in _EVENT_TYPES) + ")",
            name="ck_identity_authentication_events_type",
        ),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.user_accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.sessions.id", ondelete="RESTRICT"),
    )
    safe_context: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
