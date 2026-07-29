"""Минимальные проверки HR-модуля (без PostgreSQL)."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.hr.schemas import WorkerCreate, WorkerDismiss, WorkerUpdate


def test_worker_create_requires_names() -> None:
    with pytest.raises(ValidationError):
        WorkerCreate(company_id=1, last_name="", first_name="Иван")


def test_worker_dismiss_accepts_optional_date() -> None:
    payload = WorkerDismiss(dismissal_date=date(2026, 7, 1), note="увольнение")
    assert payload.dismissal_date == date(2026, 7, 1)


def test_worker_update_allows_partial_patch() -> None:
    payload = WorkerUpdate(phone="+79990001122")
    assert payload.phone == "+79990001122"
    assert payload.last_name is None
