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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering.models import ENGINEERING_SCHEMA
from app.projects.models import PROJECT_SCHEMA
from app.quality.inspection_workflow import (
    INSPECTION_EVENT_TYPES,
    INSPECTION_REQUESTED_OR_LATER,
    INSPECTION_STATUSES,
)
from app.quality.method_assignment_workflow import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_STATUSES,
    INSPECTION_METHOD_CODES,
)
from app.shared.db import Base

QUALITY_SCHEMA = "quality"


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


_STATUS_CHECK = _in_check("status", INSPECTION_STATUSES)
_EVENT_TYPE_CHECK = _in_check("event_type", INSPECTION_EVENT_TYPES)

# ── CHECK-выражения назначения метода контроля (Task 9B) ───────────────────────
_ASSIGNMENT_STATUS_CHECK = _in_check("status", ASSIGNMENT_STATUSES)
_ASSIGNMENT_METHOD_CHECK = _in_check("method_code", INSPECTION_METHOD_CODES)
# CANCELLED непротиворечив: заполнены автор/время/непустая причина отмены (§8.2).
_ASSIGNMENT_CANCELLED_FIELDS_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)
# Отправленная в работу заявка сохраняет requested-/ogs-readiness-поля и после
# дальнейших переходов (§7.4). DRAFT и CANCELLED — исключение: DRAFT ещё не
# отправлена, CANCELLED мог быть отменён прямо из DRAFT (поля пусты).
_REQUESTED_FIELDS_CHECK = (
    "status IN ('DRAFT', 'CANCELLED') OR ("
    "requested_at IS NOT NULL "
    "AND requested_by_worker_id IS NOT NULL "
    "AND ogs_readiness_confirmed_at IS NOT NULL "
    "AND ogs_readiness_confirmed_by_worker_id IS NOT NULL)"
)
# CANCELLED непротиворечив: заполнены автор/время/непустая причина отмены (§7.4).
_CANCELLED_FIELDS_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)

# Множество зафиксировано для наглядности инварианта requested-полей.
assert INSPECTION_REQUESTED_OR_LATER  # noqa: S101 (документирующая ссылка)


