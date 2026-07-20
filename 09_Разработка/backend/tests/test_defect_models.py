"""Тесты ORM-моделей технической модели Defect (Task 9D-3A; ADR-022, Spec §3).

Проверяют физические ограничения БД (CHECK/UNIQUE/partial unique/FK), типы ключей и
actor-полей, а также отсутствие запрещённых scope-полей/сущностей (scope-exclusion §22).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Integer
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality.defect_models import (
    Defect,
    DefectEvent,
    DefectLocationType,
    DefectRoot,
    DefectSequence,
    DefectType,
)
from app.shared.db import Base

from ._defect_support import DefectCtx, make_defect, make_root

ALL_MODELS = (
    DefectRoot,
    Defect,
    DefectType,
    DefectLocationType,
    DefectSequence,
    DefectEvent,
)


# ── Metadata / типы ────────────────────────────────────────────────────────────


def test_all_six_tables_registered_in_metadata():
    names = {
        "quality.defect_roots",
        "quality.defects",
        "quality.defect_types",
        "quality.defect_location_types",
        "quality.defect_sequences",
        "quality.defect_events",
    }
    present = {
        f"{t.schema}.{t.name}" for t in Base.metadata.tables.values()
    }
    assert names <= present


def test_primary_key_and_actor_types():
    # UUID PK у сущностных таблиц.
    for model in (DefectRoot, Defect, DefectType, DefectLocationType, DefectEvent):
        pk = list(model.__table__.primary_key.columns)
        assert len(pk) == 1
        assert isinstance(pk[0].type, PGUUID), model.__name__
    # DefectSequence PK — joint_id (UUID).
    seq_pk = list(DefectSequence.__table__.primary_key.columns)
    assert isinstance(seq_pk[0].type, PGUUID)
    # actor-поля — Integer (hr.workers.id), без FK.
    for col_name in ("created_by_worker_id", "updated_by_worker_id"):
        assert isinstance(DefectRoot.__table__.c[col_name].type, Integer)
    for col_name in (
        "created_by_worker_id",
        "activated_by_worker_id",
        "superseded_by_worker_id",
        "cancelled_by_worker_id",
    ):
        assert isinstance(Defect.__table__.c[col_name].type, Integer)
    assert isinstance(DefectEvent.__table__.c["actor_worker_id"].type, Integer)
    assert not DefectRoot.__table__.c["created_by_worker_id"].foreign_keys


# ── Уникальность корня и нумерации ─────────────────────────────────────────────


def test_unique_engineering_evaluation_id(db: Session):
    ctx = DefectCtx(db, "MDL1")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    # Вторая цепочка на той же оценке запрещена (кардинальность 0..1).
    with pytest.raises(IntegrityError):
        make_root(ctx, joint=joint, evaluation=ev, defect_no=2)
    db.rollback()


def test_unique_root_revision_no(db: Session):
    ctx = DefectCtx(db, "MDL2")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    make_defect(ctx, root=root, revision_no=1, status="CANCELLED")
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, status="DRAFT")
    db.rollback()


# ── Частичные UNIQUE: одна ACTIVE / одна открытая DRAFT ────────────────────────


def test_one_active_per_root(db: Session):
    ctx = DefectCtx(db, "MDL3")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    make_defect(ctx, root=root, revision_no=1, status="ACTIVE")
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=2, status="ACTIVE")
    db.rollback()


def test_one_draft_per_root(db: Session):
    ctx = DefectCtx(db, "MDL4")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    make_defect(ctx, root=root, revision_no=1, status="DRAFT")
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=2, status="DRAFT")
    db.rollback()


def test_active_plus_draft_allowed(db: Session):
    """ACTIVE + открытая DRAFT в одной цепочке допустимы (supersede в работе)."""
    ctx = DefectCtx(db, "MDL5")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    active = make_defect(ctx, root=root, revision_no=1, status="ACTIVE")
    draft = make_defect(
        ctx, root=root, revision_no=2, status="DRAFT",
        supersedes_defect_id=active.id,
    )
    assert draft.supersedes_defect_id == active.id  # FK self работает


# ── CHECK: статус и расположение индикации ─────────────────────────────────────


def test_status_check_rejects_unknown(db: Session):
    ctx = DefectCtx(db, "MDL6")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, status="REPAIRED")
    db.rollback()


@pytest.mark.parametrize("value", ["SURFACE", "INTERNAL", "THROUGH_THICKNESS", "UNKNOWN"])
def test_indication_location_valid(db: Session, value: str):
    ctx = DefectCtx(db, f"MDL7{value[:3]}")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, indication_location=value)
    assert d.indication_location == value


def test_indication_location_invalid(db: Session):
    ctx = DefectCtx(db, "MDL8")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, indication_location="DEEP")
    db.rollback()


# ── CHECK: измерения / положение / bounded / норматив ──────────────────────────


@pytest.mark.parametrize("field", ["length_mm", "width_mm", "height_mm", "depth_mm", "affected_area_mm2"])
def test_measurement_zero_rejected(db: Session, field: str):
    ctx = DefectCtx(db, f"MDL9{field[:3]}")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, **{field: Decimal("0")})
    db.rollback()


def test_measurement_positive_ok_and_null_ok(db: Session):
    ctx = DefectCtx(db, "MDLA")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(
        ctx, root=root, revision_no=1,
        length_mm=Decimal("12.5"), height_mm=Decimal("3"), quantity=2,
    )
    assert d.length_mm == Decimal("12.5")
    assert d.depth_mm is None  # неприменимое = NULL, не 0


def test_quantity_zero_rejected(db: Session):
    ctx = DefectCtx(db, "MDLB")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, quantity=0)
    db.rollback()


def test_axial_position_negative_rejected(db: Session):
    ctx = DefectCtx(db, "MDLC")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, axial_position_mm=Decimal("-1"))
    db.rollback()


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("359.9")])
def test_circumferential_in_range_ok(db: Session, value: Decimal):
    ctx = DefectCtx(db, f"MDLD{int(value)}")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, circumferential_position_deg=value)
    assert d.circumferential_position_deg == value


@pytest.mark.parametrize("value", [Decimal("360"), Decimal("-1"), Decimal("400")])
def test_circumferential_out_of_range_rejected(db: Session, value: Decimal):
    ctx = DefectCtx(db, f"MDLE{abs(int(value))}")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, circumferential_position_deg=value)
    db.rollback()


def test_bounded_string_empty_rejected(db: Session):
    ctx = DefectCtx(db, "MDLF")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, orientation="   ")
    db.rollback()


def test_bounded_string_value_ok(db: Session):
    ctx = DefectCtx(db, "MDLG")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(
        ctx, root=root, revision_no=1,
        orientation="LONGITUDINAL", surface="OUTER", joint_side="SIDE_1",
    )
    assert d.orientation == "LONGITUDINAL"


def test_standard_clause_requires_document(db: Session):
    ctx = DefectCtx(db, "MDLH")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(ctx, root=root, revision_no=1, standard_clause="Табл. 5")
    db.rollback()


def test_standard_reference_split_ok(db: Session):
    ctx = DefectCtx(db, "MDLI")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(
        ctx, root=root, revision_no=1,
        standard_document="ГОСТ 32569", standard_revision="2013",
        standard_clause="п. 10.2.4",
    )
    assert d.standard_document == "ГОСТ 32569"


# ── CHECK: согласованность конечных статусов ───────────────────────────────────


def test_cancelled_requires_reason(db: Session):
    ctx = DefectCtx(db, "MDLJ")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(
            ctx, root=root, revision_no=1, status="CANCELLED",
            cancellation_reason=None,
        )
    db.rollback()


def test_superseded_requires_actor_time(db: Session):
    ctx = DefectCtx(db, "MDLK")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    with pytest.raises(IntegrityError):
        make_defect(
            ctx, root=root, revision_no=1, status="SUPERSEDED",
            superseded_at=None, superseded_by_worker_id=None,
        )
    db.rollback()


# ── SUPERSEDED lineage (ADR-022 §7; review §3) ─────────────────────────────────


def test_superseded_may_have_null_supersedes(db: Session):
    """Первая ревизия после supersede может быть SUPERSEDED с NULL supersedes."""
    ctx = DefectCtx(db, "MDLL")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, status="SUPERSEDED")
    assert d.supersedes_defect_id is None
    assert d.status == "SUPERSEDED"


def test_new_revision_references_previous(db: Session):
    """Канон: rev1 SUPERSEDED (NULL supersedes) → rev2 ACTIVE ссылается на rev1."""
    ctx = DefectCtx(db, "MDLM")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    r1 = make_defect(ctx, root=root, revision_no=1, status="SUPERSEDED")
    r2 = make_defect(
        ctx, root=root, revision_no=2, status="ACTIVE",
        supersedes_defect_id=r1.id,
    )
    assert r2.supersedes_defect_id == r1.id


def test_self_supersede_rejected(db: Session):
    """Ревизия не может замещать саму себя (ck_defects_no_self_supersede)."""
    import uuid

    ctx = DefectCtx(db, "MDLN")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    own_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        make_defect(
            ctx, root=root, revision_no=1, id=own_id, supersedes_defect_id=own_id,
        )
    db.rollback()


# ── DefectEvent (append-only; FK/NOT NULL/CHECK) ───────────────────────────────


def test_defect_event_insert_ok(db: Session):
    ctx = DefectCtx(db, "MDLO")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, status="DRAFT")
    event = DefectEvent(
        defect_root_id=root.id,
        defect_id=d.id,
        event_type="DEFECT_DRAFT_CREATED",
        actor_worker_id=ctx.creator.id,
        defect_version=1,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    assert event.id is not None


def test_defect_event_root_id_required(db: Session):
    ctx = DefectCtx(db, "MDLP")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, status="DRAFT")
    event = DefectEvent(
        defect_root_id=None,
        defect_id=d.id,
        event_type="DEFECT_DRAFT_CREATED",
        actor_worker_id=ctx.creator.id,
    )
    db.add(event)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_defect_event_type_check(db: Session):
    ctx = DefectCtx(db, "MDLQ")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)
    root = make_root(ctx, joint=joint, evaluation=ev, defect_no=1)
    d = make_defect(ctx, root=root, revision_no=1, status="DRAFT")
    event = DefectEvent(
        defect_root_id=root.id,
        defect_id=d.id,
        event_type="DEFECT_CLOSED",  # запрещённый тип
        actor_worker_id=ctx.creator.id,
    )
    db.add(event)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── Scope-exclusion: запрещённые поля/сущности отсутствуют (§22) ───────────────

_FORBIDDEN_COLUMNS = {
    "repair_required",
    "repair_method",
    "repair_status",
    "is_repaired",
    "is_closed",
    "closed_at",
    "resolved_at",
    "eliminated_at",
    "reweld_operation_id",
    "standard_reference",
    "source_result_item_id",
    "finding_disposition_id",
    "origin_disposition_id",
}


def test_no_forbidden_columns_in_defect_models():
    for model in ALL_MODELS:
        cols = set(model.__table__.c.keys())
        assert not (cols & _FORBIDDEN_COLUMNS), (model.__name__, cols & _FORBIDDEN_COLUMNS)


def test_no_forbidden_tables_in_metadata():
    forbidden_tables = {
        "defect_disposition_links",
        "defect_confirmed_evaluations",
        "defect_acceptance_assessments",
        "finding_dispositions",
    }
    present = {t.name for t in Base.metadata.tables.values()}
    assert not (present & forbidden_tables), present & forbidden_tables
