"""Проверки Pydantic-схем HR-модуля worker_roles (без PostgreSQL)."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.hr.schemas import WorkerRoleCreate, WorkerRoleUpdate


def test_worker_role_create_defaults_to_global_scope() -> None:
    payload = WorkerRoleCreate(role_code="WELDER")
    assert payload.scope_type == "GLOBAL"
    assert payload.scope_id is None


def test_worker_role_create_rejects_invalid_role_code() -> None:
    with pytest.raises(ValidationError):
        WorkerRoleCreate(role_code="MASTER")  # type: ignore[arg-type]


def test_worker_role_create_accepts_all_role_codes() -> None:
    codes = [
        "WELDER",
        "FOREMAN",
        "PTO_ENGINEER",
        "OTK_INSPECTOR",
        "NDT_SPECIALIST",
        "OGS_ENGINEER",
        "CONFIRMING_PERSON",
        "CLOSING_RESPONSIBLE",
    ]
    for code in codes:
        payload = WorkerRoleCreate(role_code=code)  # type: ignore[arg-type]
        assert payload.role_code == code


def test_worker_role_update_allows_partial_patch() -> None:
    payload = WorkerRoleUpdate(note="временно", is_active=False)
    assert payload.note == "временно"
    assert payload.is_active is False
    assert payload.scope_type is None


def test_worker_role_create_with_project_scope() -> None:
    payload = WorkerRoleCreate(
        role_code="CONFIRMING_PERSON",
        scope_type="PROJECT",
        scope_id=12,
        valid_from=date(2026, 7, 3),
    )
    assert payload.scope_type == "PROJECT"
    assert payload.scope_id == 12
