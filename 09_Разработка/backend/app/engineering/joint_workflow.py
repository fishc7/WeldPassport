"""Доменная политика жизненного цикла Joint (Task 5B, ADR-011).

Единый источник словарей, классификации полей, правил переходов, машинных кодов
409 и вычисления `available_actions`. Бизнес-правила выполняет service-слой; здесь
только чистые константы и функции без обращения к БД (Р-11-1 — Р-11-4, §15 задания).

Канон статусов и блокировок закрыт по ADR-011 (решение владельца 2026-07-11):
жизненный цикл — `DRAFT/PENDING_REVIEW/ACTIVE/CANCELLED/SUPERSEDED` (без `UNDER_REVIEW`
и без `BLOCKED` как статуса); блокировка — отдельные записи (`joint_blocks`), Joint
остаётся `ACTIVE` (§20, инвариант §41.14).
"""

from __future__ import annotations

from typing import Literal

# ── Статусы жизненного цикла Joint (§3-4 ADR-011) ─────────────────────────────
JOINT_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "PENDING_REVIEW",
    "ACTIVE",
    "CANCELLED",
    "SUPERSEDED",
)
TERMINAL_STATUSES: frozenset[str] = frozenset({"CANCELLED", "SUPERSEDED"})

JointStatus = Literal["DRAFT", "PENDING_REVIEW", "ACTIVE", "CANCELLED", "SUPERSEDED"]

# ── Состояния согласований ПТО/ОГС (§5 ADR-011, Р-11-1) ───────────────────────
# Положительное решение — APPROVED (не CONFIRMED, Р-11-1).
APPROVAL_STATES: tuple[str, ...] = (
    "NOT_SUBMITTED",
    "PENDING",
    "APPROVED",
    "REJECTED",
    "REVOKED",
)
ApprovalState = Literal[
    "NOT_SUBMITTED", "PENDING", "APPROVED", "REJECTED", "REVOKED"
]

# Причина нахождения в PENDING (§5 ADR-011).
PENDING_REASONS: tuple[str, ...] = (
    "INITIAL_REVIEW",
    "REVIEW_REOPENED",
    "TEMPORARY_SUSPENSION",
    "REVALIDATION",
)
PendingReason = Literal[
    "INITIAL_REVIEW", "REVIEW_REOPENED", "TEMPORARY_SUSPENSION", "REVALIDATION"
]

# Способ принятия решения (§5, §9 ADR-011).
DECISION_METHODS: tuple[str, ...] = ("AUTOMATIC", "MANUAL", "OVERRIDE")
DecisionMethod = Literal["AUTOMATIC", "MANUAL", "OVERRIDE"]

# ── Блокировки (§20, Приложение C ADR-011) ────────────────────────────────────
BLOCK_TYPES: tuple[str, ...] = (
    "REPLACEMENT_PENDING",
    "WPS_INVALID",
    "APPROVAL_REVOKED",
    "REVISION_IMPACT_REVIEW",
    "APPROVAL_EXPIRED",
    "MANUAL_HOLD",
    "ADMIN_OVERRIDE_EXPIRED",
    "REVALIDATION_PENDING",
    "INTEGRITY_VIOLATION",
)
BlockType = Literal[
    "REPLACEMENT_PENDING",
    "WPS_INVALID",
    "APPROVAL_REVOKED",
    "REVISION_IMPACT_REVIEW",
    "APPROVAL_EXPIRED",
    "MANUAL_HOLD",
    "ADMIN_OVERRIDE_EXPIRED",
    "REVALIDATION_PENDING",
    "INTEGRITY_VIOLATION",
]

BLOCK_SCOPES: tuple[str, ...] = ("PRODUCTION", "EDITING", "APPROVAL", "ALL")
BlockScope = Literal["PRODUCTION", "EDITING", "APPROVAL", "ALL"]

# Активная блокировка с такой областью запрещает автоматическую активацию (§11).
ACTIVATION_BLOCKING_SCOPES: frozenset[str] = frozenset({"APPROVAL", "ALL"})

