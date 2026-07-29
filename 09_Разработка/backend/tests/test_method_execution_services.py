"""Интеграционные сервисные тесты выполнения метода (Task 9C, блок 9C-3).

Проверяют сервисное ядро MethodExecution напрямую (schemas/API ещё нет): создание,
жизненный цикл до LAB_CONFIRMED, участников, локальные результаты, расчёты, аудит,
RBAC/scope и регистрацию внешнего лабораторного документа. Родительские сущности
(проект/стык/заявка/лаборатория) строятся контекстом Ctx теста 9B.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import laboratory_conclusion_workflow as lcw  # noqa: F401 (симметрия)
from app.quality import method_execution_workflow as mew
from app.quality.execution_models import QualityExternalPerson
from app.quality.method_execution_services import (
    CancelExecutionInput,
    ConfirmInput,
    ExecutionCreateInput,
    MarkPerformedInput,
    MethodExecutionResultService,
    MethodExecutionService,
    ParticipantInput,
    ResultItemInput,
)
from app.quality.execution_repository import ExecutionRepo
from app.shared.errors import DomainError

from .test_inspection_method_assignments import Ctx

TODAY = date.today()
UTC = timezone.utc


def _setup(client: TestClient, db: Session, code: str, joint_no: str):
    ctx = Ctx(db, code)
    iid = ctx.inspection(client, joint_no)
    from uuid import UUID

    from app.quality.models import Inspection

    ins = db.get(Inspection, UUID(iid))
    assignment = ctx.assign(client, ctx.otk, iid, method="UT")
    from uuid import UUID as _U

    return ctx, ins, _U(assignment["id"])


def _person(db: Session, ctx: Ctx) -> QualityExternalPerson:
    person = QualityExternalPerson(
        full_name="Контролёр Петров",
        organization_company_id=ctx.lab.id,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def _add_lead(svc: MethodExecutionService, db: Session, ctx: Ctx, execution_id):
    person = _person(db, ctx)
    return svc.add_participant(
        execution_id,
        ParticipantInput(
            person_id=person.id, participant_role=mew.PARTICIPANT_LEAD_INSPECTOR
        ),
        actor_worker_id=ctx.otk.id,
    )


# ── Полный жизненный цикл до LAB_CONFIRMED ─────────────────────────────────────


def test_full_lifecycle_to_lab_confirmed(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV1", "J-sv1")
    svc = MethodExecutionService(db)
    rsvc = MethodExecutionResultService(db)

    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    assert ex.status == mew.EXEC_DRAFT
    assert ex.joint_id == ins.joint_id
    assert ex.laboratory_company_id == ctx.lab.id
    assert ex.calculated_evaluation == mew.EVAL_NOT_EVALUATED

    _add_lead(svc, db, ctx, ex.id)
    item = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_WHOLE_JOINT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    rsvc.complete_result_item(item.id, actor_worker_id=ctx.otk.id)

    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert ex.status == mew.EXEC_IN_PROGRESS
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(
            expected_version=ex.version,
            time_precision=mew.TIME_DATE_ONLY,
            performed_date=TODAY,
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert ex.status == mew.EXEC_PERFORMED
    ex = svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert ex.status == mew.EXEC_RESULT_RECORDED
    assert ex.calculated_evaluation == mew.EVAL_CONFORMING
    assert ex.calculated_completion == mew.COMPLETION_COMPLETE

    ex = svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version,
            confirmation_mode=mew.CONFIRM_EXTERNAL_DOCUMENT,
            laboratory_evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert ex.status == mew.EXEC_LAB_CONFIRMED
    assert ex.confirmation_mode == mew.CONFIRM_EXTERNAL_DOCUMENT
    assert ex.registered_by_worker_id == ctx.otk.id
    assert ex.lab_confirmed_by_user_id == ctx.otk.id
    assert ex.lab_confirmed_at is not None

    state = svc.compute_assignment_state(aid, actor_worker_id=ctx.otk.id)
    assert state == mew.ASSIGNMENT_STATE_COMPLETED_CONFORMING

    # Доменный аудит зафиксировал создание, смены статуса и подтверждение.
    events = ExecutionRepo(db).list_audit_events(
        mew.AUDIT_ENTITY_METHOD_EXECUTION, ex.id
    )
    kinds = {e.event_type for e in events}
    assert mew.AUDIT_EVENT_EXECUTION_CREATED in kinds
    assert mew.AUDIT_EVENT_STATUS_CHANGED in kinds
    assert mew.AUDIT_EVENT_RESULT_CONFIRMED in kinds
    confirmed = next(
        e for e in events if e.event_type == mew.AUDIT_EVENT_RESULT_CONFIRMED
    )
    assert confirmed.actor_worker_id == ctx.otk.id
    assert confirmed.new_values["lab_confirmed_by_user_id"] == ctx.otk.id
    assert confirmed.new_values["confirmation_mode"] == mew.CONFIRM_EXTERNAL_DOCUMENT


def test_confirm_sets_lab_confirmed_by_user_id(
    client: TestClient, db: Session
) -> None:
    ctx, _ins, aid = _setup(client, db, "SC1", "J-sc1")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _to_result_recorded(svc, rsvc, db, ctx, aid)
    confirmed_at_before = datetime.now(UTC)
    ex = svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version,
            laboratory_evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.ogs.id,
    )
    assert ex.status == mew.EXEC_LAB_CONFIRMED
    assert ex.lab_confirmed_by_user_id == ctx.ogs.id
    assert ex.registered_by_worker_id == ctx.ogs.id
    assert ex.confirmation_mode == mew.CONFIRM_EXTERNAL_DOCUMENT
    assert ex.lab_confirmed_at is not None
    assert ex.lab_confirmed_at >= confirmed_at_before


def test_reconfirm_after_lab_confirmed_rejected(
    client: TestClient, db: Session
) -> None:
    ctx, _ins, aid = _setup(client, db, "SC2", "J-sc2")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _confirmed(svc, rsvc, db, ctx, aid)
    snapshot = (
        ex.lab_confirmed_by_user_id,
        ex.lab_confirmed_at,
        ex.registered_by_worker_id,
        ex.confirmation_mode,
        ex.version,
        ex.status,
    )
    with pytest.raises(DomainError) as exc:
        svc.confirm(
            ex.id,
            ConfirmInput(
                expected_version=ex.version,
                laboratory_evaluation=mew.EVAL_CONFORMING,
            ),
            actor_worker_id=ctx.ogs.id,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == mew.EXECUTION_INVALID_TRANSITION
    db.refresh(ex)
    assert (
        ex.lab_confirmed_by_user_id,
        ex.lab_confirmed_at,
        ex.registered_by_worker_id,
        ex.confirmation_mode,
        ex.version,
        ex.status,
    ) == snapshot


def test_cancel_control_not_performed(client: TestClient, db: Session) -> None:
    ctx, _ins, aid = _setup(client, db, "SCN", "J-scn")
    svc = MethodExecutionService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert ex.status == mew.EXEC_IN_PROGRESS
    reason = "контроль не выполнен: нет доступа к стыку"
    ex = svc.cancel(
        ex.id,
        CancelExecutionInput(
            expected_version=ex.version,
            cancellation_type=mew.CANCEL_CONTROL_NOT_PERFORMED,
            cancellation_reason=reason,
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert ex.status == mew.EXEC_CANCELLED
    assert ex.cancellation_type == mew.CANCEL_CONTROL_NOT_PERFORMED
    assert ex.cancellation_reason == reason
    assert ex.cancelled_by_worker_id == ctx.otk.id
    assert ex.cancelled_at is not None

    events = ExecutionRepo(db).list_audit_events(
        mew.AUDIT_ENTITY_METHOD_EXECUTION, ex.id
    )
    assert any(
        e.event_type == mew.AUDIT_EVENT_EXECUTION_CANCELLED
        and e.actor_worker_id == ctx.otk.id
        and e.reason == reason
        for e in events
    )

    with pytest.raises(DomainError) as exc:
        svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == mew.EXECUTION_INVALID_TRANSITION

    with pytest.raises(DomainError) as exc:
        svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == mew.EXECUTION_INVALID_TRANSITION

    with pytest.raises(DomainError) as exc:
        svc.confirm(
            ex.id,
            ConfirmInput(
                expected_version=ex.version,
                laboratory_evaluation=mew.EVAL_CONFORMING,
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_INVALID_TRANSITION


def test_cancel_control_not_performed_requires_reason(
    client: TestClient, db: Session
) -> None:
    ctx, _ins, aid = _setup(client, db, "SCN2", "J-scn2")
    svc = MethodExecutionService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    with pytest.raises(DomainError) as exc:
        svc.cancel(
            ex.id,
            CancelExecutionInput(
                expected_version=ex.version,
                cancellation_type=mew.CANCEL_CONTROL_NOT_PERFORMED,
                cancellation_reason="   ",
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_CANCELLATION_REASON_REQUIRED


# ── record_result: обязательные условия ────────────────────────────────────────


def _to_performed(svc, rsvc, db, ctx, aid, *, with_lead, with_item):
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    if with_lead:
        _add_lead(svc, db, ctx, ex.id)
    if with_item:
        item = rsvc.add_result_item(
            ex.id,
            ResultItemInput(evaluation=mew.EVAL_CONFORMING),
            actor_worker_id=ctx.otk.id,
        )
        rsvc.complete_result_item(item.id, actor_worker_id=ctx.otk.id)
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(
            expected_version=ex.version, performed_date=TODAY
        ),
        actor_worker_id=ctx.otk.id,
    )
    return ex


def test_record_result_requires_items(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV2", "J-sv2")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _to_performed(svc, rsvc, db, ctx, aid, with_lead=True, with_item=False)
    with pytest.raises(DomainError) as exc:
        svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == mew.EXECUTION_NO_RESULT_ITEMS


def test_record_result_requires_lead(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV3", "J-sv3")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _to_performed(svc, rsvc, db, ctx, aid, with_lead=False, with_item=True)
    with pytest.raises(DomainError) as exc:
        svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == mew.EXECUTION_NO_LEAD_INSPECTOR


def test_record_result_rejects_draft_items(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "SV4", "J-sv4")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    _add_lead(svc, db, ctx, ex.id)
    done = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_WHOLE_JOINT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    rsvc.complete_result_item(done.id, actor_worker_id=ctx.otk.id)
    # Второй результат оставлен в DRAFT.
    rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_LINEAR_SEGMENT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(expected_version=ex.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    with pytest.raises(DomainError) as exc:
        svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == mew.EXECUTION_INCOMPLETE_RESULT_ITEMS


# ── Отмена и запрет изменений после подтверждения ──────────────────────────────


def test_cancel_before_confirm(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV5", "J-sv5")
    svc = MethodExecutionService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    ex = svc.cancel(
        ex.id,
        CancelExecutionInput(
            expected_version=ex.version,
            cancellation_type=mew.CANCEL_CREATED_BY_MISTAKE,
            cancellation_reason="ошибочно создано",
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert ex.status == mew.EXEC_CANCELLED
    assert ex.cancelled_by_worker_id == ctx.otk.id


def test_cannot_cancel_after_confirmed(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV6", "J-sv6")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _confirmed(svc, rsvc, db, ctx, aid)
    with pytest.raises(DomainError) as exc:
        svc.cancel(
            ex.id,
            CancelExecutionInput(
                expected_version=ex.version,
                cancellation_type=mew.CANCEL_OTHER,
                cancellation_reason="поздно",
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_INVALID_TRANSITION


def test_edit_after_confirmed_forbidden(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV7", "J-sv7")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _confirmed(svc, rsvc, db, ctx, aid)
    person = _person(db, ctx)
    with pytest.raises(DomainError) as exc:
        svc.add_participant(
            ex.id,
            ParticipantInput(
                person_id=person.id, participant_role=mew.PARTICIPANT_INSPECTOR
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_ALREADY_CONFIRMED


# ── RBAC / scope ───────────────────────────────────────────────────────────────


def test_write_role_required(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV8", "J-sv8")
    svc = MethodExecutionService(db)
    # ПТО видит заявку (read), но не имеет права создавать выполнение.
    with pytest.raises(DomainError) as exc:
        svc.create_execution(
            aid, ExecutionCreateInput(), actor_worker_id=ctx.pto.id
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == mew.EXECUTION_ROLE_DENIED


def test_hidden_by_scope_is_not_found(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV9", "J-sv9")
    svc = MethodExecutionService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_execution(
            aid, ExecutionCreateInput(), actor_worker_id=ctx.norole.id
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == mew.EXECUTION_NOT_FOUND


# ── Подтверждение: режимы и override ───────────────────────────────────────────


def test_direct_confirmation_unsupported(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV10", "J-sv10")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _to_result_recorded(svc, rsvc, db, ctx, aid)
    with pytest.raises(DomainError) as exc:
        svc.confirm(
            ex.id,
            ConfirmInput(
                expected_version=ex.version,
                confirmation_mode=mew.CONFIRM_DIRECT_LAB,
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_DIRECT_CONFIRMATION_UNSUPPORTED


def test_lab_evaluation_override_requires_reason(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "SV11", "J-sv11")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _to_result_recorded(svc, rsvc, db, ctx, aid)  # calc = CONFORMING
    with pytest.raises(DomainError) as exc:
        svc.confirm(
            ex.id,
            ConfirmInput(
                expected_version=ex.version,
                laboratory_evaluation=mew.EVAL_NONCONFORMING,
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert (
        exc.value.detail["code"]
        == mew.EXECUTION_EVALUATION_OVERRIDE_REASON_REQUIRED
    )
    # С обоснованием — проходит.
    ex = svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version,
            laboratory_evaluation=mew.EVAL_NONCONFORMING,
            evaluation_override_reason="лаборатория выявила недопустимое",
        ),
        actor_worker_id=ctx.otk.id,
    )
    assert ex.status == mew.EXEC_LAB_CONFIRMED
    assert ex.laboratory_evaluation == mew.EVAL_NONCONFORMING


# ── Время ──────────────────────────────────────────────────────────────────────


def test_mark_performed_finish_before_start(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "SV12", "J-sv12")
    svc = MethodExecutionService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    start = datetime(2026, 7, 14, 10, tzinfo=UTC)
    with pytest.raises(DomainError) as exc:
        svc.mark_performed(
            ex.id,
            MarkPerformedInput(
                expected_version=ex.version,
                time_precision=mew.TIME_FULL_INTERVAL,
                started_at=start,
                finished_at=start - timedelta(hours=1),
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_TIME_FINISH_BEFORE_START


# ── Участники ──────────────────────────────────────────────────────────────────


def test_second_lead_inspector_conflict(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "SV13", "J-sv13")
    svc = MethodExecutionService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    _add_lead(svc, db, ctx, ex.id)
    second = _person(db, ctx)
    with pytest.raises(DomainError) as exc:
        svc.add_participant(
            ex.id,
            ParticipantInput(
                person_id=second.id,
                participant_role=mew.PARTICIPANT_LEAD_INSPECTOR,
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_MULTIPLE_LEAD_INSPECTORS


# ── Локальные результаты: исключение и пересчёт ────────────────────────────────


def test_exclude_result_recomputes_and_audits(
    client: TestClient, db: Session
) -> None:
    ctx, ins, aid = _setup(client, db, "SV14", "J-sv14")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    good = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_WHOLE_JOINT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    rsvc.complete_result_item(good.id, actor_worker_id=ctx.otk.id)
    bad = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_LINEAR_SEGMENT,
            evaluation=mew.EVAL_NONCONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    ex2 = rsvc.complete_result_item(bad.id, actor_worker_id=ctx.otk.id)
    refreshed = svc.get_execution(ex.id, actor_worker_id=ctx.otk.id)
    assert refreshed.calculated_evaluation == mew.EVAL_NONCONFORMING

    rsvc.exclude_result_item(
        bad.id, "ошибочная строка", actor_worker_id=ctx.otk.id
    )
    refreshed = svc.get_execution(ex.id, actor_worker_id=ctx.otk.id)
    assert refreshed.calculated_evaluation == mew.EVAL_CONFORMING
    events = ExecutionRepo(db).list_audit_events(
        mew.AUDIT_ENTITY_RESULT_ITEM, bad.id
    )
    assert any(
        e.event_type == mew.AUDIT_EVENT_REMOVED_RESULT_ITEM for e in events
    )
    _ = ex2


# ── Лаборатория должна быть NDT_LAB проекта ────────────────────────────────────


def test_laboratory_must_be_ndt_lab(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV15", "J-sv15")
    svc = MethodExecutionService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_execution(
            aid,
            ExecutionCreateInput(laboratory_company_id=ctx.nonlab.id),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == mew.EXECUTION_LABORATORY_NOT_NDT_LAB


# ── Расчёт полноты по мерному поясу ────────────────────────────────────────────


def test_completion_belt_gap(client: TestClient, db: Session) -> None:
    ctx, ins, aid = _setup(client, db, "SV16", "J-sv16")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = svc.create_execution(
        aid,
        ExecutionCreateInput(
            declared_belt_length=Decimal("1000"), belt_length_unit=mew.COORD_UNIT_MM
        ),
        actor_worker_id=ctx.otk.id,
    )
    _add_lead(svc, db, ctx, ex.id)
    for lo, hi in ((Decimal("0"), Decimal("300")), (Decimal("600"), Decimal("1000"))):
        item = rsvc.add_result_item(
            ex.id,
            ResultItemInput(
                controlled_object_type=mew.OBJ_MEASURING_BELT_SEGMENT,
                coordinate_system=mew.COORD_MEASURING_BELT,
                coordinate_unit=mew.COORD_UNIT_MM,
                coordinate_from=lo,
                coordinate_to=hi,
                evaluation=mew.EVAL_CONFORMING,
            ),
            actor_worker_id=ctx.otk.id,
        )
        rsvc.complete_result_item(item.id, actor_worker_id=ctx.otk.id)
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(expected_version=ex.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    ex = svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    assert ex.calculated_completion == mew.COMPLETION_HAS_GAPS


# ── Вспомогательные конвейеры ──────────────────────────────────────────────────


def _to_result_recorded(svc, rsvc, db, ctx, aid):
    ex = svc.create_execution(
        aid, ExecutionCreateInput(), actor_worker_id=ctx.otk.id
    )
    _add_lead(svc, db, ctx, ex.id)
    item = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_WHOLE_JOINT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
    rsvc.complete_result_item(item.id, actor_worker_id=ctx.otk.id)
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(expected_version=ex.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    return svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)


def _confirmed(svc, rsvc, db, ctx, aid):
    ex = _to_result_recorded(svc, rsvc, db, ctx, aid)
    return svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version,
            laboratory_evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.otk.id,
    )
