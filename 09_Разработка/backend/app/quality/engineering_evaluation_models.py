"""ORM-модели ядра EngineeringEvaluation (Task 9D-2A, ADR-021).

Семь физических таблиц схемы `quality` (решение 9D-2-C08):

* `engineering_evaluations` — логическая оценка, 1:1 с `QualityFinding`
  (`UNIQUE(finding_id)`); номер `<PROJECT_CODE>-EE-<SEQUENCE>`; указатели на текущую и
  действующую ревизию — плоский UUID **без FK** (решение 9D-2A-T01, разрыв цикла без ALTER);
* `engineering_evaluation_revisions` — ревизия-носитель классификации, исхода,
  рекомендации, критичности, влияния и judgement-полей (C10). Поля nullable в DRAFT,
  enum-CHECK действует только при NOT NULL; обязательность и матрица — на `prepare` (9D-2C);
* `engineering_evaluation_sources`, `engineering_evaluation_criteria`,
  `engineering_exceptions` — создаются **структурно** (C08); бизнес-поведение — 9D-2B/2C;
* `engineering_evaluation_events` — неизменяемый журнал (append-only);
* `engineering_evaluation_sequences` — проектный счётчик номера.

Стиль Tasks 9A–9D-1: перечисления — CHECK (без native enum); actor-поля
(`*_by_worker_id`/`actor_worker_id`) — hr.workers.id типа Integer БЕЗ FK (переходный
период); `version` — optimistic locking; физического удаления нет (кроме DRAFT — сервис).
Набор статусов ревизии — ровно семь (C06/C09), `RETURNED_FOR_REVISION` не используется.
"""

from __future__ import annotations

from datetime import datetime
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.projects.models import PROJECT_SCHEMA
from app.quality import engineering_evaluation_workflow as eew
from app.shared.orm import Base

# Дублируется намеренно (как в quality_finding_models): независимый импорт модуля.
QUALITY_SCHEMA = "quality"

EVALUATIONS_TABLE = "engineering_evaluations"
REVISIONS_TABLE = "engineering_evaluation_revisions"
SOURCES_TABLE = "engineering_evaluation_sources"
CRITERIA_TABLE = "engineering_evaluation_criteria"
EXCEPTIONS_TABLE = "engineering_exceptions"
EVENTS_TABLE = "engineering_evaluation_events"
SEQUENCES_TABLE = "engineering_evaluation_sequences"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _null_or_in(column: str, values: tuple[str, ...]) -> str:
    """enum-CHECK, действующий только при NOT NULL (nullable DRAFT, C10)."""
    return f"{column} IS NULL OR {_in(column, values)}"


