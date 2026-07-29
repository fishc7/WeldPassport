from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import asc, desc, func, or_, text
from sqlalchemy.orm import Session

from app.engineering.models import (
    ENGINEERING_SCHEMA,
    REQUIRED_WELDING_FIELDS,
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointBlock,
    JointBulkRequest,
    JointDocumentRevision,
    JointEvent,
    WeldOperation,
    WeldOperationCorrection,
    WeldOperationOgsReview,
    WeldOperationWelderConfirmation,
)
from app.engineering.weld_operation_corrections import ACTIVE_LIFECYCLE_STATUSES
from app.engineering.schemas import (
    EngineeringDocumentListFilters,
    JointListFilters,
    WeldOperationListFilters,
)


def _ready_for_welding_clauses():
    """SQL-предикаты «поле заполнено» для каждого обязательного поля сварки.

    Строятся из того же REQUIRED_WELDING_FIELDS, что использует сервис для
    вычисления missing_welding_requirements — единый источник правды.
    """
    return [getattr(Joint, name).isnot(None) for name in REQUIRED_WELDING_FIELDS]


class EngineeringRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- engineering_documents ---

    def get_document(self, document_id: UUID) -> EngineeringDocument | None:
        return (
            self.db.query(EngineeringDocument)
            .filter(EngineeringDocument.id == document_id)
            .first()
        )

    def get_document_by_project_and_no(
        self, project_id: UUID, document_no: str
    ) -> EngineeringDocument | None:
        return (
            self.db.query(EngineeringDocument)
            .filter(
                EngineeringDocument.project_id == project_id,
                EngineeringDocument.document_no == document_no,
            )
            .first()
        )

    def list_documents(
        self, filters: EngineeringDocumentListFilters
    ) -> list[EngineeringDocument]:
        q = self.db.query(EngineeringDocument)
        if filters.project_id is not None:
            q = q.filter(EngineeringDocument.project_id == filters.project_id)
        if filters.line_id is not None:
            q = q.filter(EngineeringDocument.line_id == filters.line_id)
        if filters.document_type is not None:
            q = q.filter(EngineeringDocument.document_type == filters.document_type)
        if filters.status is not None:
            q = q.filter(EngineeringDocument.status == filters.status)
        return (
            q.order_by(
                EngineeringDocument.document_no, EngineeringDocument.created_at
            )
            .offset(filters.skip)
            .limit(filters.limit)
            .all()
        )

    def create_document(self, document: EngineeringDocument) -> EngineeringDocument:
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def save_document(self, document: EngineeringDocument) -> EngineeringDocument:
        self.db.commit()
        self.db.refresh(document)
        return document

    # --- document_revisions ---

    def get_revision(self, revision_id: UUID) -> DocumentRevision | None:
        return (
            self.db.query(DocumentRevision)
            .filter(DocumentRevision.id == revision_id)
            .first()
        )

    def get_revision_by_document_and_code(
        self, document_id: UUID, revision_code: str
    ) -> DocumentRevision | None:
        return (
            self.db.query(DocumentRevision)
            .filter(
                DocumentRevision.engineering_document_id == document_id,
                DocumentRevision.revision_code == revision_code,
            )
            .first()
        )

    def list_revisions(self, document_id: UUID) -> list[DocumentRevision]:
        return (
            self.db.query(DocumentRevision)
            .filter(DocumentRevision.engineering_document_id == document_id)
            .order_by(DocumentRevision.created_at, DocumentRevision.revision_code)
            .all()
        )

    def create_revision(self, revision: DocumentRevision) -> DocumentRevision:
        self.db.add(revision)
        self.db.commit()
        self.db.refresh(revision)
        return revision

    def save_revision(self, revision: DocumentRevision) -> DocumentRevision:
        self.db.commit()
        self.db.refresh(revision)
        return revision

    # --- joints (Task 5A) ---

    def next_system_sequence(self, project_id: UUID) -> int:
        """Атомарно выдаёт следующий номер последовательности проекта.

        `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` берёт блокировку строки
        счётчика: параллельные транзакции сериализуются, гонки `MAX()+1` нет.
        Выполняется в текущей транзакции сессии; коммит — вместе с INSERT стыка.
        """
        result = self.db.execute(
            text(
                f"""
                INSERT INTO {ENGINEERING_SCHEMA}.joint_sequences
                    (project_id, last_value)
                VALUES (CAST(:pid AS uuid), 1)
                ON CONFLICT (project_id)
                DO UPDATE SET last_value =
                    {ENGINEERING_SCHEMA}.joint_sequences.last_value + 1
                RETURNING last_value
                """
            ),
            {"pid": str(project_id)},
        )
        return int(result.scalar_one())

    def get_joint(self, joint_id: UUID) -> Joint | None:
        return self.db.query(Joint).filter(Joint.id == joint_id).first()

    def get_joint_by_revision_and_normalized(
        self, *, current_document_revision_id: UUID, joint_no_normalized: str
    ) -> Joint | None:
        return (
            self.db.query(Joint)
            .filter(
                Joint.current_document_revision_id == current_document_revision_id,
                Joint.joint_no_normalized == joint_no_normalized,
                Joint.status.notin_(("CANCELLED", "SUPERSEDED")),
            )
            .first()
        )

    def find_active_joint_numbers_for_revision(
        self,
        document_revision_id: UUID,
        normalized_joint_numbers: set[str],
    ) -> set[str]:
        """Нормализованные номера из набора, уже существующие как активные Joint в
        данной ревизии. Один запрос (`IN`) — без N+1 при проверке пакета (§13)."""
        if not normalized_joint_numbers:
            return set()
        rows = (
            self.db.query(Joint.joint_no_normalized)
            .filter(
                Joint.current_document_revision_id == document_revision_id,
                Joint.joint_no_normalized.in_(normalized_joint_numbers),
                Joint.status.notin_(("CANCELLED", "SUPERSEDED")),
            )
            .all()
        )
        return {row[0] for row in rows}

    def _apply_joint_filters(self, query, filters: JointListFilters):
        if filters.project_id is not None:
            query = query.filter(Joint.project_id == filters.project_id)
        if filters.line_id is not None:
            query = query.filter(Joint.line_id == filters.line_id)
        if filters.current_document_revision_id is not None:
            query = query.filter(
                Joint.current_document_revision_id
                == filters.current_document_revision_id
            )
        if filters.system_code is not None:
            query = query.filter(Joint.system_code == filters.system_code)
        if filters.joint_no_normalized is not None:
            query = query.filter(
                Joint.joint_no_normalized == filters.joint_no_normalized
            )
        if filters.geometry_type is not None:
            query = query.filter(Joint.geometry_type == filters.geometry_type)
        if filters.weld_joint_type is not None:
            query = query.filter(Joint.weld_joint_type == filters.weld_joint_type)
        if filters.ready_for_welding is not None:
            clauses = _ready_for_welding_clauses()
            if filters.ready_for_welding:
                for clause in clauses:
                    query = query.filter(clause)
            else:
                query = query.filter(or_(*[getattr(Joint, n).is_(None)
                                           for n in REQUIRED_WELDING_FIELDS]))
        return query

    def count_joints(self, filters: JointListFilters) -> int:
        query = self._apply_joint_filters(self.db.query(Joint), filters)
        return query.count()

    def list_joints(self, filters: JointListFilters) -> list[Joint]:
        query = self._apply_joint_filters(self.db.query(Joint), filters)
        sort_column = getattr(Joint, filters.sort_by)
        direction = desc if filters.sort_order == "desc" else asc
        # id как вторичный ключ сортировки — стабильный порядок при равных значениях.
        query = query.order_by(direction(sort_column), asc(Joint.id))
        return query.offset(filters.offset).limit(filters.limit).all()

    def add_joint(self, joint: Joint) -> Joint:
        """Добавляет Joint в текущую транзакцию (add + flush, без commit).

        Позволяет создать Joint и связанную ORIGIN-запись истории ревизий одной
        транзакцией (Task 6): id стыка доступен сразу после flush.
        """
        self.db.add(joint)
        self.db.flush()
        return joint

    def save_joint(self, joint: Joint) -> Joint:
        self.db.commit()
        self.db.refresh(joint)
        return joint

    # --- joint ↔ document_revision links (Task 6) ---

    def add_link(self, link: JointDocumentRevision) -> JointDocumentRevision:
        """Добавляет связь-снимок в текущую транзакцию (add + flush, без commit)."""
        self.db.add(link)
        self.db.flush()
        return link

    def save_link(self, link: JointDocumentRevision) -> JointDocumentRevision:
        self.db.commit()
        self.db.refresh(link)
        return link

    def get_link(self, link_id: UUID) -> JointDocumentRevision | None:
        return (
            self.db.query(JointDocumentRevision)
            .filter(JointDocumentRevision.id == link_id)
            .first()
        )

    def list_links(
        self,
        joint_id: UUID,
        *,
        link_status: str | None = None,
        document_role: str | None = None,
        revision_role: str | None = None,
    ) -> list[JointDocumentRevision]:
        query = self.db.query(JointDocumentRevision).filter(
            JointDocumentRevision.joint_id == joint_id
        )
        if link_status is not None:
            query = query.filter(JointDocumentRevision.link_status == link_status)
        if document_role is not None:
            query = query.filter(
                JointDocumentRevision.document_role == document_role
            )
        if revision_role is not None:
            query = query.filter(
                JointDocumentRevision.revision_role == revision_role
            )
        # Стабильная сортировка: created_at, затем id (§8 задания).
        return query.order_by(
            JointDocumentRevision.created_at, JointDocumentRevision.id
        ).all()

    def active_primary_link(
        self, joint_id: UUID
    ) -> JointDocumentRevision | None:
        return (
            self.db.query(JointDocumentRevision)
            .filter(
                JointDocumentRevision.joint_id == joint_id,
                JointDocumentRevision.link_status == "ACTIVE",
                JointDocumentRevision.document_role == "PRIMARY",
            )
            .first()
        )

    # --- joint blocks (Task 5B) ---

    def add_block(self, block: JointBlock) -> JointBlock:
        """Добавляет запись блокировки в текущую транзакцию (без commit)."""
        self.db.add(block)
        self.db.flush()
        return block

    def get_block(self, block_id: UUID) -> JointBlock | None:
        return self.db.query(JointBlock).filter(JointBlock.id == block_id).first()

    def list_blocks(self, joint_id: UUID) -> list[JointBlock]:
        return (
            self.db.query(JointBlock)
            .filter(JointBlock.joint_id == joint_id)
            .order_by(JointBlock.created_at, JointBlock.id)
            .all()
        )

    def active_blocks(self, joint_id: UUID) -> list[JointBlock]:
        return (
            self.db.query(JointBlock)
            .filter(
                JointBlock.joint_id == joint_id,
                JointBlock.released_at.is_(None),
            )
            .all()
        )

    def blocked_joint_ids(self, joint_ids: Iterable[UUID]) -> set[UUID]:
        """Множество joint_id из набора, имеющих хотя бы одну активную блокировку.

        Один агрегатный запрос — без N+1 при построении списка (§23 ADR-011)."""
        ids = list(joint_ids)
        if not ids:
            return set()
        rows = (
            self.db.query(JointBlock.joint_id)
            .filter(
                JointBlock.joint_id.in_(ids),
                JointBlock.released_at.is_(None),
            )
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    # --- joint events (Task 5B, append-only) ---

    def add_event(self, event: JointEvent) -> JointEvent:
        """Добавляет событие истории в текущую транзакцию (без commit)."""
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(self, joint_id: UUID) -> list[JointEvent]:
        return (
            self.db.query(JointEvent)
            .filter(JointEvent.joint_id == joint_id)
            .order_by(JointEvent.created_at, JointEvent.id)
            .all()
        )

    # --- joint bulk requests (Task 7, идемпотентность) ---

    def get_joint_bulk_request(
        self, project_id: UUID, idempotency_key: str
    ) -> JointBulkRequest | None:
        return (
            self.db.query(JointBulkRequest)
            .filter(
                JointBulkRequest.project_id == project_id,
                JointBulkRequest.idempotency_key == idempotency_key,
            )
            .first()
        )

    def add_joint_bulk_request(
        self, request: JointBulkRequest
    ) -> JointBulkRequest:
        """Добавляет запись пакета в текущую транзакцию (add + flush, без commit).

        Commit — вместе с созданными Joint и связями (один commit на пакет)."""
        self.db.add(request)
        self.db.flush()
        return request

    # --- weld operations (Task 8A) ---

    def next_weld_operation_sequence(self, joint_id: UUID) -> int:
        """Атомарно выдаёт следующий sequence_no операции внутри Joint.

        Блокирует строку Joint (`SELECT ... FOR UPDATE`) на время транзакции:
        параллельное создание операций одного Joint сериализуется, гонки `MAX()+1`
        нет. Уникальный индекс (joint_id, sequence_no) — последняя защита. Номера
        монотонно растут внутри Joint (§9 задания)."""
        self.db.execute(
            text(
                f"SELECT 1 FROM {ENGINEERING_SCHEMA}.joints "
                "WHERE id = CAST(:jid AS uuid) FOR UPDATE"
            ),
            {"jid": str(joint_id)},
        )
        current = (
            self.db.query(func.coalesce(func.max(WeldOperation.sequence_no), 0))
            .filter(WeldOperation.joint_id == joint_id)
            .scalar()
        )
        return int(current) + 1

    def get_operation(self, operation_id: UUID) -> WeldOperation | None:
        return (
            self.db.query(WeldOperation)
            .filter(WeldOperation.id == operation_id)
            .first()
        )

    def add_operation(self, operation: WeldOperation) -> WeldOperation:
        """Добавляет операцию в текущую транзакцию (add + flush, без commit)."""
        self.db.add(operation)
        self.db.flush()
        return operation

    def save_operation(self, operation: WeldOperation) -> WeldOperation:
        self.db.commit()
        self.db.refresh(operation)
        return operation

    def _apply_operation_filters(self, query, filters: WeldOperationListFilters):
        # project_id / line_id хранятся на Joint — присоединяем стык при фильтрации.
        if filters.project_id is not None or filters.line_id is not None:
            query = query.join(Joint, WeldOperation.joint_id == Joint.id)
            if filters.project_id is not None:
                query = query.filter(Joint.project_id == filters.project_id)
            if filters.line_id is not None:
                query = query.filter(Joint.line_id == filters.line_id)
        if filters.joint_id is not None:
            query = query.filter(WeldOperation.joint_id == filters.joint_id)
        if filters.actual_welder_id is not None:
            query = query.filter(
                WeldOperation.actual_welder_id == filters.actual_welder_id
            )
        if filters.responsible_worker_id is not None:
            query = query.filter(
                WeldOperation.responsible_worker_id == filters.responsible_worker_id
            )
        if filters.lifecycle_status is not None:
            query = query.filter(
                WeldOperation.lifecycle_status == filters.lifecycle_status
            )
        if filters.weld_stage is not None:
            query = query.filter(WeldOperation.weld_stage == filters.weld_stage)
        if filters.welding_method is not None:
            query = query.filter(
                WeldOperation.welding_method == filters.welding_method
            )
        if filters.qualification_validation_status is not None:
            query = query.filter(
                WeldOperation.qualification_validation_status
                == filters.qualification_validation_status
            )
        if filters.wps_validation_status is not None:
            query = query.filter(
                WeldOperation.wps_validation_status
                == filters.wps_validation_status
            )
        if filters.welder_confirmation_status is not None:
            query = query.filter(
                WeldOperation.welder_confirmation_status
                == filters.welder_confirmation_status
            )
        if filters.ogs_review_status is not None:
            query = query.filter(
                WeldOperation.ogs_review_status == filters.ogs_review_status
            )
        if filters.performed_from is not None:
            query = query.filter(WeldOperation.performed_on >= filters.performed_from)
        if filters.performed_to is not None:
            query = query.filter(WeldOperation.performed_on <= filters.performed_to)
        return query

    def count_operations(self, filters: WeldOperationListFilters) -> int:
        query = self._apply_operation_filters(self.db.query(WeldOperation), filters)
        return query.count()

    def list_operations(
        self, filters: WeldOperationListFilters
    ) -> list[WeldOperation]:
        query = self._apply_operation_filters(self.db.query(WeldOperation), filters)
        # Стабильный порядок: по Joint, затем по номеру операции.
        query = query.order_by(
            asc(WeldOperation.joint_id), asc(WeldOperation.sequence_no)
        )
        return query.offset(filters.offset).limit(filters.limit).all()

    # --- weld operation confirmation / review history (Task 8C, append-only) ---

    def get_operation_for_update(
        self, operation_id: UUID
    ) -> WeldOperation | None:
        """Операция с блокировкой строки (`FOR UPDATE`) для команд Task 8C.

        Сериализует параллельные confirmation/review одной операции: проверка
        версий, вставка history и обновление projection выполняются атомарно."""
        return (
            self.db.query(WeldOperation)
            .filter(WeldOperation.id == operation_id)
            .with_for_update()
            .first()
        )

    def add_welder_confirmation(
        self, record: WeldOperationWelderConfirmation
    ) -> WeldOperationWelderConfirmation:
        """Добавляет запись подтверждения в текущую транзакцию (без commit)."""
        self.db.add(record)
        self.db.flush()
        return record

    def list_welder_confirmations(
        self, operation_id: UUID
    ) -> list[WeldOperationWelderConfirmation]:
        return (
            self.db.query(WeldOperationWelderConfirmation)
            .filter(
                WeldOperationWelderConfirmation.weld_operation_id == operation_id
            )
            .order_by(asc(WeldOperationWelderConfirmation.confirmation_version))
            .all()
        )

    def add_ogs_review(
        self, record: WeldOperationOgsReview
    ) -> WeldOperationOgsReview:
        """Добавляет запись review ОГС в текущую транзакцию (без commit)."""
        self.db.add(record)
        self.db.flush()
        return record

    def count_ogs_reviews(self, operation_id: UUID) -> int:
        """Число явных решений ОГС по операции (§10.1: есть ли явный review)."""
        return (
            self.db.query(func.count(WeldOperationOgsReview.id))
            .filter(WeldOperationOgsReview.weld_operation_id == operation_id)
            .scalar()
        )

    def list_ogs_reviews(
        self, operation_id: UUID
    ) -> list[WeldOperationOgsReview]:
        return (
            self.db.query(WeldOperationOgsReview)
            .filter(WeldOperationOgsReview.weld_operation_id == operation_id)
            .order_by(asc(WeldOperationOgsReview.review_version))
            .all()
        )

    # --- weld operation corrections (Task 8D) ---

    def get_correction(
        self, correction_id: UUID
    ) -> WeldOperationCorrection | None:
        return (
            self.db.query(WeldOperationCorrection)
            .filter(WeldOperationCorrection.id == correction_id)
            .first()
        )

    def get_correction_for_update(
        self, correction_id: UUID
    ) -> WeldOperationCorrection | None:
        """Корректировка с блокировкой строки (`FOR UPDATE`) для атомарного
        применения (§15.1): сериализует конкурентные apply одной корректировки."""
        return (
            self.db.query(WeldOperationCorrection)
            .filter(WeldOperationCorrection.id == correction_id)
            .with_for_update()
            .first()
        )

    def add_correction(
        self, correction: WeldOperationCorrection
    ) -> WeldOperationCorrection:
        """Добавляет корректировку в текущую транзакцию (add + flush, без commit)."""
        self.db.add(correction)
        self.db.flush()
        return correction

    def save_correction(
        self, correction: WeldOperationCorrection
    ) -> WeldOperationCorrection:
        self.db.commit()
        self.db.refresh(correction)
        return correction

    def find_active_correction(
        self, source_operation_id: UUID
    ) -> WeldOperationCorrection | None:
        """Активная (DRAFT/SUBMITTED/APPROVED) корректировка исходной операции.

        Не более одной по partial unique index (§12); здесь предварительная
        проверка перед вставкой, финальная защита — сам индекс."""
        return (
            self.db.query(WeldOperationCorrection)
            .filter(
                WeldOperationCorrection.source_operation_id == source_operation_id,
                WeldOperationCorrection.lifecycle_status.in_(
                    tuple(ACTIVE_LIFECYCLE_STATUSES)
                ),
            )
            .first()
        )

    def list_corrections(
        self, source_operation_id: UUID
    ) -> list[WeldOperationCorrection]:
        """Полная история корректировок операции (§13.2): включая завершённые и
        отклонённые. Стабильный порядок — по времени создания."""
        return (
            self.db.query(WeldOperationCorrection)
            .filter(
                WeldOperationCorrection.source_operation_id == source_operation_id
            )
            .order_by(
                asc(WeldOperationCorrection.created_at),
                asc(WeldOperationCorrection.id),
            )
            .all()
        )
