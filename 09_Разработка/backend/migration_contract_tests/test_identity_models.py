from sqlalchemy import CheckConstraint, UniqueConstraint


def _unique_columns(table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_identity_models_001_register_exact_canonical_tables() -> None:
    from app.identity.models import (
        AuthenticationEvent,
        IdentitySession,
        UserAccount,
    )

    assert {
        UserAccount.__table__.fullname,
        IdentitySession.__table__.fullname,
        AuthenticationEvent.__table__.fullname,
    } == {
        "identity.user_accounts",
        "identity.sessions",
        "identity.authentication_events",
    }


def test_identity_models_002_account_has_unique_login_and_worker_binding() -> None:
    from app.identity.models import UserAccount

    assert {
        ("normalized_login",),
        ("worker_id",),
    }.issubset(_unique_columns(UserAccount.__table__))
    assert "password" not in UserAccount.__table__.c
    assert "password_hash" in UserAccount.__table__.c


def test_identity_models_003_session_persists_only_secret_hashes() -> None:
    from app.identity.models import IdentitySession

    columns = IdentitySession.__table__.c
    assert columns.token_hash.type.length == 64
    assert columns.csrf_token_hash.type.length == 64
    assert "session_token" not in columns
    assert "csrf_token" not in columns
    assert ("token_hash",) in _unique_columns(IdentitySession.__table__)


def test_identity_models_004_tables_define_fail_closed_checks() -> None:
    from app.identity.models import AuthenticationEvent, IdentitySession, UserAccount

    names = {
        constraint.name
        for table in (
            UserAccount.__table__,
            IdentitySession.__table__,
            AuthenticationEvent.__table__,
        )
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_identity_user_accounts_status",
        "ck_identity_user_accounts_failed_login_count",
        "ck_identity_user_accounts_record_version",
        "ck_identity_sessions_expiry_order",
        "ck_identity_sessions_revocation",
        "ck_identity_sessions_token_hash",
        "ck_identity_sessions_csrf_hash",
        "ck_identity_authentication_events_type",
    }.issubset(names)


def test_identity_models_005_canonical_boundary_includes_identity() -> None:
    from app.shared.canonical_metadata import (
        CANONICAL_MODEL_MODULES,
        CANONICAL_SCHEMAS,
        canonical_metadata,
    )

    assert "identity" in CANONICAL_SCHEMAS
    assert "app.identity.models" in CANONICAL_MODEL_MODULES
    assert len(canonical_metadata.tables) == 76
