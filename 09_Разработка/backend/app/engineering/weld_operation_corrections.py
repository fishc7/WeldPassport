"""Доменная политика корректировок и переварки WeldOperation (Task 8D, ADR-012).

Чистый доменный компонент (без БД и HTTP, как `weld_operation_workflow` и
`weld_operation_review`): словари статусов, типы корректировок, матрица
согласований, множество критических полей, набор снимаемых полей, коды доменных
ошибок и первичная маршрутизация lifecycle корректировки.

Ключевой инвариант Task 8D: завершённый `WeldOperation` неизменяем. Исправление
завершённой операции выполняется только через отдельную трассируемую сущность
`WeldOperationCorrection`; прямой PATCH производственных данных после `COMPLETED`
по-прежнему запрещён. Полная переварка (`reweld`) — это новая `WeldOperation`
(`operation_kind = REWELD`), а не редактирование старой и не локальный ремонт.

Импорт, разрешение конфликтов и `IMPORT_CONFLICT_RESOLUTION` относятся к Task 8E и
здесь намеренно отсутствуют.
"""

from __future__ import annotations

from typing import Literal

# ── Тип корректировки (§7.2 задания) ──────────────────────────────────────────
# Импортных типов (IMPORT_CONFLICT_RESOLUTION) в Task 8D нет.
DATA_CORRECTION = "DATA_CORRECTION"
WELDER_CORRECTION = "WELDER_CORRECTION"
TECHNOLOGY_CORRECTION = "TECHNOLOGY_CORRECTION"
CANCEL_FALSE_RECORD = "CANCEL_FALSE_RECORD"
SUPERSEDE_RECORD = "SUPERSEDE_RECORD"

CORRECTION_TYPES: tuple[str, ...] = (
    DATA_CORRECTION,
    WELDER_CORRECTION,
    TECHNOLOGY_CORRECTION,
    CANCEL_FALSE_RECORD,
    SUPERSEDE_RECORD,
)
CorrectionType = Literal[
    "DATA_CORRECTION",
    "WELDER_CORRECTION",
    "TECHNOLOGY_CORRECTION",
    "CANCEL_FALSE_RECORD",
    "SUPERSEDE_RECORD",
]

# ── Технологическая значимость (§7.3) ─────────────────────────────────────────
NON_TECHNICAL = "NON_TECHNICAL"
TECHNOLOGICAL = "TECHNOLOGICAL"
IMPACT_LEVELS: tuple[str, ...] = (NON_TECHNICAL, TECHNOLOGICAL)
ImpactLevel = Literal["NON_TECHNICAL", "TECHNOLOGICAL"]

# ── Источник корректировки (§7.4): в Task 8D только ручной ────────────────────
SOURCE_MANUAL = "MANUAL"
SOURCE_TYPES: tuple[str, ...] = (SOURCE_MANUAL,)
SourceType = Literal["MANUAL"]

# ── Lifecycle корректировки (§7.5) ────────────────────────────────────────────
CORR_DRAFT = "DRAFT"
CORR_SUBMITTED = "SUBMITTED"
CORR_APPROVED = "APPROVED"
CORR_APPLIED = "APPLIED"
CORR_REJECTED = "REJECTED"
CORR_CANCELLED = "CANCELLED"
CORRECTION_LIFECYCLE_STATUSES: tuple[str, ...] = (
    CORR_DRAFT,
    CORR_SUBMITTED,
    CORR_APPROVED,
    CORR_APPLIED,
    CORR_REJECTED,
    CORR_CANCELLED,
)
CorrectionLifecycleStatus = Literal[
    "DRAFT", "SUBMITTED", "APPROVED", "APPLIED", "REJECTED", "CANCELLED"
]
# Активная корректировка (§12): не более одной на исходную операцию. Терминальные
# APPLIED/REJECTED/CANCELLED из множества исключены — после них допустима новая.
ACTIVE_LIFECYCLE_STATUSES: frozenset[str] = frozenset(
    {CORR_DRAFT, CORR_SUBMITTED, CORR_APPROVED}
)