class Inspection(Base):
    """Заявка на контроль сварного соединения (Task 9A, ADR-015 / Session 007).

    Самостоятельная доменная сущность со своим lifecycle: одна Inspection
    относится ровно к одному Joint (`joint_id`). `system_code` формируется
    системой (`<PROJECT_CODE>-INS-<SEQUENCE>`), не принимается от клиента и не
    изменяется. `version` — optimistic locking. Подтверждение производственной
    готовности СМР и готовности ОГС хранятся прямо в заявке. Физического удаления
    нет (DELETE-endpoint не создаётся); отмена — терминальный статус CANCELLED.

    Ссылки на работников (*_by_worker_id) — hr.workers.id типа Integer БЕЗ FK, в
    стиле существующих модулей (Joint/WeldOperation, «переходный период» Р-3
    ADR-010): X-User-Id и hr.workers.id — целочисленные. FK на project.projects и
    engineering.joints добавляются (обе стороны — UUID).

    Назначение методов, лаборатории, результаты, решения ОГС, отчёты и дефекты
    (Tasks 9B–9G) в модель НЕ входят; заготовочные поля под них не создаются.
    """

    __tablename__ = "inspections"
    __table_args__ = (
        UniqueConstraint("system_code", name="uq_quality_inspections_system_code"),
        CheckConstraint("version >= 1", name="ck_quality_inspections_version"),
        CheckConstraint(
            "length(trim(request_reason)) > 0",
            name="ck_quality_inspections_request_reason_not_empty",
        ),
        CheckConstraint(_STATUS_CHECK, name="ck_quality_inspections_status"),
        CheckConstraint(
            _REQUESTED_FIELDS_CHECK, name="ck_quality_inspections_requested_fields"
        ),
        CheckConstraint(
            _CANCELLED_FIELDS_CHECK, name="ck_quality_inspections_cancelled_fields"
        ),
        # Внешний номер уникален в проекте только среди заполненных значений (§7.5).
        Index(
            "uq_quality_inspections_project_external_no",
            "project_id",
            "external_request_no",
            unique=True,
            postgresql_where="external_request_no IS NOT NULL",
        ),
        # Идемпотентность создания в рамках автора (§11).
        Index(
            "uq_quality_inspections_created_by_idempotency_key",
            "created_by_worker_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        Index("ix_quality_inspections_project_id", "project_id"),
        Index("ix_quality_inspections_joint_id", "joint_id"),
        Index("ix_quality_inspections_status", "status"),
        Index("ix_quality_inspections_project_status", "project_id", "status"),
        Index("ix_quality_inspections_joint_status", "joint_id", "status"),
        Index("ix_quality_inspections_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )

    system_code: Mapped[str] = mapped_column(String(64), nullable=False)
    external_request_no: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    # ── Подтверждение производственной готовности СМР (§13) ───────────────────
    production_ready_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    production_ready_confirmed_by_worker_id: Mapped[int | None] = mapped_column(
        Integer
    )

    # ── Готовность ОГС, фиксируемая при отправке (§14) ────────────────────────
    ogs_readiness_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    ogs_readiness_confirmed_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    readiness_override_reason: Mapped[str | None] = mapped_column(Text)

    # ── Отправка заявки в работу (§14) ────────────────────────────────────────
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_worker_id: Mapped[int | None] = mapped_column(Integer)

    # ── Отмена (§10.4) ────────────────────────────────────────────────────────
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # ── Аудит и optimistic locking ────────────────────────────────────────────
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
        Integer, nullable=False, server_default="1"
    )


class InspectionSequence(Base):
    """Служебный счётчик system_code заявок по проекту (Task 9A, §8).

    Отдельная последовательность на проект: `<project_code>-INS-<sequence>`.
    Значение выдаётся атомарно через `INSERT ... ON CONFLICT DO UPDATE ...
    RETURNING` (см. репозиторий) в текущей транзакции — гонки `MAX()+1` нет.
    Номера монотонно растут и не переиспользуются, в т.ч. после отмены заявки.
    """

    __tablename__ = "inspection_sequences"
    __table_args__ = (
        CheckConstraint(
            "last_value >= 0", name="ck_quality_inspection_sequences_last_value"
        ),
        {"schema": QUALITY_SCHEMA},
    )

    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_value: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class InspectionEvent(Base):
    """Неизменяемое событие истории Inspection (Task 9A, §9).

    Append-only: API изменения/удаления событий нет. Событие пишется в той же
    транзакции, что и основное изменение; `inspection_version` — версия заявки
    ПОСЛЕ успешной команды. `event_metadata` (колонка `metadata`) — необязательный
    контекст, не подмена нормализованным полям. `actor_worker_id` — hr.workers.id
    типа Integer без FK (как в Inspection).
    """

    __tablename__ = "inspection_events"
    __table_args__ = (
        CheckConstraint(_EVENT_TYPE_CHECK, name="ck_quality_inspection_events_type"),
        CheckConstraint(
            "inspection_version >= 1",
            name="ck_quality_inspection_events_version",
        ),
        Index("ix_quality_inspection_events_inspection_id", "inspection_id"),
        Index("ix_quality_inspection_events_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    inspection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.inspections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # `metadata` — зарезервированное имя в Declarative; маппим на атрибут
    # event_metadata с именем колонки "metadata".
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    inspection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InspectionMethodAssignment(Base):
    """Назначение метода контроля и лаборатории для Inspection (Task 9B, ADR-015).

    Отдельная доменная сущность: связывает `Inspection` с назначенным методом
    контроля (`method_code` из закрытого набора §6.1) и ответственной лабораторией
    НК (`laboratory_company_id` → project.companies.id). Лаборатория проверяется
    сервисом через project_companies с ролью NDT_LAB (§7).

    Жизненный цикл назначения (ASSIGNED → CANCELLED / REPLACED) не зависит от
    статуса Inspection и не меняет его. История отмен и замен сохраняется: записи
    физически не удаляются, замена создаёт новую запись и проставляет
    `replaced_by_assignment_id` у старой. Для одной Inspection допускается не более
    одного ASSIGNED-назначения каждого метода (partial unique index).

    Actor-поля — hr.workers.id типа Integer БЕЗ FK, как в Inspection (переходный
    период). `version` — optimistic locking. Выполнение метода и результаты
    контроля (Tasks 9C–9G) в модель НЕ входят; заготовочных полей под них нет.
    """

    __tablename__ = "inspection_method_assignments"
    __table_args__ = (
        CheckConstraint(
            "version >= 1", name="ck_quality_ima_version"
        ),
        CheckConstraint(
            _ASSIGNMENT_STATUS_CHECK, name="ck_quality_ima_status"
        ),
        CheckConstraint(
            _ASSIGNMENT_METHOD_CHECK, name="ck_quality_ima_method_code"
        ),
        CheckConstraint(
            _ASSIGNMENT_CANCELLED_FIELDS_CHECK,
            name="ck_quality_ima_cancelled_fields",
        ),
        # Не более одного активного назначения метода на Inspection (§9).
        # Исторические CANCELLED/REPLACED того же метода не ограничиваются.
        Index(
            "uq_quality_ima_active_method",
            "inspection_id",
            "method_code",
            unique=True,
            postgresql_where="status = 'ASSIGNED'",
        ),
        Index("ix_quality_ima_inspection_id", "inspection_id"),
        Index(
            "ix_quality_ima_inspection_status", "inspection_id", "status"
        ),
        Index("ix_quality_ima_laboratory_company_id", "laboratory_company_id"),
        Index("ix_quality_ima_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    inspection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.inspections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    method_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # Лаборатория — существующая организация проекта (project.companies.id —
    # Integer, не UUID; ТЗ говорит UUID, но канон проекта — Integer, §4.5/§7.1).
    laboratory_company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ASSIGNMENT_ASSIGNED
    )

    laboratory_note: Mapped[str | None] = mapped_column(Text)
    assignment_note: Mapped[str | None] = mapped_column(Text)

    # ── Назначение (§5.1) ─────────────────────────────────────────────────────
    assigned_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Отмена (§8.2) ─────────────────────────────────────────────────────────
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # ── Замена (§8.3): ссылка на новое назначение; ON DELETE SET NULL, т.к.
    # физического удаления нет, а строгий CHECK на непустую ссылку конфликтовал бы
    # с SET NULL. Ссылку проставляет сервис в одной транзакции с заменой. ─────────
    replaced_by_assignment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.inspection_method_assignments.id",
            ondelete="SET NULL",
        ),
    )

    # ── Аудит и optimistic locking (канон Task 9A) ────────────────────────────
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
        Integer, nullable=False, server_default="1"
    )


# ── Task 9C: реэкспорт моделей выполнения метода и заключения ───────────────────
# Модели Task 9C вынесены в отдельный модуль (execution_models) из-за объёма, но
# доступны через привычный неймспейс app.quality.models (conftest, Alembic, тесты).
# Импорт в конце файла: QUALITY_SCHEMA к этому моменту уже определён, цикла нет.
from app.quality.execution_models import (  # noqa: E402
    LaboratoryAccreditation,
    LaboratoryConclusion,
    LaboratoryConclusionExecution,
    MethodExecution,
    MethodExecutionParticipant,
    MethodExecutionResultItem,
    MethodExecutionStandard,
    QualityAuditEvent,
    QualityExternalPerson,
)

__all__ = [
    "QUALITY_SCHEMA",
    "Inspection",
    "InspectionSequence",
    "InspectionEvent",
    "InspectionMethodAssignment",
    "MethodExecution",
    "MethodExecutionParticipant",
    "MethodExecutionResultItem",
    "MethodExecutionStandard",
    "LaboratoryConclusion",
    "LaboratoryConclusionExecution",
    "LaboratoryAccreditation",
    "QualityExternalPerson",
    "QualityAuditEvent",
]
