"""Прикладной сервис ядра QualityFinding (Task 9D-1, ADR-019).

Реализует базовый lifecycle finding как **команды** (не универсальный update, п.5
доменных правил): создание черновика, редактирование DRAFT, регистрацию (выдача
номера, фиксация наблюдения), подтверждение получения ОГС (acknowledge), отмену и
удаление DRAFT. Инженерная оценка, дефекты, disposition, holds и дочерние сущности
finding — блоки 9D-2 … 9D-6 и в этот сервис не входят.

RBAC и scope — через общий permissions-framework (как InspectionService): изменяющие
действия исключают COMPANY-scope; скрытый по scope ресурс → 404, а не 403.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.hr.models import WorkerRole
from app.projects.repository import ProjectRepo
from app.quality import quality_finding_workflow as qfw
from app.quality.quality_finding_models import (
    QualityFinding,
    QualityFindingEvent,
)
from app.quality.quality_finding_repository import QualityFindingRepo
from app.quality.quality_finding_schemas import (
    AcknowledgeFindingCommand,
    CancelFindingCommand,
    DeleteFindingCommand,
    FindingCreate,
    FindingListFilters,
    FindingListResponse,
    FindingRead,
    RegisterFindingCommand,
    FindingUpdate,
)
from app.quality.repository import VisibilityScope
from app.shared.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    RoleDeniedError,
    VersionConflictError,
)
from app.shared.permissions import (
    JointScopeContext,
    current_check_date,
    is_role_effective_on,
    normalize_uuid,
    worker_role_codes_for_joint,
)

# Контентные поля finding, которые может менять PATCH DRAFT.
_UPDATABLE_FIELDS = (
    "origin_type",
    "initial_risk",
    "title",
    "observation",
    "external_ref",
    "source_note",
)
# Поля-источники контроля, требующие joint-match при установке.
_SOURCE_FIELDS = ("inspection_id", "method_execution_id", "weld_operation_id")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional(value: str | None) -> str | None:
    """Пустая строка → NULL: пустые значения не участвуют в уникальности/CHECK."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class QualityFindingService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = QualityFindingRepo(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── контекст scope и права (переиспользуем permissions framework) ───────────

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def _require_finding(self, finding_id: UUID) -> QualityFinding:
        finding = self._repo.get_finding(finding_id)
        if finding is None:
            raise DomainError(
                404, qfw.FINDING_NOT_FOUND, "Finding не найден"
            )
        return finding

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
    ) -> set[str]:
        # Изменяющие действия lifecycle: COMPANY-scope исключён (как в 9A §15.2).
        granted = self._granted_roles(
            joint, worker_id, allowed, include_company=False
        )
        if not granted:
            raise RoleDeniedError(
                qfw.FINDING_ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(allowed)} в подходящем scope",
            )
        return granted

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        """Finding видим, если у актора есть роль чтения, покрывающая Joint.

        Скрытый по scope ресурс → 404, а не 403."""
        if not self._granted_roles(joint, worker_id, qfw.FINDING_READ_ROLES):
            raise DomainError(404, qfw.FINDING_NOT_FOUND, "Finding не найден")

    def _visibility_scope(self, worker_id: int) -> VisibilityScope:
        """Строит область видимости для SQL-фильтрации списка (как в 9A §15.6)."""
        on_date = current_check_date()
        roles = (
            self._db.query(WorkerRole)
            .filter(
                WorkerRole.worker_id == worker_id,
                WorkerRole.is_active.is_(True),
                WorkerRole.role_code.in_(tuple(qfw.FINDING_READ_ROLES)),
            )
            .all()
        )
        scope = VisibilityScope()
        for role in roles:
            if not is_role_effective_on(role, on_date):
                continue
            scope_type = role.scope_type
            if scope_type == "GLOBAL":
                scope.all_visible = True
                continue
            if scope_type == "COMPANY":
                try:
                    scope.company_ids.add(int(str(role.scope_id).strip()))
                except (ValueError, AttributeError, TypeError):
                    continue
                continue
            if scope_type in ("PROJECT", "LINE", "ENGINEERING_DOCUMENT"):
                try:
                    scope_uuid = UUID(normalize_uuid(role.scope_id))
                except (ValueError, AttributeError, TypeError):
                    continue
                if scope_type == "PROJECT":
                    scope.project_ids.add(scope_uuid)
                elif scope_type == "LINE":
                    scope.line_ids.add(scope_uuid)
                else:
                    scope.document_ids.add(scope_uuid)
        return scope

    # ── история (append-only, одна транзакция с изменением) ────────────────────

    def _record_event(
        self,
        finding: QualityFinding,
        event_type: str,
        *,
        actor_worker_id: int,
        from_status: str | None,
        to_status: str | None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._repo.add_event(
            QualityFindingEvent(
                finding_id=finding.id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_worker_id=actor_worker_id,
                reason=reason,
                event_metadata=metadata,
                finding_version=finding.version,
            )
        )

    @staticmethod
    def _check_version(finding: QualityFinding, expected: int) -> None:
        if expected != finding.version:
            raise VersionConflictError(
                qfw.FINDING_VERSION_CONFLICT,
                expected_version=expected,
                current_version=finding.version,
            )

    # ── валидация источников контроля (joint-match) ────────────────────────────

    def _validate_source(
        self, field: str, source_id: UUID | None, joint_id: UUID
    ) -> None:
        """Проверяет существование источника и совпадение его Joint с finding.

        Источник существует и относится к тому же Joint → ок; иначе 422. Все три
        поддерживаемых источника (Inspection/MethodExecution/WeldOperation) несут
        `joint_id`."""
        if source_id is None:
            return
        if field == "inspection_id":
            entity = self._repo.get_inspection(source_id)
        elif field == "method_execution_id":
            entity = self._repo.get_method_execution(source_id)
        else:
            entity = self._repo.get_weld_operation(source_id)
        if entity is None:
            raise DomainError(
                422,
                qfw.FINDING_SOURCE_NOT_FOUND,
                f"Источник контроля {field}={source_id} не найден",
            )
        if entity.joint_id != joint_id:
            raise DomainError(
                422,
                qfw.FINDING_SOURCE_JOINT_MISMATCH,
                f"Источник контроля {field}={source_id} относится к другому стыку",
            )

    # ── чтение ─────────────────────────────────────────────────────────────────

    def get_finding(self, finding_id: UUID, *, actor_worker_id: int) -> FindingRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        return FindingRead.model_validate(finding)

    def list_findings(
        self, filters: FindingListFilters, *, actor_worker_id: int
    ) -> FindingListResponse:
        scope = self._visibility_scope(actor_worker_id)
        total = self._repo.count_findings(filters, scope)
        items = self._repo.list_findings(filters, scope)
        return FindingListResponse(
            items=[FindingRead.model_validate(f) for f in items],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def list_by_joint(
        self,
        joint_id: UUID,
        filters: FindingListFilters,
        *,
        actor_worker_id: int,
    ) -> FindingListResponse:
        # Видимость проверяется по самому Joint: скрытый Joint → 404.
        joint = self._require_joint(joint_id)
        self._require_visible(joint, actor_worker_id)
        filters = filters.model_copy(update={"joint_id": joint_id})
        scope = self._visibility_scope(actor_worker_id)
        total = self._repo.count_findings(filters, scope)
        items = self._repo.list_findings(filters, scope)
        return FindingListResponse(
            items=[FindingRead.model_validate(f) for f in items],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def list_events(self, finding_id: UUID, *, actor_worker_id: int):
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_events(finding_id)

    # ── создание черновика ─────────────────────────────────────────────────────

    def create_finding(
        self, data: FindingCreate, *, actor_worker_id: int
    ) -> FindingRead:
        joint = self._require_joint(data.joint_id)
        if data.project_id != joint.project_id:
            raise DomainError(
                422,
                qfw.FINDING_PROJECT_MISMATCH,
                "project_id finding не совпадает с project_id стыка",
            )
        if self._projects.get_project(joint.project_id) is None:
            raise NotFoundError("Проект", joint.project_id)

        self._require_roles(
            joint, actor_worker_id, qfw.FINDING_REGISTER_ROLES, "create"
        )

        external_no = _normalize_optional(data.external_no)
        if external_no is not None and self._repo.find_by_project_external_no(
            project_id=joint.project_id, external_no=external_no
        ) is not None:
            raise DomainError(
                409,
                qfw.FINDING_DUPLICATE_EXTERNAL_NO,
                f"external_no '{external_no}' уже существует в проекте",
            )

        for field in _SOURCE_FIELDS:
            self._validate_source(field, getattr(data, field), joint.id)

        finding = QualityFinding(
            project_id=joint.project_id,
            joint_id=joint.id,
            system_code=None,
            external_no=external_no,
            external_ref=_normalize_optional(data.external_ref),
            origin_type=data.origin_type,
            initial_risk=data.initial_risk,
            status=qfw.FINDING_DRAFT,
            title=_normalize_optional(data.title),
            observation=data.observation.strip(),
            inspection_id=data.inspection_id,
            method_execution_id=data.method_execution_id,
            weld_operation_id=data.weld_operation_id,
            source_note=_normalize_optional(data.source_note),
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        try:
            self._repo.add_finding(finding)
            self._record_event(
                finding,
                qfw.EVENT_CREATED,
                actor_worker_id=actor_worker_id,
                from_status=None,
                to_status=qfw.FINDING_DRAFT,
            )
            self._repo.save_finding(finding)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при создании finding"
            ) from exc
        return FindingRead.model_validate(finding)

    # ── редактирование DRAFT ───────────────────────────────────────────────────

    def update_finding(
        self, finding_id: UUID, data: FindingUpdate, *, actor_worker_id: int
    ) -> FindingRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, qfw.FINDING_REGISTER_ROLES, "update"
        )
        # Наблюдение и контент неизменяемы после регистрации: PATCH только для DRAFT.
        if finding.status != qfw.FINDING_DRAFT:
            raise DomainError(
                409,
                qfw.FINDING_NOT_DRAFT,
                f"Редактирование запрещено в статусе {finding.status} "
                "(PATCH только для DRAFT)",
            )
        self._check_version(finding, data.expected_version)

        changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})

        # Внешний номер: контролируемый 409 при дубле в проекте.
        if "external_no" in changes:
            new_external = _normalize_optional(changes["external_no"])
            if (
                new_external is not None
                and new_external != finding.external_no
                and self._repo.find_by_project_external_no(
                    project_id=finding.project_id, external_no=new_external
                )
                is not None
            ):
                raise DomainError(
                    409,
                    qfw.FINDING_DUPLICATE_EXTERNAL_NO,
                    f"external_no '{new_external}' уже существует в проекте",
                )
            finding.external_no = new_external

        # Источники: валидируем joint-match при установке.
        for field in _SOURCE_FIELDS:
            if field in changes:
                self._validate_source(field, changes[field], finding.joint_id)
                setattr(finding, field, changes[field])

        for field in _UPDATABLE_FIELDS:
            if field not in changes:
                continue
            value = changes[field]
            if field == "observation":
                finding.observation = value.strip()
            elif field in ("title", "external_ref", "source_note"):
                setattr(finding, field, _normalize_optional(value))
            else:
                setattr(finding, field, value)

        finding.updated_by_worker_id = actor_worker_id
        finding.version += 1
        try:
            self._record_event(
                finding,
                qfw.EVENT_UPDATED,
                actor_worker_id=actor_worker_id,
                from_status=qfw.FINDING_DRAFT,
                to_status=qfw.FINDING_DRAFT,
            )
            self._repo.save_finding(finding)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при изменении finding"
            ) from exc
        return FindingRead.model_validate(finding)

    # ── регистрация DRAFT → REGISTERED (выдача номера) ─────────────────────────

    def register_finding(
        self,
        finding_id: UUID,
        data: RegisterFindingCommand,
        *,
        actor_worker_id: int,
    ) -> FindingRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, qfw.FINDING_REGISTER_ROLES, "register"
        )
        if finding.status != qfw.FINDING_DRAFT:
            raise DomainError(
                409,
                qfw.FINDING_INVALID_TRANSITION,
                f"Регистрация возможна только из DRAFT (текущий статус "
                f"{finding.status})",
            )
        self._check_version(finding, data.expected_version)

        project = self._projects.get_project(finding.project_id)
        if project is None:
            raise NotFoundError("Проект", finding.project_id)

        # Номер выдаётся ПОСЛЕ всех проверок (неуспех/rollback не занимает номер).
        sequence = self._repo.next_finding_sequence(finding.project_id)
        now = _now()
        finding.system_code = f"{project.code}-QF-{sequence}"
        finding.status = qfw.FINDING_REGISTERED
        finding.registered_at = now
        finding.registered_by_worker_id = actor_worker_id
        finding.updated_by_worker_id = actor_worker_id
        finding.version += 1
        try:
            self._record_event(
                finding,
                qfw.EVENT_REGISTERED,
                actor_worker_id=actor_worker_id,
                from_status=qfw.FINDING_DRAFT,
                to_status=qfw.FINDING_REGISTERED,
                metadata={"system_code": finding.system_code},
            )
            self._repo.save_finding(finding)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при регистрации finding"
            ) from exc
        return FindingRead.model_validate(finding)

    # ── подтверждение получения ОГС: REGISTERED → UNDER_EVALUATION ─────────────

    def acknowledge_finding(
        self,
        finding_id: UUID,
        data: AcknowledgeFindingCommand,
        *,
        actor_worker_id: int,
    ) -> FindingRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, qfw.FINDING_ACKNOWLEDGE_ROLES, "acknowledge"
        )
        if finding.status != qfw.FINDING_REGISTERED:
            raise DomainError(
                409,
                qfw.FINDING_NOT_REGISTERED,
                f"Подтверждение получения возможно только из REGISTERED (текущий "
                f"статус {finding.status})",
            )
        self._check_version(finding, data.expected_version)

        now = _now()
        finding.status = qfw.FINDING_UNDER_EVALUATION
        finding.acknowledged_at = now
        finding.acknowledged_by_worker_id = actor_worker_id
        finding.updated_by_worker_id = actor_worker_id
        finding.version += 1
        self._record_event(
            finding,
            qfw.EVENT_ACKNOWLEDGED,
            actor_worker_id=actor_worker_id,
            from_status=qfw.FINDING_REGISTERED,
            to_status=qfw.FINDING_UNDER_EVALUATION,
        )
        self._repo.save_finding(finding)
        return FindingRead.model_validate(finding)

    # ── отмена ─────────────────────────────────────────────────────────────────

    def cancel_finding(
        self,
        finding_id: UUID,
        data: CancelFindingCommand,
        *,
        actor_worker_id: int,
    ) -> FindingRead:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, qfw.FINDING_CANCEL_ROLES, "cancel"
        )
        if finding.status == qfw.FINDING_CANCELLED:
            raise DomainError(
                409, qfw.FINDING_ALREADY_CANCELLED, "Finding уже отменён"
            )
        if finding.status not in qfw.FINDING_CANCELLABLE_STATUSES:
            raise DomainError(
                409,
                qfw.FINDING_INVALID_TRANSITION,
                f"Отмена невозможна из статуса {finding.status}",
            )
        self._check_version(finding, data.expected_version)

        previous_status = finding.status
        finding.status = qfw.FINDING_CANCELLED
        finding.cancelled_at = _now()
        finding.cancelled_by_worker_id = actor_worker_id
        finding.cancellation_reason = data.reason.strip()
        finding.updated_by_worker_id = actor_worker_id
        finding.version += 1
        self._record_event(
            finding,
            qfw.EVENT_CANCELLED,
            actor_worker_id=actor_worker_id,
            from_status=previous_status,
            to_status=qfw.FINDING_CANCELLED,
            reason=finding.cancellation_reason,
        )
        self._repo.save_finding(finding)
        return FindingRead.model_validate(finding)

    # ── удаление DRAFT (физическое) ────────────────────────────────────────────

    def delete_finding(
        self,
        finding_id: UUID,
        data: DeleteFindingCommand,
        *,
        actor_worker_id: int,
    ) -> None:
        finding = self._require_finding(finding_id)
        joint = self._require_joint(finding.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, qfw.FINDING_REGISTER_ROLES, "delete"
        )
        # Удалять можно только DRAFT (REGISTERED физически неудаляем — только CANCELLED).
        if finding.status != qfw.FINDING_DRAFT:
            raise DomainError(
                409,
                qfw.FINDING_NOT_DRAFT,
                f"Удаление запрещено в статусе {finding.status} "
                "(физически удаляется только DRAFT)",
            )
        self._check_version(finding, data.expected_version)
        self._repo.delete_finding(finding)
