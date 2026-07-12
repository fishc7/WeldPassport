from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.engineering.joint_workflow import (
    APPROVAL_STATES,
    BLOCK_SCOPES,
    BLOCK_TYPES,
    DECISION_METHODS,
    DOCUMENT_ROLES,
    EVENT_TYPES,
    JOINT_STATUSES,
    LINK_STATUSES,
    PENDING_REASONS,
    REVISION_ROLES,
)
from app.engineering.weld_operation_workflow import (
    WELD_OPERATION_STATUSES,
    WELD_STAGES,
)
from app.projects.models import PROJECT_SCHEMA
from app.shared.db import Base
from app.welding.models import WELDING_SCHEMA

ENGINEERING_SCHEMA = "engineering"

# Допустимые типы инженерного документа (Session 004, ADR-009). Технические коды
# в верхнем регистре; предметные названия — на стороне UI.
DOCUMENT_TYPES = ("ISOMETRIC", "DRAWING", "WELD_MAP", "OTHER")

# Жизненный цикл документа/ревизии. Переходы оформляются командами, а не правкой
# поля status (история вместо перезаписи).
ENGINEERING_STATUSES = ("DRAFT", "APPROVED", "CANCELLED", "SUPERSEDED")

_DOCUMENT_TYPE_CHECK = "document_type IN (" + ", ".join(
    f"'{code}'" for code in DOCUMENT_TYPES
) + ")"

_STATUS_CHECK = "status IN (" + ", ".join(
    f"'{code}'" for code in ENGINEERING_STATUSES
) + ")"

# ── Joint (Task 5A ядро + Task 5B жизненный цикл, ADR-010 / ADR-011) ──────────
# Перечисления классификации стыка берутся строго из ADR-010. Статусы жизненного
# цикла и словари согласований — из joint_workflow (канон ADR-011, §1-5).
GEOMETRY_TYPES = ("BUTT", "FILLET", "TEE", "LAP", "SLOT", "OTHER")
WELD_JOINT_TYPES = ("BW", "SW", "FW", "OTHER")
CONNECTION_CODES = ("C", "U", "T", "N", "P", "OTHER")


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


# Минимальный набор инженерных полей, определяющих готовность стыка к сварке
# (Б-4, ADR-009/010). Все перечисленные поля должны быть заполнены; иначе стык
# не готов, а недостающие имена возвращаются в missing_welding_requirements.
# Единый источник: сервис считает по нему `missing`, репозиторий строит по нему
# SQL-фильтр `ready_for_welding`. Материалы намеренно не входят в минимальный
# набор (выбор материала/WPS — отдельный домен, planned_wps_id без FK).
REQUIRED_WELDING_FIELDS = (
    "geometry_type",
    "weld_joint_type",
    "dn_1",
    "thickness_1",
    "required_root_method",
    "required_fill_method",
    "required_cap_method",
)

_JOINT_STATUS_CHECK = _in_check("status", JOINT_STATUSES)
# NULL допустим (классификация может быть не заполнена в DRAFT); проверяем только
# заполненные значения.
_GEOMETRY_TYPE_CHECK = (
    "geometry_type IS NULL OR " + _in_check("geometry_type", GEOMETRY_TYPES)
)
_WELD_JOINT_TYPE_CHECK = (
    "weld_joint_type IS NULL OR " + _in_check("weld_joint_type", WELD_JOINT_TYPES)
)
_CONNECTION_CODE_CHECK = (
    "connection_code IS NULL OR " + _in_check("connection_code", CONNECTION_CODES)
)
# Если задана хотя бы одна координата положения на чертеже — обязателен
# coordinate_system (ADR-010).
_COORDINATE_SYSTEM_CHECK = (
    "(position_x IS NULL AND position_y IS NULL) OR coordinate_system IS NOT NULL"
)