# ── SMR approval (§7.6) ───────────────────────────────────────────────────────
SMR_NOT_REQUIRED = "NOT_REQUIRED"
SMR_PENDING = "PENDING"
SMR_APPROVED = "APPROVED"
SMR_RETURNED = "RETURNED_FOR_CLARIFICATION"
SMR_REJECTED = "REJECTED"
SMR_APPROVAL_STATUSES: tuple[str, ...] = (
    SMR_NOT_REQUIRED,
    SMR_PENDING,
    SMR_APPROVED,
    SMR_RETURNED,
    SMR_REJECTED,
)
SmrApprovalStatus = Literal[
    "NOT_REQUIRED", "PENDING", "APPROVED", "RETURNED_FOR_CLARIFICATION", "REJECTED"
]

# ── OGS review корректировки (§7.7) ───────────────────────────────────────────
# Отдельный набор статусов review именно корректировки (не путать с
# ogs_review_status самой операции из Task 8C).
OGS_NOT_REQUIRED = "NOT_REQUIRED"
OGS_PENDING = "PENDING"
OGS_ACCEPTED = "ACCEPTED"
OGS_ACCEPTED_WITH_REMARK = "ACCEPTED_WITH_REMARK"
OGS_RETURNED = "RETURNED_FOR_CLARIFICATION"
OGS_REJECTED = "REJECTED"
OGS_REVIEW_STATUSES: tuple[str, ...] = (
    OGS_NOT_REQUIRED,
    OGS_PENDING,
    OGS_ACCEPTED,
    OGS_ACCEPTED_WITH_REMARK,
    OGS_RETURNED,
    OGS_REJECTED,
)
OgsReviewStatus = Literal[
    "NOT_REQUIRED",
    "PENDING",
    "ACCEPTED",
    "ACCEPTED_WITH_REMARK",
    "RETURNED_FOR_CLARIFICATION",
    "REJECTED",
]
# Решение ОГС, при котором корректировка готова к применению (§14).
OGS_READY_STATUSES: frozenset[str] = frozenset(
    {OGS_NOT_REQUIRED, OGS_ACCEPTED, OGS_ACCEPTED_WITH_REMARK}
)
# Допустимые решения команды ogs-accept (§13.8).
OGS_ACCEPT_DECISIONS: tuple[str, ...] = (OGS_ACCEPTED, OGS_ACCEPTED_WITH_REMARK)

# ── Статус применения (§7.8) ──────────────────────────────────────────────────
APP_NOT_READY = "NOT_READY"
APP_READY = "READY_TO_APPLY"
APP_APPLIED = "APPLIED"
APP_FAILED = "FAILED"
APPLICATION_STATUSES: tuple[str, ...] = (
    APP_NOT_READY,
    APP_READY,
    APP_APPLIED,
    APP_FAILED,
)
ApplicationStatus = Literal["NOT_READY", "READY_TO_APPLY", "APPLIED", "FAILED"]

# ── Роли (§17): существующие role_code, новых не вводим ───────────────────────
# СМР: создание, редактирование черновика, submit, SMR approval, apply.
SMR_ROLES: frozenset[str] = frozenset({"MASTER", "FOREMAN", "CHIEF_WELDER"})
# ОГС: технологический review, решение по reweld, retry.
OGS_ROLES: frozenset[str] = frozenset({"OGS_ENGINEER", "CHIEF_WELDER"})

# ── Критические поля WeldOperation (§9) ───────────────────────────────────────
# Только реальные редактируемые поля текущей модели WeldOperation (§9: не создавать
# параллельные псевдонимы). DN/толщина/материал — атрибуты Joint, не операции, и
# поэтому не входят в набор редактируемых критических полей операции; их значения
# фиксируются в снимке как контекст Joint, но патчем не меняются.
CRITICAL_FIELDS: frozenset[str] = frozenset(
    {
        "actual_welder_id",       # фактический сварщик (welder_id)
        "entered_stamp_code",     # клеймо (welder_stamp_code)
        "actual_wps_id",          # применённый WPS (wps_id)
        "welding_method",         # способ сварки
        "weld_stage",             # этап
        "welding_position",       # положение
        "performed_on",           # фактическая дата выполнения (performed_at)
        "responsible_worker_id",  # ответственный/исполняющая организация
    }
)

