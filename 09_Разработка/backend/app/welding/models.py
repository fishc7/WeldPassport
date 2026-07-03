from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.hr.models import HR_SCHEMA
from app.shared.db import Base

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
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
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
