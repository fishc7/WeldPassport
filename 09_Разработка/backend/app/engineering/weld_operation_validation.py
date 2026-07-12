"""Автоматическая техническая проверка WeldOperation (Task 8B, ADR-012).

Чистый доменный компонент: воспроизводимо считает результат проверки допуска
сварщика и WPS для одной операции. Не зависит от HTTP и БД — на вход подаются
нормализованные значения и список кандидатов допуска (`AdmissionCandidate`),
на выход отдаётся результат с машинными кодами. Task 8B ничего не решает от имени
ОГС и не изменяет производственный факт: результат информационный (§4 задания).

Границы адаптации к текущей модели `welding.welder_admissions` (архитектурное
решение владельца, Task 8B):

* модель допуска не содержит колонки `positions` — реальный DB-путь передаёт
  `positions=()`, поэтому `POSITION_NOT_COVERED` на боевых данных не возникает;
  логика положения сохранена в чистом компоненте и покрыта unit-тестами;
* модель допуска не содержит project scope — реальный DB-путь передаёт
  `project_id=None` (глобальный допуск); приоритет «проектный > глобальный»
  сохранён в чистом компоненте и покрыт unit-тестами.

Изменять `welder_admissions` в Task 8B запрещено (§3.2, §20 задания).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Sequence
from uuid import UUID

# ── Статусы результата (§2, §11 задания) ──────────────────────────────────────
# Одинаковый набор для допуска и WPS, но хранятся раздельно (§11: не общий статус).
VALIDATION_STATUSES: tuple[str, ...] = ("NOT_CHECKED", "PASS", "FAIL", "INDETERMINATE")
QualificationValidationStatus = Literal["NOT_CHECKED", "PASS", "FAIL", "INDETERMINATE"]
WpsValidationStatus = Literal["NOT_CHECKED", "PASS", "FAIL", "INDETERMINATE"]

# Версия алгоритма автоматической проверки (§5.1). Растёт при изменении правил.
VALIDATION_SOURCE_VERSION = 1

# ── Канонические коды допуска (§6.1) ──────────────────────────────────────────
WELDER_NOT_SPECIFIED = "WELDER_NOT_SPECIFIED"
WELDER_PROFILE_NOT_FOUND = "WELDER_PROFILE_NOT_FOUND"
WELDER_PROFILE_INACTIVE = "WELDER_PROFILE_INACTIVE"
NO_ACTIVE_ADMISSION = "NO_ACTIVE_ADMISSION"
ADMISSION_NOT_YET_VALID = "ADMISSION_NOT_YET_VALID"
ADMISSION_EXPIRED = "ADMISSION_EXPIRED"
METHOD_NOT_COVERED = "METHOD_NOT_COVERED"
POSITION_NOT_COVERED = "POSITION_NOT_COVERED"
DN_NOT_COVERED = "DN_NOT_COVERED"
THICKNESS_NOT_COVERED = "THICKNESS_NOT_COVERED"
MATERIAL_GROUP_NOT_CHECKABLE = "MATERIAL_GROUP_NOT_CHECKABLE"
JOINT_DATA_INCOMPLETE = "JOINT_DATA_INCOMPLETE"

# Детерминированный порядок кодов допуска (§6.1: порядок должен быть стабилен).
_QUALIFICATION_CODE_ORDER: tuple[str, ...] = (
    WELDER_NOT_SPECIFIED,
    WELDER_PROFILE_NOT_FOUND,
    WELDER_PROFILE_INACTIVE,
    NO_ACTIVE_ADMISSION,
    ADMISSION_NOT_YET_VALID,
    ADMISSION_EXPIRED,
    METHOD_NOT_COVERED,
    POSITION_NOT_COVERED,
    DN_NOT_COVERED,
    THICKNESS_NOT_COVERED,
    MATERIAL_GROUP_NOT_CHECKABLE,
    JOINT_DATA_INCOMPLETE,
)

# ── Канонические коды WPS (§6.2) ──────────────────────────────────────────────
PLANNED_WPS_MISSING = "PLANNED_WPS_MISSING"
ACTUAL_WPS_MISSING = "ACTUAL_WPS_MISSING"
WPS_MISMATCH = "WPS_MISMATCH"
REQUIRED_METHOD_MISSING = "REQUIRED_METHOD_MISSING"
ACTUAL_METHOD_MISMATCH = "ACTUAL_METHOD_MISMATCH"
UNKNOWN_WELD_STAGE = "UNKNOWN_WELD_STAGE"

_WPS_CODE_ORDER: tuple[str, ...] = (
    PLANNED_WPS_MISSING,
    ACTUAL_WPS_MISSING,
    WPS_MISMATCH,
    REQUIRED_METHOD_MISSING,
    ACTUAL_METHOD_MISMATCH,
    UNKNOWN_WELD_STAGE,
)

# Соответствие «этап → проектный метод Joint» (§9.1). Этапы вне словаря не имеют
# канонического проектного метода → UNKNOWN_WELD_STAGE.
STAGE_REQUIRED_METHOD_FIELD: dict[str, str] = {
    "ROOT": "required_root_method",
    "FILL": "required_fill_method",
    "CAP": "required_cap_method",
}


def _norm(value: str) -> str:
    """Нормализация технологического значения: strip + uppercase (§7.4, §9.3)."""
    return str(value).strip().upper()


def _order(codes, order: tuple[str, ...]) -> list[str]:
    """Уникальные коды в детерминированном каноническом порядке."""
    present = set(codes)
    return [code for code in order if code in present]


def _dec(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


# ── Входные представления (нормализованные, без ORM) ──────────────────────────


@dataclass(frozen=True)
class WelderProfileView:
    """Минимальный снимок профиля сварщика для проверки (§7.2)."""

    active: bool


@dataclass(frozen=True)
class AdmissionCandidate:
    """Нормализованный кандидат допуска — вход чистого валидатора.

    Реальный DB-путь строит его из `welding.welder_admissions` (см. сервис),
    подставляя `positions=()` и `project_id=None` из-за границ текущей модели.
    Unit-тесты конструируют кандидатов напрямую, включая positions/project scope.
    """

    id: UUID
    status: str
    validity_from: date
    validity_to: date | None
    methods: Sequence[str] = ()
    positions: Sequence[str] = ()
    material_groups: Sequence[str] = ()
    dn_min: Decimal | None = None
    dn_max: Decimal | None = None
    thickness_min: Decimal | None = None
    thickness_max: Decimal | None = None
    project_id: UUID | None = None
    worker_id: int | None = None
    welder_id: UUID | None = None


# ── Результаты ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QualificationResult:
    status: str
    codes: list[str] = field(default_factory=list)
    admission_id: UUID | None = None
    snapshot: dict | None = None


@dataclass(frozen=True)
class WpsResult:
    status: str
    codes: list[str]
    snapshot: dict


@dataclass(frozen=True)
class WeldOperationValidationResult:
    qualification: QualificationResult
    wps: WpsResult


# ── Проверка допуска (§7-8) ───────────────────────────────────────────────────


def _project_compatible(candidate_project: UUID | None, joint_project: UUID | None) -> bool:
    """Глобальный допуск (project_id IS NULL) — для любого проекта; проектный —
    только для своего (§7.3)."""
    return candidate_project is None or candidate_project == joint_project


def _valid_on(candidate: AdmissionCandidate, performed_on: date) -> bool:
    """Период действия включительно на дату сварки (§7.1)."""
    if candidate.validity_from > performed_on:
        return False
    return candidate.validity_to is None or candidate.validity_to >= performed_on


def _priority_key(candidate: AdmissionCandidate, joint_project: UUID | None):
    """Детерминированный приоритет выбора допуска (§7.3): проектный раньше
    глобального; затем более поздняя validity_from; затем стабильно по UUID."""
    project_specific = (
        candidate.project_id is not None and candidate.project_id == joint_project
    )
    return (
        0 if project_specific else 1,
        -candidate.validity_from.toordinal(),
        str(candidate.id),
    )


def _within(value: Decimal, low: Decimal | None, high: Decimal | None) -> bool:
    """Значение в диапазоне включительно; отсутствующая граница не ограничивает."""
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def _coverage_fail_codes(
    candidate: AdmissionCandidate,
    *,
    welding_method: str,
    welding_position: str | None,
    dn_known: list[Decimal],
    thickness_known: list[Decimal],
) -> list[str]:
    """Коды несоответствия одного допуска по проверяемым параметрам (§7.4-7.7).

    Один конкретный допуск должен самостоятельно покрывать все проверяемые
    параметры (§7.3): диапазоны разных допусков не объединяются."""
    codes: list[str] = []
    admission_methods = {_norm(m) for m in candidate.methods}
    if _norm(welding_method) not in admission_methods:
        codes.append(METHOD_NOT_COVERED)
    if dn_known and not all(
        _within(side, candidate.dn_min, candidate.dn_max) for side in dn_known
    ):
        codes.append(DN_NOT_COVERED)
    if thickness_known and not all(
        _within(side, candidate.thickness_min, candidate.thickness_max)
        for side in thickness_known
    ):
        codes.append(THICKNESS_NOT_COVERED)
    # Положение проверяется только если оно указано И у допуска есть непустой
    # список positions (§7.5). Пустой список → положение не проверяется.
    if welding_position and candidate.positions:
        admission_positions = {_norm(p) for p in candidate.positions}
        if _norm(welding_position) not in admission_positions:
            codes.append(POSITION_NOT_COVERED)
    return codes


def _no_eligible_admission_codes(
    active_scoped: list[AdmissionCandidate], performed_on: date
) -> set[str]:
    """Коды при отсутствии действующего на дату допуска (§7.3, §8.2)."""
    if not active_scoped:
        return {NO_ACTIVE_ADMISSION}
    codes: set[str] = set()
    for candidate in active_scoped:
        if candidate.validity_from > performed_on:
            codes.add(ADMISSION_NOT_YET_VALID)
        elif candidate.validity_to is not None and candidate.validity_to < performed_on:
            codes.add(ADMISSION_EXPIRED)
    return codes or {NO_ACTIVE_ADMISSION}


def _admission_snapshot(candidate: AdmissionCandidate) -> dict:
    """Сериализуемый снимок использованного допуска (§5.2)."""
    return {
        "admission_id": str(candidate.id),
        "welder_id": str(candidate.welder_id) if candidate.welder_id else None,
        "worker_id": candidate.worker_id,
        "status": candidate.status,
        "validity_from": candidate.validity_from.isoformat(),
        "validity_to": (
            candidate.validity_to.isoformat() if candidate.validity_to else None
        ),
        "methods": [str(m) for m in candidate.methods],
        "positions": [str(p) for p in candidate.positions],
        "material_groups": [str(g) for g in candidate.material_groups],
        "dn_min": _dec(candidate.dn_min),
        "dn_max": _dec(candidate.dn_max),
        "thickness_min": _dec(candidate.thickness_min),
        "thickness_max": _dec(candidate.thickness_max),
    }


def validate_qualification(
    *,
    welder_specified: bool,
    welder_profile: WelderProfileView | None,
    performed_on: date,
    welding_method: str,
    welding_position: str | None,
    joint_project_id: UUID | None,
    dn_sides: Sequence[Decimal | None],
    thickness_sides: Sequence[Decimal | None],
    material_present: bool,
    candidates: Sequence[AdmissionCandidate],
) -> QualificationResult:
    """Итог проверки соответствия сварщика допуску (§7-8).

    FAIL — подтверждённое несоответствие (приоритет над INDETERMINATE);
    INDETERMINATE — нарушения нет, но данных недостаточно для PASS; PASS —
    один конкретный допуск покрывает все проверяемые параметры и нет причин
    INDETERMINATE."""
    # §7.2: сварщик не указан — проверка невозможна (защита для DRAFT).
    if not welder_specified:
        return QualificationResult("INDETERMINATE", [WELDER_NOT_SPECIFIED])
    if welder_profile is None:
        return QualificationResult("FAIL", [WELDER_PROFILE_NOT_FOUND])
    if not welder_profile.active:
        return QualificationResult("FAIL", [WELDER_PROFILE_INACTIVE])

    # Причины INDETERMINATE, независимые от конкретного допуска (§7.6-7.8).
    indeterminate: set[str] = set()
    dn_known = [side for side in dn_sides if side is not None]
    thickness_known = [side for side in thickness_sides if side is not None]
    if not dn_known:
        indeterminate.add(JOINT_DATA_INCOMPLETE)
    if not thickness_known:
        indeterminate.add(JOINT_DATA_INCOMPLETE)
    if material_present:
        # Каноническую группу материала определить невозможно (§7.8) — не считать
        # материал ни подходящим, ни неподходящим; помешать PASS.
        indeterminate.add(MATERIAL_GROUP_NOT_CHECKABLE)

    # Кандидаты: active + совместимый project scope; затем действующие на дату.
    active_scoped = [
        c
        for c in candidates
        if _norm(c.status) == "ACTIVE"
        and _project_compatible(c.project_id, joint_project_id)
    ]
    eligible = [c for c in active_scoped if _valid_on(c, performed_on)]

    if not eligible:
        codes = _no_eligible_admission_codes(active_scoped, performed_on)
        return QualificationResult("FAIL", _order(codes, _QUALIFICATION_CODE_ORDER))

    # Проверяем все подходящие кандидаты; ни один диапазон не объединяется (§7.3).
    ordered = sorted(eligible, key=lambda c: _priority_key(c, joint_project_id))
    covering: list[AdmissionCandidate] = []
    best_fail: tuple | None = None
    for candidate in ordered:
        fail_codes = _coverage_fail_codes(
            candidate,
            welding_method=welding_method,
            welding_position=welding_position,
            dn_known=dn_known,
            thickness_known=thickness_known,
        )
        if not fail_codes:
            covering.append(candidate)
        key = (len(fail_codes), _priority_key(candidate, joint_project_id))
        if best_fail is None or key < best_fail[0]:
            best_fail = (key, fail_codes)

    if covering:
        if not indeterminate:
            selected = covering[0]
            return QualificationResult(
                "PASS", [], selected.id, _admission_snapshot(selected)
            )
        # Допуск покрывает всё проверяемое, но данных недостаточно (§8.3).
        return QualificationResult(
            "INDETERMINATE", _order(indeterminate, _QUALIFICATION_CODE_ORDER)
        )

    # Ни один допуск не покрывает операцию целиком → FAIL. Коды — лучшего кандидата
    # плюс выявленные пробелы данных (§8.2: содержать все выявленные причины).
    _key, fail_codes = best_fail  # type: ignore[misc]
    codes = set(fail_codes) | indeterminate
    return QualificationResult("FAIL", _order(codes, _QUALIFICATION_CODE_ORDER))


# ── Проверка WPS (§9) ─────────────────────────────────────────────────────────


def validate_wps(
    *,
    weld_stage: str,
    welding_method: str,
    planned_wps_id: UUID | None,
    actual_wps_id: UUID | None,
    required_root_method: str | None,
    required_fill_method: str | None,
    required_cap_method: str | None,
) -> WpsResult:
    """Итог сравнения фактического WPS/метода с проектным (§9).

    В Task 8B нет реестра WPS: проверяются только наличие/совпадение UUID и
    соответствие фактического метода проектному методу этапа. FAIL имеет приоритет
    над INDETERMINATE."""
    fail: set[str] = set()
    indeterminate: set[str] = set()

    # §9.2 — сравнение UUID проектного и фактического WPS.
    if planned_wps_id is not None and actual_wps_id is not None:
        if planned_wps_id != actual_wps_id:
            fail.add(WPS_MISMATCH)
    elif planned_wps_id is not None and actual_wps_id is None:
        fail.add(ACTUAL_WPS_MISSING)
    elif planned_wps_id is None and actual_wps_id is not None:
        indeterminate.add(PLANNED_WPS_MISSING)
    else:
        indeterminate.add(PLANNED_WPS_MISSING)
        indeterminate.add(ACTUAL_WPS_MISSING)

    # §9.1 / §9.3 — проектный метод этапа и его сравнение с фактическим.
    stage = _norm(weld_stage)
    required_fields = {
        "ROOT": required_root_method,
        "FILL": required_fill_method,
        "CAP": required_cap_method,
    }
    required_method: str | None
    if stage in required_fields:
        required_method = required_fields[stage]
        if required_method is None or not str(required_method).strip():
            indeterminate.add(REQUIRED_METHOD_MISSING)
        elif _norm(required_method) != _norm(welding_method):
            fail.add(ACTUAL_METHOD_MISMATCH)
    else:
        # Этап без канонического проектного метода в Joint (§9.1).
        required_method = None
        indeterminate.add(UNKNOWN_WELD_STAGE)

    if fail:
        status = "FAIL"
    elif indeterminate:
        status = "INDETERMINATE"
    else:
        status = "PASS"

    snapshot = {
        "planned_wps_id": str(planned_wps_id) if planned_wps_id else None,
        "actual_wps_id": str(actual_wps_id) if actual_wps_id else None,
        "weld_stage": weld_stage,
        "required_method": required_method,
        "actual_method": welding_method,
    }
    return WpsResult(status, _order(fail | indeterminate, _WPS_CODE_ORDER), snapshot)
