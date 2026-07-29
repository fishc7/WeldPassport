from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.hr.models import WorkerRole
from app.projects.repository import ProjectRepo
from app.quality import inspection_workflow as iw
from app.quality.inspection_readiness import evaluate_readiness
from app.quality.models import Inspection, InspectionEvent
from app.quality.repository import QualityRepo, VisibilityScope
from app.quality.schemas import (
    CancelInspectionCommand,
    ConfirmProductionReadinessCommand,
    InspectionCreate,
    InspectionListFilters,
    InspectionListResponse,
    InspectionRead,
    InspectionReadinessRead,
    InspectionUpdate,
    RequestInspectionCommand,
)
from app.shared.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    RoleDeniedError,
    ValidationError,
    VersionConflictError,
)
from app.shared.permissions import (
    JointScopeContext,
    current_check_date,
    is_role_effective_on,
    normalize_uuid,
    worker_role_codes_for_joint,
)

# Значимые поля запроса для сравнения при идемпотентном повторе (§11).
_IDEMPOTENCY_SIGNIFICANT_FIELDS = (
    "project_id",
    "joint_id",
    "external_request_no",
    "request_reason",
    "notes",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional(value: str | None) -> str | None:
    """Пустая строка → NULL (§7.5): пустые значения не участвуют в уникальности."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class InspectionService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = QualityRepo(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── контекст scope и права (§15, переиспользуем permissions framework) ─────

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def _require_inspection(self, inspection_id: UUID) -> Inspection:
        inspection = self._repo.get_inspection(inspection_id)
        if inspection is None:
            raise DomainError(
                404, iw.INSPECTION_NOT_FOUND, "Заявка на контроль не найдена"
            )
        return inspection

    def _joint_scope_ctx(
        self, joint: Joint, *, include_company: bool = True
    ) -> JointScopeContext:
        revision = self._eng.get_revision(joint.current_document_revision_id)
        engineering_document_id = (
            revision.engineering_document_id if revision is not None else None
        )
        # Task 9A: COMPANY-scope НЕ даёт права на изменяющие действия lifecycle
        # (§15.2 — для действий канон scope = GLOBAL/PROJECT/LINE/
        # ENGINEERING_DOCUMENT). Для чтения/видимости COMPANY сохраняется.
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
        # Изменяющие действия lifecycle: COMPANY-scope исключён (§15.2).
        granted = self._granted_roles(
            joint, worker_id, allowed, include_company=False
        )
        if not granted:
            raise RoleDeniedError(
                iw.INSPECTION_ROLE_DENIED,
                f"Недостаточно прав для действия '{action}': требуется одна из "
                f"ролей {sorted(allowed)} в подходящем scope",
            )
        return granted

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        """Заявка видима, если у актора есть роль чтения, покрывающая Joint (§15.4).

        Скрытый по scope ресурс → 404 (§15.7), а не 403."""
        if not self._granted_roles(joint, worker_id, iw.INSPECTION_READ_ROLES):
            raise DomainError(
                404, iw.INSPECTION_NOT_FOUND, "Заявка на контроль не найдена"
            )

    def _visibility_scope(self, worker_id: int) -> VisibilityScope:
        """Строит область видимости для SQL-фильтрации списка (§15.6).

        Собирает id-множества из собственных ролей чтения актора (несколько ролей
        объединяются по OR). Это не «загрузка всех заявок»: фильтрация строк идёт
        SQL-предикатом по project/line/document/company."""
        on_date = current_check_date()
        roles = (
            self._db.query(WorkerRole)
            .filter(
                WorkerRole.worker_id == worker_id,
                WorkerRole.is_active.is_(True),
                WorkerRole.role_code.in_(tuple(iw.INSPECTION_READ_ROLES)),
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
            # SITE и прочие уровни без физической связи не резолвятся (как в
            # permissions.role_covers_joint) — игнорируем.
        return scope

    # ── история (§9, append-only, одна транзакция с изменением) ────────────────

    def _record_event(
        self,
        inspection: Inspection,
        event_type: str,
        *,
        actor_worker_id: int,
        from_status: str | None,
        to_status: str | None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._repo.add_event(
            InspectionEvent(
                inspection_id=inspection.id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_worker_id=actor_worker_id,
                reason=reason,
                event_metadata=metadata,
                inspection_version=inspection.version,
            )
        )

    @staticmethod
    def _check_version(inspection: Inspection, expected: int) -> None:
        if expected != inspection.version:
            raise VersionConflictError(
                iw.INSPECTION_VERSION_CONFLICT,
                expected_version=expected,
                current_version=inspection.version,
            )

    # ── чтение ─────────────────────────────────────────────────────────────────

    def get_inspection(
        self, inspection_id: UUID, *, actor_worker_id: int
    ) -> InspectionRead:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        return InspectionRead.model_validate(inspection)

    def list_inspections(
        self, filters: InspectionListFilters, *, actor_worker_id: int
    ) -> InspectionListResponse:
        scope = self._visibility_scope(actor_worker_id)
        total = self._repo.count_inspections(filters, scope)
        items = self._repo.list_inspections(filters, scope)
        return InspectionListResponse(
            items=[InspectionRead.model_validate(i) for i in items],
            total=total,
            limit=filters.limit,
            offset=filters.offset,
        )

    def list_events(self, inspection_id: UUID, *, actor_worker_id: int):
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_events(inspection_id)

    def readiness(
        self, joint_id: UUID, *, actor_worker_id: int
    ) -> InspectionReadinessRead:
        joint = self._require_joint(joint_id)
        # Readiness доступен ролям §15.5 (NDT_SPECIALIST — нет). Право на действие
        # чтения readiness: 403 при отсутствии подходящей роли.
        granted = self._granted_roles(joint, actor_worker_id, iw.READINESS_READ_ROLES)
        if not granted:
            raise RoleDeniedError(
                iw.INSPECTION_ROLE_DENIED,
                "Недостаточно прав для чтения readiness стыка",
            )
        return evaluate_readiness(self._db, joint)

    # ── создание (§10.1, §11, §12) ─────────────────────────────────────────────

    def create_inspection(
        self,
        data: InspectionCreate,
        *,
        actor_worker_id: int,
        idempotency_key: str | None,
    ) -> InspectionRead:
        external_request_no = _normalize_optional(data.external_request_no)
        idem_key = _normalize_optional(idempotency_key)

        joint = self._require_joint(data.joint_id)
        # Inspection.project_id обязан совпадать с Joint.project_id (§7.2).
        if data.project_id != joint.project_id:
            raise DomainError(
                422,
                iw.INSPECTION_PROJECT_MISMATCH,
                "project_id заявки не совпадает с project_id стыка",
            )
        project = self._projects.get_project(joint.project_id)
        if project is None:
            raise NotFoundError("Проект", joint.project_id)

        self._require_roles(
            joint, actor_worker_id, iw.INSPECTION_LIFECYCLE_ROLES, "create"
        )

        # Идемпотентность (§11): повтор того же автора с тем же ключом.
        if idem_key is not None:
            existing = self._repo.find_by_idempotency(
                created_by_worker_id=actor_worker_id, idempotency_key=idem_key
            )
            if existing is not None:
                if self._same_significant_request(existing, data, external_request_no):
                    return self._read_with_readiness(existing, actor_worker_id)
                raise DomainError(
                    409,
                    iw.INSPECTION_IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key уже использован с другим телом запроса",
                )

        # Готовность к контролю (§12.3): блокирующие причины запрещают создание.
        readiness = evaluate_readiness(
            self._db, joint, production_ready_confirmed=False
        )
        if readiness.blocking_reasons:
            raise DomainError(
                409,
                iw.INSPECTION_NOT_READY,
                "Стык не готов к контролю",
                blocking_reasons=[r.model_dump() for r in readiness.blocking_reasons],
            )

        # Контролируемый 409 при дубле внешнего номера в проекте (§7.5, §21.4.5).
        if external_request_no is not None and self._repo.find_by_project_external_no(
            project_id=joint.project_id, external_request_no=external_request_no
        ) is not None:
            raise DomainError(
                409,
                iw.INSPECTION_DUPLICATE_EXTERNAL_NO,
                f"external_request_no '{external_request_no}' уже существует в проекте",
            )

        # Номер выдаётся ПОСЛЕ всех проверок (неуспех/rollback не занимает номер).
        sequence = self._repo.next_inspection_sequence(joint.project_id)
        system_code = f"{project.code}-INS-{sequence}"

        inspection = Inspection(
            project_id=joint.project_id,
            joint_id=joint.id,
            system_code=system_code,
            external_request_no=external_request_no,
            idempotency_key=idem_key,
            status="DRAFT",
            request_reason=data.request_reason,
            notes=data.notes,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        try:
            self._repo.add_inspection(inspection)
            self._record_event(
                inspection,
                iw.EVENT_CREATED,
                actor_worker_id=actor_worker_id,
                from_status=None,
                to_status="DRAFT",
            )
            self._repo.save_inspection(inspection)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при создании заявки на контроль"
            ) from exc

        return self._read_with_readiness(inspection, actor_worker_id, readiness)

    @staticmethod
    def _same_significant_request(
        existing: Inspection,
        data: InspectionCreate,
        normalized_external_no: str | None,
    ) -> bool:
        incoming = {
            "project_id": data.project_id,
            "joint_id": data.joint_id,
            "external_request_no": normalized_external_no,
            "request_reason": data.request_reason,
            "notes": data.notes,
        }
        current = {name: getattr(existing, name) for name in _IDEMPOTENCY_SIGNIFICANT_FIELDS}
        return incoming == current

    # ── редактирование DRAFT (§10.2) ───────────────────────────────────────────

    def update_inspection(
        self, inspection_id: UUID, data: InspectionUpdate, *, actor_worker_id: int
    ) -> InspectionRead:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, iw.INSPECTION_LIFECYCLE_ROLES, "update"
        )
        if inspection.status != "DRAFT":
            raise DomainError(
                409,
                iw.INSPECTION_NOT_DRAFT,
                f"Редактирование запрещено в статусе {inspection.status} "
                "(PATCH только для DRAFT)",
            )
        self._check_version(inspection, data.expected_version)

        changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
        if "external_request_no" in changes:
            new_external = _normalize_optional(changes["external_request_no"])
            if (
                new_external is not None
                and new_external != inspection.external_request_no
                and self._repo.find_by_project_external_no(
                    project_id=inspection.project_id, external_request_no=new_external
                )
                is not None
            ):
                raise DomainError(
                    409,
                    iw.INSPECTION_DUPLICATE_EXTERNAL_NO,
                    f"external_request_no '{new_external}' уже существует в проекте",
                )
            inspection.external_request_no = new_external
        if "request_reason" in changes:
            inspection.request_reason = changes["request_reason"]
        if "notes" in changes:
            inspection.notes = changes["notes"]

        inspection.updated_by_worker_id = actor_worker_id
        inspection.version += 1
        try:
            self._record_event(
                inspection,
                iw.EVENT_UPDATED,
                actor_worker_id=actor_worker_id,
                from_status="DRAFT",
                to_status="DRAFT",
            )
            self._repo.save_inspection(inspection)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушение целостности при изменении заявки на контроль"
            ) from exc
        return InspectionRead.model_validate(inspection)

    # ── подтверждение производственной готовности СМР (§13) ────────────────────

    def confirm_production_readiness(
        self,
        inspection_id: UUID,
        data: ConfirmProductionReadinessCommand,
        *,
        actor_worker_id: int,
    ) -> InspectionRead:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, iw.PRODUCTION_READINESS_ROLES, "confirm-production-readiness"
        )
        if inspection.status != "DRAFT":
            raise DomainError(
                409,
                iw.INSPECTION_NOT_DRAFT,
                "Подтверждение производственной готовности возможно только в DRAFT",
            )
        # Идемпотентность (§13.1): если уже подтверждено — возвращаем текущее
        # состояние без второго события, без увеличения версии, не меняя автора и
        # timestamp (в т.ч. для другого пользователя).
        if inspection.production_ready_confirmed_at is not None:
            return InspectionRead.model_validate(inspection)

        self._check_version(inspection, data.expected_version)

        inspection.production_ready_confirmed_at = _now()
        inspection.production_ready_confirmed_by_worker_id = actor_worker_id
        inspection.updated_by_worker_id = actor_worker_id
        inspection.version += 1
        self._record_event(
            inspection,
            iw.EVENT_PRODUCTION_READINESS_CONFIRMED,
            actor_worker_id=actor_worker_id,
            from_status="DRAFT",
            to_status="DRAFT",
        )
        self._repo.save_inspection(inspection)
        return InspectionRead.model_validate(inspection)

    # ── отправка заявки в REQUESTED (§14) ──────────────────────────────────────

    def request_inspection(
        self,
        inspection_id: UUID,
        data: RequestInspectionCommand,
        *,
        actor_worker_id: int,
    ) -> InspectionRead:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        granted = self._require_roles(
            joint, actor_worker_id, iw.INSPECTION_REQUEST_ROLES, "request"
        )
        if inspection.status != "DRAFT":
            raise DomainError(
                409,
                iw.INSPECTION_INVALID_TRANSITION,
                f"Отправка возможна только из DRAFT (текущий статус "
                f"{inspection.status})",
            )
        self._check_version(inspection, data.expected_version)

        # Override — только у главного сварщика (§14.1). Обычный ОГС не может.
        override_reason = data.readiness_override_reason
        if override_reason is not None and not (
            granted & iw.INSPECTION_OVERRIDE_ROLES
        ):
            raise RoleDeniedError(
                iw.INSPECTION_OVERRIDE_NOT_ALLOWED,
                "Обход подтверждения СМР доступен только главному сварщику "
                "(CHIEF_WELDER)",
            )

        # Системная readiness пересчитывается заново перед переходом (§14.2).
        # Блокирующие причины запрещают переход и НЕ обходятся override.
        readiness = evaluate_readiness(
            self._db,
            joint,
            exclude_inspection_id=inspection.id,
            production_ready_confirmed=(
                inspection.production_ready_confirmed_at is not None
            ),
        )
        if readiness.blocking_reasons:
            raise DomainError(
                409,
                iw.INSPECTION_NOT_READY,
                "Стык не готов к контролю",
                blocking_reasons=[r.model_dump() for r in readiness.blocking_reasons],
            )

        use_override = False
        if inspection.production_ready_confirmed_at is None:
            if override_reason is not None:
                use_override = True
            else:
                raise DomainError(
                    409,
                    iw.INSPECTION_SMR_NOT_CONFIRMED,
                    "Требуется подтверждение производственной готовности СМР "
                    "перед отправкой заявки",
                )

        now = _now()
        inspection.status = "REQUESTED"
        inspection.requested_at = now
        inspection.requested_by_worker_id = actor_worker_id
        inspection.ogs_readiness_confirmed_at = now
        inspection.ogs_readiness_confirmed_by_worker_id = actor_worker_id
        inspection.updated_by_worker_id = actor_worker_id
        # Одна бизнес-команда увеличивает версию ровно на единицу, даже при двух
        # событиях (§21.8.15).
        inspection.version += 1

        if use_override:
            inspection.readiness_override_reason = override_reason
            self._record_event(
                inspection,
                iw.EVENT_READINESS_OVERRIDDEN,
                actor_worker_id=actor_worker_id,
                from_status="DRAFT",
                to_status="DRAFT",
                reason=override_reason,
            )
        self._record_event(
            inspection,
            iw.EVENT_REQUESTED,
            actor_worker_id=actor_worker_id,
            from_status="DRAFT",
            to_status="REQUESTED",
        )
        self._repo.save_inspection(inspection)
        return InspectionRead.model_validate(inspection)

    # ── отмена (§10.4) ─────────────────────────────────────────────────────────

    def cancel_inspection(
        self,
        inspection_id: UUID,
        data: CancelInspectionCommand,
        *,
        actor_worker_id: int,
    ) -> InspectionRead:
        inspection = self._require_inspection(inspection_id)
        joint = self._require_joint(inspection.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_roles(
            joint, actor_worker_id, iw.INSPECTION_LIFECYCLE_ROLES, "cancel"
        )
        if inspection.status == "CANCELLED":
            raise DomainError(
                409,
                iw.INSPECTION_ALREADY_CANCELLED,
                "Заявка уже отменена",
            )
        if inspection.status not in iw.INSPECTION_CANCELLABLE_STATUSES:
            raise DomainError(
                409,
                iw.INSPECTION_INVALID_TRANSITION,
                f"Отмена невозможна из статуса {inspection.status}",
            )
        self._check_version(inspection, data.expected_version)

        previous_status = inspection.status
        inspection.status = "CANCELLED"
        inspection.cancelled_at = _now()
        inspection.cancelled_by_worker_id = actor_worker_id
        inspection.cancellation_reason = data.reason.strip()
        inspection.updated_by_worker_id = actor_worker_id
        inspection.version += 1
        self._record_event(
            inspection,
            iw.EVENT_CANCELLED,
            actor_worker_id=actor_worker_id,
            from_status=previous_status,
            to_status="CANCELLED",
            reason=inspection.cancellation_reason,
        )
        self._repo.save_inspection(inspection)
        return InspectionRead.model_validate(inspection)

    # ── вспомогательное ────────────────────────────────────────────────────────

    def _read_with_readiness(
        self,
        inspection: Inspection,
        actor_worker_id: int,
        readiness: InspectionReadinessRead | None = None,
    ) -> InspectionRead:
        read = InspectionRead.model_validate(inspection)
        if readiness is None:
            joint = self._eng.get_joint(inspection.joint_id)
            if joint is not None:
                readiness = evaluate_readiness(
                    self._db,
                    joint,
                    exclude_inspection_id=inspection.id,
                    production_ready_confirmed=(
                        inspection.production_ready_confirmed_at is not None
                    ),
                )
        read.readiness = readiness
        return read


# ── Интеграция с Joint: вычисляемое inspection_state (§17, без N+1) ────────────


def inspection_states_for_joints(
    db: Session, joint_ids: Iterable[UUID]
) -> dict[UUID, str]:
    """Батч-расчёт `inspection_state` для набора Joint одним запросом (§17.3)."""
    repo = QualityRepo(db)
    statuses = repo.statuses_for_joints(joint_ids)
    return {
        joint_id: iw.inspection_state_from_statuses(codes)
        for joint_id, codes in statuses.items()
    }


def inspection_state_for_joint(db: Session, joint_id: UUID) -> str:
    """`inspection_state` одного Joint (§17)."""
    return inspection_states_for_joints(db, [joint_id]).get(joint_id, "NOT_REQUIRED")
