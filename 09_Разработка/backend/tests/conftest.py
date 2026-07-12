"""Фикстуры интеграционных тестов backend (PostgreSQL)."""

from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointBlock,
    JointBulkRequest,
    JointDocumentRevision,
    JointEvent,
    JointSequence,
    WeldOperation,
    WeldOperationOgsReview,
    WeldOperationWelderConfirmation,
)
from app.hr.models import Worker, WorkerRole
from app.main import app
from app.projects.models import Company, Line, Project, ProjectCompany
from app.shared.db import SessionLocal, get_db
from app.welding.models import Welder, WelderAdmission


def _db_available() -> bool:
    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
    finally:
        session.close()


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="PostgreSQL недоступен (проверьте .env и запущенную БД)",
)

API_PREFIX = "/api/v1/ogs/welders"
AUTH_HEADERS = {"X-User-Id": "1"}
TEST_COMPANY_ID = 99_999


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations() -> None:
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
