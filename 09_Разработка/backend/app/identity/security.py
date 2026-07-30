from __future__ import annotations

from hashlib import sha256
import secrets

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from app.identity.constants import PASSWORD_POLICY_FAILED
from app.shared.errors import DomainError


class PasswordHasher:
    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher(type=Type.ID)

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password: str, encoded: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (InvalidHashError, VerificationError):
            return False


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def digest_secret(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


def validate_new_password(password: str, *, minimum_length: int) -> None:
    if len(password) < minimum_length:
        raise DomainError(
            422,
            PASSWORD_POLICY_FAILED,
            "Пароль не соответствует политике безопасности",
        )
