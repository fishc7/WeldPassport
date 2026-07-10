import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.hr.models import Department, Position, Worker, WorkerRole
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
    WorkerRoleCreate,
    WorkerRoleOut,
    WorkerRoleUpdate,
    WorkerUpdate,
)
from app.shared.errors import ConflictError, NotFoundError


def to_worker_out(worker: Worker) -> WorkerOut:
    return WorkerOut.model_validate(worker)


def to_worker_card(worker: Worker) -> WorkerCard:
    roles = sorted(
        worker.worker_roles,
        key=lambda r: (r.role_code, r.scope_type, r.scope_id or ""),
    )
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
        roles=[WorkerRoleOut.model_validate(r) for r in roles],
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

    # --- worker roles ---

    def list_worker_roles(self, worker_id: int) -> list[WorkerRole]:
        self.get_worker(worker_id)
        return self._repo.list_worker_roles(worker_id)

    def assign_worker_role(self, worker_id: int, data: WorkerRoleCreate) -> WorkerRole:
        worker = self.get_worker(worker_id)
        if worker.employment_status == "dismissed":
            raise ConflictError(
                "Нельзя назначить активную роль уволенному работнику (dismissed)"
            )
        scope_type = data.scope_type
        scope_id = self._validate_role_scope(scope_type, data.scope_id)
        if self._repo.find_active_role_duplicate(
            worker_id=worker_id,
            role_code=data.role_code,
            scope_type=scope_type,
            scope_id=scope_id,
        ):
            raise ConflictError(
                "Активная роль с таким role_code уже есть в этом scope"
            )
        role = WorkerRole(
            worker_id=worker_id,
            role_code=data.role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_from=data.valid_from or date.today(),
            valid_to=data.valid_to,
            is_active=True,
            note=data.note,
        )
        try:
            return self._repo.create_worker_role(role)
        except IntegrityError as exc:
            raise ConflictError(
                "Активная роль с таким role_code уже есть в этом scope"
            ) from exc

    def update_worker_role(
        self, worker_id: int, role_id: int, data: WorkerRoleUpdate
    ) -> WorkerRole:
        role = self._get_worker_role(worker_id, role_id)
        payload = data.model_dump(exclude_unset=True)
        scope_type = payload.get("scope_type", role.scope_type)
        raw_scope_id = payload.get("scope_id", role.scope_id)
        is_active = payload.get("is_active", role.is_active)
        scope_id = self._validate_role_scope(scope_type, raw_scope_id)
        if "scope_id" in payload:
            payload["scope_id"] = scope_id
        if is_active:
            duplicate = self._repo.find_active_role_duplicate(
                worker_id=worker_id,
                role_code=role.role_code,
                scope_type=scope_type,
                scope_id=scope_id,
                exclude_role_id=role.id,
            )
            if duplicate:
                raise ConflictError(
                    "Активная роль с таким role_code уже есть в этом scope"
                )
        for field, value in payload.items():
            setattr(role, field, value)
        try:
            return self._repo.save_worker_role(role)
        except IntegrityError as exc:
            raise ConflictError(
                "Активная роль с таким role_code уже есть в этом scope"
            ) from exc

    def deactivate_worker_role(self, worker_id: int, role_id: int) -> WorkerRole:
        role = self._get_worker_role(worker_id, role_id)
        role.is_active = False
        if role.valid_to is None:
            role.valid_to = date.today()
        return self._repo.save_worker_role(role)

    def activate_worker_role(self, worker_id: int, role_id: int) -> WorkerRole:
        worker = self.get_worker(worker_id)
        if worker.employment_status == "dismissed":
            raise ConflictError(
                "Нельзя активировать роль уволенному работнику (dismissed)"
            )
        role = self._get_worker_role(worker_id, role_id)
        if self._repo.find_active_role_duplicate(
            worker_id=worker_id,
            role_code=role.role_code,
            scope_type=role.scope_type,
            scope_id=role.scope_id,
            exclude_role_id=role.id,
        ):
            raise ConflictError(
                "Активная роль с таким role_code уже есть в этом scope"
            )
        role.is_active = True
        role.valid_to = None
        try:
            return self._repo.save_worker_role(role)
        except IntegrityError as exc:
            raise ConflictError(
                "Активная роль с таким role_code уже есть в этом scope"
            ) from exc

    def _get_worker_role(self, worker_id: int, role_id: int) -> WorkerRole:
        role = self._repo.get_worker_role(worker_id, role_id)
        if role is None:
            raise NotFoundError("Роль работника", role_id)
        return role

    def _validate_role_scope(
        self, scope_type: str, scope_id: str | None
    ) -> str | None:
        """Проверяет scope_id и возвращает канонический строковый вид.

        - GLOBAL: scope_id должен отсутствовать (None);
        - PROJECT/LINE: обязателен валидный UUID, нормализуется через uuid.UUID(...);
        - остальные scope_type (COMPANY, SITE): scope_id обязателен, но формат
          не фиксируется UUID-ом.
        """
        normalized = scope_id.strip() if isinstance(scope_id, str) else scope_id
        if normalized == "":
            normalized = None

        if scope_type == "GLOBAL":
            if normalized is not None:
                raise ConflictError(
                    "Для scope_type=GLOBAL поле scope_id должно быть null"
                )
            return None

        if normalized is None:
            raise ConflictError(
                f"Для scope_type={scope_type} поле scope_id обязательно"
            )

        if scope_type in ("PROJECT", "LINE"):
            try:
                return str(uuid.UUID(normalized))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ConflictError(
                    f"Для scope_type={scope_type} поле scope_id должно быть "
                    "валидным UUID"
                ) from exc

        return normalized

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
