"""Фикстуры интеграционных тестов backend (PostgreSQL)."""

from collections.abc import Generator
from datetime import date
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_
from sqlalchemy.orm import Session

# Импортируем первым, до app.main: там регистрируется legacy app.workforce.models
# (schema=POSTGRES_SCHEMA, обычно "test"), что иначе загрязняет Base.metadata до
# проверки validate_canonical_metadata() и валит её на схеме "test". Сам workforce
# не трогаем (ADR-005, legacy) — только порядок импорта в тестовом бутстрапе.
import app.shared.canonical_metadata  # noqa: F401

from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    HeatTreatmentBatch,
    HeatTreatmentDeviation,
    HeatTreatmentOperation,
    HeatTreatmentProcedureRevision,
    HeatTreatmentRecord,
    Joint,
    JointBlock,
    JointBulkRequest,
    JointDocumentRevision,
    JointEvent,
    JointSequence,
    WeldOperation,
    WeldOperationCorrection,
    WeldOperationOgsReview,
    WeldOperationWelderConfirmation,
)
from app.engineering.import_models import ImportSession
from app.hr.models import Worker, WorkerRole
from app.main import app
from app.projects.models import Company, Line, Project, ProjectCompany
from app.quality.models import (
    Defect,
    DefectDisposition,
    DefectDispositionEvent,
    DefectEvent,
    DefectRoot,
    DefectSequence,
    Inspection,
    InspectionEvent,
    InspectionMethodAssignment,
    InspectionSequence,
    LaboratoryAccreditation,
    EngineeringEvaluation,
    EngineeringEvaluationCriterion,
    EngineeringEvaluationEvent,
    EngineeringEvaluationRevision,
    EngineeringEvaluationSequence,
    EngineeringEvaluationSource,
    EngineeringException,
    LaboratoryConclusion,
    LaboratoryConclusionExecution,
    MethodExecution,
    MethodExecutionParticipant,
    MethodExecutionResultItem,
    MethodExecutionStandard,
    QualityAuditEvent,
    QualityDecision,
    QualityDecisionBasis,
    QualityDecisionSequence,
    QualityExternalPerson,
    QualityFinding,
    QualityFindingEvent,
    QualityFindingSequence,
)
from app.shared.config import settings
from app.shared.db import SessionLocal, get_db
from app.welding.models import Welder, WelderAdmission
from tests.test_db_safety import assert_safe_test_database

API_PREFIX = "/api/v1/ogs/welders"
AUTH_HEADERS = {"X-User-Id": "1"}
TEST_COMPANY_ID = 99_999


@pytest.fixture(scope="session")
def _test_database_safety_interlock() -> None:
    assert_safe_test_database(
        settings.postgres_db,
        destructive_opt_in=os.getenv("WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS"),
        confirmed_database_name=os.getenv("WELDPASSPORT_TEST_DB_CONFIRM"),
    )


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(_test_database_safety_interlock: None) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_worker(db: Session, *, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Тестов{suffix}",
        first_name="Иван",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=date.today(),
    )
    db.add(worker)
    db.flush()
    return worker


def _assign_welder_role(db: Session, worker_id: int) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code="WELDER",
        scope_type="GLOBAL",
        is_active=True,
        valid_from=date.today(),
    )
    db.add(role)
    db.flush()
    return role


@pytest.fixture
def worker_with_welder_role(db: Session) -> Worker:
    worker = _create_worker(db, suffix="Welder")
    _assign_welder_role(db, worker.id)
    db.commit()
    db.refresh(worker)
    return worker


@pytest.fixture
def worker_without_welder_role(db: Session) -> Worker:
    worker = _create_worker(db, suffix="NoRole")
    db.commit()
    db.refresh(worker)
    return worker


@pytest.fixture
def active_worker(db: Session) -> Worker:
    """Активный работник — валидный X-User-Id для изменяющих endpoints projects."""
    worker = _create_worker(db, suffix="ProjActive")
    db.commit()
    db.refresh(worker)
    return worker


@pytest.fixture
def inactive_worker(db: Session) -> Worker:
    """Уволенный работник — не имеет права создавать Company/Project (403)."""
    worker = _create_worker(db, suffix="ProjDismissed")
    worker.employment_status = "dismissed"
    worker.dismissal_date = date.today()
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


