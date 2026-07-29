"""Сервисное ядро лабораторного заключения (Task 9C, блок 9C-5).

Создание LaboratoryConclusion, управление составом (связь с конкретными редакциями
MethodExecution), lifecycle DRAFT → PREPARED → LAB_APPROVED → ISSUED, отмена,
контролируемые редакции с атомарным замещением и признак пересмотра при замещении
связанного выполнения. Переиспользует паттерны Tasks 9A/9B/9C (DomainError, scope,
optimistic locking, доменный аудит). Схемы и API — вне блока; вход — service-DTO.

Прямой ввод лабораторией не расширяется: подтверждающие/выпускающие лица —
`QualityExternalPerson` (внутренняя регистрация внешнего документа, §7/§22).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.projects.repository import ProjectRepo
from app.quality import laboratory_conclusion_workflow as lcw
from app.quality import method_execution_workflow as mew
from app.quality.execution_models import (
    LaboratoryConclusion,
    LaboratoryConclusionExecution,
    MethodExecution,
)
from app.quality.execution_repository import ExecutionRepo
from app.quality.method_assignment_workflow import (
    INSPECTION_METHOD_CODES,
    NDT_LAB_ROLE_CODE,
)
from app.quality.method_execution_services import QualityAuditService
from app.quality.repository import QualityRepo
from app.shared.errors import (
    ConflictError,
    DomainError,
    RoleDeniedError,
    VersionConflictError,
)
from app.shared.permissions import JointScopeContext, worker_role_codes_for_joint


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Входные DTO (не Pydantic) ──────────────────────────────────────────────────


@dataclass
class ConclusionCreateInput:
    project_id: UUID
    laboratory_company_id: int
    inspection_method_id: str
    conclusion_number: str | None = None
    conclusion_year: int | None = None
    request_reference: str | None = None
    request_date: date | None = None
    requesting_company_id: int | None = None
    laboratory_accreditation_id: UUID | None = None
    lab_approver_person_id: UUID | None = None
    issued_by_person_id: UUID | None = None
    external_revision_label: str | None = None
    source_type: str | None = None
    source_reference: str | None = None


@dataclass
class ApproveConclusionInput:
    expected_version: int
    lab_approver_person_id: UUID | None = None


@dataclass
class IssueConclusionInput:
    expected_version: int
    conclusion_number: str | None = None
    conclusion_year: int | None = None
    issued_at: datetime | None = None
    issued_by_person_id: UUID | None = None


@dataclass
class CancelConclusionInput:
    expected_version: int
    reason: str


# ── Основной сервис заключения ─────────────────────────────────────────────────


class LaboratoryConclusionService:
    """LaboratoryConclusion: создание, состав, lifecycle, выпуск, отмена (§2–§7)."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ExecutionRepo(db)
        self._quality = QualityRepo(db)
        self._projects = ProjectRepo(db)
        self._audit = QualityAuditService(self._repo)

    # ── контекст / права (project scope, §11) ─────────────────────────────────

    @staticmethod
    def _project_ctx(project_id: UUID) -> JointScopeContext:
        # Для заключения нет линии/документа — проверяем project scope (GLOBAL/PROJECT).
        return JointScopeContext(
            project_id=project_id,
            line_id=None,
            engineering_document_id=None,
            company_ids=frozenset(),
        )

    def _granted(
        self, project_id: UUID, worker_id: int, roles: frozenset[str]
    ) -> set[str]:
        return set(
            worker_role_codes_for_joint(
                self._db, worker_id, roles, self._project_ctx(project_id)
            )
        )

    def _require_visible(self, project_id: UUID, worker_id: int) -> None:
        if not self._granted(project_id, worker_id, lcw.CONCLUSION_READ_ROLES):
            raise DomainError(
                404, lcw.CONCLUSION_NOT_FOUND, "Заключение не найдено"
            )

    def _require_write(
        self, project_id: UUID, worker_id: int, action: str
    ) -> None:
        if not self._granted(project_id, worker_id, lcw.CONCLUSION_WRITE_ROLES):
            raise RoleDeniedError(
                lcw.CONCLUSION_ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(lcw.CONCLUSION_WRITE_ROLES)} в project scope",
            )

    def _require_conclusion(self, conclusion_id: UUID) -> LaboratoryConclusion:
        conclusion = self._repo.get_conclusion(conclusion_id)
        if conclusion is None:
            raise DomainError(
                404, lcw.CONCLUSION_NOT_FOUND, "Заключение не найдено"
            )
        return conclusion

    @staticmethod
    def _check_version(conclusion: LaboratoryConclusion, expected: int) -> None:
        if expected != conclusion.version:
            raise VersionConflictError(
                lcw.CONCLUSION_VERSION_CONFLICT,
                expected_version=expected,
                current_version=conclusion.version,
            )

    def _validate_laboratory(self, project_id: UUID, company_id: int) -> None:
        company = self._projects.get_company(company_id)
        if company is None:
            raise DomainError(
                404,
                lcw.CONCLUSION_LABORATORY_NOT_FOUND,
                "Организация-лаборатория не найдена",
            )
        link = self._projects.get_active_project_company(
            project_id=project_id,
            company_id=company_id,
            role_code=NDT_LAB_ROLE_CODE,
        )
        if link is None:
            raise DomainError(
                422,
                lcw.CONCLUSION_LABORATORY_NOT_NDT_LAB,
                "Организация не является действующей лабораторией НК проекта",
            )

    def _validate_accreditation(
        self, conclusion: LaboratoryConclusion, on_date: date
    ):
        if conclusion.laboratory_accreditation_id is None:
            return None
        acc = self._repo.get_accreditation(conclusion.laboratory_accreditation_id)
        if acc is None:
            raise DomainError(
                404, lcw.ACCREDITATION_NOT_FOUND, "Аккредитация не найдена"
            )
        if acc.company_id != conclusion.laboratory_company_id:
            raise DomainError(
                422,
                lcw.ACCREDITATION_LABORATORY_MISMATCH,
                "Аккредитация принадлежит другой организации",
            )
        if not lcw.is_accreditation_valid_on(
            acc.status,
            valid_from=acc.valid_from,
            valid_until=acc.valid_until,
            on_date=on_date,
        ):
            raise DomainError(
                422,
                lcw.ACCREDITATION_INVALID,
                "Аккредитация недействительна на дату выпуска",
            )
        return acc

    def _execution_method(self, execution: MethodExecution) -> str | None:
        assignment = self._quality.get_assignment(
            execution.inspection_method_assignment_id
        )
        return assignment.method_code if assignment is not None else None

    def _require_person(self, person_id: UUID) -> None:
        if self._repo.get_external_person(person_id) is None:
            raise DomainError(
                404, mew.EXTERNAL_PERSON_NOT_FOUND, "Внешнее лицо не найдено"
            )

    # ── чтение ────────────────────────────────────────────────────────────────

    def get_conclusion(
        self, conclusion_id: UUID, *, actor_worker_id: int
    ) -> LaboratoryConclusion:
        conclusion = self._require_conclusion(conclusion_id)
        self._require_visible(conclusion.project_id, actor_worker_id)
        return conclusion

    def list_conclusions(
        self,
        *,
        project_id: UUID,
        actor_worker_id: int,
        status: str | None = None,
    ) -> list[LaboratoryConclusion]:
        self._require_visible(project_id, actor_worker_id)
        return self._repo.list_conclusions(project_id=project_id, status=status)

    def list_executions(
        self, conclusion_id: UUID, *, actor_worker_id: int
    ) -> list[LaboratoryConclusionExecution]:
        conclusion = self._require_conclusion(conclusion_id)
        self._require_visible(conclusion.project_id, actor_worker_id)
        return self._repo.list_conclusion_executions(conclusion_id)

    # ── создание (§2) ─────────────────────────────────────────────────────────

    def create_conclusion(
        self, data: ConclusionCreateInput, *, actor_worker_id: int
    ) -> LaboratoryConclusion:
        self._require_visible(data.project_id, actor_worker_id)
        self._require_write(data.project_id, actor_worker_id, "create-conclusion")
        if data.inspection_method_id not in INSPECTION_METHOD_CODES:
            raise DomainError(
                422, lcw.CONCLUSION_INVALID_METHOD, "Недопустимый метод контроля"
            )
        self._validate_laboratory(data.project_id, data.laboratory_company_id)

        conclusion_id = uuid4()
        conclusion = LaboratoryConclusion(
            id=conclusion_id,
            project_id=data.project_id,
            laboratory_company_id=data.laboratory_company_id,
            inspection_method_id=data.inspection_method_id,
            root_conclusion_id=conclusion_id,
            revision_no=1,
            is_current=True,
            status=lcw.CONCLUSION_DRAFT,
            conclusion_number=data.conclusion_number,
            normalized_conclusion_number=lcw.normalize_conclusion_number(
                data.conclusion_number
            ),
            conclusion_year=data.conclusion_year,
            request_reference=data.request_reference,
            request_date=data.request_date,
            requesting_company_id=data.requesting_company_id,
            laboratory_accreditation_id=data.laboratory_accreditation_id,
            lab_approver_person_id=data.lab_approver_person_id,
            issued_by_person_id=data.issued_by_person_id,
            external_revision_label=data.external_revision_label,
            source_type=data.source_type,
            source_reference=data.source_reference,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        self._repo.add_conclusion(conclusion)
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=conclusion.id,
            event_type=mew.AUDIT_EVENT_CONCLUSION_CREATED,
            actor_worker_id=actor_worker_id,
        )
        return self._repo.save_conclusion(conclusion)

    # ── состав (§3) ───────────────────────────────────────────────────────────

    def add_execution(
        self,
        conclusion_id: UUID,
        method_execution_id: UUID,
        *,
        actor_worker_id: int,
    ) -> LaboratoryConclusionExecution:
        conclusion = self._require_conclusion(conclusion_id)
        self._require_visible(conclusion.project_id, actor_worker_id)
        self._require_write(
            conclusion.project_id, actor_worker_id, "add-conclusion-execution"
        )
        if conclusion.status != lcw.CONCLUSION_DRAFT:
            raise DomainError(
                409,
                lcw.CONCLUSION_COMPOSITION_LOCKED,
                "Состав редактируется только в DRAFT",
            )
        execution = self._repo.get_execution(method_execution_id)
        self._check_execution_compatible(conclusion, execution)
        if execution.status == mew.EXEC_CANCELLED:
            raise DomainError(
                409,
                lcw.CONCLUSION_EXECUTION_NOT_LINKABLE,
                "Отменённое выполнение нельзя включить",
            )
        if execution.status not in lcw.CONCLUSION_LINKABLE_EXECUTION_STATUSES:
            raise DomainError(
                409,
                lcw.CONCLUSION_EXECUTION_NOT_LINKABLE,
                f"Выполнение в статусе {execution.status} нельзя включить",
            )
        if self._repo.get_conclusion_execution(conclusion_id, method_execution_id):
            raise DomainError(
                409,
                lcw.CONCLUSION_EXECUTION_DUPLICATE,
                "Выполнение уже включено в заключение",
            )
        link = LaboratoryConclusionExecution(
            laboratory_conclusion_id=conclusion.id,
            method_execution_id=execution.id,
            created_by_worker_id=actor_worker_id,
        )
        try:
            self._repo.add_conclusion_execution(link)
            self._db.flush()
        except IntegrityError as exc:
            self._db.rollback()
            raise DomainError(
                409,
                lcw.CONCLUSION_EXECUTION_DUPLICATE,
                "Выполнение уже включено в заключение",
            ) from exc
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=conclusion.id,
            event_type=mew.AUDIT_EVENT_CONCLUSION_EXECUTION_ADDED,
            actor_worker_id=actor_worker_id,
            new_values={"method_execution_id": str(execution.id)},
        )
        self._db.commit()
        self._db.refresh(link)
        return link

    def remove_execution(
        self,
        conclusion_id: UUID,
        method_execution_id: UUID,
        *,
        actor_worker_id: int,
    ) -> None:
        conclusion = self._require_conclusion(conclusion_id)
        self._require_visible(conclusion.project_id, actor_worker_id)
        self._require_write(
            conclusion.project_id, actor_worker_id, "remove-conclusion-execution"
        )
        if conclusion.status != lcw.CONCLUSION_DRAFT:
            raise DomainError(
                409,
                lcw.CONCLUSION_COMPOSITION_LOCKED,
                "Состав редактируется только в DRAFT",
            )
        link = self._repo.get_conclusion_execution(
            conclusion_id, method_execution_id
        )
        if link is None:
            raise DomainError(
                404, lcw.CONCLUSION_LINK_NOT_FOUND, "Связь не найдена"
            )
        self._repo.remove_conclusion_execution(link)
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=conclusion.id,
            event_type=mew.AUDIT_EVENT_CONCLUSION_EXECUTION_REMOVED,
            actor_worker_id=actor_worker_id,
            previous_values={"method_execution_id": str(method_execution_id)},
        )
        self._db.commit()

    def _check_execution_compatible(
        self, conclusion: LaboratoryConclusion, execution: MethodExecution | None
    ) -> None:
        if execution is None:
            raise DomainError(
                404, lcw.CONCLUSION_EXECUTION_NOT_FOUND, "Выполнение не найдено"
            )
        if execution.project_id != conclusion.project_id:
            raise DomainError(
                422,
                lcw.CONCLUSION_PROJECT_MISMATCH,
                "Выполнение относится к другому проекту",
            )
        if execution.laboratory_company_id != conclusion.laboratory_company_id:
            raise DomainError(
                422,
                lcw.CONCLUSION_LABORATORY_MISMATCH,
                "Выполнение выполнено другой лабораторией",
            )
        if self._execution_method(execution) != conclusion.inspection_method_id:
            raise DomainError(
                422,
                lcw.CONCLUSION_METHOD_MISMATCH,
                "Метод выполнения не совпадает с методом заключения",
            )

    # ── lifecycle (§4) ────────────────────────────────────────────────────────

    def prepare(
        self, conclusion_id: UUID, expected_version: int, *, actor_worker_id: int
    ) -> LaboratoryConclusion:
        conclusion = self._load_for_write(
            conclusion_id, actor_worker_id, "prepare-conclusion"
        )
        self._require_transition(conclusion, lcw.CONCLUSION_PREPARED)
        self._check_version(conclusion, expected_version)
        links = self._repo.list_conclusion_executions(conclusion.id)
        if not links:
            raise DomainError(
                409, lcw.CONCLUSION_NO_EXECUTIONS, "Нет связанных выполнений"
            )
        for link in links:
            self._check_execution_compatible(
                conclusion, self._repo.get_execution(link.method_execution_id)
            )
        self._validate_accreditation(conclusion, date.today())
        self._set_status(conclusion, lcw.CONCLUSION_PREPARED, actor_worker_id)
        return self._repo.save_conclusion(conclusion)

    def approve(
        self,
        conclusion_id: UUID,
        data: ApproveConclusionInput,
        *,
        actor_worker_id: int,
    ) -> LaboratoryConclusion:
        conclusion = self._load_for_write(
            conclusion_id, actor_worker_id, "approve-conclusion"
        )
        self._require_transition(conclusion, lcw.CONCLUSION_LAB_APPROVED)
        self._check_version(conclusion, data.expected_version)
        links = self._repo.list_conclusion_executions(conclusion.id)
        if not links:
            raise DomainError(
                409, lcw.CONCLUSION_NO_EXECUTIONS, "Нет связанных выполнений"
            )
        for link in links:
            execution = self._repo.get_execution(link.method_execution_id)
            self._check_execution_compatible(conclusion, execution)
            if execution.status != mew.EXEC_LAB_CONFIRMED:
                raise DomainError(
                    409,
                    lcw.CONCLUSION_EXECUTION_NOT_CONFIRMED,
                    "Все связанные выполнения должны быть LAB_CONFIRMED",
                )

        if data.lab_approver_person_id is not None:
            self._require_person(data.lab_approver_person_id)
            conclusion.lab_approver_person_id = data.lab_approver_person_id
        if conclusion.lab_approver_person_id is None:
            raise DomainError(
                422,
                lcw.CONCLUSION_APPROVER_REQUIRED,
                "Требуется утверждающее лицо лаборатории",
            )
        acc = self._validate_accreditation(conclusion, date.today())
        if acc is not None:
            self._fill_accreditation_snapshot(conclusion, acc)

        conclusion.lab_approved_by_worker_id = actor_worker_id
        conclusion.lab_approved_at = _now()
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=conclusion.id,
            event_type=mew.AUDIT_EVENT_CONCLUSION_APPROVED,
            actor_worker_id=actor_worker_id,
        )
        self._set_status(conclusion, lcw.CONCLUSION_LAB_APPROVED, actor_worker_id)
        return self._repo.save_conclusion(conclusion)

    def issue(
        self,
        conclusion_id: UUID,
        data: IssueConclusionInput,
        *,
        actor_worker_id: int,
    ) -> LaboratoryConclusion:
        conclusion = self._load_for_write(
            conclusion_id, actor_worker_id, "issue-conclusion"
        )
        self._require_transition(conclusion, lcw.CONCLUSION_ISSUED)
        self._check_version(conclusion, data.expected_version)

        number = (
            data.conclusion_number
            if data.conclusion_number is not None
            else conclusion.conclusion_number
        )
        if not (number or "").strip():
            raise DomainError(
                422, lcw.CONCLUSION_NUMBER_REQUIRED, "Требуется номер заключения"
            )
        normalized = lcw.normalize_conclusion_number(number)
        year = (
            data.conclusion_year
            if data.conclusion_year is not None
            else conclusion.conclusion_year
        )
        if year is None:
            raise DomainError(
                422,
                lcw.CONCLUSION_ISSUE_FIELDS_REQUIRED,
                "Требуется год заключения",
            )
        issued_at = data.issued_at or _now()
        issuer = (
            data.issued_by_person_id
            if data.issued_by_person_id is not None
            else conclusion.issued_by_person_id
        )
        if issuer is None:
            raise DomainError(
                422, lcw.CONCLUSION_ISSUER_REQUIRED, "Требуется выдавшее лицо"
            )
        self._require_person(issuer)

        conflict = self._repo.find_issued_number_conflict(
            laboratory_company_id=conclusion.laboratory_company_id,
            normalized_number=normalized,
            conclusion_year=year,
            exclude_root_id=conclusion.root_conclusion_id,
        )
        if conflict is not None:
            raise DomainError(
                409,
                lcw.CONCLUSION_DUPLICATE_NUMBER,
                "Номер заключения уже занят другим действующим заключением",
            )

        links = self._repo.list_conclusion_executions(conclusion.id)
        if not links:
            raise DomainError(
                409, lcw.CONCLUSION_NO_EXECUTIONS, "Нет связанных выполнений"
            )
        for link in links:
            self._check_execution_compatible(
                conclusion, self._repo.get_execution(link.method_execution_id)
            )

        conclusion.conclusion_number = number
        conclusion.normalized_conclusion_number = normalized
        conclusion.conclusion_year = year
        conclusion.issued_at = issued_at
        conclusion.issued_by_person_id = issuer

        # Атомарное замещение прежней редакции (§7): выполняется до установки ISSUED.
        if not conclusion.is_current:
            self._promote_conclusion(conclusion, actor_worker_id)

        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=conclusion.id,
            event_type=mew.AUDIT_EVENT_CONCLUSION_ISSUED,
            actor_worker_id=actor_worker_id,
            new_values={"conclusion_number": number, "conclusion_year": year},
        )
        self._set_status(conclusion, lcw.CONCLUSION_ISSUED, actor_worker_id)
        try:
            return self._repo.save_conclusion(conclusion)
        except IntegrityError as exc:
            self._db.rollback()
            text = str(getattr(exc, "orig", exc))
            code = (
                lcw.CONCLUSION_DUPLICATE_NUMBER
                if "uq_quality_labconc_issued_number" in text
                else lcw.CONCLUSION_REVISION_CONFLICT
            )
            raise DomainError(
                409, code, "Конфликт при выпуске заключения"
            ) from exc

    def cancel(
        self,
        conclusion_id: UUID,
        data: CancelConclusionInput,
        *,
        actor_worker_id: int,
    ) -> LaboratoryConclusion:
        conclusion = self._load_for_write(
            conclusion_id, actor_worker_id, "cancel-conclusion"
        )
        if conclusion.status not in lcw.CONCLUSION_CANCELLABLE_STATUSES:
            raise DomainError(
                409,
                lcw.CONCLUSION_INVALID_TRANSITION,
                f"Отмена недоступна в статусе {conclusion.status}",
            )
        self._check_version(conclusion, data.expected_version)
        if not (data.reason or "").strip():
            raise DomainError(
                422,
                lcw.CONCLUSION_CANCELLATION_REASON_REQUIRED,
                "Причина отмены обязательна",
            )
        conclusion.cancellation_reason = data.reason.strip()
        conclusion.cancelled_by_worker_id = actor_worker_id
        conclusion.cancelled_at = _now()
        if conclusion.revision_no > 1:
            self._audit.record(
                entity_type=mew.AUDIT_ENTITY_CONCLUSION,
                entity_id=conclusion.id,
                event_type=mew.AUDIT_EVENT_CONCLUSION_REVISION_CANCELLED,
                actor_worker_id=actor_worker_id,
                reason=conclusion.cancellation_reason,
            )
        self._set_status(conclusion, lcw.CONCLUSION_CANCELLED, actor_worker_id)
        return self._repo.save_conclusion(conclusion)

    # ── атомарное замещение (§7) ──────────────────────────────────────────────

    def _promote_conclusion(
        self, conclusion: LaboratoryConclusion, actor_worker_id: int
    ) -> None:
        sibling = self._repo.get_current_conclusion_for_root_for_update(
            conclusion.root_conclusion_id, exclude_id=conclusion.id
        )
        if sibling is not None:
            previous_status = sibling.status
            sibling.is_current = False
            if sibling.status == lcw.CONCLUSION_ISSUED:
                sibling.status = lcw.CONCLUSION_SUPERSEDED
            sibling.updated_by_worker_id = actor_worker_id
            self._db.flush()  # освободить is_current/number индексы до новой текущей
            self._audit.record(
                entity_type=mew.AUDIT_ENTITY_CONCLUSION,
                entity_id=sibling.id,
                event_type=mew.AUDIT_EVENT_CONCLUSION_SUPERSEDED,
                actor_worker_id=actor_worker_id,
                previous_values={"status": previous_status, "is_current": True},
                new_values={"status": sibling.status, "is_current": False},
            )
        conclusion.is_current = True

    def _fill_accreditation_snapshot(self, conclusion, acc) -> None:
        conclusion.accreditation_number_snapshot = acc.certificate_number
        conclusion.accreditation_valid_from_snapshot = acc.valid_from
        conclusion.accreditation_valid_until_snapshot = acc.valid_until
        conclusion.accreditation_scope_snapshot = acc.accreditation_scope
        company = self._projects.get_company(conclusion.laboratory_company_id)
        if company is not None and conclusion.laboratory_name_snapshot is None:
            conclusion.laboratory_name_snapshot = company.name

    # ── общие внутренние ──────────────────────────────────────────────────────

    def _load_for_write(
        self, conclusion_id: UUID, actor_worker_id: int, action: str
    ) -> LaboratoryConclusion:
        conclusion = self._require_conclusion(conclusion_id)
        self._require_visible(conclusion.project_id, actor_worker_id)
        self._require_write(conclusion.project_id, actor_worker_id, action)
        return conclusion

    @staticmethod
    def _require_transition(
        conclusion: LaboratoryConclusion, target: str
    ) -> None:
        if not lcw.can_transition_conclusion(conclusion.status, target):
            raise DomainError(
                409,
                lcw.CONCLUSION_INVALID_TRANSITION,
                f"Недопустимый переход {conclusion.status} → {target}",
            )

    def _set_status(
        self, conclusion: LaboratoryConclusion, target: str, actor_worker_id: int
    ) -> None:
        previous = conclusion.status
        conclusion.status = target
        conclusion.updated_by_worker_id = actor_worker_id
        conclusion.version += 1
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=conclusion.id,
            event_type=mew.AUDIT_EVENT_STATUS_CHANGED,
            actor_worker_id=actor_worker_id,
            previous_values={"status": previous},
            new_values={"status": target},
        )


