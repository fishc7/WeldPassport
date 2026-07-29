"""Репозиторий DefectDisposition (Task 9D-4A-3/9D-4A-4).

Только persistence/query: чтение/запись disposition и append-only events.
Без доменной политики, RBAC и HTTP — они в сервисе/policy. Commit — в сервисе.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.quality.defect_disposition_models import (
    DefectDisposition,
    DefectDispositionEvent,
)
from app.quality.defect_disposition_workflow import DISPOSITION_OPEN_STATUSES
from app.quality.defect_models import DefectRoot


class DefectDispositionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, disposition_id: UUID) -> DefectDisposition | None:
        return self.db.get(DefectDisposition, disposition_id)

    def get_by_id_for_update(
        self, disposition_id: UUID
    ) -> DefectDisposition | None:
        """Блокирует строку disposition (SELECT … FOR UPDATE) для сериализации transition."""
        return (
            self.db.query(DefectDisposition)
            .filter(DefectDisposition.id == disposition_id)
            .with_for_update()
            .first()
        )

    def get_root(self, root_id: UUID) -> DefectRoot | None:
        return self.db.get(DefectRoot, root_id)

    def lock_root_for_update(self, root_id: UUID) -> DefectRoot | None:
        """Блокирует строку `defect_roots` (SELECT … FOR UPDATE), Task 9D-4A-4.

        Нужна для `supersede`: операция создаёт вторую строку disposition в той же
        цепочке, поэтому блокировки только старой disposition (`get_by_id_for_update`)
        недостаточно — сериализуем на уровне владельца цепочки (по прецеденту
        `DefectRepository.lock_root_for_update`).
        """
        return (
            self.db.query(DefectRoot)
            .filter(DefectRoot.id == root_id)
            .with_for_update()
            .first()
        )

    def find_open_for_root(self, root_id: UUID) -> DefectDisposition | None:
        return (
            self.db.execute(
                select(DefectDisposition).where(
                    DefectDisposition.defect_root_id == root_id,
                    DefectDisposition.status.in_(tuple(DISPOSITION_OPEN_STATUSES)),
                )
            )
            .scalars()
            .first()
        )

    def add(self, disposition: DefectDisposition) -> DefectDisposition:
        self.db.add(disposition)
        self.db.flush()
        return disposition

    def append_event(self, event: DefectDispositionEvent) -> DefectDispositionEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(
        self, disposition_id: UUID
    ) -> list[DefectDispositionEvent]:
        return list(
            self.db.execute(
                select(DefectDispositionEvent)
                .where(
                    DefectDispositionEvent.defect_disposition_id == disposition_id
                )
                .order_by(DefectDispositionEvent.created_at)
            )
            .scalars()
            .all()
        )

    def save(self) -> None:
        self.db.commit()
