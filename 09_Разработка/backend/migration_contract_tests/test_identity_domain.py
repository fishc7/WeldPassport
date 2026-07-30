from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest


def test_identity_domain_001_password_hash_is_argon2id_and_verifies() -> None:
    from app.identity.security import PasswordHasher

    hasher = PasswordHasher()
    encoded = hasher.hash_password("correct horse battery")

    assert encoded.startswith("$argon2id$")
    assert hasher.verify_password("correct horse battery", encoded) is True
    assert hasher.verify_password("wrong password", encoded) is False


def test_identity_domain_002_secret_digest_is_stable_and_one_way() -> None:
    from app.identity.security import digest_secret, generate_secret

    secret = generate_secret()
    digest = digest_secret(secret)

    assert len(secret) >= 43
    assert len(digest) == 64
    assert digest == digest_secret(secret)
    assert secret not in digest


def test_identity_domain_003_actor_is_immutable() -> None:
    from app.identity.domain import AuthenticatedActor

    actor = AuthenticatedActor(
        account_id=uuid4(),
        session_id=uuid4(),
        worker_id=1,
        authenticated_at=datetime.now(UTC),
        auth_method="LOCAL_PASSWORD",
        must_change_password=False,
    )

    with pytest.raises(FrozenInstanceError):
        actor.worker_id = 2  # type: ignore[misc]


def test_identity_domain_004_short_password_fails_without_echo() -> None:
    from app.identity.security import validate_new_password
    from app.shared.errors import DomainError

    raw_password = "too-short"
    with pytest.raises(DomainError) as exc_info:
        validate_new_password(raw_password, minimum_length=12)

    assert exc_info.value.code == "PASSWORD_POLICY_FAILED"
    assert raw_password not in str(exc_info.value.detail)


def test_identity_domain_005_production_rejects_insecure_cookie() -> None:
    from app.identity.domain import validate_auth_configuration
    from app.shared.runtime_profile import RuntimeContractError

    with pytest.raises(RuntimeContractError) as exc_info:
        validate_auth_configuration(
            deployment_environment="production",
            cookie_secure=False,
        )

    assert exc_info.value.code == "AUTH-CONFIG-UNSAFE"
    validate_auth_configuration(
        deployment_environment="development",
        cookie_secure=False,
    )
