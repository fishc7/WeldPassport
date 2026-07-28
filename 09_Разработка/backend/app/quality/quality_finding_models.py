"""ORM-модели ядра QualityFinding (Task 9D-1, ADR-019 / Session 008-07).

Продолжение канона Tasks 9A–9C (`app.quality.models`, `app.quality.execution_models`):
физические таблицы схемы `quality` для зарегистрированного факта потенциального или
подтверждённого несоответствия (`QualityFinding`), проектного счётчика номеров
(`QualityFindingSequence`) и неизменяемого журнала (`QualityFindingEvent`).

Ключевые решения (ADR-019 + план 9D-1):

* `QualityFinding` принадлежит одному `Joint`; после **регистрации** получает номер
  `<PROJECT_CODE>-QF-<SEQUENCE>` (в DRAFT номера ещё нет). Исходное наблюдение
  (`observation`) в DRAFT редактируемо, после `REGISTERED` — неизменяемо (инвариант
  проверяет сервис); дополнения/исправления — будущие сущности `FindingEvidence` /
  `FindingCorrection` (блоки 9D-1+/9D-2), в это ядро не входят;
* `origin_type` и `initial_risk` — канонические справочники (CHECK), не подменяют
  инженерную классификацию и confirmed_severity (блок 9D-2);
* источник контроля — необязательные ссылки на `Inspection` / `MethodExecution`
  (схема quality) и `WeldOperation` (схема engineering); все три несут `joint_id`,
  совпадение с finding проверяет сервис. Ссылка на точный `ResultItem`,
  `FindingLocation/Evidence` и т.п. — будущие блоки;
* actor-поля (`*_by_worker_id`) — hr.workers.id типа Integer БЕЗ FK (переходный
  период, как в 9A–9C); `version` — optimistic locking; физического удаления нет,
  кроме DRAFT (сервис). Перечисления — CHECK-ограничениями, без native enum.
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering.models import ENGINEERING_SCHEMA
from app.projects.models import PROJECT_SCHEMA
from app.quality import quality_finding_workflow as qfw
from app.shared.orm import Base

# QUALITY_SCHEMA дублирует app.quality.models.QUALITY_SCHEMA намеренно: этот модуль
# должен импортироваться независимо (models реэкспортирует классы в конце файла —
# обратная зависимость создала бы цикл).
QUALITY_SCHEMA = "quality"

FINDINGS_TABLE = "quality_findings"
FINDING_SEQUENCES_TABLE = "quality_finding_sequences"
FINDING_EVENTS_TABLE = "quality_finding_events"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


_STATUS_CHECK = _in("status", qfw.FINDING_STATUSES)
_ORIGIN_CHECK = _in("origin_type", qfw.FINDING_ORIGIN_TYPES)
_RISK_CHECK = _in("initial_risk", qfw.FINDING_INITIAL_RISKS)
_EVENT_TYPE_CHECK = _in("event_type", qfw.FINDING_EVENT_TYPES)

# Зарегистрированный (не-DRAFT) finding обязан иметь номер и registered-поля.
# DRAFT — исключение (номер выдаётся при регистрации). CANCELLED достижим только из
# REGISTERED/UNDER_EVALUATION, поэтому тоже имеет registered-поля.
_REGISTERED_FIELDS_CHECK = (
    "status = 'DRAFT' OR ("
    "system_code IS NOT NULL "
    "AND registered_at IS NOT NULL "
    "AND registered_by_worker_id IS NOT NULL)"
)
# CANCELLED непротиворечив: заполнены автор/время/непустая причина отмены.
_CANCELLED_FIELDS_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)
# Пара acknowledged-полей заполняется вместе (при переходе в UNDER_EVALUATION).
_ACKNOWLEDGED_FIELDS_CHECK = (
    "(acknowledged_at IS NULL) = (acknowledged_by_worker_id IS NULL)"
)

# Множество зафиксировано для наглядности инварианта registered-полей.
assert qfw.FINDING_REGISTERED_OR_LATER  # noqa: S101 (документирующая ссылка)


class QualityFinding(Base):
    """Зарегистрированный факт для рассмотрения (ADR-019, решение 1; Task 9D-1).

    Самостоятельная сущность качества: **не** Defect, **не** негодность Joint, **не**
    решение ОГС. Один finding относится ровно к одному `Joint`. `system_code`
    (`<PROJECT_CODE>-QF-<SEQUENCE>`) выдаётся системой при регистрации и далее не
    изменяется. Исходное наблюдение неизменяемо после регистрации (сервис). Инженерная
    оценка, дефекты, disposition, holds и дочерние сущности finding — блоки 9D-2 … 9D-6
    и в модель ядра НЕ входят; заготовочных полей под них нет.
    """

    __tablename__ = FINDINGS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_quality_findings_version"),
        CheckConstraint(_STATUS_CHECK, name="ck_quality_findings_status"),
        CheckConstraint(_ORIGIN_CHECK, name="ck_quality_findings_origin_type"),
        CheckConstraint(_RISK_CHECK, name="ck_quality_findings_initial_risk"),
        CheckConstraint(
            "length(trim(observation)) > 0",
            name="ck_quality_findings_observation_not_empty",
        ),
        CheckConstraint(
            _REGISTERED_FIELDS_CHECK, name="ck_quality_findings_registered_fields"
        ),
        CheckConstraint(
            _CANCELLED_FIELDS_CHECK, name="ck_quality_findings_cancelled_fields"
        ),
        CheckConstraint(
            _ACKNOWLEDGED_FIELDS_CHECK, name="ck_quality_findings_acknowledged_fields"
        ),
        # Номер уникален глобально среди заполненных значений (DRAFT без номера не
        # участвует). Номер уже включает код проекта и монотонную последовательность.
        Index(
            "uq_quality_findings_system_code",
            "system_code",
            unique=True,
            postgresql_where="system_code IS NOT NULL",
        ),
        # Внешний номер уникален в проекте только среди заполненных значений.
        Index(
            "uq_quality_findings_project_external_no",
            "project_id",
            "external_no",
            unique=True,
            postgresql_where="external_no IS NOT NULL",
        ),
        Index("ix_quality_findings_project_id", "project_id"),
        Index("ix_quality_findings_joint_id", "joint_id"),
        Index("ix_quality_findings_status", "status"),
        Index("ix_quality_findings_project_status", "project_id", "status"),
        Index("ix_quality_findings_joint_status", "joint_id", "status"),
        Index("ix_quality_findings_created_at", "created_at"),
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

    # Номер выдаётся при регистрации (в DRAFT — NULL).
    system_code: Mapped[str | None] = mapped_column(String(64))
    external_no: Mapped[str | None] = mapped_column(String(100))
    external_ref: Mapped[str | None] = mapped_column(Text)

    origin_type: Mapped[str] = mapped_column(String(40), nullable=False)
    initial_risk: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=qfw.FINDING_INITIAL_RISK_DEFAULT,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=qfw.FINDING_DRAFT
    )

    title: Mapped[str | None] = mapped_column(String(255))
    # Исходное наблюдение — неизменяемо после регистрации (сервис).
    observation: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Источник контроля (необязательные ссылки; joint-match проверяет сервис) ─
    inspection_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.inspections.id", ondelete="RESTRICT"),
    )
    method_execution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.method_executions.id", ondelete="RESTRICT"),
    )
    weld_operation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.weld_operations.id", ondelete="RESTRICT"),
    )
    source_note: Mapped[str | None] = mapped_column(Text)

    # ── Регистрация (DRAFT → REGISTERED) ──────────────────────────────────────
    registered_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Подтверждение получения ОГС (REGISTERED → UNDER_EVALUATION) ────────────
    acknowledged_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Отмена (REGISTERED/UNDER_EVALUATION → CANCELLED) ──────────────────────
    cancelled_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # ── Аудит и optimistic locking (канон Tasks 9A–9C) ────────────────────────
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


class QualityFindingSequence(Base):
    """Служебный счётчик номера finding по проекту (ADR-019: `<CODE>-QF-<SEQUENCE>`).

    Отдельная последовательность на проект. Значение выдаётся атомарно через
    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` (репозиторий) в текущей
    транзакции — гонки `MAX()+1` нет. Номера монотонно растут и не переиспользуются.
    """

    __tablename__ = FINDING_SEQUENCES_TABLE
    __table_args__ = (
        CheckConstraint(
            "last_value >= 0", name="ck_quality_finding_sequences_last_value"
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


class QualityFindingEvent(Base):
    """Неизменяемое событие истории QualityFinding (append-only).

    API изменения/удаления событий нет. Событие пишется в той же транзакции, что и
    основное изменение; `finding_version` — версия finding ПОСЛЕ успешной команды.
    `event_metadata` (колонка `metadata`) — необязательный контекст. `actor_worker_id`
    — hr.workers.id типа Integer без FK (как InspectionEvent).
    """

    __tablename__ = FINDING_EVENTS_TABLE
    __table_args__ = (
        CheckConstraint(_EVENT_TYPE_CHECK, name="ck_quality_finding_events_type"),
        CheckConstraint(
            "finding_version >= 1", name="ck_quality_finding_events_version"
        ),
        Index("ix_quality_finding_events_finding_id", "finding_id"),
        Index("ix_quality_finding_events_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    finding_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{FINDINGS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # `metadata` зарезервировано в Declarative; маппим на event_metadata.
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    finding_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
