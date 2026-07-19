"""Репозиторий ядра QualityFinding (Task 9D-1, ADR-019).

Изолирует SQL доступа к finding/событиям/счётчику и read-only связи с источниками
контроля. Стиль Tasks 9A–9C: add/flush без commit; save — commit + refresh; scope-
фильтрация списка целиком в SQL (не «загрузка всех finding в Python»). Область
видимости (`VisibilityScope`) переиспользуется из `app.quality.repository`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, Joint, WeldOperation
from app.projects.models import ProjectCompany
from app.quality.execution_models import MethodExecution
from app.quality.models import Inspection
from app.quality.quality_finding_models import (
    QUALITY_SCHEMA,
    QualityFinding,
    QualityFindingEvent,
)
from app.quality.quality_finding_schemas import FindingListFilters
from app.quality.repository import VisibilityScope

FINDING_SEQUENCES_TABLE = "quality_finding_sequences"


class QualityFindingRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Проектная нумерация ────────────────────────────────────────────────────

    def next_finding_sequence(self, project_id: UUID) -> int:
        """Атомарно выдаёт следующий номер последовательности проекта.

        `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` берёт блокировку строки
        счётчика: параллельные транзакции сериализуются, гонки `MAX()+1` нет.
        Выполняется в текущей транзакции; при rollback регистрации номер не считается
        выданным. Стартовое значение 0, первая выдача → 1; номера не переиспользуются.
        """
        result = self.db.execute(
            text(
                f"""
                INSERT INTO {QUALITY_SCHEMA}.{FINDING_SEQUENCES_TABLE}
                    (project_id, last_value, updated_at)
                VALUES (CAST(:pid AS uuid), 1, now())
                ON CONFLICT (project_id)
                DO UPDATE SET
                    last_value =
                        {QUALITY_SCHEMA}.{FINDING_SEQUENCES_TABLE}.last_value + 1,
                    updated_at = now()
                RETURNING last_value
                """
            ),
            {"pid": str(project_id)},
        )
        return int(result.scalar_one())

    # ── Finding: чтение ────────────────────────────────────────────────────────

    def get_finding(self, finding_id: UUID) -> QualityFinding | None:
        return (
            self.db.query(QualityFinding)
            .filter(QualityFinding.id == finding_id)
            .first()
        )

    def find_by_project_external_no(
        self, *, project_id: UUID, external_no: str
    ) -> QualityFinding | None:
        return (
            self.db.query(QualityFinding)
            .filter(
                QualityFinding.project_id == project_id,
                QualityFinding.external_no == external_no,
            )
            .first()
        )

    # ── Finding: запись (add/flush без commit; save — commit) ──────────────────

    def add_finding(self, finding: QualityFinding) -> QualityFinding:
        self.db.add(finding)
        self.db.flush()
        return finding

    def save_finding(self, finding: QualityFinding) -> QualityFinding:
        self.db.commit()
        self.db.refresh(finding)
        return finding

    def delete_finding(self, finding: QualityFinding) -> None:
        """Физическое удаление DRAFT (проверяет сервис) + commit.

        Журнал DRAFT (CREATED/UPDATED неотправленного черновика) удаляется вместе с
        finding в одной транзакции: append-only RESTRICT защищает историю
        зарегистрированных записей, а отброшенный черновик официально не существовал —
        сохранять его события незачем. Для REGISTERED физического удаления нет.
        """
        self.db.query(QualityFindingEvent).filter(
            QualityFindingEvent.finding_id == finding.id
        ).delete(synchronize_session=False)
        self.db.delete(finding)
        self.db.commit()

    # ── Журнал событий (append-only) ───────────────────────────────────────────

    def add_event(self, event: QualityFindingEvent) -> QualityFindingEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(self, finding_id: UUID) -> list[QualityFindingEvent]:
        return (
            self.db.query(QualityFindingEvent)
            .filter(QualityFindingEvent.finding_id == finding_id)
            .order_by(QualityFindingEvent.created_at, QualityFindingEvent.id)
            .all()
        )

    # ── Список с scope-фильтрацией на уровне SQL ───────────────────────────────

    def _scoped_query(self, scope: VisibilityScope):
        """Базовый query finding с наложенным scope-фильтром актора (как в 9A).

        Джойн к Joint (и к текущей ревизии для ENGINEERING_DOCUMENT) — в SQL;
        фильтрация строк — предикатом `OR` по разрешённым project/line/document/
        company. Все finding в Python не загружаются.
        """
        query = self.db.query(QualityFinding).join(
            Joint, QualityFinding.joint_id == Joint.id
        )
        if scope.all_visible:
            return query
        if not scope.has_any_scope:
            return query.filter(text("1 = 0"))

        query = query.outerjoin(
            DocumentRevision,
            Joint.current_document_revision_id == DocumentRevision.id,
        )
        clauses = []
        if scope.project_ids:
            clauses.append(Joint.project_id.in_(scope.project_ids))
        if scope.line_ids:
            clauses.append(Joint.line_id.in_(scope.line_ids))
        if scope.document_ids:
            clauses.append(
                DocumentRevision.engineering_document_id.in_(scope.document_ids)
            )
        if scope.company_ids:
            company_projects = (
                self.db.query(ProjectCompany.project_id)
                .filter(
                    ProjectCompany.company_id.in_(scope.company_ids),
                    ProjectCompany.valid_to.is_(None),
                )
                .subquery()
            )
            clauses.append(Joint.project_id.in_(company_projects))
        return query.filter(or_(*clauses))

    def _apply_filters(self, query, filters: FindingListFilters):
        if filters.project_id is not None:
            query = query.filter(QualityFinding.project_id == filters.project_id)
        if filters.joint_id is not None:
            query = query.filter(QualityFinding.joint_id == filters.joint_id)
        if filters.status is not None:
            query = query.filter(QualityFinding.status == filters.status)
        if filters.origin_type is not None:
            query = query.filter(QualityFinding.origin_type == filters.origin_type)
        if filters.initial_risk is not None:
            query = query.filter(QualityFinding.initial_risk == filters.initial_risk)
        if filters.system_code is not None:
            query = query.filter(QualityFinding.system_code == filters.system_code)
        if filters.external_no is not None:
            query = query.filter(QualityFinding.external_no == filters.external_no)
        if filters.created_by_worker_id is not None:
            query = query.filter(
                QualityFinding.created_by_worker_id == filters.created_by_worker_id
            )
        return query

    def count_findings(
        self, filters: FindingListFilters, scope: VisibilityScope
    ) -> int:
        query = self._apply_filters(self._scoped_query(scope), filters)
        return query.count()

    def list_findings(
        self, filters: FindingListFilters, scope: VisibilityScope
    ) -> list[QualityFinding]:
        query = self._apply_filters(self._scoped_query(scope), filters)
        return (
            query.order_by(
                QualityFinding.created_at.desc(), QualityFinding.id.desc()
            )
            .offset(filters.offset)
            .limit(filters.limit)
            .all()
        )

    # ── Источники контроля (read-only, для joint-match) ────────────────────────

    def get_inspection(self, inspection_id: UUID) -> Inspection | None:
        return (
            self.db.query(Inspection)
            .filter(Inspection.id == inspection_id)
            .first()
        )

    def get_method_execution(
        self, method_execution_id: UUID
    ) -> MethodExecution | None:
        return (
            self.db.query(MethodExecution)
            .filter(MethodExecution.id == method_execution_id)
            .first()
        )

    def get_weld_operation(self, weld_operation_id: UUID) -> WeldOperation | None:
        return (
            self.db.query(WeldOperation)
            .filter(WeldOperation.id == weld_operation_id)
            .first()
        )
