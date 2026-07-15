"""Тесты Pydantic-схем quality (Task 9C, блок 9C-6A).

Проверяют поведение схем без API и без БД: `extra="forbid"`, обязательный
`expected_version`, UUID-типы, non-empty-валидаторы, enum-Literal, значения по
умолчанию и чтение из ORM-подобного объекта через `from_attributes`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.quality.execution_schemas import (
    CancelExecutionCommand,
    ConfirmExecutionCommand,
    ExternalPersonRead,
    MarkPerformedCommand,
    MethodExecutionCreate,
    ParticipantCreate,
    ResultItemCreate,
    StandardRead,
)
from app.quality.laboratory_conclusion_schemas import (
    AddConclusionExecutionCommand,
    ConclusionCreate,
    CreateConclusionRevisionCommand,
    PrepareConclusionCommand,
)

UTC = timezone.utc


# ── extra="forbid" ──────────────────────────────────────────────────────────────


def test_forbid_extra_keys() -> None:
    with pytest.raises(ValidationError):
        MethodExecutionCreate(bogus=1)
    with pytest.raises(ValidationError):
        ConclusionCreate(
            project_id=uuid4(),
            laboratory_company_id=1,
            inspection_method_id="UT",
            unexpected="x",
        )


# ── expected_version обязателен ─────────────────────────────────────────────────


def test_expected_version_required() -> None:
    with pytest.raises(ValidationError):
        CancelExecutionCommand(cancellation_type="OTHER", cancellation_reason="x")
    with pytest.raises(ValidationError):
        PrepareConclusionCommand()


# ── UUID-типы ───────────────────────────────────────────────────────────────────


def test_uuid_validation() -> None:
    with pytest.raises(ValidationError):
        ParticipantCreate(person_id="not-a-uuid", participant_role="INSPECTOR")
    with pytest.raises(ValidationError):
        AddConclusionExecutionCommand(method_execution_id="nope")
    ok = ParticipantCreate(person_id=uuid4(), participant_role="LEAD_INSPECTOR")
    assert ok.participant_role == "LEAD_INSPECTOR"


# ── non-empty валидаторы ────────────────────────────────────────────────────────


def test_non_empty_reasons() -> None:
    with pytest.raises(ValidationError):
        CancelExecutionCommand(
            expected_version=1, cancellation_type="OTHER", cancellation_reason="   "
        )
    with pytest.raises(ValidationError):
        CreateConclusionRevisionCommand(expected_version=1, correction_reason="")


# ── enum-Literal ────────────────────────────────────────────────────────────────


def test_enum_literals_rejected() -> None:
    with pytest.raises(ValidationError):
        ResultItemCreate(evaluation="BOGUS")
    with pytest.raises(ValidationError):
        ConfirmExecutionCommand(expected_version=1, confirmation_mode="NOPE")
    with pytest.raises(ValidationError):
        ConclusionCreate(
            project_id=uuid4(),
            laboratory_company_id=1,
            inspection_method_id="ZZ",
        )


# ── значения по умолчанию ───────────────────────────────────────────────────────


def test_defaults() -> None:
    assert MarkPerformedCommand(expected_version=1).time_precision == "DATE_ONLY"
    assert (
        ConfirmExecutionCommand(expected_version=1).confirmation_mode
        == "EXTERNAL_DOCUMENT_REGISTRATION"
    )
    item = ResultItemCreate()
    assert item.controlled_object_type == "WHOLE_JOINT"
    assert item.evaluation == "NOT_EVALUATED"
    assert item.wraps_zero is False


# ── from_attributes (ORM не переносится напрямую) ──────────────────────────────


def test_read_from_attributes() -> None:
    now = datetime.now(UTC)
    ns = SimpleNamespace(
        id=uuid4(),
        full_name="Иванов",
        organization_company_id=7,
        external_ref="EXT-1",
        note=None,
        created_by_worker_id=1,
        created_at=now,
        updated_by_worker_id=1,
        updated_at=now,
    )
    read = ExternalPersonRead.model_validate(ns)
    assert read.full_name == "Иванов"
    assert read.organization_company_id == 7


def test_read_missing_required_field_fails() -> None:
    with pytest.raises(ValidationError):
        ExternalPersonRead.model_validate(SimpleNamespace(id=uuid4()))
    with pytest.raises(ValidationError):
        StandardRead.model_validate(SimpleNamespace(id=uuid4()))


def test_read_models_validate_real_orm(client, db) -> None:
    """Read-схемы валидируют реальные ORM-инстансы (совпадение имён полей)."""
    from app.quality.execution_repository import ExecutionRepo
    from app.quality.execution_schemas import (
        MethodExecutionRead,
        ParticipantRead,
        ResultItemRead,
    )
    from app.quality.laboratory_conclusion_schemas import (
        ConclusionExecutionRead,
        ConclusionRead,
    )

    from .test_inspection_method_assignments import Ctx
    from .test_laboratory_conclusions import _issue

    ctx = Ctx(db, "SCH1")
    svc, conclusion, execution = _issue(
        client, db, ctx, number="SCH-1", joint="J-sch"
    )
    repo = ExecutionRepo(db)

    exec_read = MethodExecutionRead.model_validate(execution)
    assert exec_read.id == execution.id
    assert exec_read.status == "LAB_CONFIRMED"

    conc_read = ConclusionRead.model_validate(conclusion)
    assert conc_read.id == conclusion.id
    assert conc_read.status == "ISSUED"
    assert conc_read.normalized_conclusion_number == "SCH-1"

    item_read = ResultItemRead.model_validate(repo.list_result_items(execution.id)[0])
    assert item_read.method_execution_id == execution.id

    part_read = ParticipantRead.model_validate(repo.list_participants(execution.id)[0])
    assert part_read.participant_role == "LEAD_INSPECTOR"

    link_read = ConclusionExecutionRead.model_validate(
        repo.list_conclusion_executions(conclusion.id)[0]
    )
    assert link_read.laboratory_conclusion_id == conclusion.id
