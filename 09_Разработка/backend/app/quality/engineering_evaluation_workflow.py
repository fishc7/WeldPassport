"""Доменная политика ядра EngineeringEvaluation (Task 9D-2A, ADR-021).

Только чистые константы и pure-функции без обращения к БД (стиль
`quality_finding_workflow`). Здесь фиксируются статусы ревизии (C06/C09), enum
классификации/исхода/рекомендации/критичности/влияния, результаты критериев, роли
источников, типы событий, роли и машинные коды ошибок.

Границы Task 9D-2A (структурное ядро):

* создаются 7 таблиц (C08); `sources`/`criteria`/`exceptions` — структурно, их
  бизнес-поведение (сверка источников, критерии, исключения, матрица комплектности) —
  блоки 9D-2B/2C;
* реализуется только структура + repository (create evaluation + первая DRAFT-ревизия,
  нумерация, чтение, update-DRAFT, журнал). Команды lifecycle, RBAC, API — блок 9D-2D;
* `RETURNED_FOR_REVISION` статусом НЕ является (C09): возврат — переход
  `PREPARED → DRAFT` + событие `EVALUATION_RETURNED`;
* классификация/исход/judgement принадлежат ревизии (C10), nullable в DRAFT,
  enum-CHECK действует только при NOT NULL; обязательность и матрица — на `prepare` (9D-2C).

Полный канонический набор статусов и типов событий фиксируется сразу (как 9A/9D-1),
чтобы будущие блоки не переписывали CHECK; 9D-2A эмитит только подмножество событий.
"""

from __future__ import annotations

from typing import Literal

from app.quality import inspection_workflow as iw

# ── Жизненный цикл ревизии (C06/C09) — ровно семь статусов ──────────────────────
EVALUATION_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "PREPARED",
    "FIXED",
    "PENDING_APPROVAL",
    "EFFECTIVE",
    "SUPERSEDED",
    "WITHDRAWN",
)
EvaluationStatus = Literal[
    "DRAFT",
    "PREPARED",
    "FIXED",
    "PENDING_APPROVAL",
    "EFFECTIVE",
    "SUPERSEDED",
    "WITHDRAWN",
]

EVAL_DRAFT = "DRAFT"
EVAL_PREPARED = "PREPARED"
EVAL_FIXED = "FIXED"
EVAL_PENDING_APPROVAL = "PENDING_APPROVAL"
EVAL_EFFECTIVE = "EFFECTIVE"
EVAL_SUPERSEDED = "SUPERSEDED"
EVAL_WITHDRAWN = "WITHDRAWN"

# Конечные статусы ревизии (обычное редактирование запрещено).
EVALUATION_TERMINAL_STATUSES: frozenset[str] = frozenset({EVAL_SUPERSEDED, EVAL_WITHDRAWN})

# ── Исход оценки — «что установлено» (9D-2-C01) ─────────────────────────────────
EVALUATION_OUTCOMES: tuple[str, ...] = (
    "ACCEPTABLE",
    "NONCONFORMING",
    "CONDITIONALLY_ACCEPTABLE",
    "INSUFFICIENT_DATA",
    "NOT_APPLICABLE",
)

# ── Инженерная классификация — канон ADR-019 «Evaluation Classification» (C07) ───
EVALUATION_CLASSIFICATIONS: tuple[str, ...] = (
    "CONFIRMED_DEFECT",
    "NOT_CONFIRMED",
    "TECHNOLOGICAL_DEVIATION",
    "DOCUMENTATION_NONCONFORMITY",
    "INSPECTION_PROCESS_NONCONFORMITY",
    "MATERIAL_TRACEABILITY_NONCONFORMITY",
    "PERSONNEL_QUALIFICATION_NONCONFORMITY",
    "REQUIRES_ADDITIONAL_EVIDENCE",
    "OUT_OF_SCOPE",
)

# Матрица согласованности classification → допустимые evaluation_outcome (C07).
# ДАННЫЕ для будущего enforcement (9D-2C); в 9D-2A не применяется.
CLASSIFICATION_OUTCOME_MATRIX: dict[str, tuple[str, ...]] = {
    "CONFIRMED_DEFECT": ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"),
    "NOT_CONFIRMED": ("ACCEPTABLE",),
    "TECHNOLOGICAL_DEVIATION": ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"),
    "DOCUMENTATION_NONCONFORMITY": ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"),
    "INSPECTION_PROCESS_NONCONFORMITY": ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"),
    "MATERIAL_TRACEABILITY_NONCONFORMITY": ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"),
    "PERSONNEL_QUALIFICATION_NONCONFORMITY": ("NONCONFORMING", "CONDITIONALLY_ACCEPTABLE"),
    "REQUIRES_ADDITIONAL_EVIDENCE": ("INSUFFICIENT_DATA",),
    "OUT_OF_SCOPE": ("NOT_APPLICABLE",),
}

