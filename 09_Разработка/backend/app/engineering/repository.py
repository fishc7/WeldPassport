from uuid import UUID

from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument
from app.engineering.schemas import EngineeringDocumentListFilters


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
