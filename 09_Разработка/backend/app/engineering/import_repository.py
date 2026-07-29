"""Доступ к данным контура импорта (Task 8E).

Слой repository: только запросы/persist, без бизнес-правил. Разрешение имён для
сопоставления (project_code/line_no/isometric_no/revision_code/welder_stamp_code)
переиспользует существующие репозитории (ProjectRepo, EngineeringRepo, WeldingRepo)
— параллельных реализаций нет.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.engineering.import_matching import JointCandidate
from app.engineering.import_models import (
    ImportApplyAttempt,
    ImportApplyGroupResult,
    ImportGroup,
    ImportIdempotencyKey,
    ImportParseAttempt,
    ImportProvenance,
    ImportResolution,
    ImportRow,
    ImportRowChange,
    ImportSession,
    ImportStatusEvent,
)
from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    Joint,
    WeldOperation,
)
from app.projects.models import Line
from app.welding.models import Welder

_ALIVE_JOINT_STATUSES = ("CANCELLED", "SUPERSEDED")


class ImportRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── ImportSession ─────────────────────────────────────────────────────────
    def add_session(self, session: ImportSession) -> ImportSession:
        self.db.add(session)
        self.db.flush()
        return session

    def get_session(self, session_id: UUID) -> ImportSession | None:
        return (
            self.db.query(ImportSession)
            .filter(ImportSession.id == session_id)
            .first()
        )

    def get_session_for_update(self, session_id: UUID) -> ImportSession | None:
        return (
            self.db.query(ImportSession)
            .filter(ImportSession.id == session_id)
            .with_for_update()
            .first()
        )

    def list_sessions(
        self, *, project_id: UUID | None, status: str | None, skip: int, limit: int
    ) -> list[ImportSession]:
        q = self.db.query(ImportSession)
        if project_id is not None:
            q = q.filter(ImportSession.project_id == project_id)
        if status is not None:
            q = q.filter(ImportSession.status == status)
        return (
            q.order_by(ImportSession.uploaded_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def find_session_by_sha(
        self, project_id: UUID, file_sha256: str
    ) -> ImportSession | None:
        return (
            self.db.query(ImportSession)
            .filter(
                ImportSession.project_id == project_id,
                ImportSession.file_sha256 == file_sha256,
            )
            .order_by(ImportSession.uploaded_at.asc())
            .first()
        )

    def save_session(self, session: ImportSession) -> ImportSession:
        self.db.add(session)
        self.db.flush()
        self.db.refresh(session)
        return session

    # ── ImportParseAttempt ────────────────────────────────────────────────────
    def next_parse_attempt_no(self, session_id: UUID) -> int:
        current = (
            self.db.query(func.max(ImportParseAttempt.attempt_no))
            .filter(ImportParseAttempt.import_session_id == session_id)
            .scalar()
        )
        return (current or 0) + 1

    def add_parse_attempt(self, attempt: ImportParseAttempt) -> ImportParseAttempt:
        self.db.add(attempt)
        self.db.flush()
        return attempt

    def list_parse_attempts(self, session_id: UUID) -> list[ImportParseAttempt]:
        return (
            self.db.query(ImportParseAttempt)
            .filter(ImportParseAttempt.import_session_id == session_id)
            .order_by(ImportParseAttempt.attempt_no.asc())
            .all()
        )

    def count_rows(self, session_id: UUID) -> int:
        return (
            self.db.query(func.count(ImportRow.id))
            .filter(ImportRow.import_session_id == session_id)
            .scalar()
            or 0
        )

    # ── ImportRow ─────────────────────────────────────────────────────────────
    def add_row(self, row: ImportRow) -> ImportRow:
        self.db.add(row)
        self.db.flush()
        return row

    def get_row(self, row_id: UUID) -> ImportRow | None:
        return self.db.query(ImportRow).filter(ImportRow.id == row_id).first()

    def get_row_for_update(self, row_id: UUID) -> ImportRow | None:
        return (
            self.db.query(ImportRow)
            .filter(ImportRow.id == row_id)
            .with_for_update()
            .first()
        )

    def list_rows(
        self,
        session_id: UUID,
        *,
        status: str | None = None,
        group_id: UUID | None = None,
        only_conflicts: bool = False,
    ) -> list[ImportRow]:
        q = self.db.query(ImportRow).filter(
            ImportRow.import_session_id == session_id
        )
        if status is not None:
            q = q.filter(ImportRow.status == status)
        if group_id is not None:
            q = q.filter(ImportRow.import_group_id == group_id)
        if only_conflicts:
            q = q.filter(
                ImportRow.status.in_(
                    ["MATCH_CONFLICT", "DUPLICATE", "PENDING_RESOLUTION",
                     "VALIDATION_ERROR"]
                )
            )
        return q.order_by(ImportRow.row_number.asc()).all()

    def rows_by_group(self, group_id: UUID) -> list[ImportRow]:
        return (
            self.db.query(ImportRow)
            .filter(ImportRow.import_group_id == group_id)
            .order_by(ImportRow.row_number.asc())
            .all()
        )

    def rows_by_group_for_update(self, group_id: UUID) -> list[ImportRow]:
        return (
            self.db.query(ImportRow)
            .filter(ImportRow.import_group_id == group_id)
            .order_by(ImportRow.row_number.asc())
            .with_for_update()
            .all()
        )

    def save_row(self, row: ImportRow) -> ImportRow:
        self.db.add(row)
        self.db.flush()
        return row

    # ── ImportRowChange ───────────────────────────────────────────────────────
    def add_row_change(self, change: ImportRowChange) -> ImportRowChange:
        self.db.add(change)
        self.db.flush()
        return change

    def list_row_changes(self, row_id: UUID) -> list[ImportRowChange]:
        return (
            self.db.query(ImportRowChange)
            .filter(ImportRowChange.import_row_id == row_id)
            .order_by(ImportRowChange.changed_at.asc())
            .all()
        )

    # ── ImportResolution ──────────────────────────────────────────────────────
    def add_resolution(self, resolution: ImportResolution) -> ImportResolution:
        self.db.add(resolution)
        self.db.flush()
        return resolution

    def active_resolution(self, row_id: UUID) -> ImportResolution | None:
        return (
            self.db.query(ImportResolution)
            .filter(
                ImportResolution.import_row_id == row_id,
                ImportResolution.is_superseded.is_(False),
            )
            .first()
        )

    def list_resolutions(self, row_id: UUID) -> list[ImportResolution]:
        return (
            self.db.query(ImportResolution)
            .filter(ImportResolution.import_row_id == row_id)
            .order_by(ImportResolution.resolved_at.asc())
            .all()
        )

    # ── ImportGroup ───────────────────────────────────────────────────────────
    def add_group(self, group: ImportGroup) -> ImportGroup:
        self.db.add(group)
        self.db.flush()
        return group

    def get_group(self, group_id: UUID) -> ImportGroup | None:
        return self.db.query(ImportGroup).filter(ImportGroup.id == group_id).first()

    def get_group_for_update(self, group_id: UUID) -> ImportGroup | None:
        return (
            self.db.query(ImportGroup)
            .filter(ImportGroup.id == group_id)
            .with_for_update()
            .first()
        )

    def list_groups(
        self, session_id: UUID, *, status: str | None = None
    ) -> list[ImportGroup]:
        q = self.db.query(ImportGroup).filter(
            ImportGroup.import_session_id == session_id
        )
        if status is not None:
            q = q.filter(ImportGroup.status == status)
        return q.order_by(ImportGroup.group_order.asc()).all()

    def list_groups_for_update(self, session_id: UUID) -> list[ImportGroup]:
        return (
            self.db.query(ImportGroup)
            .filter(ImportGroup.import_session_id == session_id)
            .order_by(ImportGroup.group_order.asc())
            .with_for_update()
            .all()
        )

    def next_group_order(self, session_id: UUID) -> int:
        current = (
            self.db.query(func.max(ImportGroup.group_order))
            .filter(ImportGroup.import_session_id == session_id)
            .scalar()
        )
        return (current or 0) + 1

    def save_group(self, group: ImportGroup) -> ImportGroup:
        self.db.add(group)
        self.db.flush()
        return group

    # ── ImportApplyAttempt / result ───────────────────────────────────────────
    def next_apply_attempt_no(self, session_id: UUID) -> int:
        current = (
            self.db.query(func.max(ImportApplyAttempt.attempt_no))
            .filter(ImportApplyAttempt.import_session_id == session_id)
            .scalar()
        )
        return (current or 0) + 1

    def add_apply_attempt(self, attempt: ImportApplyAttempt) -> ImportApplyAttempt:
        self.db.add(attempt)
        self.db.flush()
        return attempt

    def list_apply_attempts(self, session_id: UUID) -> list[ImportApplyAttempt]:
        return (
            self.db.query(ImportApplyAttempt)
            .filter(ImportApplyAttempt.import_session_id == session_id)
            .order_by(ImportApplyAttempt.attempt_no.asc())
            .all()
        )

    def add_apply_group_result(
        self, result: ImportApplyGroupResult
    ) -> ImportApplyGroupResult:
        self.db.add(result)
        self.db.flush()
        return result

    # ── ImportProvenance ──────────────────────────────────────────────────────
    def add_provenance(self, provenance: ImportProvenance) -> ImportProvenance:
        self.db.add(provenance)
        self.db.flush()
        return provenance

    def list_provenance(self, session_id: UUID) -> list[ImportProvenance]:
        return (
            self.db.query(ImportProvenance)
            .filter(ImportProvenance.import_session_id == session_id)
            .order_by(ImportProvenance.created_at.asc())
            .all()
        )

    # ── ImportStatusEvent ─────────────────────────────────────────────────────
    def add_status_event(self, event: ImportStatusEvent) -> ImportStatusEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_status_events(
        self,
        session_id: UUID,
        *,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
    ) -> list[ImportStatusEvent]:
        q = self.db.query(ImportStatusEvent).filter(
            ImportStatusEvent.import_session_id == session_id
        )
        if entity_type is not None:
            q = q.filter(ImportStatusEvent.entity_type == entity_type)
        if entity_id is not None:
            q = q.filter(ImportStatusEvent.entity_id == entity_id)
        return q.order_by(ImportStatusEvent.created_at.asc()).all()

    # ── ImportIdempotencyKey ──────────────────────────────────────────────────
    def get_idempotency(
        self,
        *,
        scope: str,
        command_type: str,
        idempotency_key: str,
        session_id: UUID | None,
        user_id: int,
    ) -> ImportIdempotencyKey | None:
        q = self.db.query(ImportIdempotencyKey).filter(
            ImportIdempotencyKey.scope == scope,
            ImportIdempotencyKey.command_type == command_type,
            ImportIdempotencyKey.idempotency_key == idempotency_key,
        )
        if scope == "SESSION":
            q = q.filter(ImportIdempotencyKey.import_session_id == session_id)
        else:
            q = q.filter(ImportIdempotencyKey.user_id == user_id)
        return q.first()

    def add_idempotency(
        self, entry: ImportIdempotencyKey
    ) -> ImportIdempotencyKey:
        self.db.add(entry)
        self.db.flush()
        return entry

    # ── Сопоставление: кандидаты Joint и существующие операции ────────────────
    def joint_candidates(
        self, project_id: UUID, joint_no_normalized: str
    ) -> list[JointCandidate]:
        rows = (
            self.db.query(
                Joint.id,
                Line.line_no,
                EngineeringDocument.document_no,
                DocumentRevision.revision_code,
            )
            .join(Line, Line.id == Joint.line_id)
            .join(
                DocumentRevision,
                DocumentRevision.id == Joint.current_document_revision_id,
            )
            .join(
                EngineeringDocument,
                EngineeringDocument.id
                == DocumentRevision.engineering_document_id,
            )
            .filter(
                Joint.project_id == project_id,
                Joint.joint_no_normalized == joint_no_normalized,
                Joint.status.notin_(_ALIVE_JOINT_STATUSES),
            )
            .all()
        )
        return [
            JointCandidate(
                joint_id=jid,
                line_code=line_no,
                isometric_no=doc_no,
                revision_code=rev_code,
            )
            for jid, line_no, doc_no, rev_code in rows
        ]

    def completed_operations_for_joint(
        self, joint_id: UUID
    ) -> list[WeldOperation]:
        """Действующие завершённые операции Joint (для проверки дублей, §8)."""
        return (
            self.db.query(WeldOperation)
            .filter(
                WeldOperation.joint_id == joint_id,
                WeldOperation.lifecycle_status == "COMPLETED",
                WeldOperation.superseded_by_operation_id.is_(None),
            )
            .all()
        )

    def resolve_welder_by_stamp(self, stamp_code: str) -> Welder | None:
        return (
            self.db.query(Welder)
            .filter(Welder.stamp_code == stamp_code)
            .first()
        )