# Некритические редактируемые реквизиты операции (§10 DATA_CORRECTION).
NON_CRITICAL_FIELDS: frozenset[str] = frozenset(
    {
        "started_at",
        "finished_at",
        "shielding_gas",
        "back_purge",
        "production_area_id",
        "production_area_text",
        "shift_ref",
        "shift_assignment_ref",
        "production_report_ref",
        "operation_note",
    }
)

# Все поля производственного факта, которые вообще допускается менять патчем.
PATCHABLE_FIELDS: frozenset[str] = CRITICAL_FIELDS | NON_CRITICAL_FIELDS

# Разрешённый набор полей патча по типу корректировки (§10). SUPERSEDE_RECORD не
# ограничивает набор одним подмножеством; CANCEL_FALSE_RECORD патч не принимает.
_ALLOWED_PATCH_FIELDS: dict[str, frozenset[str]] = {
    DATA_CORRECTION: NON_CRITICAL_FIELDS,
    WELDER_CORRECTION: frozenset({"actual_welder_id", "entered_stamp_code"}),
    TECHNOLOGY_CORRECTION: frozenset(
        {
            "welding_method",
            "weld_stage",
            "actual_wps_id",
            "welding_position",
            "performed_on",
        }
    ),
    SUPERSEDE_RECORD: PATCHABLE_FIELDS,
    CANCEL_FALSE_RECORD: frozenset(),
}


def allowed_patch_fields(correction_type: str) -> frozenset[str]:
    return _ALLOWED_PATCH_FIELDS.get(correction_type, frozenset())


def creates_replacement(correction_type: str) -> bool:
    """Создаёт ли тип корректировки заменяющую операцию (§10).

    Все типы, кроме отмены ложной записи, создают replacement draft."""
    return correction_type != CANCEL_FALSE_RECORD


def requires_ogs_review(correction_type: str) -> bool:
    """Требует ли тип корректировки технологического review ОГС (§10).

    DATA_CORRECTION — только SMR; остальные типы требуют review ОГС."""
    return correction_type != DATA_CORRECTION


def compute_impact_level(correction_type: str, changed_critical: bool) -> str:
    """Технологическая значимость корректировки (§7.3, §9).

    TECHNOLOGICAL, если изменено хотя бы одно критическое поле, а также для
    отмены ложной записи (значимое производственное действие) и всегда для
    welder/technology корректировок. Иначе NON_TECHNICAL."""
    if correction_type == CANCEL_FALSE_RECORD:
        return TECHNOLOGICAL
    if correction_type in (WELDER_CORRECTION, TECHNOLOGY_CORRECTION):
        return TECHNOLOGICAL
    return TECHNOLOGICAL if changed_critical else NON_TECHNICAL


# ── Набор полей снимка операции (§8.1) ────────────────────────────────────────
# Значимые воспроизводимые производственные поля WeldOperation. Нестабильные
# вычисляемые значения не включаются. Контекст Joint (DN/толщина/материал) кладётся
# отдельным ключом снимка сервисом.
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "id",
    "joint_id",
    "sequence_no",
    "lifecycle_status",
    "weld_stage",
    "welding_method",
    "performed_on",
    "started_at",
    "finished_at",
    "actual_welder_id",
    "entered_stamp_code",
    "profile_stamp_snapshot",
    "responsible_worker_id",
    "executor_company_id",
    "executor_department_id",
    "welder_company_id",
    "welder_department_id",
    "actual_wps_id",
    "welding_position",
    "shielding_gas",
    "back_purge",
    "production_area_id",
    "production_area_text",
    "shift_ref",
    "shift_assignment_ref",
    "production_report_ref",
    "operation_note",
    "record_version",
    "operation_kind",
    "qualification_validation_status",
    "qualification_validation_codes",
    "wps_validation_status",
    "wps_validation_codes",
    "validation_checked_at",
    "welder_confirmation_status",
    "welder_confirmation_version",
    "ogs_review_status",
    "ogs_review_version",
)

