from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from typing import Protocol

from app.readiness import MetricInput, calculate_readiness


class ManagementStatus(StrEnum):
    READY = "READY"
    READY_WITH_LIMITATIONS = "READY_WITH_LIMITATIONS"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    BLOCKED = "BLOCKED"
    NOT_CONFIRMED = "NOT_CONFIRMED"


@dataclass(frozen=True, slots=True)
class ProjectModule:
    code: str
    name: str
    stage: int
    metrics: tuple[MetricInput, ...]
    next_action: str


@dataclass(frozen=True, slots=True)
class ManagementAssessment:
    module_code: str
    status: ManagementStatus
    reason: str
    author: str
    version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ModuleSummary:
    code: str
    name: str
    stage: int
    technical_percent: Decimal
    metrics_complete: bool
    management_status: ManagementStatus
    next_action: str


@dataclass(frozen=True, slots=True)
class DashboardView:
    overall_percent: Decimal
    modules: tuple[ModuleSummary, ...]
    generated_at: datetime
    data_status: str = "DEMO"


class InMemoryAssessmentRepository:
    def __init__(self) -> None:
        self._items: dict[str, list[ManagementAssessment]] = {}
        self._lock = Lock()

    def append(
        self,
        module_code: str,
        status: ManagementStatus,
        reason: str,
        author: str,
    ) -> ManagementAssessment:
        with self._lock:
            items = self._items.setdefault(module_code, [])
            assessment = ManagementAssessment(
                module_code=module_code,
                status=status,
                reason=reason,
                author=author,
                version=len(items) + 1,
                created_at=datetime.now(UTC),
            )
            items.append(assessment)
            return assessment

    def history(self, module_code: str) -> tuple[ManagementAssessment, ...]:
        return tuple(self._items.get(module_code, ()))

    def latest(self, module_code: str) -> ManagementAssessment | None:
        items = self._items.get(module_code, ())
        return items[-1] if items else None


class AssessmentRepository(Protocol):
    def append(
        self,
        module_code: str,
        status: ManagementStatus,
        reason: str,
        author: str,
    ) -> ManagementAssessment: ...
    def history(self, module_code: str) -> tuple[ManagementAssessment, ...]: ...
    def latest(self, module_code: str) -> ManagementAssessment | None: ...


class DashboardService:
    def __init__(
        self,
        modules: list[ProjectModule],
        assessments: AssessmentRepository,
    ) -> None:
        self._modules = tuple(sorted(modules, key=lambda item: item.stage))
        self._module_codes = {module.code for module in modules}
        self._assessments = assessments

    def get_dashboard(self) -> DashboardView:
        summaries: list[ModuleSummary] = []
        for module in self._modules:
            readiness = calculate_readiness(list(module.metrics))
            assessment = self._assessments.latest(module.code)
            summaries.append(
                ModuleSummary(
                    code=module.code,
                    name=module.name,
                    stage=module.stage,
                    technical_percent=readiness.percent,
                    metrics_complete=readiness.is_complete,
                    management_status=(
                        assessment.status
                        if assessment
                        else ManagementStatus.NOT_CONFIRMED
                    ),
                    next_action=module.next_action,
                )
            )

        overall = (
            sum((item.technical_percent for item in summaries), Decimal("0"))
            / len(summaries)
            if summaries
            else Decimal("0")
        ).quantize(Decimal("0.01"))
        return DashboardView(
            overall_percent=overall,
            modules=tuple(summaries),
            generated_at=datetime.now(UTC),
        )

    def record_assessment(
        self,
        module_code: str,
        status: ManagementStatus,
        reason: str,
        author: str,
    ) -> ManagementAssessment:
        if module_code not in self._module_codes:
            raise KeyError(module_code)
        return self._assessments.append(
            module_code=module_code,
            status=status,
            reason=reason,
            author=author,
        )
