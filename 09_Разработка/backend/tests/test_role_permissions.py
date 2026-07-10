"""Проверки scoped role check (Task 1): permissions + HrRepo."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.hr.models import Worker, WorkerRole
from app.hr.repository import HrRepo
from app.hr.schemas import WorkerRoleCreate, WorkerRoleUpdate
from app.hr.services import HrService
from app.shared.errors import ConflictError
from app.shared.permissions import RoleRequirement, check_worker_role, require_worker_role

CHECK_DATE = date(2026, 7, 10)
PROJECT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
OTHER_PROJECT_ID = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
LINE_ID = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")
OTHER_LINE_ID = UUID("8d3e5f12-4a6b-4c8d-9e0f-1a2b3c4d5e6f")


def _create_worker(db: Session, *, suffix: str) -> Worker:
    from .conftest import TEST_COMPANY_ID

    worker = Worker(
        last_name=f"Perm{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=CHECK_DATE,
    )
    db.add(worker)
    db.flush()
    return worker


def _assign_role(
    db: Session,
    *,
    worker_id: int,
    role_code: str,
    scope_type: str = "GLOBAL",
    scope_id: str | None = None,
    is_active: bool = True,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=is_active,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    db.add(role)
    db.flush()
    return role


def test_worker_role_create_accepts_master_and_pto() -> None:
    master = WorkerRoleCreate(role_code="MASTER")
    assert master.role_code == "MASTER"
    pto = WorkerRoleCreate(role_code="PTO_ENGINEER")
    assert pto.role_code == "PTO_ENGINEER"


def test_has_role_global_foreman(db: Session) -> None:
    worker = _create_worker(db, suffix="GlobalForeman")
    _assign_role(db, worker_id=worker.id, role_code="FOREMAN", scope_type="GLOBAL")
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="GLOBAL",
        scope_id=None,
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is True


def test_has_role_project_scope_matches_uuid(db: Session) -> None:
    worker = _create_worker(db, suffix="ProjectForeman")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=str(PROJECT_ID),
    )
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=str(PROJECT_ID),
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is True


def test_has_role_line_scope_matches_uuid(db: Session) -> None:
    worker = _create_worker(db, suffix="LineForeman")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="LINE",
        scope_id=str(LINE_ID),
    )
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="LINE",
        scope_id=str(LINE_ID),
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is True


def test_foreign_project_scope_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="ForeignProject")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=str(PROJECT_ID),
    )
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=str(OTHER_PROJECT_ID),
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_foreign_line_scope_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="ForeignLine")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="LINE",
        scope_id=str(LINE_ID),
    )
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="LINE",
        scope_id=str(OTHER_LINE_ID),
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_inactive_role_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="Inactive")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="GLOBAL",
        is_active=False,
    )
    db.commit()

    requirement = RoleRequirement(role_code="FOREMAN", scope_type="GLOBAL")
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_future_valid_from_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="FutureFrom")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="GLOBAL",
        valid_from=date(2026, 7, 11),
    )
    db.commit()

    requirement = RoleRequirement(role_code="FOREMAN", scope_type="GLOBAL")
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_expired_role_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="Expired")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="GLOBAL",
        valid_to=date(2026, 7, 9),
    )
    db.commit()

    requirement = RoleRequirement(role_code="FOREMAN", scope_type="GLOBAL")
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_role_valid_on_boundary_dates(db: Session) -> None:
    worker = _create_worker(db, suffix="Boundary")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="GLOBAL",
        valid_from=CHECK_DATE,
        valid_to=CHECK_DATE,
    )
    db.commit()

    requirement = RoleRequirement(role_code="FOREMAN", scope_type="GLOBAL")
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is True


def test_wrong_role_code_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="WrongCode")
    _assign_role(db, worker_id=worker.id, role_code="FOREMAN", scope_type="GLOBAL")
    db.commit()

    requirement = RoleRequirement(role_code="MASTER", scope_type="GLOBAL")
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_project_scope_uuid_case_insensitive(db: Session) -> None:
    worker = _create_worker(db, suffix="CaseProject")
    upper = str(PROJECT_ID).upper()
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=upper,
    )
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=str(PROJECT_ID).lower(),
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is True


def test_require_worker_role_raises_403(db: Session) -> None:
    worker = _create_worker(db, suffix="Require403")
    db.commit()

    requirement = RoleRequirement(role_code="FOREMAN", scope_type="GLOBAL")
    with pytest.raises(HTTPException) as exc_info:
        require_worker_role(db, worker.id, requirement, on_date=CHECK_DATE)
    assert exc_info.value.status_code == 403


def test_project_scope_empty_scope_id_rejected(db: Session) -> None:
    worker = _create_worker(db, suffix="EmptyScope")
    _assign_role(
        db,
        worker_id=worker.id,
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=str(PROJECT_ID),
    )
    db.commit()

    requirement = RoleRequirement(
        role_code="FOREMAN",
        scope_type="PROJECT",
        scope_id=None,
    )
    assert check_worker_role(db, worker.id, requirement, on_date=CHECK_DATE) is False


def test_hr_repo_has_active_worker_role_unchanged_for_welding(db: Session) -> None:
    worker = _create_worker(db, suffix="WelderRole")
    _assign_role(db, worker_id=worker.id, role_code="WELDER", scope_type="GLOBAL")
    db.commit()

    repo = HrRepo(db)
    assert repo.has_active_worker_role(worker.id, "WELDER") is True
    assert repo.has_active_worker_role(worker.id, "FOREMAN") is False


# --- HrService: валидация scope_id (Task 1, синхронизация со схемами/моделью) ---


def _service_worker(db: Session, *, suffix: str) -> Worker:
    worker = _create_worker(db, suffix=suffix)
    db.commit()
    return worker


def test_service_assign_project_role_with_uuid_string(db: Session) -> None:
    """(1) PROJECT-роль со строковым UUID scope_id проходит и хранится канонично."""
    worker = _service_worker(db, suffix="SvcProject")
    service = HrService(db)

    role = service.assign_worker_role(
        worker.id,
        WorkerRoleCreate(
            role_code="FOREMAN",
            scope_type="PROJECT",
            scope_id=str(PROJECT_ID),
        ),
    )

    assert role.scope_type == "PROJECT"
    assert role.scope_id == str(PROJECT_ID)


def test_service_assign_line_role_with_uuid_string(db: Session) -> None:
    """(2) LINE-роль со строковым UUID scope_id проходит и хранится канонично."""
    worker = _service_worker(db, suffix="SvcLine")
    service = HrService(db)

    role = service.assign_worker_role(
        worker.id,
        WorkerRoleCreate(
            role_code="FOREMAN",
            scope_type="LINE",
            scope_id=str(LINE_ID),
        ),
    )

    assert role.scope_type == "LINE"
    assert role.scope_id == str(LINE_ID)


def test_service_assign_project_role_normalizes_uppercase_uuid(db: Session) -> None:
    """(1) UUID нормализуется через uuid.UUID(...) в канонический строковый вид."""
    worker = _service_worker(db, suffix="SvcNorm")
    service = HrService(db)

    role = service.assign_worker_role(
        worker.id,
        WorkerRoleCreate(
            role_code="FOREMAN",
            scope_type="PROJECT",
            scope_id=str(PROJECT_ID).upper(),
        ),
    )

    assert role.scope_id == str(PROJECT_ID)


@pytest.mark.parametrize("scope_type", ["PROJECT", "LINE"])
def test_service_assign_empty_scope_id_rejected(db: Session, scope_type: str) -> None:
    """(3) PROJECT/LINE с пустым scope_id отклоняется."""
    worker = _service_worker(db, suffix=f"SvcEmpty{scope_type}")
    service = HrService(db)

    with pytest.raises(ConflictError):
        service.assign_worker_role(
            worker.id,
            WorkerRoleCreate(
                role_code="FOREMAN",
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id="",
            ),
        )


@pytest.mark.parametrize("scope_type", ["PROJECT", "LINE"])
def test_service_assign_invalid_uuid_rejected(db: Session, scope_type: str) -> None:
    """(4) PROJECT/LINE с невалидным UUID отклоняется."""
    worker = _service_worker(db, suffix=f"SvcBad{scope_type}")
    service = HrService(db)

    with pytest.raises(ConflictError):
        service.assign_worker_role(
            worker.id,
            WorkerRoleCreate(
                role_code="FOREMAN",
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id="not-a-uuid",
            ),
        )


def test_service_assign_global_with_scope_id_rejected(db: Session) -> None:
    """(5) GLOBAL с заполненным scope_id отклоняется."""
    worker = _service_worker(db, suffix="SvcGlobalScope")
    service = HrService(db)

    with pytest.raises(ConflictError):
        service.assign_worker_role(
            worker.id,
            WorkerRoleCreate(
                role_code="FOREMAN",
                scope_type="GLOBAL",
                scope_id=str(PROJECT_ID),
            ),
        )


def test_service_assign_pto_engineer_accepted(db: Session) -> None:
    """(6) Существующий технический role_code PTO_ENGINEER принимается."""
    worker = _service_worker(db, suffix="SvcPto")
    service = HrService(db)

    role = service.assign_worker_role(
        worker.id,
        WorkerRoleCreate(role_code="PTO_ENGINEER", scope_type="GLOBAL"),
    )

    assert role.role_code == "PTO_ENGINEER"


def test_worker_role_create_rejects_new_pto_code() -> None:
    """(7) Новый role_code PTO отклоняется схемой (PTO_ENGINEER сохраняется)."""
    with pytest.raises(ValidationError):
        WorkerRoleCreate(role_code="PTO")  # type: ignore[arg-type]


@pytest.mark.parametrize("scope_type", ["PROJECT", "LINE"])
def test_service_assign_integer_scope_id_rejected(db: Session, scope_type: str) -> None:
    """(8) INTEGER scope_id для PROJECT/LINE больше не канонический вход."""
    worker = _service_worker(db, suffix=f"SvcInt{scope_type}")
    service = HrService(db)

    with pytest.raises(ConflictError):
        service.assign_worker_role(
            worker.id,
            WorkerRoleCreate(
                role_code="FOREMAN",
                scope_type=scope_type,  # type: ignore[arg-type]
                scope_id="123",
            ),
        )


def test_service_update_role_normalizes_scope_id(db: Session) -> None:
    """update тоже нормализует UUID и не оставляет int | None для scope_id."""
    worker = _service_worker(db, suffix="SvcUpdate")
    service = HrService(db)
    role = service.assign_worker_role(
        worker.id,
        WorkerRoleCreate(
            role_code="FOREMAN",
            scope_type="PROJECT",
            scope_id=str(PROJECT_ID),
        ),
    )

    updated = service.update_worker_role(
        worker.id,
        role.id,
        WorkerRoleUpdate(scope_id=str(OTHER_PROJECT_ID).upper()),
    )

    assert updated.scope_id == str(OTHER_PROJECT_ID)


def test_service_update_role_invalid_uuid_rejected(db: Session) -> None:
    """update PROJECT/LINE с невалидным UUID отклоняется."""
    worker = _service_worker(db, suffix="SvcUpdateBad")
    service = HrService(db)
    role = service.assign_worker_role(
        worker.id,
        WorkerRoleCreate(
            role_code="FOREMAN",
            scope_type="LINE",
            scope_id=str(LINE_ID),
        ),
    )

    with pytest.raises(ConflictError):
        service.update_worker_role(
            worker.id,
            role.id,
            WorkerRoleUpdate(scope_id="not-a-uuid"),
        )
