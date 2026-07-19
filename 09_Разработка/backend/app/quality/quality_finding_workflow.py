"""Доменная политика жизненного цикла QualityFinding (Task 9D-1, ADR-019).

Продолжение канона Tasks 9A–9C (`inspection_workflow`, `method_assignment_workflow`,
`method_execution_workflow`): только чистые константы и pure-функции без обращения к
БД. Здесь фиксируются статусы finding, канонический справочник происхождения
(`origin_type`), уровни первичного риска (`initial_risk`), типы событий, роли и
машинные коды доменных ошибок.

Границы Task 9D-1 (тёмное ядро QualityFinding):

* `QualityFinding` — зарегистрированный факт для рассмотрения; **не** = Defect,
  **не** = негодность Joint, **не** = решение ОГС (ADR-019, решение 1);
* реализуется базовый lifecycle `DRAFT → REGISTERED → UNDER_EVALUATION` +
  `DRAFT → deleted` + `REGISTERED/UNDER_EVALUATION → CANCELLED`;
* `EngineeringEvaluation`, `FindingDisposition`, `Defect`, `ProductionHold`,
  `FindingLocation/Evidence/Correction/Assignment` в это ядро **не входят** (блоки
  9D-2 … 9D-6). Полный канонический набор статусов фиксируется сразу (как в 9A),
  чтобы будущие блоки не переписывали CHECK; сервис реализует только подмножество.

Формат кодов — UPPERCASE, как во всём backend. Роли берутся из существующего канона
проекта (`inspection_workflow`), новые role_code не вводятся (ADR-019 «новых role_code
не вводится»).
"""

from __future__ import annotations

from typing import Literal

from app.quality import inspection_workflow as iw

# ── Полный жизненный цикл finding (ADR-019; сервис 9D-1 — подмножество) ─────────
# Через API Task 9D-1 достигаются только DRAFT/REGISTERED/UNDER_EVALUATION/CANCELLED.
# Статусы начиная с DISPOSITION_PENDING задаются блоками 9D-2 … 9D-6 и здесь в БД
# разрешены заранее, чтобы не переписывать CHECK.
FINDING_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "REGISTERED",
    "UNDER_EVALUATION",
    "DISPOSITION_PENDING",
    "ACTION_REQUIRED",
    "ACTION_IN_PROGRESS",
    "REINSPECTION_PENDING",
    "CUSTOMER_DECISION_PENDING",
    "READY_FOR_CLOSURE",
    "CLOSED",
    "CANCELLED",
)
FindingStatus = Literal[
    "DRAFT",
    "REGISTERED",
    "UNDER_EVALUATION",
    "DISPOSITION_PENDING",
    "ACTION_REQUIRED",
    "ACTION_IN_PROGRESS",
    "REINSPECTION_PENDING",
    "CUSTOMER_DECISION_PENDING",
    "READY_FOR_CLOSURE",
    "CLOSED",
    "CANCELLED",
]

FINDING_DRAFT = "DRAFT"
FINDING_REGISTERED = "REGISTERED"
FINDING_UNDER_EVALUATION = "UNDER_EVALUATION"
FINDING_CANCELLED = "CANCELLED"
FINDING_CLOSED = "CLOSED"

# Конечные статусы: обычное редактирование и переходы запрещены (ADR-019 «CLOSED и
# CANCELLED конечны»).
FINDING_TERMINAL_STATUSES: frozenset[str] = frozenset({FINDING_CLOSED, FINDING_CANCELLED})
# Статусы, из которых Task 9D-1 разрешает отмену (REGISTERED → CANCELLED — канон;
# UNDER_EVALUATION → CANCELLED допускаем: до появления disposition finding ещё можно
# признать ошибочным/дублирующим). DRAFT не отменяется, а удаляется.
FINDING_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {FINDING_REGISTERED, FINDING_UNDER_EVALUATION}
)
# Статусы, в которых finding уже зарегистрирован (номер и registered-поля заполнены).
FINDING_REGISTERED_OR_LATER: frozenset[str] = frozenset(
    {
        FINDING_REGISTERED,
        FINDING_UNDER_EVALUATION,
        "DISPOSITION_PENDING",
        "ACTION_REQUIRED",
        "ACTION_IN_PROGRESS",
        "REINSPECTION_PENDING",
        "CUSTOMER_DECISION_PENDING",
        "READY_FOR_CLOSURE",
        FINDING_CLOSED,
        FINDING_CANCELLED,
    }
)

# ── Канонический справочник происхождения (ADR-019, решение 2) ─────────────────
# origin_type не заменяет инженерную классификацию (та — в EngineeringEvaluation,
# блок 9D-2); это лишь источник появления finding.
FINDING_ORIGIN_TYPES: tuple[str, ...] = (
    "INSPECTION_RESULT",
    "VISUAL_OBSERVATION",
    "WELDING_PROCESS",
    "PERSONNEL_ADMISSION",
    "WELDING_MATERIAL",
    "BASE_MATERIAL",
    "HEAT_TREATMENT",
    "ENGINEERING_DOCUMENT",
    "EXECUTIVE_DOCUMENTATION",
    "TRACEABILITY",
    "CUSTOMER_REMARK",
    "INTERNAL_REVIEW",
    "OTHER",
)
FindingOriginType = Literal[
    "INSPECTION_RESULT",
    "VISUAL_OBSERVATION",
    "WELDING_PROCESS",
    "PERSONNEL_ADMISSION",
    "WELDING_MATERIAL",
    "BASE_MATERIAL",
    "HEAT_TREATMENT",
    "ENGINEERING_DOCUMENT",
    "EXECUTIVE_DOCUMENTATION",
    "TRACEABILITY",
    "CUSTOMER_REMARK",
    "INTERNAL_REVIEW",
    "OTHER",
]

