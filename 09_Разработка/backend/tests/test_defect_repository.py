"""Тесты repository технической модели Defect (Task 9D-3B; Spec §24)."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.quality.defect_models import DefectEvent, DefectType
from app.quality.defect_repository import DefectRepository
from app.quality.defect_services import DefectService

from ._defect_support import DefectCtx, make_defect, make_root, valid_active_fields


def _repo(db: Session) -> DefectRepository:
    return DefectRepository(db)


def test_get_root_by_id_and_evaluation_and_number(db: Session):
    ctx = DefectCtx(db, "RP1")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=7)
    repo = _repo(db)
    assert repo.get_root_by_id(root.id).id == root.id
    assert repo.get_root_by_evaluation_id(ev.id).id == root.id
    assert repo.get_root_by_joint_and_defect_no(joint.id, 7).id == root.id
    assert repo.get_root_by_joint_and_defect_no(joint.id, 99) is None


def test_get_current_active_and_open_draft(db: Session):
    ctx = DefectCtx(db, "RP2")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    active = make_defect(ctx, root=root, revision_no=1, status="ACTIVE")
    draft = make_defect(ctx, root=root, revision_no=2, status="DRAFT")
    repo = _repo(db)
    assert repo.get_current_active_revision(root.id).id == active.id
    assert repo.get_open_draft_revision(root.id).id == draft.id


def test_list_revisions_ordered(db: Session):
    ctx = DefectCtx(db, "RP3")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    make_defect(ctx, root=root, revision_no=1, status="SUPERSEDED")
    make_defect(ctx, root=root, revision_no=2, status="ACTIVE")
    repo = _repo(db)
    revs = repo.list_revisions(root.id)
    assert [r.revision_no for r in revs] == [1, 2]
    assert repo.max_revision_no(root.id) == 2


def test_list_roots_by_joint(db: Session):
    ctx = DefectCtx(db, "RP4")
    joint = ctx.new_joint("J-1")
    ev1 = ctx.new_evaluation(joint)
    ev2 = ctx.new_evaluation(joint)
    make_root(ctx, joint=joint, evaluation=ev1, defect_no=1)
    make_root(ctx, joint=joint, evaluation=ev2, defect_no=2)
    repo = _repo(db)
    roots = repo.list_roots_by_joint(joint.id)
    assert [r.defect_no for r in roots] == [1, 2]


def test_append_and_list_events(db: Session):
    ctx = DefectCtx(db, "RP5")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, status="DRAFT")
    repo = _repo(db)
    repo.append_event(
        DefectEvent(
            defect_root_id=root.id, defect_id=d.id,
            event_type="DEFECT_DRAFT_CREATED", actor_worker_id=ctx.creator.id,
            defect_version=1,
        )
    )
    db.commit()
    events = repo.list_events(root.id)
    assert len(events) == 1 and events[0].event_type == "DEFECT_DRAFT_CREATED"
    assert len(repo.list_events_for_defect(d.id)) == 1


def test_next_defect_no_delegates(db: Session):
    ctx = DefectCtx(db, "RP6")
    joint = ctx.new_joint("J-1")
    repo = _repo(db)
    assert repo.next_defect_no(joint.id) == 1
    assert repo.next_defect_no(joint.id) == 2
    db.commit()


def test_lock_root_for_update_returns_row(db: Session):
    ctx = DefectCtx(db, "RP7")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    repo = _repo(db)
    locked = repo.lock_root_for_update(root.id)
    assert locked is not None and locked.id == root.id
    assert repo.lock_root_for_update(uuid4()) is None
    db.commit()


def test_repository_does_not_mutate_reference_data(db: Session):
    ctx = DefectCtx(db, "RP8")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    make_defect(
        ctx, root=root, revision_no=1, status="DRAFT",
        defect_type_id=None,
    )
    repo = _repo(db)
    before = db.query(DefectType).count()
    repo.get_defect_type(uuid4())  # чтение не меняет НСИ
    repo.list_active_defects_by_joint(joint.id)
    db.commit()
    assert db.query(DefectType).count() == before


def test_get_defect_with_refs_single_query(db: Session):
    ctx = DefectCtx(db, "RP9")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_confirmed_evaluation(joint)
    svc = DefectService(db)
    d = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    repo = _repo(db)
    row = repo.get_defect_with_refs(d.id)
    assert row is not None
    defect, defect_type, location_type = row
    assert defect.id == d.id
    assert defect_type.code == "CRACK"
    assert location_type.code == "WELD_METAL"


def test_list_active_by_joint_no_n_plus_one(db: Session):
    """list_active_defects_by_joint выполняет константное число запросов (нет N+1)."""
    ctx = DefectCtx(db, "RPA")
    joint = ctx.new_joint("J-1")
    svc = DefectService(db)
    fields = valid_active_fields(db)
    for _ in range(4):
        ev = ctx.new_confirmed_evaluation(joint)
        svc.create_active(
            joint_id=joint.id, engineering_evaluation_id=ev.id,
            actor_worker_id=ctx.ogs.id, fields=dict(fields),
        )
    repo = _repo(db)

    engine = db.get_bind()
    statements: list[str] = []

    def _count(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = repo.list_active_defects_by_joint(joint.id)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert len(result) == 4
    # Константное число запросов (join root+revision), НЕ растёт со строками:
    # истинный N+1 при 4 строках дал бы ≥5. Здесь ≤2 (main select + возможный autoflush).
    assert len(statements) <= 2, statements
