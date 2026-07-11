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
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.projects.models import PROJECT_SCHEMA
from app.shared.db import Base

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

# ── Joint (Task 5A, ADR-010) ──────────────────────────────────────────────────
# Перечисления классификации стыка берутся строго из ADR-010. В рамках Task 5A
# статус ограничен только DRAFT; PENDING_REVIEW/ACTIVE/CANCELLED/SUPERSEDED
# вводятся в Task 5B и здесь недопустимы.
JOINT_STATUSES = ("DRAFT",)
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
        CheckConstraint("version > 0", name="ck_engineering_joints_version_positive"),
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
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )

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