# ── Инварианты согласований Joint (Task 5B, §5 ADR-011 / §2 задания) ──────────
_PTO_STATUS_CHECK = _in_check("pto_status", APPROVAL_STATES)
_OGS_STATUS_CHECK = _in_check("ogs_status", APPROVAL_STATES)
_PTO_PENDING_REASON_CHECK = (
    "pto_pending_reason IS NULL OR " + _in_check("pto_pending_reason", PENDING_REASONS)
)
_OGS_PENDING_REASON_CHECK = (
    "ogs_pending_reason IS NULL OR " + _in_check("ogs_pending_reason", PENDING_REASONS)
)
_PTO_DECISION_METHOD_CHECK = (
    "pto_decision_method IS NULL OR "
    + _in_check("pto_decision_method", DECISION_METHODS)
)
_OGS_DECISION_METHOD_CHECK = (
    "ogs_decision_method IS NULL OR "
    + _in_check("ogs_decision_method", DECISION_METHODS)
)
# NOT_SUBMITTED → способ решения обязан быть NULL (§2 задания); принятое решение
# (APPROVED/REJECTED/REVOKED) → способ обязателен.
_PTO_METHOD_CONSISTENCY_CHECK = (
    "(pto_status = 'NOT_SUBMITTED' AND pto_decision_method IS NULL) "
    "OR (pto_status = 'PENDING') "
    "OR (pto_status IN ('APPROVED', 'REJECTED', 'REVOKED') "
    "AND pto_decision_method IS NOT NULL)"
)
_OGS_METHOD_CONSISTENCY_CHECK = (
    "(ogs_status = 'NOT_SUBMITTED' AND ogs_decision_method IS NULL) "
    "OR (ogs_status = 'PENDING') "
    "OR (ogs_status IN ('APPROVED', 'REJECTED', 'REVOKED') "
    "AND ogs_decision_method IS NOT NULL)"
)
# Причина ожидания хранится только пока сторона в PENDING (§5 ADR-011).
_PTO_PENDING_PRESENCE_CHECK = (
    "(pto_status = 'PENDING') OR (pto_pending_reason IS NULL)"
)
_OGS_PENDING_PRESENCE_CHECK = (
    "(ogs_status = 'PENDING') OR (ogs_pending_reason IS NULL)"
)
# Joint не может заменить сам себя (§6 задания, §30 ADR-011).
_NO_SELF_SUPERSEDE_CHECK = (
    "superseded_by_joint_id IS NULL OR superseded_by_joint_id <> id"
)


class EngineeringDocument(Base):
    """Инженерный документ (изометрия, чертёж, карта сварки) в проекте.

    Владелец — ПТО (role_code `PTO_ENGINEER`). `line_id` необязателен: документ
    может относиться к проекту в целом либо к конкретной линии. FK на проект и
    линию — ondelete RESTRICT: документ не теряется молча при удалении контекста.
    """

    __tablename__ = "engineering_documents"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "document_no",
            name="uq_engineering_documents_project_document_no",
        ),
        CheckConstraint(
            "length(trim(document_no)) > 0",
            name="ck_engineering_documents_document_no_not_empty",
        ),
        CheckConstraint(
            _DOCUMENT_TYPE_CHECK,
            name="ck_engineering_documents_document_type",
        ),
        CheckConstraint(
            _STATUS_CHECK,
            name="ck_engineering_documents_status",
        ),
        Index("ix_engineering_documents_project_id", "project_id"),
        Index("ix_engineering_documents_line_id", "line_id"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    document_no: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    # created_by / approved_by — hr.workers.id (X-User-Id). FK не добавляем
    # (переходный период; см. ограничения плана Engineering Joints MVP).
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JointSequence(Base):
    """Служебный счётчик system_code по проекту (Task 5A, ADR-010).

    Отдельная последовательность на проект: `<project_code>-JNT-<sequence>`.
    Значение выдаётся атомарно через `INSERT ... ON CONFLICT DO UPDATE ...
    RETURNING` (см. репозиторий), что исключает гонку `MAX()+1`. Номера
    монотонно растут и не переиспользуются. FK на проект не добавляем: строка —
    инфраструктурный счётчик в стиле переходного периода (created_by без FK).
    """

    __tablename__ = "joint_sequences"
    __table_args__ = ({"schema": ENGINEERING_SCHEMA},)

    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True
    )
    last_value: Mapped[int] = mapped_column(Integer, nullable=False)


