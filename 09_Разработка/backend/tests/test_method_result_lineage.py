"""Межредакционная трассировка локальных результатов (Task 9C, блок 9C-4A).

Проверяют канон 9C-33: при копировании в новую редакцию строка сохраняет
постоянный root_result_item_id, ссылается на предшественника через
supersedes_result_item_id и увеличивает revision_no; EXCLUDED-строки не копируются;
новые строки получают собственный корень; соответствие определяется только по UUID,
а не по содержимому.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
from app.shared.errors import DomainError

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
        full_name="Контролёр Линейный",
        organization_company_id=ctx.lab.id,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def _add_lead(svc, db, ctx, execution_id) -> None:
    person = _person(db, ctx)
    svc.add_participant(
        execution_id,
        ParticipantInput(
            person_id=person.id, participant_role=mew.PARTICIPANT_LEAD_INSPECTOR
        ),
        actor_worker_id=ctx.otk.id,
    )


def _run_to_confirmed(svc, ctx, ex):
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
            laboratory_evaluation=ex.calculated_evaluation,
        ),
        actor_worker_id=ctx.otk.id,
    )


def _confirmed(client, db, code, joint_no, item_inputs, *, exclude_indexes=()):
    """Подтверждённое выполнение с заданными результатами; часть можно исключить."""
    ctx, ins, aid = _setup(client, db, code, joint_no)
    svc = MethodExecutionService(db)
    rsvc = MethodExecutionResultService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    _add_lead(svc, db, ctx, ex.id)
    item_ids = []
    for idx, data in enumerate(item_inputs):
        item = rsvc.add_result_item(ex.id, data, actor_worker_id=ctx.otk.id)
        rsvc.complete_result_item(item.id, actor_worker_id=ctx.otk.id)
        if idx in exclude_indexes:
            rsvc.exclude_result_item(
                item.id, "исключено до подтверждения", actor_worker_id=ctx.otk.id
            )
        item_ids.append(item.id)
    ex = _run_to_confirmed(svc, ctx, ex)
    return ctx, aid, ex, item_ids


def _whole_joint(evaluation=mew.EVAL_CONFORMING) -> ResultItemInput:
    return ResultItemInput(
        controlled_object_type=mew.OBJ_WHOLE_JOINT, evaluation=evaluation
    )


def _revision(db, old, ctx, *, reason="исправление"):
    return MethodExecutionRevisionService(db).create_revision(
        old.id,
        correction_reason=reason,
        expected_version=old.version,
        actor_worker_id=ctx.otk.id,
    )


# ── 1–3. Копия сохраняет корень, supersedes и revision_no ──────────────────────


def test_copy_preserves_root_and_links(client: TestClient, db: Session) -> None:
    ctx, aid, old, item_ids = _confirmed(
        client, db, "LN1", "J-ln1", [_whole_joint()]
    )
    repo = ExecutionRepo(db)
    old_item = repo.list_result_items(old.id)[0]
    assert old_item.root_result_item_id == old_item.id  # rev.1 корень = own id
    assert old_item.supersedes_result_item_id is None
    assert old_item.revision_no == 1

    new = _revision(db, old, ctx)
    new_item = repo.list_result_items(new.id)[0]
    assert new_item.id != old_item.id
    assert new_item.root_result_item_id == old_item.root_result_item_id  # (1)
    assert new_item.supersedes_result_item_id == old_item.id  # (2)
    assert new_item.revision_no == old_item.revision_no + 1  # (3)


# ── 4. Третья редакция: тот же корень, supersedes на строку второй редакции ─────


def test_third_revision_chain(client: TestClient, db: Session) -> None:
    ctx, aid, r1, _ = _confirmed(client, db, "LN2", "J-ln2", [_whole_joint()])
    repo = ExecutionRepo(db)
    item1 = repo.list_result_items(r1.id)[0]
    root = item1.root_result_item_id

    svc = MethodExecutionService(db)
    r2 = _revision(db, r1, ctx, reason="ревизия 2")
    item2 = repo.list_result_items(r2.id)[0]
    r2 = _run_to_confirmed(svc, ctx, r2)  # атомарное замещение r1 → SUPERSEDED

    r3 = _revision(db, r2, ctx, reason="ревизия 3")
    item3 = repo.list_result_items(r3.id)[0]

    assert item2.root_result_item_id == root
    assert item2.supersedes_result_item_id == item1.id
    assert item2.revision_no == 2
    assert item3.root_result_item_id == root  # тот же корень
    assert item3.supersedes_result_item_id == item2.id  # supersedes на rev.2
    assert item3.revision_no == 3


# ── 5. Новый результат в редакции получает собственный корень ──────────────────


def test_new_item_in_revision_gets_own_root(
    client: TestClient, db: Session
) -> None:
    ctx, aid, old, _ = _confirmed(client, db, "LN3", "J-ln3", [_whole_joint()])
    new = _revision(db, old, ctx)
    rsvc = MethodExecutionResultService(db)
    added = rsvc.add_result_item(
        new.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_LINEAR_SEGMENT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert added.root_result_item_id == added.id
    assert added.revision_no == 1
    assert added.supersedes_result_item_id is None


# ── 6. EXCLUDED-строка предыдущей редакции не копируется ───────────────────────


def test_excluded_item_not_copied(client: TestClient, db: Session) -> None:
    # Две строки, вторая исключена до подтверждения → в редакцию копируется только
    # действующая (COMPLETE) строка.
    ctx, aid, old, item_ids = _confirmed(
        client,
        db,
        "LN4",
        "J-ln4",
        [
            _whole_joint(),
            ResultItemInput(
                controlled_object_type=mew.OBJ_LINEAR_SEGMENT,
                evaluation=mew.EVAL_CONFORMING,
            ),
        ],
        exclude_indexes=(1,),
    )
    repo = ExecutionRepo(db)
    new = _revision(db, old, ctx)
    new_items = repo.list_result_items(new.id)
    assert len(new_items) == 1  # исключённая не перенесена
    assert new_items[0].root_result_item_id == (
        repo.get_result_item(item_ids[0]).root_result_item_id
    )
    # Исключённая строка предыдущей редакции не участвует как предшественник.
    assert new_items[0].supersedes_result_item_id == item_ids[0]


# ── 7. Исключение копии: старая неизменна, ссылки сохранены, аудит ─────────────


def test_exclude_copied_item_keeps_links(
    client: TestClient, db: Session
) -> None:
    ctx, aid, old, item_ids = _confirmed(
        client, db, "LN5", "J-ln5", [_whole_joint()]
    )
    repo = ExecutionRepo(db)
    new = _revision(db, old, ctx)
    copied = repo.list_result_items(new.id)[0]
    old_snapshot = (
        copied.root_result_item_id,
        copied.supersedes_result_item_id,
        copied.revision_no,
    )

    rsvc = MethodExecutionResultService(db)
    rsvc.exclude_result_item(
        copied.id, "ошибочный участок", actor_worker_id=ctx.otk.id
    )
    copied = repo.get_result_item(copied.id)
    assert copied.record_state == mew.RESULT_EXCLUDED
    assert (
        copied.root_result_item_id,
        copied.supersedes_result_item_id,
        copied.revision_no,
    ) == old_snapshot  # межредакционные ссылки сохранены

    old_item = repo.get_result_item(item_ids[0])
    assert old_item.record_state == mew.RESULT_COMPLETE  # старая не изменена
    events = repo.list_audit_events(mew.AUDIT_ENTITY_RESULT_ITEM, copied.id)
    assert any(
        e.event_type == mew.AUDIT_EVENT_REMOVED_RESULT_ITEM for e in events
    )


# ── 8. Одинаковые по содержимому строки — разные корни ─────────────────────────


def test_identical_content_items_have_distinct_roots(
    client: TestClient, db: Session
) -> None:
    same = dict(
        controlled_object_type=mew.OBJ_LINEAR_SEGMENT,
        coordinate_system=mew.COORD_LINEAR_WELD_LENGTH,
        coordinate_unit=mew.COORD_UNIT_MM,
        coordinate_from=Decimal("0"),
        coordinate_to=Decimal("100"),
        evaluation=mew.EVAL_CONFORMING,
        laboratory_result_text="норма",
    )
    ctx, aid, old, item_ids = _confirmed(
        client,
        db,
        "LN6",
        "J-ln6",
        [ResultItemInput(**same), ResultItemInput(**same)],
    )
    repo = ExecutionRepo(db)
    a, b = repo.get_result_item(item_ids[0]), repo.get_result_item(item_ids[1])
    assert a.root_result_item_id != b.root_result_item_id
    # После копирования корни остаются раздельными.
    new = _revision(db, old, ctx)
    roots = {i.root_result_item_id for i in repo.list_result_items(new.id)}
    assert roots == {a.root_result_item_id, b.root_result_item_id}
    assert len(roots) == 2


# ── 9. Изменение содержимого копии не мешает найти предшественника ─────────────


def test_content_change_keeps_predecessor_link(
    client: TestClient, db: Session
) -> None:
    ctx, aid, old, item_ids = _confirmed(
        client, db, "LN7", "J-ln7", [_whole_joint(mew.EVAL_CONFORMING)]
    )
    repo = ExecutionRepo(db)
    new = _revision(db, old, ctx)
    copied = repo.list_result_items(new.id)[0]
    predecessor = copied.supersedes_result_item_id
    root = copied.root_result_item_id

    # Меняем содержимое копии (координаты/оценка) прямой правкой строки DRAFT-редакции.
    copied.coordinate_system = mew.COORD_LINEAR_WELD_LENGTH
    copied.coordinate_unit = mew.COORD_UNIT_MM
    copied.coordinate_from = Decimal("10")
    copied.coordinate_to = Decimal("50")
    copied.evaluation = mew.EVAL_NONCONFORMING
    db.commit()

    reloaded = repo.get_result_item(copied.id)
    assert reloaded.supersedes_result_item_id == predecessor == item_ids[0]
    assert reloaded.root_result_item_id == root  # идентичность по UUID сохранена


# ── 10. Старая редакция и её результаты полностью неизменны ─────────────────────


def test_old_revision_fully_unchanged(client: TestClient, db: Session) -> None:
    ctx, aid, old, item_ids = _confirmed(
        client, db, "LN8", "J-ln8", [_whole_joint()]
    )
    repo = ExecutionRepo(db)
    before = repo.get_result_item(item_ids[0])
    snapshot = (
        before.id,
        before.root_result_item_id,
        before.revision_no,
        before.supersedes_result_item_id,
        before.record_state,
        before.method_execution_id,
    )

    svc = MethodExecutionService(db)
    new = _revision(db, old, ctx)
    new = _run_to_confirmed(svc, ctx, new)  # даже после замещения

    after = repo.get_result_item(item_ids[0])
    assert (
        after.id,
        after.root_result_item_id,
        after.revision_no,
        after.supersedes_result_item_id,
        after.record_state,
        after.method_execution_id,
    ) == snapshot
    old_exec = repo.get_execution(old.id)
    assert old_exec.status == mew.EXEC_SUPERSEDED  # меняется только статус выполнения
    assert old_exec.is_current is False


# ── 11. Полный lifecycle новой редакции и атомарное переключение ───────────────


def test_revision_lifecycle_and_swap_still_work(
    client: TestClient, db: Session
) -> None:
    ctx, aid, old, _ = _confirmed(client, db, "LN9", "J-ln9", [_whole_joint()])
    svc = MethodExecutionService(db)
    repo = ExecutionRepo(db)
    new = _revision(db, old, ctx)
    new = _run_to_confirmed(svc, ctx, new)
    assert new.status == mew.EXEC_LAB_CONFIRMED
    assert new.is_current is True
    current = repo.get_current_execution_for_root(old.root_execution_id)
    assert current.id == new.id
    # Цепочка результата непрерывна через редакции.
    new_item = repo.list_result_items(new.id)[0]
    old_item = repo.list_result_items(old.id)[0]
    assert new_item.root_result_item_id == old_item.root_result_item_id
    assert new_item.supersedes_result_item_id == old_item.id
