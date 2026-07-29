from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.orm import Base

PROJECT_SCHEMA = "project"

# Допустимые статусы линии (Task 3, IP-08).
LINE_STATUSES = ("draft", "active", "cancelled")

_LINE_STATUS_CHECK = "status IN (" + ", ".join(
    f"'{code}'" for code in LINE_STATUSES
) + ")"

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


class Line(Base):
    """Технологическая линия (изометрия) в проекте (Task 3, ADR-009 004-25).

    Владелец — ПТО (role_code `PTO_ENGINEER`, IP-08). `required_inspection_types` —
    снимок требуемых видов контроля для будущего копирования в Joint; хранится как
    пустой массив, не NULL. FK на проект — ondelete RESTRICT: линия не теряется
    молча при попытке удалить проект.
    """

    __tablename__ = "lines"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "line_no", name="uq_project_lines_project_line_no"
        ),
        CheckConstraint(
            "length(trim(line_no)) > 0",
            name="ck_project_lines_line_no_not_empty",
        ),
        CheckConstraint(
            "nominal_dn IS NULL OR nominal_dn > 0",
            name="ck_project_lines_nominal_dn_positive",
        ),
        CheckConstraint(
            _LINE_STATUS_CHECK,
            name="ck_project_lines_status",
        ),
        Index("ix_project_lines_project_id", "project_id"),
        {"schema": PROJECT_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_no: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    medium: Mapped[str | None] = mapped_column(String(255))
    nominal_dn: Mapped[Decimal | None] = mapped_column(Numeric)
    class_code: Mapped[str | None] = mapped_column(String(50))
    category_code: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    required_inspection_types: Mapped[list[str]] = mapped_column(
        PGARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    # created_by — hr.workers.id (X-User-Id). FK не добавляем (ограничение плана).
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
