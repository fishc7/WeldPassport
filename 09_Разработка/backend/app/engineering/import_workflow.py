"""Доменная политика импорта XLSX и разрешения конфликтов (Task 8E, ADR-012 / Session 005).

Чистый доменный компонент без БД и HTTP (как `joint_workflow`,
`weld_operation_workflow`, `weld_operation_corrections`): словари статусов,
причины блокировок, типы решений/происхождения, классификация сопоставления и
дубликатов, категории ошибок, коды доменных ошибок, роли и чистые функции
пересчёта статусов группы/строки.

Ключевые инварианты Task 8E (§2 задания):

* прямая запись данных из XLSX в производственные таблицы запрещена — только через
  staging → matching → conflict resolution → атомарный apply по `ImportGroup`;
* изменение существующей `WeldOperation` через импорт запрещено (это механизм
  Task 8D), изменение существующего `Joint` через импорт запрещено;
* correction/supersede Task 8D здесь не развивается и не дублируется.

Формат кодов — UPPERCASE, как во всём модуле engineering. Native PG enum в проекте
не используются: словари реализуются как `String` + `CHECK ... IN (...)`.
"""

from __future__ import annotations

from typing import Literal

# ══════════════════════════════════════════════════════════════════════════════
# Роли (§3 задания). Роль WELDING_ENGINEER из ТЗ в системе отсутствует и маппится
# на существующую OGS_ENGINEER (инженер ОГС); новых role_code не вводим. Полное
# применение импорта — исключительно CHIEF_WELDER.
# ══════════════════════════════════════════════════════════════════════════════
# Кто может создавать сессию, редактировать staging, разрешать конфликты, отклонять
# и возвращать строки, отменять неприменённые группы/сессию.
IMPORT_ENGINEER_ROLES: frozenset[str] = frozenset({"OGS_ENGINEER", "CHIEF_WELDER"})
# Исключительные права CHIEF_WELDER: запуск apply, возврат сессии из APPLY_FAILED,
# возврат группы из FAILED, отмена после первого частичного применения (§3).
IMPORT_CHIEF_ROLES: frozenset[str] = frozenset({"CHIEF_WELDER"})

# ══════════════════════════════════════════════════════════════════════════════
# Канонический XLSX (§4 задания)
# ══════════════════════════════════════════════════════════════════════════════
# Поддерживаемые версии шаблона. Лимиты (размер/строки/группы) задаются конфигом
# приложения (ImportLimits), здесь — только доменный словарь версий и колонок.
SUPPORTED_TEMPLATE_VERSIONS: frozenset[str] = frozenset({"1.0"})

# Обязательные колонки канонического шаблона (технические ключи; заголовки на
# стороне UI/шаблона). Одна строка = данные Joint + одна WeldOperation.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "project_code",
    "line_code",
    "isometric_no",
    "revision_code",
    "joint_no",
    "weld_stage",
    "welding_method",
    "welder_stamp_code",
    "performed_on",
)

# Необязательные распознаваемые колонки: попадают в нормализованные поля, но их
# отсутствие не является ошибкой структуры.
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "started_at",
    "finished_at",
    "welding_position",
    "shielding_gas",
    "operation_note",
)

KNOWN_COLUMNS: frozenset[str] = frozenset(REQUIRED_COLUMNS) | frozenset(OPTIONAL_COLUMNS)

# ══════════════════════════════════════════════════════════════════════════════
# ImportSession lifecycle (§6 задания)
# ══════════════════════════════════════════════════════════════════════════════
SESSION_UPLOADED = "UPLOADED"
SESSION_PARSING = "PARSING"
SESSION_PARSE_FAILED = "PARSE_FAILED"
SESSION_UNDER_REVIEW = "UNDER_REVIEW"
SESSION_READY_FOR_APPLY = "READY_FOR_APPLY"
SESSION_APPLYING = "APPLYING"
SESSION_PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
SESSION_PARTIALLY_APPLIED_WITH_FAILURES = "PARTIALLY_APPLIED_WITH_FAILURES"
SESSION_APPLY_FAILED = "APPLY_FAILED"
SESSION_COMPLETED = "COMPLETED"
SESSION_CANCELLED = "CANCELLED"

