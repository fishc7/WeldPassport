from decimal import Decimal

from fastapi.testclient import TestClient

from app.dashboard import DashboardService, InMemoryAssessmentRepository, ProjectModule
from app.main import create_app
from app.readiness import MetricInput


def client() -> TestClient:
    service = DashboardService(
        modules=[
            ProjectModule(
                code="engineering",
                name="Engineering",
                stage=3,
                metrics=(MetricInput(code="features", value=Decimal("0.74"), weight=100),),
                next_action="Завершить Engineering Evaluation",
            )
        ],
        assessments=InMemoryAssessmentRepository(),
    )
    return TestClient(create_app(service))


def test_dashboard_endpoint_returns_explainable_module_state() -> None:
    response = client().get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_percent"] == "74.00"
    assert payload["data_status"] == "DEMO"
    assert payload["modules"][0] == {
        "code": "engineering",
        "name": "Engineering",
        "stage": 3,
        "technical_percent": "74.00",
        "metrics_complete": True,
        "management_status": "NOT_CONFIRMED",
        "next_action": "Завершить Engineering Evaluation",
    }


def test_owner_can_record_assessment_and_dashboard_shows_latest_version() -> None:
    api = client()

    created = api.post(
        "/api/v1/modules/engineering/assessments",
        json={
            "status": "DECISION_REQUIRED",
            "reason": "Требуется решение по форме оценки",
            "author": "Владелец",
        },
    )

    assert created.status_code == 201
    assert created.json()["version"] == 1
    dashboard = api.get("/api/v1/dashboard").json()
    assert dashboard["modules"][0]["management_status"] == "DECISION_REQUIRED"
