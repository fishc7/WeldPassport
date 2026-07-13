from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.quality.inspection_workflow import InspectionState, InspectionStatus
from app.quality.method_assignment_workflow import (
    AssignmentStatus,
    InspectionMethodCode,
)


# ── Вход: создание / редактирование (extra=forbid; system-поля запрещены) ──────


class InspectionCreate(BaseModel):
    """Тело создания заявки (§16.1).

    Клиент задаёт только контекст и основание. Служебные поля (status, system_code,
    version, audit, поля подтверждений) в схеме отсутствуют — `extra="forbid"` даёт
    422 при попытке их передать. `idempotency_key` передаётся HTTP-заголовком, не
    телом.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    joint_id: UUID
    external_request_no: str | None = None
    request_reason: str
    notes: str | None = None

    @field_validator("request_reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("request_reason обязателен и не может быть пустым")
        return value


class InspectionUpdate(BaseModel):
    """PATCH DRAFT-заявки (§10.2, §16.4).

    Меняются только external_request_no / request_reason / notes. Immutable-поля и
    любые неизвестные ключи отклоняются (`extra="forbid"`). `expected_version`
    обязателен (optimistic locking, §10.3).
    """

    model_config = ConfigDict(extra="forbid")

    external_request_no: str | None = None
    request_reason: str | None = None
    notes: str | None = None
    expected_version: int

    @field_validator("request_reason")
    @classmethod
    def _reason_not_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("request_reason не может быть пустым")
        return value


# ── Вход: команды жизненного цикла (актор — из X-User-Id, не из тела) ──────────


class ConfirmProductionReadinessCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int


class RequestInspectionCommand(BaseModel):
    """Отправка DRAFT → REQUESTED (§14). `readiness_override_reason` — только для
    главного сварщика и только для обхода отсутствия подтверждения СМР (§14.1)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    readiness_override_reason: str | None = None

    @field_validator("readiness_override_reason")
    @classmethod
    def _override_not_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("readiness_override_reason не может быть пустым")
        return value


class CancelInspectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Причина отмены обязательна и не может быть пустой")
        return value


# ── Готовность к контролю (§12) ───────────────────────────────────────────────


class ReasonItem(BaseModel):
    code: str
    message: str


class InspectionReadinessRead(BaseModel):
    joint_id: UUID
    ready_for_inspection: bool
    blocking_reasons: list[ReasonItem] = Field(default_factory=list)
    warnings: list[ReasonItem] = Field(default_factory=list)
    weld_operation_id: UUID | None = None
    heat_treatment_operation_id: UUID | None = None


# ── Выход: заявка и события ────────────────────────────────────────────────────


class InspectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    joint_id: UUID
    system_code: str
    external_request_no: str | None
    idempotency_key: str | None
    status: InspectionStatus
    request_reason: str
    notes: str | None

    production_ready_confirmed_at: datetime | None
    production_ready_confirmed_by_worker_id: int | None
    ogs_readiness_confirmed_at: datetime | None
    ogs_readiness_confirmed_by_worker_id: int | None
    readiness_override_reason: str | None
    requested_at: datetime | None
    requested_by_worker_id: int | None
    cancelled_at: datetime | None
    cancelled_by_worker_id: int | None
    cancellation_reason: str | None

    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int

    # Вычисляемая readiness (не колонка): заполняется при создании (§16.1) и в
    # ответах команд; в списке не считается.
    readiness: InspectionReadinessRead | None = None


class InspectionListResponse(BaseModel):
    items: list[InspectionRead]
    total: int
    limit: int
    offset: int


class InspectionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    inspection_id: UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_worker_id: int
    reason: str | None
    # Атрибут модели — event_metadata; в ответе — ключ metadata.
    metadata: dict | None = Field(default=None, validation_alias="event_metadata")
    inspection_version: int
    created_at: datetime


# ── Фильтры списка (§16.2) ─────────────────────────────────────────────────────


class InspectionListFilters(BaseModel):
    project_id: UUID | None = None
    joint_id: UUID | None = None
    status: InspectionStatus | None = None
    system_code: str | None = None
    external_request_no: str | None = None
    created_by_worker_id: int | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# Вспомогательный тип для интеграции в Joint (§17).
JointInspectionState = InspectionState


# ── Task 9B: назначение метода контроля и лаборатории ──────────────────────────


class MethodAssignmentCreate(BaseModel):
    """Тело создания назначения (§16). Клиент задаёт метод, лабораторию и
    необязательные примечания. Служебные поля (status, actor, version) в схеме
    отсутствуют — `extra="forbid"` даёт 422 при попытке их передать."""

    model_config = ConfigDict(extra="forbid")

    method_code: InspectionMethodCode
    laboratory_company_id: int
    laboratory_note: str | None = None
    assignment_note: str | None = None


class MethodAssignmentUpdate(BaseModel):
    """PATCH назначения (§11): меняются только нейтральные примечания. Метод,
    лаборатория, статус, actor-поля и дата назначения через PATCH недоступны —
    любые неизвестные ключи отклоняются (`extra="forbid"`). `expected_version`
    обязателен (optimistic locking)."""

    model_config = ConfigDict(extra="forbid")

    laboratory_note: str | None = None
    assignment_note: str | None = None
    expected_version: int


class CancelMethodAssignmentCommand(BaseModel):
    """Отмена назначения (§12). Причина обязательна и не может быть пустой."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Причина отмены обязательна и не может быть пустой")
        return value


class ReplaceMethodAssignmentCommand(BaseModel):
    """Замена назначения (§13). `method_code` можно опустить — тогда метод
    сохраняется; лаборатория и метод проходят повторную проверку. Причина
    обязательна. Замена без фактических изменений отклоняется сервисом."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    method_code: InspectionMethodCode | None = None
    laboratory_company_id: int | None = None
    laboratory_note: str | None = None
    assignment_note: str | None = None
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Причина замены обязательна и не может быть пустой")
        return value


class MethodAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inspection_id: UUID
    method_code: InspectionMethodCode
    laboratory_company_id: int
    status: AssignmentStatus
    laboratory_note: str | None
    assignment_note: str | None
    assigned_by_worker_id: int
    assigned_at: datetime
    cancelled_at: datetime | None
    cancelled_by_worker_id: int | None
    cancellation_reason: str | None
    replaced_by_assignment_id: UUID | None
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int

    # Безопасные вычисляемые данные (§17): имя лаборатории и признак активности.
    laboratory_company_name: str | None = None
    is_active: bool | None = None


class MethodAssignmentListResponse(BaseModel):
    """Список назначений Inspection с вычисляемой сводкой готовности (§14, §16).

    `items` учитывает фильтр запроса (status / active_only). Сводные признаки
    (`has_method_assignments` и далее) всегда считаются по активным назначениям
    независимо от фильтра списка. `ready_for_execution` — ограниченный признак
    (§14): у Inspection есть хотя бы одно активное назначение и у каждого активного
    назначения указана допустимая лаборатория; фактической готовности производства
    или лаборатории он не означает."""

    inspection_id: UUID
    items: list[MethodAssignmentRead]
    has_method_assignments: bool
    active_method_assignment_count: int
    assigned_method_codes: list[str]
    all_assignments_have_laboratory: bool
    ready_for_execution: bool