SESSION_STATUSES: tuple[str, ...] = (
    SESSION_UPLOADED,
    SESSION_PARSING,
    SESSION_PARSE_FAILED,
    SESSION_UNDER_REVIEW,
    SESSION_READY_FOR_APPLY,
    SESSION_APPLYING,
    SESSION_PARTIALLY_APPLIED,
    SESSION_PARTIALLY_APPLIED_WITH_FAILURES,
    SESSION_APPLY_FAILED,
    SESSION_COMPLETED,
    SESSION_CANCELLED,
)
# Окончательные статусы сессии (§6): дальнейшие переходы запрещены.
SESSION_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {SESSION_COMPLETED, SESSION_CANCELLED}
)
# Статусы, в которых сессия открыта для правок staging (до apply).
SESSION_EDITABLE_STATUSES: frozenset[str] = frozenset(
    {SESSION_UNDER_REVIEW, SESSION_READY_FOR_APPLY, SESSION_PARTIALLY_APPLIED,
     SESSION_PARTIALLY_APPLIED_WITH_FAILURES}
)

SessionStatus = Literal[
    "UPLOADED", "PARSING", "PARSE_FAILED", "UNDER_REVIEW", "READY_FOR_APPLY",
    "APPLYING", "PARTIALLY_APPLIED", "PARTIALLY_APPLIED_WITH_FAILURES",
    "APPLY_FAILED", "COMPLETED", "CANCELLED",
]

# ══════════════════════════════════════════════════════════════════════════════
# ImportRow lifecycle (§6 задания)
# ══════════════════════════════════════════════════════════════════════════════
ROW_VALIDATION_ERROR = "VALIDATION_ERROR"
ROW_PENDING_MATCH = "PENDING_MATCH"
ROW_MATCH_CONFLICT = "MATCH_CONFLICT"
ROW_DUPLICATE = "DUPLICATE"
ROW_PENDING_RESOLUTION = "PENDING_RESOLUTION"
ROW_RESOLVED_CREATE_NEW = "RESOLVED_CREATE_NEW"
ROW_RESOLVED_LINK_EXISTING = "RESOLVED_LINK_EXISTING"
ROW_RESOLVED_CREATE_NEW_JOINT = "RESOLVED_CREATE_NEW_JOINT"
ROW_READY = "READY"
ROW_APPLIED = "APPLIED"
ROW_SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
ROW_RESOLVED_AS_DUPLICATE = "RESOLVED_AS_DUPLICATE"
ROW_REJECTED = "REJECTED"
ROW_CANCELLED = "CANCELLED"

ROW_STATUSES: tuple[str, ...] = (
    ROW_VALIDATION_ERROR,
    ROW_PENDING_MATCH,
    ROW_MATCH_CONFLICT,
    ROW_DUPLICATE,
    ROW_PENDING_RESOLUTION,
    ROW_RESOLVED_CREATE_NEW,
    ROW_RESOLVED_LINK_EXISTING,
    ROW_RESOLVED_CREATE_NEW_JOINT,
    ROW_READY,
    ROW_APPLIED,
    ROW_SKIPPED_DUPLICATE,
    ROW_RESOLVED_AS_DUPLICATE,
    ROW_REJECTED,
    ROW_CANCELLED,
)
# Конечные статусы строки (§6): после применения строка неизменяема.
ROW_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {ROW_APPLIED, ROW_SKIPPED_DUPLICATE, ROW_RESOLVED_AS_DUPLICATE, ROW_CANCELLED}
)
# Строки, реально создающие производственные данные при apply.
ROW_PRODUCTIVE_STATUSES: frozenset[str] = frozenset(
    {ROW_RESOLVED_CREATE_NEW, ROW_RESOLVED_LINK_EXISTING,
     ROW_RESOLVED_CREATE_NEW_JOINT, ROW_READY}
)
# Строки, исключаемые из применяемой части группы, но не блокирующие её (§9).
ROW_EXCLUDED_FROM_APPLY_STATUSES: frozenset[str] = frozenset(
    {ROW_REJECTED, ROW_SKIPPED_DUPLICATE, ROW_RESOLVED_AS_DUPLICATE, ROW_CANCELLED,
     ROW_APPLIED}
)
# Строки с ошибкой/неразрешённым конфликтом — блокируют группу (§9).
ROW_BLOCKING_STATUSES: frozenset[str] = frozenset(
    {ROW_VALIDATION_ERROR, ROW_PENDING_MATCH, ROW_MATCH_CONFLICT, ROW_DUPLICATE,
     ROW_PENDING_RESOLUTION}
)

