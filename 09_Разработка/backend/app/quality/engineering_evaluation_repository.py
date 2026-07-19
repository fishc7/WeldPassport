"""Репозиторий ядра EngineeringEvaluation (Task 9D-2A, ADR-021).

Слой доступа к данным без бизнес-правил lifecycle (команды/RBAC/API — блок 9D-2D).
Предоставляет: атомарную выдачу проектного номера, создание оценки с первой
DRAFT-ревизией и событием `EVALUATION_CREATED`, чтение, правку DRAFT-ревизии с
optimistic locking и событием `EVALUATION_UPDATED`, добавление событий (append-only).

Целостность указателей `current_revision_id` / `effective_revision_id` (плоский UUID
без FK, 9D-2A-T01) поддерживается здесь, на domain-слое.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_hash as eeh
from app.quality import engineering_evaluation_validation as eev
from app.quality import engineering_evaluation_workflow as eew
from app.quality.engineering_evaluation_models import (
    EngineeringEvaluation,
    EngineeringEvaluationCriterion,
    EngineeringEvaluationEvent,
    EngineeringEvaluationRevision,
    EngineeringEvaluationSource,
    EngineeringException,
    QUALITY_SCHEMA,
    SEQUENCES_TABLE,
)

# Поля критерия, редактируемые через update_criterion (в DRAFT).
_EDITABLE_CRITERION_FIELDS: frozenset[str] = frozenset(
    {
        "requirement_ref",
        "clause",
        "parameter",
        "actual_value",
        "actual_num",
        "allowed_value",
        "allowed_num_min",
        "allowed_num_max",
        "unit",
        "comparison_result",
        "applicability_comment",
        "engineer_comment",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)

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

    def create_next_revision(
        self,
        evaluation: EngineeringEvaluation,
        *,
        revision_reason: str,
        previous_revision_id: UUID | None,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> EngineeringEvaluationRevision:
        """Персистит следующую DRAFT-ревизию пересмотра (lifecycle решает сервис).

        Номер `revision_no` монотонно растёт в пределах оценки (`MAX + 1`, гарантия —
        `UNIQUE(evaluation_id, revision_no)`). `revision_reason` обязателен со второй
        ревизии (CHECK). Указатель `current_revision_id` переводится на новую ревизию;
        `effective_revision_id` не трогается (действующая остаётся до `set-effective`).
        Событие `EVALUATION_CREATED` на уровне новой ревизии.
        """
        max_no = (
            self.db.query(func.max(EngineeringEvaluationRevision.revision_no))
            .filter(EngineeringEvaluationRevision.evaluation_id == evaluation.id)
            .scalar()
            or 0
        )
        revision = EngineeringEvaluationRevision(
            evaluation_id=evaluation.id,
            revision_no=max_no + 1,
            previous_revision_id=previous_revision_id,
            status=eew.EVAL_DRAFT,
            revision_reason=revision_reason,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
        )
        self.db.add(revision)
        self.db.flush()

        evaluation.current_revision_id = revision.id
        evaluation.updated_by_worker_id = actor_worker_id
        evaluation.version += 1
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
                event_metadata={"revision_no": revision.revision_no},
            )
        )
        return revision

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

    # ── Источники: add / remove / reverify (Task 9D-2B) ───────────────────────

    def _require_draft(self, revision: EngineeringEvaluationRevision) -> None:
        """Изменение источников/критериев разрешено только в DRAFT.

        После PREPARED/FIXED/EFFECTIVE содержимое ревизии неизменяемо; новое
        содержание после фиксации оформляется новой ревизией (§6, 9D-2B-C).
        """
        if not eew.is_editable_status(revision.status):
            raise eew.EvaluationError(
                eew.EVAL_REVISION_NOT_DRAFT,
                "Источники/критерии изменяются только в DRAFT",
            )

    def get_source(self, source_id: UUID) -> EngineeringEvaluationSource | None:
        return (
            self.db.query(EngineeringEvaluationSource)
            .filter(EngineeringEvaluationSource.id == source_id)
            .first()
        )

    def list_sources(self, revision_id: UUID) -> list[EngineeringEvaluationSource]:
        return (
            self.db.query(EngineeringEvaluationSource)
            .filter(EngineeringEvaluationSource.revision_id == revision_id)
            .order_by(EngineeringEvaluationSource.created_at)
            .all()
        )

    def add_source(
        self,
        revision: EngineeringEvaluationRevision,
        *,
        source_role: str,
        source_entity_type: str,
        source_entity_id: UUID,
        source_revision_id: UUID | None = None,
        applicability_note: str | None = None,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> EngineeringEvaluationSource:
        """Добавляет источник к DRAFT-ревизии.

        Ревизионный источник (`source_revision_id` задан) — хэш не вычисляется.
        Неревизионный — вычисляется `source_hash` + `hash_schema_version` по профилю
        (`EVAL_SOURCE_PROFILE_UNKNOWN` / `EVAL_SOURCE_UNAVAILABLE`). `verified_at`
        фиксируется при добавлении. Событие `SOURCE_ADDED`.
        """
        self._require_draft(revision)
        source_hash: str | None = None
        hash_schema_version: str | None = None
        if source_revision_id is None:
            source_hash, hash_schema_version = eeh.compute_source_hash(
                self.db,
                source_entity_type=source_entity_type,
                source_entity_id=source_entity_id,
            )
        source = EngineeringEvaluationSource(
            revision_id=revision.id,
            source_role=source_role,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            source_revision_id=source_revision_id,
            source_hash=source_hash,
            hash_schema_version=hash_schema_version,
            verified_at=_now(),
            applicability_note=applicability_note,
            created_by_worker_id=actor_worker_id,
        )
        self.db.add(source)
        self.db.flush()
        self._source_event(
            revision, source, eew.EVENT_SOURCE_ADDED, actor_worker_id, actor_role
        )
        return source

    def remove_source(
        self,
        source: EngineeringEvaluationSource,
        *,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> None:
        """Удаляет источник из DRAFT-ревизии (только с событием `SOURCE_REMOVED`)."""
        revision = self.get_revision(source.revision_id)
        assert revision is not None
        self._require_draft(revision)
        self._source_event(
            revision, source, eew.EVENT_SOURCE_REMOVED, actor_worker_id, actor_role
        )
        self.db.delete(source)
        self.db.flush()

    def reverify_source(
        self,
        source: EngineeringEvaluationSource,
        *,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> EngineeringEvaluationSource:
        """Повторно сверяет источник (без автоподмены хэша, ADR-021 §2.11).

        Неревизионный: пересчитывает текущий хэш и сравнивает с сохранённым;
        расхождение → `EVAL_SOURCE_STALE`, недоступность → `EVAL_SOURCE_UNAVAILABLE`;
        совпадение → обновляет `verified_at`. Событие `SOURCE_REVERIFIED`.
        """
        revision = self.get_revision(source.revision_id)
        assert revision is not None
        self._require_draft(revision)
        if source.source_revision_id is None:
            current_hash, _ = eeh.compute_source_hash(
                self.db,
                source_entity_type=source.source_entity_type,
                source_entity_id=source.source_entity_id,
            )
            if current_hash != source.source_hash:
                raise eew.EvaluationError(
                    eew.EVAL_SOURCE_STALE,
                    "Источник изменился с момента фиксации хэша",
                )
        source.verified_at = _now()
        self.db.flush()
        self._source_event(
            revision, source, eew.EVENT_SOURCE_REVERIFIED, actor_worker_id, actor_role
        )
        return source

    def _source_event(
        self,
        revision: EngineeringEvaluationRevision,
        source: EngineeringEvaluationSource,
        event_type: str,
        actor_worker_id: int,
        actor_role: str | None,
    ) -> None:
        self.add_event(
            EngineeringEvaluationEvent(
                evaluation_id=revision.evaluation_id,
                revision_id=revision.id,
                event_type=event_type,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                revision_version=revision.version,
                event_metadata={
                    "source_id": str(source.id),
                    "source_entity_type": source.source_entity_type,
                    "source_role": source.source_role,
                },
            )
        )

    # ── Критерии: add / update / remove (Task 9D-2B; событие EVALUATION_UPDATED) ─

    def get_criterion(
        self, criterion_id: UUID
    ) -> EngineeringEvaluationCriterion | None:
        return (
            self.db.query(EngineeringEvaluationCriterion)
            .filter(EngineeringEvaluationCriterion.id == criterion_id)
            .first()
        )

    def list_criteria(
        self, revision_id: UUID
    ) -> list[EngineeringEvaluationCriterion]:
        return (
            self.db.query(EngineeringEvaluationCriterion)
            .filter(EngineeringEvaluationCriterion.revision_id == revision_id)
            .order_by(EngineeringEvaluationCriterion.created_at)
            .all()
        )

    def add_criterion(
        self,
        revision: EngineeringEvaluationRevision,
        *,
        requirement_ref: str,
        parameter: str,
        comparison_result: str,
        actor_worker_id: int,
        actor_role: str | None = None,
        **optional: Any,
    ) -> EngineeringEvaluationCriterion:
        """Добавляет критерий к DRAFT-ревизии. Событие `EVALUATION_UPDATED` (C01)."""
        self._require_draft(revision)
        unknown = set(optional) - _EDITABLE_CRITERION_FIELDS
        if unknown:
            raise eew.EvaluationError(
                eew.EVAL_REVISION_NOT_DRAFT,
                f"Недопустимые поля критерия: {sorted(unknown)}",
            )
        criterion = EngineeringEvaluationCriterion(
            revision_id=revision.id,
            requirement_ref=requirement_ref,
            parameter=parameter,
            comparison_result=comparison_result,
            created_by_worker_id=actor_worker_id,
            **optional,
        )
        self.db.add(criterion)
        self.db.flush()
        self._criterion_event(
            revision, criterion.id, "ADD", actor_worker_id, actor_role
        )
        return criterion

    def update_criterion(
        self,
        criterion: EngineeringEvaluationCriterion,
        *,
        actor_worker_id: int,
        fields: dict[str, Any],
        actor_role: str | None = None,
    ) -> EngineeringEvaluationCriterion:
        """Правит критерий DRAFT-ревизии. Событие `EVALUATION_UPDATED` (C01)."""
        revision = self.get_revision(criterion.revision_id)
        assert revision is not None
        self._require_draft(revision)
        unknown = set(fields) - _EDITABLE_CRITERION_FIELDS
        if unknown:
            raise eew.EvaluationError(
                eew.EVAL_REVISION_NOT_DRAFT,
                f"Недопустимые поля критерия: {sorted(unknown)}",
            )
        for key, value in fields.items():
            setattr(criterion, key, value)
        self.db.flush()
        self._criterion_event(
            revision, criterion.id, "UPDATE", actor_worker_id, actor_role
        )
        return criterion

    def remove_criterion(
        self,
        criterion: EngineeringEvaluationCriterion,
        *,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> None:
        """Удаляет критерий DRAFT-ревизии. Событие `EVALUATION_UPDATED` (C01)."""
        revision = self.get_revision(criterion.revision_id)
        assert revision is not None
        self._require_draft(revision)
        criterion_id = criterion.id
        self.db.delete(criterion)
        self.db.flush()
        self._criterion_event(
            revision, criterion_id, "REMOVE", actor_worker_id, actor_role
        )

    def _criterion_event(
        self,
        revision: EngineeringEvaluationRevision,
        criterion_id: UUID,
        operation: str,
        actor_worker_id: int,
        actor_role: str | None,
    ) -> None:
        self.add_event(
            EngineeringEvaluationEvent(
                evaluation_id=revision.evaluation_id,
                revision_id=revision.id,
                event_type=eew.EVENT_EVALUATION_UPDATED,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                revision_version=revision.version,
                event_metadata={
                    "entity": "EngineeringEvaluationCriterion",
                    "operation": operation,
                    "criterion_id": str(criterion_id),
                },
            )
        )

    # ── Исключения: add / remove (Task 9D-2C; событие EVALUATION_UPDATED) ──────

    def get_exception(self, exception_id: UUID) -> EngineeringException | None:
        return (
            self.db.query(EngineeringException)
            .filter(EngineeringException.id == exception_id)
            .first()
        )

    def list_exceptions(self, revision_id: UUID) -> list[EngineeringException]:
        return (
            self.db.query(EngineeringException)
            .filter(EngineeringException.revision_id == revision_id)
            .order_by(EngineeringException.created_at)
            .all()
        )

    def add_exception(
        self,
        revision: EngineeringEvaluationRevision,
        *,
        criterion_id: UUID,
        basis: str,
        justification: str,
        residual_risk: str,
        conditions: str | None = None,
        required_approval_route: str | None = None,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> EngineeringException:
        """Добавляет исключение к отклонённому критерию DRAFT-ревизии.

        Критерий должен принадлежать ревизии и иметь отклонённый результат
        (`DOES_NOT_COMPLY`/`CONDITIONALLY_COMPLIES`, C15), иначе
        `EVAL_EXCEPTION_CRITERION_INVALID`. Дубль на критерий — предварительная
        проверка (C17), `UNIQUE` — страховка. Событие `EVALUATION_UPDATED` (metadata
        entity=EngineeringException, operation=ADD).
        """
        self._require_draft(revision)
        criterion = self.get_criterion(criterion_id)
        if criterion is None or criterion.revision_id != revision.id:
            raise eew.EvaluationError(
                eew.EVAL_CRITERION_NOT_FOUND, "Критерий не найден в ревизии"
            )
        if criterion.comparison_result not in eew.DEVIATED_CRITERION_RESULTS:
            raise eew.EvaluationError(
                eew.EVAL_EXCEPTION_CRITERION_INVALID,
                "Исключение допустимо только для отклонённого критерия",
            )
        existing = (
            self.db.query(EngineeringException)
            .filter(
                EngineeringException.revision_id == revision.id,
                EngineeringException.criterion_id == criterion_id,
            )
            .first()
        )
        if existing is not None:
            raise eew.EvaluationError(
                eew.EVAL_EXCEPTION_DUPLICATE,
                "Для критерия уже есть исключение",
            )
        exception = EngineeringException(
            revision_id=revision.id,
            criterion_id=criterion_id,
            basis=basis,
            justification=justification,
            residual_risk=residual_risk,
            conditions=conditions,
            required_approval_route=required_approval_route,
            created_by_worker_id=actor_worker_id,
        )
        self.db.add(exception)
        self.db.flush()
        self._exception_event(
            revision, exception.id, "ADD", actor_worker_id, actor_role
        )
        return exception

    def remove_exception(
        self,
        exception: EngineeringException,
        *,
        actor_worker_id: int,
        actor_role: str | None = None,
    ) -> None:
        """Удаляет исключение из DRAFT-ревизии. Событие `EVALUATION_UPDATED` (REMOVE)."""
        revision = self.get_revision(exception.revision_id)
        assert revision is not None
        self._require_draft(revision)
        exception_id = exception.id
        self.db.delete(exception)
        self.db.flush()
        self._exception_event(
            revision, exception_id, "REMOVE", actor_worker_id, actor_role
        )

    def _exception_event(
        self,
        revision: EngineeringEvaluationRevision,
        exception_id: UUID,
        operation: str,
        actor_worker_id: int,
        actor_role: str | None,
    ) -> None:
        self.add_event(
            EngineeringEvaluationEvent(
                evaluation_id=revision.evaluation_id,
                revision_id=revision.id,
                event_type=eew.EVENT_EVALUATION_UPDATED,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                revision_version=revision.version,
                event_metadata={
                    "entity": "EngineeringException",
                    "operation": operation,
                    "exception_id": str(exception_id),
                },
            )
        )

    # ── Проверка комплектности (Task 9D-2C; read-only, C12) ────────────────────

    def validate_revision(
        self, revision: EngineeringEvaluationRevision
    ) -> eev.ValidationResult:
        """Read-only проверка готовности ревизии к PREPARED (без записи/переходов).

        Собирает критерии/исключения/источники, вычисляет свежесть неревизионных
        источников (чтение, без обновления `verified_at`) и применяет validation
        matrix. Переход статуса и запись выполняет 9D-2D, не этот метод.
        """
        criteria = self.list_criteria(revision.id)
        exceptions = self.list_exceptions(revision.id)
        sources = self.list_sources(revision.id)
        source_issues = self._source_freshness_issues(sources)
        return eev.check_prepare_completeness(
            revision,
            criteria=criteria,
            exceptions=exceptions,
            sources=sources,
            source_issues=source_issues,
        )

    def source_freshness_issues(
        self, revision: EngineeringEvaluationRevision
    ) -> list[eev.Violation]:
        """Публичная read-only сверка свежести источников ревизии (для `fix`, §7.3).

        Возвращает нарушения свежести/доступности неревизионных источников без записи
        `verified_at`. Используется командой `fix-revision`, где содержание уже
        неизменяемо, но источник мог устареть между `prepare` и `fix`.
        """
        return self._source_freshness_issues(self.list_sources(revision.id))

    def _source_freshness_issues(
        self, sources: list[EngineeringEvaluationSource]
    ) -> list[eev.Violation]:
        """Свежесть неревизионных источников (read-only): пересчёт хэша и сравнение."""
        issues: list[eev.Violation] = []
        for s in sources:
            if s.source_revision_id is not None:
                continue  # ревизионные источники здесь не хэшируются
            try:
                current_hash, _ = eeh.compute_source_hash(
                    self.db,
                    source_entity_type=s.source_entity_type,
                    source_entity_id=s.source_entity_id,
                )
            except eew.EvaluationError as exc:
                issues.append(eev.Violation(exc.code, detail=str(s.id)))
                continue
            if current_hash != s.source_hash:
                issues.append(
                    eev.Violation(eew.EVAL_SOURCE_STALE, detail=str(s.id))
                )
        return issues

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
