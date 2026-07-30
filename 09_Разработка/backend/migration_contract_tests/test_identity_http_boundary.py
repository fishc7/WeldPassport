from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.identity.domain import (
    AuthenticatedActor,
    IssuedSession,
    validate_auth_configuration,
)
from app.shared.runtime_profile import RuntimeContractError


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_identity_http_001_production_auth_has_no_trusted_header() -> None:
    source = (BACKEND_DIR / "app" / "shared" / "auth.py").read_text(
        encoding="utf-8"
    )

    assert "X-User-Id" not in source
    assert "Header(" not in source
    assert "get_authenticated_actor" in source


def test_identity_http_002_test_header_is_isolated() -> None:
    support = BACKEND_DIR / "tests" / "auth_support.py"
    assert support.is_file()
    source = support.read_text(encoding="utf-8")

    assert 'alias="X-User-Id"' in source
    assert "test_current_user_id" in source


def test_identity_http_003_router_is_canonical() -> None:
    from app.shared.application_factory import CANONICAL_ROUTER_SPECS

    assert ("app.identity.api", "router", "/api/v1") in CANONICAL_ROUTER_SPECS


def test_identity_http_004_cookie_configuration_fails_closed() -> None:
    with pytest.raises(RuntimeContractError) as exc_info:
        validate_auth_configuration(
            deployment_environment="production",
            cookie_secure=False,
        )

    assert exc_info.value.code == "AUTH-CONFIG-UNSAFE"
    validate_auth_configuration(
        deployment_environment="development",
        cookie_secure=False,
    )


def test_identity_http_005_auth_routes_and_cookie_policy_are_explicit() -> None:
    api_path = BACKEND_DIR / "app" / "identity" / "api.py"
    assert api_path.is_file()
    source = api_path.read_text(encoding="utf-8")
    from app.identity.api import router

    assert {route.path for route in router.routes} == {
        "/auth/login",
        "/auth/me",
        "/auth/logout",
        "/auth/logout-all",
        "/auth/change-password",
    }
    assert 'httponly=True' in source
    assert 'samesite="lax"' in source
    assert "auth_cookie_secure" in source


def test_identity_http_006_login_sets_hardened_cookies(monkeypatch) -> None:
    from app.identity import api
    from app.shared.db import get_db

    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    issued = IssuedSession(
        actor=AuthenticatedActor(
            account_id=uuid4(),
            session_id=uuid4(),
            worker_id=17,
            authenticated_at=now,
            auth_method="LOCAL_PASSWORD",
            must_change_password=False,
        ),
        session_token="raw-session",
        csrf_token="raw-csrf",
        idle_expires_at=now + timedelta(minutes=30),
        absolute_expires_at=now + timedelta(hours=12),
    )

    class FakeDb:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    class FakeService:
        def login(self, login, password, request_time):
            assert login == "operator"
            assert password == "correct-password"
            assert request_time.tzinfo is UTC
            return issued

    db = FakeDb()
    monkeypatch.setattr(api, "_service", lambda _db: FakeService())
    application = FastAPI()
    application.include_router(api.router, prefix="/api/v1")
    application.dependency_overrides[get_db] = lambda: db

    response = TestClient(application).post(
        "/api/v1/auth/login",
        json={"login": "operator", "password": "correct-password"},
    )

    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any(
        "wp_session=raw-session" in item
        and "HttpOnly" in item
        and "Secure" in item
        and "SameSite=lax" in item
        for item in cookies
    )
    assert any(
        "wp_csrf=raw-csrf" in item
        and "HttpOnly" not in item
        and "Secure" in item
        and "SameSite=lax" in item
        for item in cookies
    )
    assert db.commits == 1
