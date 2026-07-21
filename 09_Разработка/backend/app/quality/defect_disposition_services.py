"""Доменный сервис DefectDisposition (Task 9D-4A-3, ADR-023).

Все изменения статуса — только через этот сервис (prepare/approve/activate/cancel
или единый transition). Прямое обновление status через repository запрещено.
Policy — `defect_disposition_policy`; переходы — `defect_disposition_workflow`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.projects.repository import ProjectRepo
from app.quality import defect_disposition_policy as policy
from app.quality import defect_disposition_workflow as ddw
from app.quality.defect_disposition_models import (
    DEFECT_DISPOSITION_DECISION_TYPES,
    DefectDisposition,
    DefectDispositionEvent,
)
from app.quality.defect_disposition_repository import DefectDispositionRepository
from app.quality.defect_models import DefectRoot
from app.shared.errors import DomainError, RoleDeniedError
from app.shared.permissions import (
    JointScopeContext,
    worker_role_codes_for_joint,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DefectDispositionService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = DefectDispositionRepository(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)

    # ── scope / RBAC ───────────────────────────────────────────────────────────

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            raise DomainError(
                404, ddw.DISPOSITION_ROOT_NOT_FOUND, "Стык defect_root не найден"
            )
        return joint

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

    def _require_root(self, root_id: UUID) -> DefectRoot:
        root = self._repo.get_root(root_id)
        if root is None:
            raise DomainError(
                404, ddw.DISPOSITION_ROOT_NOT_FOUND, "DefectRoot не найден"
            )
        return root

    def _require_disposition(self, disposition_id: UUID) -> DefectDisposition:
        disp = self._repo.get_by_id(disposition_id)
        if disp is None:
            raise DomainError(
                404, ddw.DISPOSITION_NOT_FOUND, "DefectDisposition не найден"
            )
        return disp

    def _require_disposition_for_update(
        self, disposition_id: UUID
    ) -> DefectDisposition:
        disp = self._repo.get_by_id_for_update(disposition_id)
        if disp is None:
            raise DomainError(
                404, ddw.DISPOSITION_NOT_FOUND, "DefectDisposition не найден"
            )
        return disp

    def _load_with_joint(
        self, disposition_id: UUID
    ) -> tuple[DefectDisposition, DefectRoot, Joint]:
        disp = self._require_disposition(disposition_id)
        root = self._require_root(disp.defect_root_id)
        joint = self._require_joint(root.joint_id)
        return disp, root, joint

    def _load_with_joint_for_update(
        self, disposition_id: UUID
    ) -> tuple[DefectDisposition, DefectRoot, Joint]:
        """Lock disposition до проверки status/policy (сериализация конкурентных transition)."""
        disp = self._require_disposition_for_update(disposition_id)
        root = self._require_root(disp.defect_root_id)
        joint = self._require_joint(root.joint_id)
        return disp, root, joint

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        if not self._granted_roles(joint, worker_id, ddw.DISPOSITION_READ_ROLES):
            raise DomainError(
                404, ddw.DISPOSITION_NOT_FOUND, "DefectDisposition не найден"
            )

    def _deny(self, code: str, message: str) -> None:
        if code == ddw.DISPOSITION_PERMISSION_DENIED:
            raise RoleDeniedError(code, message)
        if code in (
            ddw.DISPOSITION_ACTIVE_IMMUTABLE,
            ddw.DISPOSITION_CANCELLED_IMMUTABLE,
            ddw.DISPOSITION_INVALID_TRANSITION,
        ):
            raise DomainError(409, code, message)
        if code in (
            ddw.DISPOSITION_REASON_REQUIRED,
            ddw.DISPOSITION_JUSTIFICATION_REQUIRED,
            ddw.DISPOSITION_DECISION_TYPE_INVALID,
            ddw.DISPOSITION_INVALID_ACTION,
            ddw.DISPOSITION_ALREADY_OPEN,
        ):
            raise DomainError(422, code, message)
        raise DomainError(422, code, message)

    def _record_event(
        self,
        disposition: DefectDisposition,
        *,
        event_type: str,
        action: str,
        actor_worker_id: int,
        actor_role: str | None,
        previous_status: str | None,
        new_status: str | None,
        reason: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._repo.append_event(
            DefectDispositionEvent(
                defect_disposition_id=disposition.id,
                defect_root_id=disposition.defect_root_id,
                event_type=event_type,
                action=action,
                previous_status=previous_status,
                new_status=new_status,
                actor_worker_id=actor_worker_id,
                actor_role=actor_role,
                reason=reason,
                event_metadata=metadata,
            )
        )

    # ── команды ────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        defect_root_id: UUID,
        decision_type: str,
        justification: str,
        actor_worker_id: int,
        comment: str | None = None,
    ) -> DefectDisposition:
        if decision_type not in DEFECT_DISPOSITION_DECISION_TYPES:
            self._deny(
                ddw.DISPOSITION_DECISION_TYPE_INVALID,
                f"Недопустимый decision_type: {decision_type}",
            )
        if policy.is_blank(justification):
            self._deny(
                ddw.DISPOSITION_JUSTIFICATION_REQUIRED,
                "Обоснование disposition обязательно",
            )

        root = self._require_root(defect_root_id)
        joint = self._require_joint(root.joint_id)
        granted = self._granted_roles(
            joint,
            actor_worker_id,
            ddw.DISPOSITION_CREATE_ROLES,
            include_company=False,
        )
        if not policy.can_create(granted):
            raise RoleDeniedError(
                ddw.DISPOSITION_PERMISSION_DENIED,
                "Недостаточно прав для создания DefectDisposition",
            )

        existing = self._repo.find_open_for_root(root.id)
        if existing is not None:
            self._deny(
                ddw.DISPOSITION_ALREADY_OPEN,
                "По defect_root уже есть открытое DefectDisposition",
            )

        disposition = DefectDisposition(
            defect_root_id=root.id,
            decision_type=decision_type,
            justification=justification.strip(),
            comment=comment.strip() if comment and comment.strip() else None,
            status=ddw.DISPOSITION_DRAFT,
            created_by_worker_id=actor_worker_id,
        )
        self._repo.add(disposition)
        actor_role = policy.pick_actor_role(ddw.ACTION_PREPARE, granted) or (
            ddw.ROLE_OGS_ENGINEER
            if ddw.ROLE_OGS_ENGINEER in granted
            else ddw.ROLE_CHIEF_WELDER
        )
        self._record_event(
            disposition,
            event_type=ddw.EVENT_CREATED,
            action="CREATE",
            actor_worker_id=actor_worker_id,
            actor_role=actor_role,
            previous_status=None,
            new_status=ddw.DISPOSITION_DRAFT,
        )
        self._repo.save()
        self._db.refresh(disposition)
        return disposition

    def get(
        self, disposition_id: UUID, *, actor_worker_id: int
    ) -> DefectDisposition:
        disp, _root, joint = self._load_with_joint(disposition_id)
        self._require_visible(joint, actor_worker_id)
        return disp

    def list_events(
        self, disposition_id: UUID, *, actor_worker_id: int
    ) -> list[DefectDispositionEvent]:
        disp, _root, joint = self._load_with_joint(disposition_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_events(disp.id)

    def prepare(
        self,
        disposition_id: UUID,
        *,
        actor_worker_id: int,
        comment: str | None = None,
    ) -> DefectDisposition:
        return self.transition(
            disposition_id,
            action=ddw.ACTION_PREPARE,
            actor_worker_id=actor_worker_id,
            comment=comment,
        )

    def approve(
        self,
        disposition_id: UUID,
        *,
        actor_worker_id: int,
        comment: str | None = None,
    ) -> DefectDisposition:
        return self.transition(
            disposition_id,
            action=ddw.ACTION_APPROVE,
            actor_worker_id=actor_worker_id,
            comment=comment,
        )

    def activate(
        self,
        disposition_id: UUID,
        *,
        actor_worker_id: int,
        comment: str | None = None,
    ) -> DefectDisposition:
        return self.transition(
            disposition_id,
            action=ddw.ACTION_ACTIVATE,
            actor_worker_id=actor_worker_id,
            comment=comment,
        )

    def cancel(
        self,
        disposition_id: UUID,
        *,
        actor_worker_id: int,
        comment: str | None = None,
    ) -> DefectDisposition:
        return self.transition(
            disposition_id,
            action=ddw.ACTION_CANCEL,
            actor_worker_id=actor_worker_id,
            comment=comment,
        )

    def transition(
        self,
        disposition_id: UUID,
        *,
        action: str,
        actor_worker_id: int,
        comment: str | None = None,
    ) -> DefectDisposition:
        # 1) FOR UPDATE до чтения status / policy — сериализация конкурентных команд.
        disp, _root, joint = self._load_with_joint_for_update(disposition_id)
        # 2) Скрытый ресурс → 404 до проверки роли действия.
        self._require_visible(joint, actor_worker_id)

        if not ddw.is_valid_action(action):
            self._deny(ddw.DISPOSITION_INVALID_ACTION, f"Неизвестное действие: {action}")

        granted = self._granted_roles(
            joint,
            actor_worker_id,
            ddw.roles_for_action(action),
            include_company=False,
        )

        # 3–5) status после lock → state machine + role policy.
        error = policy.validate_transition_request(
            action=action,
            current_status=disp.status,
            granted_roles=granted,
            reason=comment,
        )
        if error is not None:
            messages = {
                ddw.DISPOSITION_PERMISSION_DENIED: (
                    f"Недостаточно прав для '{action}'"
                ),
                ddw.DISPOSITION_ACTIVE_IMMUTABLE: (
                    "ACTIVE DefectDisposition нельзя изменить"
                ),
                ddw.DISPOSITION_CANCELLED_IMMUTABLE: (
                    "CANCELLED DefectDisposition нельзя восстановить"
                ),
                ddw.DISPOSITION_INVALID_TRANSITION: (
                    f"Переход {disp.status} → {ddw.target_status_for_action(action)} "
                    f"действием {action} запрещён"
                ),
                ddw.DISPOSITION_REASON_REQUIRED: (
                    "Для отмены / активации / override главного сварщика "
                    "обязательна причина"
                ),
                ddw.DISPOSITION_INVALID_ACTION: f"Неизвестное действие: {action}",
            }
            self._deny(error, messages.get(error, error))

        previous = disp.status
        target = ddw.target_status_for_action(action)
        assert target is not None

        # 6–7) status + audit event в одной транзакции; 8) один commit.
        disp.status = target
        if action == ddw.ACTION_APPROVE:
            disp.approved_by_worker_id = actor_worker_id
            disp.approved_at = _now()
        if comment and comment.strip() and action != ddw.ACTION_CANCEL:
            disp.comment = comment.strip()

        actor_role = policy.pick_actor_role(action, granted)
        event_type = ddw.event_type_for_action(action)
        assert event_type is not None
        self._record_event(
            disp,
            event_type=event_type,
            action=action,
            actor_worker_id=actor_worker_id,
            actor_role=actor_role,
            previous_status=previous,
            new_status=target,
            reason=comment.strip() if comment and comment.strip() else None,
        )
        self._repo.save()
        self._db.refresh(disp)
        return disp