RowStatus = Literal[
    "VALIDATION_ERROR", "PENDING_MATCH", "MATCH_CONFLICT", "DUPLICATE",
    "PENDING_RESOLUTION", "RESOLVED_CREATE_NEW", "RESOLVED_LINK_EXISTING",
    "RESOLVED_CREATE_NEW_JOINT", "READY", "APPLIED", "SKIPPED_DUPLICATE",
    "RESOLVED_AS_DUPLICATE", "REJECTED", "CANCELLED",
]

# ══════════════════════════════════════════════════════════════════════════════
# ImportGroup lifecycle (§6, §9 задания)
# ══════════════════════════════════════════════════════════════════════════════
GROUP_PENDING = "PENDING"
GROUP_BLOCKED = "BLOCKED"
GROUP_READY = "READY"
GROUP_APPLYING = "APPLYING"
GROUP_APPLIED = "APPLIED"
GROUP_FAILED = "FAILED"
GROUP_NO_ACTION = "NO_ACTION"
GROUP_EMPTY = "EMPTY"
GROUP_CANCELLED = "CANCELLED"

GROUP_STATUSES: tuple[str, ...] = (
    GROUP_PENDING,
    GROUP_BLOCKED,
    GROUP_READY,
    GROUP_APPLYING,
    GROUP_APPLIED,
    GROUP_FAILED,
    GROUP_NO_ACTION,
    GROUP_EMPTY,
    GROUP_CANCELLED,
)
# Конечные статусы группы (§6): APPLIED, NO_ACTION, EMPTY, CANCELLED.
GROUP_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {GROUP_APPLIED, GROUP_NO_ACTION, GROUP_EMPTY, GROUP_CANCELLED}
)

GroupStatus = Literal[
    "PENDING", "BLOCKED", "READY", "APPLYING", "APPLIED", "FAILED", "NO_ACTION",
    "EMPTY", "CANCELLED",
]

# Целевой тип группы (§6): новый или существующий Joint.
GROUP_TARGET_NEW_JOINT = "NEW_JOINT"
GROUP_TARGET_EXISTING_JOINT = "EXISTING_JOINT"
GROUP_TARGET_TYPES: tuple[str, ...] = (
    GROUP_TARGET_NEW_JOINT,
    GROUP_TARGET_EXISTING_JOINT,
)
GroupTargetType = Literal["NEW_JOINT", "EXISTING_JOINT"]

# ── Причины блокировки группы (§6). Множественные; пересчитываются системой. ────
BLOCK_ROW_VALIDATION_ERROR = "ROW_VALIDATION_ERROR"
BLOCK_UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
BLOCK_PENDING_RECHECK = "PENDING_RECHECK"
BLOCK_NON_RETRYABLE_FAILURE = "NON_RETRYABLE_FAILURE"
GROUP_BLOCK_REASONS: tuple[str, ...] = (
    BLOCK_ROW_VALIDATION_ERROR,
    BLOCK_UNRESOLVED_CONFLICT,
    BLOCK_PENDING_RECHECK,
    BLOCK_NON_RETRYABLE_FAILURE,
)

# ══════════════════════════════════════════════════════════════════════════════
# Сопоставление Joint (§7 задания)
# ══════════════════════════════════════════════════════════════════════════════
MATCH_EXACT = "EXACT_MATCH"
MATCH_NONE = "NO_MATCH"
MATCH_CONFLICT = "CONFLICT"
MATCH_MULTIPLE = "MULTIPLE_MATCHES"
MATCH_CLASSIFICATIONS: tuple[str, ...] = (
    MATCH_EXACT,
    MATCH_NONE,
    MATCH_CONFLICT,
    MATCH_MULTIPLE,
)

# Минимальные коды конфликтов сопоставления (§7).
LINE_MISMATCH = "LINE_MISMATCH"
ISOMETRIC_MISMATCH = "ISOMETRIC_MISMATCH"
REVISION_MISMATCH = "REVISION_MISMATCH"
MULTIPLE_JOINT_MATCHES = "MULTIPLE_JOINT_MATCHES"
MATCH_CONFLICT_CODES: tuple[str, ...] = (
    LINE_MISMATCH,
    ISOMETRIC_MISMATCH,
    REVISION_MISMATCH,
    MULTIPLE_JOINT_MATCHES,
)

