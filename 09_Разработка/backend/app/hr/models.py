from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base

HR_SCHEMA = "hr"


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_hr_departments_company_code"),
        {"schema": HR_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # TODO(ADR-001): FK на public.companies после появления модуля организаций.
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workers: Mapped[list[Worker]] = relationship(back_populates="department")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_hr_positions_code"),
        {"schema": HR_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workers: Mapped[list[Worker]] = relationship(back_populates="position")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint(
            "employment_status IN ('active', 'dismissed', 'suspended')",
            name="ck_hr_workers_employment_status",
        ),
        CheckConstraint(
            "(employment_status = 'dismissed') OR (dismissal_date IS NULL)",
            name="ck_hr_workers_dismissal_date",
        ),
        Index(
            "uq_hr_workers_company_personnel_number",
            "company_id",
            "personnel_number",
            unique=True,
            postgresql_where="personnel_number IS NOT NULL",
        ),
        {"schema": HR_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    personnel_number: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    birth_date: Mapped[date | None] = mapped_column(Date)
    # TODO(ADR-001): FK на public.companies после появления модуля организаций.
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{HR_SCHEMA}.departments.id"),
    )
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{HR_SCHEMA}.positions.id"),
    )
    employment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    hire_date: Mapped[date | None] = mapped_column(Date)
    dismissal_date: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    department: Mapped[Department | None] = relationship(back_populates="workers")
    position: Mapped[Position | None] = relationship(back_populates="workers")
