"""Pydantic-схемы ядра QualityFinding (Task 9D-1, ADR-019).

Стиль Tasks 9A–9C: вход с `extra="forbid"` (служебные поля запрещены → 422), команды
жизненного цикла с обязательным `expected_version` (optimistic locking), актор — из
server-authenticated actor worker id, не из тела. Инженерная оценка/дефекты/disposition (блоки 9D-2 …) в схемах
ядра отсутствуют.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.quality.quality_finding_workflow import (
    FindingInitialRisk,
    FindingOriginType,
    FindingStatus,
)


# ── Вход: создание / редактирование ─────────────────────────────────────────────


class FindingCreate(BaseModel):
    """Тело создания finding (DRAFT). Клиент задаёт контекст, происхождение, риск,
    наблюдение и необязательные ссылки на источник контроля. Служебные поля (status,
    system_code, version, audit, registered/acknowledged/cancelled) отсутствуют —
    `extra="forbid"` даёт 422 при попытке их передать. Номер выдаётся при регистрации.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    joint_id: UUID
    origin_type: FindingOriginType
    initial_risk: FindingInitialRisk = "UNKNOWN"
    title: str | None = None
    observation: str
    external_no: str | None = None
    external_ref: str | None = None
    inspection_id: UUID | None = None
    method_execution_id: UUID | None = None
    weld_operation_id: UUID | None = None
    source_note: str | None = None

    @field_validator("observation")
    @classmethod
    def _observation_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("observation обязателен и не может быть пустым")
        return value


class FindingUpdate(BaseModel):
    """PATCH DRAFT-finding. Меняются только контентные поля (origin_type, initial_risk,
    title, observation, внешние номера, ссылки на источник). Immutable-поля и любые
    неизвестные ключи отклоняются (`extra="forbid"`). `expected_version` обязателен.
    Редактирование запрещено вне DRAFT (сервис): после регистрации наблюдение
    неизменяемо.
    """

    model_config = ConfigDict(extra="forbid")

    origin_type: FindingOriginType | None = None
    initial_risk: FindingInitialRisk | None = None
    title: str | None = None
    observation: str | None = None
    external_no: str | None = None
    external_ref: str | None = None
    inspection_id: UUID | None = None
    method_execution_id: UUID | None = None
    weld_operation_id: UUID | None = None
    source_note: str | None = None
    expected_version: int

    @field_validator("observation")
    @classmethod
    def _observation_not_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("observation не может быть пустым")
        return value


# ── Вход: команды жизненного цикла ──────────────────────────────────────────────


class RegisterFindingCommand(BaseModel):
    """Регистрация DRAFT → REGISTERED: выдаёт номер, фиксирует наблюдение."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


class AcknowledgeFindingCommand(BaseModel):
    """Подтверждение получения ОГС: REGISTERED → UNDER_EVALUATION."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


class CancelFindingCommand(BaseModel):
    """Отмена ошибочной/дублирующей записи. Причина обязательна и не пуста."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Причина отмены обязательна и не может быть пустой")
        return value


class DeleteFindingCommand(BaseModel):
    """Удаление DRAFT (физическое). `expected_version` обязателен."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


# ── Выход: finding и события ────────────────────────────────────────────────────


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    joint_id: UUID
    system_code: str | None
    external_no: str | None
    external_ref: str | None
    origin_type: FindingOriginType
    initial_risk: FindingInitialRisk
    status: FindingStatus
    title: str | None
    observation: str

    inspection_id: UUID | None
    method_execution_id: UUID | None
    weld_operation_id: UUID | None
    source_note: str | None

    registered_by_worker_id: int | None
    registered_at: datetime | None
    acknowledged_by_worker_id: int | None
    acknowledged_at: datetime | None
    cancelled_by_worker_id: int | None
    cancelled_at: datetime | None
    cancellation_reason: str | None

    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int


class FindingListResponse(BaseModel):
    items: list[FindingRead]
    total: int
    limit: int
    offset: int


class FindingEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    finding_id: UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_worker_id: int
    reason: str | None
    # Атрибут модели — event_metadata; в ответе — ключ metadata.
    metadata: dict | None = Field(default=None, validation_alias="event_metadata")
    finding_version: int
    created_at: datetime


# ── Фильтры списка ──────────────────────────────────────────────────────────────


class FindingListFilters(BaseModel):
    project_id: UUID | None = None
    joint_id: UUID | None = None
    status: FindingStatus | None = None
    origin_type: FindingOriginType | None = None
    initial_risk: FindingInitialRisk | None = None
    system_code: str | None = None
    external_no: str | None = None
    created_by_worker_id: int | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
