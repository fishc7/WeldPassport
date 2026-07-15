"""Интеграционные тесты контролируемых редакций выполнения (Task 9C, блок 9C-4).

Полное копирование выполнения/участников/результатов/стандартов; прежняя
подтверждённая редакция неизменна до подтверждения новой; атомарное замещение при
новом LAB_CONFIRMED (новая → текущая, прежняя → SUPERSEDED); история, аудит и защита
конкурентности. LaboratoryConclusion/API — вне блока.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import method_execution_workflow as mew
from app.quality.execution_models import QualityExternalPerson
from app.quality.execution_repository import ExecutionRepo
from app.quality.method_execution_services import (
    ConfirmInput,
    ExecutionCreateInput,
    MarkPerformedInput,
    MethodExecutionResultService,
    MethodExecutionRevisionService,
    MethodExecutionService,
    ParticipantInput,
    ResultItemInput,
)
from app.shared.db import SessionLocal
from app.shared.errors import DomainError

from datetime import date

from .test_inspection_method_assignments import Ctx

TODAY = date.today()


def _setup(client: TestClient, db: Session, code: str, joint_no: str):
    ctx = Ctx(db, code)
    iid = ctx.inspection(client, joint_no)
    from app.quality.models import Inspection

    ins = db.get(Inspection, UUID(iid))
    assignment = ctx.assign(client, ctx.otk, iid, method="UT")
    return ctx, ins, UUID(assignment["id"])


def _person(db: Session, ctx: Ctx) -> QualityExternalPerson:
    person = QualityExternalPerson(
        full_name="Контролёр Сидоров",
        organization_company_id=ctx.lab.id,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def _confirmed(svc, rsvc, db, ctx, aid, *, standard=True):
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    person = _person(db, ctx)
    svc.add_participant(
        ex.id,
        ParticipantInput(
            person_id=person.id, participant_role=mew.PARTICIPANT_LEAD_INSPECTOR
        ),
        actor_worker_id=ctx.otk.id,
    )
    item = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_WHOLE_JOINT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    rsvc.complete_result_item(item.id, actor_worker_id=ctx.otk.id)
    if standard:
        from app.quality.method_execution_services import StandardInput

        svc.add_standard(
            ex.id,
            StandardInput(standard_code_snapshot="ГОСТ 14782"),
            actor_worker_id=ctx.otk.id,
        )
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(expected_version=ex.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    ex = svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    return svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version,
            laboratory_evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )


# ── Копирование ────────────────────────────────────────────────────────────────


def test_revision_copies_all_children(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "RV1", "J-rv1")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)

    new = rev.create_revision(
        old.id,
        correction_reason="исправление объёма",
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )
    assert new.revision_no == 2
    assert new.status == mew.EXEC_DRAFT
    assert new.is_current is False
    assert new.supersedes_execution_id == old.id
    assert new.root_execution_id == old.root_execution_id
    assert new.correction_reason == "исправление объёма"

    repo = ExecutionRepo(db)
    old_items = repo.list_result_items(old.id)
    new_items = repo.list_result_items(new.id)
    assert len(new_items) == len(old_items) == 1
    assert new_items[0].id != old_items[0].id  # новые UUID
    assert new_items[0].evaluation == old_items[0].evaluation
    assert len(repo.list_participants(new.id)) == 1
    assert len(repo.list_standards(new.id)) == 1
    # Прежняя редакция не изменена.
    old_reloaded = repo.get_execution(old.id)
    assert old_reloaded.status == mew.EXEC_LAB_CONFIRMED
    assert old_reloaded.is_current is True


# ── Прежняя неизменна до подтверждения новой ───────────────────────────────────


def test_old_unchanged_until_new_confirmed(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "RV2", "J-rv2")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    new = rev.create_revision(
        old.id,
        correction_reason="повторная обработка",
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )
    # Новая проходит lifecycle до RESULT_RECORDED, но НЕ подтверждена.
    new = svc.start(new.id, new.version, actor_worker_id=ctx.otk.id)
    new = svc.mark_performed(
        new.id,
        MarkPerformedInput(expected_version=new.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    new = svc.record_result(new.id, new.version, actor_worker_id=ctx.otk.id)

    repo = ExecutionRepo(db)
    old_reloaded = repo.get_execution(old.id)
    assert old_reloaded.status == mew.EXEC_LAB_CONFIRMED
    assert old_reloaded.is_current is True
    assert repo.get_current_execution_for_root(old.root_execution_id).id == old.id


# ── Атомарное замещение при подтверждении новой ────────────────────────────────


def test_new_confirm_supersedes_old_atomically(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "RV3", "J-rv3")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    new = rev.create_revision(
        old.id,
        correction_reason="уточнение",
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )
    new = svc.start(new.id, new.version, actor_worker_id=ctx.otk.id)
    new = svc.mark_performed(
        new.id,
        MarkPerformedInput(expected_version=new.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    new = svc.record_result(new.id, new.version, actor_worker_id=ctx.otk.id)
    new = svc.confirm(
        new.id,
        ConfirmInput(
            expected_version=new.version,
            laboratory_evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert new.status == mew.EXEC_LAB_CONFIRMED
    assert new.is_current is True

    repo = ExecutionRepo(db)
    old_reloaded = repo.get_execution(old.id)
    assert old_reloaded.status == mew.EXEC_SUPERSEDED
    assert old_reloaded.is_current is False
    # Ровно одна текущая редакция — новая.
    current = repo.get_current_execution_for_root(old.root_execution_id)
    assert current.id == new.id
    assert len(repo.list_executions_for_root(old.root_execution_id)) == 2


# ── История редакций ───────────────────────────────────────────────────────────


def test_revision_history_ordered(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "RV4", "J-rv4")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    rev.create_revision(
        old.id,
        correction_reason="ещё правка",
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )
    history = rev.list_revisions(old.id, actor_worker_id=ctx.otk.id)
    assert [h.revision_no for h in history] == [1, 2]


# ── Ошибки создания редакции ───────────────────────────────────────────────────


def test_cannot_revise_unconfirmed(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "RV5", "J-rv5")
    svc = MethodExecutionService(db)
    rev = MethodExecutionRevisionService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    with pytest.raises(DomainError) as exc:
        rev.create_revision(
            ex.id,
            correction_reason="рано",
            expected_version=ex.version,
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_NOT_CONFIRMED_FOR_REVISION


def test_revision_requires_reason(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "RV6", "J-rv6")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    with pytest.raises(DomainError) as exc:
        rev.create_revision(
            old.id,
            correction_reason="   ",
            expected_version=old.version,
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_CORRECTION_REASON_REQUIRED


def test_second_open_revision_blocked(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "RV7", "J-rv7")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    rev.create_revision(
        old.id,
        correction_reason="первая правка",
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )
    with pytest.raises(DomainError) as exc:
        rev.create_revision(
            old.id,
            correction_reason="вторая правка",
            expected_version=old.version,
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_REVISION_IN_PROGRESS


# ── Аудит и исключение результата в редакции ───────────────────────────────────


def test_revision_audit_and_removed_result_item(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "RV8", "J-rv8")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    rev = MethodExecutionRevisionService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    new = rev.create_revision(
        old.id,
        correction_reason="исключить строку",
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )
    repo = ExecutionRepo(db)
    created = repo.list_audit_events(mew.AUDIT_ENTITY_METHOD_EXECUTION, new.id)
    assert any(
        e.event_type == mew.AUDIT_EVENT_REVISION_CREATED for e in created
    )
    # §18.9: удаление результата в редакции — явное audit-событие с причиной.
    copied_item = repo.list_result_items(new.id)[0]
    rsvc.exclude_result_item(
        copied_item.id, "ошибочный участок", actor_worker_id=ctx.otk.id
    )
    item_events = repo.list_audit_events(
        mew.AUDIT_ENTITY_RESULT_ITEM, copied_item.id
    )
    assert any(
        e.event_type == mew.AUDIT_EVENT_REMOVED_RESULT_ITEM for e in item_events
    )


# ── Защита конкурентности ──────────────────────────────────────────────────────


def test_concurrent_revision_creation_serialized(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "RV9", "J-rv9")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    old = _confirmed(svc, rsvc, db, ctx, aid)
    exec_id, version, otk_id = old.id, old.version, ctx.otk.id

    def attempt(_: int) -> str:
        session = SessionLocal()
        try:
            rev = MethodExecutionRevisionService(session)
            try:
                rev.create_revision(
                    exec_id,
                    correction_reason="гонка",
                    expected_version=version,
                    actor_worker_id=otk_id,
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001
                return getattr(exc, "detail", {}).get("code", "ERR") if isinstance(
                    getattr(exc, "detail", None), dict
                ) else "ERR"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("ok") == 1
    # Ровно одна открытая редакция создана.
    repo = ExecutionRepo(db)
    revisions = repo.list_executions_for_root(old.root_execution_id)
    assert len(revisions) == 2  # исходная + одна редакция
