from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.dashboard import (
    DashboardService,
    InMemoryAssessmentRepository,
    ManagementAssessment,
    ManagementStatus,
    ProjectModule,
)
from app.readiness import MetricInput


class ModuleSummaryResponse(BaseModel):
    code: str
    name: str
    stage: int
    technical_percent: Decimal
    metrics_complete: bool
    management_status: ManagementStatus
    next_action: str


class DashboardResponse(BaseModel):
    overall_percent: Decimal
    modules: list[ModuleSummaryResponse]
    generated_at: datetime
    data_status: str


class AssessmentRequest(BaseModel):
    status: ManagementStatus
    reason: str = Field(min_length=3, max_length=1000)
    author: str = Field(min_length=2, max_length=200)


class AssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    module_code: str
    status: ManagementStatus
    reason: str
    author: str
    version: int
    created_at: datetime


def create_app(service: DashboardService) -> FastAPI:
    api = FastAPI(
        title="WeldPassport Project Control Center",
        version="0.1.0",
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/api/v1/dashboard", response_model=DashboardResponse)
    def dashboard() -> DashboardResponse:
        view = service.get_dashboard()
        return DashboardResponse(
            overall_percent=view.overall_percent,
            modules=[
                ModuleSummaryResponse.model_validate(item, from_attributes=True)
                for item in view.modules
            ],
            generated_at=view.generated_at,
            data_status=view.data_status,
        )

    @api.post(
        "/api/v1/modules/{module_code}/assessments",
        response_model=AssessmentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_assessment(
        module_code: str,
        request: AssessmentRequest,
    ) -> ManagementAssessment:
        try:
            return service.record_assessment(
                module_code=module_code,
                status=request.status,
                reason=request.reason,
                author=request.author,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Модуль не найден") from exc

    return api


def _module(code: str, name: str, stage: int, percent: str, next_action: str) -> ProjectModule:
    return ProjectModule(
        code=code,
        name=name,
        stage=stage,
        metrics=(
            MetricInput(
                code="features",
                value=Decimal(percent) / 100,
                weight=100,
            ),
        ),
        next_action=next_action,
    )


default_service = DashboardService(
    modules=[
        _module("hr", "Приём и допуск", 1, "100", "Поддерживать актуальность данных"),
        _module("projects", "Проекты", 2, "92", "Завершить проверку связей"),
        _module("engineering", "Engineering", 3, "74", "Завершить Engineering Evaluation"),
        _module("preparation", "Подготовка производства", 4, "38", "Уточнить состав операций"),
        _module("welding", "Фактическая сварка", 5, "61", "Закрыть сценарии подтверждения"),
        _module("quality", "Контроль качества", 6, "55", "Продолжить Task 9D"),
        _module("closure", "Закрытие стыка", 7, "12", "Утвердить критерии закрытия"),
    ],
    assessments=InMemoryAssessmentRepository(),
)

app = create_app(default_service)
