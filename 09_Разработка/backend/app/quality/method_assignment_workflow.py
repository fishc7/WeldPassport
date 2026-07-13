"""Доменная политика назначения методов контроля (Task 9B, ADR-015 / Session 007).

Продолжение канона Task 9A (`inspection_workflow`): только чистые константы и
pure-функции без обращения к БД. Здесь фиксируется закрытый набор кодов методов
контроля, статусы назначения, роли, машинные коды ошибок и код роли лаборатории НК.

Task 9B добавляет к контуру контроля назначение метода и лаборатории для
`Inspection` и управление жизненным циклом назначения до начала исполнения.
Выполнение метода, результаты, решения ОГС/ОТК, дефекты и отчёты (Tasks 9C–9G) НЕ
входят и здесь не моделируются.

Формат кодов — UPPERCASE, как во всём backend. Роли и код роли лаборатории берутся
из существующего канона проекта (см. `inspection_workflow` и `projects.models`),
новые роли/коды не вводятся.
"""

from __future__ import annotations

from typing import Literal

from app.quality import inspection_workflow as iw

# ── Закрытый набор кодов методов контроля (§6.1 задания) ───────────────────────
# Канонический минимальный набор Task 9B. Новые коды не придумываются: расширение
# допустимо только при наличии основания в коде или архитектурном каноне Session
# 007. Набор намеренно отделён от projects.InspectionType (ADR-009, снимок
# требуемых видов контроля линии): это разные понятия — «требуемый вид» линии и
# «назначенный метод» конкретной заявки.
INSPECTION_METHOD_CODES: tuple[str, ...] = (
    "VT",  # визуальный и измерительный контроль
    "RT",  # радиографический контроль
    "UT",  # ультразвуковой контроль
    "PT",  # капиллярный контроль
    "MT",  # магнитопорошковый контроль
    "LT",  # контроль герметичности
)
InspectionMethodCode = Literal["VT", "RT", "UT", "PT", "MT", "LT"]

# ── Статусы назначения (§8 задания) ────────────────────────────────────────────
# ASSIGNED — активное назначение; CANCELLED — отменено без замены; REPLACED —
# заменено новым назначением. Терминальные статусы неизменяемы и физически не
# удаляются (§8.3, §12). Полноценный lifecycle исполнения (Tasks 9C–9G) не вводится.
ASSIGNMENT_ASSIGNED = "ASSIGNED"
ASSIGNMENT_CANCELLED = "CANCELLED"
ASSIGNMENT_REPLACED = "REPLACED"
ASSIGNMENT_STATUSES: tuple[str, ...] = (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_CANCELLED,
    ASSIGNMENT_REPLACED,
)
AssignmentStatus = Literal["ASSIGNED", "CANCELLED", "REPLACED"]

# Терминальные (неизменяемые) статусы назначения.
ASSIGNMENT_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {ASSIGNMENT_CANCELLED, ASSIGNMENT_REPLACED}
)

# ── Код роли компании-лаборатории в проекте (§7.2 задания) ─────────────────────
# Используем существующий канонический role_code project_companies (ADR-001),
# нового кода не создаём.
NDT_LAB_ROLE_CODE = "NDT_LAB"

# ── Роли (§15 задания; канонические role_code проекта Task 9A) ──────────────────
# Организация контроля (создание/отмена/замена назначения): ОТК, НК и главный
# сварщик как глобальный администратор. WELDING_ENGINEER (OGS_ENGINEER) НЕ получает
# это право автоматически только из-за принадлежности к ОГС (§15).
ASSIGNMENT_WRITE_ROLES: frozenset[str] = frozenset(
    {
        iw.ROLE_OTK_INSPECTOR,
        iw.ROLE_NDT_SPECIALIST,
        iw.ROLE_CHIEF_WELDER,
    }
)
# Чтение назначений разрешено ролям, которым Task 9A разрешает видеть Inspection в
# соответствующем scope (§15).
ASSIGNMENT_READ_ROLES: frozenset[str] = iw.INSPECTION_READ_ROLES

# ── Машинные коды доменных ошибок (§18 задания) ────────────────────────────────
# HTTP-семантика согласована с Task 9A: 403 — роль/scope; 404 — объект не найден
# или скрыт scope; 409 — конфликт (дубль/статус/версия/замена без изменений);
# 422 — структурно недопустимая команда (метод/причина).
ASSIGNMENT_NOT_FOUND = "ASSIGNMENT_NOT_FOUND"
ASSIGNMENT_ROLE_DENIED = "ASSIGNMENT_ROLE_DENIED"
ASSIGNMENT_VERSION_CONFLICT = "ASSIGNMENT_VERSION_CONFLICT"
ASSIGNMENT_INVALID_METHOD = "ASSIGNMENT_INVALID_METHOD"
ASSIGNMENT_LABORATORY_NOT_FOUND = "ASSIGNMENT_LABORATORY_NOT_FOUND"
ASSIGNMENT_LABORATORY_INACTIVE = "ASSIGNMENT_LABORATORY_INACTIVE"
ASSIGNMENT_COMPANY_NOT_PROJECT_LABORATORY = (
    "ASSIGNMENT_COMPANY_NOT_PROJECT_LABORATORY"
)
ASSIGNMENT_DUPLICATE_ACTIVE_METHOD = "ASSIGNMENT_DUPLICATE_ACTIVE_METHOD"
ASSIGNMENT_INSPECTION_NOT_ASSIGNABLE = "ASSIGNMENT_INSPECTION_NOT_ASSIGNABLE"
ASSIGNMENT_ALREADY_CANCELLED = "ASSIGNMENT_ALREADY_CANCELLED"
ASSIGNMENT_ALREADY_REPLACED = "ASSIGNMENT_ALREADY_REPLACED"
ASSIGNMENT_NOT_ACTIVE = "ASSIGNMENT_NOT_ACTIVE"
ASSIGNMENT_NO_CHANGE = "ASSIGNMENT_NO_CHANGE"


def is_valid_method(code: str) -> bool:
    """Входит ли код метода в закрытый канонический набор (§6.1)."""
    return code in INSPECTION_METHOD_CODES
