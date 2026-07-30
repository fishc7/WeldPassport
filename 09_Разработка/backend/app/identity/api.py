from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.identity.domain import AuthenticatedActor, IssuedSession
from app.identity.repository import IdentityRepository
from app.identity.schemas import (
    AuthenticatedActorResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutAllResponse,
    OperationResponse,
)
from app.identity.services import IdentityService
from app.shared.auth import get_authenticated_actor
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.errors import DomainError


router = APIRouter(prefix="/auth", tags=["authentication"])

_SESSION_COOKIE = "wp_session"
_CSRF_COOKIE = "wp_csrf"
_CSRF_HEADER = "X-CSRF-Token"
_COOKIE_MAX_AGE = 12 * 60 * 60


def _service(db: Session) -> IdentityService:
    return IdentityService(IdentityRepository(db))


def _actor_response(actor: AuthenticatedActor) -> AuthenticatedActorResponse:
    return AuthenticatedActorResponse(
        account_id=actor.account_id,
        worker_id=actor.worker_id,
        authenticated_at=actor.authenticated_at,
        auth_method=actor.auth_method,
        must_change_password=actor.must_change_password,
    )


def _login_response(issued: IssuedSession) -> LoginResponse:
    return LoginResponse(
        **_actor_response(issued.actor).model_dump(),
        idle_expires_at=issued.idle_expires_at,
        absolute_expires_at=issued.absolute_expires_at,
    )


def _set_auth_cookies(response: Response, issued: IssuedSession) -> None:
    response.set_cookie(
        _SESSION_COOKIE,
        issued.session_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
        max_age=_COOKIE_MAX_AGE,
    )
    response.set_cookie(
        _CSRF_COOKIE,
        issued.csrf_token,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
        max_age=_COOKIE_MAX_AGE,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(_SESSION_COOKIE, path="/")
    response.delete_cookie(_CSRF_COOKIE, path="/")


def _csrf(request: Request) -> str:
    return request.headers.get(_CSRF_HEADER, "")


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    try:
        issued = _service(db).login(
            payload.login,
            payload.password,
            datetime.now(UTC),
        )
    except DomainError:
        db.commit()
        raise
    db.commit()
    _set_auth_cookies(response, issued)
    return _login_response(issued)


@router.get("/me", response_model=AuthenticatedActorResponse)
def me(
    actor: AuthenticatedActor = Depends(get_authenticated_actor),
) -> AuthenticatedActorResponse:
    return _actor_response(actor)


@router.post("/logout", response_model=OperationResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> OperationResponse:
    _service(db).logout(
        request.cookies.get(_SESSION_COOKIE, ""),
        _csrf(request),
        datetime.now(UTC),
    )
    db.commit()
    _clear_auth_cookies(response)
    return OperationResponse(status="ok")


@router.post("/logout-all", response_model=LogoutAllResponse)
def logout_all(
    request: Request,
    response: Response,
    actor: AuthenticatedActor = Depends(get_authenticated_actor),
    db: Session = Depends(get_db),
) -> LogoutAllResponse:
    count = _service(db).logout_all(actor, _csrf(request), datetime.now(UTC))
    db.commit()
    _clear_auth_cookies(response)
    return LogoutAllResponse(revoked_sessions=count)


@router.post("/change-password", response_model=OperationResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    actor: AuthenticatedActor = Depends(get_authenticated_actor),
    db: Session = Depends(get_db),
) -> OperationResponse:
    _service(db).change_password(
        actor,
        payload.current_password,
        payload.new_password,
        _csrf(request),
        datetime.now(UTC),
    )
    db.commit()
    _clear_auth_cookies(response)
    return OperationResponse(status="ok")
