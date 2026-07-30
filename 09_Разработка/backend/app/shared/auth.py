from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.hr.actor_port import HrActorPort
from app.identity.constants import AUTHENTICATION_REQUIRED
from app.identity.domain import AuthenticatedActor
from app.identity.repository import IdentityRepository
from app.identity.services import IdentityService
from app.shared.db import get_db
from app.shared.errors import DomainError


def get_authenticated_actor(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedActor:
    session_token = request.cookies.get("wp_session")
    if not session_token:
        raise DomainError(
            401,
            AUTHENTICATION_REQUIRED,
            "Требуется аутентификация",
        )
    actor = IdentityService(IdentityRepository(db)).resolve_actor(
        session_token,
        datetime.now(UTC),
    )
    db.commit()
    return actor


def get_current_user_id(
    actor: AuthenticatedActor = Depends(get_authenticated_actor),
    db: Session = Depends(get_db),
) -> int:
    return HrActorPort(db).require_business_actor(actor)
