"""Immutable role plans and injected operational boundary for TEST-DB-F2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from app.testing.f2_contract import F2Error, F2Role


@dataclass(frozen=True)
class RoleStep:
    name: str
    argv: tuple[str, ...] | None = None
    callable_name: str | None = None


class CommandExecutor(Protocol):
    def run(self, argv: tuple[str, ...]) -> int: ...


class RoleAdapter(Protocol):
    def run(self, role: F2Role) -> Mapping[str, object]: ...


def _alembic(python_executable: str, *arguments: str) -> tuple[str, ...]:
    return (python_executable, "-m", "alembic", *arguments)


def _pytest(python_executable: str, *arguments: str) -> tuple[str, ...]:
    return (python_executable, "-m", "pytest", *arguments)


def build_role_plan(
    role: F2Role,
    python_executable: str,
) -> tuple[RoleStep, ...]:
    if role is F2Role.CANONICAL:
        return (
            RoleStep(
                "canonical_upgrade",
                _alembic(python_executable, "upgrade", "head"),
            ),
            RoleStep(
                "canonical_heads",
                _alembic(python_executable, "heads"),
            ),
            RoleStep(
                "canonical_current",
                _alembic(python_executable, "current"),
            ),
            RoleStep(
                "canonical_check",
                _alembic(python_executable, "check"),
            ),
            RoleStep("canonical_runtime", callable_name="canonical_runtime"),
            RoleStep(
                "application_suite",
                _pytest(python_executable, "tests", "-q"),
            ),
        )
    if role is F2Role.LEGACY_COMPATIBLE:
        return (
            RoleStep(
                "compatible_upgrade",
                _alembic(python_executable, "upgrade", "head"),
            ),
            RoleStep(
                "compatible_check_before",
                _alembic(python_executable, "check"),
            ),
            RoleStep(
                "compatible_fixture",
                callable_name="compatible_fixture",
            ),
            RoleStep(
                "compatible_runtime",
                callable_name="compatible_runtime",
            ),
            RoleStep("compatible_smoke", callable_name="compatible_smoke"),
            RoleStep(
                "compatible_check_after",
                _alembic(python_executable, "check"),
            ),
        )
    return (
        RoleStep(
            "negative_upgrade",
            _alembic(python_executable, "upgrade", "head"),
        ),
        RoleStep("negative_snapshot_before", callable_name="negative_before"),
        RoleStep("negative_fixture", callable_name="negative_fixture"),
        RoleStep(
            "negative_runtime_rejected",
            callable_name="negative_runtime",
        ),
        RoleStep("negative_snapshot_after", callable_name="negative_after"),
    )


@dataclass
class OperationalRoleAdapter:
    executor: CommandExecutor
    handlers: Mapping[str, Callable[[], Mapping[str, object]]]
    python_executable: str

    def run(self, role: F2Role) -> Mapping[str, object]:
        completed: list[str] = []
        results: dict[str, object] = {}
        for step in build_role_plan(role, self.python_executable):
            if step.argv is not None:
                exit_code = self.executor.run(step.argv)
                if exit_code != 0:
                    code = (
                        "TEST-DB-F2-ALEMBIC-FAILED"
                        if step.argv[2] == "alembic"
                        else "TEST-DB-F2-RUNTIME-FAILED"
                    )
                    raise F2Error(code, "TEST-DB-F2 role command failed")
            else:
                handler = self.handlers.get(step.callable_name or "")
                if handler is None:
                    raise F2Error(
                        "TEST-DB-F2-RUNTIME-FAILED",
                        "TEST-DB-F2 role gate is unavailable",
                    )
                result = handler()
                results[step.name] = dict(result)
            completed.append(step.name)
        return {"completed_steps": completed, "gate_results": results}
