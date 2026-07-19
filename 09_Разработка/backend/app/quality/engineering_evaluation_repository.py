"""Репозиторий ядра EngineeringEvaluation (Task 9D-2A, ADR-021).

Слой доступа к данным без бизнес-правил lifecycle (команды/RBAC/API — блок 9D-2D).
Предоставляет: атомарную выдачу проектного номера, создание оценки с первой
DRAFT-ревизией и событием `EVALUATION_CREATED`, чтение, правку DRAFT-ревизии с
optimistic locking и событием `EVALUATION_UPDATED`, добавление событий (append-only).

Целостность указателей `current_revision_id` / `effective_revision_id` (плоский UUID
без FK, 9D-2A-T01) поддерживается здесь, на domain-слое.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_workflow as eew
from app.quality.engineering_evaluation_models import (
    EngineeringEvaluation,
    EngineeringEvaluationEvent,
    EngineeringEvaluationRevision,
    QUALITY_SCHEMA,
    SEQUENCES_TABLE,
)

# Поля DRAFT-ревизии, редактируемые через update_revision (содержание оценки, C10).
_EDITABLE_REVISION_FIELDS: frozenset[str] = frozenset(
    {
        "evaluation_outcome",
        "classification",
        "recommended_disposition",
        "confirmed_severity",
        "impact_scope",
        "rationale",
        "confidence_level",
        "confidence_note",
        "residual_risk",
        "application_conditions",
        "review_due_at",
        "revision_reason",
        "supersedes_impact",
        "required_approval_route",
    }
)


class EngineeringEvaluationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Нумерация ──────────────────────────────────────────────────────────────

    def next_evaluation_sequence(self, project_id: UUID) -> int:
        """Атомарно выдаёт следующий номер последовательности проекта.

        `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` берёт блокировку строки
        счётчика — гонки `MAX()+1` нет. Стартовое значение 0, первая выдача → 1.
        """
        result = self.db.execute(
            text(
                f"""
                INSERT INTO {QUALITY_SCHEMA}.{SEQUENCES_TABLE}
                    (project_id, last_value, updated_at)
                VALUES (CAST(:pid AS uuid), 1, now())
                ON CONFLICT (project_id)
                DO UPDATE SET
                    last_value = {QUALITY_SCHEMA}.{SEQUENCES_TABLE}.last_value + 1,
                    updated_at = now()
                RETURNING last_value
                """
            ),
            {"pid": str(project_id)},
        )
        return int(result.scalar_one())

    # ── Создание оценки + первой DRAFT-ревизии ─────────────────────────────────

    def create_evaluation(
        self,
        *,
        project_id: UUID,
        finding_id: UUID,
        project_code: str,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> tuple[EngineeringEvaluation, EngineeringEvaluationRevision]:
        """Создаёт логическую оценку и первую DRAFT-ревизию в одной транзакции.

        Номер `<PROJECT_CODE>-EE-<SEQUENCE>` выдаётся при создании. Пишется событие
        `EVALUATION_CREATED`. `current_revision_id` указывает на первую ревизию.
        `UNIQUE(finding_id)` на уровне БД гарантирует одну оценку на finding.
        """
        seq = self.next_evaluation_sequence(project_id)
        system_code = f"{project_code}-EE-{seq}"

        evaluation = EngineeringEvaluation(
            project_id=project_id,
            finding_id=finding_id,
            system_code=system_code,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
        )
        self.db.add(evaluation)
        self.db.flush()

        revision = EngineeringEvaluationRevision(
            evaluation_id=evaluation.id,
            revision_no=1,
            status=eew.EVAL_DRAFT,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
        )
        self.db.add(revision)
        self.db.flush()

        evaluation.current_revision_id = revision.id
        self.db.flush()

        self.add_event(
            EngineeringEvaluationEvent(
                evaluation_id=evaluation.id,
                revision_id=revision.id,
                event_type=eew.EVENT_EVALUATION_CREATED,
                to_status=eew.EVAL_DRAFT,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                revision_version=revision.version,
            )
        )
        return evaluation, revision

    # ── Чтение ─────────────────────────────────────────────────────────────────

    def get_evaluation(self, evaluation_id: UUID) -> EngineeringEvaluation | None:
        return (
            self.db.query(EngineeringEvaluation)
            .filter(EngineeringEvaluation.id == evaluation_id)
            .first()
        )

    def get_by_finding(self, finding_id: UUID) -> EngineeringEvaluation | None:
        return (
            self.db.query(EngineeringEvaluation)
            .filter(EngineeringEvaluation.finding_id == finding_id)
            .first()
        )

    def get_revision(
        self, revision_id: UUID
    ) -> EngineeringEvaluationRevision | None:
        return (
            self.db.query(EngineeringEvaluationRevision)
            .filter(EngineeringEvaluationRevision.id == revision_id)
            .first()
        )

    def list_revisions(
        self, evaluation_id: UUID
    ) -> list[EngineeringEvaluationRevision]:
        return (
            self.db.query(EngineeringEvaluationRevision)
            .filter(EngineeringEvaluationRevision.evaluation_id == evaluation_id)
            .order_by(EngineeringEvaluationRevision.revision_no)
            .all()
        )

    # ── Правка DRAFT-ревизии (optimistic locking) ──────────────────────────────

    def update_revision(
        self,
        revision: EngineeringEvaluationRevision,
        *,
        expected_version: int,
        actor_worker_id: int,
        fields: dict[str, Any],
        actor_role: str | None = None,
    ) -> EngineeringEvaluationRevision:
        """Правит содержание DRAFT-ревизии.

        Редактирование разрешено только в DRAFT (граница §6). Несовпадение версии →
        `EVAL_VERSION_CONFLICT`. Обновляет только поля из `_EDITABLE_REVISION_FIELDS`.
        Пишет событие `EVALUATION_UPDATED`; `version` инкрементится.
        """
        if not eew.is_editable_status(revision.status):
            raise eew.EvaluationError(
                eew.EVAL_REVISION_NOT_DRAFT,
                "Редактирование содержания разрешено только в DRAFT",
            )
        if revision.version != expected_version:
            raise eew.EvaluationError(
                eew.EVAL_VERSION_CONFLICT, "Версия ревизии изменилась"
            )

        unknown = set(fields) - _EDITABLE_REVISION_FIELDS
        if unknown:
            raise eew.EvaluationError(
                eew.EVAL_REVISION_NOT_DRAFT,
                f"Недопустимые поля правки: {sorted(unknown)}",
            )
        for key, value in fields.items():
            setattr(revision, key, value)
        revision.updated_by_worker_id = actor_worker_id
        revision.version += 1
        self.db.flush()

        self.add_event(
            EngineeringEvaluationEvent(
                evaluation_id=revision.evaluation_id,
                revision_id=revision.id,
                event_type=eew.EVENT_EVALUATION_UPDATED,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                revision_version=revision.version,
            )
        )
        return revision

    # ── Журнал (append-only) ───────────────────────────────────────────────────

    def add_event(
        self, event: EngineeringEvaluationEvent
    ) -> EngineeringEvaluationEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(
        self, evaluation_id: UUID
    ) -> list[EngineeringEvaluationEvent]:
        return (
            self.db.query(EngineeringEvaluationEvent)
            .filter(EngineeringEvaluationEvent.evaluation_id == evaluation_id)
            .order_by(
                EngineeringEvaluationEvent.created_at,
                EngineeringEvaluationEvent.id,
            )
            .all()
        )

    def save(self) -> None:
        self.db.commit()
