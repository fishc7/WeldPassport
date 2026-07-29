"""Pydantic-схемы HTTP-слоя технической модели Defect (Task 9D-3C-1; ADR-022, Spec 9D-3C).

Продолжение канона Tasks 9A–9D-2 (`quality_finding_schemas`, `engineering_evaluation_schemas`,
`execution_schemas`): вход с `extra="forbid"` (служебные/контекстные поля → 422); команды
жизненного цикла несут обязательный `expected_version` (optimistic locking); актор — из
`X-User-Id`, не из тела. Числовые характеристики — `Decimal` (колонки `Numeric`), количество —
`int` (`Integer`). Enum — `Literal`-типы из `defect_workflow`; собственные Enum-классы не вводятся.

Границы схем (Spec 9D-3C §5/§7): здесь только транспорт и формат. Доменные проверки
(CONFIRMED_DEFECT-происхождение, Joint-инвариант, lifecycle-переходы, supersede, version-checks,
RBAC, обязательность полей для ACTIVE, активность справочников) выполняет `DefectService` (9D-3B);
в схемах они не дублируются.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
)

from app.quality.defect_workflow import DefectIndicationLocation, DefectStatus


# ── Технические поля ревизии (Spec §6.1; ровно dw.DEFECT_TECHNICAL_FIELDS) ────────


class DefectFieldsInput(BaseModel):
    """Технические характеристики §5 (23 поля). Все опциональны и nullable (в `DRAFT`);
    обязательность/immutability на активацию проверяет сервис (9D-3B), не схема.

    Контекст/служебные/аудит-поля здесь отсутствуют и отклоняются `extra="forbid"` → 422:
    `id`, `defect_root_id`, `joint_id`, `engineering_evaluation_id`, `defect_no`, `revision_no`,
    `status`, `version`, `supersedes_defect_id`, actor-/timestamp-поля, `cancellation_reason`.
    Нормализация значений (trim → NULL, нормализация градусов) — в сервисе, не в схеме.
    """

    model_config = ConfigDict(extra="forbid")

    # Классификация
    defect_type_id: UUID | None = None
    location_type_id: UUID | None = None
    indication_location: DefectIndicationLocation | None = None

    # Ориентация / поверхность / сторона
    orientation: str | None = None
    surface: str | None = None
    joint_side: str | None = None

    # Положение
    axial_position_mm: Decimal | None = None
    circumferential_position_deg: Decimal | None = None

    # Измерения (положительные при NOT NULL — проверяет сервис/БД)
    length_mm: Decimal | None = None
    width_mm: Decimal | None = None
    height_mm: Decimal | None = None
    depth_mm: Decimal | None = None
    affected_area_mm2: Decimal | None = None
    quantity: int | None = None

    # Нормативная ссылка (раздельные поля; без standard_reference)
    standard_document: str | None = None
    standard_revision: str | None = None
    standard_clause: str | None = None
    acceptance_level: str | None = None
    normative_category_code: str | None = None

    # Пояснительный текст (не заменяет структуру, правило 1)
    technical_description: str | None = None
    location_description: str | None = None
    evaluation_note: str | None = None
    technical_note: str | None = None


# ── Вход: создание / редактирование ──────────────────────────────────────────────


class DefectCreateRequest(DefectFieldsInput):
    """Тело `POST /quality/defects`. Контекст (`joint_id`, `engineering_evaluation_id`) задаётся
    явно; `activate` выбирает конструктор сервиса (`create_draft` / `create_active`, Spec §8).
    Технические поля наследуются от `DefectFieldsInput`. `extra="forbid"`; актор — из `X-User-Id`.
    """

    joint_id: UUID
    engineering_evaluation_id: UUID
    activate: bool = False


class DefectUpdateRequest(DefectFieldsInput):
    """PATCH DRAFT-ревизии: partial-набор технических полей + обязательный `expected_version`.
    Правка ACTIVE/вне DRAFT запрещена сервисом (`DEFECT_ACTIVE_IMMUTABLE`/invalid transition).
    """

    expected_version: int
    reason: str | None = None


# ── Вход: команды жизненного цикла ───────────────────────────────────────────────


class DefectActivateCommand(BaseModel):
    """Активация DRAFT → ACTIVE (Spec §7). Только optimistic locking."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


