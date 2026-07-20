"""Тесты конкурентно безопасной нумерации defect_no (Task 9D-3A; Spec §7.4/§14)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality.defect_numbering import next_defect_sequence
from app.shared.db import SessionLocal

from ._defect_support import DefectCtx, make_root


def test_first_number_is_one(db: Session):
    ctx = DefectCtx(db, "NUM1")
    joint = ctx.new_joint("J-1")
    assert next_defect_sequence(db, joint.id) == 1
    db.commit()


def test_sequential_numbers(db: Session):
    ctx = DefectCtx(db, "NUM2")
    joint = ctx.new_joint("J-1")
    assert next_defect_sequence(db, joint.id) == 1
    assert next_defect_sequence(db, joint.id) == 2
    assert next_defect_sequence(db, joint.id) == 3
    db.commit()


def test_independent_sequences_per_joint(db: Session):
    ctx = DefectCtx(db, "NUM3")
    j1 = ctx.new_joint("J-1")
    j2 = ctx.new_joint("J-2")
    assert next_defect_sequence(db, j1.id) == 1
    assert next_defect_sequence(db, j1.id) == 2
    # Другой стык — независимая последовательность, снова с 1.
    assert next_defect_sequence(db, j2.id) == 1
    db.commit()


def test_number_not_reused_after_cancel(db: Session):
    ctx = DefectCtx(db, "NUM4")
    joint = ctx.new_joint("J-1")
    ev1 = ctx.new_evaluation(joint)
    ev2 = ctx.new_evaluation(joint)

    n1 = next_defect_sequence(db, joint.id)
    make_root(ctx, joint=joint, evaluation=ev1, defect_no=n1)  # cancelled-цепочка
    db.commit()

    # Следующая карточка получает СЛЕДУЮЩИЙ номер, отменённый не переиспользуется.
    n2 = next_defect_sequence(db, joint.id)
    assert n2 == n1 + 1
    make_root(ctx, joint=joint, evaluation=ev2, defect_no=n2)
    db.commit()


def test_rollback_does_not_leak_number(db: Session):
    """Rollback выдачи не оставляет сирот и не приводит к дубликату."""
    ctx = DefectCtx(db, "NUM5")
    joint = ctx.new_joint("J-1")
    db.commit()

    # Отдельная транзакция: выдать номер и откатить.
    other = SessionLocal()
    try:
        assert next_defect_sequence(other, joint.id) == 1
        other.rollback()
    finally:
        other.close()

    # После отката строки счётчика нет — следующая выдача снова 1 (номер не потерян).
    assert next_defect_sequence(db, joint.id) == 1
    db.commit()


def test_concurrent_create_unique_numbers(db: Session):
    """Конкурентная выдача из независимых сессий не даёт одинаковых номеров."""
    ctx = DefectCtx(db, "NUM6")
    joint = ctx.new_joint("J-1")
    db.commit()
    joint_id = joint.id

    n_threads = 8

    def issue() -> int:
        s = SessionLocal()
        try:
            value = next_defect_sequence(s, joint_id)
            s.commit()
            return value
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        results = list(pool.map(lambda _: issue(), range(n_threads)))

    assert len(set(results)) == n_threads, results
    assert sorted(results) == list(range(1, n_threads + 1)), results


def test_unique_joint_defect_no_last_defense(db: Session):
    """UNIQUE(joint_id, defect_no) — последняя защита от дубликата номера."""
    ctx = DefectCtx(db, "NUM7")
    joint = ctx.new_joint("J-1")
    ev1 = ctx.new_evaluation(joint)
    ev2 = ctx.new_evaluation(joint)
    make_root(ctx, joint=joint, evaluation=ev1, defect_no=1)
    with pytest.raises(IntegrityError):
        make_root(ctx, joint=joint, evaluation=ev2, defect_no=1)
    db.rollback()
