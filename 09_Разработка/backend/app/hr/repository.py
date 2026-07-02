from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.hr.models import Department, Position, Worker
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
            .options(joinedload(Worker.department), joinedload(Worker.position))
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
