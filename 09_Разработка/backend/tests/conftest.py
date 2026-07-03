"""Фикстуры интеграционных тестов backend (PostgreSQL)."""

from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.hr.models import Worker, WorkerRole
from app.main import app
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


@pytest.fixture(autouse=True)
def _cleanup_test_data(db: Session) -> Generator[None, None, None]:
    worker_ids = [
        row[0]
        for row in db.query(Worker.id)
        .filter(Worker.company_id == TEST_COMPANY_ID)
        .all()
    ]
    if worker_ids:
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
    yield
    worker_ids = [
        row[0]
        for row in db.query(Worker.id)
        .filter(Worker.company_id == TEST_COMPANY_ID)
        .all()
    ]
    if worker_ids:
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
