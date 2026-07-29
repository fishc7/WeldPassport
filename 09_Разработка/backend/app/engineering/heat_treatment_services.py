"""Application-сервис термической обработки (Task 8F).

Слой Application/Domain поверх ``HeatTreatmentRepo``: команды жизненного цикла
цикла и операций, документы, отклонения, журнал и вычисление состояния требования
термообработки по Joint. Права — через существующие permission-хелперы (RBAC со
scope), новую систему разрешений не вводим (§32). Actor приходит из X-User-Id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering import heat_treatment_workflow as htw
from app.engineering import joint_workflow as jw
from app.engineering.heat_treatment_repository import HeatTreatmentRepo
from app.engineering.heat_treatment_schemas import (
    HeatTreatmentBatchCancelCommand,
    HeatTreatmentBatchCompleteCommand,
    HeatTreatmentBatchCreate,
    HeatTreatmentBatchListFilters,
    HeatTreatmentBatchListResponse,
    HeatTreatmentBatchPlanCommand,
    HeatTreatmentBatchRead,
    HeatTreatmentBatchReviewCommand,
    HeatTreatmentBatchStartCommand,
    HeatTreatmentBatchUpdate,
    HeatTreatmentBatchCloseCommand,
    HeatTreatmentDeviationCreate,
    HeatTreatmentDeviationDecisionCommand,
    HeatTreatmentJournalRow,
    HeatTreatmentJournalResponse,
    HeatTreatmentOperationCreate,
    HeatTreatmentOperationEvaluateCommand,
    HeatTreatmentOperationExcludeCommand,
    HeatTreatmentOperationUpdate,
    HeatTreatmentRecordCreate,
    JointHeatTreatmentStateRead,
    ProcedureRevisionCreate,
)
from app.engineering.models import (
    HeatTreatmentBatch,
    HeatTreatmentDeviation,
    HeatTreatmentOperation,
    HeatTreatmentProcedureRevision,
    HeatTreatmentRecord,
    Joint,
)
from app.engineering.repository import EngineeringRepo
from app.projects.repository import ProjectRepo
from app.shared.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    RoleDeniedError,
)
from app.shared.permissions import JointScopeContext, worker_role_codes_for_joint


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


class HeatTreatmentService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = HeatTreatmentRepo(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── scope / права ─────────────────────────────────────────────────────────

    def _project_scope_ctx(self, project_id: UUID) -> JointScopeContext:
        company_ids = self._projects.active_company_ids(project_id)
        return JointScopeContext(
            project_id=project_id,
            line_id=None,
            engineering_document_id=None,
            company_ids=frozenset(company_ids),
        )

    def _require_project_role(
        self,
        project_id: UUID,
        roles: frozenset[str],
        *,
        code: str,
        action: str,
    ) -> None:
        ctx = self._project_scope_ctx(project_id)
        granted = worker_role_codes_for_joint(self._db, self._actor, roles, ctx)
        if not granted:
            raise RoleDeniedError(
                code,
                f"Недостаточно прав для действия '{action}' в проекте: требуется "
                f"одна из ролей {', '.join(sorted(roles))}",
            )

    # actor фиксируется на время команды (устанавливается публичными методами).
    _actor: int = 0

    def _with_actor(self, actor_worker_id: int) -> "HeatTreatmentService":
        self._actor = actor_worker_id
        return self

    # ── общие проверки ────────────────────────────────────────────────────────

    def _require_project(self, project_id: UUID):
        project = self._projects.get_project(project_id)
        if project is None:
            raise NotFoundError("Проект", project_id)
        return project

    def _require_batch(self, batch_id: UUID) -> HeatTreatmentBatch:
        batch = self._repo.get_batch(batch_id)
        if batch is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Цикл термообработки не найден")
        return batch

    def _lock_batch(self, batch_id: UUID) -> HeatTreatmentBatch:
        batch = self._repo.get_batch_for_update(batch_id)
        if batch is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Цикл термообработки не найден")
        return batch

    def _require_operation(self, operation_id: UUID) -> HeatTreatmentOperation:
        op = self._repo.get_operation(operation_id)
        if op is None:
            raise DomainError(
                404, htw.HT_NOT_FOUND, "Операция термообработки не найдена"
            )
        return op

    @staticmethod
    def _check_batch_version(batch: HeatTreatmentBatch, expected: int | None) -> None:
        if expected is not None and expected != batch.version:
            raise DomainError(
                409,
                htw.HT_VERSION_CONFLICT,
                "Конфликт версии цикла: перечитайте и повторите",
                expected_version=expected,
                current_version=batch.version,
            )

    @staticmethod
    def _check_op_version(op: HeatTreatmentOperation, expected: int | None) -> None:
        if expected is not None and expected != op.version:
            raise DomainError(
                409,
                htw.HT_VERSION_CONFLICT,
                "Конфликт версии операции: перечитайте и повторите",
                expected_version=expected,
                current_version=op.version,
            )

    def _require_transition(self, batch: HeatTreatmentBatch, target: str) -> None:
        if not htw.batch_transition_allowed(batch.status, target):
            raise DomainError(
                409,
                htw.HT_INVALID_TRANSITION,
                f"Недопустимый переход цикла {batch.status} → {target}",
            )

    def _require_procedure_applicable(
        self, revision: HeatTreatmentProcedureRevision, batch: HeatTreatmentBatch
    ) -> None:
        """Карта утверждена, не отменена, того же проекта, применима к составу (§13)."""
        if revision.status != "APPROVED":
            raise DomainError(
                409,
                htw.HT_PROCEDURE_NOT_APPROVED,
                "Технологическая карта термообработки не утверждена",
            )
        if revision.project_id != batch.project_id:
            raise DomainError(
                422,
                htw.HT_PROCEDURE_NOT_APPLICABLE,
                "Редакция карты относится к другому проекту",
            )
        # Применимость к каждому соединению состава по ограничению линий (§13, §14).
        allowed_lines = revision.applicable_line_ids
        if allowed_lines:
            allowed = {str(x) for x in allowed_lines}
            for op in self._repo.list_operations_for_batch(batch.id):
                if op.status == "EXCLUDED":
                    continue
                joint = self._eng.get_joint(op.joint_id)
                if joint is None or str(joint.line_id) not in allowed:
                    raise DomainError(
                        422,
                        htw.HT_PROCEDURE_NOT_APPLICABLE,
                        "Карта неприменима к соединению состава (вне области "
                        "применения)",
                    )

    # ══════════════════════════════════════════════════════════════════════════
    # Технологическая карта (минимальная ссылочная сущность)
    # ══════════════════════════════════════════════════════════════════════════

    def create_procedure(
        self, data: ProcedureRevisionCreate, *, actor_worker_id: int
    ) -> HeatTreatmentProcedureRevision:
        self._with_actor(actor_worker_id)
        self._require_project(data.project_id)
        self._require_project_role(
            data.project_id,
            htw.HT_ACTOR_ROLES | htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="create-procedure",
        )
        revision = HeatTreatmentProcedureRevision(
            project_id=data.project_id,
            procedure_no=data.procedure_no,
            revision_no=data.revision_no,
            status="DRAFT",
            ht_type=data.ht_type,
            heating_method=data.heating_method,
            min_temperature=data.min_temperature,
            max_temperature=data.max_temperature,
            soak_duration_minutes=data.soak_duration_minutes,
            max_heating_rate=data.max_heating_rate,
            max_cooling_rate=data.max_cooling_rate,
            tolerances=data.tolerances,
            applicable_line_ids=(
                [str(x) for x in data.applicable_line_ids]
                if data.applicable_line_ids is not None
                else None
            ),
            created_by=actor_worker_id,
        )
        try:
            self._repo.add_procedure(revision)
            return self._repo.save_procedure(revision)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Дубликат редакции карты (project_id, procedure_no, revision_no)"
            ) from exc

    def get_procedure(self, revision_id: UUID) -> HeatTreatmentProcedureRevision:
        revision = self._repo.get_procedure(revision_id)
        if revision is None:
            raise DomainError(
                404, htw.HT_NOT_FOUND, "Редакция карты термообработки не найдена"
            )
        return revision

    def approve_procedure(
        self, revision_id: UUID, *, actor_worker_id: int
    ) -> HeatTreatmentProcedureRevision:
        self._with_actor(actor_worker_id)
        revision = self.get_procedure(revision_id)
        self._require_project_role(
            revision.project_id,
            htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="approve-procedure",
        )
        if revision.status != "DRAFT":
            raise DomainError(
                409,
                htw.HT_INVALID_TRANSITION,
                f"Редакцию нельзя утвердить из статуса {revision.status}",
            )
        revision.status = "APPROVED"
        revision.approved_by = actor_worker_id
        revision.approved_at = _now()
        return self._repo.save_procedure(revision)

    def cancel_procedure(
        self, revision_id: UUID, *, actor_worker_id: int
    ) -> HeatTreatmentProcedureRevision:
        self._with_actor(actor_worker_id)
        revision = self.get_procedure(revision_id)
        self._require_project_role(
            revision.project_id,
            htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="cancel-procedure",
        )
        if revision.status == "CANCELLED":
            raise DomainError(
                409, htw.HT_INVALID_TRANSITION, "Редакция уже отменена"
            )
        revision.status = "CANCELLED"
        return self._repo.save_procedure(revision)

    # ══════════════════════════════════════════════════════════════════════════
    # Цикл термообработки
    # ══════════════════════════════════════════════════════════════════════════

    def create_batch(
        self, data: HeatTreatmentBatchCreate, *, actor_worker_id: int
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        self._require_project(data.project_id)
        self._require_project_role(
            data.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="create-batch",
        )
        if data.procedure_revision_id is not None:
            revision = self.get_procedure(data.procedure_revision_id)
            if revision.project_id != data.project_id:
                raise DomainError(
                    422,
                    htw.HT_PROJECT_SCOPE_VIOLATION,
                    "Редакция карты относится к другому проекту",
                )
        batch = HeatTreatmentBatch(
            project_id=data.project_id,
            batch_no=data.batch_no,
            procedure_revision_id=data.procedure_revision_id,
            status="DRAFT",
            planned_start_at=data.planned_start_at,
            operator_worker_id=data.operator_worker_id,
            operator_name_text=data.operator_name_text,
            equipment_text=data.equipment_text,
            created_by=actor_worker_id,
            updated_by=actor_worker_id,
            version=1,
        )
        try:
            self._repo.add_batch(batch)
            return self._repo.save_batch(batch)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Дубликат номера цикла в проекте (project_id, batch_no)"
            ) from exc

    def get_batch(self, batch_id: UUID) -> HeatTreatmentBatch:
        return self._require_batch(batch_id)

    def list_batches(
        self, filters: HeatTreatmentBatchListFilters
    ) -> HeatTreatmentBatchListResponse:
        total = self._repo.count_batches(filters)
        items = self._repo.list_batches(filters)
        return HeatTreatmentBatchListResponse(
            items=[HeatTreatmentBatchRead.model_validate(b) for b in items],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def update_batch(
        self, batch_id: UUID, data: HeatTreatmentBatchUpdate, *, actor_worker_id: int
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="update-batch",
        )
        if batch.status in htw.BATCH_TERMINAL_STATUSES or batch.status == "REVIEWED":
            raise DomainError(
                409,
                htw.HT_BATCH_LOCKED,
                f"Цикл в статусе {batch.status}: обычное редактирование запрещено",
            )
        self._check_batch_version(batch, data.expected_version)

        changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})

        # Метаданные состава/карты меняются только до старта (§13, §14).
        pre_start_only = {
            "batch_no",
            "procedure_revision_id",
            "planned_start_at",
            "operator_worker_id",
            "operator_name_text",
            "equipment_text",
        }
        if batch.status not in htw.BATCH_COMPOSITION_EDITABLE_STATUSES:
            touched = pre_start_only & set(changes)
            if "procedure_revision_id" in touched and changes[
                "procedure_revision_id"
            ] != batch.procedure_revision_id:
                raise DomainError(
                    409,
                    htw.HT_BATCH_LOCKED,
                    "Замена карты после старта запрещена",
                )

        if (
            "procedure_revision_id" in changes
            and changes["procedure_revision_id"] is not None
        ):
            revision = self.get_procedure(changes["procedure_revision_id"])
            if revision.project_id != batch.project_id:
                raise DomainError(
                    422,
                    htw.HT_PROJECT_SCOPE_VIOLATION,
                    "Редакция карты относится к другому проекту",
                )

        for field, value in changes.items():
            setattr(batch, field, value)
        batch.updated_by = actor_worker_id
        batch.version += 1
        return self._repo.save_batch(batch)

    # ── DRAFT → PLANNED (§22) ─────────────────────────────────────────────────

    def plan_batch(
        self, batch_id: UUID, data: HeatTreatmentBatchPlanCommand, *, actor_worker_id: int
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id, htw.HT_ACTOR_ROLES, code=jw.ROLE_DENIED, action="plan"
        )
        self._require_transition(batch, "PLANNED")
        self._check_batch_version(batch, data.expected_version)

        if batch.procedure_revision_id is None:
            raise DomainError(
                422,
                htw.HT_PROCEDURE_REQUIRED,
                "Перед планированием требуется утверждённая редакция карты",
            )
        revision = self.get_procedure(batch.procedure_revision_id)
        self._require_procedure_applicable(revision, batch)

        if self._repo.count_operations_for_batch(batch.id) == 0:
            raise DomainError(
                422, htw.HT_EMPTY_COMPOSITION, "Состав цикла пуст"
            )
        if batch.operator_worker_id is None and _blank(batch.operator_name_text):
            raise DomainError(
                422,
                htw.HT_INSUFFICIENT_ACTUAL_DATA,
                "Требуется исполнитель: назначенный оператор либо текстовое имя",
            )
        if batch.planned_start_at is None:
            raise DomainError(
                422,
                htw.HT_INSUFFICIENT_ACTUAL_DATA,
                "Требуется плановое время начала",
            )

        batch.status = "PLANNED"
        batch.updated_by = actor_worker_id
        batch.version += 1
        return self._repo.save_batch(batch)

    # ── PLANNED → IN_PROGRESS (§22) ───────────────────────────────────────────

    def start_batch(
        self,
        batch_id: UUID,
        data: HeatTreatmentBatchStartCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id, htw.HT_ACTOR_ROLES, code=jw.ROLE_DENIED, action="start"
        )
        self._require_transition(batch, "IN_PROGRESS")
        self._check_batch_version(batch, data.expected_version)

        if batch.procedure_revision_id is None:
            raise DomainError(
                422,
                htw.HT_PROCEDURE_REQUIRED,
                "Перед запуском требуется утверждённая редакция карты",
            )
        revision = self.get_procedure(batch.procedure_revision_id)
        self._require_procedure_applicable(revision, batch)

        operations = self._repo.list_operations_for_batch(batch.id)
        planned = [op for op in operations if op.status == "PLANNED"]
        if not planned:
            raise DomainError(
                422,
                htw.HT_EMPTY_COMPOSITION,
                "В цикле нет операций в статусе PLANNED",
            )

        started_at = data.actual_started_at or _now()
        # Неизменяемый снимок требований карты (§5).
        batch.procedure_snapshot = self._build_snapshot(revision)
        batch.actual_started_at = started_at
        batch.status = "IN_PROGRESS"
        batch.updated_by = actor_worker_id
        batch.version += 1
        # Состав и карта блокируются; PLANNED → INCLUDED (§10, §22).
        for op in planned:
            op.status = "INCLUDED"
            op.version += 1
        return self._repo.save_batch(batch)

    @staticmethod
    def _build_snapshot(revision: HeatTreatmentProcedureRevision) -> dict:
        """Ключевые требования применённой редакции карты (§5)."""
        def _num(value):
            return str(value) if isinstance(value, Decimal) else value

        return {
            "procedure_no": revision.procedure_no,
            "revision_no": revision.revision_no,
            "ht_type": revision.ht_type,
            "heating_method": revision.heating_method,
            "min_temperature": _num(revision.min_temperature),
            "max_temperature": _num(revision.max_temperature),
            "soak_duration_minutes": revision.soak_duration_minutes,
            "max_heating_rate": _num(revision.max_heating_rate),
            "max_cooling_rate": _num(revision.max_cooling_rate),
            "tolerances": revision.tolerances,
        }

    # ── IN_PROGRESS → COMPLETED (§22) ─────────────────────────────────────────

    def complete_batch(
        self,
        batch_id: UUID,
        data: HeatTreatmentBatchCompleteCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="complete",
        )
        self._require_transition(batch, "COMPLETED")
        self._check_batch_version(batch, data.expected_version)

        completed_at = data.actual_completed_at or _now()

        # Ключевые фактические параметры обязательны для завершения (§16, §22).
        missing = [
            name
            for name in (
                "actual_soak_temperature",
                "actual_soak_duration_minutes",
                "actual_heating_rate",
                "actual_cooling_rate",
            )
            if getattr(batch, name) is None
        ]
        if missing:
            raise DomainError(
                422,
                htw.HT_INSUFFICIENT_ACTUAL_DATA,
                "Для завершения обязательны фактические параметры: "
                + ", ".join(missing),
            )
        # Хотя бы одна температурная диаграмма (минимум UPLOADED) (§18, §22).
        if not self._repo.has_uploaded_chart(batch.id):
            raise DomainError(
                422,
                htw.HT_CHART_REQUIRED,
                "Требуется загруженная температурная диаграмма",
            )

        # Каждая операция определена как PROCESSED или EXCLUDED (§22): включённые
        # операции переводятся в PROCESSED.
        operations = self._repo.list_operations_for_batch(batch.id)
        for op in operations:
            if op.status == "INCLUDED":
                op.status = "PROCESSED"
                op.version += 1

        batch.actual_completed_at = completed_at
        # Предварительная автоматическая проверка (§17).
        result, deviations = htw.evaluate_auto_check(
            batch.procedure_snapshot,
            actual_soak_temperature=batch.actual_soak_temperature,
            actual_min_temperature=batch.actual_min_temperature,
            actual_max_temperature=batch.actual_max_temperature,
            actual_soak_duration_minutes=batch.actual_soak_duration_minutes,
            actual_heating_rate=batch.actual_heating_rate,
            actual_cooling_rate=batch.actual_cooling_rate,
            has_required_document=self._repo.has_uploaded_chart(batch.id),
        )
        batch.auto_check_result = result
        batch.auto_check_details = {"deviations": deviations}
        batch.auto_check_at = _now()

        batch.status = "COMPLETED"
        batch.updated_by = actor_worker_id
        batch.version += 1
        return self._repo.save_batch(batch)

    # ── COMPLETED → REVIEWED / REJECTED (§7, §22) ─────────────────────────────

    def review_batch(
        self,
        batch_id: UUID,
        data: HeatTreatmentBatchReviewCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="review",
        )
        if batch.status != "COMPLETED":
            raise DomainError(
                409,
                htw.HT_INVALID_TRANSITION,
                f"Решение ОГС возможно только для COMPLETED (текущий {batch.status})",
            )
        self._check_batch_version(batch, data.expected_version)

        # Отклонение общего цикла: COMPLETED → REJECTED с обязательным комментарием.
        if data.result == "REJECTED":
            if _blank(data.comment):
                raise DomainError(
                    422,
                    htw.HT_JUSTIFICATION_REQUIRED,
                    "Отклонение цикла требует обязательного комментария",
                )
            batch.review_result = "REJECTED"
            batch.review_comment = data.comment
            batch.reviewed_by = actor_worker_id
            batch.reviewed_at = _now()
            batch.status = "REJECTED"
            batch.updated_by = actor_worker_id
            batch.version += 1
            return self._repo.save_batch(batch)

        # Принятие: ACCEPTED / ACCEPTED_WITH_JUSTIFICATION.
        if data.result == "ACCEPTED_WITH_JUSTIFICATION" and _blank(data.comment):
            raise DomainError(
                422,
                htw.HT_JUSTIFICATION_REQUIRED,
                "Принятие с обоснованием требует комментария",
            )
        if not self._repo.has_verified_chart(batch.id):
            raise DomainError(
                422,
                htw.HT_NO_VERIFIED_CHART,
                "Для проверки требуется проверенная (VERIFIED) диаграмма",
            )
        if batch.auto_check_result == "NOT_CHECKED":
            raise DomainError(
                422,
                htw.HT_INSUFFICIENT_ACTUAL_DATA,
                "Автоматическая проверка не выполнена",
            )
        if self._repo.has_unreviewed_critical_deviations(batch.id):
            raise DomainError(
                409,
                htw.HT_OPEN_DEVIATIONS,
                "Есть нерассмотренные критические отклонения",
            )
        # По каждой PROCESSED-операции установлен индивидуальный результат, нет PENDING.
        operations = self._repo.list_operations_for_batch(batch.id)
        processed = [op for op in operations if op.status in ("PROCESSED", "EVALUATED")]
        pending = [
            op
            for op in processed
            if op.status != "EVALUATED" or op.result == "PENDING"
        ]
        if pending:
            raise DomainError(
                422,
                htw.HT_PENDING_OPERATION_RESULTS,
                "Не по всем обработанным соединениям установлен результат",
            )

        batch.review_result = data.result
        batch.review_comment = data.comment
        batch.reviewed_by = actor_worker_id
        batch.reviewed_at = _now()
        batch.status = "REVIEWED"
        batch.updated_by = actor_worker_id
        batch.version += 1
        return self._repo.save_batch(batch)

    # ── REVIEWED → CLOSED (§22) ───────────────────────────────────────────────

    def close_batch(
        self,
        batch_id: UUID,
        data: HeatTreatmentBatchCloseCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES | htw.HT_REVIEW_ROLES,
            code=jw.ROLE_DENIED,
            action="close",
        )
        self._require_transition(batch, "CLOSED")
        self._check_batch_version(batch, data.expected_version)

        # Нет открытых значимых отклонений (§19).
        if self._repo.has_open_significant_deviations(batch.id):
            raise DomainError(
                409,
                htw.HT_OPEN_DEVIATIONS,
                "Нельзя закрыть цикл: остаются открытые значимые отклонения",
            )
        operations = self._repo.list_operations_for_batch(batch.id)
        for op in operations:
            if op.status == "PROCESSED":
                raise DomainError(
                    422,
                    htw.HT_PENDING_OPERATION_RESULTS,
                    "Не все операции оценены (есть PROCESSED без оценки)",
                )
            if op.status == "EXCLUDED" and _blank(op.exclusion_reason):
                raise DomainError(
                    422,
                    htw.HT_EXCLUDE_REASON_REQUIRED,
                    "У исключённой операции отсутствует причина",
                )

        batch.status = "CLOSED"
        batch.updated_by = actor_worker_id
        batch.version += 1
        return self._repo.save_batch(batch)

    # ── DRAFT/PLANNED → CANCELLED (§6) ────────────────────────────────────────

    def cancel_batch(
        self,
        batch_id: UUID,
        data: HeatTreatmentBatchCancelCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentBatch:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id, htw.HT_ACTOR_ROLES, code=jw.ROLE_DENIED, action="cancel"
        )
        self._require_transition(batch, "CANCELLED")
        self._check_batch_version(batch, data.expected_version)
        batch.status = "CANCELLED"
        batch.cancelled_reason = data.reason
        batch.cancelled_by = actor_worker_id
        batch.cancelled_at = _now()
        batch.updated_by = actor_worker_id
        batch.version += 1
        return self._repo.save_batch(batch)

    # ══════════════════════════════════════════════════════════════════════════
    # Операции по соединениям
    # ══════════════════════════════════════════════════════════════════════════

    def add_operation(
        self,
        batch_id: UUID,
        data: HeatTreatmentOperationCreate,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentOperation:
        self._with_actor(actor_worker_id)
        batch = self._lock_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="add-operation",
        )
        # Добавление только в DRAFT/PLANNED (§14).
        if batch.status not in htw.BATCH_COMPOSITION_EDITABLE_STATUSES:
            raise DomainError(
                409,
                htw.HT_COMPOSITION_LOCKED,
                f"Состав цикла заблокирован в статусе {batch.status}",
            )

        joint = self._eng.get_joint(data.joint_id)
        if joint is None:
            raise NotFoundError("Стык", data.joint_id)
        if joint.project_id != batch.project_id:
            raise DomainError(
                422,
                htw.HT_PROJECT_SCOPE_VIOLATION,
                "Стык относится к другому проекту, чем цикл",
            )
        if joint.status in jw.TERMINAL_STATUSES:
            raise DomainError(
                409,
                htw.HT_WELD_OPERATION_NOT_ELIGIBLE,
                f"Стык в статусе {joint.status}: включение в цикл запрещено",
            )

        if data.reason == htw.REASON_REQUIRES_PREVIOUS:
            if data.previous_heat_treatment_operation_id is None:
                raise DomainError(
                    422,
                    htw.HT_REPEAT_WITHOUT_PREVIOUS,
                    "REPEAT_AFTER_REJECTION требует ссылки на предыдущую операцию",
                )
            self._require_operation(data.previous_heat_treatment_operation_id)

        # Связь с WeldOperation, если задана (§8).
        if data.weld_operation_id is not None:
            weld_op = self._eng.get_operation(data.weld_operation_id)
            if weld_op is None:
                raise NotFoundError("Сварочная операция", data.weld_operation_id)
            if weld_op.joint_id != joint.id:
                raise DomainError(
                    422,
                    htw.HT_WELD_OPERATION_MISMATCH,
                    "WeldOperation относится к другому Joint",
                )
            if weld_op.lifecycle_status != "COMPLETED":
                raise DomainError(
                    422,
                    htw.HT_WELD_OPERATION_NOT_ELIGIBLE,
                    "WeldOperation не завершена или отменена/заменена",
                )
            if self._repo.has_accepted_result_for_weld_operation(weld_op.id):
                raise DomainError(
                    409,
                    htw.HT_WELD_OPERATION_NOT_ELIGIBLE,
                    "Для этой WeldOperation уже есть принятый результат ТО",
                )

        # Не в другом активном цикле для того же основания (§14).
        if self._repo.joint_in_active_cycle(
            joint.id, data.reason, exclude_batch_id=batch.id
        ):
            raise DomainError(
                409,
                htw.HT_DUPLICATE_JOINT,
                "Стык уже включён в другой активный цикл для того же основания",
            )

        # Применимость назначенной карты к соединению (§14).
        if batch.procedure_revision_id is not None:
            revision = self._repo.get_procedure(batch.procedure_revision_id)
            if revision is not None and revision.applicable_line_ids:
                allowed = {str(x) for x in revision.applicable_line_ids}
                if str(joint.line_id) not in allowed:
                    raise DomainError(
                        422,
                        htw.HT_PROCEDURE_NOT_APPLICABLE,
                        "Назначенная карта неприменима к соединению",
                    )

        op = HeatTreatmentOperation(
            batch_id=batch.id,
            joint_id=joint.id,
            weld_operation_id=data.weld_operation_id,
            previous_heat_treatment_operation_id=(
                data.previous_heat_treatment_operation_id
            ),
            reason=data.reason,
            status="PLANNED",
            result="PENDING",
            evidence_sufficiency="NOT_EVALUATED",
            version=1,
        )
        try:
            self._repo.add_operation(op)
            return self._repo.save_operation(op)
        except IntegrityError as exc:
            self._db.rollback()
            raise DomainError(
                409,
                htw.HT_DUPLICATE_JOINT,
                "Стык уже присутствует в этом цикле",
            ) from exc

    def get_operation(self, operation_id: UUID) -> HeatTreatmentOperation:
        return self._require_operation(operation_id)

    def list_operations(self, batch_id: UUID) -> list[HeatTreatmentOperation]:
        self._require_batch(batch_id)
        return self._repo.list_operations_for_batch(batch_id)

    def update_operation(
        self,
        operation_id: UUID,
        data: HeatTreatmentOperationUpdate,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentOperation:
        self._with_actor(actor_worker_id)
        op = self._repo.get_operation_for_update(operation_id)
        if op is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Операция не найдена")
        batch = self._require_batch(op.batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="update-operation",
        )
        if batch.status in htw.BATCH_TERMINAL_STATUSES:
            raise DomainError(
                409, htw.HT_BATCH_LOCKED, "Цикл закрыт: изменение запрещено"
            )
        if op.status == "EVALUATED":
            raise DomainError(
                409,
                htw.HT_BATCH_LOCKED,
                "Оценённую операцию редактировать нельзя",
            )
        self._check_op_version(op, data.expected_version)

        changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
        composition_fields = {
            "reason",
            "weld_operation_id",
            "previous_heat_treatment_operation_id",
        }
        if (composition_fields & set(changes)) and (
            batch.status not in htw.BATCH_COMPOSITION_EDITABLE_STATUSES
        ):
            raise DomainError(
                409,
                htw.HT_COMPOSITION_LOCKED,
                "Изменение состава после старта запрещено",
            )
        for field, value in changes.items():
            setattr(op, field, value)
        op.version += 1
        return self._repo.save_operation(op)

    def exclude_operation(
        self,
        operation_id: UUID,
        data: HeatTreatmentOperationExcludeCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentOperation:
        self._with_actor(actor_worker_id)
        op = self._repo.get_operation_for_update(operation_id)
        if op is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Операция не найдена")
        batch = self._require_batch(op.batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="exclude-operation",
        )
        self._check_op_version(op, data.expected_version)
        if op.status not in ("PLANNED", "INCLUDED"):
            raise DomainError(
                409,
                htw.HT_INVALID_TRANSITION,
                f"Нельзя исключить операцию в статусе {op.status}",
            )
        op.status = "EXCLUDED"
        op.exclusion_reason = data.reason
        op.version += 1
        return self._repo.save_operation(op)

    def evaluate_operation(
        self,
        operation_id: UUID,
        data: HeatTreatmentOperationEvaluateCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentOperation:
        self._with_actor(actor_worker_id)
        op = self._repo.get_operation_for_update(operation_id)
        if op is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Операция не найдена")
        batch = self._require_batch(op.batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="evaluate-operation",
        )
        self._check_op_version(op, data.expected_version)
        if op.status not in ("PROCESSED", "EVALUATED"):
            raise DomainError(
                409,
                htw.HT_OPERATION_NOT_PROCESSED,
                "Оценить можно только фактически обработанную операцию",
            )

        # Согласованность результата и достаточности данных (§11, §12).
        if not htw.result_allowed_for_evidence(data.evidence_sufficiency, data.result):
            raise DomainError(
                422,
                htw.HT_ACCEPT_INSUFFICIENT_EVIDENCE,
                "Результат несовместим с достаточностью подтверждающих данных",
            )
        if data.result == "ACCEPTED_WITH_JUSTIFICATION" and _blank(
            data.result_comment
        ):
            raise DomainError(
                422,
                htw.HT_JUSTIFICATION_REQUIRED,
                "ACCEPTED_WITH_JUSTIFICATION требует непустого result_comment",
            )

        op.result = data.result
        op.evidence_sufficiency = data.evidence_sufficiency
        op.result_comment = data.result_comment
        op.status = "EVALUATED"
        op.evaluated_by = actor_worker_id
        op.evaluated_at = _now()
        op.version += 1
        return self._repo.save_operation(op)

    # ══════════════════════════════════════════════════════════════════════════
    # Документы
    # ══════════════════════════════════════════════════════════════════════════

    def add_record(
        self,
        batch_id: UUID,
        data: HeatTreatmentRecordCreate,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentRecord:
        self._with_actor(actor_worker_id)
        batch = self._require_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_ACTOR_ROLES,
            code=jw.ROLE_DENIED,
            action="add-record",
        )
        if batch.status in htw.BATCH_TERMINAL_STATUSES:
            raise DomainError(
                409, htw.HT_BATCH_LOCKED, "Цикл закрыт: загрузка документов запрещена"
            )
        record = HeatTreatmentRecord(
            batch_id=batch.id,
            record_type=data.record_type,
            document_no=data.document_no,
            document_date=data.document_date,
            file_name=data.file_name,
            storage_key=data.storage_key,
            checksum=data.checksum,
            status="UPLOADED",
            uploaded_by=actor_worker_id,
        )
        self._repo.add_record(record)
        return self._repo.save_record(record)

    def list_records(self, batch_id: UUID) -> list[HeatTreatmentRecord]:
        self._require_batch(batch_id)
        return self._repo.list_records_for_batch(batch_id)

    def _record_decision(
        self, record_id: UUID, *, new_status: str, actor_worker_id: int
    ) -> HeatTreatmentRecord:
        self._with_actor(actor_worker_id)
        record = self._repo.get_record(record_id)
        if record is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Документ не найден")
        batch = self._require_batch(record.batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="verify-record",
        )
        record.status = new_status
        record.verified_by = actor_worker_id
        record.verified_at = _now()
        return self._repo.save_record(record)

    def verify_record(
        self, record_id: UUID, *, actor_worker_id: int
    ) -> HeatTreatmentRecord:
        return self._record_decision(
            record_id, new_status="VERIFIED", actor_worker_id=actor_worker_id
        )

    def reject_record(
        self, record_id: UUID, *, actor_worker_id: int
    ) -> HeatTreatmentRecord:
        return self._record_decision(
            record_id, new_status="REJECTED", actor_worker_id=actor_worker_id
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Отклонения
    # ══════════════════════════════════════════════════════════════════════════

    def add_deviation(
        self,
        batch_id: UUID,
        data: HeatTreatmentDeviationCreate,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentDeviation:
        self._with_actor(actor_worker_id)
        batch = self._require_batch(batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_DEVIATION_ROLES,
            code=jw.ROLE_DENIED,
            action="add-deviation",
        )
        if data.operation_id is not None:
            op = self._require_operation(data.operation_id)
            if op.batch_id != batch.id:
                raise DomainError(
                    422,
                    htw.HT_PROJECT_SCOPE_VIOLATION,
                    "Операция относится к другому циклу",
                )
        deviation = HeatTreatmentDeviation(
            batch_id=batch.id,
            operation_id=data.operation_id,
            deviation_type=data.deviation_type,
            description=data.description,
            planned_value=data.planned_value,
            actual_value=data.actual_value,
            severity=data.severity,
            status="OPEN",
            created_by=actor_worker_id,
        )
        self._repo.add_deviation(deviation)
        return self._repo.save_deviation(deviation)

    def list_deviations(self, batch_id: UUID) -> list[HeatTreatmentDeviation]:
        self._require_batch(batch_id)
        return self._repo.list_deviations_for_batch(batch_id)

    def decide_deviation(
        self,
        deviation_id: UUID,
        data: HeatTreatmentDeviationDecisionCommand,
        *,
        actor_worker_id: int,
    ) -> HeatTreatmentDeviation:
        self._with_actor(actor_worker_id)
        deviation = self._repo.get_deviation(deviation_id)
        if deviation is None:
            raise DomainError(404, htw.HT_NOT_FOUND, "Отклонение не найдено")
        batch = self._require_batch(deviation.batch_id)
        self._require_project_role(
            batch.project_id,
            htw.HT_REVIEW_ROLES,
            code=htw.HT_REVIEW_ROLE_DENIED,
            action="decide-deviation",
        )
        if deviation.status in ("RESOLVED", "CANCELLED"):
            raise DomainError(
                409,
                htw.HT_INVALID_TRANSITION,
                f"Отклонение уже в статусе {deviation.status}",
            )
        deviation.ogs_decision = data.ogs_decision
        deviation.decision_comment = data.decision_comment
        deviation.status = "RESOLVED"
        deviation.decided_by = actor_worker_id
        deviation.decided_at = _now()
        return self._repo.save_deviation(deviation)

    # ══════════════════════════════════════════════════════════════════════════
    # Журнал термообработки (§25)
    # ══════════════════════════════════════════════════════════════════════════

    def journal(
        self,
        *,
        project_id: UUID | None,
        line_id: UUID | None,
        joint_id: UUID | None,
        batch_no: str | None,
        result: str | None,
        performed_from,
        performed_to,
        limit: int,
        offset: int,
    ) -> HeatTreatmentJournalResponse:
        query = self._repo.journal_query(
            project_id=project_id,
            line_id=line_id,
            joint_id=joint_id,
            batch_no=batch_no,
            result=result,
            performed_from=performed_from,
            performed_to=performed_to,
        )
        total = query.count()
        rows = query.limit(limit).offset(offset).all()
        items: list[HeatTreatmentJournalRow] = []
        chart_cache: dict[UUID, str | None] = {}
        weld_cache: dict[UUID, object] = {}
        for op, batch, joint, procedure in rows:
            if batch.id not in chart_cache:
                chart_cache[batch.id] = self._repo.first_chart_document_no(batch.id)
            weld_performed_on = None
            if op.weld_operation_id is not None:
                if op.weld_operation_id not in weld_cache:
                    weld_cache[op.weld_operation_id] = self._eng.get_operation(
                        op.weld_operation_id
                    )
                weld_op = weld_cache[op.weld_operation_id]
                weld_performed_on = (
                    weld_op.performed_on if weld_op is not None else None
                )
            items.append(
                HeatTreatmentJournalRow(
                    operation_id=op.id,
                    batch_id=batch.id,
                    joint_id=joint.id,
                    joint_no=joint.joint_no,
                    line_id=joint.line_id,
                    weld_operation_id=op.weld_operation_id,
                    weld_performed_on=weld_performed_on,
                    batch_no=batch.batch_no,
                    procedure_no=procedure.procedure_no if procedure else None,
                    procedure_revision_no=procedure.revision_no if procedure else None,
                    ht_type=procedure.ht_type if procedure else None,
                    actual_started_at=(
                        op.individual_started_at or batch.actual_started_at
                    ),
                    actual_completed_at=(
                        op.individual_completed_at or batch.actual_completed_at
                    ),
                    actual_soak_temperature=batch.actual_soak_temperature,
                    actual_soak_duration_minutes=batch.actual_soak_duration_minutes,
                    chart_document_no=chart_cache[batch.id],
                    operator_worker_id=batch.operator_worker_id,
                    operator_name_text=batch.operator_name_text,
                    operation_status=op.status,
                    operation_result=op.result,
                    batch_status=batch.status,
                    batch_review_result=batch.review_result,
                )
            )
        return HeatTreatmentJournalResponse(
            items=items, total=total, limit=limit, offset=offset
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Влияние на Joint (§23, §24)
    # ══════════════════════════════════════════════════════════════════════════

    def joint_state(self, joint_id: UUID) -> JointHeatTreatmentStateRead:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        current = self._current_operation(joint)
        if current is None:
            state = htw.joint_state_from_current(
                heat_treatment_required=joint.heat_treatment_required,
                has_current_operation=False,
                batch_status=None,
                operation_status=None,
                operation_result=None,
            )
            current_op_id = None
            current_batch_id = None
        else:
            batch = self._repo.get_batch(current.batch_id)
            state = htw.joint_state_from_current(
                heat_treatment_required=joint.heat_treatment_required,
                has_current_operation=True,
                batch_status=batch.status if batch else None,
                operation_status=current.status,
                operation_result=current.result,
            )
            current_op_id = current.id
            current_batch_id = current.batch_id
        return JointHeatTreatmentStateRead(
            joint_id=joint.id,
            heat_treatment_required=joint.heat_treatment_required,
            state=state,
            dependent_steps_ready=htw.dependent_steps_ready(state),
            current_operation_id=current_op_id,
            current_batch_id=current_batch_id,
        )

    def _current_operation(self, joint: Joint) -> HeatTreatmentOperation | None:
        """Актуальная (не устаревшая по новой сварке) операция ТО для Joint (§23).

        Операция устаревает, если её связанная WeldOperation заменена/отменена, а
        также если операция не связана с актуальной завершённой WeldOperation при
        её наличии. Прежние операции остаются в истории и не удаляются."""
        operations = self._repo.list_operations_for_joint(joint.id)
        if not operations:
            return None
        current_weld = self._repo.current_completed_weld_operation(joint.id)

        candidates: list[HeatTreatmentOperation] = []
        for op in operations:
            if op.weld_operation_id is not None:
                # Привязанная операция актуальна только для актуальной WeldOperation.
                if current_weld is not None and op.weld_operation_id == current_weld.id:
                    candidates.append(op)
            else:
                # Не привязанная к WeldOperation операция считается актуальной,
                # пока не появилась новая завершённая сварка после её создания.
                if current_weld is None:
                    candidates.append(op)
                elif (
                    current_weld.completed_at is None
                    or current_weld.completed_at <= op.created_at
                ):
                    candidates.append(op)
        if not candidates:
            return None
        # Наиболее свежая по времени создания.
        return max(candidates, key=lambda o: o.created_at)
