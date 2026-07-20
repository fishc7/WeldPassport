"""ORM-модели технической модели Defect (Task 9D-3A, ADR-022).

Шесть физических таблиц схемы `quality`:

* `defect_roots` — корневая идентичность одной цепочки версий (`defect_root`); 1 к 1 с
  `EngineeringEvaluation(CONFIRMED_DEFECT)` через `UNIQUE(engineering_evaluation_id)`;
  несёт per-joint `defect_no` (`UNIQUE(joint_id, defect_no)`) и указатели на текущую и
  действующую ревизии (плоский UUID БЕЗ FK — разрыв цикла, как в 9D-2A);
* `defects` — техническая ревизия дефекта: `defect_root_id`, `revision_no`,
  `supersedes_defect_id`, статус, полный набор структурированных характеристик ADR-022 §5
  (nullable в `DRAFT`; enum-/range-/bounded-CHECK при NOT NULL). Ровно одна `ACTIVE` и не
  более одной открытой `DRAFT` на цепочку — частичные UNIQUE-индексы;
* `defect_types`, `defect_location_types` — системные read-only справочники (без actor);
* `defect_sequences` — per-joint счётчик `defect_no`;
* `defect_events` — неизменяемый журнал (append-only).

Стиль Tasks 9A–9D-2: перечисления — CHECK (без native enum); actor-поля
(`*_by_worker_id`/`actor_worker_id`) — hr.workers.id типа Integer БЕЗ FK (переходный
период); `version` — optimistic locking; физического удаления нет (кроме будущей
бизнес-логики 9D-3B). Существенные технические поля неизменяемы после активации —
инвариант домена (сервис 9D-3B), не CHECK.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering.models import ENGINEERING_SCHEMA
from app.quality import defect_workflow as dw
from app.shared.db import Base

# Дублируется намеренно (как в quality_finding_models): независимый импорт модуля.
QUALITY_SCHEMA = "quality"

DEFECT_ROOTS_TABLE = "defect_roots"
DEFECTS_TABLE = "defects"
DEFECT_TYPES_TABLE = "defect_types"
DEFECT_LOCATION_TYPES_TABLE = "defect_location_types"
DEFECT_SEQUENCES_TABLE = "defect_sequences"
DEFECT_EVENTS_TABLE = "defect_events"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _null_or_in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {_in(column, values)}"


class DefectType(Base):
    """Системный read-only справочник типов дефектов (ADR-022 §5; Spec §3.3).

    Значения меняются только контролируемой миграцией; CRUD и project/company scope
    не вводятся. Флаги `requires_*` управляют обязательностью измерений/описания при
    активации (валидация — 9D-3B).
    """

    __tablename__ = DEFECT_TYPES_TABLE
    __table_args__ = (
        CheckConstraint(
            "length(trim(code)) > 0", name="ck_defect_types_code_not_empty"
        ),
        Index("uq_defect_types_code", "code", unique=True),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    requires_length: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_width: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_height: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_depth: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_area: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_quantity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_known_indication_location: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requires_description: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DefectLocationType(Base):
    """Системный read-only справочник расположений (ADR-022 §5; Spec §3.4)."""

    __tablename__ = DEFECT_LOCATION_TYPES_TABLE
    __table_args__ = (
        CheckConstraint(
            "length(trim(code)) > 0", name="ck_defect_location_types_code_not_empty"
        ),
        Index("uq_defect_location_types_code", "code", unique=True),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DefectRoot(Base):
    """Корневая идентичность цепочки версий одного технического дефекта (ADR-022 §7).

    1 к 1 с `EngineeringEvaluation(CONFIRMED_DEFECT)` (`UNIQUE(engineering_evaluation_id)`),
    устойчива после `CANCELLED` (не освобождает оценку — D08). Несёт per-joint `defect_no`,
    общий для всех ревизий. Указатели `current_defect_id`/`active_defect_id` — плоский UUID
    без FK (разрыв цикла, целостность на domain-слое, как `EngineeringEvaluation`).
    """

    __tablename__ = DEFECT_ROOTS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_defect_roots_version"),
        CheckConstraint("defect_no >= 1", name="ck_defect_roots_defect_no"),
        Index(
            "uq_defect_roots_engineering_evaluation_id",
            "engineering_evaluation_id",
            unique=True,
        ),
        Index(
            "uq_defect_roots_joint_defect_no",
            "joint_id",
            "defect_no",
            unique=True,
        ),
        Index("ix_defect_roots_joint_id", "joint_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    engineering_evaluation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.engineering_evaluations.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    defect_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # Указатели на ревизии — БЕЗ FK: целостность на domain-слое (9D-3B).
    current_defect_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    active_defect_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))

    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )


class Defect(Base):
    """Техническая ревизия дефекта в цепочке `DefectRoot` (ADR-022 §5–§7; Spec §3.2).

    Новый UUID на каждую ревизию; `revision_no` монотонно в цепочке; `supersedes_defect_id`
    указывает на предыдущую ревизию. Все структурированные характеристики §5 — самостоятельные
    колонки, nullable в `DRAFT`; обязательность/immutability проверяются сервисом (9D-3B).
    Независимого `standard_reference` нет (правило 7): только раздельные document/revision/clause.
    """

    __tablename__ = DEFECTS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_defects_version"),
        CheckConstraint("revision_no >= 1", name="ck_defects_revision_no"),
        CheckConstraint(
            _in("status", dw.DEFECT_STATUSES), name="ck_defects_status"
        ),
        CheckConstraint(
            _null_or_in("indication_location", dw.DEFECT_INDICATION_LOCATIONS),
            name="ck_defects_indication_location",
        ),
        # Измерения строго положительны при NOT NULL (неприменимое = NULL, не 0).
        CheckConstraint(
            "length_mm IS NULL OR length_mm > 0", name="ck_defects_length_positive"
        ),
        CheckConstraint(
            "width_mm IS NULL OR width_mm > 0", name="ck_defects_width_positive"
        ),
        CheckConstraint(
            "height_mm IS NULL OR height_mm > 0", name="ck_defects_height_positive"
        ),
        CheckConstraint(
            "depth_mm IS NULL OR depth_mm > 0", name="ck_defects_depth_positive"
        ),
        CheckConstraint(
            "affected_area_mm2 IS NULL OR affected_area_mm2 > 0",
            name="ck_defects_area_positive",
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity > 0", name="ck_defects_quantity_positive"
        ),
        # Положение (Spec §7.9): осевое >= 0; окружное нормализовано в [0, 360).
        CheckConstraint(
            "axial_position_mm IS NULL OR axial_position_mm >= 0",
            name="ck_defects_axial_position_nonneg",
        ),
        CheckConstraint(
            "circumferential_position_deg IS NULL OR "
            "(circumferential_position_deg >= 0 AND circumferential_position_deg < 360)",
            name="ck_defects_circumferential_range",
        ),
        # Bounded strings непусты при NOT NULL.
        CheckConstraint(
            "orientation IS NULL OR length(trim(orientation)) > 0",
            name="ck_defects_orientation_not_empty",
        ),
        CheckConstraint(
            "surface IS NULL OR length(trim(surface)) > 0",
            name="ck_defects_surface_not_empty",
        ),
        CheckConstraint(
            "joint_side IS NULL OR length(trim(joint_side)) > 0",
            name="ck_defects_joint_side_not_empty",
        ),
        CheckConstraint(
            "standard_document IS NULL OR length(trim(standard_document)) > 0",
            name="ck_defects_standard_document_not_empty",
        ),
        CheckConstraint(
            "standard_revision IS NULL OR length(trim(standard_revision)) > 0",
            name="ck_defects_standard_revision_not_empty",
        ),
        CheckConstraint(
            "standard_clause IS NULL OR length(trim(standard_clause)) > 0",
            name="ck_defects_standard_clause_not_empty",
        ),
        # Нормативная зависимость (Spec §7.8): revision/clause требуют document.
        CheckConstraint(
            "standard_revision IS NULL OR standard_document IS NOT NULL",
            name="ck_defects_standard_revision_requires_document",
        ),
        CheckConstraint(
            "standard_clause IS NULL OR standard_document IS NOT NULL",
            name="ck_defects_standard_clause_requires_document",
        ),
        # Согласованность конечных статусов.
        CheckConstraint(
            "status <> 'CANCELLED' OR ("
            "cancelled_at IS NOT NULL "
            "AND cancelled_by_worker_id IS NOT NULL "
            "AND cancellation_reason IS NOT NULL "
            "AND length(trim(cancellation_reason)) > 0)",
            name="ck_defects_cancelled_fields",
        ),
        CheckConstraint(
            "status <> 'SUPERSEDED' OR ("
            "superseded_at IS NOT NULL AND superseded_by_worker_id IS NOT NULL)",
            name="ck_defects_superseded_fields",
        ),
        CheckConstraint(
            "(activated_at IS NULL) = (activated_by_worker_id IS NULL)",
            name="ck_defects_activated_pair",
        ),
        # Ревизия не может замещать саму себя (принадлежность одной цепочке проверяет
        # сервис 9D-3B; self-reference безопасно закрывается CHECK).
        CheckConstraint(
            "supersedes_defect_id IS NULL OR supersedes_defect_id <> id",
            name="ck_defects_no_self_supersede",
        ),
        # Уникальность номера ревизии в цепочке.
        Index(
            "uq_defects_root_revision_no",
            "defect_root_id",
            "revision_no",
            unique=True,
        ),
        # Ровно одна ACTIVE и не более одной открытой DRAFT на цепочку (D04).
        Index(
            "uq_defects_one_active_per_root",
            "defect_root_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "uq_defects_one_draft_per_root",
            "defect_root_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        Index("ix_defects_root_status", "defect_root_id", "status"),
        Index("ix_defects_defect_type_id", "defect_type_id"),
        Index("ix_defects_location_type_id", "location_type_id"),
        Index("ix_defects_supersedes_defect_id", "supersedes_defect_id"),
        Index("ix_defects_created_at", "created_at"),
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
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_defect_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{DEFECTS_TABLE}.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=dw.DEFECT_DRAFT
    )

    # ── Классификация (nullable в DRAFT; обязательность на активацию — 9D-3B) ───
    defect_type_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{DEFECT_TYPES_TABLE}.id", ondelete="RESTRICT"
        ),
    )
    location_type_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{DEFECT_LOCATION_TYPES_TABLE}.id", ondelete="RESTRICT"
        ),
    )
    indication_location: Mapped[str | None] = mapped_column(String(20))

    # ── Ориентация / поверхность / сторона (bounded string, §4.4) ──────────────
    orientation: Mapped[str | None] = mapped_column(String(30))
    surface: Mapped[str | None] = mapped_column(String(20))
    joint_side: Mapped[str | None] = mapped_column(String(30))

    # ── Положение (Spec §7.9) ──────────────────────────────────────────────────
    axial_position_mm: Mapped[Decimal | None] = mapped_column(Numeric)
    circumferential_position_deg: Mapped[Decimal | None] = mapped_column(Numeric)

    # ── Измерения (положительные при NOT NULL) ─────────────────────────────────
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric)
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric)
    depth_mm: Mapped[Decimal | None] = mapped_column(Numeric)
    affected_area_mm2: Mapped[Decimal | None] = mapped_column(Numeric)
    quantity: Mapped[int | None] = mapped_column(Integer)

    # ── Нормативная ссылка (раздельные поля; без standard_reference) ───────────
    standard_document: Mapped[str | None] = mapped_column(Text)
    standard_revision: Mapped[str | None] = mapped_column(Text)
    standard_clause: Mapped[str | None] = mapped_column(Text)
    acceptance_level: Mapped[str | None] = mapped_column(Text)
    normative_category_code: Mapped[str | None] = mapped_column(String(60))

    # ── Пояснительный текст (не заменяет структуру, правило 1) ──────────────────
    technical_description: Mapped[str | None] = mapped_column(Text)
    location_description: Mapped[str | None] = mapped_column(Text)
    evaluation_note: Mapped[str | None] = mapped_column(Text)
    technical_note: Mapped[str | None] = mapped_column(Text)

    # ── Lifecycle actor/time ───────────────────────────────────────────────────
    activated_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # ── Аудит и optimistic locking ─────────────────────────────────────────────
    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )


class DefectSequence(Base):
    """Служебный per-joint счётчик номера дефекта (Spec §3.5).

    Отдельная последовательность на `Joint`. Значение выдаётся атомарно
    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` (см. `defect_numbering`). Стартовое
    значение 0, первая выдача → 1; номера монотонно растут и не переиспользуются.
    """

    __tablename__ = DEFECT_SEQUENCES_TABLE
    __table_args__ = (
        CheckConstraint("last_value >= 0", name="ck_defect_sequences_last_value"),
        {"schema": QUALITY_SCHEMA},
    )

    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_value: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DefectEvent(Base):
    """Неизменяемое событие истории Defect (append-only).

    API изменения/удаления событий нет (бизнес-запись — 9D-3B). `defect_version` — версия
    ревизии ПОСЛЕ команды (как `finding_version`/`revision_version`). `event_metadata`
    (колонка `metadata`) — необязательный контекст. `actor_worker_id` — hr.workers.id типа
    Integer без FK. `defect_root_id` — для истории всей цепочки.
    """

    __tablename__ = DEFECT_EVENTS_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("event_type", dw.DEFECT_EVENT_TYPES), name="ck_defect_events_type"
        ),
        CheckConstraint(
            "defect_version IS NULL OR defect_version >= 1",
            name="ck_defect_events_defect_version",
        ),
        Index("ix_defect_events_defect_root_id", "defect_root_id", "created_at"),
        Index("ix_defect_events_defect_id", "defect_id", "created_at"),
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
    defect_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{DEFECTS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    # `metadata` зарезервировано в Declarative; маппим на event_metadata.
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    defect_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
