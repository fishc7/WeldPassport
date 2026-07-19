"""Интеграционные тесты структурного ядра EngineeringEvaluation (Task 9D-2A, ADR-021).

Покрывают: создание логической оценки с первой DRAFT-ревизией и проектной нумерацией
`<CODE>-EE-<SEQUENCE>`, событие EVALUATION_CREATED, `UNIQUE(finding_id)`, правку DRAFT с
optimistic locking, принадлежность классификации/исхода ревизии (а не оценке), набор
статусов C06/C09 (без RETURNED_FOR_REVISION/APPROVED), enum-CHECK при NOT NULL,
неизменяемость `QualityFinding.status` (C04).

Команды lifecycle, RBAC, API, бизнес-поведение sources/criteria/exceptions — не здесь
(блоки 9D-2B/2C/2D). Defect/FindingDisposition не создаются.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project
from app.quality import engineering_evaluation_workflow as eew
from app.quality.engineering_evaluation_models import (
    EngineeringEvaluation,
    EngineeringEvaluationRevision,
)
from app.quality.engineering_evaluation_repository import (
    EngineeringEvaluationRepository,
)
from app.quality.models import QualityFinding

from .conftest import TEST_COMPANY_ID

ENG = "/api/v1/engineering"
TODAY = date.today()


def _worker(db: Session, suffix: str) -> Worker:
    w = Worker(
        last_name=f"Ee{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=TODAY,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def _role_worker(db: Session, suffix: str, role_code: str) -> Worker:
    w = _worker(db, suffix)
    db.add(
        WorkerRole(
            worker_id=w.id,
            role_code=role_code,
            scope_type="GLOBAL",
            scope_id=None,
            is_active=True,
            valid_from=TODAY,
        )
    )
    db.commit()
    return w


class EvalCtx:
    """Проект/линия/документ/ревизия/роли/стык + фабрика finding для тестов оценки."""

    def __init__(self, db: Session, client: TestClient, code: str) -> None:
        self.db = db
        self.client = client
        self.creator = _worker(db, f"{code}Cr")
        self.project = Project(
            code=code, name=f"Проект {code}", status="active",
            created_by=self.creator.id,
        )
        db.add(self.project)
        db.commit()
        db.refresh(self.project)
        self.line = Line(
            project_id=self.project.id, line_no=f"L-{code}", status="active",
            required_inspection_types=[], created_by=self.creator.id,
        )
        db.add(self.line)
        db.commit()
        db.refresh(self.line)
        self.document = EngineeringDocument(
            project_id=self.project.id, line_id=self.line.id,
            document_no=f"DOC-{code}", document_type="ISOMETRIC",
            status="APPROVED", created_by=self.creator.id,
        )
        db.add(self.document)
        db.commit()
        db.refresh(self.document)
        self.revision = DocumentRevision(
            engineering_document_id=self.document.id, revision_code="R0",
            status="APPROVED", created_by=self.creator.id,
        )
        db.add(self.revision)
        db.commit()
        db.refresh(self.revision)
        self.pto = _role_worker(db, f"{code}P", "PTO_ENGINEER")
        self.ogs = _role_worker(db, f"{code}O", "OGS_ENGINEER")
        self._joint_seq = 0
        self._qf_seq = 0

    def _h(self, w: Worker) -> dict[str, str]:
        return {"X-User-Id": str(w.id)}

    def create_joint(self) -> str:
        self._joint_seq += 1
        payload = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": f"J-{self._joint_seq}",
            "created_by": self.creator.id,
        }
        r = self.client.post(f"{ENG}/joints", json=payload, headers=self._h(self.pto))
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def make_finding(self) -> QualityFinding:
        """Прямая вставка finding в статусе UNDER_EVALUATION (для привязки оценки)."""
        joint_id = self.create_joint()
        self._qf_seq += 1
        now = datetime.now(timezone.utc)
        finding = QualityFinding(
            project_id=self.project.id,
            joint_id=joint_id,
            system_code=f"{self.project.code}-QF-{self._qf_seq}",
            origin_type="INSPECTION_RESULT",
            initial_risk="HIGH",
            status="UNDER_EVALUATION",
            observation="Индикация в корне шва — на инженерную оценку",
            registered_by_worker_id=self.creator.id,
            registered_at=now,
            acknowledged_by_worker_id=self.ogs.id,
            acknowledged_at=now,
            created_by_worker_id=self.creator.id,
            updated_by_worker_id=self.creator.id,
            version=1,
        )
        self.db.add(finding)
        self.db.commit()
        self.db.refresh(finding)
        return finding

    def repo(self) -> EngineeringEvaluationRepository:
        return EngineeringEvaluationRepository(self.db)


# ── Создание и нумерация ──────────────────────────────────────────────────────


def test_create_allocates_number_and_draft_revision(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EEA")
    finding = ctx.make_finding()
    repo = ctx.repo()

    ev, rev = repo.create_evaluation(
        project_id=ctx.project.id,
        finding_id=finding.id,
        project_code=ctx.project.code,
        actor_worker_id=ctx.ogs.id,
        actor_role="OGS_ENGINEER",
    )
    repo.save()

    assert ev.system_code == "EEA-EE-1"
    assert rev.revision_no == 1
    assert rev.status == "DRAFT"
    assert ev.current_revision_id == rev.id
    assert ev.effective_revision_id is None
    events = repo.list_events(ev.id)
    assert [e.event_type for e in events] == ["EVALUATION_CREATED"]
    assert events[0].actor_worker_id == ctx.ogs.id
    assert events[0].revision_version == 1


def test_second_evaluation_increments_sequence(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EEB")
    repo = ctx.repo()
    f1 = ctx.make_finding()
    f2 = ctx.make_finding()

    ev1, _ = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=f1.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    ev2, _ = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=f2.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    assert ev1.system_code == "EEB-EE-1"
    assert ev2.system_code == "EEB-EE-2"


def test_unique_evaluation_per_finding(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EEC")
    repo = ctx.repo()
    finding = ctx.make_finding()
    repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()

    try:
        repo.create_evaluation(
            project_id=ctx.project.id, finding_id=finding.id,
            project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
        )
        db.flush()
        raised = False
    except IntegrityError:
        raised = True
    finally:
        db.rollback()
    assert raised, "UNIQUE(finding_id) должен запрещать вторую оценку на finding"


# ── Правка DRAFT и optimistic locking ─────────────────────────────────────────


def test_update_draft_and_version_conflict(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EED")
    repo = ctx.repo()
    finding = ctx.make_finding()
    _, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()

    repo.update_revision(
        rev,
        expected_version=1,
        actor_worker_id=ctx.ogs.id,
        fields={"evaluation_outcome": "ACCEPTABLE", "classification": "NOT_CONFIRMED"},
    )
    repo.save()
    assert rev.version == 2
    assert rev.evaluation_outcome == "ACCEPTABLE"
    assert rev.classification == "NOT_CONFIRMED"
    types = [e.event_type for e in repo.list_events(rev.evaluation_id)]
    assert types == ["EVALUATION_CREATED", "EVALUATION_UPDATED"]

    try:
        repo.update_revision(
            rev, expected_version=1, actor_worker_id=ctx.ogs.id,
            fields={"rationale": "устаревшая версия"},
        )
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    assert code == eew.EVAL_VERSION_CONFLICT


# ── C10/C01: классификация принадлежит ревизии, не оценке ─────────────────────


def test_classification_belongs_to_revision_not_evaluation(client, db: Session):
    rev_cols = {c.key for c in sa_inspect(EngineeringEvaluationRevision).columns}
    ev_cols = {c.key for c in sa_inspect(EngineeringEvaluation).columns}
    owned = {
        "evaluation_outcome",
        "classification",
        "recommended_disposition",
        "confirmed_severity",
        "impact_scope",
    }
    assert owned <= rev_cols
    assert owned.isdisjoint(ev_cols)


# ── C06/C09: набор статусов ───────────────────────────────────────────────────


def test_status_set_is_c06_c09():
    assert set(eew.EVALUATION_STATUSES) == {
        "DRAFT",
        "PREPARED",
        "FIXED",
        "PENDING_APPROVAL",
        "EFFECTIVE",
        "SUPERSEDED",
        "WITHDRAWN",
    }
    assert "RETURNED_FOR_REVISION" not in eew.EVALUATION_STATUSES
    assert "APPROVED" not in eew.EVALUATION_STATUSES


def test_status_check_rejects_returned_and_approved(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EEE")
    repo = ctx.repo()
    finding = ctx.make_finding()
    ev, _ = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()

    for bad_status in ("RETURNED_FOR_REVISION", "APPROVED"):
        try:
            db.add(
                EngineeringEvaluationRevision(
                    evaluation_id=ev.id, revision_no=2, status=bad_status,
                    revision_reason="probe",
                    created_by_worker_id=ctx.ogs.id,
                    updated_by_worker_id=ctx.ogs.id,
                )
            )
            db.flush()
            raised = False
        except IntegrityError:
            raised = True
        finally:
            db.rollback()
        assert raised, f"CHECK статуса должен отклонять {bad_status}"


# ── enum-CHECK при NOT NULL; NULL в DRAFT допустим ────────────────────────────


def test_enum_check_rejects_invalid_and_allows_null(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EEF")
    repo = ctx.repo()
    finding = ctx.make_finding()
    ev, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()

    # NULL в DRAFT допустим (создание прошло без outcome/classification).
    assert rev.evaluation_outcome is None
    assert rev.classification is None

    # Невалидное значение enum → IntegrityError.
    try:
        db.add(
            EngineeringEvaluationRevision(
                evaluation_id=ev.id, revision_no=2, status="DRAFT",
                revision_reason="probe", evaluation_outcome="WRONG",
                created_by_worker_id=ctx.ogs.id, updated_by_worker_id=ctx.ogs.id,
            )
        )
        db.flush()
        raised = False
    except IntegrityError:
        raised = True
    finally:
        db.rollback()
    assert raised


# ── C04: QualityFinding.status не меняется из 9D-2 ─────────────────────────────


def test_finding_status_unchanged(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "EEG")
    repo = ctx.repo()
    finding = ctx.make_finding()
    assert finding.status == "UNDER_EVALUATION"

    repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    db.refresh(finding)
    assert finding.status == "UNDER_EVALUATION"