# ══════════════════════════════════════════════════════════════════════════════
# Дубликаты WeldOperation (§8 задания)
# ══════════════════════════════════════════════════════════════════════════════
DUP_INTRA_FILE = "INTRA_FILE_DUPLICATE"
DUP_EXISTING_OPERATION = "EXISTING_OPERATION_DUPLICATE"
DUP_EXISTING_CONFLICT = "EXISTING_OPERATION_CONFLICT"
DUPLICATE_TYPES: tuple[str, ...] = (
    DUP_INTRA_FILE,
    DUP_EXISTING_OPERATION,
    DUP_EXISTING_CONFLICT,
)

# ══════════════════════════════════════════════════════════════════════════════
# ImportResolution (§6 задания): принятое решение по конфликту
# ══════════════════════════════════════════════════════════════════════════════
RES_LINK_EXISTING_JOINT = "LINK_EXISTING_JOINT"
RES_CREATE_NEW_JOINT = "CREATE_NEW_JOINT"
RES_MARK_OPERATION_DUPLICATE = "MARK_OPERATION_DUPLICATE"
RES_CREATE_NEW_OPERATION = "CREATE_NEW_OPERATION"
RES_REJECT_ROW = "REJECT_ROW"
RESOLUTION_TYPES: tuple[str, ...] = (
    RES_LINK_EXISTING_JOINT,
    RES_CREATE_NEW_JOINT,
    RES_MARK_OPERATION_DUPLICATE,
    RES_CREATE_NEW_OPERATION,
    RES_REJECT_ROW,
)
ResolutionType = Literal[
    "LINK_EXISTING_JOINT", "CREATE_NEW_JOINT", "MARK_OPERATION_DUPLICATE",
    "CREATE_NEW_OPERATION", "REJECT_ROW",
]

# Статус строки, в который переводит каждый тип решения (§6).
RESOLUTION_ROW_STATUS: dict[str, str] = {
    RES_LINK_EXISTING_JOINT: ROW_RESOLVED_LINK_EXISTING,
    RES_CREATE_NEW_JOINT: ROW_RESOLVED_CREATE_NEW_JOINT,
    RES_MARK_OPERATION_DUPLICATE: ROW_RESOLVED_AS_DUPLICATE,
    RES_CREATE_NEW_OPERATION: ROW_RESOLVED_CREATE_NEW,
    RES_REJECT_ROW: ROW_REJECTED,
}

# ══════════════════════════════════════════════════════════════════════════════
# ImportProvenance (§6 задания): происхождение доменных данных
# ══════════════════════════════════════════════════════════════════════════════
PROV_CREATED = "CREATED"
PROV_MATCHED_EXISTING = "MATCHED_EXISTING"
PROV_SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
PROV_RESOLVED_AS_DUPLICATE = "RESOLVED_AS_DUPLICATE"
PROVENANCE_LINK_TYPES: tuple[str, ...] = (
    PROV_CREATED,
    PROV_MATCHED_EXISTING,
    PROV_SKIPPED_DUPLICATE,
    PROV_RESOLVED_AS_DUPLICATE,
)

# Целевой домен provenance.
PROV_TARGET_JOINT = "JOINT"
PROV_TARGET_WELD_OPERATION = "WELD_OPERATION"
PROVENANCE_TARGET_TYPES: tuple[str, ...] = (
    PROV_TARGET_JOINT,
    PROV_TARGET_WELD_OPERATION,
)

# ══════════════════════════════════════════════════════════════════════════════
# Apply attempt / group result (§6 задания)
# ══════════════════════════════════════════════════════════════════════════════
APPLY_RESULT_APPLIED = "APPLIED"
APPLY_RESULT_FAILED = "FAILED"
APPLY_RESULT_SKIPPED = "SKIPPED"
APPLY_GROUP_RESULT_STATUSES: tuple[str, ...] = (
    APPLY_RESULT_APPLIED,
    APPLY_RESULT_FAILED,
    APPLY_RESULT_SKIPPED,
)

# Итог попытки применения сессии.
ATTEMPT_SUCCEEDED = "SUCCEEDED"
ATTEMPT_PARTIAL = "PARTIAL"
ATTEMPT_FAILED = "FAILED"
APPLY_ATTEMPT_OUTCOMES: tuple[str, ...] = (
    ATTEMPT_SUCCEEDED,
    ATTEMPT_PARTIAL,
    ATTEMPT_FAILED,
)

