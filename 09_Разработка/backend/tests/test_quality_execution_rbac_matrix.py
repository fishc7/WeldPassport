"""Минимальная RBAC-матрица Task 9C: позитивные и негативные роли/scope.

Подтверждает уже заложенный канон прав без расширения матрицы:
- EXECUTION_WRITE_ROLES: OTK / NDT_SPECIALIST / CHIEF_WELDER;
- EXTERNAL_REGISTRATION_ROLES / CONCLUSION_WRITE_ROLES: OTK / OGS_ENGINEER /
  CHIEF_WELDER;
- роль без write → 403; actor вне scope → скрытый 404.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hr.models import Worker, WorkerRole
from app.quality import laboratory_conclusion_workflow as lcw
from app.quality import method_execution_workflow as mew
from app.quality.execution_models import QualityExternalPerson
from app.quality.laboratory_conclusion_services import (
    ConclusionCreateInput,
    LaboratoryConclusionService,
)
from app.quality.method_execution_services import (
    ConfirmInput,
    ExecutionCreateInput,
    MarkPerformedInput,
    MethodExecutionResultService,
    MethodExecutionService,
    ParticipantInput,
    ResultItemInput,
)
from app.shared.errors import DomainError

from .test_inspection_method_assignments import Ctx

TODAY = date.today()


def _person(db: Session, ctx: Ctx) -> QualityExternalPerson:
    person = QualityExternalPerson(
        full_name="RBAC контролёр",
        organization_company_id=ctx.lab.id,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def _assignment(client: TestClient, db: Session, code: str, joint_no: str):
    ctx = Ctx(db, code)
    iid = ctx.inspection(client, joint_no)
    assignment = ctx.assign(client, ctx.otk, iid, method="UT")
    return ctx, UUID(assignment["id"])


def _prepare_for_confirm(svc, rsvc, db, ctx, aid, *, actor):
    ex = svc.create_execution(aid, ExecutionCreateInput(), actor_worker_id=actor.id)
    person = _person(db, ctx)
    svc.add_participant(
        ex.id,
        ParticipantInput(
            person_id=person.id, participant_role=mew.PARTICIPANT_LEAD_INSPECTOR
        ),
        actor_worker_id=actor.id,
    )
    item = rsvc.add_result_item(
        ex.id,
        ResultItemInput(
            controlled_object_type=mew.OBJ_WHOLE_JOINT,
            evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=actor.id,
    )
    rsvc.complete_result_item(item.id, actor_worker_id=actor.id)
    ex = svc.start(ex.id, ex.version, actor_worker_id=actor.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(expected_version=ex.version, performed_date=TODAY),
        actor_worker_id=actor.id,
    )
    return svc.record_result(ex.id, ex.version, actor_worker_id=actor.id)


# ── Позитивные сценарии ────────────────────────────────────────────────────────


def test_ndt_specialist_can_create_start_and_drive_execution(
    client: TestClient, db: Session
) -> None:
    ctx, aid = _assignment(client, db, "RB1", "J-rb1")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _prepare_for_confirm(svc, rsvc, db, ctx, aid, actor=ctx.ndt)
    assert ex.status == mew.EXEC_RESULT_RECORDED
    assert ex.updated_by_worker_id == ctx.ndt.id


def test_ogs_engineer_can_register_external_document(
    client: TestClient, db: Session
) -> None:
    ctx, aid = _assignment(client, db, "RB2", "J-rb2")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    # Подготовку ведёт NDT/OTK-роль; confirm выполняет OGS.
    ex = _prepare_for_confirm(svc, rsvc, db, ctx, aid, actor=ctx.ndt)
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


def test_ogs_engineer_can_create_laboratory_conclusion(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "RB3")
    svc = LaboratoryConclusionService(db)
    conclusion = svc.create_conclusion(
        ConclusionCreateInput(
            project_id=ctx.project.id,
            laboratory_company_id=ctx.lab.id,
            inspection_method_id="UT",
        ),
        actor_worker_id=ctx.ogs.id,
    )
    assert conclusion.status == lcw.CONCLUSION_DRAFT
    assert conclusion.created_by_worker_id == ctx.ogs.id


def test_chief_welder_can_drive_execution_and_conclusion(
    client: TestClient, db: Session
) -> None:
    ctx, aid = _assignment(client, db, "RB4", "J-rb4")
    svc, rsvc = MethodExecutionService(db), MethodExecutionResultService(db)
    ex = _prepare_for_confirm(svc, rsvc, db, ctx, aid, actor=ctx.chief)
    ex = svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version,
            laboratory_evaluation=mew.EVAL_CONFORMING,
        ),
        actor_worker_id=ctx.chief.id,
    )
    assert ex.status == mew.EXEC_LAB_CONFIRMED
    assert ex.lab_confirmed_by_user_id == ctx.chief.id

    conclusion = LaboratoryConclusionService(db).create_conclusion(
        ConclusionCreateInput(
            project_id=ctx.project.id,
            laboratory_company_id=ctx.lab.id,
            inspection_method_id="UT",
        ),
        actor_worker_id=ctx.chief.id,
    )
    assert conclusion.status == lcw.CONCLUSION_DRAFT


# ── Негативные сценарии ────────────────────────────────────────────────────────


def test_ndt_specialist_cannot_write_laboratory_conclusion(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "RB5")
    with pytest.raises(DomainError) as exc:
        LaboratoryConclusionService(db).create_conclusion(
            ConclusionCreateInput(
                project_id=ctx.project.id,
                laboratory_company_id=ctx.lab.id,
                inspection_method_id="UT",
            ),
            actor_worker_id=ctx.ndt.id,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == lcw.CONCLUSION_ROLE_DENIED


def test_role_without_access_gets_403(client: TestClient, db: Session) -> None:
    ctx, aid = _assignment(client, db, "RB6", "J-rb6")
    with pytest.raises(DomainError) as exc:
        MethodExecutionService(db).create_execution(
            aid, ExecutionCreateInput(), actor_worker_id=ctx.pto.id
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == mew.EXECUTION_ROLE_DENIED


def test_out_of_scope_actor_gets_hidden_404(
    client: TestClient, db: Session
) -> None:
    ctx, aid = _assignment(client, db, "RB7", "J-rb7")
    outsider = Worker(
        last_name="Вне",
        first_name="Скоуп",
        company_id=99_901,
        employment_status="active",
        hire_date=TODAY,
    )
    db.add(outsider)
    db.commit()
    db.refresh(outsider)
    db.add(
        WorkerRole(
            worker_id=outsider.id,
            role_code="OTK_INSPECTOR",
            scope_type="PROJECT",
            scope_id=str(uuid4()),
            is_active=True,
            valid_from=TODAY,
        )
    )
    db.commit()

    with pytest.raises(DomainError) as exc:
        MethodExecutionService(db).create_execution(
            aid, ExecutionCreateInput(), actor_worker_id=outsider.id
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == mew.EXECUTION_NOT_FOUND