# ── Сервис редакций заключения (§6) ────────────────────────────────────────────


class LaboratoryConclusionRevisionService:
    """Контролируемые редакции заключения (§6–§8).

    Новая редакция создаётся только из текущего ISSUED-заключения: копия реквизитов
    и связей на те же конкретные редакции выполнений в новую нетекущую DRAFT-запись
    того же root. Прежняя ISSUED остаётся текущей до выпуска новой; при выпуске —
    атомарное замещение (см. `LaboratoryConclusionService.issue`).
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ExecutionRepo(db)
        self._svc = LaboratoryConclusionService(db)
        self._audit = QualityAuditService(self._repo)

    def create_revision(
        self,
        conclusion_id: UUID,
        *,
        correction_reason: str,
        expected_version: int,
        conclusion_number: str | None = None,
        actor_worker_id: int,
    ) -> LaboratoryConclusion:
        old = self._svc._require_conclusion(conclusion_id)  # noqa: SLF001
        self._svc._require_visible(old.project_id, actor_worker_id)  # noqa: SLF001
        self._svc._require_write(  # noqa: SLF001
            old.project_id, actor_worker_id, "create-conclusion-revision"
        )
        if old.status != lcw.CONCLUSION_ISSUED:
            raise DomainError(
                409,
                lcw.CONCLUSION_NOT_ISSUED_FOR_REVISION,
                "Редакция создаётся только из выпущенного заключения",
            )
        if not old.is_current:
            raise DomainError(
                409,
                lcw.CONCLUSION_NOT_CURRENT_REVISION,
                "Исправляется только текущая редакция",
            )
        if not (correction_reason or "").strip():
            raise DomainError(
                422,
                lcw.CONCLUSION_CORRECTION_REASON_REQUIRED,
                "Причина исправления обязательна",
            )
        self._svc._check_version(old, expected_version)  # noqa: SLF001

        self._repo.get_current_conclusion_for_root_for_update(
            old.root_conclusion_id
        )
        if self._repo.has_open_conclusion_revision(
            old.root_conclusion_id, exclude_id=old.id
        ):
            raise DomainError(
                409,
                lcw.CONCLUSION_REVISION_IN_PROGRESS,
                "По цепочке уже есть незавершённая редакция",
            )

        new = self._clone(old, correction_reason.strip(), conclusion_number, actor_worker_id)
        self._repo.add_conclusion(new)
        for link in self._repo.list_conclusion_executions(old.id):
            self._repo.add_conclusion_execution(
                LaboratoryConclusionExecution(
                    laboratory_conclusion_id=new.id,
                    method_execution_id=link.method_execution_id,
                    created_by_worker_id=actor_worker_id,
                )
            )
        self._audit.record(
            entity_type=mew.AUDIT_ENTITY_CONCLUSION,
            entity_id=new.id,
            event_type=mew.AUDIT_EVENT_REVISION_CREATED,
            actor_worker_id=actor_worker_id,
            reason=correction_reason.strip(),
            previous_values={
                "supersedes_conclusion_id": str(old.id),
                "revision_no": old.revision_no,
            },
            new_values={"revision_no": new.revision_no},
        )
        try:
            return self._repo.save_conclusion(new)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Нарушение целостности при создании редакции") from exc

    def list_revisions(
        self, conclusion_id: UUID, *, actor_worker_id: int
    ) -> list[LaboratoryConclusion]:
        conclusion = self._svc._require_conclusion(conclusion_id)  # noqa: SLF001
        self._svc._require_visible(conclusion.project_id, actor_worker_id)  # noqa: SLF001
        return self._repo.list_conclusion_revisions(conclusion.root_conclusion_id)

    @staticmethod
    def _clone(
        old: LaboratoryConclusion,
        correction_reason: str,
        new_number: str | None,
        actor_worker_id: int,
    ) -> LaboratoryConclusion:
        new_id = uuid4()
        number = new_number if new_number is not None else old.conclusion_number
        return LaboratoryConclusion(
            id=new_id,
            project_id=old.project_id,
            laboratory_company_id=old.laboratory_company_id,
            inspection_method_id=old.inspection_method_id,
            root_conclusion_id=old.root_conclusion_id,
            revision_no=old.revision_no + 1,
            supersedes_conclusion_id=old.id,
            is_current=False,
            status=lcw.CONCLUSION_DRAFT,
            correction_reason=correction_reason,
            # Реквизиты копируются; выпуск/утверждение/отмена/review сбрасываются.
            conclusion_number=number,
            normalized_conclusion_number=lcw.normalize_conclusion_number(number),
            conclusion_year=old.conclusion_year,
            request_reference=old.request_reference,
            request_date=old.request_date,
            requesting_company_id=old.requesting_company_id,
            laboratory_accreditation_id=old.laboratory_accreditation_id,
            lab_approver_person_id=old.lab_approver_person_id,
            issued_by_person_id=old.issued_by_person_id,
            external_revision_label=old.external_revision_label,
            source_type=old.source_type,
            source_reference=old.source_reference,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
