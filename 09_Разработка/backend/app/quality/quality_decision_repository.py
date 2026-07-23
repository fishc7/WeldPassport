"""Репозиторий QualityDecision (Task 10A, Implementation Block 2; ADR-027 ACCEPTED).

Только persistence/query — доменные правила (переходы, роли, комплектность
оснований, supersede) в сервисе (`quality_decision_services`). Commit — в сервисе.

Локирует по требованию Block 2 §CONCURRENCY: строку `QualityDecision` (повторный
DECIDE/UPDATE_DRAFT/SUBMIT/RETURN одной и той же записи), строку `Joint` (два
параллельных DECIDE на РАЗНЫЕ QualityDecision одного Joint) и строки
`EngineeringEvaluationRevision`-оснований (переключение `is_basis_of_decided`).
`Joint` и `EngineeringEvaluationRevision` принадлежат другим модулям (engineering /
EngineeringEvaluation) — здесь только чтение и блокировка строки, без записи; их
собственные модули (модели/сервисы) не меняются (аналог `lock_root_for_update` в
`DefectDispositionRepository`, где блокируется чужая для disposition, но своя для
quality-домена таблица `defect_roots`).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.quality import method_execution_workflow as mew
from app.quality.engineering_evaluation_models import EngineeringEvaluationRevision
from app.quality.execution_models import QualityAuditEvent
from app.quality.quality_decision_models import (
    QUALITY_DECISION_DECIDED,
    QUALITY_DECISION_SEQUENCES_TABLE,
    QUALITY_SCHEMA,
    QualityDecision,
    QualityDecisionBasis,
)


class QualityDecisionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Нумерация (паттерн EngineeringEvaluationRepository.next_evaluation_sequence) ─

    def next_sequence(self, project_id: UUID) -> int:
        """Атомарно выдаёт следующий номер последовательности проекта.

        `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` берёт блокировку строки
        счётчика — гонки `MAX()+1` нет. Стартовое значение 0, первая выдача → 1.
        """
        result = self.db.execute(
            text(
                f"""
                INSERT INTO {QUALITY_SCHEMA}.{QUALITY_DECISION_SEQUENCES_TABLE}
                    (project_id, last_value, updated_at)
                VALUES (CAST(:pid AS uuid), 1, now())
                ON CONFLICT (project_id)
                DO UPDATE SET
                    last_value = {QUALITY_SCHEMA}.{QUALITY_DECISION_SEQUENCES_TABLE}.last_value + 1,
                    updated_at = now()
                RETURNING last_value
                """
            ),
            {"pid": str(project_id)},
        )
        return int(result.scalar_one())

    # ── QualityDecision ──────────────────────────────────────────────────────────

    def get_by_id(self, decision_id: UUID) -> QualityDecision | None:
        return self.db.get(QualityDecision, decision_id)

    def get_by_id_for_update(self, decision_id: UUID) -> QualityDecision | None:
        """Блокирует строку решения (SELECT … FOR UPDATE) — сериализация повторного
        UPDATE_DRAFT/SUBMIT/RETURN/DECIDE над одной записью."""
        return (
            self.db.query(QualityDecision)
            .filter(QualityDecision.id == decision_id)
            .with_for_update()
            .first()
        )

    def lock_joint_for_update(self, joint_id: UUID) -> Joint | None:
        """Блокирует строку Joint (SELECT … FOR UPDATE), Task 10A Block 2 §CONCURRENCY.

        Нужна только в `DECIDE`: исключает гонку двух РАЗНЫХ QualityDecision одного
        Joint, одновременно претендующих на `DECIDED` (партиционный
        `uq_quality_decisions_one_decided_per_joint`). Только чтение/lock строки
        Joint — engineering-модуль не меняется.
        """
        return (
            self.db.query(Joint).filter(Joint.id == joint_id).with_for_update().first()
        )

    def find_decided_for_joint(self, joint_id: UUID) -> QualityDecision | None:
        return (
            self.db.execute(
                select(QualityDecision).where(
                    QualityDecision.joint_id == joint_id,
                    QualityDecision.status == QUALITY_DECISION_DECIDED,
                )
            )
            .scalars()
            .first()
        )

    def list_for_joint(self, joint_id: UUID) -> list[QualityDecision]:
        return list(
            self.db.execute(
                select(QualityDecision)
                .where(QualityDecision.joint_id == joint_id)
                .order_by(QualityDecision.created_at)
            )
            .scalars()
            .all()
        )

    def add(self, decision: QualityDecision) -> QualityDecision:
        self.db.add(decision)
        self.db.flush()
        return decision

    # ── QualityDecisionBasis ─────────────────────────────────────────────────────

    def list_bases(self, decision_id: UUID) -> list[QualityDecisionBasis]:
        return list(
            self.db.execute(
                select(QualityDecisionBasis).where(
                    QualityDecisionBasis.quality_decision_id == decision_id
                )
            )
            .scalars()
            .all()
        )

    def add_basis(self, basis: QualityDecisionBasis) -> QualityDecisionBasis:
        self.db.add(basis)
        self.db.flush()
        return basis

    def delete_basis(self, basis: QualityDecisionBasis) -> None:
        self.db.delete(basis)
        self.db.flush()

    def find_basis_row_for_revision(
        self, revision_id: UUID, *, is_basis_of_decided: bool = True
    ) -> QualityDecisionBasis | None:
        """Строка-основание, где ревизия уже помечена как основание DECIDED — для
        проверки партиционного unique-инварианта до его переключения в DECIDE."""
        return (
            self.db.execute(
                select(QualityDecisionBasis).where(
                    QualityDecisionBasis.engineering_evaluation_revision_id
                    == revision_id,
                    QualityDecisionBasis.is_basis_of_decided.is_(is_basis_of_decided),
                )
            )
            .scalars()
            .first()
        )

    # ── EngineeringEvaluationRevision (только чтение/lock; модуль не меняется) ────

    def get_revision(self, revision_id: UUID) -> EngineeringEvaluationRevision | None:
        return self.db.get(EngineeringEvaluationRevision, revision_id)

    def lock_revisions_for_update(
        self, revision_ids: list[UUID]
    ) -> list[EngineeringEvaluationRevision]:
        """Блокирует строки ревизий-оснований (SELECT … FOR UPDATE), отсортированные
        по id — фиксированный порядок исключает deadlock при параллельных DECIDE с
        пересекающимся набором оснований (Task 10A Block 2 §CONCURRENCY)."""
        if not revision_ids:
            return []
        ordered_ids = sorted(set(revision_ids), key=str)
        return (
            self.db.query(EngineeringEvaluationRevision)
            .filter(EngineeringEvaluationRevision.id.in_(ordered_ids))
            .order_by(EngineeringEvaluationRevision.id)
            .with_for_update()
            .all()
        )

    # ── Аудит (quality_audit_events, полиморфно; Task 10A Block 1 расширение CHECK) ─

    def append_audit_event(self, event: QualityAuditEvent) -> QualityAuditEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_audit_events(self, decision_id: UUID) -> list[QualityAuditEvent]:
        return list(
            self.db.execute(
                select(QualityAuditEvent)
                .where(
                    QualityAuditEvent.entity_type == mew.AUDIT_ENTITY_QUALITY_DECISION,
                    QualityAuditEvent.entity_id == decision_id,
                )
                .order_by(QualityAuditEvent.occurred_at)
            )
            .scalars()
            .all()
        )

    def save(self) -> None:
        self.db.commit()