@pytest.fixture
def worker_with_welder_profile(db: Session, worker_with_welder_role: Worker) -> Worker:
    """Работник с ролью WELDER и оформленным профилем сварщика ОГС."""
    welder = Welder(
        worker_id=worker_with_welder_role.id,
        stamp_code="W-001",
        status="active",
    )
    db.add(welder)
    db.commit()
    db.refresh(worker_with_welder_role)
    return worker_with_welder_role


def create_welder_profile(db: Session, worker_id: int, stamp_code: str) -> Welder:
    welder = Welder(
        worker_id=worker_id,
        stamp_code=stamp_code,
        status="active",
    )
    db.add(welder)
    db.flush()
    return welder


def _purge_test_data(db: Session) -> None:
    """Удаляет тестовые данные: сначала project (по created_by = тестовый worker),
    затем welding/hr. Порядок учитывает FK. Данные projects помечены created_by,
    равным id тестовых workers (TEST_COMPANY_ID)."""
    worker_ids = [
        row[0]
        for row in db.query(Worker.id)
        .filter(Worker.company_id == TEST_COMPANY_ID)
        .all()
    ]
    if not worker_ids:
        return

    # DefectDisposition (Task 9D-4A) удаляем ДО DefectRoot: FK
    # defect_dispositions.defect_root_id → defect_roots RESTRICT;
    # events → dispositions RESTRICT. Порядок: events → dispositions (self-FK
    # supersedes обнуляем) → затем Defect/Root ниже.
    disposition_ids = [
        row[0]
        for row in db.query(DefectDisposition.id)
        .filter(DefectDisposition.created_by_worker_id.in_(worker_ids))
        .all()
    ]
    if disposition_ids:
        db.query(DefectDispositionEvent).filter(
            DefectDispositionEvent.defect_disposition_id.in_(disposition_ids)
        ).delete(synchronize_session=False)
        db.query(DefectDisposition).filter(
            DefectDisposition.id.in_(disposition_ids)
        ).update(
            {DefectDisposition.supersedes_disposition_id: None},
            synchronize_session=False,
        )
        db.query(DefectDisposition).filter(
            DefectDisposition.id.in_(disposition_ids)
        ).delete(synchronize_session=False)

    # Defect (Task 9D-3A) удаляем ДО EngineeringEvaluation: FK
    # defect_roots.engineering_evaluation_id → engineering_evaluations RESTRICT и
    # defect_roots.joint_id → joints RESTRICT. Порядок дети → родители: events →
    # defects (self-FK supersedes_defect_id RESTRICT — обнуляем) → roots.
    # defect_sequences (joint_id CASCADE) уходят со стыками ниже, но чистим явно.
    defect_ids = [
        row[0]
        for row in db.query(Defect.id)
        .filter(Defect.created_by_worker_id.in_(worker_ids))
        .all()
    ]
    if defect_ids:
        db.query(DefectEvent).filter(
            DefectEvent.defect_id.in_(defect_ids)
        ).delete(synchronize_session=False)
        db.query(Defect).filter(Defect.id.in_(defect_ids)).update(
            {Defect.supersedes_defect_id: None}, synchronize_session=False
        )
        db.query(Defect).filter(Defect.id.in_(defect_ids)).delete(
            synchronize_session=False
        )
    db.query(DefectRoot).filter(
        DefectRoot.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)

    # QualityDecision (Task 10A) удаляем ДО EngineeringEvaluationRevision/Joint: FK
    # quality_decision_bases.engineering_evaluation_revision_id →
    # engineering_evaluation_revisions RESTRICT и quality_decisions.joint_id → joints
    # RESTRICT. Порядок: idempotency → bases → self-FK
    # supersedes_quality_decision_id (обнуляем) →
    # decisions. quality_audit_events по QualityDecision уже покрыты общей чисткой
    # QualityAuditEvent по actor_worker_id ниже (полиморфный журнал, без FK).
    qd_ids = [
        row[0]
        for row in db.query(QualityDecision.id)
        .filter(QualityDecision.created_by_worker_id.in_(worker_ids))
        .all()
    ]
    if qd_ids:
        from app.quality.quality_decision_models import (
            QualityDecisionIdempotencyRecord,
        )

        db.query(QualityDecisionIdempotencyRecord).filter(
            QualityDecisionIdempotencyRecord.quality_decision_id.in_(qd_ids)
        ).delete(synchronize_session=False)
        db.query(QualityDecisionBasis).filter(
            QualityDecisionBasis.quality_decision_id.in_(qd_ids)
        ).delete(synchronize_session=False)
        db.query(QualityDecision).filter(QualityDecision.id.in_(qd_ids)).update(
            {QualityDecision.supersedes_quality_decision_id: None},
            synchronize_session=False,
        )
        db.query(QualityDecision).filter(QualityDecision.id.in_(qd_ids)).delete(
            synchronize_session=False
        )

    # EngineeringEvaluation (Task 9D-2A) удаляем ДО finding: FK
    # engineering_evaluations.finding_id → quality_findings RESTRICT. Порядок дети →
    # родители: events → exceptions → criteria → sources → revisions → evaluations.
    # sequences чистятся по project_id ниже. Указатели current/effective_revision_id —
    # без FK, спец-обнуление не нужно.
    db.query(EngineeringEvaluationEvent).filter(
        EngineeringEvaluationEvent.actor_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(EngineeringException).filter(
        EngineeringException.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(EngineeringEvaluationCriterion).filter(
        EngineeringEvaluationCriterion.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(EngineeringEvaluationSource).filter(
        EngineeringEvaluationSource.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(EngineeringEvaluationRevision).filter(
        EngineeringEvaluationRevision.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(EngineeringEvaluation).filter(
        EngineeringEvaluation.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)

    # QualityFinding (Task 9D-1) удаляем раньше всего: FK quality.quality_findings
    # → inspections / method_executions / weld_operations / joints / projects c
    # RESTRICT. Journal → findings c RESTRICT. Finding помечены created_by_worker_id
    # тестовых workers; finding_sequences чистятся по project_id ниже.
    finding_ids = [
        row[0]
        for row in db.query(QualityFinding.id)
        .filter(QualityFinding.created_by_worker_id.in_(worker_ids))
        .all()
    ]
    if finding_ids:
        db.query(QualityFindingEvent).filter(
            QualityFindingEvent.finding_id.in_(finding_ids)
        ).delete(synchronize_session=False)
        db.query(QualityFinding).filter(
            QualityFinding.id.in_(finding_ids)
        ).delete(synchronize_session=False)

    # Выполнение метода и заключения (Task 9C) удаляем раньше всего: их таблицы
    # ссылаются на назначения (RESTRICT), стыки/проекты/компании (RESTRICT) и
    # method_executions (RESTRICT). Порядок — дети → родители; фильтр по
    # created_by_worker_id (audit — по actor_worker_id) тестовых workers. Self-FK
    # supersedes_* — SET NULL, спец-обнуление не нужно.
    db.query(QualityAuditEvent).filter(
        QualityAuditEvent.actor_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(LaboratoryConclusionExecution).filter(
        LaboratoryConclusionExecution.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(MethodExecutionParticipant).filter(
        MethodExecutionParticipant.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(MethodExecutionResultItem).filter(
        MethodExecutionResultItem.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(MethodExecutionStandard).filter(
        MethodExecutionStandard.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(LaboratoryConclusion).filter(
        LaboratoryConclusion.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(MethodExecution).filter(
        MethodExecution.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(LaboratoryAccreditation).filter(
        LaboratoryAccreditation.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(QualityExternalPerson).filter(
        QualityExternalPerson.created_by_worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)

    # Заявки на контроль (Task 9A) удаляем первыми: FK quality.inspections →
    # engineering.joints и project.projects c RESTRICT, quality.inspection_events
    # → quality.inspections c RESTRICT. Заявки помечены created_by_worker_id
    # тестовых workers; счётчики inspection_sequences чистятся по project_id ниже.
    inspection_ids = [
        row[0]
        for row in db.query(Inspection.id)
        .filter(Inspection.created_by_worker_id.in_(worker_ids))
        .all()
    ]
    if inspection_ids:
        # Назначения методов (Task 9B): FK inspection_method_assignments →
        # inspections c RESTRICT — удаляем раньше заявок. Self-FK
        # replaced_by_assignment_id — SET NULL, поэтому спец-обнуление не нужно.
        db.query(InspectionMethodAssignment).filter(
            InspectionMethodAssignment.inspection_id.in_(inspection_ids)
        ).delete(synchronize_session=False)
        db.query(InspectionEvent).filter(
            InspectionEvent.inspection_id.in_(inspection_ids)
        ).delete(synchronize_session=False)
        db.query(Inspection).filter(Inspection.id.in_(inspection_ids)).delete(
            synchronize_session=False
        )

    # Термообработка (Task 8F) удаляем раньше стыков/сварочных операций/проектов:
    # FK heat_treatment_operations → joints/weld_operations и heat_treatment_*
    # → heat_treatment_batches/procedure_revisions c RESTRICT. Циклы помечены
    # created_by тестовых workers.
    ht_batch_ids = [
        row[0]
        for row in db.query(HeatTreatmentBatch.id)
        .filter(HeatTreatmentBatch.created_by.in_(worker_ids))
        .all()
    ]
    if ht_batch_ids:
        db.query(HeatTreatmentDeviation).filter(
            HeatTreatmentDeviation.batch_id.in_(ht_batch_ids)
        ).delete(synchronize_session=False)
        db.query(HeatTreatmentRecord).filter(
            HeatTreatmentRecord.batch_id.in_(ht_batch_ids)
        ).delete(synchronize_session=False)
        # Самоссылку previous обнуляем (RESTRICT), reason сбрасываем на
        # AFTER_INITIAL_WELD: обнуление previous у REPEAT_AFTER_REJECTION иначе
        # нарушило бы CHECK repeat_previous (данные удаляются).
        db.query(HeatTreatmentOperation).filter(
            HeatTreatmentOperation.batch_id.in_(ht_batch_ids)
        ).update(
            {
                HeatTreatmentOperation.previous_heat_treatment_operation_id: None,
                HeatTreatmentOperation.reason: "AFTER_INITIAL_WELD",
            },
            synchronize_session=False,
        )
        db.query(HeatTreatmentOperation).filter(
            HeatTreatmentOperation.batch_id.in_(ht_batch_ids)
        ).delete(synchronize_session=False)
        db.query(HeatTreatmentBatch).filter(
            HeatTreatmentBatch.id.in_(ht_batch_ids)
        ).delete(synchronize_session=False)
    db.query(HeatTreatmentProcedureRevision).filter(
        HeatTreatmentProcedureRevision.created_by.in_(worker_ids)
    ).delete(synchronize_session=False)

    # Импорт (Task 8E) удаляем первым: import_provenance/rows/groups/resolutions
    # ссылаются на joints/weld_operations c RESTRICT, но каскадятся от
    # import_sessions. Сессии помечены uploaded_by тестовых workers.
    db.query(ImportSession).filter(
        ImportSession.uploaded_by.in_(worker_ids)
    ).delete(synchronize_session=False)

    # Сварочные операции (Task 8A) удаляем раньше стыков и профилей сварщиков:
    # FK engineering.weld_operations → engineering.joints и welding.welders c
    # ondelete RESTRICT. Операции помечены created_by тестовых workers. Историю
    # решений Task 8C (confirmation/review) удаляем первой: FK → weld_operations.
    operation_ids = [
        row[0]
        for row in db.query(WeldOperation.id)
        .filter(WeldOperation.created_by.in_(worker_ids))
        .all()
    ]
    if operation_ids:
        db.query(WeldOperationWelderConfirmation).filter(
            WeldOperationWelderConfirmation.weld_operation_id.in_(operation_ids)
        ).delete(synchronize_session=False)
        db.query(WeldOperationOgsReview).filter(
            WeldOperationOgsReview.weld_operation_id.in_(operation_ids)
        ).delete(synchronize_session=False)
        # Корректировки (Task 8D) ссылаются на source/replacement операции c
        # RESTRICT — удаляем раньше самих операций. Self-FK замены (supersedes/
        # superseded_by) обнуляем, иначе RESTRICT блокирует удаление.
        db.query(WeldOperationCorrection).filter(
            WeldOperationCorrection.source_operation_id.in_(operation_ids)
        ).delete(synchronize_session=False)
        # operation_kind сбрасываем на STANDARD вместе с обнулением ссылок: у REWELD
        # обнуление supersedes нарушило бы CHECK reweld_required (данные удаляются).
        db.query(WeldOperation).filter(
            WeldOperation.id.in_(operation_ids)
        ).update(
            {
                WeldOperation.supersedes_operation_id: None,
                WeldOperation.superseded_by_operation_id: None,
                WeldOperation.operation_kind: "STANDARD",
            },
            synchronize_session=False,
        )
    db.query(WeldOperation).filter(
        WeldOperation.created_by.in_(worker_ids)
    ).delete(synchronize_session=False)

    project_ids = [
        row[0]
        for row in db.query(Project.id)
        .filter(Project.created_by.in_(worker_ids))
        .all()
    ]
    company_ids = [
        row[0]
        for row in db.query(Company.id)
        .filter(Company.created_by.in_(worker_ids))
        .all()
    ]

    # Стыки удаляем раньше ревизий/линий/проектов: FK engineering.joints →
    # project.* и engineering.document_revisions c ondelete RESTRICT. Стыки
    # помечены created_by тестовых workers. Счётчики last_value чистим по
    # project_id, чтобы не оставлять сирот.
    joint_ids = [
        row[0]
        for row in db.query(Joint.id)
        .filter(Joint.created_by.in_(worker_ids))
        .all()
    ]
    if joint_ids:
        # События, блокировки и связи ревизий (Task 5B/6) ссылаются на joints c
        # RESTRICT — удаляем раньше. Самоссылку supersede обнуляем, иначе RESTRICT
        # блокирует удаление.
        db.query(JointEvent).filter(JointEvent.joint_id.in_(joint_ids)).delete(
            synchronize_session=False
        )
        db.query(JointBlock).filter(JointBlock.joint_id.in_(joint_ids)).delete(
            synchronize_session=False
        )
        db.query(JointDocumentRevision).filter(
            JointDocumentRevision.joint_id.in_(joint_ids)
        ).delete(synchronize_session=False)
        # Defect per-joint счётчики (Task 9D-3A): joint_id CASCADE, но чистим явно
        # (как прочие *_sequences), чтобы не полагаться только на каскад.
        db.query(DefectSequence).filter(
            DefectSequence.joint_id.in_(joint_ids)
        ).delete(synchronize_session=False)
        db.query(Joint).filter(Joint.id.in_(joint_ids)).update(
            {Joint.superseded_by_joint_id: None}, synchronize_session=False
        )
    db.query(Joint).filter(Joint.created_by.in_(worker_ids)).delete(
        synchronize_session=False
    )
    if project_ids:
        # Идемпотентные bulk-запросы (Task 7): FK project_id → projects RESTRICT,
        # удаляем раньше проектов.
        db.query(JointBulkRequest).filter(
            JointBulkRequest.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.query(JointSequence).filter(
            JointSequence.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.query(InspectionSequence).filter(
            InspectionSequence.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.query(QualityFindingSequence).filter(
            QualityFindingSequence.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.query(EngineeringEvaluationSequence).filter(
            EngineeringEvaluationSequence.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.query(QualityDecisionSequence).filter(
            QualityDecisionSequence.project_id.in_(project_ids)
        ).delete(synchronize_session=False)

    # Инженерные документы/ревизии удаляем раньше линий и проектов:
    # FK engineering.* → project.* c ondelete RESTRICT. Документы помечены
    # created_by тестовых workers.
    document_ids = [
        row[0]
        for row in db.query(EngineeringDocument.id)
        .filter(EngineeringDocument.created_by.in_(worker_ids))
        .all()
    ]
    if document_ids:
        db.query(DocumentRevision).filter(
            DocumentRevision.engineering_document_id.in_(document_ids)
        ).delete(synchronize_session=False)
        db.query(EngineeringDocument).filter(
            EngineeringDocument.id.in_(document_ids)
        ).delete(synchronize_session=False)

    if project_ids or company_ids:
        conditions = []
        if project_ids:
            conditions.append(ProjectCompany.project_id.in_(project_ids))
        if company_ids:
            conditions.append(ProjectCompany.company_id.in_(company_ids))
        db.query(ProjectCompany).filter(or_(*conditions)).delete(
            synchronize_session=False
        )
    if project_ids:
        # Линии удаляем раньше проектов: FK project.lines → projects RESTRICT.
        db.query(Line).filter(Line.project_id.in_(project_ids)).delete(
            synchronize_session=False
        )
        db.query(Project).filter(Project.id.in_(project_ids)).delete(
            synchronize_session=False
        )
    if company_ids:
        db.query(Company).filter(Company.id.in_(company_ids)).delete(
            synchronize_session=False
        )

    db.query(WelderAdmission).filter(
        WelderAdmission.worker_id.in_(worker_ids)
    ).delete(synchronize_session=False)
    db.query(Welder).filter(Welder.worker_id.in_(worker_ids)).delete(
        synchronize_session=False
    )
    db.query(WorkerRole).filter(WorkerRole.worker_id.in_(worker_ids)).delete(
        synchronize_session=False
    )
    db.query(Worker).filter(Worker.id.in_(worker_ids)).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture(autouse=True)
def _cleanup_test_data(db: Session) -> Generator[None, None, None]:
    _purge_test_data(db)
    yield
    _purge_test_data(db)
