"""Тестовые фикстуры для набора Defect (Task 9D-3A).

Единственная ответственность — построение валидной цепочки родительских сущностей
(Project → Line → EngineeringDocument → DocumentRevision → Joint; QualityFinding →
EngineeringEvaluation) прямыми ORM-вставками, без обращения к API/сервисам Defect
(в 9D-3A их нет). Не тестовый модуль (pytest его как тесты не собирает).
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument, Joint
from app.hr.models import Worker, WorkerRole
from app.projects.models import Company, Line, Project, ProjectCompany
from app.quality.defect_models import (
    Defect,
    DefectEvent,
    DefectLocationType,
    DefectRoot,
    DefectType,
)
from app.quality.models import (
    EngineeringEvaluation,
    EngineeringEvaluationRevision,
    QualityFinding,
)

from .conftest import TEST_COMPANY_ID

TODAY = date.today()

DEFECTS_API = "/api/v1/quality/defects"


def seeded_type_id(db: Session, code: str = "CRACK"):
    return db.execute(
        select(DefectType.id).where(DefectType.code == code)
    ).scalar_one()


def seeded_location_id(db: Session, code: str = "WELD_METAL"):
    return db.execute(
        select(DefectLocationType.id).where(DefectLocationType.code == code)
    ).scalar_one()


def valid_active_fields(db: Session, **over) -> dict:
    """Минимальный валидный набор технических полей для ACTIVE (тип CRACK: requires_*=false)."""
    fields = {
        "defect_type_id": seeded_type_id(db),
        "location_type_id": seeded_location_id(db),
        "indication_location": "SURFACE",
    }
    fields.update(over)
    return fields


class DefectCtx:
    """Проект/линия/документ/ревизия + стык + finding + evaluation для тестов Defect."""

    def __init__(self, db: Session, code: str) -> None:
        self.db = db
        self.code = code
        self.creator = self._worker(f"{code}Cr")
        self.project = Project(
            code=f"{code}-{uuid4().hex[:6]}",
            name=f"Проект {code}",
            status="active",
            created_by=self.creator.id,
        )
        db.add(self.project)
        db.commit()
        db.refresh(self.project)
        self.line = Line(
            project_id=self.project.id,
            line_no=f"L-{code}",
            status="active",
            required_inspection_types=[],
            created_by=self.creator.id,
        )
        db.add(self.line)
        db.commit()
        db.refresh(self.line)
        self.document = EngineeringDocument(
            project_id=self.project.id,
            line_id=self.line.id,
            document_no=f"DOC-{code}",
            document_type="ISOMETRIC",
            status="APPROVED",
            created_by=self.creator.id,
        )
        db.add(self.document)
        db.commit()
        db.refresh(self.document)
        self.revision = DocumentRevision(
            engineering_document_id=self.document.id,
            revision_code="R0",
            status="APPROVED",
            created_by=self.creator.id,
        )
        db.add(self.revision)
        db.commit()
        db.refresh(self.revision)

        # Роли с GLOBAL-scope (покрывают любой стык).
        self.ogs = self._role_worker(f"{code}O", "OGS_ENGINEER")
        self.chief = self._role_worker(f"{code}C", "CHIEF_WELDER")
        self.otk = self._role_worker(f"{code}K", "OTK_INSPECTOR")
        self.norole = self._worker(f"{code}Z")
        self._linked_company: Company | None = None

    def _worker(self, suffix: str) -> Worker:
        w = Worker(
            last_name=f"Df{suffix}",
            first_name="Тест",
            company_id=TEST_COMPANY_ID,
            employment_status="active",
            hire_date=TODAY,
        )
        self.db.add(w)
        self.db.commit()
        self.db.refresh(w)
        return w

    def _role_worker(self, suffix: str, role_code: str) -> Worker:
        return self.scoped_role_worker(suffix, role_code, "GLOBAL")

    def scoped_role_worker(
        self,
        suffix: str,
        role_code: str,
        scope_type: str,
        scope_id: str | None = None,
    ) -> Worker:
        """Работник с ролью в заданном scope (для RBAC/scope-матрицы 9D-3C-4)."""
        w = self._worker(suffix)
        role = WorkerRole(
            worker_id=w.id,
            role_code=role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            is_active=True,
            valid_from=TODAY,
        )
        self.db.add(role)
        self.db.commit()
        return w

    def scope_id_for(self, scope_type: str) -> str | None:
        """Идентификатор scope для текущего контекста Joint (COMPANY — связанная org)."""
        if scope_type == "PROJECT":
            return str(self.project.id)
        if scope_type == "LINE":
            return str(self.line.id)
        if scope_type == "ENGINEERING_DOCUMENT":
            return str(self.document.id)
        if scope_type == "COMPANY":
            return str(self.ensure_linked_company().id)
        if scope_type == "SITE":
            return str(uuid4())
        return None

    def ensure_linked_company(
        self, *, name: str | None = None, role_code: str = "WELDING_CONTRACTOR"
    ) -> Company:
        """Организация с действующей связью project_companies (для COMPANY-scope)."""
        if self._linked_company is not None:
            return self._linked_company
        company = Company(
            name=name or f"Org {self.code}",
            status="active",
            created_by=self.creator.id,
        )
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        self.link_project_company(company, role_code)
        self._linked_company = company
        return company

    def link_project_company(self, company: Company, role_code: str) -> None:
        self.db.add(
            ProjectCompany(
                project_id=self.project.id,
                company_id=company.id,
                role_code=role_code,
                valid_from=TODAY,
            )
        )
        self.db.commit()

    @staticmethod
    def h(worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def new_joint(self, joint_no: str) -> Joint:
        j = Joint(
            project_id=self.project.id,
            line_id=self.line.id,
            origin_document_revision_id=self.revision.id,
            current_document_revision_id=self.revision.id,
            system_code=f"{self.project.code}-J-{uuid4().hex[:8]}",
            joint_no=joint_no,
            joint_no_normalized=joint_no.upper(),
            created_by=self.creator.id,
            updated_by=self.creator.id,
        )
        self.db.add(j)
        self.db.commit()
        self.db.refresh(j)
        return j

    def new_evaluation(self, joint: Joint) -> EngineeringEvaluation:
        """Минимальная EngineeringEvaluation (для FK defect_roots).

        На уровне БД достаточно валидной строки; доменные правила
        (EFFECTIVE/CONFIRMED_DEFECT) проверяет сервис 9D-3B, не CHECK.
        """
        # DRAFT-finding достаточно для FK evaluation.finding_id (доменные правила
        # EFFECTIVE/CONFIRMED_DEFECT — сервис 9D-3B, не уровень БД). DRAFT не требует
        # registered-полей (CHECK ck_quality_findings_registered_fields).
        finding = QualityFinding(
            project_id=self.project.id,
            joint_id=joint.id,
            origin_type="INSPECTION_RESULT",
            initial_risk="HIGH",
            observation="Индикация для технической карточки дефекта",
            created_by_worker_id=self.creator.id,
            updated_by_worker_id=self.creator.id,
        )
        self.db.add(finding)
        self.db.commit()
        self.db.refresh(finding)
        ev = EngineeringEvaluation(
            project_id=self.project.id,
            finding_id=finding.id,
            system_code=f"{self.project.code}-EE-{uuid4().hex[:8]}",
            created_by_worker_id=self.creator.id,
            updated_by_worker_id=self.creator.id,
        )
        self.db.add(ev)
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def new_confirmed_evaluation(
        self, joint: Joint, *, classification: str = "CONFIRMED_DEFECT",
        status: str = "EFFECTIVE",
    ) -> EngineeringEvaluation:
        """EngineeringEvaluation с действующей ревизией (по умолчанию EFFECTIVE +
        CONFIRMED_DEFECT) — валидное основание для регистрации Defect (9D-3B)."""
        ev = self.new_evaluation(joint)
        rev = EngineeringEvaluationRevision(
            evaluation_id=ev.id,
            revision_no=1,
            status=status,
            classification=classification,
            created_by_worker_id=self.creator.id,
            updated_by_worker_id=self.creator.id,
            version=1,
        )
        self.db.add(rev)
        self.db.commit()
        self.db.refresh(rev)
        ev.current_revision_id = rev.id
        ev.effective_revision_id = rev.id
        self.db.add(ev)
        self.db.commit()
        self.db.refresh(ev)
        return ev


def make_root(
    ctx: DefectCtx,
    *,
    joint: Joint,
    evaluation: EngineeringEvaluation,
    defect_no: int,
) -> DefectRoot:
    root = DefectRoot(
        engineering_evaluation_id=evaluation.id,
        joint_id=joint.id,
        defect_no=defect_no,
        created_by_worker_id=ctx.creator.id,
        updated_by_worker_id=ctx.creator.id,
    )
    ctx.db.add(root)
    ctx.db.commit()
    ctx.db.refresh(root)
    return root


def make_defect(
    ctx: DefectCtx,
    *,
    root: DefectRoot,
    revision_no: int = 1,
    status: str = "DRAFT",
    supersedes_defect_id=None,
    **fields,
) -> Defect:
    """Создаёт ревизию Defect с валидными служебными полями по статусу."""
    data: dict = {
        "defect_root_id": root.id,
        "revision_no": revision_no,
        "status": status,
        "supersedes_defect_id": supersedes_defect_id,
        "created_by_worker_id": ctx.creator.id,
        "updated_by_worker_id": ctx.creator.id,
    }
    if status == "ACTIVE":
        data.setdefault("activated_by_worker_id", ctx.creator.id)
        data.setdefault("activated_at", _now(ctx))
    if status == "SUPERSEDED":
        data.setdefault("superseded_by_worker_id", ctx.creator.id)
        data.setdefault("superseded_at", _now(ctx))
    if status == "CANCELLED":
        data.setdefault("cancelled_by_worker_id", ctx.creator.id)
        data.setdefault("cancelled_at", _now(ctx))
        data.setdefault("cancellation_reason", "ошибочная карточка")
    data.update(fields)
    d = Defect(**data)
    ctx.db.add(d)
    ctx.db.commit()
    ctx.db.refresh(d)
    return d


def _now(ctx: DefectCtx):
    from sqlalchemy import text

    return ctx.db.execute(text("SELECT now()")).scalar_one()


def create_defect_http(
    client,
    worker: Worker,
    *,
    joint_id,
    engineering_evaluation_id,
    activate: bool = False,
    extra_fields: dict | None = None,
):
    """POST /quality/defects через TestClient (real-DB HTTP helper)."""
    from decimal import Decimal
    from uuid import UUID

    body: dict = {
        "joint_id": str(joint_id),
        "engineering_evaluation_id": str(engineering_evaluation_id),
        "activate": activate,
    }
    if extra_fields:
        for key, value in extra_fields.items():
            if isinstance(value, UUID):
                body[key] = str(value)
            elif isinstance(value, Decimal):
                body[key] = str(value)
            else:
                body[key] = value
    return client.post(DEFECTS_API, json=body, headers=DefectCtx.h(worker))


__all__ = [
    "DEFECTS_API",
    "DefectCtx",
    "DefectEvent",
    "create_defect_http",
    "make_defect",
    "make_root",
    "seeded_location_id",
    "seeded_type_id",
    "valid_active_fields",
]
