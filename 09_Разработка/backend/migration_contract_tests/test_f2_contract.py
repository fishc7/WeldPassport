from dataclasses import FrozenInstanceError

import pytest

from app.testing.f2_contract import (
    F2Error,
    F2MachineStatus,
    F2ParentInputs,
    F2Role,
    F2TargetInput,
    load_parent_inputs,
)


def _environment() -> dict[str, str]:
    environment = {
        "WELDPASSPORT_F2_WORKING_DATABASE_URL": "working-secret",
        "WELDPASSPORT_F2_EVIDENCE_DIR": "C:/evidence",
        "WELDPASSPORT_F2_OPERATOR_AUTHORIZATION": (
            "I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL"
        ),
        "WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS": "YES",
    }
    for prefix in ("CANONICAL", "LEGACY_COMPATIBLE", "LEGACY_NEGATIVE"):
        environment[f"WELDPASSPORT_F2_{prefix}_TEST_DATABASE_URL"] = (
            f"{prefix}-url-secret"
        )
        environment[f"WELDPASSPORT_F2_{prefix}_DATABASE_CONFIRM"] = (
            f"{prefix.lower()}_test"
        )
        environment[f"WELDPASSPORT_F2_{prefix}_OWNERSHIP_TOKEN"] = (
            f"{prefix}-token-secret"
        )
    return environment


def test_f2_contract_001_loads_exact_order_and_redacts_secrets() -> None:
    inputs = load_parent_inputs(_environment())

    assert isinstance(inputs, F2ParentInputs)
    assert tuple(target.role for target in inputs.targets) == (
        F2Role.CANONICAL,
        F2Role.LEGACY_COMPATIBLE,
        F2Role.LEGACY_NEGATIVE,
    )
    rendered = repr(inputs)
    for forbidden in ("working-secret", "url-secret", "token-secret"):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "name,value",
    [
        ("WELDPASSPORT_F2_OPERATOR_AUTHORIZATION", "wrong"),
        ("WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS", "yes"),
        ("WELDPASSPORT_F2_CANONICAL_TEST_DATABASE_URL", ""),
    ],
)
def test_f2_contract_002_rejects_missing_or_nonexact_input(
    name: str,
    value: str,
) -> None:
    environment = _environment()
    environment[name] = value

    with pytest.raises(F2Error) as exc_info:
        load_parent_inputs(environment)

    assert exc_info.value.code == "TEST-DB-F2-AUTHORIZATION-MISSING"
    if value:
        assert value not in str(exc_info.value)


def test_f2_contract_003_rejects_unknown_f2_variable() -> None:
    environment = _environment()
    environment["WELDPASSPORT_F2_UNEXPECTED_SECRET"] = "must-not-leak"

    with pytest.raises(F2Error) as exc_info:
        load_parent_inputs(environment)

    assert exc_info.value.code == "TEST-DB-F2-AUTHORIZATION-MISSING"
    assert "must-not-leak" not in str(exc_info.value)


def test_f2_contract_004_contract_values_are_immutable() -> None:
    target = F2TargetInput(F2Role.CANONICAL, "url", "name", "token")

    with pytest.raises(FrozenInstanceError):
        target.confirmed_name = "changed"  # type: ignore[misc]

    assert F2MachineStatus.REHEARSAL_VERIFIED == "TEST_DB_F2_REHEARSAL_VERIFIED"
