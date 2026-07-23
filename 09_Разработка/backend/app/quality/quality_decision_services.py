"""Прикладной сервис QualityDecision (Task 10A, Implementation Block 2; ADR-027 ACCEPTED).

Сервис владеет жизненным циклом: `CREATE` (→ `DRAFT`), `update_draft` (правка
`summary`/состава оснований только в `DRAFT`), `submit_for_review` (`DRAFT` →
`UNDER_REVIEW`), `return_to_draft` (`UNDER_REVIEW` → `DRAFT`, только OTK_INSPECTOR),
`decide` (`UNDER_REVIEW` → `DECIDED`, только OTK_INSPECTOR; в той же транзакции
замещает предыдущий `DECIDED` того же Joint — `SUPERSEDED`, ADR-027 §G). Прямое
изменение `status`/`is_basis_of_decided` через репозиторий вне сервиса запрещено.

Границы (не нарушать, Task 10A Block 2):

* не создаёт, не читает состояние и не изменяет `Defect`/`DefectDisposition` —
  `DEFECT_CONFIRMED` фиксируется только как значение `decision_result`, связь с
  `Defect` — будущий блок;
* не меняет `EngineeringEvaluation`/`EngineeringEvaluationRevision` — только читает
  их для проверки оснований (существование, тот же Joint, статус `EFFECTIVE`);
* RBAC/scope — существующий механизм (`JointScopeContext`, `worker_role_codes_for_
  joint`), новый не вводится; скрытый по scope ресурс → 404 (паттерн
  DefectDisposition/EngineeringEvaluation);
* API/FastAPI endpoints не создаются — входные данные передаются explicit kwargs
  (как `DefectDispositionService`), не Pydantic-схемами.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.engineering.models import Joint
from app.engineering.repository import EngineeringRepo
from app.projects.repository import ProjectRepo
from app.quality import quality_decision_workflow as qdw
from app.quality.engineering_evaluation_models import EngineeringEvaluationRevision
from app.quality.engineering_evaluation_repository import (
    EngineeringEvaluationRepository,
)
from app.quality.engineering_evaluation_workflow import EVAL_EFFECTIVE
from app.quality.execution_models import QualityAuditEvent
from app.quality.quality_decision_models import QualityDecision, QualityDecisionBasis
from app.quality.quality_decision_repository import QualityDecisionRepository
from app.quality.quality_finding_repository import QualityFindingRepo
from app.shared.errors import DomainError, RoleDeniedError
from app.shared.permissions import JointScopeContext, worker_role_codes_for_joint

# Коды 404 (скрытый/несуществующий ресурс — до проверки роли действия).
_NOT_FOUND_CODES: frozenset[str] = frozenset(
    {
        qdw.QD_NOT_FOUND,
        qdw.QD_JOINT_NOT_FOUND,
        qdw.QD_PROJECT_NOT_FOUND,
        qdw.QD_REVISION_NOT_FOUND,
    }
)
# Коды 409 (конфликт состояния/версии — ресурс существует, но операция сейчас
# недопустима).
_CONFLICT_CODES: frozenset[str] = frozenset(
    {
        qdw.QD_INVALID_TRANSITION,
        qdw.QD_TERMINAL_IMMUTABLE,
        qdw.QD_ONLY_DRAFT_EDITABLE,
        qdw.QD_VERSION_CONFLICT,
        qdw.QD_REVISION_ALREADY_DECIDED,
        qdw.QD_REVISION_WRONG_JOINT,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class QualityDecisionService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = QualityDecisionRepository(db)
        self._eng = EngineeringRepo(db)
        self._projects = ProjectRepo(db)
        self._ee = EngineeringEvaluationRepository(db)
        self._findings = QualityFindingRepo(db)

    # ── scope / RBAC (паттерн DefectDisposition/EngineeringEvaluation) ───────────

    def _require_joint(self, joint_id: UUID) -> Joint:
        joint = self._eng.get_joint(joint_id)
        if joint is None:
            self._deny(qdw.QD_JOINT_NOT_FOUND, qdw.QD_ERROR_MESSAGES[qdw.QD_JOINT_NOT_FOUND])
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

    def _require_decision(self, decision_id: UUID) -> QualityDecision:
        decision = self._repo.get_by_id(decision_id)
        if decision is None:
            self._deny(qdw.QD_NOT_FOUND, qdw.QD_ERROR_MESSAGES[qdw.QD_NOT_FOUND])
        return decision

    def _require_decision_for_update(self, decision_id: UUID) -> QualityDecision:
        decision = self._repo.get_by_id_for_update(decision_id)
        if decision is None:
            self._deny(qdw.QD_NOT_FOUND, qdw.QD_ERROR_MESSAGES[qdw.QD_NOT_FOUND])
        return decision

    def _require_visible(self, joint: Joint, worker_id: int) -> None:
        if not self._granted_roles(joint, worker_id, qdw.QD_READ_ROLES):
            self._deny(qdw.QD_NOT_FOUND, qdw.QD_ERROR_MESSAGES[qdw.QD_NOT_FOUND])

    def _deny(self, code: str, message: str) -> None:
        if code == qdw.QD_PERMISSION_DENIED:
            raise RoleDeniedError(code, message)
        if code in _NOT_FOUND_CODES:
            raise DomainError(404, code, message)
        if code in _CONFLICT_CODES:
            raise DomainError(409, code, message)
        raise DomainError(422, code, message)

    def _record_audit(
        self,
        decision: QualityDecision,
        *,
        event_type: str,
        actor_worker_id: int,
        reason: str | None = None,
        changed_fields: dict | None = None,
        previous_values: dict | None = None,
        new_values: dict | None = None,
    ) -> None:
        self._repo.append_audit_event(
            QualityAuditEvent(
                entity_type=qdw.AUDIT_ENTITY,
                entity_id=decision.id,
                event_type=event_type,
                actor_worker_id=actor_worker_id,
                reason=reason,
                changed_fields=changed_fields,
                previous_values=previous_values,
                new_values=new_values,
            )
        )

    # ── основания (CREATE / UPDATE_DRAFT / DECIDE) ────────────────────────────────

    def _joint_id_for_revision(
        self, revision: EngineeringEvaluationRevision
    ) -> UUID | None:
        """Joint, к которому относится ревизия: revision → evaluation → finding → joint.

        Только чтение через существующие репозитории EngineeringEvaluation/
        QualityFinding — их модули не меняются (Task 10A Block 2 ограничение)."""
        evaluation = self._ee.get_evaluation(revision.evaluation_id)
        if evaluation is None:
            return None
        finding = self._findings.get_finding(evaluation.finding_id)
        if finding is None:
            return None
        return finding.joint_id

    def _resolve_basis_revisions(
        self, joint: Joint, revision_ids: list[UUID]
    ) -> list[EngineeringEvaluationRevision]:
        """Проверяет каждую ревизию-основание: существует, тот же Joint, EFFECTIVE."""
        seen: set[UUID] = set()
        revisions: list[EngineeringEvaluationRevision] = []
        for revision_id in revision_ids:
            if revision_id in seen:
                continue
            seen.add(revision_id)
            revision = self._repo.get_revision(revision_id)
            if revision is None:
                self._deny(
                    qdw.QD_REVISION_NOT_FOUND,
                    f"EngineeringEvaluationRevision {revision_id} не найдена",
                )
            if self._joint_id_for_revision(revision) != joint.id:
                self._deny(
                    qdw.QD_REVISION_WRONG_JOINT,
                    f"Ревизия {revision_id} относится к другому Joint",
                )
            if revision.status != EVAL_EFFECTIVE:
                self._deny(
                    qdw.QD_REVISION_NOT_EFFECTIVE,
                    f"Ревизия {revision_id} не в статусе EFFECTIVE "
                    f"(текущий: {revision.status})",
                )
            revisions.append(revision)
        return revisions

    def _replace_bases(
        self,
        decision: QualityDecision,
        revisions: list[EngineeringEvaluationRevision],
        *,
        actor_worker_id: int,
    ) -> None:
        existing = self._repo.list_bases(decision.id)
        existing_by_revision = {b.engineering_evaluation_revision_id: b for b in existing}
        keep_ids = {r.id for r in revisions}
        for basis in existing:
            if basis.engineering_evaluation_revision_id not in keep_ids:
                self._repo.delete_basis(basis)
        for revision in revisions:
            if revision.id not in existing_by_revision:
                self._repo.add_basis(
                    QualityDecisionBasis(
                        quality_decision_id=decision.id,
                        engineering_evaluation_revision_id=revision.id,
                        linked_by_worker_id=actor_worker_id,
                    )
                )

    # ── CREATE ────────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        joint_id: UUID,
        basis_revision_ids: list[UUID],
        actor_worker_id: int,
        summary: str | None = None,
    ) -> QualityDecision:
        joint = self._require_joint(joint_id)
        granted = self._granted_roles(
            joint, actor_worker_id, qdw.QD_CREATE_ROLES, include_company=False
        )

        error = qdw.validate_create_request(
            granted_roles=granted, has_basis=bool(basis_revision_ids)
        )
        if error is not None:
            self._deny(error, qdw.QD_ERROR_MESSAGES.get(error, error))

        revisions = self._resolve_basis_revisions(joint, basis_revision_ids)

        project = self._projects.get_project(joint.project_id)
        if project is None:
            self._deny(
                qdw.QD_PROJECT_NOT_FOUND, qdw.QD_ERROR_MESSAGES[qdw.QD_PROJECT_NOT_FOUND]
            )

        seq = self._repo.next_sequence(project.id)
        system_code = f"{project.code}-QD-{seq}"

        decision = QualityDecision(
            project_id=joint.project_id,
            joint_id=joint.id,
            system_code=system_code,
            status=qdw.QD_DRAFT,
            summary=summary.strip() if summary and summary.strip() else None,
            created_by_worker_id=actor_worker_id,
        )
        self._repo.add(decision)

        for revision in revisions:
            self._repo.add_basis(
                QualityDecisionBasis(
                    quality_decision_id=decision.id,
                    engineering_evaluation_revision_id=revision.id,
                    linked_by_worker_id=actor_worker_id,
                )
            )

        actor_role = qdw.pick_actor_role(qdw.ACTION_CREATE, granted)
        self._record_audit(
            decision,
            event_type=qdw.EVENT_CREATED,
            actor_worker_id=actor_worker_id,
            changed_fields={"actor_role": actor_role},
            new_values={
                "status": qdw.QD_DRAFT,
                "joint_id": str(joint.id),
                "basis_revision_ids": [str(r.id) for r in revisions],
            },
        )
        self._repo.save()
        self._db.refresh(decision)
        return decision

    # ── чтение ────────────────────────────────────────────────────────────────────

    def get(self, decision_id: UUID, *, actor_worker_id: int) -> QualityDecision:
        decision = self._require_decision(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)
        return decision

    def list_bases(
        self, decision_id: UUID, *, actor_worker_id: int
    ) -> list[QualityDecisionBasis]:
        decision = self._require_decision(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_bases(decision.id)

    def list_audit_events(
        self, decision_id: UUID, *, actor_worker_id: int
    ) -> list[QualityAuditEvent]:
        decision = self._require_decision(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)
        return self._repo.list_audit_events(decision.id)

    # ── UPDATE_DRAFT ──────────────────────────────────────────────────────────────

    def update_draft(
        self,
        decision_id: UUID,
        *,
        expected_version: int,
        actor_worker_id: int,
        summary: str | None = None,
        basis_revision_ids: list[UUID] | None = None,
    ) -> QualityDecision:
        """Правка `DRAFT`: `summary`/состав оснований. Не пишет audit event (§UPDATE
        DRAFT задания: изменения DRAFT не требуют отдельного audit event)."""
        decision = self._require_decision_for_update(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)

        granted = self._granted_roles(
            joint, actor_worker_id, qdw.QD_UPDATE_DRAFT_ROLES, include_company=False
        )
        error = qdw.validate_update_draft_request(
            current_status=decision.status, granted_roles=granted
        )
        if error is not None:
            self._deny(error, qdw.QD_ERROR_MESSAGES.get(error, error))

        if decision.version != expected_version:
            self._deny(
                qdw.QD_VERSION_CONFLICT,
                f"Ожидалась версия {expected_version}, текущая {decision.version}",
            )

        if summary is not None:
            decision.summary = summary.strip() if summary.strip() else None

        if basis_revision_ids is not None:
            revisions = self._resolve_basis_revisions(joint, basis_revision_ids)
            if not revisions:
                self._deny(
                    qdw.QD_BASIS_REQUIRED, qdw.QD_ERROR_MESSAGES[qdw.QD_BASIS_REQUIRED]
                )
            self._replace_bases(decision, revisions, actor_worker_id=actor_worker_id)

        decision.version += 1
        self._repo.save()
        self._db.refresh(decision)
        return decision

    # ── SUBMIT_FOR_REVIEW ─────────────────────────────────────────────────────────

    def submit_for_review(
        self, decision_id: UUID, *, expected_version: int, actor_worker_id: int
    ) -> QualityDecision:
        decision = self._require_decision_for_update(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)

        granted = self._granted_roles(
            joint,
            actor_worker_id,
            qdw.roles_for_action(qdw.ACTION_SUBMIT_FOR_REVIEW),
            include_company=False,
        )
        bases = self._repo.list_bases(decision.id)

        error = qdw.validate_submit_request(
            current_status=decision.status,
            granted_roles=granted,
            has_summary=not qdw.is_blank(decision.summary),
            has_basis=bool(bases),
        )
        if error is not None:
            self._deny(error, qdw.QD_ERROR_MESSAGES.get(error, error))

        if decision.version != expected_version:
            self._deny(
                qdw.QD_VERSION_CONFLICT,
                f"Ожидалась версия {expected_version}, текущая {decision.version}",
            )

        previous_status = decision.status
        decision.status = qdw.QD_UNDER_REVIEW
        decision.version += 1

        actor_role = qdw.pick_actor_role(qdw.ACTION_SUBMIT_FOR_REVIEW, granted)
        self._record_audit(
            decision,
            event_type=qdw.EVENT_SUBMITTED,
            actor_worker_id=actor_worker_id,
            changed_fields={"actor_role": actor_role},
            previous_values={"status": previous_status},
            new_values={"status": decision.status},
        )
        self._repo.save()
        self._db.refresh(decision)
        return decision

    # ── RETURN ────────────────────────────────────────────────────────────────────

    def return_to_draft(
        self,
        decision_id: UUID,
        *,
        expected_version: int,
        return_reason: str,
        actor_worker_id: int,
    ) -> QualityDecision:
        decision = self._require_decision_for_update(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)

        granted = self._granted_roles(
            joint,
            actor_worker_id,
            qdw.roles_for_action(qdw.ACTION_RETURN),
            include_company=False,
        )

        error = qdw.validate_return_request(
            current_status=decision.status,
            granted_roles=granted,
            reason=return_reason,
        )
        if error is not None:
            self._deny(error, qdw.QD_ERROR_MESSAGES.get(error, error))

        if decision.version != expected_version:
            self._deny(
                qdw.QD_VERSION_CONFLICT,
                f"Ожидалась версия {expected_version}, текущая {decision.version}",
            )

        previous_status = decision.status
        decision.status = qdw.QD_DRAFT
        decision.return_reason = return_reason.strip()
        decision.version += 1

        actor_role = qdw.pick_actor_role(qdw.ACTION_RETURN, granted)
        self._record_audit(
            decision,
            event_type=qdw.EVENT_RETURNED,
            actor_worker_id=actor_worker_id,
            reason=decision.return_reason,
            changed_fields={"actor_role": actor_role},
            previous_values={"status": previous_status},
            new_values={"status": decision.status},
        )
        self._repo.save()
        self._db.refresh(decision)
        return decision

    # ── DECIDE (+ системный supersede, ADR-027 §G) ───────────────────────────────

    def decide(
        self,
        decision_id: UUID,
        *,
        expected_version: int,
        decision_result: str,
        actor_worker_id: int,
    ) -> QualityDecision:
        """`UNDER_REVIEW` → `DECIDED` (только OTK_INSPECTOR).

        Атомарно: если у Joint уже есть `DECIDED` QualityDecision — замещает его
        (`DECIDED` → `SUPERSEDED`) в той же транзакции (ADR-027 §G; системное
        следствие, не отдельная команда). Порядок блокировок: 1) строка `decision`
        (сериализация повторного DECIDE); 2) строка `Joint` (сериализация двух
        параллельных DECIDE на разные QualityDecision одного Joint); 3) строки
        ревизий-оснований (сериализация переключения `is_basis_of_decided`).
        Замещение старой записи флешится до простановки новых флагов/статуса —
        иначе партиционные unique-индексы (`uq_quality_decisions_one_decided_per_
        joint`, `uq_quality_decision_bases_one_decided_per_revision`) могут увидеть
        транзитный дубликат в рамках одного flush.
        """
        decision = self._require_decision_for_update(decision_id)
        joint = self._require_joint(decision.joint_id)
        self._require_visible(joint, actor_worker_id)

        granted = self._granted_roles(
            joint,
            actor_worker_id,
            qdw.roles_for_action(qdw.ACTION_DECIDE),
            include_company=False,
        )

        # Сериализация относительно других QualityDecision того же Joint.
        self._repo.lock_joint_for_update(joint.id)

        bases = self._repo.list_bases(decision.id)

        error = qdw.validate_decide_request(
            current_status=decision.status,
            granted_roles=granted,
            result=decision_result,
            has_basis=bool(bases),
        )
        if error is not None:
            self._deny(error, qdw.QD_ERROR_MESSAGES.get(error, error))

        if decision.version != expected_version:
            self._deny(
                qdw.QD_VERSION_CONFLICT,
                f"Ожидалась версия {expected_version}, текущая {decision.version}",
            )

        revision_ids = [b.engineering_evaluation_revision_id for b in bases]
        locked_revisions = {
            r.id: r for r in self._repo.lock_revisions_for_update(revision_ids)
        }
        for basis in bases:
            revision = locked_revisions.get(basis.engineering_evaluation_revision_id)
            if revision is None or revision.status != EVAL_EFFECTIVE:
                self._deny(
                    qdw.QD_REVISION_NOT_EFFECTIVE,
                    qdw.QD_ERROR_MESSAGES[qdw.QD_REVISION_NOT_EFFECTIVE],
                )

        old = self._repo.find_decided_for_joint(joint.id)
        if old is not None and old.id == decision.id:
            old = None  # защитно: DECIDED уже терминален, сюда не дойти по validate

        # Конфликт «уже основание другого DECIDED» ожидаем только для ревизий,
        # принадлежащих замещаемому `old` (штатный supersede-сценарий).
        for basis in bases:
            conflict = self._repo.find_basis_row_for_revision(
                basis.engineering_evaluation_revision_id, is_basis_of_decided=True
            )
            if conflict is not None and (
                old is None or conflict.quality_decision_id != old.id
            ):
                self._deny(
                    qdw.QD_REVISION_ALREADY_DECIDED,
                    qdw.QD_ERROR_MESSAGES[qdw.QD_REVISION_ALREADY_DECIDED],
                )

        previous_status = decision.status
        actor_role = qdw.pick_actor_role(qdw.ACTION_DECIDE, granted)
        now = _now()

        old_previous_status: str | None = None
        if old is not None:
            old = self._repo.get_by_id_for_update(old.id)
            self._db.refresh(old)
            old_previous_status = old.status
            old.status = qdw.QD_SUPERSEDED
            old.version += 1
            for old_basis in self._repo.list_bases(old.id):
                old_basis.is_basis_of_decided = False
            # Флеш до простановки нового статуса/флагов (см. docstring метода).
            self._db.flush()

        decision.status = qdw.QD_DECIDED
        decision.decision_result = decision_result
        decision.approved_by_worker_id = actor_worker_id
        decision.approved_at = now
        decision.approved_role = actor_role
        decision.supersedes_quality_decision_id = old.id if old is not None else None
        decision.version += 1

        for basis in bases:
            basis.is_basis_of_decided = True

        self._record_audit(
            decision,
            event_type=qdw.EVENT_DECIDED,
            actor_worker_id=actor_worker_id,
            changed_fields={"actor_role": actor_role},
            previous_values={"status": previous_status},
            new_values={
                "status": decision.status,
                "decision_result": decision.decision_result,
            },
        )
        if old is not None:
            self._record_audit(
                old,
                event_type=qdw.EVENT_SUPERSEDED,
                actor_worker_id=actor_worker_id,
                changed_fields={
                    "actor_role": actor_role,
                    "superseded_by_quality_decision_id": str(decision.id),
                },
                previous_values={"status": old_previous_status},
                new_values={"status": old.status},
            )

        self._repo.save()
        self._db.refresh(decision)
        if old is not None:
            self._db.refresh(old)
        return decision