# Итог попытки разбора (parse).
PARSE_SUCCEEDED = "SUCCEEDED"
PARSE_FAILED_OUTCOME = "FAILED"
PARSE_ATTEMPT_OUTCOMES: tuple[str, ...] = (PARSE_SUCCEEDED, PARSE_FAILED_OUTCOME)

# ══════════════════════════════════════════════════════════════════════════════
# История статусов (§6): единая таблица для session/group/row
# ══════════════════════════════════════════════════════════════════════════════
EVENT_ENTITY_SESSION = "SESSION"
EVENT_ENTITY_GROUP = "GROUP"
EVENT_ENTITY_ROW = "ROW"
EVENT_ENTITY_TYPES: tuple[str, ...] = (
    EVENT_ENTITY_SESSION,
    EVENT_ENTITY_GROUP,
    EVENT_ENTITY_ROW,
)
# Инициатор перехода: пользователь или система.
ACTOR_USER = "USER"
ACTOR_SYSTEM = "SYSTEM"
EVENT_ACTOR_KINDS: tuple[str, ...] = (ACTOR_USER, ACTOR_SYSTEM)

# ══════════════════════════════════════════════════════════════════════════════
# Категории ошибок (§14 задания)
# ══════════════════════════════════════════════════════════════════════════════
ERR_BUSINESS = "BUSINESS"
ERR_VALIDATION = "VALIDATION"
ERR_CONFLICT = "CONFLICT"
ERR_INFRASTRUCTURE = "INFRASTRUCTURE"
ERR_DATABASE = "DATABASE"
ERR_UNEXPECTED = "UNEXPECTED"
ERROR_CATEGORIES: tuple[str, ...] = (
    ERR_BUSINESS,
    ERR_VALIDATION,
    ERR_CONFLICT,
    ERR_INFRASTRUCTURE,
    ERR_DATABASE,
    ERR_UNEXPECTED,
)

# ══════════════════════════════════════════════════════════════════════════════
# Идемпотентность (§13 задания): типы команд
# ══════════════════════════════════════════════════════════════════════════════
CMD_UPLOAD = "UPLOAD"
CMD_REPARSE = "REPARSE"
CMD_EDIT_ROW = "EDIT_ROW"
CMD_RESOLVE = "RESOLVE"
CMD_REJECT_ROW = "REJECT_ROW"
CMD_RETURN_ROW = "RETURN_ROW"
CMD_CANCEL_GROUP = "CANCEL_GROUP"
CMD_CANCEL_SESSION = "CANCEL_SESSION"
CMD_TO_READY_FOR_APPLY = "TO_READY_FOR_APPLY"
CMD_APPLY = "APPLY"
CMD_RETURN_SESSION_AFTER_APPLY_FAILED = "RETURN_SESSION_AFTER_APPLY_FAILED"
CMD_RETURN_GROUP_AFTER_FAILED = "RETURN_GROUP_AFTER_FAILED"
IDEMPOTENT_COMMANDS: tuple[str, ...] = (
    CMD_UPLOAD,
    CMD_REPARSE,
    CMD_EDIT_ROW,
    CMD_RESOLVE,
    CMD_REJECT_ROW,
    CMD_RETURN_ROW,
    CMD_CANCEL_GROUP,
    CMD_CANCEL_SESSION,
    CMD_TO_READY_FOR_APPLY,
    CMD_APPLY,
    CMD_RETURN_SESSION_AFTER_APPLY_FAILED,
    CMD_RETURN_GROUP_AFTER_FAILED,
)
# Область уникальности идемпотентного ключа (§13). UPLOAD — по пользователю; все
# остальные команды — по ImportSession.
IDEMPOTENCY_SCOPE_USER = "USER"
IDEMPOTENCY_SCOPE_SESSION = "SESSION"

# ══════════════════════════════════════════════════════════════════════════════
# Нормализованные staging-поля строки (§6). Изменение этих полей требует комментария
# при ручном редактировании (§6 ImportRowChange).
# ══════════════════════════════════════════════════════════════════════════════
NORMALIZED_FIELDS: tuple[str, ...] = (
    "project_code",
    "line_code",
    "isometric_no",
    "revision_code",
    "joint_no",
    "weld_stage",
    "welding_method",
    "welder_stamp_code",
    "performed_on",
    "started_at",
    "finished_at",
    "welding_position",
    "shielding_gas",
    "operation_note",
)
# Обязательные для непустой строки нормализованные поля (частично заполненная строка
# → VALIDATION_ERROR, §4).
REQUIRED_NORMALIZED_FIELDS: tuple[str, ...] = (
    "line_code",
    "isometric_no",
    "revision_code",
    "joint_no",
    "weld_stage",
    "welding_method",
    "welder_stamp_code",
    "performed_on",
)
# Изменение этих полей обязательно сопровождается комментарием (§6 ImportRowChange).
COMMENT_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"joint_no", "line_code", "isometric_no", "revision_code",
     "welder_stamp_code", "welding_method", "performed_on"}
)

