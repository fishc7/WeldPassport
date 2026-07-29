"""Интеграционные тесты сервисного ядра LaboratoryConclusion (Task 9C, блок 9C-5).

Покрывают создание, состав (связь с конкретными редакциями MethodExecution),
lifecycle DRAFT→PREPARED→LAB_APPROVED→ISSUED, отмену, номер и его нормализацию,
контролируемые редакции с атомарным замещением, признак пересмотра при замещении
связанного выполнения, аккредитацию, RBAC/scope и аудит. Schemas/API — вне блока.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.quality import laboratory_conclusion_workflow as lcw
from app.quality import method_execution_workflow as mew
from app.quality.execution_models import (
    LaboratoryAccreditation,
    QualityExternalPerson,
)
from app.quality.execution_repository import ExecutionRepo
from app.quality.laboratory_conclusion_services import (
    ApproveConclusionInput,
    CancelConclusionInput,
    ConclusionCreateInput,
    IssueConclusionInput,
    LaboratoryConclusionRevisionService,
    LaboratoryConclusionService,
)
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

from .test_inspection_method_assignments import Ctx

TODAY = date.today()


def _person(db: Session, ctx: Ctx) -> QualityExternalPerson:
    p = QualityExternalPerson(
        full_name="Лаб. представитель",
        organization_company_id=ctx.lab.id,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _execution(client, db, ctx, joint_no, *, method="UT", lab=None, stage="CONFIRMED"):
    """Строит MethodExecution нужной стадии для указанной лаборатории/метода."""
    lab = lab or ctx.lab
    iid = ctx.inspection(client, joint_no)
    a = ctx.assign(client, ctx.otk, iid, method=method, lab_id=lab.id)
    svc = MethodExecutionService(db)
    rsvc = MethodExecutionResultService(db)
    ex = svc.create_execution(
        UUID(a["id"]), ExecutionCreateInput(), actor_worker_id=ctx.otk.id
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
    ex = svc.start(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    ex = svc.mark_performed(
        ex.id,
        MarkPerformedInput(expected_version=ex.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    if stage == "PERFORMED":
        return ex
    ex = svc.record_result(ex.id, ex.version, actor_worker_id=ctx.otk.id)
    if stage == "RESULT_RECORDED":
        return ex
    return svc.confirm(
        ex.id,
        ConfirmInput(
            expected_version=ex.version, laboratory_evaluation=mew.EVAL_CONFORMING
        ),
        actor_worker_id=ctx.otk.id,
    )


def _create(svc, ctx, *, method="UT", number=None, year=None, accreditation_id=None):
    person = _person(svc._db, ctx)  # noqa: SLF001 (тестовая вставка внешнего лица)
    return svc.create_conclusion(
        ConclusionCreateInput(
            project_id=ctx.project.id,
            laboratory_company_id=ctx.lab.id,
            inspection_method_id=method,
            conclusion_number=number,
            conclusion_year=year,
            laboratory_accreditation_id=accreditation_id,
            lab_approver_person_id=person.id,
            issued_by_person_id=person.id,
        ),
        actor_worker_id=ctx.otk.id,
    )


def _issue(client, db, ctx, *, number, year=2026, method="UT", joint="J"):
    """Полный путь до ISSUED: создание → связь → PREPARED → APPROVED → ISSUED."""
    ex = _execution(client, db, ctx, joint, method=method)
    svc = LaboratoryConclusionService(db)
    c = _create(svc, ctx, method=method)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    c = svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    c = svc.approve(
        c.id, ApproveConclusionInput(expected_version=c.version),
        actor_worker_id=ctx.otk.id,
    )
    c = svc.issue(
        c.id,
        IssueConclusionInput(
            expected_version=c.version, conclusion_number=number, conclusion_year=year
        ),
        actor_worker_id=ctx.otk.id,
    )
    return svc, c, ex


def _accreditation(db, ctx, company, *, valid_until=None, status="ACTIVE"):
    acc = LaboratoryAccreditation(
        company_id=company.id,
        certificate_number="ACC-100",
        valid_from=date(2026, 1, 1),
        valid_until=valid_until,
        status=status,
        created_by_worker_id=ctx.otk.id,
        updated_by_worker_id=ctx.otk.id,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


# ── Создание (1–4) ─────────────────────────────────────────────────────────────


def test_create_draft(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC01")
    svc = LaboratoryConclusionService(db)
    c = _create(svc, ctx)
    assert c.status == lcw.CONCLUSION_DRAFT
    assert c.is_current is True
    assert c.revision_no == 1
    assert c.root_conclusion_id == c.id
    events = ExecutionRepo(db).list_audit_events(
        mew.AUDIT_ENTITY_CONCLUSION, c.id
    )
    assert any(e.event_type == mew.AUDIT_EVENT_CONCLUSION_CREATED for e in events)


def test_create_laboratory_not_ndt_lab(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC02")
    svc = LaboratoryConclusionService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_conclusion(
            ConclusionCreateInput(
                project_id=ctx.project.id,
                laboratory_company_id=ctx.nonlab.id,
                inspection_method_id="UT",
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_LABORATORY_NOT_NDT_LAB


def test_create_other_scope_not_found(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC03")
    from app.hr.models import Worker, WorkerRole

    w = Worker(
        last_name="Чужой", first_name="Скоуп",
        company_id=99_999, employment_status="active", hire_date=TODAY,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    db.add(
        WorkerRole(
            worker_id=w.id, role_code="OTK_INSPECTOR", scope_type="PROJECT",
            scope_id=str(uuid4()), is_active=True, valid_from=TODAY,
        )
    )
    db.commit()
    svc = LaboratoryConclusionService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_conclusion(
            ConclusionCreateInput(
                project_id=ctx.project.id,
                laboratory_company_id=ctx.lab.id,
                inspection_method_id="UT",
            ),
            actor_worker_id=w.id,
        )
    assert exc.value.status_code == 404


def test_create_role_denied(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC04")
    svc = LaboratoryConclusionService(db)
    with pytest.raises(DomainError) as exc:
        svc.create_conclusion(
            ConclusionCreateInput(
                project_id=ctx.project.id,
                laboratory_company_id=ctx.lab.id,
                inspection_method_id="UT",
            ),
            actor_worker_id=ctx.pto.id,  # PTO: read, но не write
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == lcw.CONCLUSION_ROLE_DENIED


# ── Связи (5–11) ────────────────────────────────────────────────────────────────


def test_add_single_confirmed_execution(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC05")
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-5")
    c = _create(svc, ctx)
    link = svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    assert link.method_execution_id == ex.id
    events = ExecutionRepo(db).list_audit_events(
        mew.AUDIT_ENTITY_CONCLUSION, c.id
    )
    assert any(
        e.event_type == mew.AUDIT_EVENT_CONCLUSION_EXECUTION_ADDED for e in events
    )


def test_add_multiple_executions_same_method(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "LC06")
    svc = LaboratoryConclusionService(db)
    ex1 = _execution(client, db, ctx, "J-6a")
    ex2 = _execution(client, db, ctx, "J-6b")
    c = _create(svc, ctx)
    svc.add_execution(c.id, ex1.id, actor_worker_id=ctx.otk.id)
    svc.add_execution(c.id, ex2.id, actor_worker_id=ctx.otk.id)
    assert len(svc.list_executions(c.id, actor_worker_id=ctx.otk.id)) == 2


def test_add_other_method_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC07")
    svc = LaboratoryConclusionService(db)
    ex_rt = _execution(client, db, ctx, "J-7", method="RT")
    c = _create(svc, ctx, method="UT")
    with pytest.raises(DomainError) as exc:
        svc.add_execution(c.id, ex_rt.id, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_METHOD_MISMATCH


def test_add_other_laboratory_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC08")
    svc = LaboratoryConclusionService(db)
    ex_lab2 = _execution(client, db, ctx, "J-8", lab=ctx.lab2)
    c = _create(svc, ctx)  # lab = ctx.lab
    with pytest.raises(DomainError) as exc:
        svc.add_execution(c.id, ex_lab2.id, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_LABORATORY_MISMATCH


def test_add_other_project_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC09")
    other = Ctx(db, "LC09B")
    svc = LaboratoryConclusionService(db)
    ex_other = _execution(client, db, other, "J-9", lab=other.lab)
    c = _create(svc, ctx)
    with pytest.raises(DomainError) as exc:
        svc.add_execution(c.id, ex_other.id, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_PROJECT_MISMATCH


def test_add_duplicate_link_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC10")
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-10")
    c = _create(svc, ctx)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    with pytest.raises(DomainError) as exc:
        svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_EXECUTION_DUPLICATE


def test_remove_link_only_in_draft(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC11")
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-11")
    c = _create(svc, ctx)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    svc.remove_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)  # DRAFT: ok
    assert svc.list_executions(c.id, actor_worker_id=ctx.otk.id) == []
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    c = svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    with pytest.raises(DomainError) as exc:
        svc.remove_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_COMPOSITION_LOCKED
    events = ExecutionRepo(db).list_audit_events(
        mew.AUDIT_ENTITY_CONCLUSION, c.id
    )
    assert any(
        e.event_type == mew.AUDIT_EVENT_CONCLUSION_EXECUTION_REMOVED for e in events
    )


# ── Lifecycle (12–18) ───────────────────────────────────────────────────────────


def test_prepare_from_draft(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC12")
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-12")
    c = _create(svc, ctx)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    c = svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    assert c.status == lcw.CONCLUSION_PREPARED


def test_prepare_without_executions_fails(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC13")
    svc = LaboratoryConclusionService(db)
    c = _create(svc, ctx)
    with pytest.raises(DomainError) as exc:
        svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_NO_EXECUTIONS


def test_approve_requires_all_confirmed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC14")
    svc = LaboratoryConclusionService(db)
    ex_perf = _execution(client, db, ctx, "J-14", stage="PERFORMED")
    c = _create(svc, ctx)
    svc.add_execution(c.id, ex_perf.id, actor_worker_id=ctx.otk.id)
    c = svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    with pytest.raises(DomainError) as exc:
        svc.approve(
            c.id, ApproveConclusionInput(expected_version=c.version),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_EXECUTION_NOT_CONFIRMED


def test_issue_requires_number_and_year(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC15")
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-15")
    c = _create(svc, ctx)  # без номера/года
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    c = svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    c = svc.approve(
        c.id, ApproveConclusionInput(expected_version=c.version),
        actor_worker_id=ctx.otk.id,
    )
    with pytest.raises(DomainError) as exc:
        svc.issue(
            c.id, IssueConclusionInput(expected_version=c.version),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_NUMBER_REQUIRED
    with pytest.raises(DomainError) as exc2:
        svc.issue(
            c.id,
            IssueConclusionInput(expected_version=c.version, conclusion_number="A-1"),
            actor_worker_id=ctx.otk.id,
        )
    assert exc2.value.detail["code"] == lcw.CONCLUSION_ISSUE_FIELDS_REQUIRED


def test_no_edit_after_issued(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC16")
    svc, c, ex = _issue(client, db, ctx, number="I-16", joint="J-16")
    other = _execution(client, db, ctx, "J-16b")
    with pytest.raises(DomainError) as exc:
        svc.add_execution(c.id, other.id, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.CONCLUSION_COMPOSITION_LOCKED


def test_cancel_before_issued(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC17")
    svc = LaboratoryConclusionService(db)
    c = _create(svc, ctx)
    c = svc.cancel(
        c.id, CancelConclusionInput(expected_version=c.version, reason="черновик"),
        actor_worker_id=ctx.otk.id,
    )
    assert c.status == lcw.CONCLUSION_CANCELLED


def test_cannot_cancel_issued(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC18")
    svc, c, ex = _issue(client, db, ctx, number="I-18", joint="J-18")
    with pytest.raises(DomainError) as exc:
        svc.cancel(
            c.id, CancelConclusionInput(expected_version=c.version, reason="нет"),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_INVALID_TRANSITION


# ── Номер (19–23) ───────────────────────────────────────────────────────────────


def test_issued_number_conflict_other_root(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC19")
    _issue(client, db, ctx, number="DUP-1", year=2026, joint="J-19a")
    ex2 = _execution(client, db, ctx, "J-19b")
    svc = LaboratoryConclusionService(db)
    c2 = _create(svc, ctx)
    svc.add_execution(c2.id, ex2.id, actor_worker_id=ctx.otk.id)
    c2 = svc.prepare(c2.id, c2.version, actor_worker_id=ctx.otk.id)
    c2 = svc.approve(
        c2.id, ApproveConclusionInput(expected_version=c2.version),
        actor_worker_id=ctx.otk.id,
    )
    with pytest.raises(DomainError) as exc:
        svc.issue(
            c2.id,
            IssueConclusionInput(
                expected_version=c2.version, conclusion_number="DUP-1",
                conclusion_year=2026,
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_DUPLICATE_NUMBER


def test_draft_may_reuse_issued_number(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC20")
    _issue(client, db, ctx, number="RE-1", year=2026, joint="J-20a")
    svc = LaboratoryConclusionService(db)
    c2 = _create(svc, ctx, number="RE-1", year=2026)  # DRAFT — допустимо
    assert c2.status == lcw.CONCLUSION_DRAFT
    assert c2.normalized_conclusion_number == "RE-1"


def test_revision_may_keep_number(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC21")
    svc, c, ex = _issue(client, db, ctx, number="K-21", year=2026, joint="J-21")
    rev = LaboratoryConclusionRevisionService(db)
    r2 = rev.create_revision(
        c.id, correction_reason="правка", expected_version=c.version,
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.prepare(r2.id, r2.version, actor_worker_id=ctx.otk.id)
    r2 = svc.approve(
        r2.id, ApproveConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.issue(
        r2.id, IssueConclusionInput(expected_version=r2.version),  # тот же номер
        actor_worker_id=ctx.otk.id,
    )
    assert r2.status == lcw.CONCLUSION_ISSUED
    assert r2.conclusion_number == "K-21"


def test_revision_may_use_new_number(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC22")
    svc, c, ex = _issue(client, db, ctx, number="OLD-22", year=2026, joint="J-22")
    rev = LaboratoryConclusionRevisionService(db)
    r2 = rev.create_revision(
        c.id, correction_reason="новый номер", expected_version=c.version,
        conclusion_number="NEW-22", actor_worker_id=ctx.otk.id,
    )
    assert r2.conclusion_number == "NEW-22"
    r2 = svc.prepare(r2.id, r2.version, actor_worker_id=ctx.otk.id)
    r2 = svc.approve(
        r2.id, ApproveConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.issue(
        r2.id, IssueConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    assert r2.conclusion_number == "NEW-22"


def test_number_normalization_blocks_false_duplicates(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "LC23")
    _issue(client, db, ctx, number="N 5", year=2026, joint="J-23a")
    ex2 = _execution(client, db, ctx, "J-23b")
    svc = LaboratoryConclusionService(db)
    c2 = _create(svc, ctx)
    svc.add_execution(c2.id, ex2.id, actor_worker_id=ctx.otk.id)
    c2 = svc.prepare(c2.id, c2.version, actor_worker_id=ctx.otk.id)
    c2 = svc.approve(
        c2.id, ApproveConclusionInput(expected_version=c2.version),
        actor_worker_id=ctx.otk.id,
    )
    with pytest.raises(DomainError) as exc:
        svc.issue(
            c2.id,
            IssueConclusionInput(
                expected_version=c2.version, conclusion_number="  n   5 ",
                conclusion_year=2026,
            ),
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_DUPLICATE_NUMBER


# ── Редакции (24–34) ────────────────────────────────────────────────────────────


def test_create_revision_from_issued(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC24")
    svc, c, ex = _issue(client, db, ctx, number="R-24", joint="J-24")
    rev = LaboratoryConclusionRevisionService(db)
    r2 = rev.create_revision(
        c.id, correction_reason="ревизия", expected_version=c.version,
        actor_worker_id=ctx.otk.id,
    )
    assert r2.revision_no == 2
    assert r2.status == lcw.CONCLUSION_DRAFT
    assert r2.is_current is False
    assert r2.supersedes_conclusion_id == c.id
    assert r2.root_conclusion_id == c.root_conclusion_id
    # 25: старая остаётся текущей ISSUED
    old = ExecutionRepo(db).get_conclusion(c.id)
    assert old.status == lcw.CONCLUSION_ISSUED and old.is_current is True
    # 26: связи скопированы
    assert len(svc.list_executions(r2.id, actor_worker_id=ctx.otk.id)) == 1
    # 27: выпуск/утверждение сброшены
    assert r2.issued_at is None
    assert r2.lab_approved_by_worker_id is None
    assert r2.revision_review_required is False


def test_revision_full_lifecycle_and_swap(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC29")
    svc, c, ex = _issue(client, db, ctx, number="S-29", joint="J-29")
    rev = LaboratoryConclusionRevisionService(db)
    r2 = rev.create_revision(
        c.id, correction_reason="ревизия", expected_version=c.version,
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.prepare(r2.id, r2.version, actor_worker_id=ctx.otk.id)
    r2 = svc.approve(
        r2.id, ApproveConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.issue(
        r2.id, IssueConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    assert r2.status == lcw.CONCLUSION_ISSUED and r2.is_current is True
    repo = ExecutionRepo(db)
    old = repo.get_conclusion(c.id)
    assert old.status == lcw.CONCLUSION_SUPERSEDED and old.is_current is False
    current = repo.get_current_conclusion_for_root(c.root_conclusion_id)
    assert current.id == r2.id
    assert len(repo.list_conclusion_revisions(c.root_conclusion_id)) == 2


def test_revision_cancel_keeps_old_current(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC32")
    svc, c, ex = _issue(client, db, ctx, number="C-32", joint="J-32")
    rev = LaboratoryConclusionRevisionService(db)
    r2 = rev.create_revision(
        c.id, correction_reason="ревизия", expected_version=c.version,
        actor_worker_id=ctx.otk.id,
    )
    svc.cancel(
        r2.id, CancelConclusionInput(expected_version=r2.version, reason="откат"),
        actor_worker_id=ctx.otk.id,
    )
    repo = ExecutionRepo(db)
    old = repo.get_conclusion(c.id)
    assert old.status == lcw.CONCLUSION_ISSUED and old.is_current is True
    r2_reloaded = repo.get_conclusion(r2.id)
    assert r2_reloaded.status == lcw.CONCLUSION_CANCELLED
    events = repo.list_audit_events(mew.AUDIT_ENTITY_CONCLUSION, r2.id)
    assert any(
        e.event_type == mew.AUDIT_EVENT_CONCLUSION_REVISION_CANCELLED for e in events
    )


def test_second_open_revision_blocked(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC33")
    svc, c, ex = _issue(client, db, ctx, number="B-33", joint="J-33")
    rev = LaboratoryConclusionRevisionService(db)
    rev.create_revision(
        c.id, correction_reason="первая", expected_version=c.version,
        actor_worker_id=ctx.otk.id,
    )
    with pytest.raises(DomainError) as exc:
        rev.create_revision(
            c.id, correction_reason="вторая", expected_version=c.version,
            actor_worker_id=ctx.otk.id,
        )
    assert exc.value.detail["code"] == lcw.CONCLUSION_REVISION_IN_PROGRESS


def test_concurrent_revision_creation(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC34")
    svc, c, ex = _issue(client, db, ctx, number="X-34", joint="J-34")
    cid, version, otk = c.id, c.version, ctx.otk.id

    def attempt(_: int) -> str:
        session = SessionLocal()
        try:
            rev = LaboratoryConclusionRevisionService(session)
            try:
                rev.create_revision(
                    cid, correction_reason="гонка", expected_version=version,
                    actor_worker_id=otk,
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001
                d = getattr(exc, "detail", None)
                return d.get("code", "ERR") if isinstance(d, dict) else "ERR"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("ok") == 1
    assert len(
        ExecutionRepo(db).list_conclusion_revisions(c.root_conclusion_id)
    ) == 2


# ── Review required (35–38) ─────────────────────────────────────────────────────


def test_execution_supersede_flags_conclusion_review(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "LC35")
    svc, c, ex = _issue(client, db, ctx, number="RR-35", joint="J-35")
    # Создаём и подтверждаем редакцию связанного выполнения → ex становится SUPERSEDED.
    mexec = MethodExecutionService(db)
    mrev = MethodExecutionRevisionService(db)
    new = mrev.create_revision(
        ex.id, correction_reason="исправление выполнения",
        expected_version=ex.version, actor_worker_id=ctx.otk.id,
    )
    new = mexec.start(new.id, new.version, actor_worker_id=ctx.otk.id)
    new = mexec.mark_performed(
        new.id, MarkPerformedInput(expected_version=new.version, performed_date=TODAY),
        actor_worker_id=ctx.otk.id,
    )
    new = mexec.record_result(new.id, new.version, actor_worker_id=ctx.otk.id)
    new = mexec.confirm(
        new.id, ConfirmInput(
            expected_version=new.version, laboratory_evaluation=mew.EVAL_CONFORMING
        ),
        actor_worker_id=ctx.otk.id,
    )
    repo = ExecutionRepo(db)
    reloaded = repo.get_conclusion(c.id)
    # 35 + 36: флаг выставлен, заключение остаётся ISSUED
    assert reloaded.revision_review_required is True
    assert reloaded.revision_review_reason == (
        lcw.REVIEW_REASON_LINKED_EXECUTION_SUPERSEDED
    )
    assert reloaded.status == lcw.CONCLUSION_ISSUED
    # 37: связь по-прежнему на старую редакцию выполнения
    links = repo.list_conclusion_executions(c.id)
    assert [link.method_execution_id for link in links] == [ex.id]
    # 46: audit-событие пересмотра
    events = repo.list_audit_events(mew.AUDIT_ENTITY_CONCLUSION, c.id)
    assert any(
        e.event_type == mew.AUDIT_EVENT_CONCLUSION_REVIEW_REQUIRED for e in events
    )
    # 38: новая редакция заключения может связаться с новой редакцией выполнения
    crev = LaboratoryConclusionRevisionService(db)
    r2 = crev.create_revision(
        c.id, correction_reason="актуализация", expected_version=reloaded.version,
        actor_worker_id=ctx.otk.id,
    )
    svc.remove_execution(r2.id, ex.id, actor_worker_id=ctx.otk.id)
    link = svc.add_execution(r2.id, new.id, actor_worker_id=ctx.otk.id)
    assert link.method_execution_id == new.id


# ── Аккредитация (39–41) ────────────────────────────────────────────────────────


def test_valid_accreditation(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC39")
    acc = _accreditation(db, ctx, ctx.lab, valid_until=date(2027, 12, 31))
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-39")
    c = _create(svc, ctx, accreditation_id=acc.id)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    c = svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    c = svc.approve(
        c.id, ApproveConclusionInput(expected_version=c.version),
        actor_worker_id=ctx.otk.id,
    )
    assert c.accreditation_number_snapshot == "ACC-100"


def test_foreign_lab_accreditation_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "LC40")
    acc = _accreditation(db, ctx, ctx.lab2)  # аккредитация другой лаборатории
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-40")
    c = _create(svc, ctx, accreditation_id=acc.id)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    with pytest.raises(DomainError) as exc:
        svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.ACCREDITATION_LABORATORY_MISMATCH


def test_expired_accreditation_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC41")
    acc = _accreditation(db, ctx, ctx.lab, valid_until=date(2026, 1, 2))
    svc = LaboratoryConclusionService(db)
    ex = _execution(client, db, ctx, "J-41")
    c = _create(svc, ctx, accreditation_id=acc.id)
    svc.add_execution(c.id, ex.id, actor_worker_id=ctx.otk.id)
    with pytest.raises(DomainError) as exc:
        svc.prepare(c.id, c.version, actor_worker_id=ctx.otk.id)
    assert exc.value.detail["code"] == lcw.ACCREDITATION_INVALID


# ── Аудит выпуска и редакции (44–45) ────────────────────────────────────────────


def test_issue_and_revision_audit(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "LC44")
    svc, c, ex = _issue(client, db, ctx, number="AU-44", joint="J-44")
    repo = ExecutionRepo(db)
    ev = {
        e.event_type
        for e in repo.list_audit_events(mew.AUDIT_ENTITY_CONCLUSION, c.id)
    }
    assert mew.AUDIT_EVENT_CONCLUSION_APPROVED in ev
    assert mew.AUDIT_EVENT_CONCLUSION_ISSUED in ev

    rev = LaboratoryConclusionRevisionService(db)
    r2 = rev.create_revision(
        c.id, correction_reason="ревизия", expected_version=c.version,
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.prepare(r2.id, r2.version, actor_worker_id=ctx.otk.id)
    r2 = svc.approve(
        r2.id, ApproveConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    r2 = svc.issue(
        r2.id, IssueConclusionInput(expected_version=r2.version),
        actor_worker_id=ctx.otk.id,
    )
    r2_events = {
        e.event_type
        for e in repo.list_audit_events(mew.AUDIT_ENTITY_CONCLUSION, r2.id)
    }
    assert mew.AUDIT_EVENT_REVISION_CREATED in r2_events
    assert mew.AUDIT_EVENT_CONCLUSION_ISSUED in r2_events
    old_events = {
        e.event_type
        for e in repo.list_audit_events(mew.AUDIT_ENTITY_CONCLUSION, c.id)
    }
    assert mew.AUDIT_EVENT_CONCLUSION_SUPERSEDED in old_events