# ── Типы событий истории (§37 ADR-011) ────────────────────────────────────────
EVENT_TYPES: tuple[str, ...] = (
    "SUBMITTED_FOR_REVIEW",
    "REVIEW_REOPENED",
    "PTO_APPROVED",
    "PTO_REJECTED",
    "PTO_REVOKED",
    "OGS_APPROVED",
    "OGS_REJECTED",
    "OGS_REVOKED",
    "ACTIVATED",
    "DEACTIVATED",
    "APPROVAL_RESET",
    "APPROVAL_CARRIED_FORWARD",
    "SIGNIFICANT_EDIT",
    "BLOCKED",
    "UNBLOCKED",
    "CANCELLED",
    "SUPERSEDED",
)

# ── Роли (Р-11-3, §18 ADR-011) ────────────────────────────────────────────────
PTO_ROLES: frozenset[str] = frozenset({"PTO_ENGINEER", "PTO_MANAGER"})
OGS_ROLES: frozenset[str] = frozenset({"OGS_ENGINEER", "CHIEF_WELDER"})
# CHIEF_WELDER — неограниченная административная роль всей системы (§4 задания).
GLOBAL_ADMIN_ROLES: frozenset[str] = frozenset({"CHIEF_WELDER"})
# Роль, допускающая OGS OVERRIDE (§9 ADR-011).
OGS_OVERRIDE_ROLES: frozenset[str] = frozenset({"CHIEF_WELDER"})
AUDITOR_ROLE = "AUDITOR"

# ── Классификация редактируемых полей Joint (§13-14 ADR-011, §9 задания) ───────
# Единая матрица: какое согласование сбрасывается при изменении поля. Выведена из
# зон ответственности §7 (ПТО) и §8 (ОГС) ADR-011 — ADR не даёт отдельной
# поколоночной таблицы, поэтому классификация строится по владельцу данных.
#
#   IDENTITY  — идентичность соединения; обычным PATCH после DRAFT не меняется,
#               требуется новый Joint (SUPERSEDE_REQUIRED, §13).
#   SERVICE   — служебные/аннотационные поля; только record_version.
#   PTO       — инженерная зона; сбрасывает согласование ПТО.
#   OGS       — сварочно-технологическая зона; сбрасывает согласование ОГС.
#   BOTH      — затрагивает обе зоны; сбрасывает оба согласования.
IDENTITY_FIELDS: frozenset[str] = frozenset({"joint_no", "line_id"})
SERVICE_FIELDS: frozenset[str] = frozenset(
    {
        "sheet_no",
        "drawing_zone",
        "position_x",
        "position_y",
        "coordinate_system",
        "location_note",
        "document_note",
        "heat_treatment_note",
    }
)
PTO_FIELDS: frozenset[str] = frozenset(
    {
        "component_type_1",
        "component_type_2",
        "component_item_id_1",
        "component_item_id_2",
        "component_text_1",
        "component_text_2",
    }
)
OGS_FIELDS: frozenset[str] = frozenset(
    {
        "required_root_method",
        "required_fill_method",
        "required_cap_method",
        "planned_wps_id",
        "heat_treatment_required",
        "heat_treatment_type",
    }
)
BOTH_FIELDS: frozenset[str] = frozenset(
    {
        "dn_1",
        "dn_2",
        "thickness_1",
        "thickness_2",
        "material_id_1",
        "material_id_2",
        "material_text_1",
        "material_text_2",
        "geometry_type",
        "weld_joint_type",
        "connection_code",
    }
)

# Значимые (влияющие на согласование) поля.
SIGNIFICANT_FIELDS: frozenset[str] = PTO_FIELDS | OGS_FIELDS | BOTH_FIELDS


def affected_sides(changed_fields: set[str]) -> set[str]:
    """Возвращает затронутые согласования ('PTO'/'OGS') для набора изменённых
    значимых полей (§9 задания, §6/§13 ADR-011)."""
    sides: set[str] = set()
    if changed_fields & BOTH_FIELDS:
        sides.update({"PTO", "OGS"})
    if changed_fields & PTO_FIELDS:
        sides.add("PTO")
    if changed_fields & OGS_FIELDS:
        sides.add("OGS")
    return sides


