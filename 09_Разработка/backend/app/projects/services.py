from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.hr.repository import HrRepo
from app.projects.models import Company, Line, Project, ProjectCompany
from app.projects.repository import ProjectRepo
from app.projects.schemas import (
    CompanyCreate,
    LineCreate,
    LineUpdate,
    ProjectCompanyCreate,
    ProjectCreate,
    ProjectListFilters,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.permissions import RoleRequirement, check_worker_role

# Владелец Line — ПТО (IP-08). Технический role_code существующего backend.
LINE_OWNER_ROLE = "PTO_ENGINEER"


class ProjectService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ProjectRepo(db)
        self._hr = HrRepo(db)

    # --- временное правило доступа MVP (IP-03) ---

    def _require_active_worker(self, worker_id: int) -> None:
        """Изменяющие endpoints Task 2: X-User-Id должен быть активным работником.

        Роль ПТО/FOREMAN/MASTER на этом этапе не требуется; отдельная роль
        администратора не вводится (role-based управление — будущее решение).
        """
        worker = self._hr.get_worker(worker_id)
        if worker is None:
            raise NotFoundError("Работник", worker_id)
        if worker.employment_status != "active":
            raise HTTPException(
                status_code=403,
                detail="Работник неактивен и не может выполнять это действие",
            )

    # --- companies ---

    def list_companies(self, *, skip: int = 0, limit: int = 100) -> list[Company]:
        return self._repo.list_companies(skip=skip, limit=limit)

    def create_company(self, data: CompanyCreate, *, created_by: int) -> Company:
        self._require_active_worker(created_by)

        inn = data.inn.strip() if data.inn else None
        inn = inn or None
        if inn is not None and self._repo.get_company_by_inn(inn) is not None:
            raise ConflictError("Организация с таким ИНН уже существует")

        company = Company(
            name=data.name.strip(),
            inn=inn,
            status=data.status,
            created_by=created_by,
        )
        try:
            return self._repo.create_company(company)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Организация с таким ИНН уже существует") from exc

    # --- projects ---

    def get_project(self, project_id: UUID) -> Project:
        project = self._repo.get_project(project_id)
        if project is None:
            raise NotFoundError("Проект", project_id)
        return project

    def list_projects(self, filters: ProjectListFilters) -> list[Project]:
        return self._repo.list_projects(filters)

    def create_project(self, data: ProjectCreate, *, created_by: int) -> Project:
        self._require_active_worker(created_by)

        code = data.code.strip()
        if self._repo.get_project_by_code(code) is not None:
            raise ConflictError("Проект с таким code уже существует")

        project = Project(
            code=code,
            name=data.name.strip(),
            status=data.status,
            created_by=created_by,
        )
        try:
            return self._repo.create_project(project)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Проект с таким code уже существует") from exc

    # --- project_companies ---

    def list_project_companies(self, project_id: UUID) -> list[ProjectCompany]:
        self.get_project(project_id)
        return self._repo.list_project_companies(project_id)

    def add_project_company(
        self, project_id: UUID, data: ProjectCompanyCreate, *, created_by: int
    ) -> ProjectCompany:
        self._require_active_worker(created_by)
        self.get_project(project_id)

        if self._repo.get_company(data.company_id) is None:
            raise NotFoundError("Организация", data.company_id)

        valid_from = data.valid_from or date.today()
        if data.valid_to is not None and data.valid_to < valid_from:
            raise ValidationError("valid_to не может быть раньше valid_from")

        # Действующее участие определяется valid_to IS NULL; дубликат активной
        # связи (project_id + company_id + role_code) запрещён. Исторические
        # (закрытые valid_to) участия не блокируют новую активную связь.
        if data.valid_to is None and self._repo.get_active_project_company(
            project_id=project_id,
            company_id=data.company_id,
            role_code=data.role_code,
        ):
            raise ConflictError(
                "Активное участие организации с этой ролью уже существует"
            )

        link = ProjectCompany(
            project_id=project_id,
            company_id=data.company_id,
            role_code=data.role_code,
            valid_from=valid_from,
            valid_to=data.valid_to,
        )
        try:
            return self._repo.create_project_company(link)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Активное участие организации с этой ролью уже существует"
            ) from exc

    # --- lines (IP-08) ---

    def _forbidden(self) -> HTTPException:
        return HTTPException(
            status_code=403,
            detail="Недостаточно прав: требуется роль ПТО (PTO_ENGINEER)",
        )

    def _require_line_create_permission(
        self, worker_id: int, project_id: UUID
    ) -> None:
        """POST Line — ПТО с GLOBAL или соответствующим PROJECT scope.

        LINE scope для создания ещё не существующей линии не допускается (IP-08).
        """
        requirements = (
            RoleRequirement(LINE_OWNER_ROLE, "GLOBAL"),
            RoleRequirement(LINE_OWNER_ROLE, "PROJECT", str(project_id)),
        )
        if not any(
            check_worker_role(self._db, worker_id, req) for req in requirements
        ):
            raise self._forbidden()

    def _require_line_update_permission(
        self, worker_id: int, project_id: UUID, line_id: UUID
    ) -> None:
        """PATCH Line — ПТО с GLOBAL, соответствующим PROJECT либо LINE scope."""
        requirements = (
            RoleRequirement(LINE_OWNER_ROLE, "GLOBAL"),
            RoleRequirement(LINE_OWNER_ROLE, "PROJECT", str(project_id)),
            RoleRequirement(LINE_OWNER_ROLE, "LINE", str(line_id)),
        )
        if not any(
            check_worker_role(self._db, worker_id, req) for req in requirements
        ):
            raise self._forbidden()

    def get_line(self, line_id: UUID) -> Line:
        line = self._repo.get_line(line_id)
        if line is None:
            raise NotFoundError("Линия", line_id)
        return line

    def list_lines(self, project_id: UUID) -> list[Line]:
        self.get_project(project_id)
        return self._repo.list_lines(project_id)

    def create_line(
        self, project_id: UUID, data: LineCreate, *, created_by: int
    ) -> Line:
        self._require_line_create_permission(created_by, project_id)
        self.get_project(project_id)

        line_no = data.line_no.strip()
        if self._repo.get_line_by_project_and_no(project_id, line_no) is not None:
            raise ConflictError("Линия с таким line_no в проекте уже существует")

        line = Line(
            project_id=project_id,
            line_no=line_no,
            name=data.name,
            medium=data.medium,
            nominal_dn=data.nominal_dn,
            class_code=data.class_code,
            category_code=data.category_code,
            status=data.status,
            required_inspection_types=list(data.required_inspection_types),
            created_by=created_by,
        )
        try:
            return self._repo.create_line(line)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Линия с таким line_no в проекте уже существует"
            ) from exc

    def update_line(
        self, line_id: UUID, data: LineUpdate, *, updated_by: int
    ) -> Line:
        line = self.get_line(line_id)
        self._require_line_update_permission(updated_by, line.project_id, line_id)

        if line.status == "cancelled":
            raise ConflictError("Отменённую линию нельзя редактировать")

        changes = data.model_dump(exclude_unset=True)
        if "line_no" in changes and changes["line_no"] is not None:
            changes["line_no"] = changes["line_no"].strip()
        for field, value in changes.items():
            if field == "required_inspection_types" and value is not None:
                value = list(value)
            setattr(line, field, value)

        try:
            return self._repo.save_line(line)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Линия с таким line_no в проекте уже существует"
            ) from exc
