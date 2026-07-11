from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import asc, desc, or_, text
from sqlalchemy.orm import Session

from app.engineering.models import (
    ENGINEERING_SCHEMA,
    REQUIRED_WELDING_FIELDS,
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointBlock,
    JointEvent,
)
from app.engineering.schemas import EngineeringDocumentListFilters, JointListFilters


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

    def create_joint(self, joint: Joint) -> Joint:
        self.db.add(joint)
        self.db.commit()
        self.db.refresh(joint)
        return joint

    def save_joint(self, joint: Joint) -> Joint:
        self.db.commit()
        self.db.refresh(joint)
        return joint

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
