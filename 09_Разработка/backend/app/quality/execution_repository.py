"""Repository выполнения метода контроля (Task 9C, блок 9C-3).

Доступ к данным сущностей выполнения (`MethodExecution` и дочерних), участников,
локальных результатов, стандартов, внешних лиц, аккредитаций и доменного аудита.
Только данные: инварианты и lifecycle — в сервисном слое (как QualityRepo Tasks
9A/9B). add/flush — без commit; save — commit + refresh.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.quality.execution_models import (
    LaboratoryAccreditation,
    LaboratoryConclusion,
    LaboratoryConclusionExecution,
    MethodExecution,
    MethodExecutionParticipant,
    MethodExecutionResultItem,
    MethodExecutionStandard,
    QualityAuditEvent,
    QualityExternalPerson,
)
from app.quality.laboratory_conclusion_workflow import (
    CONCLUSION_CANCELLED,
    CONCLUSION_ISSUED,
    CONCLUSION_SUPERSEDED,
    CONCLUSION_TERMINAL_STATUSES,
)
from app.quality.method_execution_workflow import (
    EXEC_CANCELLED,
    EXEC_SUPERSEDED,
    EXECUTION_CANCELLABLE_STATUSES,
    RESULT_COMPLETE,
    RESULT_EXCLUDED,
    PARTICIPANT_LEAD_INSPECTOR,
)

# Статусы выполнения, исключаемые из «действующих текущих» для расчёта состояния
# назначения: терминальные истории (отмена/замещение) не участвуют.
_INACTIVE_EXEC_STATUSES = (EXEC_CANCELLED, EXEC_SUPERSEDED)
# Открытые (редактируемые, не терминальные) статусы редакции — «редакция в работе».
_OPEN_EXEC_STATUSES = EXECUTION_CANCELLABLE_STATUSES
# Открытые (не терминальные) статусы заключения — «редакция заключения в работе».
_OPEN_CONCLUSION_STATUSES = tuple(
    s for s in ("DRAFT", "PREPARED", "LAB_APPROVED")
)
_ = CONCLUSION_TERMINAL_STATUSES  # документирующая ссылка
# Ссылка на константы заключения зарезервирована для будущих блоков (§15–20).
_ = (CONCLUSION_CANCELLED, CONCLUSION_SUPERSEDED)


class ExecutionRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── MethodExecution ───────────────────────────────────────────────────────

    def get_execution(self, execution_id: UUID) -> MethodExecution | None:
        return (
            self.db.query(MethodExecution)
            .filter(MethodExecution.id == execution_id)
            .first()
        )

    def add_execution(self, execution: MethodExecution) -> MethodExecution:
        self.db.add(execution)
        self.db.flush()
        return execution

    def save_execution(self, execution: MethodExecution) -> MethodExecution:
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def list_executions_for_assignment(
        self, assignment_id: UUID
    ) -> list[MethodExecution]:
        return (
            self.db.query(MethodExecution)
            .filter(
                MethodExecution.inspection_method_assignment_id == assignment_id
            )
            .order_by(MethodExecution.created_at, MethodExecution.id)
            .all()
        )

    def list_executions_for_root(
        self, root_execution_id: UUID
    ) -> list[MethodExecution]:
        """История редакций одного физического эпизода (§18)."""
        return (
            self.db.query(MethodExecution)
            .filter(MethodExecution.root_execution_id == root_execution_id)
            .order_by(MethodExecution.revision_no, MethodExecution.created_at)
            .all()
        )

    def get_current_execution_for_root(
        self,
        root_execution_id: UUID,
        *,
        exclude_id: UUID | None = None,
        for_update: bool = False,
    ) -> MethodExecution | None:
        """Текущая редакция root (§5.3). `for_update` берёт блокировку строки для
        сериализации конкурентного подтверждения редакций (§18)."""
        query = self.db.query(MethodExecution).filter(
            MethodExecution.root_execution_id == root_execution_id,
            MethodExecution.is_current.is_(True),
        )
        if exclude_id is not None:
            query = query.filter(MethodExecution.id != exclude_id)
        if for_update:
            query = query.with_for_update()
        return query.first()

    def has_open_revision(
        self, root_execution_id: UUID, *, exclude_id: UUID | None = None
    ) -> bool:
        """Есть ли незавершённая (редактируемая) редакция root, кроме exclude (§18)."""
        query = self.db.query(MethodExecution.id).filter(
            MethodExecution.root_execution_id == root_execution_id,
            MethodExecution.status.in_(tuple(_OPEN_EXEC_STATUSES)),
        )
        if exclude_id is not None:
            query = query.filter(MethodExecution.id != exclude_id)
        return query.first() is not None

    def current_executions_for_assignment(
        self, assignment_id: UUID
    ) -> list[MethodExecution]:
        """Действующие текущие редакции выполнения назначения (для §24).

        Только `is_current=True` и не отменённые/замещённые — история статусов
        CANCELLED/SUPERSEDED в вычисление состояния назначения не входит.
        """
        return (
            self.db.query(MethodExecution)
            .filter(
                MethodExecution.inspection_method_assignment_id == assignment_id,
                MethodExecution.is_current.is_(True),
                MethodExecution.status.notin_(_INACTIVE_EXEC_STATUSES),
            )
            .order_by(MethodExecution.created_at, MethodExecution.id)
            .all()
        )

    # ── Участники ─────────────────────────────────────────────────────────────

    def get_participant(
        self, participant_id: UUID
    ) -> MethodExecutionParticipant | None:
        return (
            self.db.query(MethodExecutionParticipant)
            .filter(MethodExecutionParticipant.id == participant_id)
            .first()
        )

    def list_participants(
        self, execution_id: UUID
    ) -> list[MethodExecutionParticipant]:
        return (
            self.db.query(MethodExecutionParticipant)
            .filter(MethodExecutionParticipant.method_execution_id == execution_id)
            .order_by(
                MethodExecutionParticipant.created_at,
                MethodExecutionParticipant.id,
            )
            .all()
        )

    def count_lead_inspectors(self, execution_id: UUID) -> int:
        return (
            self.db.query(MethodExecutionParticipant)
            .filter(
                MethodExecutionParticipant.method_execution_id == execution_id,
                MethodExecutionParticipant.participant_role
                == PARTICIPANT_LEAD_INSPECTOR,
            )
            .count()
        )

    def add_participant(
        self, participant: MethodExecutionParticipant
    ) -> MethodExecutionParticipant:
        self.db.add(participant)
        self.db.flush()
        return participant

    def delete_participant(
        self, participant: MethodExecutionParticipant
    ) -> None:
        self.db.delete(participant)
        self.db.flush()

    # ── Локальные результаты ──────────────────────────────────────────────────

    def get_result_item(
        self, item_id: UUID
    ) -> MethodExecutionResultItem | None:
        return (
            self.db.query(MethodExecutionResultItem)
            .filter(MethodExecutionResultItem.id == item_id)
            .first()
        )

    def list_result_items(
        self, execution_id: UUID
    ) -> list[MethodExecutionResultItem]:
        return (
            self.db.query(MethodExecutionResultItem)
            .filter(MethodExecutionResultItem.method_execution_id == execution_id)
            .order_by(
                MethodExecutionResultItem.created_at,
                MethodExecutionResultItem.id,
            )
            .all()
        )

    def effective_result_items(
        self, execution_id: UUID
    ) -> list[MethodExecutionResultItem]:
        """Действующие результаты для расчётов (§10.3): COMPLETE и не EXCLUDED."""
        return (
            self.db.query(MethodExecutionResultItem)
            .filter(
                MethodExecutionResultItem.method_execution_id == execution_id,
                MethodExecutionResultItem.record_state == RESULT_COMPLETE,
            )
            .order_by(
                MethodExecutionResultItem.created_at,
                MethodExecutionResultItem.id,
            )
            .all()
        )

    def has_excluded_items(self, execution_id: UUID) -> bool:
        return (
            self.db.query(MethodExecutionResultItem.id)
            .filter(
                MethodExecutionResultItem.method_execution_id == execution_id,
                MethodExecutionResultItem.record_state == RESULT_EXCLUDED,
            )
            .first()
            is not None
        )

    def add_result_item(
        self, item: MethodExecutionResultItem
    ) -> MethodExecutionResultItem:
        self.db.add(item)
        self.db.flush()
        return item

    # ── Стандарты ─────────────────────────────────────────────────────────────

    def list_standards(
        self, execution_id: UUID
    ) -> list[MethodExecutionStandard]:
        return (
            self.db.query(MethodExecutionStandard)
            .filter(MethodExecutionStandard.method_execution_id == execution_id)
            .order_by(
                MethodExecutionStandard.created_at, MethodExecutionStandard.id
            )
            .all()
        )

    def add_standard(
        self, standard: MethodExecutionStandard
    ) -> MethodExecutionStandard:
        self.db.add(standard)
        self.db.flush()
        return standard

    # ── Внешние лица и аккредитации ───────────────────────────────────────────

    def get_external_person(
        self, person_id: UUID
    ) -> QualityExternalPerson | None:
        return (
            self.db.query(QualityExternalPerson)
            .filter(QualityExternalPerson.id == person_id)
            .first()
        )

    def add_external_person(
        self, person: QualityExternalPerson
    ) -> QualityExternalPerson:
        self.db.add(person)
        self.db.flush()
        return person

    def get_accreditation(
        self, accreditation_id: UUID
    ) -> LaboratoryAccreditation | None:
        return (
            self.db.query(LaboratoryAccreditation)
            .filter(LaboratoryAccreditation.id == accreditation_id)
            .first()
        )

    # ── Доменный аудит (append-only) ──────────────────────────────────────────

    def add_audit_event(self, event: QualityAuditEvent) -> QualityAuditEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_audit_events(
        self, entity_type: str, entity_id: UUID
    ) -> list[QualityAuditEvent]:
        return (
            self.db.query(QualityAuditEvent)
            .filter(
                QualityAuditEvent.entity_type == entity_type,
                QualityAuditEvent.entity_id == entity_id,
            )
            .order_by(QualityAuditEvent.occurred_at, QualityAuditEvent.id)
            .all()
        )

    # ── LaboratoryConclusion (§1 блока 9C-5) ──────────────────────────────────

    def add_conclusion(self, conclusion: LaboratoryConclusion) -> LaboratoryConclusion:
        self.db.add(conclusion)
        self.db.flush()
        return conclusion

    def save_conclusion(
        self, conclusion: LaboratoryConclusion
    ) -> LaboratoryConclusion:
        self.db.commit()
        self.db.refresh(conclusion)
        return conclusion

    def get_conclusion(self, conclusion_id: UUID) -> LaboratoryConclusion | None:
        return (
            self.db.query(LaboratoryConclusion)
            .filter(LaboratoryConclusion.id == conclusion_id)
            .first()
        )

    def get_conclusion_for_update(
        self, conclusion_id: UUID
    ) -> LaboratoryConclusion | None:
        return (
            self.db.query(LaboratoryConclusion)
            .filter(LaboratoryConclusion.id == conclusion_id)
            .with_for_update()
            .first()
        )

    def list_conclusions(
        self,
        *,
        project_id: UUID | None = None,
        laboratory_company_id: int | None = None,
        status: str | None = None,
    ) -> list[LaboratoryConclusion]:
        query = self.db.query(LaboratoryConclusion)
        if project_id is not None:
            query = query.filter(LaboratoryConclusion.project_id == project_id)
        if laboratory_company_id is not None:
            query = query.filter(
                LaboratoryConclusion.laboratory_company_id == laboratory_company_id
            )
        if status is not None:
            query = query.filter(LaboratoryConclusion.status == status)
        return query.order_by(
            LaboratoryConclusion.created_at.desc(), LaboratoryConclusion.id.desc()
        ).all()

    def list_conclusion_executions(
        self, conclusion_id: UUID
    ) -> list[LaboratoryConclusionExecution]:
        return (
            self.db.query(LaboratoryConclusionExecution)
            .filter(
                LaboratoryConclusionExecution.laboratory_conclusion_id
                == conclusion_id
            )
            .order_by(
                LaboratoryConclusionExecution.created_at,
                LaboratoryConclusionExecution.id,
            )
            .all()
        )

    def get_conclusion_execution(
        self, conclusion_id: UUID, method_execution_id: UUID
    ) -> LaboratoryConclusionExecution | None:
        return (
            self.db.query(LaboratoryConclusionExecution)
            .filter(
                LaboratoryConclusionExecution.laboratory_conclusion_id
                == conclusion_id,
                LaboratoryConclusionExecution.method_execution_id
                == method_execution_id,
            )
            .first()
        )

    def add_conclusion_execution(
        self, link: LaboratoryConclusionExecution
    ) -> LaboratoryConclusionExecution:
        self.db.add(link)
        self.db.flush()
        return link

    def remove_conclusion_execution(
        self, link: LaboratoryConclusionExecution
    ) -> None:
        self.db.delete(link)
        self.db.flush()

    def get_current_conclusion_for_root(
        self, root_conclusion_id: UUID, *, exclude_id: UUID | None = None
    ) -> LaboratoryConclusion | None:
        query = self.db.query(LaboratoryConclusion).filter(
            LaboratoryConclusion.root_conclusion_id == root_conclusion_id,
            LaboratoryConclusion.is_current.is_(True),
        )
        if exclude_id is not None:
            query = query.filter(LaboratoryConclusion.id != exclude_id)
        return query.first()

    def get_current_conclusion_for_root_for_update(
        self, root_conclusion_id: UUID, *, exclude_id: UUID | None = None
    ) -> LaboratoryConclusion | None:
        query = self.db.query(LaboratoryConclusion).filter(
            LaboratoryConclusion.root_conclusion_id == root_conclusion_id,
            LaboratoryConclusion.is_current.is_(True),
        )
        if exclude_id is not None:
            query = query.filter(LaboratoryConclusion.id != exclude_id)
        return query.with_for_update().first()

    def get_latest_conclusion_revision_no(self, root_conclusion_id: UUID) -> int:
        from sqlalchemy import func as _func

        value = (
            self.db.query(_func.max(LaboratoryConclusion.revision_no))
            .filter(
                LaboratoryConclusion.root_conclusion_id == root_conclusion_id
            )
            .scalar()
        )
        return int(value or 0)

    def has_open_conclusion_revision(
        self, root_conclusion_id: UUID, *, exclude_id: UUID | None = None
    ) -> bool:
        query = self.db.query(LaboratoryConclusion.id).filter(
            LaboratoryConclusion.root_conclusion_id == root_conclusion_id,
            LaboratoryConclusion.status.in_(_OPEN_CONCLUSION_STATUSES),
        )
        if exclude_id is not None:
            query = query.filter(LaboratoryConclusion.id != exclude_id)
        return query.first() is not None

    def list_conclusion_revisions(
        self, root_conclusion_id: UUID
    ) -> list[LaboratoryConclusion]:
        return (
            self.db.query(LaboratoryConclusion)
            .filter(
                LaboratoryConclusion.root_conclusion_id == root_conclusion_id
            )
            .order_by(
                LaboratoryConclusion.revision_no, LaboratoryConclusion.created_at
            )
            .all()
        )

    def find_issued_number_conflict(
        self,
        *,
        laboratory_company_id: int,
        normalized_number: str,
        conclusion_year: int,
        exclude_root_id: UUID | None = None,
    ) -> LaboratoryConclusion | None:
        """Действующее ISSUED-заключение с тем же номером/годом иной цепочки (§5)."""
        query = self.db.query(LaboratoryConclusion).filter(
            LaboratoryConclusion.laboratory_company_id == laboratory_company_id,
            LaboratoryConclusion.normalized_conclusion_number == normalized_number,
            LaboratoryConclusion.conclusion_year == conclusion_year,
            LaboratoryConclusion.status == CONCLUSION_ISSUED,
        )
        if exclude_root_id is not None:
            query = query.filter(
                LaboratoryConclusion.root_conclusion_id != exclude_root_id
            )
        return query.first()

    def mark_conclusions_for_execution_review(
        self, method_execution_id: UUID, reason: str
    ) -> list[LaboratoryConclusion]:
        """Помечает действующие ISSUED-заключения, связанные с выполнением (§9).

        Возвращает затронутые заключения (для audit вызывающим кодом). Статус не
        меняется; связь на новую редакцию выполнения не переключается."""
        conclusion_ids = [
            row[0]
            for row in self.db.query(
                LaboratoryConclusionExecution.laboratory_conclusion_id
            )
            .filter(
                LaboratoryConclusionExecution.method_execution_id
                == method_execution_id
            )
            .all()
        ]
        if not conclusion_ids:
            return []
        conclusions = (
            self.db.query(LaboratoryConclusion)
            .filter(
                LaboratoryConclusion.id.in_(conclusion_ids),
                LaboratoryConclusion.status == CONCLUSION_ISSUED,
            )
            .all()
        )
        for conclusion in conclusions:
            conclusion.revision_review_required = True
            conclusion.revision_review_reason = reason
        if conclusions:
            self.db.flush()
        return conclusions

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, obj) -> None:
        self.db.refresh(obj)

    @staticmethod
    def ids(rows: Iterable) -> list[UUID]:
        return [row.id for row in rows]
