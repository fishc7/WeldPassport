"""Сервисные тесты технической модели Defect (Task 9D-3B; ADR-022, Spec §8/§25)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.quality import defect_workflow as dw
from app.quality.defect_models import DefectLocationType, DefectRoot, DefectType
from app.quality.defect_repository import DefectRepository
from app.quality.defect_services import DefectService
from app.shared.errors import DomainError, RoleDeniedError

from ._defect_support import (
    DefectCtx,
    make_defect,
    seeded_location_id,
    seeded_type_id,
    valid_active_fields,
)


def _ctx(db: Session, code: str):
    ctx = DefectCtx(db, code)
    joint = ctx.new_joint("J-1")
    ev = ctx.new_confirmed_evaluation(joint)
    return ctx, joint, ev


def _inactive_type(db: Session) -> DefectType:
    existing = (
        db.query(DefectType).filter(DefectType.code == "ZZ_TEST_INACTIVE").first()
    )
    if existing is not None:
        return existing
    t = DefectType(code="ZZ_TEST_INACTIVE", name="Test inactive", is_active=False)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── Create DRAFT ───────────────────────────────────────────────────────────────


def test_create_draft_success(db: Session):
    ctx, joint, ev = _ctx(db, "SVD1")
    svc = DefectService(db)
    d = svc.create_draft(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id,
    )
    assert d.status == dw.DEFECT_DRAFT
    assert d.revision_no == 1
    root = db.get(DefectRoot, d.defect_root_id)
    assert root.defect_no == 1
    assert root.current_defect_id == d.id
    events = svc.history(d.id, actor_worker_id=ctx.ogs.id)
    assert [e.event_type for e in events] == ["DEFECT_DRAFT_CREATED"]


def test_create_draft_repeated_evaluation_rejected(db: Session):
    ctx, joint, ev = _ctx(db, "SVD2")
    svc = DefectService(db)
    svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError) as exc:
        svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_ALREADY_EXISTS_FOR_EVALUATION


def test_create_draft_joint_mismatch(db: Session):
    ctx, joint, ev = _ctx(db, "SVD3")
    other_joint = ctx.new_joint("J-2")
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_draft(joint_id=other_joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_JOINT_MISMATCH


def test_create_draft_evaluation_not_effective(db: Session):
    ctx = DefectCtx(db, "SVD4")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_evaluation(joint)  # без effective revision
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_EVALUATION_NOT_EFFECTIVE


def test_create_draft_classification_not_confirmed(db: Session):
    ctx = DefectCtx(db, "SVD5")
    joint = ctx.new_joint("J-1")
    ev = ctx.new_confirmed_evaluation(joint, classification="NOT_CONFIRMED")
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_EVALUATION_NOT_CONFIRMED


def test_create_draft_permission_denied(db: Session):
    ctx, joint, ev = _ctx(db, "SVD6")
    svc = DefectService(db)
    with pytest.raises(RoleDeniedError) as exc:
        svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.norole.id)
    assert exc.value.code == dw.DEFECT_PERMISSION_DENIED


def test_create_draft_rollback_leaves_nothing(db: Session):
    ctx, joint, ev = _ctx(db, "SVD7")
    svc = DefectService(db)
    # Первый успешно, второй падает по UNIQUE eval — не оставляет второй root.
    svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError):
        svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    roots = db.query(DefectRoot).filter(DefectRoot.engineering_evaluation_id == ev.id).all()
    assert len(roots) == 1


# ── Create ACTIVE ──────────────────────────────────────────────────────────────


def test_create_active_success(db: Session):
    ctx, joint, ev = _ctx(db, "SVA1")
    svc = DefectService(db)
    d = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    assert d.status == dw.DEFECT_ACTIVE
    assert d.activated_by_worker_id == ctx.ogs.id and d.activated_at is not None
    root = db.get(DefectRoot, d.defect_root_id)
    assert root.active_defect_id == d.id
    events = svc.history(d.id, actor_worker_id=ctx.ogs.id)
    assert [e.event_type for e in events] == ["DEFECT_ACTIVATED"]


def test_create_active_type_required(db: Session):
    ctx, joint, ev = _ctx(db, "SVA2")
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_active(
            joint_id=joint.id, engineering_evaluation_id=ev.id,
            actor_worker_id=ctx.ogs.id,
            fields={"location_type_id": seeded_location_id(db), "indication_location": "SURFACE"},
        )
    assert exc.value.code == dw.DEFECT_TYPE_REQUIRED


def test_create_active_inactive_type_rejected(db: Session):
    ctx, joint, ev = _ctx(db, "SVA3")
    inactive = _inactive_type(db)
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_active(
            joint_id=joint.id, engineering_evaluation_id=ev.id,
            actor_worker_id=ctx.ogs.id,
            fields=valid_active_fields(db, defect_type_id=inactive.id),
        )
    assert exc.value.code == dw.DEFECT_TYPE_INACTIVE


def test_create_active_other_requires_description(db: Session):
    ctx, joint, ev = _ctx(db, "SVA4")
    svc = DefectService(db)
    other_id = seeded_type_id(db, "OTHER")
    with pytest.raises(DomainError) as exc:
        svc.create_active(
            joint_id=joint.id, engineering_evaluation_id=ev.id,
            actor_worker_id=ctx.ogs.id,
            fields=valid_active_fields(db, defect_type_id=other_id),
        )
    assert exc.value.code == dw.DEFECT_DESCRIPTION_REQUIRED
    # С описанием — успешно.
    d = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id,
        fields=valid_active_fields(db, defect_type_id=other_id, technical_description="скол кромки"),
    )
    assert d.status == dw.DEFECT_ACTIVE


def test_create_active_axial_requires_context(db: Session):
    ctx, joint, ev = _ctx(db, "SVA5")
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_active(
            joint_id=joint.id, engineering_evaluation_id=ev.id,
            actor_worker_id=ctx.ogs.id,
            fields=valid_active_fields(db, axial_position_mm=Decimal("120")),
        )
    assert exc.value.code == dw.DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED


def test_create_active_standard_clause_requires_document(db: Session):
    ctx, joint, ev = _ctx(db, "SVA6")
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_active(
            joint_id=joint.id, engineering_evaluation_id=ev.id,
            actor_worker_id=ctx.ogs.id,
            fields=valid_active_fields(db, standard_clause="п. 5"),
        )
    assert exc.value.code == dw.DEFECT_STANDARD_DOCUMENT_REQUIRED


def test_create_active_circumferential_normalized(db: Session):
    ctx, joint, ev = _ctx(db, "SVA7")
    svc = DefectService(db)
    d = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id,
        fields=valid_active_fields(db, circumferential_position_deg=Decimal("370")),
    )
    assert d.circumferential_position_deg == Decimal("10")


# ── Update DRAFT ───────────────────────────────────────────────────────────────


def test_update_draft_success(db: Session):
    ctx, joint, ev = _ctx(db, "SVU1")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    updated = svc.update_draft(
        d.id, expected_version=d.version, actor_worker_id=ctx.ogs.id,
        fields={"technical_description": "поверхностная трещина"},
    )
    assert updated.version == 2
    assert updated.technical_description == "поверхностная трещина"


def test_update_draft_version_conflict(db: Session):
    ctx, joint, ev = _ctx(db, "SVU2")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError) as exc:
        svc.update_draft(d.id, expected_version=999, actor_worker_id=ctx.ogs.id, fields={})
    assert exc.value.code == dw.DEFECT_VERSION_CONFLICT


def test_update_active_rejected_immutable(db: Session):
    ctx, joint, ev = _ctx(db, "SVU3")
    svc = DefectService(db)
    d = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    with pytest.raises(DomainError) as exc:
        svc.update_draft(d.id, expected_version=d.version, actor_worker_id=ctx.ogs.id, fields={"technical_note": "x"})
    assert exc.value.code == dw.DEFECT_ACTIVE_IMMUTABLE


# ── Activate ───────────────────────────────────────────────────────────────────


def test_activate_success(db: Session):
    ctx, joint, ev = _ctx(db, "SVAC1")
    svc = DefectService(db)
    d = svc.create_draft(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    activated = svc.activate(d.id, expected_version=d.version, actor_worker_id=ctx.chief.id)
    assert activated.status == dw.DEFECT_ACTIVE
    assert activated.version == 2
    events = [e.event_type for e in svc.history(d.id, actor_worker_id=ctx.ogs.id)]
    assert events == ["DEFECT_DRAFT_CREATED", "DEFECT_ACTIVATED"]


def test_activate_incomplete_rejected(db: Session):
    ctx, joint, ev = _ctx(db, "SVAC2")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError) as exc:
        svc.activate(d.id, expected_version=d.version, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_TYPE_REQUIRED


def test_activate_version_conflict(db: Session):
    ctx, joint, ev = _ctx(db, "SVAC3")
    svc = DefectService(db)
    d = svc.create_draft(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    with pytest.raises(DomainError) as exc:
        svc.activate(d.id, expected_version=999, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_VERSION_CONFLICT


# ── Supersede ──────────────────────────────────────────────────────────────────


def test_supersede_creates_draft_and_supersedes_previous(db: Session):
    """Двухшаговый supersede (supersede-time): previous → SUPERSEDED + новая DRAFT;
    отдельный activate переводит новую ревизию в ACTIVE (Spec §5; §8 п.1–6, 11)."""
    ctx, joint, ev = _ctx(db, "SVS1")
    svc = DefectService(db)
    repo = DefectRepository(db)
    d1 = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id,
        fields=valid_active_fields(db, length_mm=Decimal("10")),
    )
    d2 = svc.supersede(
        d1.id, expected_version=d1.version, actor_worker_id=ctx.chief.id,
        fields={"length_mm": Decimal("12.5")}, reason="уточнение размера",
    )
    # (1) новая ревизия — DRAFT, а не ACTIVE.
    assert d2.status == dw.DEFECT_DRAFT
    assert d2.id != d1.id
    assert d2.defect_root_id == d1.defect_root_id
    assert d2.revision_no == 2
    assert d2.supersedes_defect_id == d1.id
    assert d2.length_mm == Decimal("12.5")
    assert d2.defect_type_id == d1.defect_type_id  # snapshot скопирован
    # (2) новая ревизия не имеет activation actor/time.
    assert d2.activated_by_worker_id is None and d2.activated_at is None
    # (3) previous становится SUPERSEDED.
    db.refresh(d1)
    assert d1.status == dw.DEFECT_SUPERSEDED
    assert d1.superseded_by_worker_id == ctx.chief.id and d1.superseded_at is not None
    # (4) current ACTIVE после supersede отсутствует.
    root = db.get(DefectRoot, d1.defect_root_id)
    assert root.active_defect_id is None
    assert repo.get_current_active_revision(root.id) is None
    # (5) open DRAFT указывает на новую ревизию.
    assert repo.get_open_draft_revision(root.id).id == d2.id
    assert root.current_defect_id == d2.id
    # события supersede: DEFECT_SUPERSEDED + DEFECT_REVISION_CREATED, без ACTIVATED.
    events = svc.history(d2.id, actor_worker_id=ctx.ogs.id)
    types_after_supersede = [e.event_type for e in events]
    assert "DEFECT_SUPERSEDED" in types_after_supersede
    assert "DEFECT_REVISION_CREATED" in types_after_supersede
    assert types_after_supersede.count("DEFECT_ACTIVATED") == 1  # только create_active d1
    # (11) audit transitions: ACTIVE → SUPERSEDED и NULL → DRAFT.
    sup = next(e for e in events if e.event_type == "DEFECT_SUPERSEDED")
    assert sup.from_status == dw.DEFECT_ACTIVE and sup.to_status == dw.DEFECT_SUPERSEDED
    assert sup.defect_id == d1.id and sup.defect_version == d1.version
    rev = next(e for e in events if e.event_type == "DEFECT_REVISION_CREATED")
    assert rev.from_status is None and rev.to_status == dw.DEFECT_DRAFT
    assert rev.defect_id == d2.id and rev.defect_version == 1
    # (6) отдельный activate переводит новую ревизию в ACTIVE (DRAFT → ACTIVE).
    activated = svc.activate(
        d2.id, expected_version=d2.version, actor_worker_id=ctx.ogs.id
    )
    assert activated.status == dw.DEFECT_ACTIVE
    db.refresh(root)
    assert root.active_defect_id == d2.id
    assert repo.get_open_draft_revision(root.id) is None
    last = svc.history(d2.id, actor_worker_id=ctx.ogs.id)[-1]
    assert last.event_type == "DEFECT_ACTIVATED"
    assert last.from_status == dw.DEFECT_DRAFT and last.to_status == dw.DEFECT_ACTIVE


def test_supersede_version_conflict(db: Session):
    ctx, joint, ev = _ctx(db, "SVS2")
    svc = DefectService(db)
    d1 = svc.create_active(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db))
    with pytest.raises(DomainError) as exc:
        svc.supersede(d1.id, expected_version=999, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_VERSION_CONFLICT
    db.refresh(d1)
    assert d1.status == dw.DEFECT_ACTIVE  # конфликт версии не трогает previous


def test_supersede_structural_invalid_keeps_previous_active(db: Session):
    """Структурно недопустимый patch отклоняется ДО изменения previous — previous
    остаётся ACTIVE, новая DRAFT не создаётся, событий нет (Spec §3; §8 п.10)."""
    ctx, joint, ev = _ctx(db, "SVS3")
    svc = DefectService(db)
    repo = DefectRepository(db)
    d1 = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id,
        fields=valid_active_fields(db, length_mm=Decimal("10")),
    )
    with pytest.raises(DomainError) as exc:
        svc.supersede(
            d1.id, expected_version=d1.version, actor_worker_id=ctx.ogs.id,
            fields={"length_mm": Decimal("-1")},  # неположительное измерение → DB CHECK
        )
    assert exc.value.code == dw.DEFECT_MEASUREMENT_NOT_POSITIVE
    db.refresh(d1)
    assert d1.status == dw.DEFECT_ACTIVE  # previous не тронута
    root = db.get(DefectRoot, d1.defect_root_id)
    assert root.active_defect_id == d1.id
    assert repo.get_open_draft_revision(root.id) is None  # DRAFT не создана
    assert svc.list_by_joint(joint.id, actor_worker_id=ctx.ogs.id)[0].id == d1.id


def test_supersede_incomplete_draft_then_activation_rejected(db: Session):
    """Неполный patch создаёт допустимую DRAFT (structural OK), но полная §8-проверка
    выполняется при activate и отклоняет такую DRAFT (Spec §5/§8; §8 п.7–8)."""
    ctx, joint, ev = _ctx(db, "SVS5")
    svc = DefectService(db)
    d1 = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    # axial_position_mm без location_description: структурно (DB CHECK) допустимо, но
    # §7.9-контекст датума требуется только при активации (activate-time проверка).
    d2 = svc.supersede(
        d1.id, expected_version=d1.version, actor_worker_id=ctx.ogs.id,
        fields={"axial_position_mm": Decimal("120")},
    )
    assert d2.status == dw.DEFECT_DRAFT  # DRAFT создана
    assert d2.axial_position_mm == Decimal("120")
    db.refresh(d1)
    assert d1.status == dw.DEFECT_SUPERSEDED  # previous уже замещён
    # Активация неполной DRAFT отклоняется полной §8-проверкой.
    with pytest.raises(DomainError) as exc:
        svc.activate(d2.id, expected_version=d2.version, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED
    db.refresh(d2)
    assert d2.status == dw.DEFECT_DRAFT  # осталась DRAFT после отказа активации


def test_supersede_requires_active(db: Session):
    """supersede из DRAFT (в цепочке нет ACTIVE) → DEFECT_SUPERSEDE_REQUIRES_ACTIVE."""
    ctx, joint, ev = _ctx(db, "SVS4")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError) as exc:
        svc.supersede(d.id, expected_version=d.version, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_SUPERSEDE_REQUIRES_ACTIVE


def test_supersede_rejected_when_open_draft_exists(db: Session):
    """D04: при уже существующей открытой DRAFT в цепочке supersede отклоняется
    (DEFECT_CHAIN_HAS_OPEN_DRAFT), previous остаётся ACTIVE (Spec §5/§7 concurrency)."""
    ctx, joint, ev = _ctx(db, "SVS6")
    svc = DefectService(db)
    d1 = svc.create_active(
        joint_id=joint.id, engineering_evaluation_id=ev.id,
        actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db),
    )
    root = db.get(DefectRoot, d1.defect_root_id)
    # Прямой ORM-вброс второй открытой DRAFT (обход сервиса) для проверки guard D04.
    make_defect(ctx, root=root, revision_no=2, status="DRAFT")
    with pytest.raises(DomainError) as exc:
        svc.supersede(d1.id, expected_version=d1.version, actor_worker_id=ctx.ogs.id)
    assert exc.value.code == dw.DEFECT_CHAIN_HAS_OPEN_DRAFT
    db.refresh(d1)
    assert d1.status == dw.DEFECT_ACTIVE  # previous не тронута


# ── Cancel ─────────────────────────────────────────────────────────────────────


def test_cancel_draft(db: Session):
    ctx, joint, ev = _ctx(db, "SVC1")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    cancelled = svc.cancel(d.id, expected_version=d.version, actor_worker_id=ctx.ogs.id, reason="ошибочная карточка")
    assert cancelled.status == dw.DEFECT_CANCELLED
    # evaluation/root/number сохраняются.
    root = db.get(DefectRoot, d.defect_root_id)
    assert root is not None and root.engineering_evaluation_id == ev.id and root.defect_no == 1


def test_cancel_active_clears_active_pointer(db: Session):
    ctx, joint, ev = _ctx(db, "SVC2")
    svc = DefectService(db)
    d = svc.create_active(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db))
    svc.cancel(d.id, expected_version=d.version, actor_worker_id=ctx.chief.id, reason="дубль")
    root = db.get(DefectRoot, d.defect_root_id)
    assert root.active_defect_id is None


def test_cancel_reason_required(db: Session):
    ctx, joint, ev = _ctx(db, "SVC3")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError) as exc:
        svc.cancel(d.id, expected_version=d.version, actor_worker_id=ctx.ogs.id, reason="   ")
    assert exc.value.code == dw.DEFECT_CANCELLATION_REASON_REQUIRED


def test_cancel_superseded_denied(db: Session):
    ctx, joint, ev = _ctx(db, "SVC4")
    svc = DefectService(db)
    d1 = svc.create_active(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id, fields=valid_active_fields(db))
    svc.supersede(d1.id, expected_version=d1.version, actor_worker_id=ctx.ogs.id)
    db.refresh(d1)
    with pytest.raises(DomainError) as exc:
        svc.cancel(d1.id, expected_version=d1.version, actor_worker_id=ctx.ogs.id, reason="x")
    assert exc.value.code == dw.DEFECT_INVALID_TRANSITION


# ── Read / visibility ──────────────────────────────────────────────────────────


def test_get_invisible_resource_404(db: Session):
    ctx, joint, ev = _ctx(db, "SVR1")
    svc = DefectService(db)
    d = svc.create_draft(joint_id=joint.id, engineering_evaluation_id=ev.id, actor_worker_id=ctx.ogs.id)
    with pytest.raises(DomainError) as exc:
        svc.get(d.id, actor_worker_id=ctx.norole.id)
    assert exc.value.status_code == 404


def test_get_not_found(db: Session):
    DefectCtx(db, "SVR2")
    svc = DefectService(db)
    with pytest.raises(DomainError) as exc:
        svc.get(uuid4(), actor_worker_id=1)
    assert exc.value.code == dw.DEFECT_NOT_FOUND
