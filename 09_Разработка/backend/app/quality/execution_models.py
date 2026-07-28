"""ORM-модели выполнения метода контроля и заключения (Task 9C, ADR-015 / Session 007).

Продолжение канона Tasks 9A/9B (`app.quality.models`): физические таблицы схемы
`quality` для фактического выполнения назначенного метода (`MethodExecution`), его
участников, локальных результатов, стандартов, а также лабораторного заключения
(`LaboratoryConclusion`), связи заключение↔выполнение, аккредитации, внешнего лица
и доменного аудита.

Ключевые решения (планирование 9C + ревью 9C-1):

* именование гибридное (имена ТЗ), прежние термины канона `InspectionMethodExecution`
  / `InspectionMethodResult` считаются заменёнными (docs — отдельным шагом);
* терминал выполнения — `LAB_CONFIRMED` (не `VERIFIED`); enum оценки —
  `CONFORMING/NONCONFORMING/INCONCLUSIVE/NOT_EVALUATED`;
* дочерние части выполнения (participants/result_items/standards) ссылаются на
  `method_executions` с `ON DELETE RESTRICT` (историю несёт редакция, каскада нет);
* `root_*_id` — обычные UUID БЕЗ self-FK (по ревью 9C-1); self-FK только у
  `supersedes_*` с `ON DELETE SET NULL`;
* одна текущая редакция — partial unique `WHERE is_current`; не более одного
  `LEAD_INSPECTOR` на выполнение — partial unique (ровно один — позже сервисом);
* номер заключения нормализован: partial unique `WHERE status='ISSUED'`;
* actor-поля — hr.workers.id типа Integer БЕЗ FK (переходный период, как в 9A/9B);
  лаборатория — `project.companies.id` (Integer), роль NDT_LAB проверяет сервис.

Перечисления реализованы CHECK-ограничениями в стиле Tasks 9A/9B (без native enum).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering.models import ENGINEERING_SCHEMA
from app.projects.models import PROJECT_SCHEMA
from app.quality import laboratory_conclusion_workflow as lcw
from app.quality import method_execution_workflow as mew
from app.quality.method_assignment_workflow import INSPECTION_METHOD_CODES
from app.shared.orm import Base

# QUALITY_SCHEMA дублирует app.quality.models.QUALITY_SCHEMA намеренно:
# execution_models должен импортироваться независимо от models (models
# реэкспортирует эти классы в конце файла — обратная зависимость создала бы цикл).
QUALITY_SCHEMA = "quality"

EXECUTIONS_TABLE = "method_executions"
CONCLUSIONS_TABLE = "laboratory_conclusions"
EXTERNAL_PERSONS_TABLE = "quality_external_persons"
ACCREDITATIONS_TABLE = "laboratory_accreditations"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _nullable_in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR " + _in(column, values)


# ── Внешнее лицо лаборатории (§9.3 задания; решение 9C: минимальная модель) ─────


class QualityExternalPerson(Base):
    """Минимальное внешнее лицо контроля НК (исполнитель/утверждающий лаборатории).

    Не `hr.Worker` (лабораторные контролёры — внешние). Полноценный кадровый модуль
    внешней лаборатории в Task 9C не строится (§9.3): здесь только идентификация и
    привязка к организации-участнику проекта. Исторические реквизиты квалификации
    хранятся снимком на участнике выполнения, а не тут.
    """

    __tablename__ = EXTERNAL_PERSONS_TABLE
    __table_args__ = (
        CheckConstraint(
            "length(trim(full_name)) > 0",
            name="ck_quality_external_persons_full_name_not_empty",
        ),
        Index(
            "ix_quality_external_persons_organization",
            "organization_company_id",
        ),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Организация-участник проекта (обычно лаборатория). Integer — как company.id.
    organization_company_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
    )
    external_ref: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)

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


# ── Аккредитация лаборатории (§21 задания; минимальная модель) ─────────────────


class LaboratoryAccreditation(Base):
    """Минимальная аккредитация лаборатории НК (§21).

    Принадлежит организации (`company_id`). Проверки принадлежности, действия на
    дату контроля и соответствия методу — сервисом; на заключении хранится
    исторический снимок реквизитов. Сложный workflow аккредитаций не строится.
    """

    __tablename__ = ACCREDITATIONS_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("status", lcw.ACCREDITATION_STATUSES),
            name="ck_quality_accreditation_status",
        ),
        CheckConstraint(
            "length(trim(certificate_number)) > 0",
            name="ck_quality_accreditation_cert_not_empty",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_quality_accreditation_valid_range",
        ),
        Index("ix_quality_accreditation_company", "company_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    certificate_number: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    accreditation_scope: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=lcw.ACCREDITATION_ACTIVE
    )

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


# ── Выполнение метода контроля (§5 задания) ────────────────────────────────────

# CANCELLED непротиворечив: тип, время, автор и непустая причина (§6).
_EXEC_CANCELLED_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancellation_type IS NOT NULL "
    "AND cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)
# Интервал времени: finished_at не раньше started_at (§8).
_EXEC_TIME_INTERVAL_CHECK = (
    "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at"
)


class MethodExecution(Base):
    """Фактический эпизод выполнения назначенного метода контроля (§5).

    Одно выполнение относится ровно к одному назначению, одному соединению и одной
    лаборатории; `joint_id` наследуется из назначения (инвариант проверяет сервис,
    §5.3). Разные `root_execution_id` — разные физические эпизоды; одинаковый root и
    разные `revision_no` — исправления одного эпизода (§18). Одна текущая редакция на
    root — partial unique `WHERE is_current`. После LAB_CONFIRMED обычное
    редактирование запрещено (исправление — новой редакцией).
    """

    __tablename__ = EXECUTIONS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_quality_mexec_version"),
        CheckConstraint("revision_no >= 1", name="ck_quality_mexec_revision_no"),
        CheckConstraint(
            _in("status", mew.EXECUTION_STATUSES), name="ck_quality_mexec_status"
        ),
        CheckConstraint(
            _nullable_in("confirmation_mode", mew.CONFIRMATION_MODES),
            name="ck_quality_mexec_confirmation_mode",
        ),
        CheckConstraint(
            _nullable_in("time_precision", mew.TIME_PRECISIONS),
            name="ck_quality_mexec_time_precision",
        ),
        CheckConstraint(
            _nullable_in("calculated_evaluation", mew.EVALUATIONS),
            name="ck_quality_mexec_calc_evaluation",
        ),
        CheckConstraint(
            _nullable_in("laboratory_evaluation", mew.EVALUATIONS),
            name="ck_quality_mexec_lab_evaluation",
        ),
        CheckConstraint(
            _nullable_in("calculated_completion", mew.CALCULATED_COMPLETIONS),
            name="ck_quality_mexec_calc_completion",
        ),
        CheckConstraint(
            _nullable_in("declared_completion", mew.DECLARED_COMPLETIONS),
            name="ck_quality_mexec_declared_completion",
        ),
        CheckConstraint(
            _nullable_in("cancellation_type", mew.CANCELLATION_TYPES),
            name="ck_quality_mexec_cancellation_type",
        ),
        CheckConstraint(_EXEC_CANCELLED_CHECK, name="ck_quality_mexec_cancelled"),
        CheckConstraint(
            _EXEC_TIME_INTERVAL_CHECK, name="ck_quality_mexec_time_interval"
        ),
        # Одна текущая редакция на физический эпизод (§5.3 / §18).
        Index(
            "uq_quality_mexec_current_revision",
            "root_execution_id",
            unique=True,
            postgresql_where="is_current",
        ),
        Index("ix_quality_mexec_assignment", "inspection_method_assignment_id"),
        Index("ix_quality_mexec_joint", "joint_id"),
        Index("ix_quality_mexec_laboratory", "laboratory_company_id"),
        Index("ix_quality_mexec_status", "status"),
        Index("ix_quality_mexec_root", "root_execution_id"),
        Index("ix_quality_mexec_created_at", "created_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    inspection_method_assignment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.inspection_method_assignments.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    laboratory_company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ── Ревизии (§18): root — обычный UUID без self-FK; supersedes — self-FK ────
    root_execution_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    supersedes_execution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EXECUTIONS_TABLE}.id", ondelete="SET NULL"),
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=mew.EXEC_DRAFT
    )
    confirmation_mode: Mapped[str | None] = mapped_column(String(40))

    # ── Время (§8) ────────────────────────────────────────────────────────────
    performed_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_precision: Mapped[str | None] = mapped_column(String(20))

    # ── Оценка (§11) ──────────────────────────────────────────────────────────
    calculated_evaluation: Mapped[str | None] = mapped_column(String(20))
    laboratory_evaluation: Mapped[str | None] = mapped_column(String(20))
    evaluation_override_reason: Mapped[str | None] = mapped_column(Text)

    # ── Полнота (§12) ─────────────────────────────────────────────────────────
    calculated_completion: Mapped[str | None] = mapped_column(String(20))
    declared_completion: Mapped[str | None] = mapped_column(String(20))
    completion_override_reason: Mapped[str | None] = mapped_column(Text)

    # ── Мерной пояс (§13) ─────────────────────────────────────────────────────
    calculated_belt_length: Mapped[Decimal | None] = mapped_column(Numeric)
    declared_belt_length: Mapped[Decimal | None] = mapped_column(Numeric)
    belt_length_unit: Mapped[str | None] = mapped_column(String(10))
    belt_length_override_reason: Mapped[str | None] = mapped_column(Text)

    # ── Источник данных (§5.2) ────────────────────────────────────────────────
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # ── Технологическая карта — снимок или ссылка (§14.1) ──────────────────────
    procedure_document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    procedure_reference_snapshot: Mapped[str | None] = mapped_column(Text)
    procedure_revision_snapshot: Mapped[str | None] = mapped_column(String(100))

    # ── Отмена (§6) ───────────────────────────────────────────────────────────
    cancellation_type: Mapped[str | None] = mapped_column(String(40))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Подтверждение лабораторией / регистрация внешнего документа (§7) ───────
    lab_confirmed_by_user_id: Mapped[int | None] = mapped_column(Integer)
    lab_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lab_approver_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{EXTERNAL_PERSONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )
    external_lab_approver_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{EXTERNAL_PERSONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )
    external_lab_approval_date: Mapped[date | None] = mapped_column(Date)
    registered_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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


# ── Участник выполнения (§9 задания) ───────────────────────────────────────────


class MethodExecutionParticipant(Base):
    """Участник фактического контроля со снимком квалификации (§9).

    Ссылается на выполнение с `ON DELETE RESTRICT` (часть редакции; каскада нет).
    `person_id` → `quality_external_persons`. Не более одного `LEAD_INSPECTOR` на
    выполнение обеспечивает partial unique index; требование «ровно один перед
    RESULT_RECORDED» проверяет сервис (§9.1).
    """

    __tablename__ = "method_execution_participants"
    __table_args__ = (
        CheckConstraint(
            _in("participant_role", mew.PARTICIPANT_ROLES),
            name="ck_quality_mexec_part_role",
        ),
        CheckConstraint(
            _nullable_in("engagement_type", mew.ENGAGEMENT_TYPES),
            name="ck_quality_mexec_part_engagement",
        ),
        # Не более одного LEAD_INSPECTOR на выполнение (§9.1).
        Index(
            "uq_quality_mexec_part_lead",
            "method_execution_id",
            unique=True,
            postgresql_where="participant_role = 'LEAD_INSPECTOR'",
        ),
        Index("ix_quality_mexec_part_execution", "method_execution_id"),
        Index("ix_quality_mexec_part_person", "person_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    method_execution_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EXECUTIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{EXTERNAL_PERSONS_TABLE}.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    participant_organization_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
    )
    engagement_type: Mapped[str | None] = mapped_column(String(40))
    engagement_basis: Mapped[str | None] = mapped_column(Text)
    participant_role: Mapped[str] = mapped_column(String(20), nullable=False)
    person_certification_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )

    # ── Исторический снимок квалификации (§9.2) ───────────────────────────────
    person_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    organization_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    qualification_level_snapshot: Mapped[str | None] = mapped_column(String(100))
    certificate_number_snapshot: Mapped[str | None] = mapped_column(String(100))
    certificate_valid_from_snapshot: Mapped[date | None] = mapped_column(Date)
    certificate_valid_until_snapshot: Mapped[date | None] = mapped_column(Date)
    certification_scope_snapshot: Mapped[str | None] = mapped_column(Text)

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


# ── Локальный результат (§10 задания) ──────────────────────────────────────────

# wraps_zero допустим только для замкнутых координатных систем (§10.5).
_RESULT_WRAPS_ZERO_CHECK = "NOT wraps_zero OR " + _in(
    "coordinate_system", tuple(sorted(mew.CLOSED_COORDINATE_SYSTEMS))
)
# OTHER-объект обязан иметь описание (§10.4).
_RESULT_OTHER_CHECK = (
    "controlled_object_type <> 'OTHER' "
    "OR length(trim(coalesce(description, ''))) > 0"
)
# EXCLUDED обязан иметь причину исключения (§10.3).
_RESULT_EXCLUDED_CHECK = (
    "record_state <> 'EXCLUDED' "
    "OR length(trim(coalesce(excluded_reason, ''))) > 0"
)


class MethodExecutionResultItem(Base):
    """Отдельный локальный результат выполнения (§10).

    Один неделимый контролируемый объект (всё соединение, участок, снимок, зона).
    Ссылается на выполнение с `ON DELETE RESTRICT`. `root_result_item_id` — обычный
    UUID без self-FK; `supersedes_result_item_id` — self-FK SET NULL. EXCLUDED не
    участвует в расчётах (§10.3) и требует причины.
    """

    __tablename__ = "method_execution_result_items"
    __table_args__ = (
        CheckConstraint("revision_no >= 1", name="ck_quality_mres_revision_no"),
        CheckConstraint(
            _in("record_state", mew.RESULT_STATES), name="ck_quality_mres_state"
        ),
        CheckConstraint(
            _in("controlled_object_type", mew.CONTROLLED_OBJECT_TYPES),
            name="ck_quality_mres_object_type",
        ),
        CheckConstraint(
            _nullable_in("coordinate_system", mew.COORDINATE_SYSTEMS),
            name="ck_quality_mres_coord_system",
        ),
        CheckConstraint(
            _nullable_in("coordinate_unit", mew.COORDINATE_UNITS),
            name="ck_quality_mres_coord_unit",
        ),
        CheckConstraint(
            _in("evaluation", mew.EVALUATIONS), name="ck_quality_mres_evaluation"
        ),
        CheckConstraint(
            _nullable_in("required_action", mew.REQUIRED_ACTIONS),
            name="ck_quality_mres_required_action",
        ),
        CheckConstraint(_RESULT_WRAPS_ZERO_CHECK, name="ck_quality_mres_wraps_zero"),
        CheckConstraint(_RESULT_OTHER_CHECK, name="ck_quality_mres_other_desc"),
        CheckConstraint(
            _RESULT_EXCLUDED_CHECK, name="ck_quality_mres_excluded_reason"
        ),
        Index("ix_quality_mres_execution", "method_execution_id"),
        Index("ix_quality_mres_execution_state", "method_execution_id", "record_state"),
        Index("ix_quality_mres_root", "root_result_item_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    method_execution_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EXECUTIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    root_result_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    supersedes_result_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.method_execution_result_items.id",
            ondelete="SET NULL",
        ),
    )

    record_state: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=mew.RESULT_DRAFT
    )
    controlled_object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    object_reference: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    # ── Координаты (§10.5) ────────────────────────────────────────────────────
    coordinate_system: Mapped[str | None] = mapped_column(String(30))
    coordinate_from: Mapped[Decimal | None] = mapped_column(Numeric)
    coordinate_to: Mapped[Decimal | None] = mapped_column(Numeric)
    coordinate_unit: Mapped[str | None] = mapped_column(String(10))
    wraps_zero: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # ── Объём (§12) ───────────────────────────────────────────────────────────
    controlled_volume_value: Mapped[Decimal | None] = mapped_column(Numeric)
    controlled_volume_unit: Mapped[str | None] = mapped_column(String(10))
    coverage_percent: Mapped[Decimal | None] = mapped_column(Numeric)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)

    # ── Индикация ─────────────────────────────────────────────────────────────
    indication_description: Mapped[str | None] = mapped_column(Text)
    indication_coordinate_from: Mapped[Decimal | None] = mapped_column(Numeric)
    indication_coordinate_to: Mapped[Decimal | None] = mapped_column(Numeric)
    indication_coordinate_unit: Mapped[str | None] = mapped_column(String(10))

    # ── Оценка (§10.6) ────────────────────────────────────────────────────────
    evaluation: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=mew.EVAL_NOT_EVALUATED
    )
    required_action: Mapped[str | None] = mapped_column(String(30))
    laboratory_result_text: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    # ── Источник строки и причина исключения ──────────────────────────────────
    source_page_reference: Mapped[str | None] = mapped_column(String(100))
    source_row_reference: Mapped[str | None] = mapped_column(String(100))
    source_note: Mapped[str | None] = mapped_column(Text)
    excluded_reason: Mapped[str | None] = mapped_column(Text)

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


# ── Стандарт выполнения (§14.2 задания) ────────────────────────────────────────


class MethodExecutionStandard(Base):
    """Нормативный документ (стандарт) выполнения со снимком реквизитов (§14.2).

    Ссылается на выполнение с `ON DELETE RESTRICT`. Отдельный глобальный модуль
    стандартов в Task 9C не создаётся: только снимок кода/названия/редакции и
    необязательная ссылка на документ.
    """

    __tablename__ = "method_execution_standards"
    __table_args__ = (
        Index("ix_quality_mstd_execution", "method_execution_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    method_execution_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EXECUTIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    standard_document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    standard_code_snapshot: Mapped[str | None] = mapped_column(String(100))
    standard_title_snapshot: Mapped[str | None] = mapped_column(Text)
    revision_snapshot: Mapped[str | None] = mapped_column(String(100))

    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Лабораторное заключение (§15 задания) ──────────────────────────────────────

# ISSUED обязателен номер/год/дата выпуска (§16).
_CONCLUSION_ISSUED_CHECK = (
    "status <> 'ISSUED' OR ("
    "conclusion_number IS NOT NULL "
    "AND conclusion_year IS NOT NULL "
    "AND issued_at IS NOT NULL)"
)
# CANCELLED непротиворечив: автор/время/непустая причина (§16).
_CONCLUSION_CANCELLED_CHECK = (
    "status <> 'CANCELLED' OR ("
    "cancelled_at IS NOT NULL "
    "AND cancelled_by_worker_id IS NOT NULL "
    "AND length(trim(cancellation_reason)) > 0)"
)


class LaboratoryConclusion(Base):
    """Официальный документ лаборатории, объединяющий выполнения (§15).

    Одно заключение — одна лаборатория, один проект, один метод (`inspection_method_
    id`); может объединять несколько выполнений и несколько соединений. Единый итог
    ACCEPTABLE/UNACCEPTABLE не хранится. Номер нормализован: partial unique
    `(laboratory_company_id, conclusion_number, conclusion_year) WHERE status='ISSUED'`
    — независимые заключения лаборатории не дублируют номер в году, а редакции одного
    root наследуют его (в ISSUED одновременно только одна редакция root). Одна
    текущая редакция — partial unique `WHERE is_current`.
    """

    __tablename__ = CONCLUSIONS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_quality_labconc_version"),
        CheckConstraint("revision_no >= 1", name="ck_quality_labconc_revision_no"),
        CheckConstraint(
            _in("status", lcw.CONCLUSION_STATUSES), name="ck_quality_labconc_status"
        ),
        CheckConstraint(
            _in("inspection_method_id", INSPECTION_METHOD_CODES),
            name="ck_quality_labconc_method",
        ),
        CheckConstraint(
            "conclusion_year IS NULL OR (conclusion_year BETWEEN 1900 AND 3000)",
            name="ck_quality_labconc_year_range",
        ),
        CheckConstraint(_CONCLUSION_ISSUED_CHECK, name="ck_quality_labconc_issued"),
        CheckConstraint(
            _CONCLUSION_CANCELLED_CHECK, name="ck_quality_labconc_cancelled"
        ),
        # Нормализованная уникальность номера (§20 / §5 блока 9C-5): индекс по
        # normalized_conclusion_number (миграция 18), исходный номер — отдельно.
        Index(
            "uq_quality_labconc_issued_number",
            "laboratory_company_id",
            "normalized_conclusion_number",
            "conclusion_year",
            unique=True,
            postgresql_where="status = 'ISSUED'",
        ),
        Index(
            "uq_quality_labconc_current_revision",
            "root_conclusion_id",
            unique=True,
            postgresql_where="is_current",
        ),
        Index("ix_quality_labconc_project", "project_id"),
        Index("ix_quality_labconc_laboratory", "laboratory_company_id"),
        Index("ix_quality_labconc_status", "status"),
        Index("ix_quality_labconc_root", "root_conclusion_id"),
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
    laboratory_company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    inspection_method_id: Mapped[str] = mapped_column(String(10), nullable=False)

    # ── Ревизии (§19) ─────────────────────────────────────────────────────────
    root_conclusion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    supersedes_conclusion_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{CONCLUSIONS_TABLE}.id", ondelete="SET NULL"),
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    external_revision_label: Mapped[str | None] = mapped_column(String(100))
    correction_reason: Mapped[str | None] = mapped_column(Text)

    # ── Реквизиты документа ───────────────────────────────────────────────────
    conclusion_number: Mapped[str | None] = mapped_column(String(100))
    conclusion_year: Mapped[int | None] = mapped_column(Integer)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    request_reference: Mapped[str | None] = mapped_column(Text)
    request_date: Mapped[date | None] = mapped_column(Date)
    requesting_company_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(f"{PROJECT_SCHEMA}.companies.id", ondelete="RESTRICT"),
    )

    # ── Снимок аккредитации (§21) ─────────────────────────────────────────────
    laboratory_accreditation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{ACCREDITATIONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )
    laboratory_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    accreditation_number_snapshot: Mapped[str | None] = mapped_column(String(100))
    accreditation_valid_from_snapshot: Mapped[date | None] = mapped_column(Date)
    accreditation_valid_until_snapshot: Mapped[date | None] = mapped_column(Date)
    accreditation_scope_snapshot: Mapped[str | None] = mapped_column(Text)

    # ── Утверждающее лицо и выдавший (§7 / §15) ───────────────────────────────
    lab_approver_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{EXTERNAL_PERSONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )
    issued_by_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{EXTERNAL_PERSONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )

    source_type: Mapped[str | None] = mapped_column(String(40))
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=lcw.CONCLUSION_DRAFT
    )

    lab_approved_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    lab_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    revision_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    revision_review_reason: Mapped[str | None] = mapped_column(Text)

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
    # Миграция 18 добавила нормализованный номер после исходной структуры таблицы.
    normalized_conclusion_number: Mapped[str | None] = mapped_column(String(100))


# ── Связь заключение ↔ конкретная редакция выполнения (§17 задания) ─────────────


class LaboratoryConclusionExecution(Base):
    """Связь заключения с конкретной редакцией выполнения (§17).

    Обе стороны — `ON DELETE RESTRICT` (не каскадим производственную историю).
    После выпуска заключения связь не переключается автоматически на новую редакцию
    выполнения (§17): актуализация — новой редакцией заключения.
    """

    __tablename__ = "laboratory_conclusion_executions"
    __table_args__ = (
        UniqueConstraint(
            "laboratory_conclusion_id",
            "method_execution_id",
            name="uq_quality_labconc_exec_pair",
        ),
        Index("ix_quality_labconc_exec_conclusion", "laboratory_conclusion_id"),
        Index("ix_quality_labconc_exec_execution", "method_execution_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    laboratory_conclusion_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{CONCLUSIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    method_execution_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{QUALITY_SCHEMA}.{EXECUTIONS_TABLE}.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Доменный аудит (§23 задания) ───────────────────────────────────────────────


class QualityAuditEvent(Base):
    """Полиморфный журнал значимых действий контроля (§23), append-only.

    `entity_type`/`entity_id` без FK (как InspectionEvent Task 9A) — журнал
    покрывает разнотипные сущности. JSONB только для changed_fields/previous/new;
    основные доменные данные в JSON не хранятся. API изменения/удаления событий нет.
    """

    __tablename__ = "quality_audit_events"
    __table_args__ = (
        CheckConstraint(
            _in("entity_type", mew.QUALITY_AUDIT_ENTITY_TYPES),
            name="ck_quality_audit_entity_type",
        ),
        CheckConstraint(
            _in("event_type", mew.QUALITY_AUDIT_EVENT_TYPES),
            name="ck_quality_audit_event_type",
        ),
        CheckConstraint(
            "entity_type <> 'QUALITY_DECISION' "
            "OR authorization_context IS NOT NULL",
            name="ck_quality_audit_qd_authorization_context",
        ),
        Index("ix_quality_audit_entity", "entity_type", "entity_id"),
        Index("ix_quality_audit_occurred_at", "occurred_at"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_fields: Mapped[dict | None] = mapped_column(JSONB)
    previous_values: Mapped[dict | None] = mapped_column(JSONB)
    new_values: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    authorization_context: Mapped[dict | None] = mapped_column(JSONB)
