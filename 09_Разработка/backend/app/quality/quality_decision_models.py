"""ORM-модели ядра QualityDecision (Task 10A, Implementation Block 1; ADR-027 ACCEPTED).

Четыре физические таблицы схемы `quality`:

* `quality_decisions` — официальное решение по качеству, принятое на основании одной или
  нескольких `EngineeringEvaluationRevision` конкретного `Joint`. Не заменяет
  `EngineeringEvaluation`, `Defect` или `DefectDisposition` (ADR-027 §B). Номер —
  `<PROJECT_CODE>-QD-<SEQUENCE>` (поле `system_code`, как в `EngineeringEvaluation`/
  `Inspection`);
* `quality_decision_bases` — основание принятого решения: ссылка на конкретную
  `EngineeringEvaluationRevision` (не на header `EngineeringEvaluation`, ADR-027 §C).
  Минимум одно основание на `QualityDecision` и требование статуса `EFFECTIVE` у
  ревизии — service-level правила (Block 2), не CHECK;
* `quality_decision_sequences` — проектный счётчик номера (per-project, как
  `EngineeringEvaluationSequence`).
* `quality_decision_idempotency_records` — атомарный журнал успешных command
  response snapshots для replay пяти мутирующих команд (Recovery Addendum L.2).

Статусы (ADR-027 ACCEPTED, Q-D8): ровно четыре персистентных значения — `DRAFT`,
`UNDER_REVIEW`, `DECIDED`, `SUPERSEDED`. `RETURNED` не является персистентным статусом:
возврат на доработку — атомарная команда `RETURN` (`UNDER_REVIEW → DRAFT`), видимая только
в audit trail (Block 2).

Инварианты БД (Task 10A + ADR-027 §F, ACCEPTED; Q-D2 скорректировано Block 1 Correction
2026-07-23 после архитектурного review):

* `UNIQUE(system_code)` — глобальная уникальность номера;
* `UNIQUE(joint_id) WHERE status = 'DECIDED'` — не более одного действующего решения на
  Joint одновременно. **Единственное ограничение количества** по Joint;
* `DRAFT` и `UNDER_REVIEW` — количество на Joint **не ограничивается** (Q-D2, уточнённое
  решение: разрешено несколько `DRAFT`/`UNDER_REVIEW` одновременно на один Joint; ранее
  ошибочно реализованный `UNIQUE(joint_id) WHERE status IN ('DRAFT', 'UNDER_REVIEW')`
  удалён — не соответствовал принятому решению);
* `UNIQUE(engineering_evaluation_revision_id) WHERE is_basis_of_decided = true` — одна
  ревизия не может быть основанием более чем одного `DECIDED` `QualityDecision`
  одновременно (ADR-027 §F.3). Переключение флага — обязанность сервиса (Block 2), под
  той же транзакцией, что переход статуса решения.

Стиль Tasks 9A–9D-4A: перечисления — CHECK (без native enum); actor-поля
(`*_by_worker_id`) — hr.workers.id типа Integer БЕЗ FK (переходный период); время —
timestamptz; `version` — optimistic locking. Физического удаления нет; история решений
(`SUPERSEDED`) хранится вечно.
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
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering.models import ENGINEERING_SCHEMA
from app.projects.models import PROJECT_SCHEMA
from app.quality.engineering_evaluation_models import REVISIONS_TABLE
from app.shared.orm import Base

# Дублируется намеренно (как в остальных модулях quality): независимый импорт модуля.
QUALITY_SCHEMA = "quality"

QUALITY_DECISIONS_TABLE = "quality_decisions"
QUALITY_DECISION_BASES_TABLE = "quality_decision_bases"
QUALITY_DECISION_SEQUENCES_TABLE = "quality_decision_sequences"
QUALITY_DECISION_IDEMPOTENCY_TABLE = "quality_decision_idempotency_records"

QUALITY_DECISION_IDEMPOTENT_COMMANDS: tuple[str, ...] = (
    "CREATE",
    "UPDATE_DRAFT",
    "SUBMIT_FOR_REVIEW",
    "RETURN",
    "DECIDE",
)
QUALITY_DECISION_IDEMPOTENCY_TARGET_TYPES: tuple[str, ...] = (
    "JOINT",
    "QUALITY_DECISION",
)

# ── Статусы QualityDecision (ADR-027 ACCEPTED, Q-D8: ровно четыре значения) ─────
QUALITY_DECISION_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "UNDER_REVIEW",
    "DECIDED",
    "SUPERSEDED",
)

QUALITY_DECISION_DRAFT = "DRAFT"
QUALITY_DECISION_UNDER_REVIEW = "UNDER_REVIEW"
QUALITY_DECISION_DECIDED = "DECIDED"
QUALITY_DECISION_SUPERSEDED = "SUPERSEDED"

# ── Результат решения (ADR-027 §C; nullable до DECIDED) ─────────────────────────
QUALITY_DECISION_RESULTS: tuple[str, ...] = (
    "ACCEPTED",
    "NOT_CONFIRMED",
    "DEFECT_CONFIRMED",
)

QUALITY_DECISION_RESULT_ACCEPTED = "ACCEPTED"
QUALITY_DECISION_RESULT_NOT_CONFIRMED = "NOT_CONFIRMED"
QUALITY_DECISION_RESULT_DEFECT_CONFIRMED = "DEFECT_CONFIRMED"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _null_or_in(column: str, values: tuple[str, ...]) -> str:
    """enum-CHECK, действующий только при NOT NULL (`decision_result` nullable до DECIDED)."""
    return f"{column} IS NULL OR {_in(column, values)}"


class QualityDecision(Base):
    """Официальное решение по качеству для одного Joint (ADR-027; Task 10A).

    Принадлежит одному `Joint`, опирается на ≥1 `QualityDecisionBasis` (проверка —
    сервис, Block 2). `supersedes_quality_decision_id` заполняется системой в момент
    `DECIDE`, если у Joint уже был `DECIDED` (lineage, не ручная команда, ADR-027 §G).
    `APPROVED` не используется как статус: утверждение хранится отдельными полями
    (`approved_*`), заполняемыми только командой `DECIDE`.
    """

    __tablename__ = QUALITY_DECISIONS_TABLE
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_quality_decisions_version"),
        CheckConstraint(
            "length(trim(system_code)) > 0",
            name="ck_quality_decisions_system_code_not_empty",
        ),
        CheckConstraint(
            _in("status", QUALITY_DECISION_STATUSES),
            name="ck_quality_decisions_status",
        ),
        CheckConstraint(
            _null_or_in("decision_result", QUALITY_DECISION_RESULTS),
            name="ck_quality_decisions_decision_result",
        ),
        # Решение не может замещать само себя (принадлежность одному Joint
        # проверяет сервис; self-reference безопасно закрывается CHECK).
        CheckConstraint(
            "supersedes_quality_decision_id IS NULL OR "
            "supersedes_quality_decision_id <> id",
            name="ck_quality_decisions_no_self_supersede",
        ),
        # Утверждение фиксируется парой actor+time целиком либо не фиксируется вовсе.
        CheckConstraint(
            "(approved_at IS NULL) = (approved_by_worker_id IS NULL)",
            name="ck_quality_decisions_approved_pair",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND review_submitted_by_worker_id IS NULL) OR "
            "(status IN ('UNDER_REVIEW', 'DECIDED', 'SUPERSEDED') "
            "AND review_submitted_by_worker_id IS NOT NULL)",
            name="ck_quality_decisions_review_submitter_state",
        ),
        Index(
            "uq_quality_decisions_system_code", "system_code", unique=True
        ),
        # Не более одного действующего решения на Joint одновременно (ADR-027 §F.2).
        # Единственное ограничение количества по Joint (Q-D2, уточнено Block 1
        # Correction): DRAFT/UNDER_REVIEW на один Joint не ограничиваются.
        Index(
            "uq_quality_decisions_one_decided_per_joint",
            "joint_id",
            unique=True,
            postgresql_where=text("status = 'DECIDED'"),
        ),
        Index("ix_quality_decisions_project_id", "project_id"),
        Index("ix_quality_decisions_joint_id", "joint_id"),
        Index("ix_quality_decisions_status", "status"),
        Index("ix_quality_decisions_joint_status", "joint_id", "status"),
        Index("ix_quality_decisions_created_by", "created_by_worker_id"),
        Index(
            "ix_quality_decisions_supersedes",
            "supersedes_quality_decision_id",
        ),
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

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=QUALITY_DECISION_DRAFT
    )
    decision_result: Mapped[str | None] = mapped_column(String(30))

    summary: Mapped[str | None] = mapped_column(Text)
    return_reason: Mapped[str | None] = mapped_column(Text)

    supersedes_quality_decision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{QUALITY_DECISIONS_TABLE}.id", ondelete="RESTRICT"
        ),
    )

    created_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by_worker_id: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_role: Mapped[str | None] = mapped_column(String(40))

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    review_submitted_by_worker_id: Mapped[int | None] = mapped_column(Integer)


class QualityDecisionBasis(Base):
    """Основание принятого решения — ссылка на `EngineeringEvaluationRevision`.

    `is_basis_of_decided` — `true` только для строк владеющей `DECIDED`-записи
    (ADR-027 §F.3); переключение и проверка «revision.status == EFFECTIVE» — service-
    level (Block 2), не CHECK. `UNIQUE(quality_decision_id,
    engineering_evaluation_revision_id)` — техническая защита от дублирования одной и
    той же ревизии в составе оснований одного решения (не предписано ADR явно, но
    следует общему стилю join-таблиц проекта, см. `uq_ee_exceptions_revision_criterion`).
    """

    __tablename__ = QUALITY_DECISION_BASES_TABLE
    __table_args__ = (
        Index(
            "uq_quality_decision_bases_decision_revision",
            "quality_decision_id",
            "engineering_evaluation_revision_id",
            unique=True,
        ),
        # Одна EngineeringEvaluationRevision не может быть основанием более чем
        # одного DECIDED QualityDecision одновременно (ADR-027 §F.3).
        Index(
            "uq_quality_decision_bases_one_decided_per_revision",
            "engineering_evaluation_revision_id",
            unique=True,
            postgresql_where=text("is_basis_of_decided = true"),
        ),
        Index(
            "ix_quality_decision_bases_quality_decision_id", "quality_decision_id"
        ),
        Index(
            "ix_quality_decision_bases_revision_id",
            "engineering_evaluation_revision_id",
        ),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    quality_decision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{QUALITY_DECISIONS_TABLE}.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    engineering_evaluation_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{REVISIONS_TABLE}.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    is_basis_of_decided: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    linked_by_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QualityDecisionSequence(Base):
    """Служебный проектный счётчик номера решения (`<PROJECT_CODE>-QD-<SEQUENCE>`).

    Та же схема, что `EngineeringEvaluationSequence`: значение выдаётся атомарно
    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` в сервисном слое (Block 2).
    """

    __tablename__ = QUALITY_DECISION_SEQUENCES_TABLE
    __table_args__ = (
        CheckConstraint(
            "last_value >= 0", name="ck_quality_decision_sequences_last_value"
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


class QualityDecisionIdempotencyRecord(Base):
    """Успешный command replay Task 10A (ADR-027 Addendum L.2).

    Запись сохраняется в одной транзакции с state и audit. `target_id` указывает
    на Joint для CREATE и на QualityDecision для остальных команд.
    """

    __tablename__ = QUALITY_DECISION_IDEMPOTENCY_TABLE
    __table_args__ = (
        CheckConstraint(
            _in("command_type", QUALITY_DECISION_IDEMPOTENT_COMMANDS),
            name="ck_qd_idem_command_type",
        ),
        CheckConstraint(
            _in("target_type", QUALITY_DECISION_IDEMPOTENCY_TARGET_TYPES),
            name="ck_qd_idem_target_type",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_qd_idem_key_not_empty",
        ),
        CheckConstraint(
            "response_status BETWEEN 200 AND 299",
            name="ck_qd_idem_response_status",
        ),
        Index(
            "uq_qd_idem_command_target_key",
            "actor_worker_id",
            "command_type",
            "target_type",
            "target_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_qd_idem_quality_decision_id", "quality_decision_id"),
        {"schema": QUALITY_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    command_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_decision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{QUALITY_SCHEMA}.{QUALITY_DECISIONS_TABLE}.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