# ── Необязывающая рекомендация ОГС (9D-2-C01) ───────────────────────────────────
RECOMMENDED_DISPOSITIONS: tuple[str, ...] = (
    "NONE",
    "ACCEPT_AS_IS",
    "REPAIR",
    "REWORK",
    "ADDITIONAL_INSPECTION",
    "REJECT",
)

# ── Подтверждённая критичность — канон ADR-019 (C02) ────────────────────────────
CONFIRMED_SEVERITIES: tuple[str, ...] = ("NOT_APPLICABLE", "MINOR", "MAJOR", "CRITICAL")

# ── Влияние оценки — канон ADR-019 (C02) ────────────────────────────────────────
IMPACT_SCOPES: tuple[str, ...] = (
    "NO_OPERATIONAL_IMPACT",
    "DOCUMENT_HANDOVER_BLOCK",
    "INSPECTION_ACCEPTANCE_BLOCK",
    "FURTHER_PROCESSING_BLOCK",
    "TECHNICAL_ACCEPTANCE_BLOCK",
    "FULL_JOINT_BLOCK",
)

# ── Уровень уверенности (§4.5) ──────────────────────────────────────────────────
CONFIDENCE_LEVELS: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")

# ── Результат критерия (§4.3; таблица criteria — структурно в 9D-2A) ────────────
CRITERION_RESULTS: tuple[str, ...] = (
    "COMPLIES",
    "DOES_NOT_COMPLY",
    "CONDITIONALLY_COMPLIES",
    "NOT_APPLICABLE",
    "INSUFFICIENT_DATA",
)

# ── Роль источника (§4.4; таблица sources — структурно в 9D-2A) ─────────────────
SOURCE_ROLES: tuple[str, ...] = (
    "PRIMARY_EVIDENCE",
    "SUPPORTING_EVIDENCE",
    "ACCEPTANCE_CRITERIA",
    "CONTEXT",
    "REJECTED_EVIDENCE",
)

# ── Типы событий журнала (append-only). 9D-2A эмитит CREATED/UPDATED ─────────────
EVENT_EVALUATION_CREATED = "EVALUATION_CREATED"
EVENT_EVALUATION_UPDATED = "EVALUATION_UPDATED"
EVALUATION_EVENT_TYPES: tuple[str, ...] = (
    "EVALUATION_CREATED",
    "EVALUATION_UPDATED",
    "EVALUATION_PREPARED",
    "EVALUATION_RETURNED",
    "EVALUATION_FIXED",
    "EVALUATION_WITHDRAWN",
    "EVALUATION_BECAME_EFFECTIVE",
    "EVALUATION_SUPERSEDED",
    "SOURCE_ADDED",
    "SOURCE_REMOVED",
    "SOURCE_REVERIFIED",
    "REVIEW_CONFIRMATION_REQUESTED",
    "REVIEW_CONFIRMED",
    "REVIEW_OVERDUE",
)

# ── Роли (канонические role_code проекта; новых не вводим). Используются с 9D-2D ─
# Подготовка (`prepare`) — WELDING_ENGINEER ↔ OGS_ENGINEER; фиксация/ввод в действие —
# CHIEF_WELDER (ADR-021 §2.4). В 9D-2A RBAC не применяется.
EVALUATION_PREPARE_ROLES: frozenset[str] = frozenset({iw.ROLE_OGS_ENGINEER})
EVALUATION_FIX_ROLES: frozenset[str] = frozenset({iw.ROLE_CHIEF_WELDER})
EVALUATION_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES

# ── Машинные коды доменных ошибок (HTTP-семантика 9D-1: 403/404/409/422) ─────────
EVAL_NOT_FOUND = "EVAL_NOT_FOUND"
EVAL_VERSION_CONFLICT = "EVAL_VERSION_CONFLICT"
EVAL_REVISION_NOT_DRAFT = "EVAL_REVISION_NOT_DRAFT"
EVAL_ALREADY_EXISTS = "EVAL_ALREADY_EXISTS"
EVAL_FINDING_NOT_FOUND = "EVAL_FINDING_NOT_FOUND"


class EvaluationError(Exception):
    """Доменная ошибка ядра оценки с машинным кодом (для сервиса/HTTP в 9D-2D)."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def is_valid_status(code: str) -> bool:
    """Входит ли статус в канонический набор C06/C09 (без RETURNED_FOR_REVISION)."""
    return code in EVALUATION_STATUSES


def is_editable_status(code: str) -> bool:
    """Редактирование содержания разрешено только в DRAFT (граница §6)."""
    return code == EVAL_DRAFT
