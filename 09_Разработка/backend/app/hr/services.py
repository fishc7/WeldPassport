from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.hr.models import Department, Position, Worker
from app.hr.repository import HrRepo
from app.hr.schemas import (
    CompanyRef,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    PositionCreate,
    PositionOut,
    PositionUpdate,
    WorkerCard,
    WorkerCreate,
    WorkerDismiss,
    WorkerListFilters,
    WorkerOut,
    WorkerUpdate,
)
from app.shared.errors import ConflictError, NotFoundError


def to_worker_out(worker: Worker) -> WorkerOut:
    return WorkerOut.model_validate(worker)


def to_worker_card(worker: Worker) -> WorkerCard:
    return WorkerCard(
        **to_worker_out(worker).model_dump(),
        department=(
            DepartmentOut.model_validate(worker.department)
            if worker.department
            else None
        ),
        position=(
            PositionOut.model_validate(worker.position) if worker.position else None
        ),
        company=CompanyRef(id=worker.company_id),
    )


class HrService:
    def __init__(self, db: Session) -> None:
        self._repo = HrRepo(db)

    # --- departments ---

    def list_departments(
        self,
        *,
        company_id: int | None = None,
        is_active: bool | None = True,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Department]:
        return self._repo.list_departments(
            company_id=company_id,
            is_active=is_active,
            skip=skip,
            limit=limit,
        )

    def create_department(self, data: DepartmentCreate) -> Department:
        department = Department(**data.model_dump())
        try:
            return self._repo.create_department(department)
        except IntegrityError as exc:
            raise ConflictError(
                "Подразделение с таким code уже существует в организации"
            ) from exc

    def update_department(
        self, department_id: int, data: DepartmentUpdate
    ) -> Department:
        department = self._get_department(department_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(department, field, value)
        try:
            return self._repo.save_department(department)
        except IntegrityError as exc:
            raise ConflictError(
                "Подразделение с таким code уже существует в организации"
            ) from exc

    # --- positions ---

    def list_positions(
        self,
        *,
        is_active: bool | None = True,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Position]:
        return self._repo.list_positions(is_active=is_active, skip=skip, limit=limit)

    def create_position(self, data: PositionCreate) -> Position:
        position = Position(**data.model_dump())
        try:
            return self._repo.create_position(position)
        except IntegrityError as exc:
            raise ConflictError("Должность с таким code уже существует") from exc

    def update_position(self, position_id: int, data: PositionUpdate) -> Position:
        position = self._get_position(position_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(position, field, value)
        try:
            return self._repo.save_position(position)
        except IntegrityError as exc:
            raise ConflictError("Должность с таким code уже существует") from exc

    # --- workers ---

    def list_workers(self, filters: WorkerListFilters) -> list[Worker]:
        return self._repo.list_workers(filters)

    def get_worker(self, worker_id: int) -> Worker:
        worker = self._repo.get_worker(worker_id)
        if worker is None:
            raise NotFoundError("Работник", worker_id)
        return worker

    def create_worker(self, data: WorkerCreate) -> Worker:
        self._validate_worker_refs(
            company_id=data.company_id,
            department_id=data.department_id,
            position_id=data.position_id,
        )
        worker = Worker(
            personnel_number=data.personnel_number,
            last_name=data.last_name.strip(),
            first_name=data.first_name.strip(),
            middle_name=data.middle_name.strip() if data.middle_name else None,
            birth_date=data.birth_date,
            company_id=data.company_id,
            department_id=data.department_id,
            position_id=data.position_id,
            hire_date=data.hire_date,
            phone=data.phone,
            email=data.email,
            note=data.note,
            employment_status="active",
        )
        try:
            return self._repo.create_worker(worker)
        except IntegrityError as exc:
            raise ConflictError(
                "Табельный номер уже занят в этой организации"
            ) from exc

    def update_worker(self, worker_id: int, data: WorkerUpdate) -> Worker:
        worker = self.get_worker(worker_id)
        payload = data.model_dump(exclude_unset=True)
        for name_field in ("last_name", "first_name", "middle_name"):
            if name_field in payload and payload[name_field] is not None:
                payload[name_field] = payload[name_field].strip()

        company_id = payload.get("company_id", worker.company_id)
        department_id = payload.get("department_id", worker.department_id)
        position_id = payload.get("position_id", worker.position_id)
        self._validate_worker_refs(
            company_id=company_id,
            department_id=department_id,
            position_id=position_id,
        )

        if worker.employment_status != "dismissed" and "dismissal_date" in payload:
            payload.pop("dismissal_date", None)

        for field, value in payload.items():
            setattr(worker, field, value)
        try:
            return self._repo.save_worker(worker)
        except IntegrityError as exc:
            raise ConflictError(
                "Табельный номер уже занят в этой организации"
            ) from exc

    def dismiss_worker(self, worker_id: int, data: WorkerDismiss) -> Worker:
        worker = self.get_worker(worker_id)
        if worker.employment_status == "dismissed":
            raise ConflictError("Работник уже уволен (dismissed)")
        worker.employment_status = "dismissed"
        worker.dismissal_date = data.dismissal_date or date.today()
        if data.note is not None:
            worker.note = data.note
        return self._repo.save_worker(worker)

    def activate_worker(self, worker_id: int) -> Worker:
        worker = self.get_worker(worker_id)
        worker.employment_status = "active"
        worker.dismissal_date = None
        return self._repo.save_worker(worker)

    def _get_department(self, department_id: int) -> Department:
        department = self._repo.get_department(department_id)
        if department is None:
            raise NotFoundError("Подразделение", department_id)
        return department

    def _get_position(self, position_id: int) -> Position:
        position = self._repo.get_position(position_id)
        if position is None:
            raise NotFoundError("Должность", position_id)
        return position

    def _validate_worker_refs(
        self,
        *,
        company_id: int,
        department_id: int | None,
        position_id: int | None,
    ) -> None:
        if company_id <= 0:
            raise ConflictError("company_id должен быть положительным")

        if department_id is not None:
            department = self._get_department(department_id)
            if department.company_id != company_id:
                raise ConflictError(
                    "Подразделение принадлежит другой организации (company_id)"
                )
            if not department.is_active:
                raise ConflictError("Подразделение неактивно")

        if position_id is not None:
            position = self._get_position(position_id)
            if not position.is_active:
                raise ConflictError("Должность неактивна")
