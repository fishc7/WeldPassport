from __future__ import annotations

from app.hr.models import Worker
from app.identity.constants import (
    ACTOR_WORKER_INACTIVE,
    ACTOR_WORKER_REQUIRED,
    PASSWORD_CHANGE_REQUIRED,
)
from app.identity.domain import AuthenticatedActor
from app.shared.errors import DomainError


class HrActorPort:
    """HR-owned adapter exposing only worker activity, never the ORM entity."""

    def __init__(self, db) -> None:
        self.db = db

    def require_active_worker(self, worker_id: int) -> None:
        worker = self.db.get(Worker, worker_id)
        if worker is None or worker.employment_status != "active":
            raise DomainError(
                403,
                ACTOR_WORKER_INACTIVE,
                "Связанный работник неактивен",
            )

    def require_business_actor(self, actor: AuthenticatedActor) -> int:
        if actor.must_change_password:
            raise DomainError(
                403,
                PASSWORD_CHANGE_REQUIRED,
                "Перед работой необходимо сменить пароль",
            )
        if actor.worker_id is None:
            raise DomainError(
                403,
                ACTOR_WORKER_REQUIRED,
                "Учётная запись не связана с работником",
            )
        self.require_active_worker(actor.worker_id)
        return actor.worker_id


__all__ = ["HrActorPort"]
