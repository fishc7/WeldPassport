"""Прикладной сервис ядра EngineeringEvaluation (Task 9D-2D, ADR-021).

Сервис **владеет** жизненным циклом: команды создают/переводят ревизии, проверяют
роли/scope, комплектность (§8) и свежесть источников (§7.3). Репозиторий — только
persistence и чтение; доменные правила переходов здесь.

Ключевые границы (не нарушать):

* `recommended_disposition` необязывающая — сервис **никогда** не меняет
  `QualityFinding.status`, не создаёт `Repair`/`Rework`/`Inspection`/`ProductionHold`
  и не создаёт/не заменяет `FindingDisposition` (C01/C04). В модуле нет ни одного
  вызова, изменяющего сущности вне `EngineeringEvaluation*`;
* `EvaluationError` (repo/hash/validation/доменные проверки сервиса) транслируется в
  `DomainError` с HTTP-семантикой 403/404/409/422 (`eew.http_status_for`);
* `PENDING_APPROVAL` — только контракт 9D-3: перехода В него из 9D-2 нет; `fix`
  допускается и из `PENDING_APPROVAL`;
* `expected_version` ревизии обязателен на всех дочерних изменениях (источники/
  критерии/исключения) и командах lifecycle (optimistic locking).

RBAC/scope повторяют паттерн `QualityFindingService`: контекст — Joint оценки
(evaluation → finding → joint); изменяющие действия исключают COMPANY-scope; скрытый
по scope ресурс → 404.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.projects.repository import ProjectRepo
from app.quality import engineering_evaluation_workflow as eew
from app.quality.engineering_evaluation_models import (
    EngineeringEvaluation,
    EngineeringEvaluationEvent,
    EngineeringEvaluationRevision,
)
from app.quality.engineering_evaluation_repository import (
    EngineeringEvaluationRepository,
)
from app.quality.engineering_evaluation_schemas import (
    ConfirmReviewCommand,
    CriterionAddCommand,
    CriterionRead,
    CriterionUpdateCommand,
    EvaluationRead,
    ExceptionAddCommand,
    ExceptionRead,
    FixCommand,
    PrepareCommand,
    RequestReviewConfirmationCommand,
    RevisionCreateCommand,
    RevisionDetailRead,
    RevisionRead,
    RevisionUpdateCommand,
    ReturnCommand,
    SetEffectiveCommand,
    SourceAddCommand,
    SourceRead,
    SourceReverifyCommand,
    WithdrawCommand,
)
from app.quality.quality_finding_models import QualityFinding
from app.quality.quality_finding_repository import QualityFindingRepo
from app.shared.errors import DomainError, NotFoundError, RoleDeniedError
from app.shared.permissions import JointScopeContext, worker_role_codes_for_joint

# Профиль finding, при котором допустимо создание оценки (ОГС ведёт оценку с момента
# подтверждения получения; C04 — статус finding при этом не меняется).
_FINDING_EVALUABLE_STATUSES: frozenset[str] = frozenset({"UNDER_EVALUATION"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EngineeringEvaluationService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = EngineeringEvaluationRepository(db)
        self._findings = QualityFindingRepo(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── Трансляция доменных ошибок ─────────────────────────────────────────────

    @contextmanager
    def _translate(self):
        """`EvaluationError` → `DomainError` с HTTP-семантикой (§11).

        При доменной ошибке откатывает незакоммиченные изменения сессии: команды могут
        инкрементить версию/менять статус до операции, которая затем отклоняется
        (например, сверка источников на `fix`). Откат оставляет сессию чистой (в
        проде это делает per-request сессия) и не допускает частичных мутаций."""
        try:
            yield
        except eew.EvaluationError as exc:
            self._db.rollback()
            raise DomainError(
                eew.http_status_for(exc.code), exc.code, str(exc)
            ) from exc

    # ── Resolution ─────────────────────────────────────────────────────────────

    def _require_finding(self, finding_id: UUID) -> QualityFinding:
        finding = self._findings.get_finding(finding_id)
        if finding is None:
            raise DomainError(404, eew.EVAL_FINDING_NOT_FOUND, "Finding не найден")
        return finding

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def _require_evaluation(self, evaluation_id: UUID) -> EngineeringEvaluation:
        evaluation = self._repo.get_evaluation(evaluation_id)
        if evaluation is None:
            raise DomainError(404, eew.EVAL_NOT_FOUND, "Оценка не найдена")
        return evaluation

    def _require_revision(
        self, revision_id: UUID
    ) -> EngineeringEvaluationRevision:
        revision = self._repo.get_revision(revision_id)
        if revision is None:
            raise DomainError(404, eew.EVAL_NOT_FOUND, "Ревизия не найдена")
        return revision

    def _joint_of_evaluation(self, evaluation: EngineeringEvaluation) -> Joint:
        finding = self._require_finding(evaluation.finding_id)
        return self._require_joint(finding.joint_id)

    # ── RBAC / scope (паттерн QualityFindingService) ────────────────────────────

    def _joint_scope_ctx(
        self, joint: Joint, *, include_company: bool = True
    ) -> JointScopeContext:
        revision = self._eng.get_revision(joint.current_document_revision_id)
        engineering_document_id = (
            revision.engineering_document_id if revision is not None else None
        )
        company_ids = (
            self._projects.active_company_ids(joint.project_id)
            if include_company
            else set()
        )
        return JointScopeContext(
            project_id=joint.project_id,
            line_id=joint.line_id,
            engineering_document_id=engineering_document_id,
            company_ids=frozenset(company_ids),
        )

    def _granted_roles(
        self,
        joint: Joint,
        worker_id: int,
        allowed: frozenset[str],
        *,
        include_company: bool = True,
    ) -> set[str]:
        ctx = self._joint_scope_ctx(joint, include_company=include_company)
        return set(worker_role_codes_for_joint(self._db, worker_id, allowed, ctx))

    def _require_roles(
        self,
        joint: Joint,
        worker_id: int,
        allowed: frozenset[str],
        action: str,
    ) -> str:
        # Изменяющие действия lifecycle: COMPANY-scope исключён (как в 9A §15.2).
        granted = self._granted_roles(
            joint, worker_id, allowed, include_company=False
        )
        if not granted:
            raise RoleDeniedError(
                eew.EVAL_ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(allowed)} в подходящем scope",
            )
        return sorted(granted)[0]

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        """Оценка видима, если у актора есть роль чтения, покрывающая Joint (иначе 404)."""
        if not self._granted_roles(joint, worker_id, eew.EVALUATION_READ_ROLES):
            raise DomainError(404, eew.EVAL_NOT_FOUND, "Оценка не найдена")

    # ── История ────────────────────────────────────────────────────────────────

    def _record_event(
        self,
        evaluation_id: UUID,
        revision: EngineeringEvaluationRevision | None,
        event_type: str,
        actor_worker_id: int,
        *,
        actor_role: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._repo.add_event(
            EngineeringEvaluationEvent(
                evaluation_id=evaluation_id,
                revision_id=revision.id if revision is not None else None,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                reason=reason,
                event_metadata=metadata,
                revision_version=revision.version if revision is not None else None,
            )
        )

    def _check_version(
        self, revision: EngineeringEvaluationRevision, expected: int
    ) -> None:
        if revision.version != expected:
            raise eew.EvaluationError(
                eew.EVAL_VERSION_CONFLICT,
                "Версия ревизии изменилась — перечитайте и повторите",
            )

    def _guard_child_edit(
        self,
        revision: EngineeringEvaluationRevision,
        expected_version: int,
        actor_worker_id: int,
    ) -> None:
        """Дочернее изменение допустимо только в DRAFT и при совпадении версии.

        Версия ревизии инкрементится ДО делегирования в repo, чтобы событие
        `EVALUATION_UPDATED` несло версию ПОСЛЕ команды (optimistic locking дочерних
        изменений, требование 9D-2D)."""
        if not eew.is_editable_status(revision.status):
            raise eew.EvaluationError(
                eew.EVAL_REVISION_NOT_DRAFT,
                "Дочерние изменения разрешены только в DRAFT",
            )
        self._check_version(revision, expected_version)
        revision.version += 1
        revision.updated_by_worker_id = actor_worker_id

    # ── Чтение ─────────────────────────────────────────────────────────────────

    def _assemble_detail(
        self, revision: EngineeringEvaluationRevision
    ) -> RevisionDetailRead:
        detail = RevisionDetailRead.model_validate(revision)
        detail.sources = [
            SourceRead.model_validate(s)
            for s in self._repo.list_sources(revision.id)
        ]
        detail.criteria = [
            CriterionRead.model_validate(c)
            for c in self._repo.list_criteria(revision.id)
        ]
        detail.exceptions = [
            ExceptionRead.model_validate(e)
            for e in self._repo.list_exceptions(revision.id)
        ]
        return detail

    def get_by_finding(
        self, finding_id: UUID, *, actor_worker_id: int
    ) -> EvaluationRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        evaluation = self._repo.get_by_finding(finding_id)
        if evaluation is None:
            raise DomainError(
                404, eew.EVAL_NOT_FOUND, "Оценка для finding не создана"
            )
        read = EvaluationRead.model_validate(evaluation)
        read.revisions = [
            RevisionRead.model_validate(r)
            for r in self._repo.list_revisions(evaluation.id)
        ]
        return read

    def get_revision(
        self, revision_id: UUID, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        revision = self._require_revision(revision_id)
        evaluation = self._require_evaluation(revision.evaluation_id)
        joint = self._joint_of_evaluation(evaluation)
        self._require_visible(joint, actor_worker_id)
        return self._assemble_detail(revision)

    def list_events(
        self, evaluation_id: UUID, *, actor_worker_id: int
    ) -> list[EngineeringEvaluationEvent]:
        evaluation = self._require_evaluation(evaluation_id)
        joint = self._joint_of_evaluation(evaluation)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_events(evaluation_id)

    # ── Создание оценки ──────────────────────────────────────────────────────────

    def create_evaluation(
        self, finding_id: UUID, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "create"
        )
        if finding.status not in _FINDING_EVALUABLE_STATUSES:
            raise DomainError(
                409,
                eew.EVAL_FINDING_STATE_INVALID,
                f"Оценка создаётся только для finding в статусе "
                f"{sorted(_FINDING_EVALUABLE_STATUSES)} (текущий {finding.status})",
            )
        if self._repo.get_by_finding(finding_id) is not None:
            raise DomainError(
                409, eew.EVAL_ALREADY_EXISTS, "Оценка для finding уже существует"
            )
        project = self._projects.get_project(finding.project_id)
        if project is None:
            raise NotFoundError("Проект", finding.project_id)

        with self._translate():
            try:
                _, revision = self._repo.create_evaluation(
                    project_id=finding.project_id,
                    finding_id=finding_id,
                    project_code=project.code,
                    actor_worker_id=actor_worker_id,
                    actor_role=actor_role,
                )
                self._repo.save()
            except IntegrityError as exc:
                self._db.rollback()
                raise DomainError(
                    409,
                    eew.EVAL_ALREADY_EXISTS,
                    "Нарушение целостности при создании оценки",
                ) from exc
        return self._assemble_detail(revision)

    def create_revision(
        self,
        finding_id: UUID,
        data: RevisionCreateCommand,
        *,
        actor_worker_id: int,
    ) -> RevisionDetailRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "create-revision"
        )
        evaluation = self._repo.get_by_finding(finding_id)
        if evaluation is None:
            raise DomainError(
                404, eew.EVAL_NOT_FOUND, "Оценка для finding не создана"
            )
        current = (
            self._repo.get_revision(evaluation.current_revision_id)
            if evaluation.current_revision_id is not None
            else None
        )
        # Новую ревизию нельзя создать при незакрытой (открытой) текущей (Spec §5).
        if current is not None and current.status in eew.EVALUATION_OPEN_STATUSES:
            raise DomainError(
                409,
                eew.EVAL_INVALID_TRANSITION,
                f"Есть незакрытая ревизия в статусе {current.status}; закройте её "
                "(fix/withdraw) перед созданием новой",
            )
        with self._translate():
            revision = self._repo.create_next_revision(
                evaluation,
                revision_reason=data.revision_reason.strip(),
                previous_revision_id=evaluation.current_revision_id,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    # ── Правка DRAFT-ревизии ─────────────────────────────────────────────────────

    def update_revision(
        self,
        revision_id: UUID,
        data: RevisionUpdateCommand,
        *,
        actor_worker_id: int,
    ) -> RevisionDetailRead:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "update"
        )
        fields = data.model_dump(
            exclude_unset=True, exclude={"expected_version"}
        )
        with self._translate():
            self._repo.update_revision(
                revision,
                expected_version=data.expected_version,
                actor_worker_id=actor_worker_id,
                fields=fields,
                actor_role=actor_role,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def _resolve_editable(
        self, revision_id: UUID, actor_worker_id: int
    ) -> tuple[EngineeringEvaluationRevision, EngineeringEvaluation, Joint]:
        revision = self._require_revision(revision_id)
        evaluation = self._require_evaluation(revision.evaluation_id)
        joint = self._joint_of_evaluation(evaluation)
        self._require_visible(joint, actor_worker_id)
        return revision, evaluation, joint

    # ── Источники ────────────────────────────────────────────────────────────────

    def add_source(
        self, revision_id: UUID, data: SourceAddCommand, *, actor_worker_id: int
    ) -> SourceRead:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "add-source"
        )
        with self._translate():
            self._guard_child_edit(revision, data.expected_version, actor_worker_id)
            source = self._repo.add_source(
                revision,
                source_role=data.source_role,
                source_entity_type=data.source_entity_type,
                source_entity_id=data.source_entity_id,
                source_revision_id=data.source_revision_id,
                applicability_note=data.applicability_note,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
            )
            self._repo.save()
        return SourceRead.model_validate(source)

    def remove_source(
        self,
        revision_id: UUID,
        source_id: UUID,
        expected_version: int,
        *,
        actor_worker_id: int,
    ) -> None:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "remove-source"
        )
        source = self._repo.get_source(source_id)
        if source is None or source.revision_id != revision.id:
            raise DomainError(
                404, eew.EVAL_SOURCE_NOT_FOUND, "Источник не найден в ревизии"
            )
        with self._translate():
            self._guard_child_edit(revision, expected_version, actor_worker_id)
            self._repo.remove_source(
                source, actor_worker_id=actor_worker_id, actor_role=actor_role
            )
            self._repo.save()

    def reverify_sources(
        self,
        revision_id: UUID,
        data: SourceReverifyCommand,
        *,
        actor_worker_id: int,
    ) -> RevisionDetailRead:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "reverify-sources"
        )
        with self._translate():
            self._guard_child_edit(revision, data.expected_version, actor_worker_id)
            for source in self._repo.list_sources(revision.id):
                self._repo.reverify_source(
                    source,
                    actor_worker_id=actor_worker_id,
                    actor_role=actor_role,
                )
            self._repo.save()
        return self._assemble_detail(revision)

    # ── Критерии ─────────────────────────────────────────────────────────────────

    def add_criterion(
        self, revision_id: UUID, data: CriterionAddCommand, *, actor_worker_id: int
    ) -> CriterionRead:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "add-criterion"
        )
        optional = data.model_dump(
            exclude_unset=True,
            exclude={
                "expected_version",
                "requirement_ref",
                "parameter",
                "comparison_result",
            },
        )
        with self._translate():
            self._guard_child_edit(revision, data.expected_version, actor_worker_id)
            criterion = self._repo.add_criterion(
                revision,
                requirement_ref=data.requirement_ref,
                parameter=data.parameter,
                comparison_result=data.comparison_result,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                **optional,
            )
            self._repo.save()
        return CriterionRead.model_validate(criterion)

    def update_criterion(
        self,
        revision_id: UUID,
        criterion_id: UUID,
        data: CriterionUpdateCommand,
        *,
        actor_worker_id: int,
    ) -> CriterionRead:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "update-criterion"
        )
        criterion = self._repo.get_criterion(criterion_id)
        if criterion is None or criterion.revision_id != revision.id:
            raise DomainError(
                404, eew.EVAL_CRITERION_NOT_FOUND, "Критерий не найден в ревизии"
            )
        fields = data.model_dump(
            exclude_unset=True, exclude={"expected_version"}
        )
        with self._translate():
            self._guard_child_edit(revision, data.expected_version, actor_worker_id)
            self._repo.update_criterion(
                criterion,
                actor_worker_id=actor_worker_id,
                fields=fields,
                actor_role=actor_role,
            )
            self._repo.save()
        return CriterionRead.model_validate(criterion)

    def remove_criterion(
        self,
        revision_id: UUID,
        criterion_id: UUID,
        expected_version: int,
        *,
        actor_worker_id: int,
    ) -> None:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "remove-criterion"
        )
        criterion = self._repo.get_criterion(criterion_id)
        if criterion is None or criterion.revision_id != revision.id:
            raise DomainError(
                404, eew.EVAL_CRITERION_NOT_FOUND, "Критерий не найден в ревизии"
            )
        with self._translate():
            self._guard_child_edit(revision, expected_version, actor_worker_id)
            self._repo.remove_criterion(
                criterion, actor_worker_id=actor_worker_id, actor_role=actor_role
            )
            self._repo.save()

    # ── Исключения ───────────────────────────────────────────────────────────────

    def add_exception(
        self, revision_id: UUID, data: ExceptionAddCommand, *, actor_worker_id: int
    ) -> ExceptionRead:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "add-exception"
        )
        with self._translate():
            self._guard_child_edit(revision, data.expected_version, actor_worker_id)
            exception = self._repo.add_exception(
                revision,
                criterion_id=data.criterion_id,
                basis=data.basis,
                justification=data.justification,
                residual_risk=data.residual_risk,
                conditions=data.conditions,
                required_approval_route=data.required_approval_route,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
            )
            self._repo.save()
        return ExceptionRead.model_validate(exception)

    def remove_exception(
        self,
        revision_id: UUID,
        exception_id: UUID,
        expected_version: int,
        *,
        actor_worker_id: int,
    ) -> None:
        revision, _, joint = self._resolve_editable(revision_id, actor_worker_id)
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "remove-exception"
        )
        exception = self._repo.get_exception(exception_id)
        if exception is None or exception.revision_id != revision.id:
            raise DomainError(
                404, eew.EVAL_EXCEPTION_NOT_FOUND, "Исключение не найдено в ревизии"
            )
        with self._translate():
            self._guard_child_edit(revision, expected_version, actor_worker_id)
            self._repo.remove_exception(
                exception, actor_worker_id=actor_worker_id, actor_role=actor_role
            )
            self._repo.save()

    # ── Lifecycle: prepare / return / fix / set-effective / withdraw ─────────────

    def prepare(
        self, revision_id: UUID, data: PrepareCommand, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_PREPARE_ROLES, "prepare"
        )
        with self._translate():
            if revision.status != eew.EVAL_DRAFT:
                raise eew.EvaluationError(
                    eew.EVAL_INVALID_TRANSITION,
                    f"prepare возможен только из DRAFT (текущий {revision.status})",
                )
            self._check_version(revision, data.expected_version)
            # Комплектность §8 + свежесть источников §7.3 (агрегированно, read-only).
            result = self._repo.validate_revision(revision)
            if not result.ok:
                raise DomainError(
                    422,
                    eew.EVAL_PREPARE_INCOMPLETE,
                    "Ревизия не прошла проверку комплектности",
                    violations=[
                        {"code": v.code, "detail": v.detail}
                        for v in result.violations
                    ],
                )
            revision.status = eew.EVAL_PREPARED
            revision.prepared_by_worker_id = actor_worker_id
            revision.prepared_at = _now()
            revision.updated_by_worker_id = actor_worker_id
            revision.version += 1
            self._record_event(
                evaluation.id,
                revision,
                "EVALUATION_PREPARED",
                actor_worker_id,
                actor_role=actor_role,
                from_status=eew.EVAL_DRAFT,
                to_status=eew.EVAL_PREPARED,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def return_revision(
        self, revision_id: UUID, data: ReturnCommand, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_FIX_ROLES, "return"
        )
        with self._translate():
            if revision.status != eew.EVAL_PREPARED:
                raise eew.EvaluationError(
                    eew.EVAL_INVALID_TRANSITION,
                    f"Возврат возможен только из PREPARED (текущий {revision.status})",
                )
            self._check_version(revision, data.expected_version)
            # Возврат НЕ создаёт новую ревизию (§6): текущая → DRAFT, пара prepared_*
            # обнуляется (симметрия CHECK), допускает повторную подготовку.
            revision.status = eew.EVAL_DRAFT
            revision.prepared_by_worker_id = None
            revision.prepared_at = None
            revision.updated_by_worker_id = actor_worker_id
            revision.version += 1
            self._record_event(
                evaluation.id,
                revision,
                "EVALUATION_RETURNED",
                actor_worker_id,
                actor_role=actor_role,
                from_status=eew.EVAL_PREPARED,
                to_status=eew.EVAL_DRAFT,
                reason=data.reason.strip(),
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def fix(
        self, revision_id: UUID, data: FixCommand, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_FIX_ROLES, "fix"
        )
        with self._translate():
            if revision.status not in eew.EVALUATION_FIXABLE_FROM:
                raise eew.EvaluationError(
                    eew.EVAL_INVALID_TRANSITION,
                    f"fix возможен только из {sorted(eew.EVALUATION_FIXABLE_FROM)} "
                    f"(текущий {revision.status})",
                )
            # Подготовка и фиксация — разными акторами (§5).
            if revision.prepared_by_worker_id == actor_worker_id:
                raise eew.EvaluationError(
                    eew.EVAL_SAME_ACTOR_PREPARE_FIX,
                    "Фиксация должна выполняться иным актором, чем подготовка",
                )
            self._check_version(revision, data.expected_version)
            # Повторная сверка источников перед фиксацией (§7.3).
            issues = self._repo.source_freshness_issues(revision)
            if issues:
                raise eew.EvaluationError(
                    issues[0].code,
                    f"Источник не прошёл сверку перед фиксацией: {issues[0].detail}",
                )
            previous_status = revision.status
            revision.status = eew.EVAL_FIXED
            revision.fixed_by_worker_id = actor_worker_id
            revision.fixed_at = _now()
            revision.updated_by_worker_id = actor_worker_id
            revision.version += 1
            self._record_event(
                evaluation.id,
                revision,
                "EVALUATION_FIXED",
                actor_worker_id,
                actor_role=actor_role,
                from_status=previous_status,
                to_status=eew.EVAL_FIXED,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def set_effective(
        self, revision_id: UUID, data: SetEffectiveCommand, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_FIX_ROLES, "set-effective"
        )
        with self._translate():
            if revision.status == eew.EVAL_EFFECTIVE:
                raise eew.EvaluationError(
                    eew.EVAL_ALREADY_EFFECTIVE, "Ревизия уже действует"
                )
            if revision.status != eew.EVAL_FIXED:
                raise eew.EvaluationError(
                    eew.EVAL_INVALID_TRANSITION,
                    f"set-effective возможен только из FIXED (текущий "
                    f"{revision.status})",
                )
            self._check_version(revision, data.expected_version)
            now = _now()
            # Замещение предыдущей действующей ревизии (инвариант 11: одна EFFECTIVE).
            prev_id = evaluation.effective_revision_id
            if prev_id is not None and prev_id != revision.id:
                previous = self._repo.get_revision(prev_id)
                if previous is not None and previous.status == eew.EVAL_EFFECTIVE:
                    previous.status = eew.EVAL_SUPERSEDED
                    previous.superseded_at = now
                    previous.updated_by_worker_id = actor_worker_id
                    previous.version += 1
                    self._record_event(
                        evaluation.id,
                        previous,
                        "EVALUATION_SUPERSEDED",
                        actor_worker_id,
                        actor_role=actor_role,
                        from_status=eew.EVAL_EFFECTIVE,
                        to_status=eew.EVAL_SUPERSEDED,
                    )
            revision.status = eew.EVAL_EFFECTIVE
            revision.effective_at = now
            revision.updated_by_worker_id = actor_worker_id
            revision.version += 1
            evaluation.effective_revision_id = revision.id
            evaluation.current_revision_id = revision.id
            evaluation.updated_by_worker_id = actor_worker_id
            evaluation.version += 1
            self._record_event(
                evaluation.id,
                revision,
                "EVALUATION_BECAME_EFFECTIVE",
                actor_worker_id,
                actor_role=actor_role,
                from_status=eew.EVAL_FIXED,
                to_status=eew.EVAL_EFFECTIVE,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def withdraw(
        self, revision_id: UUID, data: WithdrawCommand, *, actor_worker_id: int
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_WITHDRAW_ROLES, "withdraw"
        )
        with self._translate():
            if revision.status not in eew.EVALUATION_WITHDRAWABLE_FROM:
                raise eew.EvaluationError(
                    eew.EVAL_INVALID_TRANSITION,
                    f"withdraw возможен только из "
                    f"{sorted(eew.EVALUATION_WITHDRAWABLE_FROM)} (текущий "
                    f"{revision.status})",
                )
            self._check_version(revision, data.expected_version)
            previous_status = revision.status
            revision.status = eew.EVAL_WITHDRAWN
            revision.withdrawn_by_worker_id = actor_worker_id
            revision.withdrawn_at = _now()
            revision.withdrawal_reason = data.reason.strip()
            revision.updated_by_worker_id = actor_worker_id
            revision.version += 1
            self._record_event(
                evaluation.id,
                revision,
                "EVALUATION_WITHDRAWN",
                actor_worker_id,
                actor_role=actor_role,
                from_status=previous_status,
                to_status=eew.EVAL_WITHDRAWN,
                reason=revision.withdrawal_reason,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    # ── Подтверждение пересмотра (§7.8, двухролевой, без внешнего согласования) ──

    def request_review_confirmation(
        self,
        revision_id: UUID,
        data: RequestReviewConfirmationCommand,
        *,
        actor_worker_id: int,
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint,
            actor_worker_id,
            eew.EVALUATION_PREPARE_ROLES,
            "request-review-confirmation",
        )
        with self._translate():
            if (
                revision.status != eew.EVAL_EFFECTIVE
                or evaluation.effective_revision_id != revision.id
            ):
                raise eew.EvaluationError(
                    eew.EVAL_INVALID_TRANSITION,
                    "Инициировать пересмотр можно только для действующей ревизии",
                )
            self._check_version(revision, data.expected_version)
            metadata: dict[str, Any] = {}
            if data.proposed_review_due_at is not None:
                metadata["proposed_review_due_at"] = (
                    data.proposed_review_due_at.isoformat()
                )
            self._record_event(
                evaluation.id,
                revision,
                "REVIEW_CONFIRMATION_REQUESTED",
                actor_worker_id,
                actor_role=actor_role,
                metadata=metadata or None,
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def confirm_review(
        self,
        revision_id: UUID,
        data: ConfirmReviewCommand,
        *,
        actor_worker_id: int,
    ) -> RevisionDetailRead:
        revision, evaluation, joint = self._resolve_editable(
            revision_id, actor_worker_id
        )
        actor_role = self._require_roles(
            joint, actor_worker_id, eew.EVALUATION_FIX_ROLES, "confirm-review"
        )
        with self._translate():
            if (
                revision.status != eew.EVAL_EFFECTIVE
                or evaluation.effective_revision_id != revision.id
            ):
                raise eew.EvaluationError(
                    eew.EVAL_REVIEW_CONTENT_CHANGED,
                    "Действующее содержание изменилось — требуется новая ревизия",
                )
            self._check_version(revision, data.expected_version)
            requester = self._pending_review_requester(evaluation.id, revision.id)
            if requester is None:
                raise eew.EvaluationError(
                    eew.EVAL_REVIEW_NOT_REQUESTED,
                    "Нет ожидающего запроса на подтверждение пересмотра",
                )
            if requester == actor_worker_id:
                raise eew.EvaluationError(
                    eew.EVAL_SAME_ACTOR_REVIEW,
                    "Подтверждение должно выполняться иным актором, чем инициатор",
                )
            # Единственная допустимая правка EFFECTIVE-ревизии (§7.8): срок пересмотра.
            revision.review_due_at = data.review_due_at
            revision.updated_by_worker_id = actor_worker_id
            revision.version += 1
            self._record_event(
                evaluation.id,
                revision,
                "REVIEW_CONFIRMED",
                actor_worker_id,
                actor_role=actor_role,
                metadata={"review_due_at": data.review_due_at.isoformat()},
            )
            self._repo.save()
        return self._assemble_detail(revision)

    def _pending_review_requester(
        self, evaluation_id: UUID, revision_id: UUID
    ) -> int | None:
        """Актор последнего REVIEW_CONFIRMATION_REQUESTED без последующего REVIEW_CONFIRMED."""
        requester: int | None = None
        for event in self._repo.list_events(evaluation_id):
            if event.revision_id != revision_id:
                continue
            if event.event_type == "REVIEW_CONFIRMATION_REQUESTED":
                requester = event.actor_worker_id
            elif event.event_type == "REVIEW_CONFIRMED":
                requester = None
        return requester
