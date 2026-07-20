"""Доменный сервис технической модели Defect (Task 9D-3B; ADR-022, Spec 9D-3).

Бизнес-действия оформлены **командами** (не универсальный update): create_draft,
create_active, update_draft, activate, supersede, cancel + чтение. RBAC/visibility —
через общий permissions-framework (как QualityFindingService): изменяющие действия
исключают COMPANY-scope; скрытый по scope ресурс → 404-эквивалентная доменная ошибка.

Происхождение (ADR-022 §2/§4, Spec §7.1): Defect регистрируется только по действующей
`EFFECTIVE` `EngineeringEvaluationRevision` с `classification = CONFIRMED_DEFECT` и
совпадением Joint. Исправление `ACTIVE` — только через supersede (новая ревизия), прямое
изменение существенных полей запрещено. Одна `EngineeringEvaluation` → одна корневая
цепочка (`DefectRoot`). `FindingDisposition` не используется.

Supersede — **двухшаговая** модель (Spec §5, вариант supersede-time). Команда
`supersede` в одной транзакции: предыдущая `ACTIVE` → `SUPERSEDED` **и** создаётся новая
`DRAFT`-ревизия (`revision_no + 1`); события `DEFECT_SUPERSEDED` + `DEFECT_REVISION_CREATED`.
После `supersede` действующей `ACTIVE` в цепочке нет (0 ACTIVE, 1 открытая `DRAFT`).
Активация новой ревизии — отдельной командой `activate` (`DRAFT → ACTIVE`, событие
`DEFECT_ACTIVATED`). Новая `DRAFT` может быть неполной (только структурная проверка);
полная §8-проверка комплектности — при `activate`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.hr.models import WorkerRole
from app.projects.repository import ProjectRepo
from app.quality import defect_workflow as dw
from app.quality import engineering_evaluation_workflow as eew
from app.quality.defect_models import Defect, DefectEvent, DefectRoot
from app.quality.defect_repository import DefectRepository
from app.quality.defect_validation import (
    normalize_field_values,
    validate_draft_structural,
    validate_for_activation,
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

CONFIRMED_DEFECT = "CONFIRMED_DEFECT"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _jsonable(value: Any) -> Any:
    """Приводит значение к JSON-совместимому виду для JSONB-метаданных события."""
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    return value


class DefectService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = DefectRepository(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── контекст scope и права (переиспользуем permissions framework) ───────────

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise NotFoundError("Стык", joint_id)
        return joint

    def _require_defect(self, defect_id: UUID) -> Defect:
        defect = self._repo.get_defect_by_id(defect_id)
        if defect is None:
            raise DomainError(404, dw.DEFECT_NOT_FOUND, "Defect не найден")
        return defect

    def _require_root(self, root_id: UUID) -> DefectRoot:
        root = self._repo.get_root_by_id(root_id)
        if root is None:
            raise DomainError(404, dw.DEFECT_ROOT_NOT_FOUND, "DefectRoot не найден")
        return root

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

    def _require_write_roles(
        self, joint: Joint, worker_id: int, action: str
    ) -> set[str]:
        # Изменяющие действия lifecycle: COMPANY-scope исключён (как в 9A §15.2).
        granted = self._granted_roles(
            joint, worker_id, dw.DEFECT_WRITE_ROLES, include_company=False
        )
        if not granted:
            raise RoleDeniedError(
                dw.DEFECT_PERMISSION_DENIED,
                f"Недостаточно прав для '{action}': требуется одна из ролей "
                f"{sorted(dw.DEFECT_WRITE_ROLES)} в подходящем scope",
            )
        return granted

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        """Скрытый по scope ресурс → 404, а не 403 (канон 9A/9D-1)."""
        if not self._granted_roles(joint, worker_id, dw.DEFECT_READ_ROLES):
            raise DomainError(404, dw.DEFECT_NOT_FOUND, "Defect не найден")

    def _visibility_scope(self, worker_id: int) -> VisibilityScope:
        on_date = current_check_date()
        roles = (
            self._db.query(WorkerRole)
            .filter(
                WorkerRole.worker_id == worker_id,
                WorkerRole.is_active.is_(True),
                WorkerRole.role_code.in_(tuple(dw.DEFECT_READ_ROLES)),
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
        defect: Defect,
        event_type: str,
        *,
        actor_worker_id: int,
        from_status: str | None,
        to_status: str | None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._repo.append_event(
            DefectEvent(
                defect_root_id=defect.defect_root_id,
                defect_id=defect.id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_worker_id=actor_worker_id,
                reason=reason,
                event_metadata=metadata,
                defect_version=defect.version,
            )
        )

    @staticmethod
    def _check_version(defect: Defect, expected: int) -> None:
        if expected != defect.version:
            raise VersionConflictError(
                dw.DEFECT_VERSION_CONFLICT,
                expected_version=expected,
                current_version=defect.version,
            )

    # ── доменные проверки происхождения ────────────────────────────────────────

    def _require_confirmed_evaluation(self, evaluation_id: UUID, joint_id: UUID):
        """Проверяет effective CONFIRMED_DEFECT-оценку и совпадение Joint (§4)."""
        evaluation = self._repo.get_evaluation(evaluation_id)
        if evaluation is None:
            raise DomainError(
                404, dw.DEFECT_EVALUATION_NOT_FOUND, "EngineeringEvaluation не найдена"
            )
        eff_id = evaluation.effective_revision_id
        if eff_id is None:
            raise DomainError(
                422,
                dw.DEFECT_EVALUATION_NOT_EFFECTIVE,
                "У оценки нет действующей (EFFECTIVE) ревизии",
            )
        revision = self._repo.get_evaluation_revision(eff_id)
        if revision is None or revision.status != eew.EVAL_EFFECTIVE:
            raise DomainError(
                422,
                dw.DEFECT_EVALUATION_NOT_EFFECTIVE,
                "Действующая ревизия оценки не в статусе EFFECTIVE",
            )
        if revision.classification != CONFIRMED_DEFECT:
            raise DomainError(
                422,
                dw.DEFECT_EVALUATION_NOT_CONFIRMED,
                "Классификация действующей оценки не CONFIRMED_DEFECT",
            )
        finding = self._repo.get_finding(evaluation.finding_id)
        if finding is None or finding.joint_id != joint_id:
            raise DomainError(
                422,
                dw.DEFECT_JOINT_MISMATCH,
                "Joint оценки не совпадает с запрошенным joint_id",
            )
        return evaluation, finding

    def _apply_fields(self, defect: Defect, fields: dict[str, Any] | None) -> None:
        clean = normalize_field_values(
            {
                k: v
                for k, v in (fields or {}).items()
                if k in dw.DEFECT_TECHNICAL_FIELDS
            }
        )
        for key, value in clean.items():
            setattr(defect, key, value)

    def _resolve_refs(self, defect: Defect):
        defect_type = None
        location_type = None
        if defect.defect_type_id is not None:
            defect_type = self._repo.get_defect_type(defect.defect_type_id)
            if defect_type is None:
                raise DomainError(
                    422, dw.DEFECT_TYPE_NOT_FOUND, "Тип дефекта не найден"
                )
        if defect.location_type_id is not None:
            location_type = self._repo.get_defect_location_type(defect.location_type_id)
            if location_type is None:
                raise DomainError(
                    422,
                    dw.DEFECT_LOCATION_TYPE_NOT_FOUND,
                    "Расположение не найдено",
                )
        return defect_type, location_type

    def _validate_active(self, defect: Defect) -> None:
        defect_type, location_type = self._resolve_refs(defect)
        violations = validate_for_activation(defect, defect_type, location_type)
        if violations:
            first_code, first_msg = violations[0]
            raise DomainError(
                422,
                first_code,
                first_msg,
                violations=[code for code, _ in violations],
            )

    def _validate_draft_structural(self, defect: Defect) -> None:
        """Только структурные (CHECK-уровня) инварианты DRAFT (Spec §3/§6)."""
        violations = validate_draft_structural(defect)
        if violations:
            first_code, first_msg = violations[0]
            raise DomainError(
                422,
                first_code,
                first_msg,
                violations=[code for code, _ in violations],
            )

    # ── чтение ─────────────────────────────────────────────────────────────────

    def get(self, defect_id: UUID, *, actor_worker_id: int) -> Defect:
        defect = self._require_defect(defect_id)
        root = self._require_root(defect.defect_root_id)
        joint = self._require_joint(root.joint_id)
        self._require_visible(joint, actor_worker_id)
        return defect

    def list_by_joint(self, joint_id: UUID, *, actor_worker_id: int) -> list[Defect]:
        joint = self._require_joint(joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_active_defects_by_joint(joint_id)

    def history(self, defect_id: UUID, *, actor_worker_id: int) -> list[DefectEvent]:
        defect = self._require_defect(defect_id)
        root = self._require_root(defect.defect_root_id)
        joint = self._require_joint(root.joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_events(root.id)

    # ── создание DRAFT ─────────────────────────────────────────────────────────

    def create_draft(
        self,
        *,
        joint_id: UUID,
        engineering_evaluation_id: UUID,
        actor_worker_id: int,
        fields: dict[str, Any] | None = None,
    ) -> Defect:
        joint = self._require_joint(joint_id)
        self._require_write_roles(joint, actor_worker_id, "create_draft")
        self._require_confirmed_evaluation(engineering_evaluation_id, joint_id)
        if (
            self._repo.get_root_by_evaluation_id(engineering_evaluation_id)
            is not None
        ):
            raise DomainError(
                409,
                dw.DEFECT_ALREADY_EXISTS_FOR_EVALUATION,
                "Для этой оценки уже существует цепочка Defect",
            )
        return self._create(
            joint_id=joint_id,
            engineering_evaluation_id=engineering_evaluation_id,
            actor_worker_id=actor_worker_id,
            fields=fields,
            activate=False,
        )

    # ── создание ACTIVE ────────────────────────────────────────────────────────

    def create_active(
        self,
        *,
        joint_id: UUID,
        engineering_evaluation_id: UUID,
        actor_worker_id: int,
        fields: dict[str, Any] | None = None,
    ) -> Defect:
        joint = self._require_joint(joint_id)
        self._require_write_roles(joint, actor_worker_id, "create_active")
        self._require_confirmed_evaluation(engineering_evaluation_id, joint_id)
        if (
            self._repo.get_root_by_evaluation_id(engineering_evaluation_id)
            is not None
        ):
            raise DomainError(
                409,
                dw.DEFECT_ALREADY_EXISTS_FOR_EVALUATION,
                "Для этой оценки уже существует цепочка Defect",
            )
        return self._create(
            joint_id=joint_id,
            engineering_evaluation_id=engineering_evaluation_id,
            actor_worker_id=actor_worker_id,
            fields=fields,
            activate=True,
        )

    def _create(
        self,
        *,
        joint_id: UUID,
        engineering_evaluation_id: UUID,
        actor_worker_id: int,
        fields: dict[str, Any] | None,
        activate: bool,
    ) -> Defect:
        now = _now()
        defect_no = self._repo.next_defect_no(joint_id)
        root = DefectRoot(
            engineering_evaluation_id=engineering_evaluation_id,
            joint_id=joint_id,
            defect_no=defect_no,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        status = dw.DEFECT_ACTIVE if activate else dw.DEFECT_DRAFT
        defect = Defect(
            defect_root_id=None,
            revision_no=1,
            status=status,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        if activate:
            defect.activated_by_worker_id = actor_worker_id
            defect.activated_at = now
        self._apply_fields(defect, fields)
        if activate:
            self._validate_active(defect)
        try:
            self._repo.create_root(root)
            defect.defect_root_id = root.id
            self._repo.create_revision(defect)
            root.current_defect_id = defect.id
            if activate:
                root.active_defect_id = defect.id
            self._record_event(
                defect,
                dw.EVENT_ACTIVATED if activate else dw.EVENT_DRAFT_CREATED,
                actor_worker_id=actor_worker_id,
                from_status=None,
                to_status=status,
            )
            self._repo.save()
        except IntegrityError as exc:
            self._db.rollback()
            # UNIQUE(engineering_evaluation_id) — гонка двух create для одной оценки.
            raise DomainError(
                409,
                dw.DEFECT_ALREADY_EXISTS_FOR_EVALUATION,
                "Для этой оценки уже существует цепочка Defect",
            ) from exc
        return defect

    # ── редактирование DRAFT ───────────────────────────────────────────────────

    def update_draft(
        self,
        defect_id: UUID,
        *,
        expected_version: int,
        actor_worker_id: int,
        fields: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> Defect:
        defect = self._require_defect(defect_id)
        root = self._require_root(defect.defect_root_id)
        joint = self._require_joint(root.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_write_roles(joint, actor_worker_id, "update_draft")
        if defect.status == dw.DEFECT_ACTIVE:
            raise DomainError(
                409,
                dw.DEFECT_ACTIVE_IMMUTABLE,
                "Технические поля ACTIVE неизменяемы; исправление — через supersede",
            )
        if defect.status != dw.DEFECT_DRAFT:
            raise DomainError(
                409,
                dw.DEFECT_INVALID_TRANSITION,
                f"Редактирование запрещено в статусе {defect.status}",
            )
        self._check_version(defect, expected_version)
        self._apply_fields(defect, fields)
        defect.updated_by_worker_id = actor_worker_id
        defect.version += 1
        try:
            self._record_event(
                defect,
                dw.EVENT_UPDATED,
                actor_worker_id=actor_worker_id,
                from_status=dw.DEFECT_DRAFT,
                to_status=dw.DEFECT_DRAFT,
                reason=reason.strip() if reason and reason.strip() else None,
            )
            self._repo.save()
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Нарушение целостности при изменении DRAFT") from exc
        return defect

    # ── активация DRAFT → ACTIVE ───────────────────────────────────────────────

    def activate(
        self,
        defect_id: UUID,
        *,
        expected_version: int,
        actor_worker_id: int,
    ) -> Defect:
        defect = self._require_defect(defect_id)
        root = self._repo.lock_root_for_update(defect.defect_root_id)
        if root is None:
            raise DomainError(404, dw.DEFECT_ROOT_NOT_FOUND, "DefectRoot не найден")
        self._db.refresh(defect)
        joint = self._require_joint(root.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_write_roles(joint, actor_worker_id, "activate")
        if defect.status != dw.DEFECT_DRAFT:
            raise DomainError(
                409,
                dw.DEFECT_INVALID_TRANSITION,
                f"Активация возможна только из DRAFT (текущий {defect.status})",
            )
        self._check_version(defect, expected_version)
        if self._repo.get_current_active_revision(root.id) is not None:
            raise DomainError(
                409,
                dw.DEFECT_INVALID_TRANSITION,
                "В цепочке уже есть ACTIVE-ревизия (используйте supersede)",
            )
        # Инвариант происхождения проверяется повторно (источник мог измениться).
        self._require_confirmed_evaluation(root.engineering_evaluation_id, root.joint_id)
        self._validate_active(defect)

        defect.status = dw.DEFECT_ACTIVE
        defect.activated_by_worker_id = actor_worker_id
        defect.activated_at = _now()
        defect.updated_by_worker_id = actor_worker_id
        defect.version += 1
        root.active_defect_id = defect.id
        root.current_defect_id = defect.id
        root.updated_by_worker_id = actor_worker_id
        root.version += 1
        try:
            self._record_event(
                defect,
                dw.EVENT_ACTIVATED,
                actor_worker_id=actor_worker_id,
                from_status=dw.DEFECT_DRAFT,
                to_status=dw.DEFECT_ACTIVE,
            )
            self._repo.save()
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Нарушение целостности при активации") from exc
        return defect

    # ── supersede: ACTIVE → SUPERSEDED + новая DRAFT (двухшагово, Spec §5) ──────

    def supersede(
        self,
        defect_id: UUID,
        *,
        expected_version: int,
        actor_worker_id: int,
        fields: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> Defect:
        """Замещает действующую `ACTIVE`-ревизию новой `DRAFT`-ревизией (supersede-time).

        Одна атомарная транзакция (Spec §3): блокировка корня/текущей `ACTIVE` →
        `expected_version` → нормализация patch → снимок новой `DRAFT` → структурная
        проверка DRAFT → previous `ACTIVE → SUPERSEDED` → создание `DRAFT` → два события
        (`DEFECT_SUPERSEDED` + `DEFECT_REVISION_CREATED`) → commit. При любой ошибке до
        коммита previous остаётся `ACTIVE`, новая `DRAFT` не создаётся, событий нет.
        Активация новой `DRAFT` — отдельной командой `activate`.
        """
        previous = self._require_defect(defect_id)
        root = self._repo.lock_root_for_update(previous.defect_root_id)
        if root is None:
            raise DomainError(404, dw.DEFECT_ROOT_NOT_FOUND, "DefectRoot не найден")
        joint = self._require_joint(root.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_write_roles(joint, actor_worker_id, "supersede")

        # После блокировки корня перечитываем действующую ревизию (защита от гонки).
        current = self._repo.lock_current_active_revision(root.id)
        if current is None:
            raise DomainError(
                409,
                dw.DEFECT_SUPERSEDE_REQUIRES_ACTIVE,
                "В цепочке нет действующей ACTIVE-ревизии для замещения",
            )
        if current.id != previous.id:
            raise DomainError(
                409,
                dw.DEFECT_INVALID_TRANSITION,
                "Действующая ревизия изменилась; повторите supersede",
            )
        self._db.refresh(previous)
        if previous.status != dw.DEFECT_ACTIVE:
            raise DomainError(
                409,
                dw.DEFECT_SUPERSEDE_REQUIRES_ACTIVE,
                f"supersede возможен только из ACTIVE (текущий {previous.status})",
            )
        self._check_version(previous, expected_version)
        # Не более одной открытой DRAFT в цепочке (D04).
        if self._repo.get_open_draft_revision(root.id) is not None:
            raise DomainError(
                409,
                dw.DEFECT_CHAIN_HAS_OPEN_DRAFT,
                "В цепочке уже есть открытая DRAFT-ревизия",
            )
        # Инвариант происхождения проверяется повторно: оценка того же Joint (Spec §5).
        self._require_confirmed_evaluation(root.engineering_evaluation_id, root.joint_id)

        # Полный снимок предыдущей ACTIVE + нормализованный patch.
        snapshot = {f: getattr(previous, f) for f in dw.DEFECT_TECHNICAL_FIELDS}
        patch = normalize_field_values(
            {
                k: v
                for k, v in (fields or {}).items()
                if k in dw.DEFECT_TECHNICAL_FIELDS
            }
        )
        merged = {**snapshot, **patch}
        now = _now()
        new_no = self._repo.max_revision_no(root.id) + 1
        new = Defect(
            defect_root_id=root.id,
            revision_no=new_no,
            status=dw.DEFECT_DRAFT,
            supersedes_defect_id=previous.id,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
            version=1,
        )
        for key, value in merged.items():
            setattr(new, key, value)
        # Новая ревизия — DRAFT: только структурные (CHECK-уровня) инварианты; полная
        # §8-комплектность ACTIVE не требуется (Spec §6) — она проверяется при activate.
        # Проверка ДО изменения previous: сбой оставляет previous ACTIVE.
        self._validate_draft_structural(new)

        changed = {
            f: (snapshot[f], merged[f])
            for f in dw.DEFECT_TECHNICAL_FIELDS
            if snapshot[f] != merged[f]
        }

        # supersede-time: гасим предыдущую (освобождает частичный UNIQUE «одна ACTIVE»),
        # затем вставляем новую DRAFT — одна атомарная транзакция.
        previous.status = dw.DEFECT_SUPERSEDED
        previous.superseded_by_worker_id = actor_worker_id
        previous.superseded_at = now
        previous.updated_by_worker_id = actor_worker_id
        previous.version += 1
        self._db.flush()

        try:
            self._repo.create_revision(new)
            # После supersede действующей ACTIVE в цепочке нет (0 ACTIVE, 1 DRAFT).
            root.active_defect_id = None
            root.current_defect_id = new.id
            root.updated_by_worker_id = actor_worker_id
            root.version += 1
            metadata = {
                "previous_defect_id": str(previous.id),
                "new_defect_id": str(new.id),
                "defect_root_id": str(root.id),
                "previous_revision_no": previous.revision_no,
                "new_revision_no": new_no,
                "changed_fields": list(changed.keys()),
                "before_values": {k: _jsonable(v[0]) for k, v in changed.items()},
                "after_values": {k: _jsonable(v[1]) for k, v in changed.items()},
            }
            if reason and reason.strip():
                metadata["reason"] = reason.strip()
            # Предыдущая: ACTIVE → SUPERSEDED (defect_version = previous.version после команды).
            self._record_event(
                previous,
                dw.EVENT_SUPERSEDED,
                actor_worker_id=actor_worker_id,
                from_status=dw.DEFECT_ACTIVE,
                to_status=dw.DEFECT_SUPERSEDED,
                reason=reason.strip() if reason and reason.strip() else None,
                metadata={
                    "previous_defect_id": str(previous.id),
                    "new_defect_id": str(new.id),
                    "defect_root_id": str(root.id),
                },
            )
            # Новая ревизия: NULL → DRAFT (defect_version = 1). Activation-события нет.
            self._record_event(
                new,
                dw.EVENT_REVISION_CREATED,
                actor_worker_id=actor_worker_id,
                from_status=None,
                to_status=dw.DEFECT_DRAFT,
                metadata=metadata,
            )
            self._repo.save()
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Нарушение целостности при supersede") from exc
        return new

    # ── отмена ─────────────────────────────────────────────────────────────────

    def cancel(
        self,
        defect_id: UUID,
        *,
        expected_version: int,
        actor_worker_id: int,
        reason: str,
    ) -> Defect:
        defect = self._require_defect(defect_id)
        root = self._repo.lock_root_for_update(defect.defect_root_id)
        if root is None:
            raise DomainError(404, dw.DEFECT_ROOT_NOT_FOUND, "DefectRoot не найден")
        self._db.refresh(defect)
        joint = self._require_joint(root.joint_id)
        self._require_visible(joint, actor_worker_id)
        self._require_write_roles(joint, actor_worker_id, "cancel")
        if _is_blank(reason):
            raise DomainError(
                422,
                dw.DEFECT_CANCELLATION_REASON_REQUIRED,
                "Причина отмены обязательна",
            )
        if defect.status not in (dw.DEFECT_DRAFT, dw.DEFECT_ACTIVE):
            raise DomainError(
                409,
                dw.DEFECT_INVALID_TRANSITION,
                f"Отмена невозможна из статуса {defect.status}",
            )
        self._check_version(defect, expected_version)

        previous_status = defect.status
        defect.status = dw.DEFECT_CANCELLED
        defect.cancelled_by_worker_id = actor_worker_id
        defect.cancelled_at = _now()
        defect.cancellation_reason = reason.strip()
        defect.updated_by_worker_id = actor_worker_id
        defect.version += 1
        if previous_status == dw.DEFECT_ACTIVE:
            root.active_defect_id = None
            root.updated_by_worker_id = actor_worker_id
            root.version += 1
        self._record_event(
            defect,
            dw.EVENT_CANCELLED,
            actor_worker_id=actor_worker_id,
            from_status=previous_status,
            to_status=dw.DEFECT_CANCELLED,
            reason=defect.cancellation_reason,
        )
        self._repo.save()
        return defect
