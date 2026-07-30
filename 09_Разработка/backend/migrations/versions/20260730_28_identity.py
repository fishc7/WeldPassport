"""add identity authentication schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260730_28_identity"
down_revision = "canonical_baseline_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text('CREATE SCHEMA "identity"'))
    op.create_table(
        "user_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("normalized_login", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "record_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="ck_identity_user_accounts_status",
        ),
        sa.CheckConstraint(
            "failed_login_count >= 0",
            name="ck_identity_user_accounts_failed_login_count",
        ),
        sa.CheckConstraint(
            "record_version > 0",
            name="ck_identity_user_accounts_record_version",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["hr.workers.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_login",
            name="uq_identity_user_accounts_normalized_login",
        ),
        sa.UniqueConstraint(
            "worker_id",
            name="uq_identity_user_accounts_worker_id",
        ),
        schema="identity",
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "idle_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "absolute_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=100), nullable=True),
        sa.Column("user_agent_digest", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_identity_sessions_expiry_order",
        ),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR revoked_at IS NOT NULL",
            name="ck_identity_sessions_revocation",
        ),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_identity_sessions_token_hash",
        ),
        sa.CheckConstraint(
            "length(csrf_token_hash) = 64",
            name="ck_identity_sessions_csrf_hash",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["identity.user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_identity_sessions_token_hash",
        ),
        schema="identity",
    )
    op.create_index(
        op.f("ix_identity_sessions_account_id"),
        "sessions",
        ["account_id"],
        unique=False,
        schema="identity",
    )
    op.create_table(
        "authentication_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "safe_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('ACCOUNT_CREATED','WORKER_BOUND','ACCOUNT_DISABLED',"
            "'ACCOUNT_UNLOCKED','TEMPORARY_PASSWORD_SET',"
            "'LOGIN_SUCCEEDED','LOGIN_FAILED','ACCOUNT_LOCKED',"
            "'PASSWORD_CHANGED','LOGOUT','SESSION_REVOKED','SESSIONS_REVOKED')",
            name="ck_identity_authentication_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["identity.user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["identity.sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index(
        op.f("ix_identity_authentication_events_account_id"),
        "authentication_events",
        ["account_id"],
        unique=False,
        schema="identity",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM identity.user_accounts LIMIT 1
              ) OR EXISTS (
                SELECT 1 FROM identity.sessions LIMIT 1
              ) OR EXISTS (
                SELECT 1 FROM identity.authentication_events LIMIT 1
              ) THEN
                RAISE EXCEPTION
                  'identity downgrade refused: tables are not empty';
              END IF;
            END
            $$;
            """
        )
    )
    op.drop_index(
        op.f("ix_identity_authentication_events_account_id"),
        table_name="authentication_events",
        schema="identity",
    )
    op.drop_table("authentication_events", schema="identity")
    op.drop_index(
        op.f("ix_identity_sessions_account_id"),
        table_name="sessions",
        schema="identity",
    )
    op.drop_table("sessions", schema="identity")
    op.drop_table("user_accounts", schema="identity")
    op.execute(sa.text('DROP SCHEMA "identity"'))
