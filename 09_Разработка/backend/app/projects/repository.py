from uuid import UUID

from sqlalchemy.orm import Session

from app.projects.models import Company, Line, Project, ProjectCompany
from app.projects.schemas import ProjectListFilters


class ProjectRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- companies ---

    def get_company(self, company_id: int) -> Company | None:
        return self.db.query(Company).filter(Company.id == company_id).first()

    def get_company_by_inn(self, inn: str) -> Company | None:
        return self.db.query(Company).filter(Company.inn == inn).first()

    def list_companies(self, *, skip: int = 0, limit: int = 100) -> list[Company]:
        return (
            self.db.query(Company)
            .order_by(Company.name, Company.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def create_company(self, company: Company) -> Company:
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company

    # --- projects ---

    def get_project(self, project_id: UUID) -> Project | None:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def get_project_by_code(self, code: str) -> Project | None:
        return self.db.query(Project).filter(Project.code == code).first()

    def list_projects(self, filters: ProjectListFilters) -> list[Project]:
        q = self.db.query(Project)
        if filters.company_id is not None or filters.role_code is not None:
            q = q.join(ProjectCompany, ProjectCompany.project_id == Project.id).filter(
                ProjectCompany.valid_to.is_(None)
            )
            if filters.company_id is not None:
                q = q.filter(ProjectCompany.company_id == filters.company_id)
            if filters.role_code is not None:
                q = q.filter(ProjectCompany.role_code == filters.role_code)
            q = q.distinct()
        return (
            q.order_by(Project.code)
            .offset(filters.skip)
            .limit(filters.limit)
            .all()
        )

    def create_project(self, project: Project) -> Project:
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    # --- project_companies ---

    def get_active_project_company(
        self, *, project_id: UUID, company_id: int, role_code: str
    ) -> ProjectCompany | None:
        return (
            self.db.query(ProjectCompany)
            .filter(
                ProjectCompany.project_id == project_id,
                ProjectCompany.company_id == company_id,
                ProjectCompany.role_code == role_code,
                ProjectCompany.valid_to.is_(None),
            )
            .first()
        )

    def list_project_companies(self, project_id: UUID) -> list[ProjectCompany]:
        return (
            self.db.query(ProjectCompany)
            .filter(ProjectCompany.project_id == project_id)
            .order_by(ProjectCompany.role_code, ProjectCompany.id)
            .all()
        )

    def create_project_company(self, link: ProjectCompany) -> ProjectCompany:
        self.db.add(link)
        self.db.commit()
        self.db.refresh(link)
        return link

    # --- lines ---

    def get_line(self, line_id: UUID) -> Line | None:
        return self.db.query(Line).filter(Line.id == line_id).first()

    def get_line_by_project_and_no(
        self, project_id: UUID, line_no: str
    ) -> Line | None:
        return (
            self.db.query(Line)
            .filter(Line.project_id == project_id, Line.line_no == line_no)
            .first()
        )

    def list_lines(self, project_id: UUID) -> list[Line]:
        return (
            self.db.query(Line)
            .filter(Line.project_id == project_id)
            .order_by(Line.line_no, Line.id)
            .all()
        )

    def create_line(self, line: Line) -> Line:
        self.db.add(line)
        self.db.commit()
        self.db.refresh(line)
        return line

    def save_line(self, line: Line) -> Line:
        self.db.commit()
        self.db.refresh(line)
        return line
