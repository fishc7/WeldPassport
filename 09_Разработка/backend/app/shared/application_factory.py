from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import importlib
from typing import cast

from fastapi import APIRouter, FastAPI

from app.identity.domain import validate_auth_configuration
from app.shared.config import settings
from app.shared.runtime_profile import (
    RuntimeConfiguration,
    RuntimeContractError,
    RuntimeProfile,
)


CANONICAL_ROUTER_SPECS = (
    ("app.identity.api", "router", "/api/v1"),
    ("app.hr.api", "router", "/api/v1"),
    ("app.welding.api", "router", "/api/v1"),
    ("app.projects.api", "router", "/api/v1"),
    ("app.engineering.api", "router", "/api/v1"),
    ("app.engineering.heat_treatment_api", "router", "/api/v1"),
    ("app.engineering.import_api", "router", "/api/v1"),
    ("app.quality.api", "router", "/api/v1"),
    ("app.quality.execution_api", "router", "/api/v1"),
    ("app.quality.quality_finding_api", "router", "/api/v1"),
    ("app.quality.quality_decision_api", "router", "/api/v1"),
    ("app.quality.engineering_evaluation_api", "router", "/api/v1"),
    ("app.quality.defect_api", "router", "/api/v1"),
    ("app.quality.defect_disposition_api", "router", "/api/v1"),
)


@dataclass(frozen=True)
class CanonicalRouterBinding:
    router: APIRouter
    prefix: str


@dataclass(frozen=True)
class RuntimeDependencies:
    load_canonical_routers: Callable[
        [], tuple[CanonicalRouterBinding, ...]
    ]
    run_canonical_preflight: Callable[[], None]
    bind_legacy_schema: Callable[[str], str]
    run_legacy_preflight: Callable[[str], None]
    load_workforce_router: Callable[[], APIRouter]


def _load_canonical_routers() -> tuple[CanonicalRouterBinding, ...]:
    return tuple(
        CanonicalRouterBinding(
            router=getattr(importlib.import_module(module_name), attribute),
            prefix=prefix,
        )
        for module_name, attribute, prefix in CANONICAL_ROUTER_SPECS
    )


def _run_canonical_preflight() -> None:
    from app.shared.db import engine
    from app.shared.runtime_marker import (
        resolve_active_alembic_head,
        verify_canonical_marker,
    )

    expected_head = resolve_active_alembic_head()
    with engine.connect() as connection:
        verify_canonical_marker(connection, expected_head)


def _bind_legacy_schema(schema: str) -> str:
    from app.workforce.legacy_orm import bind_legacy_schema

    return bind_legacy_schema(schema)


def _run_legacy_preflight(schema: str) -> None:
    from app.shared.db import engine
    from app.workforce.legacy_preflight import run_legacy_preflight

    with engine.connect() as connection:
        run_legacy_preflight(connection, schema)


def _load_workforce_router() -> APIRouter:
    module = importlib.import_module("app.workforce.api")
    return cast(APIRouter, module.router)


def _default_dependencies() -> RuntimeDependencies:
    return RuntimeDependencies(
        load_canonical_routers=_load_canonical_routers,
        run_canonical_preflight=_run_canonical_preflight,
        bind_legacy_schema=_bind_legacy_schema,
        run_legacy_preflight=_run_legacy_preflight,
        load_workforce_router=_load_workforce_router,
    )


def create_app(
    configuration: RuntimeConfiguration,
    *,
    dependencies: RuntimeDependencies | None = None,
) -> FastAPI:
    deps = _default_dependencies() if dependencies is None else dependencies
    validate_auth_configuration(
        deployment_environment=settings.deployment_environment,
        cookie_secure=settings.auth_cookie_secure,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime_ready = False
        deps.run_canonical_preflight()
        if configuration.profile is RuntimeProfile.LEGACY_COMPATIBILITY:
            schema = cast(str, configuration.legacy_schema)
            deps.bind_legacy_schema(schema)
            deps.run_legacy_preflight(schema)
            if not app.state.workforce_router_attached:
                app.include_router(
                    deps.load_workforce_router(),
                    prefix="/api/v1",
                )
                app.state.workforce_router_attached = True
                app.openapi_schema = None
        app.state.runtime_ready = True
        try:
            yield
        finally:
            app.state.runtime_ready = False

    app = FastAPI(
        title="WeldPassport API",
        version="0.1.0",
        description="API системы управления сварочным производством",
        lifespan=lifespan,
    )
    app.state.runtime_ready = False
    app.state.workforce_router_attached = False

    for binding in deps.load_canonical_routers():
        app.include_router(binding.router, prefix=binding.prefix)

    original_openapi = app.openapi

    def guarded_openapi():
        if app.state.runtime_ready is not True:
            raise RuntimeContractError(
                "RUNTIME-STARTUP-INCOMPLETE",
                "runtime preflight has not completed",
            )
        return original_openapi()

    app.openapi = guarded_openapi
    return app