class DefectSupersedeCommand(DefectFieldsInput):
    """Supersede-time (ADR-022 D-3B-S01): ACTIVE → SUPERSEDED + новая DRAFT-ревизия. Тело несёт
    partial patch поверх снимка предыдущей ACTIVE + обязательный `expected_version` (Spec §9).
    """

    expected_version: int
    reason: str | None = None


class DefectCancelCommand(BaseModel):
    """Отмена ревизии (DRAFT/ACTIVE → CANCELLED). Причина обязательна и не пуста."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Причина отмены обязательна и не может быть пустой")
        return trimmed


# ── Выход: ревизия дефекта ────────────────────────────────────────────────────────


class DefectRead(BaseModel):
    """DTO чтения ревизии Defect. `defect_no` не включается — он принадлежит `DefectRoot`,
    а не ревизии (Spec §6.4). `standard_reference_display` — производное read-поле (parent §10),
    собирается из раздельных `standard_*`, не персистится.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    defect_root_id: UUID
    revision_no: int
    supersedes_defect_id: UUID | None
    status: DefectStatus

    # Классификация
    defect_type_id: UUID | None
    location_type_id: UUID | None
    indication_location: DefectIndicationLocation | None

    # Ориентация / поверхность / сторона
    orientation: str | None
    surface: str | None
    joint_side: str | None

    # Положение
    axial_position_mm: Decimal | None
    circumferential_position_deg: Decimal | None

    # Измерения
    length_mm: Decimal | None
    width_mm: Decimal | None
    height_mm: Decimal | None
    depth_mm: Decimal | None
    affected_area_mm2: Decimal | None
    quantity: int | None

    # Нормативная ссылка (раздельные поля)
    standard_document: str | None
    standard_revision: str | None
    standard_clause: str | None
    acceptance_level: str | None
    normative_category_code: str | None

    # Пояснительный текст
    technical_description: str | None
    location_description: str | None
    evaluation_note: str | None
    technical_note: str | None

    # Lifecycle actor/time
    activated_by_worker_id: int | None
    activated_at: datetime | None
    superseded_by_worker_id: int | None
    superseded_at: datetime | None
    cancelled_by_worker_id: int | None
    cancelled_at: datetime | None
    cancellation_reason: str | None

    # Аудит и optimistic locking
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def standard_reference_display(self) -> str | None:
        """Производная нормативная ссылка «document revision, clause» (parent §7.8/§10).

        Собирается из раздельных полей с корректным сокращением при отсутствии частей.
        Домен допускает `revision`/`clause` только при заданном `standard_document`, поэтому
        без документа результат — None. Значение не персистится (правило 8).
        """
        if not self.standard_document:
            return None
        result = self.standard_document
        if self.standard_revision:
            result += f" {self.standard_revision}"
        if self.standard_clause:
            result += f", {self.standard_clause}"
        return result


class DefectEventRead(BaseModel):
    """Событие append-only-журнала Defect. Атрибут модели — `event_metadata`; в ответе — `metadata`."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    defect_root_id: UUID
    defect_id: UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_worker_id: int
    actor_role: str | None
    reason: str | None
    metadata: dict | None = Field(default=None, validation_alias="event_metadata")
    correlation_id: UUID | None
    defect_version: int | None
    created_at: datetime


# ── Выход: справочники (read-only) ────────────────────────────────────────────────


class DefectTypeRead(BaseModel):
    """Справочник типов дефектов (system-managed read-only, ADR-022 §5)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    category: str | None
    is_active: bool

    requires_description: bool
    requires_length: bool
    requires_width: bool
    requires_height: bool
    requires_depth: bool
    requires_area: bool
    requires_quantity: bool
    requires_known_indication_location: bool


class DefectLocationTypeRead(BaseModel):
    """Справочник расположений индикации (system-managed read-only, ADR-022 §5)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
