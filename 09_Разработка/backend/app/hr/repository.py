from datetime import date

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.hr.models import Department, Position, Worker, WorkerRole
from app.hr.schemas import WorkerListFilters


class HrRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- departments ---

    def list_departments(
        self,
        *,
        company_id: int | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Department]:
        q = self.db.query(Department)
        if company_id is not None:
            q = q.filter(Department.company_id == company_id)
        if is_active is not None:
            q = q.filter(Department.is_active == is_active)
        return q.order_by(Department.name).offset(skip).limit(limit).all()

    def get_department(self, department_id: int) -> Department | None:
        return self.db.query(Department).filter(Department.id == department_id).first()

    def create_department(self, department: Department) -> Department:
        self.db.add(department)
        self.db.commit()
        self.db.refresh(department)
        return department

    def save_department(self, department: Department) -> Department:
        self.db.commit()
        self.db.refresh(department)
        return department

    # --- positions ---

    def list_positions(
        self,
        *,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Position]:
        q = self.db.query(Position)
        if is_active is not None:
            q = q.filter(Position.is_active == is_active)
        return q.order_by(Position.name).offset(skip).limit(limit).all()

    def get_position(self, position_id: int) -> Position | None:
        return self.db.query(Position).filter(Position.id == position_id).first()

    def create_position(self, position: Position) -> Position:
        self.db.add(position)
        self.db.commit()
        self.db.refresh(position)
        return position

    def save_position(self, position: Position) -> Position:
        self.db.commit()
        self.db.refresh(position)
        return position

    # --- workers ---

    def list_workers(self, filters: WorkerListFilters) -> list[Worker]:
        q = (
            self.db.query(Worker)
            .options(joinedload(Worker.department), joinedload(Worker.position))
            .order_by(Worker.last_name, Worker.first_name)
        )
        if filters.company_id is not None:
            q = q.filter(Worker.company_id == filters.company_id)
        if filters.department_id is not None:
            q = q.filter(Worker.department_id == filters.department_id)
        if filters.position_id is not None:
            q = q.filter(Worker.position_id == filters.position_id)
        if filters.employment_status is not None:
            q = q.filter(Worker.employment_status == filters.employment_status)
        if filters.search:
            term = f"%{filters.search.lower()}%"
            full_name = func.lower(
                func.trim(
                    func.concat(
                        Worker.last_name,
                        " ",
                        Worker.first_name,
                        " ",
                        func.coalesce(Worker.middle_name, ""),
                    )
                )
            )
            q = q.filter(
                or_(
                    func.lower(Worker.last_name).like(term),
                    func.lower(Worker.first_name).like(term),
                    func.lower(func.coalesce(Worker.middle_name, "")).like(term),
                    full_name.like(term),
                    func.lower(func.coalesce(Worker.personnel_number, "")).like(term),
                    func.lower(func.coalesce(Worker.phone, "")).like(term),
                    func.lower(func.coalesce(Worker.email, "")).like(term),
                )
            )
        return q.offset(filters.skip).limit(filters.limit).all()

    def get_worker(self, worker_id: int) -> Worker | None:
        return (
            self.db.query(Worker)
            .options(
                joinedload(Worker.department),
                joinedload(Worker.position),
                selectinload(Worker.worker_roles),
            )
            .filter(Worker.id == worker_id)
            .first()
        )

    def create_worker(self, worker: Worker) -> Worker:
        self.db.add(worker)
        self.db.commit()
        result = self.get_worker(worker.id)
        assert result is not None
        return result

    def save_worker(self, worker: Worker) -> Worker:
        self.db.commit()
        result = self.get_worker(worker.id)
        assert result is not None
        return result

    # --- worker roles ---

    def list_worker_roles(self, worker_id: int) -> list[WorkerRole]:
        return (
            self.db.query(WorkerRole)
            .filter(WorkerRole.worker_id == worker_id)
            .order_by(WorkerRole.role_code, WorkerRole.scope_type)
            .all()
        )

    def get_worker_role(self, worker_id: int, role_id: int) -> WorkerRole | None:
        return (
            self.db.query(WorkerRole)
            .filter(WorkerRole.worker_id == worker_id, WorkerRole.id == role_id)
            .first()
        )

    def find_active_role_duplicate(
        self,
        *,
        worker_id: int,
        role_code: str,
        scope_type: str,
        scope_id: str | None,
        exclude_role_id: int | None = None,
    ) -> WorkerRole | None:
        q = self.db.query(WorkerRole).filter(
            WorkerRole.worker_id == worker_id,
            WorkerRole.role_code == role_code,
            WorkerRole.scope_type == scope_type,
            WorkerRole.is_active.is_(True),
        )
        if scope_id is None:
            q = q.filter(WorkerRole.scope_id.is_(None))
        else:
            q = q.filter(WorkerRole.scope_id == scope_id)
        if exclude_role_id is not None:
            q = q.filter(WorkerRole.id != exclude_role_id)
        return q.first()

    def create_worker_role(self, role: WorkerRole) -> WorkerRole:
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def save_worker_role(self, role: WorkerRole) -> WorkerRole:
        self.db.commit()
        self.db.refresh(role)
        return role

    def find_active_roles(
        self,
        *,
        worker_id: int,
        role_code: str,
    ) -> list[WorkerRole]:
        return (
            self.db.query(WorkerRole)
            .filter(
                WorkerRole.worker_id == worker_id,
                WorkerRole.role_code == role_code,
                WorkerRole.is_active.is_(True),
            )
            .all()
        )

    def has_active_worker_role_in_scope(
        self,
        worker_id: int,
        role_code: str,
        scope_type: str,
        scope_id: str | None = None,
        *,
        on_date: date | None = None,
    ) -> bool:
        from app.shared.permissions import RoleRequirement, check_worker_role

        requirement = RoleRequirement(
            role_code=role_code,
            scope_type=scope_type,  # type: ignore[arg-type]
            scope_id=scope_id,
        )
        return check_worker_role(self.db, worker_id, requirement, on_date=on_date)

    def has_active_worker_role(self, worker_id: int, role_code: str) -> bool:
        return (
            self.db.query(WorkerRole)
            .filter(
                WorkerRole.worker_id == worker_id,
                WorkerRole.role_code == role_code,
                WorkerRole.is_active.is_(True),
            )
            .first()
            is not None
        )
