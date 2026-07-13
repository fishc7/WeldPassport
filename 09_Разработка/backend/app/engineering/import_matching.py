"""Чистое сопоставление Joint и классификация дубликатов WeldOperation (Task 8E, §7-8).

Без БД и HTTP: получает уже разрешённые репозиторием кандидаты/сигнатуры и
классифицирует результат. Разрешение имён (line_code/isometric_no/revision_code →
сущности, welder_stamp_code → профиль) выполняет репозиторий/сервис.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.engineering import import_workflow as iw

# Импортируемые поля операции, участвующие в сравнении «полного совпадения» дубля
# (помимо ключевых). Ключевые: performed_on, welder, welding_method, weld_stage.
_DUP_COMPARE_FIELDS: tuple[str, ...] = (
    "welding_position",
    "shielding_gas",
    "started_at",
    "finished_at",
    "operation_note",
)


# ══════════════════════════════════════════════════════════════════════════════
# Сопоставление Joint (§7)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class JointCandidate:
    """Кандидат Joint (уже отобран по project_id + joint_no_normalized, «живой»).

    line_code/isometric_no/revision_code — разрешённые репозиторием строковые
    признаки текущей ревизии кандидата для уточнения сопоставления."""

    joint_id: UUID
    line_code: str | None
    isometric_no: str | None
    revision_code: str | None


@dataclass(frozen=True)
class RowMatchInput:
    line_code: str | None
    isometric_no: str | None
    revision_code: str | None
    joint_no_normalized: str


@dataclass
class JointMatchResult:
    classification: str
    conflict_codes: list[str] = field(default_factory=list)
    matched_joint_id: UUID | None = None


def classify_joint_match(
    row: RowMatchInput, candidates: list[JointCandidate]
) -> JointMatchResult:
    """Классификация сопоставления Joint (§7): exact / none / conflict / multiple.

    Точное совпадение — единственный кандидат, у которого совпадают line/isometric/
    revision. Единственный кандидат с расхождением инженерных привязок → CONFLICT с
    конкретными кодами. Несколько кандидатов без единственного точного →
    MULTIPLE_JOINT_MATCHES."""
    if not candidates:
        return JointMatchResult(iw.MATCH_NONE)

    full = [
        c
        for c in candidates
        if c.line_code == row.line_code
        and c.isometric_no == row.isometric_no
        and c.revision_code == row.revision_code
    ]
    if len(full) == 1:
        return JointMatchResult(iw.MATCH_EXACT, matched_joint_id=full[0].joint_id)
    if len(full) > 1:
        return JointMatchResult(iw.MATCH_MULTIPLE, [iw.MULTIPLE_JOINT_MATCHES])

    if len(candidates) == 1:
        c = candidates[0]
        codes: list[str] = []
        if c.line_code != row.line_code:
            codes.append(iw.LINE_MISMATCH)
        if c.isometric_no != row.isometric_no:
            codes.append(iw.ISOMETRIC_MISMATCH)
        if c.revision_code != row.revision_code:
            codes.append(iw.REVISION_MISMATCH)
        return JointMatchResult(iw.MATCH_CONFLICT, codes)

    return JointMatchResult(iw.MATCH_MULTIPLE, [iw.MULTIPLE_JOINT_MATCHES])


# ══════════════════════════════════════════════════════════════════════════════
# Дубликаты WeldOperation (§8)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class OperationSignature:
    """Сигнатура операции для сравнения дублей.

    `key` — ключевые признаки (joint, performed_on, welder, method, stage); `extra`
    — прочие импортируемые поля для проверки «полного совпадения»."""

    key: tuple
    extra: tuple


def build_operation_signature(
    joint_key: object,
    normalized: dict,
    welder_key: object,
) -> OperationSignature:
    """Строит сигнатуру из нормализованной строки (§8).

    joint_key — идентификатор целевого Joint (UUID существующего или суррогат новой
    группы); welder_key — разрешённый welder_id (или None, если не разрешён)."""
    key = (
        str(joint_key),
        normalized.get("performed_on"),
        str(welder_key) if welder_key is not None else None,
        normalized.get("welding_method"),
        normalized.get("weld_stage"),
    )
    extra = tuple(normalized.get(f) for f in _DUP_COMPARE_FIELDS)
    return OperationSignature(key=key, extra=extra)


@dataclass
class DuplicateResult:
    is_duplicate: bool
    duplicate_type: str | None = None
    conflict_codes: list[str] = field(default_factory=list)
    matched_operation_id: UUID | None = None


def classify_existing_duplicate(
    imported: OperationSignature,
    existing: list[tuple[UUID, OperationSignature]],
) -> DuplicateResult:
    """Дубликат относительно существующих операций Joint (§8).

    Полное совпадение (ключ + все импортируемые поля) → SKIPPED_DUPLICATE (идемпотентно).
    Совпал ключ, но отличается хотя бы одно импортируемое поле → конфликт ручного
    разрешения (EXISTING_OPERATION_CONFLICT). Иначе — не дубликат."""
    key_matches = [(op_id, sig) for op_id, sig in existing if sig.key == imported.key]
    if not key_matches:
        return DuplicateResult(False)
    for op_id, sig in key_matches:
        if sig.extra == imported.extra:
            return DuplicateResult(
                True,
                duplicate_type=iw.DUP_EXISTING_OPERATION,
                matched_operation_id=op_id,
            )
    # Ключ совпал, но данные отличаются — конфликт (существующую операцию не менять).
    return DuplicateResult(
        True,
        duplicate_type=iw.DUP_EXISTING_CONFLICT,
        conflict_codes=[iw.DUP_EXISTING_CONFLICT],
        matched_operation_id=key_matches[0][0],
    )


def find_intra_file_duplicates(
    signatures: list[tuple[UUID, OperationSignature]],
) -> dict[UUID, UUID]:
    """Внутрисессионные полные дубликаты (§8): первая строка рабочая, последующие
    полностью идентичные (ключ+данные) — INTRA_FILE_DUPLICATE.

    Возвращает отображение row_id → row_id первой (рабочей) строки. `signatures`
    подаются в стабильном порядке (по row_number)."""
    seen: dict[tuple, UUID] = {}
    duplicates: dict[UUID, UUID] = {}
    for row_id, sig in signatures:
        full = (sig.key, sig.extra)
        if full in seen:
            duplicates[row_id] = seen[full]
        else:
            seen[full] = row_id
    return duplicates
