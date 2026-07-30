from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import APIRouter

from app.shared.application_factory import (
    CanonicalRouterBinding,
    RuntimeDependencies,
    create_app,
)
from app.shared.runtime_profile import (
    RuntimeConfiguration,
    RuntimeContractError,
    RuntimeProfile,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _router(path: str) -> APIRouter:
    router = APIRouter()

    @router.get(path)
    def endpoint() -> dict[str, bool]:
        return {"ok": True}

    return router


def _dependencies(
    events: list[str],
    *,
    canonical_failure: bool = False,
    legacy_failure: bool = False,
) -> RuntimeDependencies:
    def load_canonical():
        return (CanonicalRouterBinding(_router("/canonical"), "/api/v1"),)

    def canonical_preflight() -> None:
        events.append("canonical_marker")
        if canonical_failure:
            raise RuntimeContractError(
                "CANONICAL-MARKER-MISMATCH",
                "test marker failure",
            )

    def bind_schema(schema: str) -> str:
        assert schema == "legacy_fixture"
        events.append("bind_legacy_schema")
        return schema

    def legacy_preflight(schema: str) -> None:
        assert schema == "legacy_fixture"
        events.append("legacy_contract")
        if legacy_failure:
            raise RuntimeContractError(
                "LEGACY-CONTRACT-MISMATCH",
                "test legacy failure",
            )

    def load_workforce() -> APIRouter:
        events.append("load_workforce_router")
        return _router("/workers")

    return RuntimeDependencies(
        load_canonical_routers=load_canonical,
        run_canonical_preflight=canonical_preflight,
        bind_legacy_schema=bind_schema,
        run_legacy_preflight=legacy_preflight,
        load_workforce_router=load_workforce,
    )


def _run_lifespan(app) -> None:
    async def run() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.runtime_ready is True

    asyncio.run(run())


def test_application_factory_001_canonical_is_fail_closed_until_lifespan() -> None:
    events: list[str] = []
    app = create_app(
        RuntimeConfiguration(RuntimeProfile.CANONICAL, None),
        dependencies=_dependencies(events),
    )

    with pytest.raises(RuntimeContractError) as exc_info:
        app.openapi()
    assert exc_info.value.code == "RUNTIME-STARTUP-INCOMPLETE"

    async def run() -> None:
        async with app.router.lifespan_context(app):
            assert events == ["canonical_marker"]
            assert app.state.runtime_ready is True
            schema = app.openapi()
            assert "/api/v1/canonical" in schema["paths"]
            assert "/api/v1/workers" not in schema["paths"]

    asyncio.run(run())
    assert app.state.runtime_ready is False


def test_application_factory_002_canonical_failure_never_becomes_ready() -> None:
    events: list[str] = []
    app = create_app(
        RuntimeConfiguration(RuntimeProfile.CANONICAL, None),
        dependencies=_dependencies(events, canonical_failure=True),
    )

    with pytest.raises(RuntimeContractError):
        _run_lifespan(app)

    assert events == ["canonical_marker"]
    assert app.state.runtime_ready is False


def test_application_factory_003_legacy_order_and_attachment_are_exact() -> None:
    events: list[str] = []
    app = create_app(
        RuntimeConfiguration(
            RuntimeProfile.LEGACY_COMPATIBILITY,
            "legacy_fixture",
        ),
        dependencies=_dependencies(events),
    )

    async def run() -> None:
        async with app.router.lifespan_context(app):
            events.append("runtime_ready")
            assert "/api/v1/workers" in app.openapi()["paths"]

    asyncio.run(run())
    assert events == [
        "canonical_marker",
        "bind_legacy_schema",
        "legacy_contract",
        "load_workforce_router",
        "runtime_ready",
    ]


def test_application_factory_004_legacy_failure_never_loads_router() -> None:
    events: list[str] = []
    app = create_app(
        RuntimeConfiguration(
            RuntimeProfile.LEGACY_COMPATIBILITY,
            "legacy_fixture",
        ),
        dependencies=_dependencies(events, legacy_failure=True),
    )

    with pytest.raises(RuntimeContractError):
        _run_lifespan(app)

    assert events == [
        "canonical_marker",
        "bind_legacy_schema",
        "legacy_contract",
    ]
    assert all(route.path != "/api/v1/workers" for route in app.routes)
    assert app.state.runtime_ready is False


def test_application_factory_005_repeated_lifespan_does_not_duplicate_routes() -> None:
    events: list[str] = []
    app = create_app(
        RuntimeConfiguration(
            RuntimeProfile.LEGACY_COMPATIBILITY,
            "legacy_fixture",
        ),
        dependencies=_dependencies(events),
    )

    _run_lifespan(app)
    first_count = sum(route.path == "/api/v1/workers" for route in app.routes)
    _run_lifespan(app)
    second_count = sum(route.path == "/api/v1/workers" for route in app.routes)

    assert first_count == second_count == 1
    assert events.count("canonical_marker") == 2
    assert events.count("legacy_contract") == 2
    assert events.count("load_workforce_router") == 1


def test_application_factory_006_canonical_main_imports_no_workforce_modules() -> None:
    code = """
import sys
import app.main
loaded = sorted(name for name in sys.modules if name.startswith("app.workforce"))
assert loaded == [], loaded
assert all(route.path != "/api/v1/workers" for route in app.main.app.routes)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