# ══════════════════════════════════════════════════════════════════════════════
# Машинные коды доменных ошибок (§14 задания). Стабильные, UPPERCASE.
# ══════════════════════════════════════════════════════════════════════════════
# Загрузка/парс.
IMPORT_FILE_EXTENSION_INVALID = "IMPORT_FILE_EXTENSION_INVALID"
IMPORT_FILE_MIME_INVALID = "IMPORT_FILE_MIME_INVALID"
IMPORT_FILE_CORRUPT = "IMPORT_FILE_CORRUPT"
IMPORT_TEMPLATE_VERSION_UNSUPPORTED = "IMPORT_TEMPLATE_VERSION_UNSUPPORTED"
IMPORT_MISSING_REQUIRED_COLUMN = "IMPORT_MISSING_REQUIRED_COLUMN"
IMPORT_FILE_TOO_LARGE = "IMPORT_FILE_TOO_LARGE"
IMPORT_TOO_MANY_ROWS = "IMPORT_TOO_MANY_ROWS"
IMPORT_TOO_MANY_GROUPS = "IMPORT_TOO_MANY_GROUPS"
IMPORT_FILE_HASH_MISMATCH = "IMPORT_FILE_HASH_MISMATCH"
IMPORT_REPARSE_NOT_ALLOWED = "IMPORT_REPARSE_NOT_ALLOWED"
IMPORT_PARSE_ALREADY_STAGED = "IMPORT_PARSE_ALREADY_STAGED"
# Состояние сессии/группы/строки.
IMPORT_SESSION_NOT_FOUND = "IMPORT_SESSION_NOT_FOUND"
IMPORT_GROUP_NOT_FOUND = "IMPORT_GROUP_NOT_FOUND"
IMPORT_ROW_NOT_FOUND = "IMPORT_ROW_NOT_FOUND"
IMPORT_SESSION_INVALID_STATE = "IMPORT_SESSION_INVALID_STATE"
IMPORT_GROUP_INVALID_STATE = "IMPORT_GROUP_INVALID_STATE"
IMPORT_ROW_INVALID_STATE = "IMPORT_ROW_INVALID_STATE"
IMPORT_ROW_IMMUTABLE = "IMPORT_ROW_IMMUTABLE"
IMPORT_SESSION_LOCKED_DURING_APPLY = "IMPORT_SESSION_LOCKED_DURING_APPLY"
IMPORT_NOT_READY_FOR_APPLY = "IMPORT_NOT_READY_FOR_APPLY"
IMPORT_NO_READY_GROUPS = "IMPORT_NO_READY_GROUPS"
IMPORT_UNRESOLVED_GROUPS_EXIST = "IMPORT_UNRESOLVED_GROUPS_EXIST"
IMPORT_ROW_VERSION_CONFLICT = "IMPORT_ROW_VERSION_CONFLICT"
IMPORT_GROUP_VERSION_CONFLICT = "IMPORT_GROUP_VERSION_CONFLICT"
IMPORT_SESSION_VERSION_CONFLICT = "IMPORT_SESSION_VERSION_CONFLICT"
# Разрешение конфликтов/комментарии.
IMPORT_COMMENT_REQUIRED = "IMPORT_COMMENT_REQUIRED"
IMPORT_RESOLUTION_NOT_APPLICABLE = "IMPORT_RESOLUTION_NOT_APPLICABLE"
IMPORT_RESOLUTION_TARGET_REQUIRED = "IMPORT_RESOLUTION_TARGET_REQUIRED"
IMPORT_RESOLUTION_TARGET_INVALID = "IMPORT_RESOLUTION_TARGET_INVALID"
IMPORT_FIELD_NOT_EDITABLE = "IMPORT_FIELD_NOT_EDITABLE"
# Отмена/возврат.
IMPORT_CANCEL_NOT_ALLOWED = "IMPORT_CANCEL_NOT_ALLOWED"
IMPORT_RETURN_NOT_ALLOWED = "IMPORT_RETURN_NOT_ALLOWED"
IMPORT_GROUP_RETURN_NOT_RETRYABLE = "IMPORT_GROUP_RETURN_NOT_RETRYABLE"
# Права/идемпотентность.
IMPORT_ROLE_DENIED = "IMPORT_ROLE_DENIED"
IMPORT_APPLY_ROLE_DENIED = "IMPORT_APPLY_ROLE_DENIED"
IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD = (
    "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
)
# Применение.
IMPORT_APPLY_FAILED = "IMPORT_APPLY_FAILED"