# Максимум идемпотентных технических попыток атомарного применения (§15.4).
MAX_APPLICATION_ATTEMPTS = 3

# ── Машинные коды доменных ошибок (§20) ───────────────────────────────────────
# HTTP-семантика: 400 — недопустимый transition/payload; 403 — роль/scope;
# 404 — операция/корректировка не найдена; 409 — конфликт версий/состояния;
# 422 — структурно недопустимая команда.
SOURCE_NOT_COMPLETED = "SOURCE_OPERATION_NOT_COMPLETED"
SOURCE_NOT_CORRECTABLE = "SOURCE_OPERATION_NOT_CORRECTABLE"
ACTIVE_CORRECTION_EXISTS = "ACTIVE_CORRECTION_EXISTS"
CORRECTION_NO_CHANGES = "CORRECTION_NO_EFFECTIVE_CHANGES"
CORRECTION_FIELD_NOT_ALLOWED = "CORRECTION_FIELD_NOT_ALLOWED"
CORRECTION_CRITICAL_FIELD_NOT_ALLOWED = "CORRECTION_CRITICAL_FIELD_NOT_ALLOWED"
CORRECTION_PATCH_NOT_ALLOWED = "CORRECTION_PATCH_NOT_ALLOWED"
CORRECTION_NOT_DRAFT = "CORRECTION_NOT_DRAFT"
CORRECTION_INVALID_TRANSITION = "CORRECTION_INVALID_TRANSITION"
CORRECTION_NOT_READY = "CORRECTION_NOT_READY_TO_APPLY"
CORRECTION_ALREADY_TERMINAL = "CORRECTION_ALREADY_TERMINAL"
CORRECTION_ALREADY_APPLIED = "CORRECTION_ALREADY_APPLIED"
CORRECTION_VERSION_CONFLICT = "CORRECTION_VERSION_CONFLICT"
SOURCE_VERSION_CONFLICT = "SOURCE_OPERATION_VERSION_CONFLICT"
SMR_APPROVAL_REQUIRED = "SMR_APPROVAL_REQUIRED"
OGS_REVIEW_REQUIRED = "OGS_REVIEW_REQUIRED"
REPLACEMENT_ALREADY_APPLIED = "REPLACEMENT_ALREADY_APPLIED"
CORRECTION_APPLY_FAILED = "CORRECTION_APPLY_FAILED"
RETRY_NOT_ALLOWED = "CORRECTION_RETRY_NOT_ALLOWED"
CORRECTION_COMMENT_REQUIRED = "CORRECTION_COMMENT_REQUIRED"
CORRECTION_ROLE_DENIED = "CORRECTION_ROLE_DENIED"

# ── Reweld (§16) ──────────────────────────────────────────────────────────────
REWELD_DECISION_REQUIRED = "REWELD_DECISION_REQUIRED"
REWELD_ALREADY_DECIDED = "REWELD_ALREADY_DECIDED"
REWELD_NOT_DRAFT = "REWELD_NOT_DRAFT"
REWELD_NOT_REWELD = "OPERATION_NOT_REWELD"
REWELD_SELF_REFERENCE = "REWELD_SELF_REFERENCE"
REWELD_DIFFERENT_JOINT = "REWELD_DIFFERENT_JOINT"


def readiness_after_decisions(
    smr_status: str, ogs_status: str
) -> bool:
    """Готова ли корректировка к применению (§14).

    Требуется SMR APPROVED и (ОГС не требуется либо принят с/без замечания)."""
    return smr_status == SMR_APPROVED and ogs_status in OGS_READY_STATUSES
