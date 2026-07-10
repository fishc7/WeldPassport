from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.projects.models import PROJECT_SCHEMA
from app.shared.db import Base

ENGINEERING_SCHEMA = "engineering"

# Допустимые типы инженерного документа (Session 004, ADR-009). Технические коды
# в верхнем регистре; предметные названия — на стороне UI.
DOCUMENT_TYPES = ("ISOMETRIC", "DRAWING", "WELD_MAP", "OTHER")

# Жизненный цикл документа/ревизии. Переходы оформляются командами, а не правкой
# поля status (история вместо перезаписи).
ENGINEERING_STATUSES = ("DRAFT", "APPROVED", "CANCELLED", "SUPERSEDED")

_DOCUMENT_TYPE_CHECK = "document_type IN (" + ", ".join(
    f"'{code}'" for code in DOCUMENT_TYPES
) + ")"

_STATUS_CHECK = "status IN (" + ", ".join(
    f"'{code}'" for code in ENGINEERING_STATUSES
) + ")"


class EngineeringDocument(Base):
    """Инженерный документ (изометрия, чертёж, карта сварки) в проекте.

    Владелец — ПТО (role_code `PTO_ENGINEER`). `line_id` необязателен: документ
    может относиться к проекту в целом либо к конкретной линии. FK на проект и
    линию — ondelete RESTRICT: документ не теряется молча при удалении контекста.
    """

    __tablename__ = "engineering_documents"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "document_no",
            name="uq_engineering_documents_project_document_no",
        ),
        CheckConstraint(
            "length(trim(document_no)) > 0",
            name="ck_engineering_documents_document_no_not_empty",
        ),
        CheckConstraint(
            _DOCUMENT_TYPE_CHECK,
            name="ck_engineering_documents_document_type",
        ),
        CheckConstraint(
            _STATUS_CHECK,
            name="ck_engineering_documents_status",
        ),
        Index("ix_engineering_documents_project_id", "project_id"),
        Index("ix_engineering_documents_line_id", "line_id"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    document_no: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    # created_by / approved_by — hr.workers.id (X-User-Id). FK не добавляем
    # (переходный период; см. ограничения плана Engineering Joints MVP).
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentRevision(Base):
    """Ревизия инженерного документа. Scope прав наследуется от документа."""

    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint(
            "engineering_document_id",
            "revision_code",
            name="uq_engineering_document_revisions_doc_revision_code",
        ),
        CheckConstraint(
            "length(trim(revision_code)) > 0",
            name="ck_engineering_document_revisions_revision_code_not_empty",
        ),
        CheckConstraint(
            _STATUS_CHECK,
            name="ck_engineering_document_revisions_status",
        ),
        Index(
            "ix_engineering_document_revisions_document_id",
            "engineering_document_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    engineering_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.engineering_documents.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    revision_code: Mapped[str] = mapped_column(String(100), nullable=False)
    issued_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
