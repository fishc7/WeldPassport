"""Тесты физических ограничений схемы Task 9C (блок 9C-2).

Проверяют ограничения БД (CHECK, partial unique, FK ON DELETE RESTRICT) новых
таблиц выполнения метода и заключения ПРЯМОЙ вставкой через ORM — сервисов,
schemas и API Task 9C ещё нет. Родительские сущности (проект, стык, заявка,
назначение, лаборатория) строятся через контекст Ctx теста 9B.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality.models import (
    Inspection,
    LaboratoryConclusion,
    MethodExecution,
    MethodExecutionParticipant,
    MethodExecutionResultItem,
    QualityExternalPerson,
)

from .test_inspection_method_assignments import Ctx

API = "/api/v1"


def _assignment(client: TestClient, db: Session, ctx: Ctx, joint_no: str):
    """Создаёт заявку и активное назначение метода; возвращает (Inspection, id)."""
    iid = ctx.inspection(client, joint_no)
    ins = db.get(Inspection, UUID(iid))
    assignment = ctx.assign(client, ctx.otk, iid, method="UT")
    return ins, assignment["id"]


def _execution(
    db: Session, ctx: Ctx, ins: Inspection, assignment_id: str, **over
) -> MethodExecution:
    eid = over.pop("id", uuid4())
    fields: dict = dict(
        id=eid,
        inspection_method_assignment_id=UUID(assignment_id),
        joint_id=ins.joint_id,
        project_id=ins.project_id,
        laboratory_company_id=ctx.lab.id,
        root_execution_id=over.pop("root_execution_id", eid),
        revision_no=1,
        is_current=True,
        status="DRAFT",
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
        version=1,
    )
    fields.update(over)
    return MethodExecution(**fields)


def _person(db: Session, ctx: Ctx) -> QualityExternalPerson:
    person = QualityExternalPerson(
        full_name="Контролёр Иванов",
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def _result_item(
    db: Session, ctx: Ctx, execution_id, **over
) -> MethodExecutionResultItem:
    rid = over.pop("id", uuid4())
    fields: dict = dict(
        id=rid,
        method_execution_id=execution_id,
        root_result_item_id=over.pop("root_result_item_id", rid),
        revision_no=1,
        record_state="DRAFT",
        controlled_object_type="WHOLE_JOINT",
        evaluation="NOT_EVALUATED",
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    fields.update(over)
    return MethodExecutionResultItem(**fields)


# ── Ревизии выполнения: одна текущая на root ───────────────────────────────────


def test_only_one_current_revision_per_root(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "S1CUR")
    ins, aid = _assignment(client, db, ctx, "J-cur")
    first = _execution(db, ctx, ins, aid)
    db.add(first)
    db.commit()

    second = _execution(
        db, ctx, ins, aid, root_execution_id=first.root_execution_id, revision_no=2
    )
    db.add(second)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── Не более одного LEAD_INSPECTOR на выполнение ───────────────────────────────


def test_single_lead_inspector_per_execution(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1LEAD")
    ins, aid = _assignment(client, db, ctx, "J-lead")
    execution = _execution(db, ctx, ins, aid)
    db.add(execution)
    db.commit()
    person = _person(db, ctx)

    def _lead() -> MethodExecutionParticipant:
        return MethodExecutionParticipant(
            method_execution_id=execution.id,
            person_id=person.id,
            participant_role="LEAD_INSPECTOR",
            created_by_worker_id=ctx.otk.id,
            updated_by_worker_id=ctx.otk.id,
        )

    db.add(_lead())
    db.commit()
    db.add(_lead())
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── wraps_zero только для замкнутых координатных систем ─────────────────────────


def test_wraps_zero_rejected_for_open_system(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1WZ")
    ins, aid = _assignment(client, db, ctx, "J-wz")
    execution = _execution(db, ctx, ins, aid)
    db.add(execution)
    db.commit()

    bad = _result_item(
        db,
        ctx,
        execution.id,
        controlled_object_type="LINEAR_SEGMENT",
        coordinate_system="LINEAR_WELD_LENGTH",
        wraps_zero=True,
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_wraps_zero_allowed_for_measuring_belt(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1WZOK")
    ins, aid = _assignment(client, db, ctx, "J-wzok")
    execution = _execution(db, ctx, ins, aid)
    db.add(execution)
    db.commit()

    ok = _result_item(
        db,
        ctx,
        execution.id,
        controlled_object_type="MEASURING_BELT_SEGMENT",
        coordinate_system="MEASURING_BELT",
        wraps_zero=True,
    )
    db.add(ok)
    db.commit()
    assert db.get(MethodExecutionResultItem, ok.id) is not None


# ── EXCLUDED требует причины ────────────────────────────────────────────────────


def test_excluded_result_requires_reason(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1EXC")
    ins, aid = _assignment(client, db, ctx, "J-exc")
    execution = _execution(db, ctx, ins, aid)
    db.add(execution)
    db.commit()

    bad = _result_item(db, ctx, execution.id, record_state="EXCLUDED")
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── OTHER-объект требует описания ──────────────────────────────────────────────


def test_other_object_requires_description(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1OTH")
    ins, aid = _assignment(client, db, ctx, "J-oth")
    execution = _execution(db, ctx, ins, aid)
    db.add(execution)
    db.commit()

    bad = _result_item(db, ctx, execution.id, controlled_object_type="OTHER")
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── FK RESTRICT: нельзя удалить выполнение с локальным результатом ──────────────


def test_execution_delete_restricted_by_result_item(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1RES")
    ins, aid = _assignment(client, db, ctx, "J-res")
    execution = _execution(db, ctx, ins, aid)
    db.add(execution)
    db.commit()
    item = _result_item(db, ctx, execution.id)
    db.add(item)
    db.commit()

    db.delete(execution)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── CHECK статуса и полей отмены выполнения ─────────────────────────────────────


def test_invalid_execution_status_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1BAD")
    ins, aid = _assignment(client, db, ctx, "J-bad")
    bad = _execution(db, ctx, ins, aid, status="BOGUS")
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cancelled_execution_requires_fields(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "S1CAN")
    ins, aid = _assignment(client, db, ctx, "J-can")
    # CANCELLED без cancellation_type/причины/автора/времени — нарушение CHECK.
    bad = _execution(db, ctx, ins, aid, status="CANCELLED")
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── Нормализованная уникальность номера заключения ─────────────────────────────


def _conclusion(db: Session, ctx: Ctx, **over) -> LaboratoryConclusion:
    cid = over.pop("id", uuid4())
    fields: dict = dict(
        id=cid,
        project_id=ctx.project.id,
        laboratory_company_id=ctx.lab.id,
        inspection_method_id="UT",
        root_conclusion_id=over.pop("root_conclusion_id", cid),
        revision_no=1,
        is_current=True,
        status="DRAFT",
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
        version=1,
    )
    fields.update(over)
    # Уникальный ISSUED-индекс — по normalized_conclusion_number (миграция 18):
    # зеркалим переданный conclusion_number, если нормализованный явно не задан.
    if "normalized_conclusion_number" not in fields and fields.get(
        "conclusion_number"
    ):
        fields["normalized_conclusion_number"] = fields["conclusion_number"]
    return LaboratoryConclusion(**fields)


def test_issued_conclusion_number_unique_per_lab_year(
    client: TestClient, db: Session
) -> None:
    from datetime import datetime, timezone

    ctx = Ctx(db, "S1NUM")
    now = datetime.now(timezone.utc)
    first = _conclusion(
        db,
        ctx,
        status="ISSUED",
        conclusion_number="Z-100",
        conclusion_year=2026,
        issued_at=now,
    )
    db.add(first)
    db.commit()

    dup = _conclusion(
        db,
        ctx,
        status="ISSUED",
        conclusion_number="Z-100",
        conclusion_year=2026,
        issued_at=now,
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_draft_conclusion_may_share_issued_number(
    client: TestClient, db: Session
) -> None:
    from datetime import datetime, timezone

    ctx = Ctx(db, "S1NUM2")
    now = datetime.now(timezone.utc)
    issued = _conclusion(
        db,
        ctx,
        status="ISSUED",
        conclusion_number="Z-200",
        conclusion_year=2026,
        issued_at=now,
    )
    db.add(issued)
    db.commit()

    # DRAFT-редакция вне partial unique (WHERE status='ISSUED') — тот же номер допустим.
    draft = _conclusion(
        db, ctx, conclusion_number="Z-200", conclusion_year=2026
    )
    db.add(draft)
    db.commit()
    assert db.get(LaboratoryConclusion, draft.id) is not None
