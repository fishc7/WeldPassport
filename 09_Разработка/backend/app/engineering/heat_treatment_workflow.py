"""Доменная политика термической обработки сварных соединений (Task 8F).

Чистый доменный компонент по образцу ``weld_operation_workflow`` и
``weld_operation_review``: словари статусов/результатов, роли, машинные коды
ошибок и pure-функции переходов и автоматической проверки. Без обращения к БД и
HTTP — только константы и вычисления.

Термическая обработка моделируется двумя сущностями (§3 задания Task 8F):

* ``HeatTreatmentBatch`` — общий фактически выполненный цикл, охватывающий один и
  более ``Joint``;
* ``HeatTreatmentOperation`` — участие одного ``Joint`` в одном цикле.

Технологическая карта термообработки в коде — нейтральная сущность
``HeatTreatmentProcedureRevision`` (не ``WPS``: WPS уже означает технологию
сварки, §4). Форматы кодов — UPPERCASE, как во всём модуле engineering.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

# ── Технологическая карта: жизненный цикл минимальной ссылочной сущности ───────
# Минимальная редакция карты (§4, §13): к циклу можно привязать только
# утверждённую (APPROVED) и не отменённую редакцию. Полный редактор карт в
# Task 8F не реализуется.
PROCEDURE_REVISION_STATUSES: tuple[str, ...] = ("DRAFT", "APPROVED", "CANCELLED")
ProcedureRevisionStatus = Literal["DRAFT", "APPROVED", "CANCELLED"]

# ── Жизненный цикл цикла термообработки (§6) ──────────────────────────────────
BATCH_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED",
    "REVIEWED",
    "CLOSED",
    "CANCELLED",
    "REJECTED",
)
BatchStatus = Literal[
    "DRAFT",
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED",
    "REVIEWED",
    "CLOSED",
    "CANCELLED",
    "REJECTED",
]

# Разрешённые переходы (§6). Основной путь плюс отмена черновика/плана и
# отклонение завершённого цикла ОГС.
BATCH_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"PLANNED", "CANCELLED"}),
    "PLANNED": frozenset({"IN_PROGRESS", "CANCELLED"}),
    "IN_PROGRESS": frozenset({"COMPLETED"}),
    "COMPLETED": frozenset({"REVIEWED", "REJECTED"}),
    "REVIEWED": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
}
# Терминальные статусы: обычного редактирования и переходов дальше нет (§6).
BATCH_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"CLOSED", "CANCELLED", "REJECTED"}
)
# Статусы, в которых состав цикла ещё можно менять (§14). После IN_PROGRESS
# состав заблокирован.
BATCH_COMPOSITION_EDITABLE_STATUSES: frozenset[str] = frozenset({"DRAFT", "PLANNED"})


def batch_transition_allowed(current: str, target: str) -> bool:
    """Разрешён ли переход общего цикла ``current -> target`` (§6)."""
    return target in BATCH_TRANSITIONS.get(current, frozenset())


# ── Инженерный результат общего цикла (§7) ────────────────────────────────────
BATCH_REVIEW_RESULTS: tuple[str, ...] = (
    "PENDING",
    "ACCEPTED",
    "ACCEPTED_WITH_JUSTIFICATION",
    "REJECTED",
)
BatchReviewResult = Literal[
    "PENDING", "ACCEPTED", "ACCEPTED_WITH_JUSTIFICATION", "REJECTED"
]
# Результаты, при которых цикл допускается перевести в REVIEWED (§7).
BATCH_REVIEW_ACCEPTED_RESULTS: frozenset[str] = frozenset(
    {"ACCEPTED", "ACCEPTED_WITH_JUSTIFICATION"}
)

# ── Причина термообработки соединения (§9) ────────────────────────────────────
OPERATION_REASONS: tuple[str, ...] = (
    "AFTER_INITIAL_WELD",
    "AFTER_REWELD",
    "AFTER_REPAIR",
    "REPEAT_AFTER_REJECTION",
    "OTHER",
)
OperationReason = Literal[
    "AFTER_INITIAL_WELD",
    "AFTER_REWELD",
    "AFTER_REPAIR",
    "REPEAT_AFTER_REJECTION",
    "OTHER",
]
# Причина, требующая ссылки на предыдущую операцию (§9, §20).
REASON_REQUIRES_PREVIOUS = "REPEAT_AFTER_REJECTION"

# ── Статус выполнения операции по соединению (§10) ────────────────────────────
OPERATION_STATUSES: tuple[str, ...] = (
    "PLANNED",
    "INCLUDED",
    "PROCESSED",
    "EVALUATED",
    "EXCLUDED",
)
OperationStatus = Literal["PLANNED", "INCLUDED", "PROCESSED", "EVALUATED", "EXCLUDED"]
# Операции, достигшие PROCESSED, считаются фактически выполненными тепловыми
# циклами (§20), в т.ч. отклонённые. Исключённые до нагрева — нет.
OPERATION_PROCESSED_OR_LATER: frozenset[str] = frozenset({"PROCESSED", "EVALUATED"})

# ── Индивидуальный результат по соединению (§11) ──────────────────────────────
OPERATION_RESULTS: tuple[str, ...] = (
    "PENDING",
    "ACCEPTED",
    "ACCEPTED_WITH_JUSTIFICATION",
    "REJECTED",
    "NOT_APPLICABLE",
)
OperationResult = Literal[
    "PENDING", "ACCEPTED", "ACCEPTED_WITH_JUSTIFICATION", "REJECTED", "NOT_APPLICABLE"
]
OPERATION_ACCEPTED_RESULTS: frozenset[str] = frozenset(
    {"ACCEPTED", "ACCEPTED_WITH_JUSTIFICATION"}
)

# ── Достаточность подтверждающих данных (§12) ─────────────────────────────────
EVIDENCE_SUFFICIENCY_VALUES: tuple[str, ...] = (
    "NOT_EVALUATED",
    "SUFFICIENT",
    "PARTIALLY_SUFFICIENT",
    "INSUFFICIENT",
)
EvidenceSufficiency = Literal[
    "NOT_EVALUATED", "SUFFICIENT", "PARTIALLY_SUFFICIENT", "INSUFFICIENT"
]

# ── Предварительная автоматическая проверка цикла (§17) ───────────────────────
AUTO_CHECK_RESULTS: tuple[str, ...] = (
    "NOT_CHECKED",
    "COMPLIANT",
    "DEVIATION_DETECTED",
    "INSUFFICIENT_DATA",
)
AutoCheckResult = Literal[
    "NOT_CHECKED", "COMPLIANT", "DEVIATION_DETECTED", "INSUFFICIENT_DATA"
]

# ── Документы термообработки (§18) ────────────────────────────────────────────
RECORD_TYPES: tuple[str, ...] = ("TEMPERATURE_CHART", "PROTOCOL", "ACT", "OTHER")
RecordType = Literal["TEMPERATURE_CHART", "PROTOCOL", "ACT", "OTHER"]
RECORD_STATUSES: tuple[str, ...] = ("UPLOADED", "VERIFIED", "REJECTED")
RecordStatus = Literal["UPLOADED", "VERIFIED", "REJECTED"]

# ── Отклонения (§19) ──────────────────────────────────────────────────────────
# Тип отклонения — минимальный доменный набор (в задании не перечислен явно).
DEVIATION_TYPES: tuple[str, ...] = (
    "TEMPERATURE",
    "SOAK_DURATION",
    "HEATING_RATE",
    "COOLING_RATE",
    "MISSING_DATA",
    "EQUIPMENT",
    "OTHER",
)
DeviationType = Literal[
    "TEMPERATURE",
    "SOAK_DURATION",
    "HEATING_RATE",
    "COOLING_RATE",
    "MISSING_DATA",
    "EQUIPMENT",
    "OTHER",
]
DEVIATION_SEVERITIES: tuple[str, ...] = ("MINOR", "MAJOR", "CRITICAL")
DeviationSeverity = Literal["MINOR", "MAJOR", "CRITICAL"]
DEVIATION_STATUSES: tuple[str, ...] = (
    "OPEN",
    "UNDER_REVIEW",
    "RESOLVED",
    "CANCELLED",
)
DeviationStatus = Literal["OPEN", "UNDER_REVIEW", "RESOLVED", "CANCELLED"]
DEVIATION_OGS_DECISIONS: tuple[str, ...] = (
    "NO_IMPACT",
    "CORRECTED_DURING_PROCESS",
    "ACCEPTED_WITH_JUSTIFICATION",
    "REQUIRES_REPEAT_HEAT_TREATMENT",
    "REJECTED",
)
DeviationOgsDecision = Literal[
    "NO_IMPACT",
    "CORRECTED_DURING_PROCESS",
    "ACCEPTED_WITH_JUSTIFICATION",
    "REQUIRES_REPEAT_HEAT_TREATMENT",
    "REJECTED",
]
# Открытыми значимыми считаются отклонения MAJOR/CRITICAL в статусе OPEN/
# UNDER_REVIEW: пока они есть, цикл нельзя закрыть (§19, §22 REVIEWED→CLOSED).
DEVIATION_OPEN_STATUSES: frozenset[str] = frozenset({"OPEN", "UNDER_REVIEW"})
DEVIATION_SIGNIFICANT_SEVERITIES: frozenset[str] = frozenset({"MAJOR", "CRITICAL"})
# Критические отклонения блокируют переход COMPLETED→REVIEWED, пока не рассмотрены.
DEVIATION_CRITICAL_SEVERITIES: frozenset[str] = frozenset({"CRITICAL"})

# ── Вычисляемое состояние требования термообработки по Joint (§23) ────────────
JOINT_HT_STATES: tuple[str, ...] = (
    "NOT_REQUIRED",
    "NOT_DETERMINED",
    "NOT_STARTED",
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED_NOT_ACCEPTED",
    "ACCEPTED",
    "REJECTED",
)
JointHeatTreatmentState = Literal[
    "NOT_REQUIRED",
    "NOT_DETERMINED",
    "NOT_STARTED",
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED_NOT_ACCEPTED",
    "ACCEPTED",
    "REJECTED",
]

# ── Роли (§21; канонические role_code проекта, новых не вводим) ────────────────
# Оператор/мастер/прораб: создание, состав, планирование, запуск, фактические
# параметры, завершение, загрузка документов, регистрация отклонений. Совпадает с
# набором ролей действия WeldOperation (Task 8A).
HT_ACTOR_ROLES: frozenset[str] = frozenset({"MASTER", "FOREMAN", "CHIEF_WELDER"})
# Инженерный результат термообработки принимает ОГС или главный сварщик (§21).
# WELDING_ENGINEER в каноне ролей проекта отсутствует — используем OGS_ENGINEER
# (тот же принцип, что review WeldOperation Task 8C).
HT_REVIEW_ROLES: frozenset[str] = frozenset({"OGS_ENGINEER", "CHIEF_WELDER"})
# ОТК просматривает цикл/документы и может регистрировать отклонения, но не
# принимает инженерный результат (§21).
HT_DEVIATION_ROLES: frozenset[str] = frozenset(
    {"MASTER", "FOREMAN", "OTK_INSPECTOR", "CHIEF_WELDER"}
)

# ── Машинные коды доменных ошибок (§27) ───────────────────────────────────────
# HTTP-семантика: 403 — роль/scope; 404 — объект не найден; 409 — недопустимый
# переход/состояние/конфликт версии; 422 — структурно недопустимая команда.
HT_NOT_FOUND = "HEAT_TREATMENT_NOT_FOUND"
HT_PROJECT_SCOPE_VIOLATION = "HEAT_TREATMENT_PROJECT_SCOPE_VIOLATION"
HT_INVALID_TRANSITION = "HEAT_TREATMENT_INVALID_TRANSITION"
HT_PROCEDURE_NOT_APPROVED = "HEAT_TREATMENT_PROCEDURE_NOT_APPROVED"
HT_PROCEDURE_NOT_APPLICABLE = "HEAT_TREATMENT_PROCEDURE_NOT_APPLICABLE"
HT_PROCEDURE_REQUIRED = "HEAT_TREATMENT_PROCEDURE_REQUIRED"
HT_EMPTY_COMPOSITION = "HEAT_TREATMENT_EMPTY_COMPOSITION"
HT_COMPOSITION_LOCKED = "HEAT_TREATMENT_COMPOSITION_LOCKED"
HT_DUPLICATE_JOINT = "HEAT_TREATMENT_DUPLICATE_JOINT"
HT_WELD_OPERATION_MISMATCH = "HEAT_TREATMENT_WELD_OPERATION_MISMATCH"
HT_WELD_OPERATION_NOT_ELIGIBLE = "HEAT_TREATMENT_WELD_OPERATION_NOT_ELIGIBLE"
HT_INSUFFICIENT_ACTUAL_DATA = "HEAT_TREATMENT_INSUFFICIENT_ACTUAL_DATA"
HT_NO_VERIFIED_CHART = "HEAT_TREATMENT_NO_VERIFIED_CHART"
HT_CHART_REQUIRED = "HEAT_TREATMENT_CHART_REQUIRED"
HT_REVIEW_ROLE_DENIED = "HEAT_TREATMENT_REVIEW_ROLE_DENIED"
HT_ACCEPT_INSUFFICIENT_EVIDENCE = "HEAT_TREATMENT_ACCEPT_INSUFFICIENT_EVIDENCE"
HT_OPEN_DEVIATIONS = "HEAT_TREATMENT_OPEN_DEVIATIONS"
HT_BATCH_LOCKED = "HEAT_TREATMENT_BATCH_LOCKED"
HT_REPEAT_WITHOUT_PREVIOUS = "HEAT_TREATMENT_REPEAT_WITHOUT_PREVIOUS"
HT_JUSTIFICATION_REQUIRED = "HEAT_TREATMENT_JUSTIFICATION_REQUIRED"
HT_RESULT_NOT_ALLOWED = "HEAT_TREATMENT_RESULT_NOT_ALLOWED"
HT_OPERATION_NOT_PROCESSED = "HEAT_TREATMENT_OPERATION_NOT_PROCESSED"
HT_VERSION_CONFLICT = "HEAT_TREATMENT_VERSION_CONFLICT"
HT_REVIEW_RESULT_REQUIRED = "HEAT_TREATMENT_REVIEW_RESULT_REQUIRED"
HT_PENDING_OPERATION_RESULTS = "HEAT_TREATMENT_PENDING_OPERATION_RESULTS"
HT_UNPROCESSED_OPERATIONS = "HEAT_TREATMENT_UNPROCESSED_OPERATIONS"
HT_EXCLUDE_REASON_REQUIRED = "HEAT_TREATMENT_EXCLUDE_REASON_REQUIRED"


# ── Результат оценки достаточности данных и результата (§12) ───────────────────


def result_allowed_for_evidence(evidence: str, result: str) -> bool:
    """Согласованность индивидуального результата и достаточности данных (§12).

    * ``SUFFICIENT`` допускает любой результат, включая ``ACCEPTED``.
    * ``PARTIALLY_SUFFICIENT`` — только ``ACCEPTED_WITH_JUSTIFICATION``,
      ``REJECTED`` или ``NOT_APPLICABLE`` (чистый ``ACCEPTED`` запрещён).
    * ``INSUFFICIENT`` — запрещает ``ACCEPTED`` и ``ACCEPTED_WITH_JUSTIFICATION``.
    * ``NOT_EVALUATED`` — допускает только ``PENDING`` (оценка ещё не выполнена).
    """
    if result == "PENDING":
        return True
    if evidence == "NOT_EVALUATED":
        return False
    if evidence == "SUFFICIENT":
        return True
    if evidence == "PARTIALLY_SUFFICIENT":
        return result in {"ACCEPTED_WITH_JUSTIFICATION", "REJECTED", "NOT_APPLICABLE"}
    if evidence == "INSUFFICIENT":
        return result in {"REJECTED", "NOT_APPLICABLE"}
    return False


# ── Автоматическая проверка фактических данных против снимка карты (§17) ───────


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


def evaluate_auto_check(
    snapshot: dict | None,
    *,
    actual_soak_temperature,
    actual_min_temperature,
    actual_max_temperature,
    actual_soak_duration_minutes,
    actual_heating_rate,
    actual_cooling_rate,
    has_required_document: bool,
) -> tuple[str, list[str]]:
    """Сравнивает фактические параметры со снимком требований карты (§17).

    Возвращает ``(result, deviations)``:

    * ``INSUFFICIENT_DATA`` — снимок отсутствует, не заполнены обязательные
      фактические параметры или нет обязательного подтверждающего документа;
    * ``DEVIATION_DETECTED`` — обнаружено хотя бы одно отклонение от снимка;
    * ``COMPLIANT`` — данные полны и в допуске.

    Проверяются минимум: температура, продолжительность выдержки, скорость
    нагрева, скорость охлаждения, полнота обязательных параметров и наличие
    обязательного документа. Проверка не заменяет решение ОГС (§17).
    """
    deviations: list[str] = []

    soak_temp = _to_decimal(actual_soak_temperature)
    duration = actual_soak_duration_minutes
    heating_rate = _to_decimal(actual_heating_rate)
    cooling_rate = _to_decimal(actual_cooling_rate)

    # Полнота обязательных фактических параметров (§16, §17).
    required_present = (
        soak_temp is not None
        and duration is not None
        and heating_rate is not None
        and cooling_rate is not None
    )
    if snapshot is None or not required_present or not has_required_document:
        return "INSUFFICIENT_DATA", ["INSUFFICIENT_DATA"]

    min_temp = _to_decimal(snapshot.get("min_temperature"))
    max_temp = _to_decimal(snapshot.get("max_temperature"))
    req_duration = snapshot.get("soak_duration_minutes")
    max_heating = _to_decimal(snapshot.get("max_heating_rate"))
    max_cooling = _to_decimal(snapshot.get("max_cooling_rate"))

    if min_temp is not None and soak_temp < min_temp:
        deviations.append("TEMPERATURE_BELOW_MIN")
    if max_temp is not None and soak_temp > max_temp:
        deviations.append("TEMPERATURE_ABOVE_MAX")
    if req_duration is not None and duration < req_duration:
        deviations.append("SOAK_DURATION_TOO_SHORT")
    if max_heating is not None and heating_rate > max_heating:
        deviations.append("HEATING_RATE_TOO_HIGH")
    if max_cooling is not None and cooling_rate > max_cooling:
        deviations.append("COOLING_RATE_TOO_HIGH")

    if deviations:
        return "DEVIATION_DETECTED", deviations
    return "COMPLIANT", []


# ── Вычисление состояния требования термообработки по Joint (§23) ──────────────


def joint_state_from_current(
    *,
    heat_treatment_required: bool,
    has_current_operation: bool,
    batch_status: str | None,
    operation_status: str | None,
    operation_result: str | None,
) -> str:
    """Выводит состояние требования термообработки по актуальной операции (§23).

    ``has_current_operation`` — есть ли для Joint актуальная (не устаревшая по
    новой сварке/ремонту) ``HeatTreatmentOperation``; при её отсутствии для
    требуемой обработки — ``NOT_STARTED``. Остальные значения выводятся из статуса
    цикла, статуса операции и её индивидуального результата.
    """
    if not heat_treatment_required:
        return "NOT_REQUIRED"
    if not has_current_operation:
        return "NOT_STARTED"

    # Исключённая до нагрева операция не считается фактическим циклом (§10, §20).
    if operation_status == "EXCLUDED":
        return "NOT_STARTED"
    if operation_status in ("PLANNED", "INCLUDED"):
        if batch_status == "IN_PROGRESS":
            return "IN_PROGRESS"
        return "PLANNED"
    if operation_status == "PROCESSED":
        return "COMPLETED_NOT_ACCEPTED"
    if operation_status == "EVALUATED":
        if operation_result in OPERATION_ACCEPTED_RESULTS and batch_status in (
            "REVIEWED",
            "CLOSED",
        ):
            return "ACCEPTED"
        if operation_result == "REJECTED" or batch_status == "REJECTED":
            return "REJECTED"
        # NOT_APPLICABLE или незакрытый цикл — считаем ещё не принятым.
        return "COMPLETED_NOT_ACCEPTED"
    return "NOT_STARTED"


def dependent_steps_ready(joint_ht_state: str) -> bool:
    """Готов ли Joint к зависимым этапам (контроль/закрытие) по требованию ТО (§24).

    Если термообработка не требуется — зависимые этапы доступны. Если требуется —
    только когда актуальная операция принята и общий цикл проверен/закрыт
    (``joint_ht_state == "ACCEPTED"``)."""
    if joint_ht_state == "NOT_REQUIRED":
        return True
    return joint_ht_state == "ACCEPTED"