# ── Машинные коды конфликта версий (§16 ADR-011, §3 задания) ──────────────────
RECORD_VERSION_CONFLICT = "RECORD_VERSION_CONFLICT"
APPROVAL_VERSION_CONFLICT = "APPROVAL_VERSION_CONFLICT"
WORKFLOW_VERSION_CONFLICT = "WORKFLOW_VERSION_CONFLICT"
SOURCE_JOINT_VERSION_CONFLICT = "SOURCE_JOINT_VERSION_CONFLICT"
SUCCESSOR_JOINT_VERSION_CONFLICT = "SUCCESSOR_JOINT_VERSION_CONFLICT"

# ── Прочие машинные коды доменных ошибок (§13 задания) ────────────────────────
INVALID_TRANSITION = "INVALID_TRANSITION"
TERMINAL_JOINT = "TERMINAL_JOINT"
INVALID_APPROVAL_STATE = "INVALID_APPROVAL_STATE"
STALE_APPROVAL = "STALE_APPROVAL"
SUPERSEDE_REQUIRED = "SUPERSEDE_REQUIRED"
CANNOT_UNBLOCK = "CANNOT_UNBLOCK"
CANNOT_CANCEL = "CANNOT_CANCEL"
CANNOT_SUPERSEDE = "CANNOT_SUPERSEDE"
ROLE_DENIED = "ROLE_DENIED"
SCOPE_DENIED = "SCOPE_DENIED"


# ── available_actions (§22-23 ADR-011, §11 задания) ───────────────────────────
# Полный перечень укрупнённых действий. Frontend не дублирует эту логику (§22).
ACTION_CODES: tuple[str, ...] = (
    "edit_service_fields",
    "edit_significant_fields",
    "submit_for_review",
    "approve_pto",
    "reject_pto",
    "revoke_pto",
    "approve_ogs",
    "reject_ogs",
    "revoke_ogs",
    "block",
    "unblock",
    "cancel",
    "supersede",
)


def compute_available_actions(
    *,
    status: str,
    pto_status: str,
    ogs_status: str,
    has_active_block: bool,
    actor_roles: frozenset[str],
) -> list[str]:
    """Вычисляет доступные действия для актора по состоянию Joint и его ролям.

    `actor_roles` — множество role_code активных ролей актора, покрывающих Joint по
    иерархии scope. Аудитор (только AUDITOR без иных ролей) не получает изменяющих
    действий (§18 ADR-011). Терминальный Joint не допускает действий (§4.4/4.5).
    """
    if status in TERMINAL_STATUSES:
        return []

    is_pto = bool(actor_roles & PTO_ROLES)
    is_ogs = bool(actor_roles & OGS_ROLES)
    actions: list[str] = []

    editable = status in ("DRAFT", "PENDING_REVIEW", "ACTIVE")
    if is_pto and editable:
        actions.append("edit_service_fields")
        actions.append("edit_significant_fields")

    if is_pto and status == "DRAFT":
        actions.append("submit_for_review")
    # Повторное открытие после отклонения/отзыва.
    if is_pto and status == "PENDING_REVIEW" and (
        pto_status in ("REJECTED", "REVOKED") or ogs_status in ("REJECTED", "REVOKED")
    ):
        actions.append("submit_for_review")

    if is_pto and pto_status == "PENDING":
        actions.extend(["approve_pto", "reject_pto"])
    if is_pto and pto_status == "APPROVED":
        actions.append("revoke_pto")

    if is_ogs and ogs_status == "PENDING":
        actions.extend(["approve_ogs", "reject_ogs"])
    if is_ogs and ogs_status == "APPROVED":
        actions.append("revoke_ogs")

    if (is_pto or is_ogs):
        actions.append("block")
        if has_active_block:
            actions.append("unblock")

    if is_pto and status in ("DRAFT", "PENDING_REVIEW", "ACTIVE"):
        actions.append("cancel")
    if is_pto and status in ("PENDING_REVIEW", "ACTIVE"):
        actions.append("supersede")

    # Убираем возможные дубли, сохраняя порядок ACTION_CODES.
    ordered = [a for a in ACTION_CODES if a in set(actions)]
    return ordered
