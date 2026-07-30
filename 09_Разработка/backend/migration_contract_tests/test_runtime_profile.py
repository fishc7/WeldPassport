from dataclasses import FrozenInstanceError

import pytest

from app.shared.config import Settings
from app.shared.runtime_profile import (
    RuntimeConfiguration,
    RuntimeContractError,
    RuntimeProfile,
    resolve_runtime_configuration,
)


def test_runtime_001_absent_profile_is_canonical_and_ignores_legacy_input() -> None:
    secret_like_schema = 'ignored_invalid_"schema"_secret'

    configuration = resolve_runtime_configuration(
        runtime_profile=None,
        legacy_schema=secret_like_schema,
    )

    assert configuration == RuntimeConfiguration(
        profile=RuntimeProfile.CANONICAL,
        legacy_schema=None,
    )
    assert secret_like_schema not in repr(configuration)


def test_runtime_002_explicit_canonical_ignores_legacy_input() -> None:
    configuration = resolve_runtime_configuration(
        runtime_profile="canonical",
        legacy_schema='invalid "schema"',
    )

    assert configuration.profile is RuntimeProfile.CANONICAL
    assert configuration.legacy_schema is None


@pytest.mark.parametrize("raw", ["", "CANONICAL", "unknown", " canonical "])
def test_runtime_003_explicit_invalid_profile_fails_without_echoing_input(
    raw: str,
) -> None:
    with pytest.raises(RuntimeContractError) as exc_info:
        resolve_runtime_configuration(runtime_profile=raw, legacy_schema=None)

    assert exc_info.value.code == "RUNTIME-PROFILE-UNKNOWN"
    assert exc_info.value.safe_detail == "runtime profile is not supported"
    if raw:
        assert raw not in str(exc_info.value)


def test_runtime_004_legacy_profile_uses_default_schema() -> None:
    configuration = resolve_runtime_configuration(
        runtime_profile="legacy_compatibility",
        legacy_schema=None,
    )

    assert configuration == RuntimeConfiguration(
        profile=RuntimeProfile.LEGACY_COMPATIBILITY,
        legacy_schema="test",
    )


def test_runtime_005_legacy_profile_accepts_valid_schema() -> None:
    configuration = resolve_runtime_configuration(
        runtime_profile="legacy_compatibility",
        legacy_schema="legacy_fixture_$1",
    )

    assert configuration.legacy_schema == "legacy_fixture_$1"


@pytest.mark.parametrize(
    "raw",
    ["", "1legacy", "legacy-schema", "legacy.schema", 'legacy"schema', "схема"],
)
def test_runtime_006_invalid_legacy_schema_fails_without_echoing_input(
    raw: str,
) -> None:
    with pytest.raises(RuntimeContractError) as exc_info:
        resolve_runtime_configuration(
            runtime_profile="legacy_compatibility",
            legacy_schema=raw,
        )

    assert exc_info.value.code == "LEGACY-CONTRACT-MISMATCH"
    assert exc_info.value.safe_detail == "legacy schema identifier is invalid"
    if raw:
        assert raw not in str(exc_info.value)


def test_runtime_007_configuration_is_immutable() -> None:
    configuration = RuntimeConfiguration(
        profile=RuntimeProfile.CANONICAL,
        legacy_schema=None,
    )

    with pytest.raises(FrozenInstanceError):
        configuration.legacy_schema = "mutated"  # type: ignore[misc]


def test_runtime_008_settings_exposes_raw_runtime_inputs(monkeypatch) -> None:
    monkeypatch.setenv(
        "WELDPASSPORT_RUNTIME_PROFILE",
        "legacy_compatibility",
    )
    monkeypatch.setenv("WELDPASSPORT_LEGACY_SCHEMA", "legacy_fixture")

    raw_settings = Settings(_env_file=None)

    assert raw_settings.runtime_profile == "legacy_compatibility"
    assert raw_settings.legacy_schema == "legacy_fixture"
