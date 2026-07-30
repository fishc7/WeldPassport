from dataclasses import dataclass
from enum import StrEnum
import re


class RuntimeProfile(StrEnum):
    CANONICAL = "canonical"
    LEGACY_COMPATIBILITY = "legacy_compatibility"


@dataclass(frozen=True)
class RuntimeConfiguration:
    profile: RuntimeProfile
    legacy_schema: str | None


class RuntimeContractError(RuntimeError):
    def __init__(self, code: str, safe_detail: str) -> None:
        self.code = code
        self.safe_detail = safe_detail
        super().__init__(f"{code}: {safe_detail}")


_POSTGRES_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_legacy_schema_identifier(raw: str) -> str:
    if _POSTGRES_IDENTIFIER.fullmatch(raw) is None:
        raise RuntimeContractError(
            "LEGACY-CONTRACT-MISMATCH",
            "legacy schema identifier is invalid",
        )
    return raw


def resolve_runtime_configuration(
    *,
    runtime_profile: str | None,
    legacy_schema: str | None,
) -> RuntimeConfiguration:
    if runtime_profile is None:
        profile = RuntimeProfile.CANONICAL
    else:
        try:
            profile = RuntimeProfile(runtime_profile)
        except ValueError:
            raise RuntimeContractError(
                "RUNTIME-PROFILE-UNKNOWN",
                "runtime profile is not supported",
            ) from None

    if profile is RuntimeProfile.CANONICAL:
        return RuntimeConfiguration(profile=profile, legacy_schema=None)

    resolved_schema = "test" if legacy_schema is None else legacy_schema
    validate_legacy_schema_identifier(resolved_schema)
    return RuntimeConfiguration(profile=profile, legacy_schema=resolved_schema)
