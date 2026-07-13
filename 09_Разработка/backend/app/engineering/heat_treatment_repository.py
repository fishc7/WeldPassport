"""Репозиторий термической обработки (Task 8F).

Инкапсулирует доступ к таблицам ``heat_treatment_*`` (add/flush без commit; commit
на границе команды сервиса, как в ``EngineeringRepo``). Другие домены к этим
таблицам напрямую не обращаются — только через сервис (модульный монолит).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.engineering.heat_treatment_schemas import HeatTreatmentBatchListFilters
from app.engineering.heat_treatment_workflow import (
    BATCH_TERMINAL_STATUSES,
    OPERATION_ACCEPTED_RESULTS,
)
from app.engineering.models import (
    HeatTreatmentBatch,
    HeatTreatmentDeviation,
    HeatTreatmentOperation,
    HeatTreatmentProcedureRevision,
    HeatTreatmentRecord,
    Joint,
    WeldOperation,
)


class HeatTreatmentRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Технологическая карта ─────────────────────────────────────────────────

    def get_procedure(self, revision_id: UUID) -> HeatTreatmentProcedureRevision | None:
        return (
            self.db.query(HeatTreatmentProcedureRevision)
            .filter(HeatTreatmentProcedureRevision.id == revision_id)
            .first()
        )

    def add_procedure(
        self, revision: HeatTreatmentProcedureRevision
    ) -> HeatTreatmentProcedureRevision:
        self.db.add(revision)
        self.db.flush()
        return revision

    def save_procedure(
        self, revision: HeatTreatmentProcedureRevision
    ) -> HeatTreatmentProcedureRevision:
        self.db.commit()
        self.db.refresh(revision)
        return revision

    # ── Цикл ──────────────────────────────────────────────────────────────────

    def get_batch(self, batch_id: UUID) -> HeatTreatmentBatch | None:
        return (
            self.db.query(HeatTreatmentBatch)
            .filter(HeatTreatmentBatch.id == batch_id)
            .first()
        )

    def get_batch_for_update(self, batch_id: UUID) -> HeatTreatmentBatch | None:
        return (
            self.db.query(HeatTreatmentBatch)
            .filter(HeatTreatmentBatch.id == batch_id)
            .with_for_update()
            .first()
        )

    def add_batch(self, batch: HeatTreatmentBatch) -> HeatTreatmentBatch:
        self.db.add(batch)
        self.db.flush()
        return batch

    def save_batch(self, batch: HeatTreatmentBatch) -> HeatTreatmentBatch:
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def _apply_batch_filters(self, query, filters: HeatTreatmentBatchListFilters):
        if filters.project_id is not None:
            query = query.filter(HeatTreatmentBatch.project_id == filters.project_id)
        if filters.procedure_revision_id is not None:
            query = query.filter(
                HeatTreatmentBatch.procedure_revision_id
                == filters.procedure_revision_id
            )
        if filters.status is not None:
            query = query.filter(HeatTreatmentBatch.status == filters.status)
        if filters.review_result is not None:
            query = query.filter(
                HeatTreatmentBatch.review_result == filters.review_result
            )
        if filters.batch_no is not None:
            query = query.filter(HeatTreatmentBatch.batch_no == filters.batch_no)
        return query

    def count_batches(self, filters: HeatTreatmentBatchListFilters) -> int:
        query = self._apply_batch_filters(
            self.db.query(func.count(HeatTreatmentBatch.id)), filters
        )
        return int(query.scalar() or 0)

    def list_batches(
        self, filters: HeatTreatmentBatchListFilters
    ) -> list[HeatTreatmentBatch]:
        query = self._apply_batch_filters(
            self.db.query(HeatTreatmentBatch), filters
        )
        return (
            query.order_by(HeatTreatmentBatch.created_at.desc())
            .limit(filters.limit)
            .offset(filters.offset)
            .all()
        )

    # ── Операции по соединениям ───────────────────────────────────────────────

    def get_operation(self, operation_id: UUID) -> HeatTreatmentOperation | None:
        return (
            self.db.query(HeatTreatmentOperation)
            .filter(HeatTreatmentOperation.id == operation_id)
            .first()
        )

    def get_operation_for_update(
        self, operation_id: UUID
    ) -> HeatTreatmentOperation | None:
        return (
            self.db.query(HeatTreatmentOperation)
            .filter(HeatTreatmentOperation.id == operation_id)
            .with_for_update()
            .first()
        )

    def add_operation(
        self, operation: HeatTreatmentOperation
    ) -> HeatTreatmentOperation:
        self.db.add(operation)
        self.db.flush()
        return operation

    def save_operation(
        self, operation: HeatTreatmentOperation
    ) -> HeatTreatmentOperation:
        self.db.commit()
        self.db.refresh(operation)
        return operation

    def list_operations_for_batch(
        self, batch_id: UUID
    ) -> list[HeatTreatmentOperation]:
        return (
            self.db.query(HeatTreatmentOperation)
            .filter(HeatTreatmentOperation.batch_id == batch_id)
            .order_by(HeatTreatmentOperation.created_at.asc())
            .all()
        )

    def list_operations_for_joint(
        self, joint_id: UUID
    ) -> list[HeatTreatmentOperation]:
        return (
            self.db.query(HeatTreatmentOperation)
            .filter(HeatTreatmentOperation.joint_id == joint_id)
            .order_by(HeatTreatmentOperation.created_at.asc())
            .all()
        )

    def count_operations_for_batch(self, batch_id: UUID) -> int:
        return int(
            self.db.query(func.count(HeatTreatmentOperation.id))
            .filter(HeatTreatmentOperation.batch_id == batch_id)
            .scalar()
            or 0
        )

    def joint_in_active_cycle(
        self, joint_id: UUID, reason: str, *, exclude_batch_id: UUID | None = None
    ) -> bool:
        """Уже включён ли Joint в другой активный цикл для того же основания (§14).

        Активный цикл — не в терминальном статусе (CLOSED/CANCELLED/REJECTED);
        учитываются только не исключённые операции."""
        query = (
            self.db.query(func.count(HeatTreatmentOperation.id))
            .join(
                HeatTreatmentBatch,
                HeatTreatmentOperation.batch_id == HeatTreatmentBatch.id,
            )
            .filter(
                HeatTreatmentOperation.joint_id == joint_id,
                HeatTreatmentOperation.reason == reason,
                HeatTreatmentOperation.status != "EXCLUDED",
                HeatTreatmentBatch.status.notin_(tuple(BATCH_TERMINAL_STATUSES)),
            )
        )
        if exclude_batch_id is not None:
            query = query.filter(HeatTreatmentOperation.batch_id != exclude_batch_id)
        return int(query.scalar() or 0) > 0

    def has_accepted_result_for_weld_operation(
        self, weld_operation_id: UUID
    ) -> bool:
        """Есть ли уже принятый актуальный результат ТО для той же WeldOperation (§14)."""
        count = (
            self.db.query(func.count(HeatTreatmentOperation.id))
            .join(
                HeatTreatmentBatch,
                HeatTreatmentOperation.batch_id == HeatTreatmentBatch.id,
            )
            .filter(
                HeatTreatmentOperation.weld_operation_id == weld_operation_id,
                HeatTreatmentOperation.status == "EVALUATED",
                HeatTreatmentOperation.result.in_(tuple(OPERATION_ACCEPTED_RESULTS)),
                HeatTreatmentBatch.status.in_(("REVIEWED", "CLOSED")),
            )
            .scalar()
        )
        return int(count or 0) > 0

    # ── Документы ─────────────────────────────────────────────────────────────

    def add_record(self, record: HeatTreatmentRecord) -> HeatTreatmentRecord:
        self.db.add(record)
        self.db.flush()
        return record

    def save_record(self, record: HeatTreatmentRecord) -> HeatTreatmentRecord:
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_record(self, record_id: UUID) -> HeatTreatmentRecord | None:
        return (
            self.db.query(HeatTreatmentRecord)
            .filter(HeatTreatmentRecord.id == record_id)
            .first()
        )

    def list_records_for_batch(self, batch_id: UUID) -> list[HeatTreatmentRecord]:
        return (
            self.db.query(HeatTreatmentRecord)
            .filter(HeatTreatmentRecord.batch_id == batch_id)
            .order_by(HeatTreatmentRecord.uploaded_at.asc())
            .all()
        )

    def _chart_count(self, batch_id: UUID, *, statuses: tuple[str, ...]) -> int:
        return int(
            self.db.query(func.count(HeatTreatmentRecord.id))
            .filter(
                HeatTreatmentRecord.batch_id == batch_id,
                HeatTreatmentRecord.record_type == "TEMPERATURE_CHART",
                HeatTreatmentRecord.status.in_(statuses),
            )
            .scalar()
            or 0
        )

    def has_uploaded_chart(self, batch_id: UUID) -> bool:
        return self._chart_count(batch_id, statuses=("UPLOADED", "VERIFIED")) > 0

    def has_verified_chart(self, batch_id: UUID) -> bool:
        return self._chart_count(batch_id, statuses=("VERIFIED",)) > 0

    # ── Отклонения ────────────────────────────────────────────────────────────

    def add_deviation(
        self, deviation: HeatTreatmentDeviation
    ) -> HeatTreatmentDeviation:
        self.db.add(deviation)
        self.db.flush()
        return deviation

    def save_deviation(
        self, deviation: HeatTreatmentDeviation
    ) -> HeatTreatmentDeviation:
        self.db.commit()
        self.db.refresh(deviation)
        return deviation

    def get_deviation(self, deviation_id: UUID) -> HeatTreatmentDeviation | None:
        return (
            self.db.query(HeatTreatmentDeviation)
            .filter(HeatTreatmentDeviation.id == deviation_id)
            .first()
        )

    def list_deviations_for_batch(
        self, batch_id: UUID
    ) -> list[HeatTreatmentDeviation]:
        return (
            self.db.query(HeatTreatmentDeviation)
            .filter(HeatTreatmentDeviation.batch_id == batch_id)
            .order_by(HeatTreatmentDeviation.created_at.asc())
            .all()
        )

    def has_open_significant_deviations(self, batch_id: UUID) -> bool:
        """Есть ли открытые значимые отклонения (MAJOR/CRITICAL, OPEN/UNDER_REVIEW)."""
        return (
            int(
                self.db.query(func.count(HeatTreatmentDeviation.id))
                .filter(
                    HeatTreatmentDeviation.batch_id == batch_id,
                    HeatTreatmentDeviation.severity.in_(("MAJOR", "CRITICAL")),
                    HeatTreatmentDeviation.status.in_(("OPEN", "UNDER_REVIEW")),
                )
                .scalar()
                or 0
            )
            > 0
        )

    def has_unreviewed_critical_deviations(self, batch_id: UUID) -> bool:
        """Есть ли нерассмотренные критические отклонения (CRITICAL, OPEN/UNDER_REVIEW)."""
        return (
            int(
                self.db.query(func.count(HeatTreatmentDeviation.id))
                .filter(
                    HeatTreatmentDeviation.batch_id == batch_id,
                    HeatTreatmentDeviation.severity == "CRITICAL",
                    HeatTreatmentDeviation.status.in_(("OPEN", "UNDER_REVIEW")),
                )
                .scalar()
                or 0
            )
            > 0
        )

    # ── Актуальность по WeldOperation (§23) ───────────────────────────────────

    def current_completed_weld_operation(
        self, joint_id: UUID
    ) -> WeldOperation | None:
        """Актуальная завершённая производственная операция Joint (§23).

        Это последняя COMPLETED-операция, не заменённая (superseded_by IS NULL) —
        актуальное звено производственной цепочки. Переварка/корректировка
        переводят прежнюю в SUPERSEDED, поэтому она перестаёт быть актуальной."""
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

    def latest_completed_weld_at(self, joint_id: UUID):
        """Максимальный completed_at среди завершённых операций Joint (для currency)."""
        return (
            self.db.query(func.max(WeldOperation.completed_at))
            .filter(
                WeldOperation.joint_id == joint_id,
                WeldOperation.lifecycle_status.in_(("COMPLETED", "SUPERSEDED")),
            )
            .scalar()
        )

    # ── Журнал (§25) ──────────────────────────────────────────────────────────

    def journal_query(
        self,
        *,
        project_id: UUID | None,
        line_id: UUID | None,
        joint_id: UUID | None,
        batch_no: str | None,
        result: str | None,
        performed_from,
        performed_to,
    ):
        """Базовый join операций/циклов/стыков/карт для строк журнала (§25).

        Возвращает query объектов (op, batch, joint, procedure); диаграмма
        добавляется отдельным запросом в сервисе, чтобы не размножать строки при
        нескольких документах."""
        query = (
            self.db.query(
                HeatTreatmentOperation,
                HeatTreatmentBatch,
                Joint,
                HeatTreatmentProcedureRevision,
            )
            .join(
                HeatTreatmentBatch,
                HeatTreatmentOperation.batch_id == HeatTreatmentBatch.id,
            )
            .join(Joint, HeatTreatmentOperation.joint_id == Joint.id)
            .outerjoin(
                HeatTreatmentProcedureRevision,
                HeatTreatmentBatch.procedure_revision_id
                == HeatTreatmentProcedureRevision.id,
            )
        )
        if project_id is not None:
            query = query.filter(HeatTreatmentBatch.project_id == project_id)
        if line_id is not None:
            query = query.filter(Joint.line_id == line_id)
        if joint_id is not None:
            query = query.filter(HeatTreatmentOperation.joint_id == joint_id)
        if batch_no is not None:
            query = query.filter(HeatTreatmentBatch.batch_no == batch_no)
        if result is not None:
            query = query.filter(HeatTreatmentOperation.result == result)
        if performed_from is not None:
            query = query.filter(
                or_(
                    and_(
                        HeatTreatmentOperation.individual_started_at.isnot(None),
                        HeatTreatmentOperation.individual_started_at >= performed_from,
                    ),
                    and_(
                        HeatTreatmentOperation.individual_started_at.is_(None),
                        HeatTreatmentBatch.actual_started_at >= performed_from,
                    ),
                )
            )
        if performed_to is not None:
            query = query.filter(
                or_(
                    and_(
                        HeatTreatmentOperation.individual_started_at.isnot(None),
                        HeatTreatmentOperation.individual_started_at <= performed_to,
                    ),
                    and_(
                        HeatTreatmentOperation.individual_started_at.is_(None),
                        HeatTreatmentBatch.actual_started_at <= performed_to,
                    ),
                )
            )
        return query.order_by(
            HeatTreatmentBatch.actual_started_at.asc().nullslast(),
            HeatTreatmentOperation.created_at.asc(),
        )

    def first_chart_document_no(self, batch_id: UUID) -> str | None:
        record = (
            self.db.query(HeatTreatmentRecord)
            .filter(
                HeatTreatmentRecord.batch_id == batch_id,
                HeatTreatmentRecord.record_type == "TEMPERATURE_CHART",
            )
            .order_by(HeatTreatmentRecord.uploaded_at.asc())
            .first()
        )
        return record.document_no if record is not None else None
