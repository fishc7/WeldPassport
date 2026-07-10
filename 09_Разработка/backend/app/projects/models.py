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

from app.shared.db import Base

PROJECT_SCHEMA = "project"

# Допустимые роли организации в проекте (ADR-001). Технические коды в верхнем
# регистре; предметные названия — на стороне UI.
PROJECT_COMPANY_ROLE_CODES = (
    "CUSTOMER",
    "GENERAL_CONTRACTOR",
    "WELDING_CONTRACTOR",
    "NDT_LAB",
    "INSPECTION",
    "DESIGNER",
)

_ROLE_CODE_CHECK = "role_code IN (" + ", ".join(
    f"'{code}'" for code in PROJECT_COMPANY_ROLE_CODES
) + ")"


class Company(Base):
    """Минимальный реестр организаций (IP-02). Расширенная карточка отложена."""

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_project_companies_status",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_project_companies_name_not_empty",
        ),
        Index(
            "uq_project_companies_inn",
            "inn",
            unique=True,
            postgresql_where="inn IS NOT NULL",
        ),
        {"schema": PROJECT_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    # created_by — hr.workers.id (X-User-Id). FK не добавляем (ADR-001, ограничение плана).
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("code", name="uq_project_projects_code"),
        CheckConstraint(
            "status IN ('draft', 'active', 'closed')",
            name="ck_project_projects_status",
        ),
        CheckConstraint(
            "length(trim(code)) > 0",
            name="ck_project_projects_code_not_empty",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_project_projects_name_not_empty",
        ),
        {"schema": PROJECT_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProjectCompany(Base):
    """Связь многие-ко-многим companies ↔ projects (ADR-001).

    Действующее участие: valid_to IS NULL. Исторические (закрытые) участия
    сохраняются и не блокируют новую активную связь с тем же role_code.
    """

    __tablename__ = "project_companies"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_project_project_companies_valid_range",
        ),
        CheckConstraint(
            _ROLE_CODE_CHECK,
            name="ck_project_project_companies_role_code",
        ),
        Index(
            "uq_project_project_companies_active",
            "project_id",
            "company_id",
            "role_code",
            unique=True,
            postgresql_where="valid_to IS NULL",
        ),
        {"schema": PROJECT_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id"),
        nullable=False,
        index=True,
    )
    role_code: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
