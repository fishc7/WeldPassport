"""ORM-модели официального решения по дефекту — DefectDisposition (Task 9D-4A).

Физические таблицы схемы `quality`:

* `defect_dispositions` — исполняемое решение по цепочке дефекта (9D-4A-2);
* `defect_disposition_events` — append-only аудит переходов (9D-4A-3; CHECK типов
  события расширен под `DISPOSITION_SUPERSEDED` миграцией `20260721_24_disp_supersede`,
  Task 9D-4A-4 — миграции `22`/`23` задним числом не меняются).

Решение привязано к `DefectRoot` (цепочке версий дефекта), а не к конкретной
технической ревизии `Defect`: техническая ревизия может быть заменена через supersede,
а официальное решение относится к дефекту как таковому и должно переживать такую
замену. Инвариант «одно действующее решение на дефект» реализован частичным UNIQUE
по `defect_root_id WHERE status = 'ACTIVE'` — тем же приёмом, что
`uq_defects_one_active_per_root` в 9D-3A.

Стиль Tasks 9A–9D-3: перечисления — CHECK (без native enum); actor-поля
(`*_by_worker_id`) — hr.workers.id типа Integer БЕЗ FK (переходный период); время —
`timestamptz`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.quality.defect_models import DEFECT_ROOTS_TABLE, QUALITY_SCHEMA
from app.shared.orm import Base

DEFECT_DISPOSITIONS_TABLE = "defect_dispositions"
DEFECT_DISPOSITION_EVENTS_TABLE = "defect_disposition_events"

# ── Тип решения (Task 9D-4A) ───────────────────────────────────────────────────
DEFECT_DISPOSITION_DECISION_TYPES: tuple[str, ...] = (
    "REPAIR_REQUIRED",
    "REINSPECTION_REQUIRED",
    "ACCEPT_AS_IS",
    "REJECT_JOINT",
)

DEFECT_DISPOSITION_REPAIR_REQUIRED = "REPAIR_REQUIRED"
DEFECT_DISPOSITION_REINSPECTION_REQUIRED = "REINSPECTION_REQUIRED"
DEFECT_DISPOSITION_ACCEPT_AS_IS = "ACCEPT_AS_IS"
DEFECT_DISPOSITION_REJECT_JOINT = "REJECT_JOINT"

# ── Жизненный цикл решения (полный канонический набор фиксируется сразу, как в
# 9A/9D-1/9D-3A, чтобы последующие блоки не переписывали CHECK) ─────────────────
DEFECT_DISPOSITION_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "PREPARED",
    "APPROVED",
    "ACTIVE",
    "SUPERSEDED",
    "CANCELLED",
)

DEFECT_DISPOSITION_DRAFT = "DRAFT"
DEFECT_DISPOSITION_PREPARED = "PREPARED"
DEFECT_DISPOSITION_APPROVED = "APPROVED"
DEFECT_DISPOSITION_ACTIVE = "ACTIVE"
DEFECT_DISPOSITION_SUPERSEDED = "SUPERSEDED"
DEFECT_DISPOSITION_CANCELLED = "CANCELLED"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class DefectDisposition(Base):
    """Официальное исполняемое решение по цепочке дефекта (`DefectRoot`).

    Обоснование (`justification`) обязательно на уровне БД: решение без объяснимого
    основания недопустимо (правило «допуск/решение — результат правил, а не флаг»).
    `comment` — свободный комментарий, `supersede_reason` — причина замены решения.
    Коррекция решения выполняется только через supersede (новая запись,
    `supersedes_disposition_id` → предыдущая); перезаписи истории нет.
    """

    __tablename__ = DEFECT_DISPOSITIONS_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("decision_type", DEFECT_DISPOSITION_DECISION_TYPES),
            name="ck_defect_dispositions_decision_type",
        ),
        CheckConstraint(
            _in("status", DEFECT_DISPOSITION_STATUSES),
            name="ck_defect_dispositions_status",
        ),
        CheckConstraint(
            "length(trim(justification)) > 0",
            name="ck_defect_dispositions_justification_not_empty",
        ),
        # Решение не может замещать само себя (принадлежность одной цепочке дефекта
        # проверяет сервис; self-reference безопасно закрывается CHECK).
        CheckConstraint(
            "supersedes_disposition_id IS NULL OR supersedes_disposition_id <> id",
            name="ck_defect_dispositions_no_self_supersede",
        ),
        # Утверждение фиксируется парой actor+time целиком либо не фиксируется вовсе.
        CheckConstraint(
            "(approved_at IS NULL) = (approved_by_worker_id IS NULL)",
            name="ck_defect_dispositions_approved_pair",
        ),
        # Одно действующее решение на один дефект (цепочку версий).
        Index(
            "uq_defect_dispositions_one_active_per_root",
            "defect_root_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_defect_dispositions_defect_root_id", "defect_root_id"),
        Index("ix_defect_dispositions_root_status", "defect_root_id", "status"),
        Index("ix_defect_dispositions_created_by", "created_by_worker_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    defect_root_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{DEFECT_ROOTS_TABLE}.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    supersedes_disposition_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{DEFECT_DISPOSITIONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )

    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=DEFECT_DISPOSITION_DRAFT
    )

    justification: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    supersede_reason: Mapped[str | None] = mapped_column(Text)

    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _in_event(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


# Импорт типов событий после констант статусов — избегаем циклов при seed.
# Значения дублируются строками в CHECK миграции; канон — defect_disposition_workflow.
# DISPOSITION_SUPERSEDED добавлен миграцией 20260721_24_disp_supersede (Task 9D-4A-4).
_DISPOSITION_EVENT_TYPES: tuple[str, ...] = (
    "DISPOSITION_CREATED",
    "DISPOSITION_PREPARED",
    "DISPOSITION_APPROVED",
    "DISPOSITION_ACTIVATED",
    "DISPOSITION_CANCELLED",
    "DISPOSITION_SUPERSEDED",
)


class DefectDispositionEvent(Base):
    """Неизменяемое событие перехода DefectDisposition (append-only, Task 9D-4A-3/9D-4A-4).

    API изменения/удаления событий нет. `actor_worker_id` — hr.workers.id (Integer
    без FK). `action` — команда перехода (`PREPARE`/`APPROVE`/`ACTIVATE`/`CANCEL`),
    `CREATE` при создании либо `SUPERSEDE` (9D-4A-4: пишется для старой версии при
    `ACTIVE → SUPERSEDED`; для новой версии — обычный `DISPOSITION_CREATED`).
    """

    __tablename__ = DEFECT_DISPOSITION_EVENTS_TABLE
    __table_args__ = (
        CheckConstraint(
            _in_event("event_type", _DISPOSITION_EVENT_TYPES),
            name="ck_defect_disposition_events_type",
        ),
        Index(
            "ix_defect_disposition_events_disposition_id",
            "defect_disposition_id",
            "created_at",
        ),
        Index(
            "ix_defect_disposition_events_root_id",
            "defect_root_id",
            "created_at",
        ),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    defect_disposition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{DEFECT_DISPOSITIONS_TABLE}.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    defect_root_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{DEFECT_ROOTS_TABLE}.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str | None] = mapped_column(String(30))
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