# ── Первичный риск (ADR-019, решение 3) ────────────────────────────────────────
# initial_risk назначается ДО оценки (приоритет/SLA/эскалация). Подтверждённая
# критичность (confirmed_severity) устанавливается только EFFECTIVE
# EngineeringEvaluationRevision (блок 9D-2, ADR-021 / решение 9D-2-C03; ранний forward
# reference «APPROVED EngineeringEvaluation» устарел) и в ядро 9D-1 не входит.
FINDING_INITIAL_RISKS: tuple[str, ...] = (
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    "UNKNOWN",
)
FindingInitialRisk = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
FINDING_INITIAL_RISK_DEFAULT = "UNKNOWN"

# ── Типы событий журнала finding (append-only) ─────────────────────────────────
EVENT_CREATED = "CREATED"
EVENT_UPDATED = "UPDATED"
EVENT_REGISTERED = "REGISTERED"
EVENT_ACKNOWLEDGED = "ACKNOWLEDGED"
EVENT_CANCELLED = "CANCELLED"
FINDING_EVENT_TYPES: tuple[str, ...] = (
    EVENT_CREATED,
    EVENT_UPDATED,
    EVENT_REGISTERED,
    EVENT_ACKNOWLEDGED,
    EVENT_CANCELLED,
)

# ── Роли (канонические role_code проекта; новых не вводим, ADR-019) ─────────────
# Сопоставление ролей ТЗ с каноном проекта: WELDING_ENGINEER ↔ OGS_ENGINEER (код),
# NDT ↔ NDT_SPECIALIST, INSPECTOR ↔ OTK_INSPECTOR. Дубликаты ролей не создаются.
#
# Регистрация finding — любой авторизованный участник в пределах полномочий
# (ADR-019, решение 1). Набор ограничен ролями ТЗ 9D-1: главный сварщик, инженер
# ОГС, специалист НК, инспектор ОТК. Создание, редактирование DRAFT, регистрация и
# удаление DRAFT используют этот же набор.
FINDING_REGISTER_ROLES: frozenset[str] = frozenset(
    {
        iw.ROLE_CHIEF_WELDER,
        iw.ROLE_OGS_ENGINEER,
        iw.ROLE_NDT_SPECIALIST,
        iw.ROLE_OTK_INSPECTOR,
    }
)
# Подтверждение получения (acknowledge) и управление оценкой — контур ОГС
# (ADR-019: «ОГС подтверждает получение, управляет инженерной оценкой»).
FINDING_ACKNOWLEDGE_ROLES: frozenset[str] = frozenset(
    {iw.ROLE_CHIEF_WELDER, iw.ROLE_OGS_ENGINEER}
)
# Перевод ошибочной/дублирующей записи в CANCELLED — контур ОГС.
FINDING_CANCEL_ROLES: frozenset[str] = frozenset(
    {iw.ROLE_CHIEF_WELDER, iw.ROLE_OGS_ENGINEER}
)
# Чтение finding доступно тем же ролям, что видят Inspection в scope (Task 9A §15).
FINDING_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES

# ── Машинные коды доменных ошибок ──────────────────────────────────────────────
# HTTP-семантика (как в 9A–9C): 403 — роль/scope; 404 — объект не найден или скрыт
# scope; 409 — конфликт версии/недопустимый переход; 422 — структурно недопустимая
# команда или несоответствие ссылок.
FINDING_NOT_FOUND = "FINDING_NOT_FOUND"
FINDING_ROLE_DENIED = "FINDING_ROLE_DENIED"
FINDING_VERSION_CONFLICT = "FINDING_VERSION_CONFLICT"
FINDING_NOT_DRAFT = "FINDING_NOT_DRAFT"
FINDING_NOT_REGISTERED = "FINDING_NOT_REGISTERED"
FINDING_INVALID_TRANSITION = "FINDING_INVALID_TRANSITION"
FINDING_ALREADY_CANCELLED = "FINDING_ALREADY_CANCELLED"
FINDING_PROJECT_MISMATCH = "FINDING_PROJECT_MISMATCH"
FINDING_DUPLICATE_EXTERNAL_NO = "FINDING_DUPLICATE_EXTERNAL_NO"
FINDING_SOURCE_NOT_FOUND = "FINDING_SOURCE_NOT_FOUND"
FINDING_SOURCE_JOINT_MISMATCH = "FINDING_SOURCE_JOINT_MISMATCH"


def is_valid_status(code: str) -> bool:
    """Входит ли статус в канонический набор."""
    return code in FINDING_STATUSES


def is_valid_origin_type(code: str) -> bool:
    """Входит ли origin_type в канонический справочник (решение 2)."""
    return code in FINDING_ORIGIN_TYPES
