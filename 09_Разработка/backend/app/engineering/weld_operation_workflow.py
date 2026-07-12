"""Доменная политика жизненного цикла WeldOperation (Task 8A, ADR-012 / Session 005).

Единый источник словарей, ролей и машинных кодов ошибок для модели, миграции,
Pydantic-схем и сервиса производственного факта сварки. Здесь только чистые
константы без обращения к БД (как joint_workflow для Joint).

Task 8A реализует минимальное ядро `Joint → WeldOperation`: хранение, черновик,
редактирование черновика, завершение, отмену черновика и неизменяемость
завершённой операции. Проверки допуска, WPS, review ОГС, подтверждения сварщика,
корректировок, переварки и импорта в Task 8A НЕ входят (Tasks 8B–8E).

Формат кодов — UPPERCASE, как в существующем модуле engineering (JOINT_STATUSES,
GEOMETRY_TYPES, ENGINEERING_STATUSES). Канон Session 005 фиксирует этапы
`root/fill/cap/back_weld/tack` и lifecycle `draft/completed/superseded/cancelled`;
в Task 8A используется согласованный UPPERCASE и подмножество lifecycle без
SUPERSEDED (замена — Task 8D).
"""

from __future__ import annotations

from typing import Literal

# ── Жизненный цикл операции (§7.1 задания; подмножество 005-CA без SUPERSEDED) ──
WELD_OPERATION_STATUSES: tuple[str, ...] = ("DRAFT", "COMPLETED", "CANCELLED")
WeldOperationStatus = Literal["DRAFT", "COMPLETED", "CANCELLED"]
# Терминальные статусы: прямое редактирование запрещено (§13.4). CANCELLED и
# COMPLETED необратимы в Task 8A (COMPLETED→CANCELLED — Task 8D).
WELD_OPERATION_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "CANCELLED"})

# ── Классифицированный этап сварки (§7.2 задания; канон 005-Y) ─────────────────
WELD_STAGES: tuple[str, ...] = ("ROOT", "FILL", "CAP", "BACK_WELD", "TACK")
WeldStage = Literal["ROOT", "FILL", "CAP", "BACK_WELD", "TACK"]

# ── Роли (§10 задания; 005-C / 005-BZ) ────────────────────────────────────────
# Кто может создавать, вести черновик, завершать и отменять операцию. MASTER и
# FOREMAN — производственные роли; CHIEF_WELDER — неограниченная административная
# роль всей системы (не ломаем существующее право, §10.3), новых ролей не вводим.
WELD_OPERATION_ACTOR_ROLES: frozenset[str] = frozenset(
    {"MASTER", "FOREMAN", "CHIEF_WELDER"}
)
# Ответственным может быть только работник с ролью MASTER или FOREMAN и доступом к
# проекту/линии Joint (005-BZ, §10.2). CHIEF_WELDER ответственным не назначается.
WELD_OPERATION_RESPONSIBLE_ROLES: frozenset[str] = frozenset({"MASTER", "FOREMAN"})

# ── Машинные коды доменных ошибок (§18 задания) ───────────────────────────────
# HTTP-семантика: 409 — конфликт lifecycle/optimistic lock/изменение завершённой;
# 422 — структурные условия команды не выполнены. 403/404 — через общие ошибки.
WELD_OPERATION_COMPLETED = "WELD_OPERATION_COMPLETED"
WELD_OPERATION_CANCELLED = "WELD_OPERATION_CANCELLED"
WELD_OPERATION_NOT_DRAFT = "WELD_OPERATION_NOT_DRAFT"
WELD_OPERATION_INCOMPLETE = "WELD_OPERATION_INCOMPLETE"
JOINT_NOT_PRODUCIBLE = "JOINT_NOT_PRODUCIBLE"

# Сообщение о неизменяемости завершённой операции (§13.4): исправление — только
# через будущий механизм корректировок Task 8D, который в 8A не создаётся.
COMPLETED_IMMUTABLE_MESSAGE = (
    "Завершённая операция неизменяема: изменение выполняется только через будущий "
    "механизм корректировок (Task 8D)"
)
