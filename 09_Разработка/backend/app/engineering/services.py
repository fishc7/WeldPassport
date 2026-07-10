from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument
from app.engineering.repository import EngineeringRepo
from app.engineering.schemas import (
    DocumentRevisionCreate,
    EngineeringDocumentCreate,
    EngineeringDocumentListFilters,
)
from app.projects.repository import ProjectRepo
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.permissions import RoleRequirement, check_worker_role

# Владелец инженерных документов и ревизий — ПТО (IP-07). Технический role_code
# существующего backend.
ENGINEERING_OWNER_ROLE = "PTO_ENGINEER"


class EngineeringService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # --- права (IP-05, scope GLOBAL / PROJECT / LINE) ---

    def _forbidden(self) -> HTTPException:
        return HTTPException(
            status_code=403,
            detail="Недостаточно прав: требуется роль ПТО (PTO_ENGINEER)",
        )

    def _require_permission(
        self, worker_id: int, project_id: UUID, line_id: UUID | None
    ) -> None:
        """Единая проверка scope для создания и переходов.

        Допустимо: GLOBAL всегда; PROJECT со scope_id == project_id; LINE только
        если сущность привязана к line_id и scope_id == line_id.
        """
        requirements = [
            RoleRequirement(ENGINEERING_OWNER_ROLE, "GLOBAL"),
            RoleRequirement(ENGINEERING_OWNER_ROLE, "PROJECT", str(project_id)),
        ]
        if line_id is not None:
            requirements.append(
                RoleRequirement(ENGINEERING_OWNER_ROLE, "LINE", str(line_id))
            )
        if not any(
            check_worker_role(self._db, worker_id, req) for req in requirements
        ):
            raise self._forbidden()

    # --- консистентность project / line ---

    def _validate_project_and_line(
        self, project_id: UUID, line_id: UUID | None
    ) -> None:
        if self._projects.get_project(project_id) is None:
            raise NotFoundError("Проект", project_id)
        if line_id is not None:
            line = self._projects.get_line(line_id)
            if line is None or line.project_id != project_id:
                raise ValidationError(
                    "line_id не найден или принадлежит другому проекту"
                )

    # --- документы ---

    def get_document(self, document_id: UUID) -> EngineeringDocument:
        document = self._repo.get_document(document_id)
        if document is None:
            raise NotFoundError("Инженерный документ", document_id)
        return document

    def list_documents(
        self, filters: EngineeringDocumentListFilters
    ) -> list[EngineeringDocument]:
        return self._repo.list_documents(filters)

    def create_document(
        self, data: EngineeringDocumentCreate, *, created_by: int
    ) -> EngineeringDocument:
        # Проверка прав до обращения к БД по контексту документа.
        self._require_permission(created_by, data.project_id, data.line_id)
        self._validate_project_and_line(data.project_id, data.line_id)

        document_no = data.document_no.strip()
        if (
            self._repo.get_document_by_project_and_no(data.project_id, document_no)
            is not None
        ):
            raise ConflictError(
                "Документ с таким document_no в проекте уже существует"
            )

        document = EngineeringDocument(
            project_id=data.project_id,
            line_id=data.line_id,
            document_no=document_no,
            document_type=data.document_type,
            title=data.title,
            status="DRAFT",
            created_by=created_by,
        )
        try:
            return self._repo.create_document(document)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Документ с таким document_no в проекте уже существует"
            ) from exc

    # --- переходы документа ---

    def approve_document(
        self, document_id: UUID, *, worker_id: int
    ) -> EngineeringDocument:
        document = self.get_document(document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)
        self._apply_approve(document, worker_id=worker_id)
        return self._repo.save_document(document)

    def cancel_document(
        self, document_id: UUID, *, worker_id: int
    ) -> EngineeringDocument:
        document = self.get_document(document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)
        self._apply_cancel(document)
        return self._repo.save_document(document)

    def supersede_document(
        self, document_id: UUID, *, worker_id: int
    ) -> EngineeringDocument:
        document = self.get_document(document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)
        self._apply_supersede(document)
        return self._repo.save_document(document)

    # --- ревизии ---

    def list_revisions(self, document_id: UUID) -> list[DocumentRevision]:
        self.get_document(document_id)
        return self._repo.list_revisions(document_id)

    def create_revision(
        self, document_id: UUID, data: DocumentRevisionCreate, *, created_by: int
    ) -> DocumentRevision:
        document = self.get_document(document_id)
        # Scope ревизии наследуется от родительского документа.
        self._require_permission(created_by, document.project_id, document.line_id)

        revision_code = data.revision_code.strip()
        if (
            self._repo.get_revision_by_document_and_code(document_id, revision_code)
            is not None
        ):
            raise ConflictError(
                "Ревизия с таким revision_code в документе уже существует"
            )

        revision = DocumentRevision(
            engineering_document_id=document_id,
            revision_code=revision_code,
            issued_at=data.issued_at,
            status="DRAFT",
            created_by=created_by,
        )
        try:
            return self._repo.create_revision(revision)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Ревизия с таким revision_code в документе уже существует"
            ) from exc

    # --- переходы ревизии ---

    def _get_revision(self, revision_id: UUID) -> DocumentRevision:
        revision = self._repo.get_revision(revision_id)
        if revision is None:
            raise NotFoundError("Ревизия документа", revision_id)
        return revision

    def _require_revision_permission(
        self, revision: DocumentRevision, *, worker_id: int
    ) -> None:
        document = self.get_document(revision.engineering_document_id)
        self._require_permission(worker_id, document.project_id, document.line_id)

    def approve_revision(
        self, revision_id: UUID, *, worker_id: int
    ) -> DocumentRevision:
        revision = self._get_revision(revision_id)
        self._require_revision_permission(revision, worker_id=worker_id)
        self._apply_approve(revision, worker_id=worker_id)
        return self._repo.save_revision(revision)

    def cancel_revision(
        self, revision_id: UUID, *, worker_id: int
    ) -> DocumentRevision:
        revision = self._get_revision(revision_id)
        self._require_revision_permission(revision, worker_id=worker_id)
        self._apply_cancel(revision)
        return self._repo.save_revision(revision)

    def supersede_revision(
        self, revision_id: UUID, *, worker_id: int
    ) -> DocumentRevision:
        revision = self._get_revision(revision_id)
        self._require_revision_permission(revision, worker_id=worker_id)
        self._apply_supersede(revision)
        return self._repo.save_revision(revision)

    # --- централизованные правила переходов ---
    #
    # Переход разрешён только из явно допустимых исходных статусов; иначе 409.
    # Правила общие для EngineeringDocument и DocumentRevision (одинаковый набор
    # статусов). Обобщённого update поля status нет — только эти команды.

    @staticmethod
    def _apply_approve(
        entity: EngineeringDocument | DocumentRevision, *, worker_id: int
    ) -> None:
        if entity.status != "DRAFT":
            raise ConflictError(
                f"Утверждение недопустимо из статуса {entity.status}"
            )
        entity.status = "APPROVED"
        entity.approved_by = worker_id
        entity.approved_at = datetime.now(timezone.utc)

    @staticmethod
    def _apply_cancel(entity: EngineeringDocument | DocumentRevision) -> None:
        if entity.status not in ("DRAFT", "APPROVED"):
            raise ConflictError(f"Отмена недопустима из статуса {entity.status}")
        # approved_by/approved_at сохраняются: отмена ранее утверждённой сущности
        # не стирает факт утверждения (история вместо перезаписи).
        entity.status = "CANCELLED"

    @staticmethod
    def _apply_supersede(entity: EngineeringDocument | DocumentRevision) -> None:
        if entity.status != "APPROVED":
            raise ConflictError(f"Замена недопустима из статуса {entity.status}")
        entity.status = "SUPERSEDED"
