"""Тесты QualityDecision Core Block 2 (Task 10A, ADR-027 ACCEPTED).

Сервисный/workflow уровень (repository/service/workflow) — API нет (Block 2 её не
создаёт). Переиспользует `DefectCtx` (`tests._defect_support`): роль `ctx.ogs`
(технический код `OGS_ENGINEER`) — бизнес-роль WELDING_ENGINEER контура
QualityDecision; `ctx.otk` — OTK_INSPECTOR; `ctx.chief`/`ctx.norole` — отрицательные
кейсы (CHIEF_WELDER не участвует в контуре, `norole` — без ролей вовсе).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality import quality_decision_workflow as qdw
from app.quality.engineering_evaluation_models import EngineeringEvaluationRevision
from app.quality.execution_models import QualityAuditEvent
from app.quality.quality_decision_models import QualityDecision
from app.quality.quality_decision_services import QualityDecisionService
from app.shared.db import SessionLocal
from app.shared.errors import DomainError, RoleDeniedError

from ._defect_support import DefectCtx


@pytest.fixture
def ctx(db: Session) -> DefectCtx:
    return DefectCtx(db, "Qd")


def _draft_revision(ctx: DefectCtx, joint) -> EngineeringEvaluationRevision:
    """Ревизия в статусе DRAFT (не EFFECTIVE) — для негативных кейсов."""
    ev = ctx.new_evaluation(joint)
    rev = EngineeringEvaluationRevision(
        evaluation_id=ev.id,
        revision_no=1,
        created_by_worker_id=ctx.creator.id,
        updated_by_worker_id=ctx.creator.id,
    )
    ctx.db.add(rev)
    ctx.db.commit()
    ctx.db.refresh(rev)
    ev.current_revision_id = rev.id
    ctx.db.add(ev)
    ctx.db.commit()
    return rev


def _effective_revision(ctx: DefectCtx, joint) -> EngineeringEvaluationRevision:
    ev = ctx.new_confirmed_evaluation(joint)
    return ctx.db.get(EngineeringEvaluationRevision, ev.effective_revision_id)


def _run_parallel(fns: list[Callable]) -> list:
    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(fn) for fn in fns]
        return [f.result() for f in futures]


def _create_under_review(
    svc: QualityDecisionService, ctx: DefectCtx, joint, rev, *, summary="итог"
) -> QualityDecision:
    decision = svc.create(
        joint_id=joint.id,
        basis_revision_ids=[rev.id],
        actor_worker_id=ctx.ogs.id,
        summary=summary,
    )
    return svc.submit_for_review(
        decision.id, expected_version=decision.version, actor_worker_id=ctx.ogs.id
    )


def _create_decided(
    svc: QualityDecisionService,
    ctx: DefectCtx,
    joint,
    rev,
    *,
    result: str = "ACCEPTED",
    summary: str = "итог",
) -> QualityDecision:
    under_review = _create_under_review(svc, ctx, joint, rev, summary=summary)
    return svc.decide(
        under_review.id,
        expected_version=under_review.version,
        decision_result=result,
        actor_worker_id=ctx.otk.id,
    )


# ── Pure workflow ────────────────────────────────────────────────────────────────


class TestWorkflowPure:
    def test_allowed_transitions(self):
        assert qdw.can_transition("DRAFT", "UNDER_REVIEW")
        assert qdw.can_transition("UNDER_REVIEW", "DRAFT")
        assert qdw.can_transition("UNDER_REVIEW", "DECIDED")
        assert qdw.can_transition("DECIDED", "SUPERSEDED")
        assert not qdw.can_transition("DRAFT", "DECIDED")
        assert not qdw.can_transition("SUPERSEDED", "DRAFT")
        assert not qdw.can_transition("DECIDED", "DRAFT")

    def test_terminal_statuses(self):
        assert qdw.is_terminal("DECIDED")
        assert qdw.is_terminal("SUPERSEDED")
        assert not qdw.is_terminal("DRAFT")
        assert not qdw.is_terminal("UNDER_REVIEW")

    def test_roles_no_chief_welder_anywhere(self):
        all_roles: set[str] = set()
        for action in (
            qdw.ACTION_CREATE,
            qdw.ACTION_UPDATE_DRAFT,
            qdw.ACTION_SUBMIT_FOR_REVIEW,
            qdw.ACTION_RETURN,
            qdw.ACTION_DECIDE,
        ):
            all_roles |= qdw.roles_for_action(action)
        assert "CHIEF_WELDER" not in all_roles
        assert qdw.ROLE_WELDING_ENGINEER == "OGS_ENGINEER"
        assert qdw.ROLE_OTK_INSPECTOR == "OTK_INSPECTOR"

    def test_welding_engineer_create_submit_not_decide(self):
        we = {qdw.ROLE_WELDING_ENGINEER}
        assert qdw.can_perform_action(qdw.ACTION_CREATE, we)
        assert qdw.can_perform_action(qdw.ACTION_SUBMIT_FOR_REVIEW, we)
        assert not qdw.can_perform_action(qdw.ACTION_DECIDE, we)
        assert not qdw.can_perform_action(qdw.ACTION_RETURN, we)

    def test_otk_decide_return_not_create(self):
        otk = {qdw.ROLE_OTK_INSPECTOR}
        assert qdw.can_perform_action(qdw.ACTION_DECIDE, otk)
        assert qdw.can_perform_action(qdw.ACTION_RETURN, otk)
        assert not qdw.can_perform_action(qdw.ACTION_CREATE, otk)
        assert not qdw.can_perform_action(qdw.ACTION_SUBMIT_FOR_REVIEW, otk)

    def test_validate_decide_request_result_invalid(self):
        code = qdw.validate_decide_request(
            current_status=qdw.QD_UNDER_REVIEW,
            granted_roles={qdw.ROLE_OTK_INSPECTOR},
            result="NOT_A_RESULT",
            has_basis=True,
        )
        assert code == qdw.QD_RESULT_INVALID

    def test_validate_submit_request_needs_summary_and_basis(self):
        code = qdw.validate_submit_request(
            current_status=qdw.QD_DRAFT,
            granted_roles={qdw.ROLE_WELDING_ENGINEER},
            has_summary=False,
            has_basis=True,
        )
        assert code == qdw.QD_SUMMARY_REQUIRED


# ── CREATE ─────────────────────────────────────────────────────────────────────


class TestCreate:
    def test_happy_path(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-1")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)

        decision = svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev.id],
            actor_worker_id=ctx.ogs.id,
            summary="Проверка по результатам НК",
        )

        assert decision.status == qdw.QD_DRAFT
        assert decision.project_id == joint.project_id
        assert decision.joint_id == joint.id
        assert decision.version == 1
        assert "-QD-" in decision.system_code

        bases = svc.list_bases(decision.id, actor_worker_id=ctx.ogs.id)
        assert [b.engineering_evaluation_revision_id for b in bases] == [rev.id]

        events = svc.list_audit_events(decision.id, actor_worker_id=ctx.ogs.id)
        assert [e.event_type for e in events] == [qdw.EVENT_CREATED]
        assert events[0].actor_worker_id == ctx.ogs.id

    def test_requires_basis(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-2")
        svc = QualityDecisionService(db)
        with pytest.raises(DomainError) as exc:
            svc.create(
                joint_id=joint.id, basis_revision_ids=[], actor_worker_id=ctx.ogs.id
            )
        assert exc.value.code == qdw.QD_BASIS_REQUIRED

    def test_requires_welding_engineer_role(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-3")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        with pytest.raises(RoleDeniedError):
            svc.create(
                joint_id=joint.id,
                basis_revision_ids=[rev.id],
                actor_worker_id=ctx.otk.id,
            )
        with pytest.raises(RoleDeniedError):
            svc.create(
                joint_id=joint.id,
                basis_revision_ids=[rev.id],
                actor_worker_id=ctx.norole.id,
            )

    def test_rejects_non_effective_revision(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-4")
        rev = _draft_revision(ctx, joint)
        svc = QualityDecisionService(db)
        with pytest.raises(DomainError) as exc:
            svc.create(
                joint_id=joint.id,
                basis_revision_ids=[rev.id],
                actor_worker_id=ctx.ogs.id,
            )
        assert exc.value.code == qdw.QD_REVISION_NOT_EFFECTIVE

    def test_rejects_revision_of_another_joint(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-5")
        other_joint = ctx.new_joint("J-QD-5B")
        other_rev = _effective_revision(ctx, other_joint)
        svc = QualityDecisionService(db)
        with pytest.raises(DomainError) as exc:
            svc.create(
                joint_id=joint.id,
                basis_revision_ids=[other_rev.id],
                actor_worker_id=ctx.ogs.id,
            )
        assert exc.value.code == qdw.QD_REVISION_WRONG_JOINT

    def test_rejects_unknown_revision(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-6")
        svc = QualityDecisionService(db)
        with pytest.raises(DomainError) as exc:
            svc.create(
                joint_id=joint.id,
                basis_revision_ids=[uuid4()],
                actor_worker_id=ctx.ogs.id,
            )
        assert exc.value.code == qdw.QD_REVISION_NOT_FOUND

    def test_unknown_joint_404(self, db: Session, ctx: DefectCtx):
        svc = QualityDecisionService(db)
        with pytest.raises(DomainError) as exc:
            svc.create(
                joint_id=uuid4(),
                basis_revision_ids=[uuid4()],
                actor_worker_id=ctx.ogs.id,
            )
        assert exc.value.code == qdw.QD_JOINT_NOT_FOUND

    def test_multiple_draft_allowed_on_same_joint(self, db: Session, ctx: DefectCtx):
        """Q-D2 (уточнено Block 1 Correction): DRAFT/UNDER_REVIEW не ограничены."""
        joint = ctx.new_joint("J-QD-7")
        rev1 = _effective_revision(ctx, joint)
        rev2 = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        d1 = svc.create(
            joint_id=joint.id, basis_revision_ids=[rev1.id], actor_worker_id=ctx.ogs.id
        )
        d2 = svc.create(
            joint_id=joint.id, basis_revision_ids=[rev2.id], actor_worker_id=ctx.ogs.id
        )
        assert d1.status == qdw.QD_DRAFT
        assert d2.status == qdw.QD_DRAFT
        assert d1.id != d2.id


# ── UPDATE_DRAFT ─────────────────────────────────────────────────────────────────


class TestUpdateDraft:
    def _create(self, svc, ctx, joint, rev):
        return svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev.id],
            actor_worker_id=ctx.ogs.id,
            summary="исходное summary",
        )

    def test_updates_summary_and_bases(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-U1")
        rev1 = _effective_revision(ctx, joint)
        rev2 = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._create(svc, ctx, joint, rev1)
        original_version = decision.version

        updated = svc.update_draft(
            decision.id,
            expected_version=decision.version,
            actor_worker_id=ctx.ogs.id,
            summary="новое summary",
            basis_revision_ids=[rev2.id],
        )
        assert updated.summary == "новое summary"
        assert updated.version == original_version + 1
        bases = svc.list_bases(decision.id, actor_worker_id=ctx.ogs.id)
        assert [b.engineering_evaluation_revision_id for b in bases] == [rev2.id]

        # UPDATE_DRAFT не пишет audit event (только CREATE).
        events = svc.list_audit_events(decision.id, actor_worker_id=ctx.ogs.id)
        assert [e.event_type for e in events] == [qdw.EVENT_CREATED]

    def test_cannot_clear_all_bases(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-U2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._create(svc, ctx, joint, rev)
        with pytest.raises(DomainError) as exc:
            svc.update_draft(
                decision.id,
                expected_version=decision.version,
                actor_worker_id=ctx.ogs.id,
                basis_revision_ids=[],
            )
        assert exc.value.code == qdw.QD_BASIS_REQUIRED

    def test_version_conflict(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-U3")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._create(svc, ctx, joint, rev)
        with pytest.raises(DomainError) as exc:
            svc.update_draft(
                decision.id,
                expected_version=decision.version + 5,
                actor_worker_id=ctx.ogs.id,
                summary="x",
            )
        assert exc.value.code == qdw.QD_VERSION_CONFLICT

    def test_only_draft_editable(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-U4")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._create(svc, ctx, joint, rev)
        submitted = svc.submit_for_review(
            decision.id, expected_version=decision.version, actor_worker_id=ctx.ogs.id
        )
        with pytest.raises(DomainError) as exc:
            svc.update_draft(
                submitted.id,
                expected_version=submitted.version,
                actor_worker_id=ctx.ogs.id,
                summary="попытка правки UNDER_REVIEW",
            )
        assert exc.value.code == qdw.QD_ONLY_DRAFT_EDITABLE

    def test_otk_cannot_update_draft(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-U5")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._create(svc, ctx, joint, rev)
        with pytest.raises(RoleDeniedError):
            svc.update_draft(
                decision.id,
                expected_version=decision.version,
                actor_worker_id=ctx.otk.id,
                summary="попытка ОТК",
            )


# ── SUBMIT_FOR_REVIEW / RETURN ───────────────────────────────────────────────────


class TestSubmitAndReturn:
    def _draft(self, svc, ctx, joint, rev, summary="Итог оценки"):
        return svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev.id],
            actor_worker_id=ctx.ogs.id,
            summary=summary,
        )

    def test_submit_requires_summary(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-S1")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._draft(svc, ctx, joint, rev, summary=None)
        with pytest.raises(DomainError) as exc:
            svc.submit_for_review(
                decision.id,
                expected_version=decision.version,
                actor_worker_id=ctx.ogs.id,
            )
        assert exc.value.code == qdw.QD_SUMMARY_REQUIRED

    def test_submit_happy_path(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-S2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._draft(svc, ctx, joint, rev)
        submitted = svc.submit_for_review(
            decision.id,
            expected_version=decision.version,
            actor_worker_id=ctx.ogs.id,
        )
        assert submitted.status == qdw.QD_UNDER_REVIEW
        events = svc.list_audit_events(decision.id, actor_worker_id=ctx.ogs.id)
        assert [e.event_type for e in events] == [
            qdw.EVENT_CREATED,
            qdw.EVENT_SUBMITTED,
        ]

    def test_submit_only_welding_engineer(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-S3")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._draft(svc, ctx, joint, rev)
        with pytest.raises(RoleDeniedError):
            svc.submit_for_review(
                decision.id, expected_version=decision.version, actor_worker_id=ctx.otk.id
            )

    def test_return_requires_otk(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-R1")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._draft(svc, ctx, joint, rev)
        submitted = svc.submit_for_review(
            decision.id, expected_version=decision.version, actor_worker_id=ctx.ogs.id
        )
        with pytest.raises(RoleDeniedError):
            svc.return_to_draft(
                submitted.id,
                expected_version=submitted.version,
                return_reason="попытка ОГС",
                actor_worker_id=ctx.ogs.id,
            )

    def test_return_requires_reason(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-R2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._draft(svc, ctx, joint, rev)
        submitted = svc.submit_for_review(
            decision.id, expected_version=decision.version, actor_worker_id=ctx.ogs.id
        )
        with pytest.raises(DomainError) as exc:
            svc.return_to_draft(
                submitted.id,
                expected_version=submitted.version,
                return_reason="   ",
                actor_worker_id=ctx.otk.id,
            )
        assert exc.value.code == qdw.QD_RETURN_REASON_REQUIRED

    def test_return_happy_path(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-R3")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = self._draft(svc, ctx, joint, rev)
        submitted = svc.submit_for_review(
            decision.id, expected_version=decision.version, actor_worker_id=ctx.ogs.id
        )
        returned = svc.return_to_draft(
            submitted.id,
            expected_version=submitted.version,
            return_reason="Недостаточно обоснования",
            actor_worker_id=ctx.otk.id,
        )
        assert returned.status == qdw.QD_DRAFT
        assert returned.return_reason == "Недостаточно обоснования"

        events = svc.list_audit_events(decision.id, actor_worker_id=ctx.ogs.id)
        assert [e.event_type for e in events] == [
            qdw.EVENT_CREATED,
            qdw.EVENT_SUBMITTED,
            qdw.EVENT_RETURNED,
        ]
        assert events[-1].reason == "Недостаточно обоснования"

        # RETURNED не является персистентным статусом (только промежуточный audit).
        assert returned.status != "RETURNED"


# ── DECIDE ────────────────────────────────────────────────────────────────────────


class TestDecide:
    def test_decide_requires_otk(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-D1")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        under_review = _create_under_review(svc, ctx, joint, rev)
        with pytest.raises(RoleDeniedError):
            svc.decide(
                under_review.id,
                expected_version=under_review.version,
                decision_result=qdw.QD_RESULT_ACCEPTED,
                actor_worker_id=ctx.ogs.id,
            )

    def test_decide_requires_valid_result(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-D2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        under_review = _create_under_review(svc, ctx, joint, rev)
        with pytest.raises(DomainError) as exc:
            svc.decide(
                under_review.id,
                expected_version=under_review.version,
                decision_result="NOT_A_RESULT",
                actor_worker_id=ctx.otk.id,
            )
        assert exc.value.code == qdw.QD_RESULT_INVALID

    def test_decide_happy_path(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-D3")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        under_review = _create_under_review(svc, ctx, joint, rev)

        decided = svc.decide(
            under_review.id,
            expected_version=under_review.version,
            decision_result=qdw.QD_RESULT_ACCEPTED,
            actor_worker_id=ctx.otk.id,
        )
        assert decided.status == qdw.QD_DECIDED
        assert decided.decision_result == qdw.QD_RESULT_ACCEPTED
        assert decided.approved_by_worker_id == ctx.otk.id
        assert decided.approved_at is not None
        assert decided.approved_role == "OTK_INSPECTOR"
        assert decided.supersedes_quality_decision_id is None

        bases = svc.list_bases(decided.id, actor_worker_id=ctx.otk.id)
        assert all(b.is_basis_of_decided for b in bases)

        events = svc.list_audit_events(decided.id, actor_worker_id=ctx.otk.id)
        assert [e.event_type for e in events] == [
            qdw.EVENT_CREATED,
            qdw.EVENT_SUBMITTED,
            qdw.EVENT_DECIDED,
        ]

    def test_decide_requires_effective_revision_still(
        self, db: Session, ctx: DefectCtx
    ):
        """Ревизия перестала быть EFFECTIVE между CREATE и DECIDE."""
        joint = ctx.new_joint("J-QD-D4")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        under_review = _create_under_review(svc, ctx, joint, rev)

        # Ревизия перестала быть EFFECTIVE (в реальном сценарии — через withdraw/
        # supersede EE; здесь достаточно прямой правки статуса, EE-сервис не трогаем).
        rev.status = "DRAFT"
        db.add(rev)
        db.flush()

        with pytest.raises(DomainError) as exc:
            svc.decide(
                under_review.id,
                expected_version=under_review.version,
                decision_result=qdw.QD_RESULT_ACCEPTED,
                actor_worker_id=ctx.otk.id,
            )
        assert exc.value.code == qdw.QD_REVISION_NOT_EFFECTIVE

    def test_cannot_decide_draft_directly(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-D5")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev.id],
            actor_worker_id=ctx.ogs.id,
            summary="итог",
        )
        with pytest.raises(DomainError) as exc:
            svc.decide(
                decision.id,
                expected_version=decision.version,
                decision_result=qdw.QD_RESULT_ACCEPTED,
                actor_worker_id=ctx.otk.id,
            )
        assert exc.value.code == qdw.QD_INVALID_TRANSITION

    def test_cannot_edit_decided(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-D6")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decided = _create_decided(svc, ctx, joint, rev)
        with pytest.raises(DomainError) as exc:
            svc.update_draft(
                decided.id,
                expected_version=decided.version,
                actor_worker_id=ctx.ogs.id,
                summary="попытка правки DECIDED",
            )
        assert exc.value.code == qdw.QD_ONLY_DRAFT_EDITABLE


# ── SUPERSEDE (системное следствие DECIDE, ADR-027 §G) ───────────────────────────


class TestSupersede:
    def test_second_decide_supersedes_first(self, db: Session, ctx: DefectCtx):
        joint = ctx.new_joint("J-QD-SS1")
        rev1 = _effective_revision(ctx, joint)
        rev2 = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)

        old = _create_decided(svc, ctx, joint, rev1)

        new_draft = svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev2.id],
            actor_worker_id=ctx.ogs.id,
            summary="пересмотр",
        )
        new_submitted = svc.submit_for_review(
            new_draft.id, expected_version=new_draft.version, actor_worker_id=ctx.ogs.id
        )
        new_decided = svc.decide(
            new_submitted.id,
            expected_version=new_submitted.version,
            decision_result=qdw.QD_RESULT_DEFECT_CONFIRMED,
            actor_worker_id=ctx.otk.id,
        )

        assert new_decided.status == qdw.QD_DECIDED
        assert new_decided.supersedes_quality_decision_id == old.id

        db.expire_all()
        reloaded_old = db.get(QualityDecision, old.id)
        assert reloaded_old.status == qdw.QD_SUPERSEDED

        old_bases = svc.list_bases(old.id, actor_worker_id=ctx.otk.id)
        assert all(not b.is_basis_of_decided for b in old_bases)
        new_bases = svc.list_bases(new_decided.id, actor_worker_id=ctx.otk.id)
        assert all(b.is_basis_of_decided for b in new_bases)

        old_events = svc.list_audit_events(old.id, actor_worker_id=ctx.otk.id)
        assert old_events[-1].event_type == qdw.EVENT_SUPERSEDED

    def test_supersede_with_overlapping_basis_revision(
        self, db: Session, ctx: DefectCtx
    ):
        """Новый DECIDED переиспользует ту же ревизию, что старый DECIDED."""
        joint = ctx.new_joint("J-QD-SS2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)

        old = _create_decided(svc, ctx, joint, rev)

        new_draft = svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev.id],
            actor_worker_id=ctx.ogs.id,
            summary="пересмотр с той же ревизией",
        )
        new_submitted = svc.submit_for_review(
            new_draft.id, expected_version=new_draft.version, actor_worker_id=ctx.ogs.id
        )
        new_decided = svc.decide(
            new_submitted.id,
            expected_version=new_submitted.version,
            decision_result=qdw.QD_RESULT_NOT_CONFIRMED,
            actor_worker_id=ctx.otk.id,
        )

        assert new_decided.status == qdw.QD_DECIDED
        assert new_decided.supersedes_quality_decision_id == old.id

        db.expire_all()
        assert db.get(QualityDecision, old.id).status == qdw.QD_SUPERSEDED

        new_basis = svc.list_bases(new_decided.id, actor_worker_id=ctx.otk.id)[0]
        assert new_basis.is_basis_of_decided is True


# ── Integrity ─────────────────────────────────────────────────────────────────────


class TestIntegrity:
    def test_only_one_decided_per_joint_at_db_level(
        self, db: Session, ctx: DefectCtx
    ):
        """Прямая попытка вставить второй DECIDED в обход сервиса — блокирует БД."""
        joint = ctx.new_joint("J-QD-I1")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        _create_decided(svc, ctx, joint, rev)
        db.commit()

        second = QualityDecision(
            project_id=joint.project_id,
            joint_id=joint.id,
            system_code=f"{joint.system_code}-QD-DUP",
            status=qdw.QD_DECIDED,
            decision_result=qdw.QD_RESULT_ACCEPTED,
            created_by_worker_id=ctx.ogs.id,
        )
        db.add(second)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_rollback_keeps_state_consistent(
        self, db: Session, ctx: DefectCtx, monkeypatch
    ):
        joint = ctx.new_joint("J-QD-I2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = svc.create(
            joint_id=joint.id,
            basis_revision_ids=[rev.id],
            actor_worker_id=ctx.ogs.id,
            summary="итог",
        )
        decision_id = decision.id

        def boom() -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(svc._repo, "save", boom)
        with pytest.raises(RuntimeError):
            svc.submit_for_review(
                decision_id, expected_version=decision.version, actor_worker_id=ctx.ogs.id
            )
        db.rollback()
        db.expire_all()

        reloaded = db.get(QualityDecision, decision_id)
        assert reloaded is not None
        assert reloaded.status == qdw.QD_DRAFT

        events = (
            db.query(QualityAuditEvent)
            .filter(
                QualityAuditEvent.entity_type == qdw.AUDIT_ENTITY,
                QualityAuditEvent.entity_id == decision_id,
            )
            .all()
        )
        assert [e.event_type for e in events] == [qdw.EVENT_CREATED]


# ── Concurrency (PostgreSQL FOR UPDATE) ──────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_decide_two_decisions_same_joint(self, db: Session):
        """Два QualityDecision одного Joint, DECIDE параллельно: ровно один DECIDED."""
        ctx = DefectCtx(db, "Qc")
        joint = ctx.new_joint("J-QD-C1")
        rev_a = _effective_revision(ctx, joint)
        rev_b = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)

        a = _create_under_review(svc, ctx, joint, rev_a, summary="A")
        b = _create_under_review(svc, ctx, joint, rev_b, summary="B")
        a_id, b_id, a_version, b_version = a.id, b.id, a.version, b.version
        otk_id = ctx.otk.id
        db.commit()

        def decide_worker(decision_id, expected_version):
            s = SessionLocal()
            try:
                result = QualityDecisionService(s).decide(
                    decision_id,
                    expected_version=expected_version,
                    decision_result=qdw.QD_RESULT_ACCEPTED,
                    actor_worker_id=otk_id,
                )
                return ("ok", str(result.id))
            except DomainError as exc:
                s.rollback()
                return ("err", exc.code)
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                return ("err", type(exc).__name__)
            finally:
                s.close()

        results = _run_parallel(
            [
                lambda: decide_worker(a_id, a_version),
                lambda: decide_worker(b_id, b_version),
            ]
        )
        # Обе команды нацелены на РАЗНЫЕ QualityDecision: обе успешны — проигравшая
        # по времени становится SUPERSEDED автоматически (ADR-027 §G), исключений нет.
        assert [r[0] for r in results] == ["ok", "ok"], results

        db.expire_all()
        final_a = db.get(QualityDecision, a_id)
        final_b = db.get(QualityDecision, b_id)
        statuses = sorted([final_a.status, final_b.status])
        assert statuses == [qdw.QD_DECIDED, qdw.QD_SUPERSEDED], (
            final_a.status,
            final_b.status,
        )
        decided, superseded = (
            (final_a, final_b)
            if final_a.status == qdw.QD_DECIDED
            else (final_b, final_a)
        )
        assert decided.supersedes_quality_decision_id == superseded.id

    def test_concurrent_decide_same_decision_twice(self, db: Session):
        ctx = DefectCtx(db, "Qc2")
        joint = ctx.new_joint("J-QD-C2")
        rev = _effective_revision(ctx, joint)
        svc = QualityDecisionService(db)
        decision = _create_under_review(svc, ctx, joint, rev)
        decision_id, version = decision.id, decision.version
        otk_id = ctx.otk.id
        db.commit()

        def decide_worker(tag: str):
            s = SessionLocal()
            try:
                result = QualityDecisionService(s).decide(
                    decision_id,
                    expected_version=version,
                    decision_result=qdw.QD_RESULT_ACCEPTED,
                    actor_worker_id=otk_id,
                )
                return ("ok", str(result.id))
            except DomainError as exc:
                s.rollback()
                return ("err", exc.code)
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                return ("err", type(exc).__name__)
            finally:
                s.close()

        results = _run_parallel(
            [lambda: decide_worker("A"), lambda: decide_worker("B")]
        )
        codes = [r[0] for r in results]
        assert codes.count("ok") == 1, results
        assert codes.count("err") == 1, results
        err_code = [r[1] for r in results if r[0] == "err"][0]
        assert err_code in (
            qdw.QD_TERMINAL_IMMUTABLE,
            qdw.QD_VERSION_CONFLICT,
        ), results

        db.expire_all()
        final = db.get(QualityDecision, decision_id)
        assert final.status == qdw.QD_DECIDED