class EngineeringEvaluation(Base):
    """Логическая оценка ОГС по одному QualityFinding (ADR-021; 9D-2-C01).

    Не хранит классификацию/исход — только идентичность, номер и указатели на
    текущую/действующую ревизию (плоский UUID без FK — 9D-2A-T01). Классификация и
    исход принадлежат ревизии (C10).
    """

    __tablename__ = EVALUATIONS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_engineering_evaluations_version"),
        CheckConstraint(
            "length(trim(system_code)) > 0",
            name="ck_engineering_evaluations_system_code_not_empty",
        ),
        Index(
            "uq_engineering_evaluations_finding_id", "finding_id", unique=True
        ),
        Index(
            "uq_engineering_evaluations_system_code", "system_code", unique=True
        ),
        Index("ix_engineering_evaluations_project_id", "project_id"),
        Index("ix_engineering_evaluations_created_at", "created_at"),
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
    finding_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.quality_findings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    system_code: Mapped[str] = mapped_column(String(64), nullable=False)

    # Указатели на ревизии — БЕЗ FK (9D-2A-T01): целостность на domain-слое.
    current_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    effective_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))

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
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class EngineeringEvaluationRevision(Base):
    """Ревизия оценки — носитель содержания (ADR-021; C06/C09/C10).

    Классификация/исход/рекомендация/критичность/влияние и judgement-поля создаются
    сразу (C10), nullable в DRAFT; enum-CHECK — только при NOT NULL. Обязательность,
    согласованность (§4.8) и матрица комплектности проверяются на `prepare` (9D-2C),
    а не CHECK-ограничением. `rationale` — не безусловный NOT NULL.
    """

    __tablename__ = REVISIONS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_ee_revisions_version"),
        CheckConstraint("revision_no >= 1", name="ck_ee_revisions_revision_no"),
        CheckConstraint(
            _in("status", eew.EVALUATION_STATUSES), name="ck_ee_revisions_status"
        ),
        CheckConstraint(
            _null_or_in("evaluation_outcome", eew.EVALUATION_OUTCOMES),
            name="ck_ee_revisions_evaluation_outcome",
        ),
        CheckConstraint(
            _null_or_in("classification", eew.EVALUATION_CLASSIFICATIONS),
            name="ck_ee_revisions_classification",
        ),
        CheckConstraint(
            _null_or_in("recommended_disposition", eew.RECOMMENDED_DISPOSITIONS),
            name="ck_ee_revisions_recommended_disposition",
        ),
        CheckConstraint(
            _null_or_in("confirmed_severity", eew.CONFIRMED_SEVERITIES),
            name="ck_ee_revisions_confirmed_severity",
        ),
        CheckConstraint(
            _null_or_in("impact_scope", eew.IMPACT_SCOPES),
            name="ck_ee_revisions_impact_scope",
        ),
        CheckConstraint(
            _null_or_in("confidence_level", eew.CONFIDENCE_LEVELS),
            name="ck_ee_revisions_confidence_level",
        ),
        # Пересмотр обоснован: со второй ревизии причина обязательна.
        CheckConstraint(
            "revision_no = 1 OR revision_reason IS NOT NULL",
            name="ck_ee_revisions_revision_reason",
        ),
        # WITHDRAWN непротиворечив: автор/время/непустая причина.
        CheckConstraint(
            "status <> 'WITHDRAWN' OR ("
            "withdrawn_at IS NOT NULL "
            "AND withdrawn_by_worker_id IS NOT NULL "
            "AND length(trim(withdrawal_reason)) > 0)",
            name="ck_ee_revisions_withdrawn_fields",
        ),
        # Пары actor/time заполняются вместе.
        CheckConstraint(
            "(prepared_at IS NULL) = (prepared_by_worker_id IS NULL)",
            name="ck_ee_revisions_prepared_pair",
        ),
        CheckConstraint(
            "(fixed_at IS NULL) = (fixed_by_worker_id IS NULL)",
            name="ck_ee_revisions_fixed_pair",
        ),
        Index(
            "uq_ee_revisions_evaluation_revno",
            "evaluation_id",
            "revision_no",
            unique=True,
        ),
        Index("ix_ee_revisions_evaluation_id", "evaluation_id"),
        Index("ix_ee_revisions_status", "status"),
        Index("ix_ee_revisions_previous_revision_id", "previous_revision_id"),
        Index("ix_ee_revisions_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    evaluation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EVALUATIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=eew.EVAL_DRAFT
    )

    # ── Классификация/исход (принадлежат ревизии; nullable в DRAFT) ────────────
    evaluation_outcome: Mapped[str | None] = mapped_column(String(30))
    classification: Mapped[str | None] = mapped_column(String(40))
    recommended_disposition: Mapped[str | None] = mapped_column(String(30))
    confirmed_severity: Mapped[str | None] = mapped_column(String(20))
    impact_scope: Mapped[str | None] = mapped_column(String(40))

    # ── Обоснование и judgement (nullable в DRAFT; обязательность на prepare) ──
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str | None] = mapped_column(String(10))
    confidence_note: Mapped[str | None] = mapped_column(Text)
    residual_risk: Mapped[str | None] = mapped_column(Text)
    application_conditions: Mapped[str | None] = mapped_column(Text)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_impact: Mapped[str | None] = mapped_column(Text)
    required_approval_route: Mapped[str | None] = mapped_column(Text)

    # ── Переходы (actor/time) — заполняются командами 9D-2D ────────────────────
    prepared_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fixed_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class EngineeringEvaluationSource(Base):
    """Структурированная ссылка на источник (структурно в 9D-2A; поведение 9D-2B).

    Ревизионный источник → `source_revision_id`; неревизионный → `source_hash` +
    `hash_schema_version`. Сверка актуальности и профили — блок 9D-2B.
    """

    __tablename__ = SOURCES_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("source_role", eew.SOURCE_ROLES), name="ck_ee_sources_role"
        ),
        CheckConstraint(
            "source_revision_id IS NOT NULL OR "
            "(source_hash IS NOT NULL AND hash_schema_version IS NOT NULL)",
            name="ck_ee_sources_revisional_or_hash",
        ),
        Index("ix_ee_sources_revision_id", "revision_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_role: Mapped[str] = mapped_column(String(30), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_hash: Mapped[str | None] = mapped_column(String(128))
    hash_schema_version: Mapped[str | None] = mapped_column(String(40))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applicability_note: Mapped[str | None] = mapped_column(Text)
    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EngineeringEvaluationCriterion(Base):
    """Применимый критерий приёмки (структурно в 9D-2A; поведение 9D-2B)."""

    __tablename__ = CRITERIA_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("comparison_result", eew.CRITERION_RESULTS),
            name="ck_ee_criteria_comparison_result",
        ),
        Index("ix_ee_criteria_revision_id", "revision_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requirement_ref: Mapped[str] = mapped_column(Text, nullable=False)
    clause: Mapped[str | None] = mapped_column(Text)
    parameter: Mapped[str] = mapped_column(Text, nullable=False)
    actual_value: Mapped[str | None] = mapped_column(Text)
    actual_num: Mapped[float | None] = mapped_column(Numeric)
    allowed_value: Mapped[str | None] = mapped_column(Text)
    allowed_num_min: Mapped[float | None] = mapped_column(Numeric)
    allowed_num_max: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(40))
    comparison_result: Mapped[str] = mapped_column(String(30), nullable=False)
    applicability_comment: Mapped[str | None] = mapped_column(Text)
    engineer_comment: Mapped[str | None] = mapped_column(Text)
    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EngineeringException(Base):
    """Отступление от одного критерия (структурно в 9D-2A; поведение 9D-2C).

    Одно исключение — один критерий (`UNIQUE(revision_id, criterion_id)`).
    """

    __tablename__ = EXCEPTIONS_TABLE
    __table_args__ = (
        Index(
            "uq_ee_exceptions_revision_criterion",
            "revision_id",
            "criterion_id",
            unique=True,
        ),
        Index("ix_ee_exceptions_revision_id", "revision_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    criterion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{CRITERIA_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    residual_risk: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[str | None] = mapped_column(Text)
    required_approval_route: Mapped[str | None] = mapped_column(Text)
    is_draft_copy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EngineeringEvaluationEvent(Base):
    """Неизменяемое событие истории оценки (append-only).

    `revision_id` — null для событий уровня оценки; `revision_version` — версия ревизии
    ПОСЛЕ команды (null для событий уровня оценки). `actor_worker_id` — hr.workers.id
    Integer без FK. `event_metadata` маппится на колонку `metadata`.
    """

    __tablename__ = EVENTS_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("event_type", eew.EVALUATION_EVENT_TYPES),
            name="ck_ee_events_type",
        ),
        CheckConstraint(
            "revision_version IS NULL OR revision_version >= 1",
            name="ck_ee_events_revision_version",
        ),
        Index("ix_ee_events_evaluation_id", "evaluation_id"),
        Index("ix_ee_events_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    evaluation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EVALUATIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id", ondelete="RESTRICT"),
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    correlation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revision_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EngineeringEvaluationSequence(Base):
    """Служебный счётчик номера оценки по проекту (`<CODE>-EE-<SEQUENCE>`)."""

    __tablename__ = SEQUENCES_TABLE
    __table_args__ = (
        CheckConstraint(
            "last_value >= 0", name="ck_ee_sequences_last_value"
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
