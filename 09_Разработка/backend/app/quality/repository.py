from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, Joint, WeldOperation
from app.projects.models import ProjectCompany
from app.quality.models import (
    QUALITY_SCHEMA,
    Inspection,
    InspectionEvent,
)
from app.quality.schemas import InspectionListFilters


@dataclass
class VisibilityScope:
    """Разрешённая область видимости заявок для актора (SQL-фильтр, §15.6).

    `all_visible=True` — глобальная роль: фильтр не накладывается. Иначе строки
    отбираются по project/line/engineering_document/company актора. Если ни одного
    scope нет и роль не глобальная — доступа нет (пустой результат).
    """

    all_visible: bool = False
    project_ids: set[UUID] = field(default_factory=set)
    line_ids: set[UUID] = field(default_factory=set)
    document_ids: set[UUID] = field(default_factory=set)
    company_ids: set[int] = field(default_factory=set)

    @property
    def has_any_scope(self) -> bool:
        return bool(
            self.project_ids
            or self.line_ids
            or self.document_ids
            or self.company_ids
        )


class QualityRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Проектная нумерация (§8) ──────────────────────────────────────────────

    def next_inspection_sequence(self, project_id: UUID) -> int:
        """Атомарно выдаёт следующий номер последовательности проекта (§8.1).

        `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` берёт блокировку строки
        счётчика: параллельные транзакции сериализуются, гонки `MAX()+1` нет.
        Выполняется в текущей транзакции; коммит — вместе с INSERT заявки, поэтому
        при rollback создания номер не считается выданным. Стартовое значение 0,
        первая выдача → 1; номера не переиспользуются.
        """
        result = self.db.execute(
            text(
                f"""
                INSERT INTO {QUALITY_SCHEMA}.inspection_sequences
                    (project_id, last_value, updated_at)
                VALUES (CAST(:pid AS uuid), 1, now())
                ON CONFLICT (project_id)
                DO UPDATE SET
                    last_value = {QUALITY_SCHEMA}.inspection_sequences.last_value + 1,
                    updated_at = now()
                RETURNING last_value
                """
            ),
            {"pid": str(project_id)},
        )
        return int(result.scalar_one())

    # ── Inspection: чтение ────────────────────────────────────────────────────

    def get_inspection(self, inspection_id: UUID) -> Inspection | None:
        return (
            self.db.query(Inspection)
            .filter(Inspection.id == inspection_id)
            .first()
        )

    def find_by_idempotency(
        self, *, created_by_worker_id: int, idempotency_key: str
    ) -> Inspection | None:
        return (
            self.db.query(Inspection)
            .filter(
                Inspection.created_by_worker_id == created_by_worker_id,
                Inspection.idempotency_key == idempotency_key,
            )
            .first()
        )

    def find_by_project_external_no(
        self, *, project_id: UUID, external_request_no: str
    ) -> Inspection | None:
        return (
            self.db.query(Inspection)
            .filter(
                Inspection.project_id == project_id,
                Inspection.external_request_no == external_request_no,
            )
            .first()
        )

    def has_other_active_inspection(
        self, joint_id: UUID, *, exclude_id: UUID | None = None
    ) -> bool:
        """Есть ли для Joint другая действующая (не терминальная) заявка (§12.2)."""
        q = self.db.query(Inspection.id).filter(
            Inspection.joint_id == joint_id,
            Inspection.status.notin_(("CANCELLED", "TERMINATED")),
        )
        if exclude_id is not None:
            q = q.filter(Inspection.id != exclude_id)
        return q.first() is not None

    def statuses_for_joints(
        self, joint_ids: Iterable[UUID]
    ) -> dict[UUID, list[str]]:
        """Статусы заявок по каждому Joint из набора — один запрос (без N+1, §17.3)."""
        ids = list(joint_ids)
        result: dict[UUID, list[str]] = {jid: [] for jid in ids}
        if not ids:
            return result
        rows = (
            self.db.query(Inspection.joint_id, Inspection.status)
            .filter(Inspection.joint_id.in_(ids))
            .all()
        )
        for joint_id, status in rows:
            result.setdefault(joint_id, []).append(status)
        return result

    # ── Inspection: запись (add/flush без commit; save — commit) ───────────────

    def add_inspection(self, inspection: Inspection) -> Inspection:
        self.db.add(inspection)
        self.db.flush()
        return inspection

    def save_inspection(self, inspection: Inspection) -> Inspection:
        self.db.commit()
        self.db.refresh(inspection)
        return inspection

    # ── Журнал событий (append-only, §9) ──────────────────────────────────────

    def add_event(self, event: InspectionEvent) -> InspectionEvent:
        """Добавляет событие в текущую транзакцию (add + flush, без commit)."""
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(self, inspection_id: UUID) -> list[InspectionEvent]:
        return (
            self.db.query(InspectionEvent)
            .filter(InspectionEvent.inspection_id == inspection_id)
            .order_by(InspectionEvent.created_at, InspectionEvent.id)
            .all()
        )

    # ── Список с scope-фильтрацией на уровне SQL (§15.6) ───────────────────────

    def _scoped_query(self, scope: VisibilityScope):
        """Базовый query заявок с наложенным scope-фильтром актора.

        Джойн к Joint (и к текущей ревизии для ENGINEERING_DOCUMENT) выполняется в
        SQL; фильтрация строк — предикатом `OR` по разрешённым project/line/
        document/company. Ни при каких условиях не загружаем все заявки в Python.
        """
        query = self.db.query(Inspection).join(
            Joint, Inspection.joint_id == Joint.id
        )
        if scope.all_visible:
            return query
        if not scope.has_any_scope:
            # Роль без глобального scope и без единого конкретного scope — доступа
            # нет: заведомо ложный предикат (пустой результат) целиком в SQL.
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

    def _apply_filters(self, query, filters: InspectionListFilters):
        if filters.project_id is not None:
            query = query.filter(Inspection.project_id == filters.project_id)
        if filters.joint_id is not None:
            query = query.filter(Inspection.joint_id == filters.joint_id)
        if filters.status is not None:
            query = query.filter(Inspection.status == filters.status)
        if filters.system_code is not None:
            query = query.filter(Inspection.system_code == filters.system_code)
        if filters.external_request_no is not None:
            query = query.filter(
                Inspection.external_request_no == filters.external_request_no
            )
        if filters.created_by_worker_id is not None:
            query = query.filter(
                Inspection.created_by_worker_id == filters.created_by_worker_id
            )
        return query

    def count_inspections(
        self, filters: InspectionListFilters, scope: VisibilityScope
    ) -> int:
        query = self._apply_filters(self._scoped_query(scope), filters)
        return query.count()

    def list_inspections(
        self, filters: InspectionListFilters, scope: VisibilityScope
    ) -> list[Inspection]:
        query = self._apply_filters(self._scoped_query(scope), filters)
        return (
            query.order_by(Inspection.created_at.desc(), Inspection.id.desc())
            .offset(filters.offset)
            .limit(filters.limit)
            .all()
        )

    # ── Read-only связи с производственным фактом сварки (§12.1) ───────────────

    def current_completed_weld_operation(
        self, joint_id: UUID
    ) -> WeldOperation | None:
        """Актуальная завершённая производственная операция Joint (§12.1).

        Последняя COMPLETED-операция, не заменённая (superseded_by IS NULL) —
        актуальное звено производственной цепочки. Переварка/корректировка
        переводят прежнюю в SUPERSEDED, и она перестаёт быть актуальной."""
        return (
            self.db.query(WeldOperation)
            .filter(
                WeldOperation.joint_id == joint_id,
                WeldOperation.lifecycle_status == "COMPLETED",
                WeldOperation.superseded_by_operation_id.is_(None),
            )
            .order_by(WeldOperation.sequence_no.desc())
            .first()
        )

    def has_completed_weld_operation_history(self, joint_id: UUID) -> bool:
        """Существовала ли вообще завершённая операция (COMPLETED/SUPERSEDED, §12.1).

        Позволяет отличить «сварка не завершена» (нет истории) от «завершена, но
        заменена и не актуальна» (есть история, актуальной нет)."""
        return (
            self.db.query(WeldOperation.id)
            .filter(
                WeldOperation.joint_id == joint_id,
                WeldOperation.lifecycle_status.in_(("COMPLETED", "SUPERSEDED")),
            )
            .first()
            is not None
        )
