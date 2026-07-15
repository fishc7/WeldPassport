"""Доменная политика выполнения метода контроля (Task 9C, ADR-015 / Session 007).

Продолжение канона Tasks 9A/9B (`inspection_workflow`, `method_assignment_workflow`):
только чистые константы и pure-функции без обращения к БД. Здесь фиксируются словари
статусов выполнения, участников, локальных результатов, оценок и полноты, коды
ошибок, а также расчётные функции (агрегированная оценка, проверка времени,
допустимость `wraps_zero`, вычисляемое состояние назначения).

Task 9C добавляет к контуру контроля фактическое выполнение назначенного метода
(`MethodExecution`), его участников, локальные результаты, стандарты и лабораторное
заключение. Решение ОГС, решение ОТК по соединению, дефекты и ремонт (Tasks 9D–9G)
НЕ входят и здесь не моделируются.

Согласование терминологии с каноном Session 007 (принято при планировании 9C):

* именование сущностей — гибрид: `MethodExecution`, `MethodExecutionResultItem`,
  `LaboratoryConclusion` (имена ТЗ), при этом прежние термины канона
  (`InspectionMethodExecution`, `InspectionMethodResult`) считаются ЗАМЕНЁННЫМИ,
  а не параллельными (обновление docs — отдельным шагом);
* терминал выполнения — `LAB_CONFIRMED` (НЕ `VERIFIED`): `VERIFIED` зарезервирован
  за последующей проверкой ОТК и в Task 9C не вводится;
* enum оценки результата — `CONFORMING / NONCONFORMING / INCONCLUSIVE /
  NOT_EVALUATED`. Канонический `NOT_PERFORMED` не смешивается с `NOT_EVALUATED`:
  невыполненный контроль отражается жизненным циклом и `cancellation_type =
  CONTROL_NOT_PERFORMED`, а не значением оценки. `NOT_PERFORMED` в коде нигде не
  используется (только в docs) — согласование терминологии документарное.

Формат кодов — UPPERCASE, как во всём backend. Роли и код роли лаборатории берутся
из существующего канона (`inspection_workflow`, `method_assignment_workflow`), новые
роли/коды не вводятся.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from app.quality import inspection_workflow as iw
from app.quality import method_assignment_workflow as maw

# Числовой допуск сравнения длин/координат при анализе покрытия (§12).
_COVERAGE_EPS = Decimal("0.001")

Number = int | float | Decimal


# ── Жизненный цикл выполнения (§6 задания, с корректировкой планирования) ───────
# DRAFT → IN_PROGRESS → PERFORMED → RESULT_RECORDED → LAB_CONFIRMED. CANCELLED —
# до подтверждения. SUPERSEDED — исторический статус предыдущей редакции после
# того, как новая редакция того же root_execution_id стала текущей (§18). После
# LAB_CONFIRMED обычное редактирование запрещено — исправление только через ревизию.
EXEC_DRAFT = "DRAFT"
EXEC_IN_PROGRESS = "IN_PROGRESS"
EXEC_PERFORMED = "PERFORMED"
EXEC_RESULT_RECORDED = "RESULT_RECORDED"
EXEC_LAB_CONFIRMED = "LAB_CONFIRMED"
EXEC_CANCELLED = "CANCELLED"
EXEC_SUPERSEDED = "SUPERSEDED"

EXECUTION_STATUSES: tuple[str, ...] = (
    EXEC_DRAFT,
    EXEC_IN_PROGRESS,
    EXEC_PERFORMED,
    EXEC_RESULT_RECORDED,
    EXEC_LAB_CONFIRMED,
    EXEC_CANCELLED,
    EXEC_SUPERSEDED,
)
ExecutionStatus = Literal[
    "DRAFT",
    "IN_PROGRESS",
    "PERFORMED",
    "RESULT_RECORDED",
    "LAB_CONFIRMED",
    "CANCELLED",
    "SUPERSEDED",
]

# Терминальные статусы: обычное редактирование и переходы запрещены. LAB_CONFIRMED
# исправляется только созданием новой редакции (§18); CANCELLED/SUPERSEDED —
# неизменяемая история.
EXECUTION_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {EXEC_LAB_CONFIRMED, EXEC_CANCELLED, EXEC_SUPERSEDED}
)
# Статусы, из которых допустима отмена (до подтверждения, §6/§7).
EXECUTION_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {EXEC_DRAFT, EXEC_IN_PROGRESS, EXEC_PERFORMED, EXEC_RESULT_RECORDED}
)

# Разрешённые прямые переходы жизненного цикла (без учёта отмены/замещения).
# Линейная цепочка вперёд; ветвление CANCELLED/SUPERSEDED задаётся отдельно, т.к.
# отмена и замещение — команды с дополнительными инвариантами, а не рядовой шаг.
_FORWARD_TRANSITIONS: dict[str, frozenset[str]] = {
    EXEC_DRAFT: frozenset({EXEC_IN_PROGRESS, EXEC_PERFORMED}),
    EXEC_IN_PROGRESS: frozenset({EXEC_PERFORMED}),
    EXEC_PERFORMED: frozenset({EXEC_RESULT_RECORDED}),
    EXEC_RESULT_RECORDED: frozenset({EXEC_LAB_CONFIRMED}),
    EXEC_LAB_CONFIRMED: frozenset(),
    EXEC_CANCELLED: frozenset(),
    EXEC_SUPERSEDED: frozenset(),
}


# ── Режим подтверждения (§7 задания) ───────────────────────────────────────────
# DIRECT_LAB_CONFIRMATION — подтверждает пользователь, представляющий лабораторию.
# EXTERNAL_DOCUMENT_REGISTRATION — внутренний пользователь (ОТК/ОГС/главный сварщик)
# регистрирует уже выданный вне WeldPassport лабораторный документ. Внутренний
# регистратор НЕ является исполнителем, НЕ утверждающим лицом лаборатории и НЕ
# выполняет акт ОТК — он отвечает только за корректность переноса данных.
CONFIRM_DIRECT_LAB = "DIRECT_LAB_CONFIRMATION"
CONFIRM_EXTERNAL_DOCUMENT = "EXTERNAL_DOCUMENT_REGISTRATION"
CONFIRMATION_MODES: tuple[str, ...] = (
    CONFIRM_DIRECT_LAB,
    CONFIRM_EXTERNAL_DOCUMENT,
)
ConfirmationMode = Literal[
    "DIRECT_LAB_CONFIRMATION", "EXTERNAL_DOCUMENT_REGISTRATION"
]


# ── Точность времени выполнения (§8 задания) ───────────────────────────────────
TIME_DATE_ONLY = "DATE_ONLY"
TIME_START_KNOWN = "START_TIME_KNOWN"
TIME_FULL_INTERVAL = "FULL_INTERVAL"
TIME_PRECISIONS: tuple[str, ...] = (
    TIME_DATE_ONLY,
    TIME_START_KNOWN,
    TIME_FULL_INTERVAL,
)
TimePrecision = Literal["DATE_ONLY", "START_TIME_KNOWN", "FULL_INTERVAL"]


# ── Тип и причина отмены выполнения (§6 задания) ───────────────────────────────
CANCEL_CREATED_BY_MISTAKE = "CREATED_BY_MISTAKE"
CANCEL_DUPLICATE = "DUPLICATE"
CANCEL_CONTROL_NOT_PERFORMED = "CONTROL_NOT_PERFORMED"
CANCEL_WRONG_ASSIGNMENT = "WRONG_ASSIGNMENT"
CANCEL_WRONG_LABORATORY = "WRONG_LABORATORY"
CANCEL_OTHER = "OTHER"
CANCELLATION_TYPES: tuple[str, ...] = (
    CANCEL_CREATED_BY_MISTAKE,
    CANCEL_DUPLICATE,
    CANCEL_CONTROL_NOT_PERFORMED,
    CANCEL_WRONG_ASSIGNMENT,
    CANCEL_WRONG_LABORATORY,
    CANCEL_OTHER,
)
CancellationType = Literal[
    "CREATED_BY_MISTAKE",
    "DUPLICATE",
    "CONTROL_NOT_PERFORMED",
    "WRONG_ASSIGNMENT",
    "WRONG_LABORATORY",
    "OTHER",
]


# ── Роли участников фактического контроля (§9.1 задания) ────────────────────────
PARTICIPANT_LEAD_INSPECTOR = "LEAD_INSPECTOR"
PARTICIPANT_INSPECTOR = "INSPECTOR"
PARTICIPANT_ASSISTANT = "ASSISTANT"
PARTICIPANT_TRAINEE = "TRAINEE"
PARTICIPANT_RESULT_REVIEWER = "RESULT_REVIEWER"
PARTICIPANT_ROLES: tuple[str, ...] = (
    PARTICIPANT_LEAD_INSPECTOR,
    PARTICIPANT_INSPECTOR,
    PARTICIPANT_ASSISTANT,
    PARTICIPANT_TRAINEE,
    PARTICIPANT_RESULT_REVIEWER,
)
ParticipantRole = Literal[
    "LEAD_INSPECTOR", "INSPECTOR", "ASSISTANT", "TRAINEE", "RESULT_REVIEWER"
]

# Форма привлечения участника (§9.2 задания).
ENGAGEMENT_EMPLOYEE = "EMPLOYEE"
ENGAGEMENT_CONTRACTOR = "CONTRACTOR"
ENGAGEMENT_SECONDMENT = "SECONDMENT"
ENGAGEMENT_AUTHORIZED_EXTERNAL = "AUTHORIZED_EXTERNAL_SPECIALIST"
ENGAGEMENT_TYPES: tuple[str, ...] = (
    ENGAGEMENT_EMPLOYEE,
    ENGAGEMENT_CONTRACTOR,
    ENGAGEMENT_SECONDMENT,
    ENGAGEMENT_AUTHORIZED_EXTERNAL,
)
EngagementType = Literal[
    "EMPLOYEE", "CONTRACTOR", "SECONDMENT", "AUTHORIZED_EXTERNAL_SPECIALIST"
]


# ── Локальный результат: состояние записи (§10.3 задания) ──────────────────────
# EXCLUDED не участвует в расчётах; исключение сопровождается audit-событием (§10.3).
RESULT_DRAFT = "DRAFT"
RESULT_COMPLETE = "COMPLETE"
RESULT_EXCLUDED = "EXCLUDED"
RESULT_STATES: tuple[str, ...] = (RESULT_DRAFT, RESULT_COMPLETE, RESULT_EXCLUDED)
RecordState = Literal["DRAFT", "COMPLETE", "EXCLUDED"]


# ── Тип контролируемого объекта (§10.4 задания) ────────────────────────────────
OBJ_WHOLE_JOINT = "WHOLE_JOINT"
OBJ_MEASURING_BELT_SEGMENT = "MEASURING_BELT_SEGMENT"
OBJ_LINEAR_SEGMENT = "LINEAR_SEGMENT"
OBJ_IMAGE = "IMAGE"
OBJ_SURFACE_AREA = "SURFACE_AREA"
OBJ_BASE_METAL_1 = "BASE_METAL_1"
OBJ_BASE_METAL_2 = "BASE_METAL_2"
OBJ_WELD_METAL = "WELD_METAL"
OBJ_HEAT_AFFECTED_ZONE = "HEAT_AFFECTED_ZONE"
OBJ_OTHER = "OTHER"
CONTROLLED_OBJECT_TYPES: tuple[str, ...] = (
    OBJ_WHOLE_JOINT,
    OBJ_MEASURING_BELT_SEGMENT,
    OBJ_LINEAR_SEGMENT,
    OBJ_IMAGE,
    OBJ_SURFACE_AREA,
    OBJ_BASE_METAL_1,
    OBJ_BASE_METAL_2,
    OBJ_WELD_METAL,
    OBJ_HEAT_AFFECTED_ZONE,
    OBJ_OTHER,
)
ControlledObjectType = Literal[
    "WHOLE_JOINT",
    "MEASURING_BELT_SEGMENT",
    "LINEAR_SEGMENT",
    "IMAGE",
    "SURFACE_AREA",
    "BASE_METAL_1",
    "BASE_METAL_2",
    "WELD_METAL",
    "HEAT_AFFECTED_ZONE",
    "OTHER",
]


# ── Координатная система и единицы (§10.5 задания) ──────────────────────────────
COORD_MEASURING_BELT = "MEASURING_BELT"
COORD_LINEAR_WELD_LENGTH = "LINEAR_WELD_LENGTH"
COORD_IMAGE_NUMBER = "IMAGE_NUMBER"
COORD_SECTOR = "SECTOR"
COORD_LOCAL_ZONE = "LOCAL_ZONE"
COORD_OTHER = "OTHER"
COORDINATE_SYSTEMS: tuple[str, ...] = (
    COORD_MEASURING_BELT,
    COORD_LINEAR_WELD_LENGTH,
    COORD_IMAGE_NUMBER,
    COORD_SECTOR,
    COORD_LOCAL_ZONE,
    COORD_OTHER,
)
CoordinateSystem = Literal[
    "MEASURING_BELT",
    "LINEAR_WELD_LENGTH",
    "IMAGE_NUMBER",
    "SECTOR",
    "LOCAL_ZONE",
    "OTHER",
]

COORD_UNIT_MM = "MM"
COORD_UNIT_DEGREE = "DEGREE"
COORD_UNIT_NUMBER = "NUMBER"
COORD_UNIT_PERCENT = "PERCENT"
COORD_UNIT_TEXT = "TEXT"
COORDINATE_UNITS: tuple[str, ...] = (
    COORD_UNIT_MM,
    COORD_UNIT_DEGREE,
    COORD_UNIT_NUMBER,
    COORD_UNIT_PERCENT,
    COORD_UNIT_TEXT,
)
CoordinateUnit = Literal["MM", "DEGREE", "NUMBER", "PERCENT", "TEXT"]

# Замкнутые (кольцевые) координатные системы: только для них допустим wraps_zero
# (§10.5). Мерной пояс и угловой сектор кольцевого стыка замкнуты по окружности;
# LINEAR_WELD_LENGTH по умолчанию трактуется как разомкнутая (прямой шов). Набор
# намеренно консервативен и расширяется только при явном доменном основании.
CLOSED_COORDINATE_SYSTEMS: frozenset[str] = frozenset(
    {COORD_MEASURING_BELT, COORD_SECTOR}
)


# ── Техническая оценка результата (§10.6 задания; enum согласован с каноном) ────
# NOT_EVALUATED — «не оценён» (оценка не вынесена), НЕ «не выполнен». Невыполненный
# контроль отражается статусом выполнения и cancellation_type=CONTROL_NOT_PERFORMED.
EVAL_CONFORMING = "CONFORMING"
EVAL_NONCONFORMING = "NONCONFORMING"
EVAL_INCONCLUSIVE = "INCONCLUSIVE"
EVAL_NOT_EVALUATED = "NOT_EVALUATED"
EVALUATIONS: tuple[str, ...] = (
    EVAL_CONFORMING,
    EVAL_NONCONFORMING,
    EVAL_INCONCLUSIVE,
    EVAL_NOT_EVALUATED,
)
Evaluation = Literal[
    "CONFORMING", "NONCONFORMING", "INCONCLUSIVE", "NOT_EVALUATED"
]

# Приоритет агрегированной оценки выполнения (§11): худший результат «побеждает».
# NONCONFORMING > INCONCLUSIVE > NOT_EVALUATED > CONFORMING.
_EVALUATION_PRIORITY: tuple[str, ...] = (
    EVAL_NONCONFORMING,
    EVAL_INCONCLUSIVE,
    EVAL_NOT_EVALUATED,
    EVAL_CONFORMING,
)


# ── Рекомендуемое действие по результату (§10.6 задания) ───────────────────────
ACTION_NONE = "NONE"
ACTION_REPAIR = "REPAIR"
ACTION_RECONTROL = "RECONTROL"
ACTION_ADDITIONAL_CONTROL = "ADDITIONAL_CONTROL"
ACTION_REVIEW = "REVIEW"
REQUIRED_ACTIONS: tuple[str, ...] = (
    ACTION_NONE,
    ACTION_REPAIR,
    ACTION_RECONTROL,
    ACTION_ADDITIONAL_CONTROL,
    ACTION_REVIEW,
)
RequiredAction = Literal[
    "NONE", "REPAIR", "RECONTROL", "ADDITIONAL_CONTROL", "REVIEW"
]


# ── Полнота покрытия (§12 задания) ─────────────────────────────────────────────
# Расчётная (по данным локальных результатов) и заявленная (исполнителем/лабораторией).
COMPLETION_PARTIAL = "PARTIAL"
COMPLETION_COMPLETE = "COMPLETE"
COMPLETION_OVERLAPPING = "OVERLAPPING"
COMPLETION_HAS_GAPS = "HAS_GAPS"
COMPLETION_NOT_CALCULABLE = "NOT_CALCULABLE"
CALCULATED_COMPLETIONS: tuple[str, ...] = (
    COMPLETION_PARTIAL,
    COMPLETION_COMPLETE,
    COMPLETION_OVERLAPPING,
    COMPLETION_HAS_GAPS,
    COMPLETION_NOT_CALCULABLE,
)
CalculatedCompletion = Literal[
    "PARTIAL", "COMPLETE", "OVERLAPPING", "HAS_GAPS", "NOT_CALCULABLE"
]

DECLARED_PARTIAL = "PARTIAL"
DECLARED_COMPLETE = "COMPLETE"
DECLARED_OVERFULFILLED = "OVERFULFILLED"
DECLARED_NOT_DETERMINED = "NOT_DETERMINED"
DECLARED_COMPLETIONS: tuple[str, ...] = (
    DECLARED_PARTIAL,
    DECLARED_COMPLETE,
    DECLARED_OVERFULFILLED,
    DECLARED_NOT_DETERMINED,
)
DeclaredCompletion = Literal[
    "PARTIAL", "COMPLETE", "OVERFULFILLED", "NOT_DETERMINED"
]


# ── Вычисляемое состояние назначения метода (§24 задания) ──────────────────────
# Гибрид: имена COMPLETED_* приведены к терминологии оценки канона (CONFORMING/
# NONCONFORMING) вместо ACCEPTABLE/UNACCEPTABLE. Состояние вычисляемое, физической
# колонки не заводит (§24): только по текущим редакциям и подтверждённым выполнениям.
ASSIGNMENT_STATE_NOT_STARTED = "NOT_STARTED"
ASSIGNMENT_STATE_IN_PROGRESS = "IN_PROGRESS"
ASSIGNMENT_STATE_PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
ASSIGNMENT_STATE_COMPLETED_CONFORMING = "COMPLETED_CONFORMING"
ASSIGNMENT_STATE_COMPLETED_WITH_NONCONFORMING = "COMPLETED_WITH_NONCONFORMING"
ASSIGNMENT_STATE_COMPLETED_INCONCLUSIVE = "COMPLETED_INCONCLUSIVE"
ASSIGNMENT_STATE_COMPLETED_MIXED = "COMPLETED_MIXED"
ASSIGNMENT_STATES: tuple[str, ...] = (
    ASSIGNMENT_STATE_NOT_STARTED,
    ASSIGNMENT_STATE_IN_PROGRESS,
    ASSIGNMENT_STATE_PARTIALLY_COMPLETED,
    ASSIGNMENT_STATE_COMPLETED_CONFORMING,
    ASSIGNMENT_STATE_COMPLETED_WITH_NONCONFORMING,
    ASSIGNMENT_STATE_COMPLETED_INCONCLUSIVE,
    ASSIGNMENT_STATE_COMPLETED_MIXED,
)
AssignmentComputedState = Literal[
    "NOT_STARTED",
    "IN_PROGRESS",
    "PARTIALLY_COMPLETED",
    "COMPLETED_CONFORMING",
    "COMPLETED_WITH_NONCONFORMING",
    "COMPLETED_INCONCLUSIVE",
    "COMPLETED_MIXED",
]


# ── Роли (§22 задания; канонические role_code, новых не вводим) ─────────────────
# Организация выполнения/результатов (создание/редактирование до подтверждения):
# как в Task 9B — ОТК, НК и главный сварщик. Полноценная внешняя авторизация
# лаборатории — будущая задача (§22).
EXECUTION_WRITE_ROLES: frozenset[str] = maw.ASSIGNMENT_WRITE_ROLES
# Регистрация внешнего лабораторного документа (EXTERNAL_DOCUMENT_REGISTRATION,
# §22, решение 9C-29): ОТК, действующая роль ОГС (OGS_ENGINEER) и главный сварщик.
# Отдельного permission не вводится; scope — проектный, кроме глобального
# CHIEF_WELDER.
EXTERNAL_REGISTRATION_ROLES: frozenset[str] = frozenset(
    {
        iw.ROLE_OTK_INSPECTOR,
        iw.ROLE_OGS_ENGINEER,
        iw.ROLE_CHIEF_WELDER,
    }
)
# Чтение выполнения/результатов — как чтение назначения Task 9B.
EXECUTION_READ_ROLES: frozenset[str] = maw.ASSIGNMENT_READ_ROLES

# Код роли компании-лаборатории в проекте — существующий канон (§4 задания).
NDT_LAB_ROLE_CODE = maw.NDT_LAB_ROLE_CODE


# ── Машинные коды доменных ошибок (§27 задания) ────────────────────────────────
# HTTP-семантика согласована с Tasks 9A/9B: 403 — роль/scope; 404 — не найдено или
# скрыто scope; 409 — конфликт (статус/версия/дубль/подтверждённая запись);
# 422 — структурно недопустимая команда (время/координаты/оценка/override).
EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
EXECUTION_ROLE_DENIED = "EXECUTION_ROLE_DENIED"
EXECUTION_VERSION_CONFLICT = "EXECUTION_VERSION_CONFLICT"
EXECUTION_JOINT_MISMATCH = "EXECUTION_JOINT_MISMATCH"
EXECUTION_PROJECT_MISMATCH = "EXECUTION_PROJECT_MISMATCH"
EXECUTION_LABORATORY_NOT_FOUND = "EXECUTION_LABORATORY_NOT_FOUND"
EXECUTION_LABORATORY_NOT_NDT_LAB = "EXECUTION_LABORATORY_NOT_NDT_LAB"
EXECUTION_LABORATORY_PROJECT_MISMATCH = "EXECUTION_LABORATORY_PROJECT_MISMATCH"
EXECUTION_ASSIGNMENT_NOT_ASSIGNABLE = "EXECUTION_ASSIGNMENT_NOT_ASSIGNABLE"
EXECUTION_INVALID_TRANSITION = "EXECUTION_INVALID_TRANSITION"
EXECUTION_NO_RESULT_ITEMS = "EXECUTION_NO_RESULT_ITEMS"
EXECUTION_INCOMPLETE_RESULT_ITEMS = "EXECUTION_INCOMPLETE_RESULT_ITEMS"
EXECUTION_NO_LEAD_INSPECTOR = "EXECUTION_NO_LEAD_INSPECTOR"
EXECUTION_MULTIPLE_LEAD_INSPECTORS = "EXECUTION_MULTIPLE_LEAD_INSPECTORS"
EXECUTION_PERFORMED_DATE_REQUIRED = "EXECUTION_PERFORMED_DATE_REQUIRED"
EXECUTION_TIME_START_REQUIRED = "EXECUTION_TIME_START_REQUIRED"
EXECUTION_TIME_FINISH_REQUIRED = "EXECUTION_TIME_FINISH_REQUIRED"
EXECUTION_TIME_FINISH_BEFORE_START = "EXECUTION_TIME_FINISH_BEFORE_START"
EXECUTION_INVALID_COORDINATES = "EXECUTION_INVALID_COORDINATES"
EXECUTION_INVALID_WRAPS_ZERO = "EXECUTION_INVALID_WRAPS_ZERO"
EXECUTION_EVALUATION_OVERRIDE_REASON_REQUIRED = (
    "EXECUTION_EVALUATION_OVERRIDE_REASON_REQUIRED"
)
EXECUTION_COMPLETION_OVERRIDE_REASON_REQUIRED = (
    "EXECUTION_COMPLETION_OVERRIDE_REASON_REQUIRED"
)
EXECUTION_ALREADY_CONFIRMED = "EXECUTION_ALREADY_CONFIRMED"
EXECUTION_ALREADY_TERMINAL = "EXECUTION_ALREADY_TERMINAL"
EXECUTION_CANCELLATION_REASON_REQUIRED = "EXECUTION_CANCELLATION_REASON_REQUIRED"
# ── Редакции выполнения (§18) ─────────────────────────────────────────────────
EXECUTION_NOT_CONFIRMED_FOR_REVISION = "EXECUTION_NOT_CONFIRMED_FOR_REVISION"
EXECUTION_NOT_CURRENT_REVISION = "EXECUTION_NOT_CURRENT_REVISION"
EXECUTION_CORRECTION_REASON_REQUIRED = "EXECUTION_CORRECTION_REASON_REQUIRED"
EXECUTION_REVISION_IN_PROGRESS = "EXECUTION_REVISION_IN_PROGRESS"
EXECUTION_REVISION_CONFLICT = "EXECUTION_REVISION_CONFLICT"
RESULT_ITEM_NOT_FOUND = "RESULT_ITEM_NOT_FOUND"
RESULT_ITEM_ALREADY_EXCLUDED = "RESULT_ITEM_ALREADY_EXCLUDED"
RESULT_ITEM_EXCLUDE_REASON_REQUIRED = "RESULT_ITEM_EXCLUDE_REASON_REQUIRED"
PARTICIPANT_NOT_FOUND = "PARTICIPANT_NOT_FOUND"
PARTICIPANT_DELETE_NOT_DRAFT = "PARTICIPANT_DELETE_NOT_DRAFT"
EXTERNAL_PERSON_NOT_FOUND = "EXTERNAL_PERSON_NOT_FOUND"
EXECUTION_CONFIRMATION_MODE_REQUIRED = "EXECUTION_CONFIRMATION_MODE_REQUIRED"
# Прямой ввод лабораторией (DIRECT_LAB_CONFIRMATION) требует полноценной внешней
# auth-модели, которая в блоке 9C-3 не строится (§22): поддержан только
# EXTERNAL_DOCUMENT_REGISTRATION.
EXECUTION_DIRECT_CONFIRMATION_UNSUPPORTED = (
    "EXECUTION_DIRECT_CONFIRMATION_UNSUPPORTED"
)


# ── Доменный аудит (§23 задания) ───────────────────────────────────────────────
# Полиморфный журнал значимых действий: entity_type/entity_id без FK (как
# InspectionEvent Task 9A). JSONB — только для changed_fields/previous/new; основные
# доменные данные в JSON не хранятся.
AUDIT_ENTITY_METHOD_EXECUTION = "METHOD_EXECUTION"
AUDIT_ENTITY_PARTICIPANT = "METHOD_EXECUTION_PARTICIPANT"
AUDIT_ENTITY_RESULT_ITEM = "METHOD_EXECUTION_RESULT_ITEM"
AUDIT_ENTITY_STANDARD = "METHOD_EXECUTION_STANDARD"
AUDIT_ENTITY_CONCLUSION = "LABORATORY_CONCLUSION"
AUDIT_ENTITY_CONCLUSION_EXECUTION = "LABORATORY_CONCLUSION_EXECUTION"
AUDIT_ENTITY_ACCREDITATION = "LABORATORY_ACCREDITATION"
QUALITY_AUDIT_ENTITY_TYPES: tuple[str, ...] = (
    AUDIT_ENTITY_METHOD_EXECUTION,
    AUDIT_ENTITY_PARTICIPANT,
    AUDIT_ENTITY_RESULT_ITEM,
    AUDIT_ENTITY_STANDARD,
    AUDIT_ENTITY_CONCLUSION,
    AUDIT_ENTITY_CONCLUSION_EXECUTION,
    AUDIT_ENTITY_ACCREDITATION,
)

AUDIT_EVENT_EXECUTION_CREATED = "EXECUTION_CREATED"
AUDIT_EVENT_STATUS_CHANGED = "STATUS_CHANGED"
AUDIT_EVENT_LABORATORY_CHANGED = "LABORATORY_CHANGED"
AUDIT_EVENT_PARTICIPANTS_CHANGED = "PARTICIPANTS_CHANGED"
AUDIT_EVENT_TIME_CHANGED = "TIME_CHANGED"
AUDIT_EVENT_VOLUME_CHANGED = "VOLUME_CHANGED"
AUDIT_EVENT_COORDINATES_CHANGED = "COORDINATES_CHANGED"
AUDIT_EVENT_EVALUATION_CHANGED = "EVALUATION_CHANGED"
AUDIT_EVENT_REQUIRED_ACTION_CHANGED = "REQUIRED_ACTION_CHANGED"
AUDIT_EVENT_RESULT_CONFIRMED = "RESULT_CONFIRMED"
AUDIT_EVENT_EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
AUDIT_EVENT_REVISION_CREATED = "REVISION_CREATED"
AUDIT_EVENT_REMOVED_RESULT_ITEM = "REMOVED_RESULT_ITEM"
AUDIT_EVENT_CONCLUSION_CREATED = "CONCLUSION_CREATED"
AUDIT_EVENT_CONCLUSION_COMPOSITION_CHANGED = "CONCLUSION_COMPOSITION_CHANGED"
AUDIT_EVENT_CONCLUSION_APPROVED = "CONCLUSION_APPROVED"
AUDIT_EVENT_CONCLUSION_ISSUED = "CONCLUSION_ISSUED"
AUDIT_EVENT_CONCLUSION_SUPERSEDED = "CONCLUSION_SUPERSEDED"
# ── Добавлено блоком 9C-5 (расширение CHECK — миграция 18) ─────────────────────
AUDIT_EVENT_CONCLUSION_EXECUTION_ADDED = "CONCLUSION_EXECUTION_ADDED"
AUDIT_EVENT_CONCLUSION_EXECUTION_REMOVED = "CONCLUSION_EXECUTION_REMOVED"
AUDIT_EVENT_CONCLUSION_REVISION_CANCELLED = "CONCLUSION_REVISION_CANCELLED"
AUDIT_EVENT_CONCLUSION_REVIEW_REQUIRED = "CONCLUSION_REVIEW_REQUIRED"
# Значения, добавленные к аудит-CHECK миграцией 18 (нужны для downgrade).
QUALITY_AUDIT_EVENT_TYPES_ADDED_IN_18: tuple[str, ...] = (
    AUDIT_EVENT_CONCLUSION_EXECUTION_ADDED,
    AUDIT_EVENT_CONCLUSION_EXECUTION_REMOVED,
    AUDIT_EVENT_CONCLUSION_REVISION_CANCELLED,
    AUDIT_EVENT_CONCLUSION_REVIEW_REQUIRED,
)
QUALITY_AUDIT_EVENT_TYPES: tuple[str, ...] = (
    AUDIT_EVENT_EXECUTION_CREATED,
    AUDIT_EVENT_STATUS_CHANGED,
    AUDIT_EVENT_LABORATORY_CHANGED,
    AUDIT_EVENT_PARTICIPANTS_CHANGED,
    AUDIT_EVENT_TIME_CHANGED,
    AUDIT_EVENT_VOLUME_CHANGED,
    AUDIT_EVENT_COORDINATES_CHANGED,
    AUDIT_EVENT_EVALUATION_CHANGED,
    AUDIT_EVENT_REQUIRED_ACTION_CHANGED,
    AUDIT_EVENT_RESULT_CONFIRMED,
    AUDIT_EVENT_EXECUTION_CANCELLED,
    AUDIT_EVENT_REVISION_CREATED,
    AUDIT_EVENT_REMOVED_RESULT_ITEM,
    AUDIT_EVENT_CONCLUSION_CREATED,
    AUDIT_EVENT_CONCLUSION_COMPOSITION_CHANGED,
    AUDIT_EVENT_CONCLUSION_APPROVED,
    AUDIT_EVENT_CONCLUSION_ISSUED,
    AUDIT_EVENT_CONCLUSION_SUPERSEDED,
    AUDIT_EVENT_CONCLUSION_EXECUTION_ADDED,
    AUDIT_EVENT_CONCLUSION_EXECUTION_REMOVED,
    AUDIT_EVENT_CONCLUSION_REVISION_CANCELLED,
    AUDIT_EVENT_CONCLUSION_REVIEW_REQUIRED,
)


def is_valid_execution_status(status: str) -> bool:
    """Входит ли статус в закрытый набор статусов выполнения (§6)."""
    return status in EXECUTION_STATUSES


def can_transition_execution(current: str, target: str) -> bool:
    """Допустим ли прямой переход статуса выполнения вперёд по цепочке (§6).

    Отмена (→CANCELLED) и замещение (→SUPERSEDED) сюда НЕ входят: это отдельные
    команды со своими инвариантами (тип/причина отмены; появление новой текущей
    редакции). Проверяются в сервисном слое, а не как рядовой шаг lifecycle.
    """
    return target in _FORWARD_TRANSITIONS.get(current, frozenset())


def aggregate_evaluation(evaluations: Iterable[str]) -> str:
    """Агрегирует оценки действующих локальных результатов в оценку выполнения (§11).

    Приоритет худшего результата: NONCONFORMING > INCONCLUSIVE > NOT_EVALUATED >
    CONFORMING. Пустой вход (нет действующих результатов) → NOT_EVALUATED: оценка
    ещё не может быть вынесена. EXCLUDED-результаты исключает вызывающий код (§10.3),
    сюда они не передаются.
    """
    present = set(evaluations)
    for evaluation in _EVALUATION_PRIORITY:
        if evaluation in present:
            return evaluation
    return EVAL_NOT_EVALUATED


def check_time_consistency(
    precision: str,
    *,
    performed_date: date | None,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> str | None:
    """Проверяет непротиворечивость полей времени по точности (§8).

    Возвращает машинный код ошибки или None, если поля согласованы. Система не
    подставляет фиктивное время: недостающие обязательные поля — ошибка.

    * DATE_ONLY — обязателен `performed_date`.
    * START_TIME_KNOWN — обязательны `performed_date` и `started_at`.
    * FULL_INTERVAL — обязательны `started_at` и `finished_at`; `finished_at` не
      раньше `started_at`.
    """
    if precision == TIME_DATE_ONLY:
        if performed_date is None:
            return EXECUTION_PERFORMED_DATE_REQUIRED
        return None
    if precision == TIME_START_KNOWN:
        if performed_date is None:
            return EXECUTION_PERFORMED_DATE_REQUIRED
        if started_at is None:
            return EXECUTION_TIME_START_REQUIRED
        return None
    if precision == TIME_FULL_INTERVAL:
        if started_at is None:
            return EXECUTION_TIME_START_REQUIRED
        if finished_at is None:
            return EXECUTION_TIME_FINISH_REQUIRED
        if finished_at < started_at:
            return EXECUTION_TIME_FINISH_BEFORE_START
        return None
    # Неизвестная точность отсекается схемой-enum раньше; на всякий случай — ошибка.
    return EXECUTION_PERFORMED_DATE_REQUIRED


def is_wraps_zero_allowed(coordinate_system: str) -> bool:
    """Допустим ли `wraps_zero=true` для координатной системы (§10.5).

    Только для замкнутых (кольцевых) систем: мерной пояс, угловой сектор. Для
    разомкнутых (LINEAR_WELD_LENGTH, IMAGE_NUMBER, LOCAL_ZONE, OTHER) — недопустим.
    """
    return coordinate_system in CLOSED_COORDINATE_SYSTEMS


@dataclass(frozen=True)
class ExecutionOutcome:
    """Свёртка одного выполнения для расчёта состояния назначения (§24).

    Только текущие редакции (`is_current`) передаются в `assignment_state`. `status`
    — статус выполнения; `evaluation` — его агрегированная оценка (`aggregate_
    evaluation`); `coverage_complete` — признак полного покрытия соединения этим
    выполнением (COMPLETE по расчёту или заявленной полноте).
    """

    status: str
    evaluation: str
    coverage_complete: bool


def assignment_state(outcomes: Sequence[ExecutionOutcome]) -> str:
    """Вычисляет состояние назначения метода по его текущим выполнениям (§24).

    Учитываются только переданные текущие редакции. Состояние вычисляемое и не
    вводится вручную; оно не создаёт Defect, не запускает ремонт и не является
    решением ОГС/ОТК.

    * нет выполнений → NOT_STARTED;
    * есть выполнения, но ни одно не LAB_CONFIRMED → IN_PROGRESS;
    * есть подтверждённые, но покрытие неполное → PARTIALLY_COMPLETED;
    * покрытие полное — по набору оценок подтверждённых выполнений (решение
      ревью 9C-1: NONCONFORMING имеет приоритет над «смешанным»):
      любой NONCONFORMING → COMPLETED_WITH_NONCONFORMING;
      только CONFORMING → COMPLETED_CONFORMING;
      только INCONCLUSIVE / NOT_EVALUATED → COMPLETED_INCONCLUSIVE;
      CONFORMING вместе с INCONCLUSIVE / NOT_EVALUATED (без NONCONFORMING)
      → COMPLETED_MIXED.
    """
    if not outcomes:
        return ASSIGNMENT_STATE_NOT_STARTED
    confirmed = [o for o in outcomes if o.status == EXEC_LAB_CONFIRMED]
    if not confirmed:
        return ASSIGNMENT_STATE_IN_PROGRESS
    if not all(o.coverage_complete for o in confirmed):
        return ASSIGNMENT_STATE_PARTIALLY_COMPLETED
    evals = {o.evaluation for o in confirmed}
    if EVAL_NONCONFORMING in evals:
        return ASSIGNMENT_STATE_COMPLETED_WITH_NONCONFORMING
    if evals <= {EVAL_CONFORMING}:
        return ASSIGNMENT_STATE_COMPLETED_CONFORMING
    if evals <= {EVAL_INCONCLUSIVE, EVAL_NOT_EVALUATED}:
        return ASSIGNMENT_STATE_COMPLETED_INCONCLUSIVE
    return ASSIGNMENT_STATE_COMPLETED_MIXED


@dataclass(frozen=True)
class CoverageSegment:
    """Нормализованный участок покрытия для анализа полноты (§12).

    `start`/`end` — числовые координаты в ОДНОЙ единице; `wraps_zero` — участок
    замкнутой системы, пересекающий ноль (например, мерной пояс 4800 → 0).
    """

    start: Number
    end: Number
    wraps_zero: bool = False


def analyze_coverage(
    segments: Sequence[CoverageSegment],
    total_length: Number | None,
    *,
    closed: bool,
) -> str:
    """Определяет расчётную полноту покрытия по участкам одного измерения (§12).

    Все участки должны быть в одной единице и относиться к одной измеримой
    геометрии (несовместимые единицы вызывающий код не смешивает — §12). Возвращает
    один из CALCULATED_COMPLETIONS.

    Алгоритм: `wraps_zero`-участки замкнутой системы разбиваются на два по нулю;
    участки сортируются и проверяются на пересечение (OVERLAPPING) и объединяются;
    покрытая длина сравнивается с `total_length` с допуском. Разрывы между
    объединёнными блоками → HAS_GAPS, единый неполный блок → PARTIAL, полное
    совпадение → COMPLETE. Недостаточные/некорректные данные → NOT_CALCULABLE.
    """
    if total_length is None:
        return COMPLETION_NOT_CALCULABLE
    total = Decimal(str(total_length))
    if total <= 0:
        return COMPLETION_NOT_CALCULABLE
    normalized = _normalize_segments(segments, total, closed=closed)
    if normalized is None:
        return COMPLETION_NOT_CALCULABLE
    if not normalized:
        return COMPLETION_PARTIAL

    normalized.sort(key=lambda pair: pair[0])
    covered = Decimal(0)
    overlapping = False
    gap = False
    cur_start, cur_end = normalized[0]
    covered_from = cur_start
    for start, end in normalized[1:]:
        if start < cur_end - _COVERAGE_EPS:
            overlapping = True
            cur_end = max(cur_end, end)
            continue
        if start > cur_end + _COVERAGE_EPS:
            gap = True
        covered += cur_end - cur_start
        cur_start, cur_end = start, end
    covered += cur_end - cur_start
    _ = covered_from  # начало первого блока (для читаемости алгоритма)

    if overlapping:
        return COMPLETION_OVERLAPPING
    if abs(covered - total) <= _COVERAGE_EPS:
        return COMPLETION_COMPLETE
    if gap:
        return COMPLETION_HAS_GAPS
    return COMPLETION_PARTIAL


def _normalize_segments(
    segments: Sequence[CoverageSegment],
    total: Decimal,
    *,
    closed: bool,
) -> list[tuple[Decimal, Decimal]] | None:
    """Разворачивает участки в отрезки [start, end] с учётом wraps_zero.

    Возвращает None при некорректных данных (wraps_zero в разомкнутой системе,
    выход за границы, вырожденный отрезок) — вызывающий трактует как NOT_CALCULABLE.
    """
    result: list[tuple[Decimal, Decimal]] = []
    for seg in segments:
        start = Decimal(str(seg.start))
        end = Decimal(str(seg.end))
        if start < 0 or end < 0 or start > total or end > total:
            return None
        if seg.wraps_zero:
            if not closed:
                return None
            # Замкнутый участок через ноль: [start, total] + [0, end].
            if start <= end:
                return None
            if start < total:
                result.append((start, total))
            if end > 0:
                result.append((Decimal(0), end))
        else:
            if end <= start:
                return None
            result.append((start, end))
    return result