class Joint(Base):
    """Сварной стык (Task 5A, ADR-010).

    Ядро модели без lifecycle-переходов согласования (Task 5B) и истории снимков
    (Task 6). `line_id` обязателен. `system_code` формируется системой и не
    принимается от пользователя. `joint_no_normalized` — служебная нормализация
    исходного `joint_no` для сравнения дублей. `version` — optimistic locking.
    Физического удаления нет (DELETE-endpoint не создаётся).

    Ссылки на справочники материалов/номенклатуры/WPS — nullable UUID **без FK**
    (Р-4 ADR-010): соответствующие домены ещё не реализованы.
    """

    __tablename__ = "joints"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "system_code",
            name="uq_engineering_joints_project_system_code",
        ),
        CheckConstraint(
            "length(trim(joint_no)) > 0",
            name="ck_engineering_joints_joint_no_not_empty",
        ),
        CheckConstraint(
            "length(trim(joint_no_normalized)) > 0",
            name="ck_engineering_joints_joint_no_normalized_not_empty",
        ),
        CheckConstraint(_JOINT_STATUS_CHECK, name="ck_engineering_joints_status"),
        CheckConstraint(
            "record_version > 0",
            name="ck_engineering_joints_record_version_positive",
        ),
        CheckConstraint(
            "approval_version > 0",
            name="ck_engineering_joints_approval_version_positive",
        ),
        CheckConstraint(
            "workflow_version > 0",
            name="ck_engineering_joints_workflow_version_positive",
        ),
        CheckConstraint(_PTO_STATUS_CHECK, name="ck_engineering_joints_pto_status"),
        CheckConstraint(_OGS_STATUS_CHECK, name="ck_engineering_joints_ogs_status"),
        CheckConstraint(
            _PTO_PENDING_REASON_CHECK,
            name="ck_engineering_joints_pto_pending_reason",
        ),
        CheckConstraint(
            _OGS_PENDING_REASON_CHECK,
            name="ck_engineering_joints_ogs_pending_reason",
        ),
        CheckConstraint(
            _PTO_DECISION_METHOD_CHECK,
            name="ck_engineering_joints_pto_decision_method",
        ),
        CheckConstraint(
            _OGS_DECISION_METHOD_CHECK,
            name="ck_engineering_joints_ogs_decision_method",
        ),
        CheckConstraint(
            _PTO_METHOD_CONSISTENCY_CHECK,
            name="ck_engineering_joints_pto_method_consistency",
        ),
        CheckConstraint(
            _OGS_METHOD_CONSISTENCY_CHECK,
            name="ck_engineering_joints_ogs_method_consistency",
        ),
        CheckConstraint(
            _PTO_PENDING_PRESENCE_CHECK,
            name="ck_engineering_joints_pto_pending_presence",
        ),
        CheckConstraint(
            _OGS_PENDING_PRESENCE_CHECK,
            name="ck_engineering_joints_ogs_pending_presence",
        ),
        CheckConstraint(
            _NO_SELF_SUPERSEDE_CHECK,
            name="ck_engineering_joints_no_self_supersede",
        ),
        CheckConstraint(
            _GEOMETRY_TYPE_CHECK, name="ck_engineering_joints_geometry_type"
        ),
        CheckConstraint(
            _WELD_JOINT_TYPE_CHECK, name="ck_engineering_joints_weld_joint_type"
        ),
        CheckConstraint(
            _CONNECTION_CODE_CHECK, name="ck_engineering_joints_connection_code"
        ),
        CheckConstraint(
            _COORDINATE_SYSTEM_CHECK,
            name="ck_engineering_joints_coordinate_system",
        ),
        CheckConstraint(
            "dn_1 IS NULL OR dn_1 > 0", name="ck_engineering_joints_dn_1_positive"
        ),
        CheckConstraint(
            "dn_2 IS NULL OR dn_2 > 0", name="ck_engineering_joints_dn_2_positive"
        ),
        CheckConstraint(
            "thickness_1 IS NULL OR thickness_1 > 0",
            name="ck_engineering_joints_thickness_1_positive",
        ),
        CheckConstraint(
            "thickness_2 IS NULL OR thickness_2 > 0",
            name="ck_engineering_joints_thickness_2_positive",
        ),
        # Дубль номера в пределах текущей ревизии документа запрещён среди «живых»
        # стыков. Partial-предикат заранее исключает будущие статусы
        # CANCELLED/SUPERSEDED (Task 5B), чтобы снятый стык не блокировал замену с
        # тем же номером. В Task 5A все стыки DRAFT, поэтому индекс работает как
        # обычный UNIQUE. В Task 6 бизнес-ключ переезжает в partial unique index
        # на joint_document_revisions (WHERE link_status='ACTIVE'); этот индекс
        # тогда снимается отдельной миграцией.
        Index(
            "uq_engineering_joints_revision_joint_no",
            "project_id",
            "current_document_revision_id",
            "joint_no_normalized",
            unique=True,
            postgresql_where="status NOT IN ('CANCELLED', 'SUPERSEDED')",
        ),
        Index("ix_engineering_joints_project_id", "project_id"),
        Index("ix_engineering_joints_line_id", "line_id"),
        Index(
            "ix_engineering_joints_current_revision_id",
            "current_document_revision_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_document_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.document_revisions.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    current_document_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.document_revisions.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    system_code: Mapped[str] = mapped_column(String(64), nullable=False)
    joint_no: Mapped[str] = mapped_column(String(100), nullable=False)
    joint_no_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )

    # ── Три версии (Task 5B, §15 ADR-011 / §3 задания) ────────────────────────
    # record_version — concurrency (прежняя version Task 5A, переименование);
    # approval_version — значимые инженерные/технологические данные (к ней
    # привязаны согласования); workflow_version — переходы/блокировки/замена.
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    approval_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    workflow_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )

    # ── Согласование ПТО (§5-7 ADR-011) ───────────────────────────────────────
    pto_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="NOT_SUBMITTED"
    )
    pto_pending_reason: Mapped[str | None] = mapped_column(String(30))
    pto_decision_method: Mapped[str | None] = mapped_column(String(20))
    # approval_version, к которой относится текущее решение ПТО (§2 задания, §36
    # ADR-011). Устаревшее (не равное approval_version) не активирует Joint.
    pto_approval_version: Mapped[int | None] = mapped_column(Integer)
    pto_decided_by: Mapped[int | None] = mapped_column(Integer)
    pto_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pto_comment: Mapped[str | None] = mapped_column(Text)

    # ── Согласование ОГС (§5, §8-9 ADR-011) ───────────────────────────────────
    ogs_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="NOT_SUBMITTED"
    )
    ogs_pending_reason: Mapped[str | None] = mapped_column(String(30))
    ogs_decision_method: Mapped[str | None] = mapped_column(String(20))
    ogs_approval_version: Mapped[int | None] = mapped_column(Integer)
    ogs_decided_by: Mapped[int | None] = mapped_column(Integer)
    ogs_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ogs_comment: Mapped[str | None] = mapped_column(Text)

    # ── Отправка на согласование / отмена / замена ────────────────────────────
    submitted_by: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[int | None] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Самоссылка замены: source → successor (§6 задания). predecessor/successor
    # определяются по этой связи; исходный Joint не удаляется.
    superseded_by_joint_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
    )
    superseded_by: Mapped[int | None] = mapped_column(Integer)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Инженерные поля по сторонам соединения (1/2).
    dn_1: Mapped[Decimal | None] = mapped_column(Numeric)
    dn_2: Mapped[Decimal | None] = mapped_column(Numeric)
    thickness_1: Mapped[Decimal | None] = mapped_column(Numeric)
    thickness_2: Mapped[Decimal | None] = mapped_column(Numeric)
    material_id_1: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    material_id_2: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    material_text_1: Mapped[str | None] = mapped_column(String(255))
    material_text_2: Mapped[str | None] = mapped_column(String(255))
    component_type_1: Mapped[str | None] = mapped_column(String(50))
    component_type_2: Mapped[str | None] = mapped_column(String(50))
    component_item_id_1: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    component_item_id_2: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    component_text_1: Mapped[str | None] = mapped_column(String(255))
    component_text_2: Mapped[str | None] = mapped_column(String(255))

    # Классификация.
    geometry_type: Mapped[str | None] = mapped_column(String(20))
    weld_joint_type: Mapped[str | None] = mapped_column(String(20))
    connection_code: Mapped[str | None] = mapped_column(String(20))

    # Проектные способы сварки (коды/обозначения; без FK на WPS — Р-4).
    required_root_method: Mapped[str | None] = mapped_column(String(50))
    required_fill_method: Mapped[str | None] = mapped_column(String(50))
    required_cap_method: Mapped[str | None] = mapped_column(String(50))
    planned_wps_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))

    # Термообработка.
    heat_treatment_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    heat_treatment_type: Mapped[str | None] = mapped_column(String(50))
    heat_treatment_note: Mapped[str | None] = mapped_column(Text)

    # Положение на чертеже.
    sheet_no: Mapped[str | None] = mapped_column(String(50))
    drawing_zone: Mapped[str | None] = mapped_column(String(50))
    position_x: Mapped[Decimal | None] = mapped_column(Numeric)
    position_y: Mapped[Decimal | None] = mapped_column(Numeric)
    coordinate_system: Mapped[str | None] = mapped_column(String(50))
    location_note: Mapped[str | None] = mapped_column(Text)
    document_note: Mapped[str | None] = mapped_column(Text)

    # Аудит. created_by/updated_by — hr.workers.id (без FK, переходный период).
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class JointBulkRequest(Base):
    """Идемпотентная запись успешного массового создания Joint (Task 7, ADR-010).

    Хранит только успешные пакеты (`status = 'COMPLETED'`; неуспешные попытки не
    сохраняются). `response_payload` — полный сохранённый ответ; при идемпотентном
    повторе с тем же `(project_id, idempotency_key)` и `request_hash` возвращается
    как есть, без пересборки из текущего состояния Joint. `idempotency_key` хранится
    после `strip()`, регистр значим; один ключ допустим в разных проектах
    (UNIQUE на пару). Запись не обновляется и не удаляется физически.

    `created_by` — hr.workers.id (актор) без FK, в стиле существующих поля-акторов
    (Р-3 ADR-010: переходный период, FK на hr.workers не добавляется).
    """

    __tablename__ = "joint_bulk_requests"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_engineering_joint_bulk_requests_project_key",
        ),
        CheckConstraint(
            "status = 'COMPLETED'",
            name="ck_engineering_joint_bulk_requests_status",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_engineering_joint_bulk_requests_key_not_empty",
        ),
        Index("ix_engineering_joint_bulk_requests_project_id", "project_id"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{PROJECT_SCHEMA}.projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="COMPLETED"
    )
    response_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentRevision(Base):
    """Ревизия инженерного документа. Scope прав наследуется от документа."""

    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint(
            "engineering_document_id",
            "revision_code",
            name="uq_engineering_document_revisions_doc_revision_code",
        ),
        CheckConstraint(
            "length(trim(revision_code)) > 0",
            name="ck_engineering_document_revisions_revision_code_not_empty",
        ),
        CheckConstraint(
            _STATUS_CHECK,
            name="ck_engineering_document_revisions_status",
        ),
        Index(
            "ix_engineering_document_revisions_document_id",
            "engineering_document_id",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    engineering_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.engineering_documents.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    revision_code: Mapped[str] = mapped_column(String(100), nullable=False)
    issued_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JointBlock(Base):
    """Блокировка Joint (Task 5B, §20 ADR-011).

    Блокировка — отдельная запись, а не статус жизненного цикла: у одного Joint
    может быть несколько активных блокировок, при этом сам Joint остаётся ACTIVE
    (инвариант §41.14). Активная блокировка — `released_at IS NULL`. История
    сохраняется: закрытие проставляет released_*, запись не удаляется.
    """

    __tablename__ = "joint_blocks"
    __table_args__ = (
        CheckConstraint(
            _in_check("block_type", BLOCK_TYPES),
            name="ck_engineering_joint_blocks_type",
        ),
        CheckConstraint(
            _in_check("scope", BLOCK_SCOPES),
            name="ck_engineering_joint_blocks_scope",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_engineering_joint_blocks_reason_not_empty",
        ),
        Index("ix_engineering_joint_blocks_joint_id", "joint_id"),
        # Быстрый поиск активных блокировок Joint.
        Index(
            "ix_engineering_joint_blocks_active",
            "joint_id",
            postgresql_where="released_at IS NULL",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    released_by: Mapped[int | None] = mapped_column(Integer)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(Text)


class JointEvent(Base):
    """Неизменяемое событие истории Joint (Task 5B, §37 ADR-011).

    Append-only: API удаления/редактирования нет. Фиксирует актора, роль, версии,
    способ решения, основание и снимок статусов до/после (§37, §10 задания).
    """

    __tablename__ = "joint_events"
    __table_args__ = (
        CheckConstraint(
            _in_check("event_type", EVENT_TYPES),
            name="ck_engineering_joint_events_type",
        ),
        Index("ix_engineering_joint_events_joint_id", "joint_id"),
        Index("ix_engineering_joint_events_created_at", "created_at"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_role_code: Mapped[str | None] = mapped_column(String(50))
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    previous_pto_status: Mapped[str | None] = mapped_column(String(20))
    new_pto_status: Mapped[str | None] = mapped_column(String(20))
    previous_ogs_status: Mapped[str | None] = mapped_column(String(20))
    new_ogs_status: Mapped[str | None] = mapped_column(String(20))
    record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_method: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Связь Joint ↔ DocumentRevision с неизменяемым снимком (Task 6, ADR-010) ────
# Аннулированная связь остаётся историей: link_status=INVALIDATED требует полного
# аудита аннулирования, ACTIVE — его отсутствия.
_LINK_INVALIDATION_CHECK = (
    "(link_status = 'ACTIVE' AND invalidated_at IS NULL "
    "AND invalidated_by IS NULL AND invalidated_reason IS NULL) "
    "OR (link_status = 'INVALIDATED' AND invalidated_at IS NOT NULL "
    "AND invalidated_by IS NOT NULL "
    "AND length(trim(invalidated_reason)) > 0)"
)


class JointDocumentRevision(Base):
    """Неизменяемая история связи Joint ↔ DocumentRevision (Task 6, ADR-010).

    Каждая связь фиксирует полный снимок основных инженерных параметров стыка на
    момент создания. Снимок хранится в колонках с префиксом `snapshot_`, явно
    отделяющим историческую копию от текущих полей Joint, и неизменяем (PATCH
    снимка нет); меняется только статус связи при аннулировании (`invalidated_*`,
    `updated_*`). Физического удаления нет. Инварианты:

    * при создании Joint автоматически существует ORIGIN-связь (revision_role=ORIGIN,
      document_role=PRIMARY, link_status=ACTIVE);
    * ровно одна активная PRIMARY-связь на Joint, соответствующая
      `current_document_revision_id` (partial unique index);
    * `snapshot_joint_no_normalized` уникален среди ACTIVE-связей внутри одной
      DocumentRevision (partial unique index);
    * ровно одна ORIGIN-связь на Joint независимо от link_status (partial unique);
    * аннулированная связь остаётся в истории и не может стать текущей PRIMARY.
    """

    __tablename__ = "joint_document_revisions"
    __table_args__ = (
        CheckConstraint(
            _in_check("revision_role", REVISION_ROLES),
            name="ck_engineering_joint_doc_revisions_revision_role",
        ),
        CheckConstraint(
            _in_check("document_role", DOCUMENT_ROLES),
            name="ck_engineering_joint_doc_revisions_document_role",
        ),
        CheckConstraint(
            _in_check("link_status", LINK_STATUSES),
            name="ck_engineering_joint_doc_revisions_link_status",
        ),
        CheckConstraint(
            "length(trim(snapshot_joint_no_normalized)) > 0",
            name="ck_engineering_joint_doc_revisions_snapshot_norm_not_empty",
        ),
        # Аннулирование непротиворечиво: INVALIDATED ⇒ заполнены invalidated_*,
        # ACTIVE ⇒ они пусты.
        CheckConstraint(
            _LINK_INVALIDATION_CHECK,
            name="ck_engineering_joint_doc_revisions_invalidation",
        ),
        Index(
            "ix_engineering_joint_doc_revisions_joint_id", "joint_id"
        ),
        Index(
            "ix_engineering_joint_doc_revisions_revision_id",
            "document_revision_id",
        ),
        # snapshot_joint_no_normalized уникален среди ACTIVE-связей одной ревизии.
        Index(
            "uq_engineering_joint_doc_revisions_active_no",
            "document_revision_id",
            "snapshot_joint_no_normalized",
            unique=True,
            postgresql_where="link_status = 'ACTIVE'",
        ),
        # Ровно одна активная PRIMARY-связь на Joint (= current_document_revision_id).
        Index(
            "uq_engineering_joint_doc_revisions_active_primary",
            "joint_id",
            unique=True,
            postgresql_where="link_status = 'ACTIVE' AND document_role = 'PRIMARY'",
        ),
        # Ровно одна ORIGIN-связь на Joint (не зависит от link_status: ORIGIN неизменна).
        Index(
            "uq_engineering_joint_doc_revisions_origin",
            "joint_id",
            unique=True,
            postgresql_where="revision_role = 'ORIGIN'",
        ),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            f"{ENGINEERING_SCHEMA}.document_revisions.id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    revision_role: Mapped[str] = mapped_column(String(20), nullable=False)
    document_role: Mapped[str] = mapped_column(String(20), nullable=False)
    link_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )

    # ── Аудит и аннулирование ─────────────────────────────────────────────────
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # updated_* меняются ТОЛЬКО при аннулировании (§ Task 6): снимок неизменяем.
    updated_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    invalidated_by: Mapped[int | None] = mapped_column(Integer)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Неизменяемый снимок основных параметров Joint на момент связи ─────────
    # Идентичность (joint_no + нормализация + line_id) и все инженерные поля Task 5A.
    # snapshot_line_id обязателен: смена ревизии восстанавливает инженерную привязку.
    snapshot_joint_no: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_joint_no_normalized: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    snapshot_line_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    snapshot_dn_1: Mapped[Decimal | None] = mapped_column(Numeric)
    snapshot_dn_2: Mapped[Decimal | None] = mapped_column(Numeric)
    snapshot_thickness_1: Mapped[Decimal | None] = mapped_column(Numeric)
    snapshot_thickness_2: Mapped[Decimal | None] = mapped_column(Numeric)
    snapshot_material_id_1: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    snapshot_material_id_2: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    snapshot_material_text_1: Mapped[str | None] = mapped_column(String(255))
    snapshot_material_text_2: Mapped[str | None] = mapped_column(String(255))
    snapshot_component_type_1: Mapped[str | None] = mapped_column(String(50))
    snapshot_component_type_2: Mapped[str | None] = mapped_column(String(50))
    snapshot_component_item_id_1: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    snapshot_component_item_id_2: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    snapshot_component_text_1: Mapped[str | None] = mapped_column(String(255))
    snapshot_component_text_2: Mapped[str | None] = mapped_column(String(255))
    snapshot_geometry_type: Mapped[str | None] = mapped_column(String(20))
    snapshot_weld_joint_type: Mapped[str | None] = mapped_column(String(20))
    snapshot_connection_code: Mapped[str | None] = mapped_column(String(20))
    snapshot_required_root_method: Mapped[str | None] = mapped_column(String(50))
    snapshot_required_fill_method: Mapped[str | None] = mapped_column(String(50))
    snapshot_required_cap_method: Mapped[str | None] = mapped_column(String(50))
    snapshot_planned_wps_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    snapshot_heat_treatment_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    snapshot_heat_treatment_type: Mapped[str | None] = mapped_column(String(50))
    snapshot_heat_treatment_note: Mapped[str | None] = mapped_column(Text)
    snapshot_sheet_no: Mapped[str | None] = mapped_column(String(50))
    snapshot_drawing_zone: Mapped[str | None] = mapped_column(String(50))
    snapshot_position_x: Mapped[Decimal | None] = mapped_column(Numeric)
    snapshot_position_y: Mapped[Decimal | None] = mapped_column(Numeric)
    snapshot_coordinate_system: Mapped[str | None] = mapped_column(String(50))
    snapshot_location_note: Mapped[str | None] = mapped_column(Text)
    snapshot_document_note: Mapped[str | None] = mapped_column(Text)


# ── WeldOperation (Task 8A, ADR-012 / Session 005) ────────────────────────────
# Неизменяемый после завершения производственный факт: один Joint + один
# фактический сварщик + один классифицированный этап + один фактически применённый
# способ. Согласованные UPPERCASE-словари lifecycle/этапов — в weld_operation_workflow.
_WELD_OP_STATUS_CHECK = _in_check("lifecycle_status", WELD_OPERATION_STATUSES)
_WELD_OP_STAGE_CHECK = _in_check("weld_stage", WELD_STAGES)
# COMPLETED требует автора/времени завершения и фактического сварщика (§8.7, §8.11);
# вне COMPLETED поля завершения пусты (§8.13). Один согласованный CHECK.
_WELD_OP_COMPLETION_CHECK = (
    "(lifecycle_status = 'COMPLETED' AND completed_by IS NOT NULL "
    "AND completed_at IS NOT NULL AND actual_welder_id IS NOT NULL) "
    "OR (lifecycle_status <> 'COMPLETED' AND completed_by IS NULL "
    "AND completed_at IS NULL)"
)
# CANCELLED требует автора/времени/причины отмены (§8.12); вне CANCELLED — пусто (§8.13).
_WELD_OP_CANCELLATION_CHECK = (
    "(lifecycle_status = 'CANCELLED' AND cancelled_by IS NOT NULL "
    "AND cancelled_at IS NOT NULL AND length(trim(cancellation_reason)) > 0) "
    "OR (lifecycle_status <> 'CANCELLED' AND cancelled_by IS NULL "
    "AND cancelled_at IS NULL AND cancellation_reason IS NULL)"
)
# Согласованность интервала времени: при наличии обоих finished_at >= started_at (§8.10).
_WELD_OP_TIME_CHECK = (
    "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at"
)


class WeldOperation(Base):
    """Производственный факт сварки одного этапа одним сварщиком (Task 8A).

    Ядро без квалификационной проверки, WPS-валидации, review ОГС, подтверждения
    сварщика, корректировок и импорта (Tasks 8B–8E не входят). `sequence_no`
    выдаётся системой атомарно (блокировка строки Joint + UNIQUE(joint_id,
    sequence_no)); клиент его не задаёт. `actual_wps_id` — nullable UUID без FK
    (домен WPS ещё не реализован; отсутствие WPS не блокирует Task 8A).
    Организационный снимок (executor_/welder_* company/department) и
    `profile_stamp_snapshot` фиксируются на момент создания и не пересчитываются.
    Завершённая операция (`COMPLETED`) неизменяема; физического удаления нет.
    Ссылки на работников (responsible/created/updated/completed/cancelled_by) —
    hr.workers.id без FK (переходный период, как в Joint).
    """

    __tablename__ = "weld_operations"
    __table_args__ = (
        UniqueConstraint(
            "joint_id",
            "sequence_no",
            name="uq_engineering_weld_operations_joint_sequence",
        ),
        CheckConstraint(
            "sequence_no > 0",
            name="ck_engineering_weld_operations_sequence_positive",
        ),
        CheckConstraint(
            _WELD_OP_STATUS_CHECK,
            name="ck_engineering_weld_operations_lifecycle_status",
        ),
        CheckConstraint(
            _WELD_OP_STAGE_CHECK, name="ck_engineering_weld_operations_weld_stage"
        ),
        CheckConstraint(
            "length(trim(welding_method)) > 0",
            name="ck_engineering_weld_operations_method_not_empty",
        ),
        CheckConstraint(
            "record_version > 0",
            name="ck_engineering_weld_operations_record_version_positive",
        ),
        CheckConstraint(
            _WELD_OP_TIME_CHECK, name="ck_engineering_weld_operations_time_range"
        ),
        CheckConstraint(
            _WELD_OP_COMPLETION_CHECK,
            name="ck_engineering_weld_operations_completion",
        ),
        CheckConstraint(
            _WELD_OP_CANCELLATION_CHECK,
            name="ck_engineering_weld_operations_cancellation",
        ),
        Index("ix_engineering_weld_operations_joint_id", "joint_id"),
        Index(
            "ix_engineering_weld_operations_actual_welder_id", "actual_welder_id"
        ),
        Index(
            "ix_engineering_weld_operations_responsible_worker_id",
            "responsible_worker_id",
        ),
        Index(
            "ix_engineering_weld_operations_lifecycle_status", "lifecycle_status"
        ),
        Index("ix_engineering_weld_operations_performed_on", "performed_on"),
        {"schema": ENGINEERING_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    joint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ENGINEERING_SCHEMA}.joints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )

    # Классификация факта: один этап и один способ на операцию (005-A).
    weld_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    welding_method: Mapped[str] = mapped_column(String(50), nullable=False)

    # Дата/время выполнения. performed_on обязателен; времена — необязательны.
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Фактический сварщик (профиль welding.welders) и клеймо. Введённое клеймо и
    # исторический снимок профильного клейма хранятся раздельно; сравнение —
    # Task 8C, в 8A не выполняется. actual_welder_id nullable в DRAFT, обязателен
    # для завершения (CHECK completion).
    actual_welder_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{WELDING_SCHEMA}.welders.id", ondelete="RESTRICT"),
    )
    entered_stamp_code: Mapped[str | None] = mapped_column(String(100))
    profile_stamp_snapshot: Mapped[str | None] = mapped_column(String(100))

    # Ответственный мастер/прораб (hr.workers.id, роль MASTER/FOREMAN). Автор и
    # ответственный могут различаться (§10.2). FK не добавляем (переходный период).
    responsible_worker_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Аудит и переходы. Все *_by — hr.workers.id без FK.
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_by: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(Integer)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # Исторический организационный снимок на момент создания (§12). Организации/
    # подразделения — hr-идентификаторы (Integer) без FK: снимок неизменен и не
    # пересчитывается. Данные, недоступные из текущей модели, остаются NULL.
    executor_company_id: Mapped[int | None] = mapped_column(Integer)
    executor_department_id: Mapped[int | None] = mapped_column(Integer)
    welder_company_id: Mapped[int | None] = mapped_column(Integer)
    welder_department_id: Mapped[int | None] = mapped_column(Integer)

    # Производственная зона и внешние ссылки (§6.3): без новых справочников —
    # nullable UUID/строки. FK к несуществующим таблицам не добавляем.
    production_area_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    production_area_text: Mapped[str | None] = mapped_column(Text)
    shift_ref: Mapped[str | None] = mapped_column(String(100))
    shift_assignment_ref: Mapped[str | None] = mapped_column(String(100))
    production_report_ref: Mapped[str | None] = mapped_column(String(100))

    # Фактически применённый WPS — nullable UUID без FK (домен WPS не реализован).
    actual_wps_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    welding_position: Mapped[str | None] = mapped_column(String(50))
    shielding_gas: Mapped[str | None] = mapped_column(String(100))
    back_purge: Mapped[bool | None] = mapped_column(Boolean)
    operation_note: Mapped[str | None] = mapped_column(Text)

    # Optimistic locking (как record_version у Joint).
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