# ══════════════════════════════════════════════════════════════════════════════
# Чистые функции пересчёта статусов группы (§9 задания)
# ══════════════════════════════════════════════════════════════════════════════
def group_block_reasons(row_statuses: list[str]) -> list[str]:
    """Причины блокировки группы по статусам её активных строк (§6, §9).

    Множественные причины; порядок стабильный (по кортежу GROUP_BLOCK_REASONS).
    NON_RETRYABLE_FAILURE вычисляется отдельно (по failure-результату), здесь —
    только причины уровня строк."""
    reasons: set[str] = set()
    for status in row_statuses:
        if status == ROW_VALIDATION_ERROR:
            reasons.add(BLOCK_ROW_VALIDATION_ERROR)
        elif status in (ROW_MATCH_CONFLICT, ROW_DUPLICATE, ROW_PENDING_RESOLUTION):
            reasons.add(BLOCK_UNRESOLVED_CONFLICT)
        elif status == ROW_PENDING_MATCH:
            reasons.add(BLOCK_PENDING_RECHECK)
    return [r for r in GROUP_BLOCK_REASONS if r in reasons]


def compute_group_status(row_statuses: list[str]) -> tuple[str, list[str]]:
    """Пересчёт статуса неприменённой группы по статусам её строк (§9).

    Возвращает (status, block_reasons). Правила:
      * нет ни одной строки → EMPTY;
      * нет активных (все конечные) строк → EMPTY;
      * есть блокирующая строка → BLOCKED + причины;
      * все активные урегулированы, но ни одна не создаёт данные → NO_ACTION;
      * есть хотя бы одна продуктивная строка и нет блокировок → READY.
    Терминальные/APPLYING статусы этой функцией не выставляются."""
    if not row_statuses:
        return GROUP_EMPTY, []
    active = [s for s in row_statuses if s not in ROW_TERMINAL_STATUSES]
    if not active:
        return GROUP_EMPTY, []
    blocking = [s for s in active if s in ROW_BLOCKING_STATUSES]
    if blocking:
        return GROUP_BLOCKED, group_block_reasons(active)
    productive = [s for s in active if s in ROW_PRODUCTIVE_STATUSES]
    if not productive:
        return GROUP_NO_ACTION, []
    return GROUP_READY, []


def resolution_requires_target(resolution_type: str) -> bool:
    """Требует ли тип решения выбранный целевой Joint/WeldOperation (§6)."""
    return resolution_type in (RES_LINK_EXISTING_JOINT, RES_MARK_OPERATION_DUPLICATE)


def comment_required_for_fields(fields: list[str]) -> bool:
    """Обязателен ли комментарий при изменении набора staging-полей (§6)."""
    return bool(set(fields) & COMMENT_REQUIRED_FIELDS)


def session_status_after_apply(
    total_groups: int,
    applied: int,
    failed: int,
    remaining_actionable: int,
    infra_stopped: bool,
) -> str:
    """Итоговый статус сессии после попытки применения (§10 задания).

    * COMPLETED — все группы имеют конечный результат (ничего не осталось);
    * APPLY_FAILED — успешных групп нет и применение остановлено техническим сбоем;
    * PARTIALLY_APPLIED_WITH_FAILURES — часть применена и есть FAILED-группы;
    * PARTIALLY_APPLIED — часть применена, остаются необработанные группы.
    """
    if remaining_actionable == 0 and failed == 0:
        return SESSION_COMPLETED
    if applied == 0 and infra_stopped and failed == 0:
        return SESSION_APPLY_FAILED
    if failed > 0:
        return SESSION_PARTIALLY_APPLIED_WITH_FAILURES
    return SESSION_PARTIALLY_APPLIED
