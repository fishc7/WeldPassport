from decimal import Decimal

from app.dashboard import (
    DashboardService,
    InMemoryAssessmentRepository,
    ManagementStatus,
    ProjectModule,
)
from app.readiness import MetricInput


def module(code: str, readiness: str) -> ProjectModule:
    return ProjectModule(
        code=code,
        name=code.title(),
        stage=1,
        metrics=(
            MetricInput(
                code="features",
                value=Decimal(readiness) / 100,
                weight=100,
            ),
        ),
        next_action="Продолжить реализацию",
    )


def test_dashboard_aggregates_module_readiness() -> None:
    service = DashboardService(
        modules=[module("hr", "80"), module("engineering", "60")],
        assessments=InMemoryAssessmentRepository(),
    )

    dashboard = service.get_dashboard()

    assert dashboard.overall_percent == Decimal("70.00")
    assert [item.code for item in dashboard.modules] == ["hr", "engineering"]
    assert dashboard.modules[0].technical_percent == Decimal("80.00")
    assert dashboard.modules[0].management_status is ManagementStatus.NOT_CONFIRMED


def test_new_assessment_creates_version_without_overwriting_history() -> None:
    repository = InMemoryAssessmentRepository()
    service = DashboardService(
        modules=[module("engineering", "60")],
        assessments=repository,
    )

    first = service.record_assessment(
        module_code="engineering",
        status=ManagementStatus.DECISION_REQUIRED,
        reason="Нужно утвердить модель оценки",
        author="Владелец",
    )
    second = service.record_assessment(
        module_code="engineering",
        status=ManagementStatus.READY_WITH_LIMITATIONS,
        reason="Модель утверждена, UI ещё не подключён",
        author="Владелец",
    )

    assert first.version == 1
    assert second.version == 2
    assert len(repository.history("engineering")) == 2
    assert service.get_dashboard().modules[0].management_status is ManagementStatus.READY_WITH_LIMITATIONS


def test_repository_allocates_assessment_versions_atomically() -> None:
    repository = InMemoryAssessmentRepository()

    first = repository.append(
        module_code="engineering",
        status=ManagementStatus.DECISION_REQUIRED,
        reason="Первое решение",
        author="Владелец",
    )
    second = repository.append(
        module_code="engineering",
        status=ManagementStatus.READY,
        reason="Решение принято",
        author="Владелец",
    )

    assert (first.version, second.version) == (1, 2)
