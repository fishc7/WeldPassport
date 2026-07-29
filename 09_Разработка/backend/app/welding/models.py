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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.hr.models import HR_SCHEMA
from app.shared.orm import Base

WELDING_SCHEMA = "welding"


class Welder(Base):
    __tablename__ = "welders"
    __table_args__ = (
        UniqueConstraint("worker_id", name="uq_welding_welders_worker_id"),
        UniqueConstraint("stamp_code", name="uq_welding_welders_stamp_code"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'suspended')",
            name="ck_welding_welders_status",
        ),
        {"schema": WELDING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    worker_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{HR_SCHEMA}.workers.id"),
        nullable=False,
    )
    stamp_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default="active"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WelderAdmission(Base):
    __tablename__ = "welder_admissions"
    __table_args__ = (
        CheckConstraint(
            "admission_status IN ('draft', 'active', 'suspended', 'expired', 'revoked')",
            name="ck_welding_welder_admissions_admission_status",
        ),
        CheckConstraint(
            "length(trim(stamp_code)) > 0",
            name="ck_welding_welder_admissions_stamp_code_not_empty",
        ),
        CheckConstraint(
            "diameter_min IS NULL OR diameter_max IS NULL OR diameter_min <= diameter_max",
            name="ck_welding_welder_admissions_diameter_range",
        ),
        CheckConstraint(
            "thickness_min IS NULL OR thickness_max IS NULL OR thickness_min <= thickness_max",
            name="ck_welding_welder_admissions_thickness_range",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_welding_welder_admissions_valid_range",
        ),
        Index(
            "ux_welding_welder_admissions_active_stamp_code",
            "stamp_code",
            unique=True,
            postgresql_where="admission_status = 'active'",
        ),
        {"schema": WELDING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    worker_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{HR_SCHEMA}.workers.id"),
        nullable=False,
        index=True,
    )
    stamp_code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    admission_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="draft", server_default="draft", index=True
    )
    welding_methods: Mapped[list] = mapped_column(JSONB, nullable=False)
    material_groups: Mapped[list] = mapped_column(JSONB, nullable=False)
    diameter_min: Mapped[Decimal | None] = mapped_column(Numeric)
    diameter_max: Mapped[Decimal | None] = mapped_column(Numeric)
    thickness_min: Mapped[Decimal | None] = mapped_column(Numeric)
    thickness_max: Mapped[Decimal | None] = mapped_column(Numeric)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    valid_until: Mapped[date | None] = mapped_column(Date, index=True)
    basis_document: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
