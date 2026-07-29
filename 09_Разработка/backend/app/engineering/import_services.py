"""Оркестрация импорта XLSX и разрешения конфликтов (Task 8E).

Слой application-сервиса поверх доменной логики Joint/WeldOperation. Создание
Joint переиспользует `EngineeringService.create_joint`; создание/завершение
WeldOperation — доменные helpers `WeldOperationService` (без API-гейтов Task 8A,
т.к. импорт — отдельный авторизованный путь CHIEF_WELDER). Параллельной доменной
логики нет.

Соблюдаются инварианты ТЗ: прямой записи XLSX в производственные таблицы нет
(staging → matching → resolution → атомарный apply по группам); существующие
Joint/WeldOperation импортом не изменяются; correction/supersede Task 8D не
затрагивается. Apply — синхронный, паттерн транзакций как в Task 8D.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.engineering import import_matching as im
from app.engineering import import_parse as ip
from app.engineering import import_workflow as iw
from app.engineering.import_models import (
    ImportApplyAttempt,
    ImportApplyGroupResult,
    ImportGroup,
    ImportIdempotencyKey,
    ImportParseAttempt,
    ImportProvenance,
    ImportResolution,
    ImportRow,
    ImportRowChange,
    ImportSession,
    ImportStatusEvent,
)
from app.engineering.import_repository import ImportRepo
from app.engineering.import_storage import FileStorage, compute_sha256, get_file_storage
from app.engineering.models import Joint, WeldOperation
from app.engineering.schemas import JointCreate
from app.engineering.services import (
    EngineeringService,
    WeldOperationService,
    normalize_joint_no,
)
from app.hr.repository import HrRepo
from app.projects.repository import ProjectRepo
from app.shared.errors import (
    DomainError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from app.shared.permissions import is_role_effective_on

_XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ImportService:
    def __init__(self, db: Session, storage: FileStorage | None = None) -> None:
        self._db = db
        self._repo = ImportRepo(db)
        self._projects = ProjectRepo(db)
        self._hr = HrRepo(db)
        self._eng = EngineeringService(db)
        self._wos = WeldOperationService(db)
        self._storage = storage or get_file_storage()

    # ══════════════════════════════════════════════════════════════════════════
    # RBAC (§3). WELDING_ENGINEER маппится на OGS_ENGINEER.
    # ══════════════════════════════════════════════════════════════════════════
    def _granted(self, actor: int, codes: frozenset[str], project_id: UUID) -> set[str]:
        today = date.today()
        company_ids = set(self._projects.active_company_ids(project_id))
        granted: set[str] = set()
        for code in codes:
            for role in self._hr.find_active_roles(worker_id=actor, role_code=code):
                if not is_role_effective_on(role, today):
                    continue
                scope = role.scope_type
                sid = str(role.scope_id).strip() if role.scope_id is not None else ""
                if scope == "GLOBAL" and not sid:
                    granted.add(code)
                    break
                if scope == "PROJECT" and sid == str(project_id):
                    granted.add(code)
                    break
                if scope == "COMPANY" and sid.isdigit() and int(sid) in company_ids:
                    granted.add(code)
                    break
        return granted

    def _require_engineer(self, actor: int, project_id: UUID) -> None:
        if not self._granted(actor, iw.IMPORT_ENGINEER_ROLES, project_id):
            raise DomainError(
                403,
                iw.IMPORT_ROLE_DENIED,
                "Недостаточно прав: требуется роль OGS_ENGINEER или CHIEF_WELDER "
                "в scope проекта",
            )

    def _require_chief(self, actor: int, project_id: UUID) -> None:
        if not self._granted(actor, iw.IMPORT_CHIEF_ROLES, project_id):
            raise DomainError(
                403,
                iw.IMPORT_APPLY_ROLE_DENIED,
                "Действие доступно только роли CHIEF_WELDER",
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Идемпотентность (§13)
    # ══════════════════════════════════════════════════════════════════════════
    def _check_idempotency(
        self,
        *,
        scope: str,
        command_type: str,
        key: str | None,
        session_id: UUID | None,
        user_id: int,
        payload_hash: str,
    ) -> dict | None:
        """Возвращает сохранённый результат при валидном повторе; None — если это
        новая команда. При том же ключе и другом payload — 409 (§13)."""
        if not key:
            return None
        existing = self._repo.get_idempotency(
            scope=scope,
            command_type=command_type,
            idempotency_key=key,
            session_id=session_id,
            user_id=user_id,
        )
        if existing is None:
            return None
        if existing.payload_hash != payload_hash:
            raise DomainError(
                409,
                iw.IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD,
                "Ключ идемпотентности уже использован для другого содержимого",
            )
        return existing.response_payload or {}

    def _store_idempotency(
        self,
        *,
        scope: str,
        command_type: str,
        key: str | None,
        session_id: UUID | None,
        user_id: int,
        payload_hash: str,
        response_payload: dict,
        status_code: int,
    ) -> None:
        if not key:
            return
        self._repo.add_idempotency(
            ImportIdempotencyKey(
                scope=scope,
                command_type=command_type,
                import_session_id=session_id,
                user_id=user_id,
                idempotency_key=key,
                payload_hash=payload_hash,
                response_payload=response_payload,
                response_status_code=status_code,
            )
        )

    # ══════════════════════════════════════════════════════════════════════════
    # История статусов (§6)
    # ══════════════════════════════════════════════════════════════════════════
    def _event(
        self,
        session_id: UUID,
        entity_type: str,
        entity_id: UUID,
        previous: str | None,
        new: str | None,
        *,
        reason: str | None = None,
        actor: int | None = None,
        correlation_id: UUID | None = None,
    ) -> None:
        self._repo.add_status_event(
            ImportStatusEvent(
                import_session_id=session_id,
                entity_type=entity_type,
                entity_id=entity_id,
                previous_status=previous,
                new_status=new,
                reason=reason,
                actor_kind=iw.ACTOR_USER if actor is not None else iw.ACTOR_SYSTEM,
                actor_worker_id=actor,
                correlation_id=correlation_id,
            )
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Загрузка XLSX + разбор (§4-6). Upload создаёт сессию и синхронно разбирает.
    # ══════════════════════════════════════════════════════════════════════════
    def upload(
        self,
        *,
        project_id: UUID,
        filename: str,
        content_type: str | None,
        data: bytes,
        actor: int,
        idempotency_key: str | None,
    ) -> ImportSession:
        if self._projects.get_project(project_id) is None:
            raise NotFoundError("Проект", project_id)
        self._require_engineer(actor, project_id)

        # Структурные проверки до создания staging (§4): расширение, mime, размер.
        if not filename.lower().endswith(".xlsx"):
            raise DomainError(
                422, iw.IMPORT_FILE_EXTENSION_INVALID,
                "Ожидается файл с расширением .xlsx",
            )
        if content_type and content_type not in (_XLSX_MIME, "application/octet-stream"):
            raise DomainError(
                422, iw.IMPORT_FILE_MIME_INVALID,
                f"Недопустимый MIME-type: {content_type}",
            )
        from app.shared.config import settings

        if len(data) > settings.import_max_file_size_bytes:
            raise DomainError(
                422, iw.IMPORT_FILE_TOO_LARGE,
                f"Превышен максимальный размер файла "
                f"({settings.import_max_file_size_bytes} байт)",
            )

        file_sha = compute_sha256(data)
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_UPLOAD, "project_id": str(project_id), "sha256": file_sha}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_USER, command_type=iw.CMD_UPLOAD,
            key=idempotency_key, session_id=None, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            existing = self._repo.get_session(UUID(replay["id"]))
            if existing is not None:
                return existing

        duplicate_of = self._repo.find_session_by_sha(project_id, file_sha)

        object_key = FileStorage.build_key(str(project_id), filename)
        self._storage.put(object_key, data, content_type=_XLSX_MIME)

        session = ImportSession(
            project_id=project_id,
            template_version="",  # заполнится при успешном разборе
            original_filename=filename,
            file_size_bytes=len(data),
            mime_type=content_type or _XLSX_MIME,
            file_sha256=file_sha,
            storage_object_key=object_key,
            status=iw.SESSION_UPLOADED,
            duplicate_of_session_id=(
                duplicate_of.id if duplicate_of is not None else None
            ),
            uploaded_by=actor,
            updated_by=actor,
        )
        self._repo.add_session(session)
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, None,
            iw.SESSION_UPLOADED, actor=actor,
        )
        # Синхронный разбор.
        self._run_parse(session, actor, data=data)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_USER, command_type=iw.CMD_UPLOAD,
            key=idempotency_key, session_id=None, user_id=actor,
            payload_hash=payload_hash,
            response_payload={"id": str(session.id)}, status_code=201,
        )
        self._db.commit()
        self._db.refresh(session)
        return session

    def reparse(
        self, session_id: UUID, *, actor: int, idempotency_key: str | None
    ) -> ImportSession:
        session = self._repo.get_session_for_update(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        self._require_engineer(actor, session.project_id)

        payload_hash = _canonical_hash({"cmd": iw.CMD_REPARSE})
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_REPARSE,
            key=idempotency_key, session_id=session_id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return session

        if session.status != iw.SESSION_PARSE_FAILED:
            raise DomainError(
                409, iw.IMPORT_REPARSE_NOT_ALLOWED,
                "Повторный разбор допустим только после PARSE_FAILED",
            )
        # Повторный parse запрещён, если staging уже создан (§6).
        if self._repo.count_rows(session_id) > 0:
            raise DomainError(
                409, iw.IMPORT_PARSE_ALREADY_STAGED,
                "Staging уже создан: повторный разбор запрещён",
            )
        data = self._read_file(session)
        self._run_parse(session, actor, data=data)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_REPARSE,
            key=idempotency_key, session_id=session_id, user_id=actor,
            payload_hash=payload_hash,
            response_payload={"id": str(session.id)}, status_code=200,
        )
        self._db.commit()
        self._db.refresh(session)
        return session

    def _read_file(self, session: ImportSession) -> bytes:
        """Читает исходный файл и сверяет SHA-256 (§5). Несовпадение — 409."""
        data = self._storage.get(session.storage_object_key)
        if compute_sha256(data) != session.file_sha256:
            raise DomainError(
                409, iw.IMPORT_FILE_HASH_MISMATCH,
                "Контрольная сумма исходного файла не совпадает: файл повреждён",
            )
        return data

    def _run_parse(self, session: ImportSession, actor: int, *, data: bytes) -> None:
        """Один разбор: PARSING → staging (UNDER_REVIEW) либо PARSE_FAILED (§6)."""
        from app.shared.config import settings

        prev = session.status
        session.status = iw.SESSION_PARSING
        session.updated_by = actor
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, prev,
            iw.SESSION_PARSING, actor=actor,
        )
        attempt = ImportParseAttempt(
            import_session_id=session.id,
            attempt_no=self._repo.next_parse_attempt_no(session.id),
            initiated_by=actor,
            started_at=_now(),
        )
        self._repo.add_parse_attempt(attempt)
        try:
            result = ip.parse_workbook(
                data,
                max_rows=settings.import_max_rows,
                max_groups=settings.import_max_groups,
            )
        except ip.ParseStructureError as exc:
            attempt.finished_at = _now()
            attempt.outcome = iw.PARSE_FAILED_OUTCOME
            attempt.error_code = exc.code
            attempt.error_message = exc.message
            session.status = iw.SESSION_PARSE_FAILED
            self._event(
                session.id, iw.EVENT_ENTITY_SESSION, session.id,
                iw.SESSION_PARSING, iw.SESSION_PARSE_FAILED,
                reason=exc.code, actor=actor,
            )
            return

        session.template_version = result.template_version
        self._create_staging_rows(session, result, actor)
        attempt.finished_at = _now()
        attempt.outcome = iw.PARSE_SUCCEEDED
        attempt.rows_read = result.rows_read
        attempt.rows_empty = result.rows_empty
        attempt.rows_created = len(result.rows)
        attempt.rows_error = result.rows_error
        # Полный пересчёт: сопоставление, дубли, группировка.
        self._recheck_session(session, actor)
        session.status = iw.SESSION_UNDER_REVIEW
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id,
            iw.SESSION_PARSING, iw.SESSION_UNDER_REVIEW, actor=actor,
        )

    def _create_staging_rows(
        self, session: ImportSession, result: ip.ParseResult, actor: int
    ) -> None:
        for parsed in result.rows:
            status = (
                iw.ROW_VALIDATION_ERROR if parsed.error_codes else iw.ROW_PENDING_MATCH
            )
            row = ImportRow(
                import_session_id=session.id,
                row_number=parsed.row_number,
                raw_snapshot=parsed.raw,
                normalized_data=parsed.normalized,
                normalized_joint_no=parsed.normalized_joint_no,
                status=status,
                error_codes=list(parsed.error_codes),
                conflict_codes=[],
                created_by=actor,
                updated_by=actor,
            )
            self._repo.add_row(row)

    # ══════════════════════════════════════════════════════════════════════════
    # Пересчёт: сопоставление, дубли, группировка (§7-9)
    # ══════════════════════════════════════════════════════════════════════════
    def _recheck_session(self, session: ImportSession, actor: int) -> None:
        """Полный пересчёт всех неприменённых строк и групп сессии."""
        rows = self._repo.list_rows(session.id)
        for row in rows:
            if row.status in iw.ROW_TERMINAL_STATUSES:
                continue
            if row.status in (
                iw.ROW_RESOLVED_CREATE_NEW, iw.ROW_RESOLVED_LINK_EXISTING,
                iw.ROW_RESOLVED_CREATE_NEW_JOINT,
            ):
                # Строка уже урегулирована ручным решением — сопоставление не
                # переопределяем, только повторная валидация типов.
                self._revalidate_row(row)
                continue
            self._recheck_row(row, session)
        self._intra_file_duplicates(session, rows)
        self._rebuild_groups(session, actor)

    def _revalidate_row(self, row: ImportRow) -> None:
        errors = self._row_validation_errors(row)
        if errors:
            row.error_codes = errors
            row.status = iw.ROW_VALIDATION_ERROR

    def _row_validation_errors(self, row: ImportRow) -> list[str]:
        nd = row.normalized_data or {}
        errors: list[str] = []
        for field in iw.REQUIRED_NORMALIZED_FIELDS:
            if not nd.get(field):
                errors.append(f"{ip.ROW_REQUIRED_FIELD_MISSING}:{field}")
        stage = nd.get("weld_stage")
        from app.engineering.weld_operation_workflow import WELD_STAGES

        if stage is not None and stage not in WELD_STAGES:
            errors.append(ip.ROW_INVALID_WELD_STAGE)
        if nd.get("performed_on") and ip._normalize_date(nd["performed_on"]) is None:
            errors.append(ip.ROW_INVALID_PERFORMED_ON)
        # Разрешимость сварщика по клейму (§8 требует welder_id).
        stamp = nd.get("welder_stamp_code")
        if stamp and self._repo.resolve_welder_by_stamp(stamp) is None:
            errors.append("WELDER_STAMP_UNRESOLVED")
        return errors

    def _recheck_row(self, row: ImportRow, session: ImportSession) -> None:
        """Валидация → сопоставление Joint → проверка дубля существующей операции."""
        errors = self._row_validation_errors(row)
        if errors:
            row.error_codes = errors
            row.conflict_codes = []
            row.match_classification = None
            row.matched_joint_id = None
            row.status = iw.ROW_VALIDATION_ERROR
            return
        row.error_codes = []

        nd = row.normalized_data
        candidates = self._repo.joint_candidates(
            session.project_id, row.normalized_joint_no
        )
        match = im.classify_joint_match(
            im.RowMatchInput(
                line_code=nd.get("line_code"),
                isometric_no=nd.get("isometric_no"),
                revision_code=nd.get("revision_code"),
                joint_no_normalized=row.normalized_joint_no,
            ),
            candidates,
        )
        row.match_classification = match.classification
        row.conflict_codes = list(match.conflict_codes)

        if match.classification == iw.MATCH_NONE:
            row.matched_joint_id = None
            row.status = iw.ROW_READY  # создаёт новый Joint + операцию
            return
        if match.classification == iw.MATCH_EXACT:
            row.matched_joint_id = match.matched_joint_id
            self._check_existing_duplicate(row)
            return
        # CONFLICT / MULTIPLE — ручное разрешение (§7).
        row.matched_joint_id = None
        row.status = iw.ROW_MATCH_CONFLICT

    def _check_existing_duplicate(self, row: ImportRow) -> None:
        """Дубль относительно завершённых операций сопоставленного Joint (§8)."""
        nd = row.normalized_data
        welder = self._repo.resolve_welder_by_stamp(nd.get("welder_stamp_code"))
        welder_key = welder.id if welder is not None else None
        imported = im.build_operation_signature(
            row.matched_joint_id, nd, welder_key
        )
        existing = [
            (op.id, self._op_signature(row.matched_joint_id, op))
            for op in self._repo.completed_operations_for_joint(row.matched_joint_id)
        ]
        dup = im.classify_existing_duplicate(imported, existing)
        if not dup.is_duplicate:
            row.matched_weld_operation_id = None
            row.status = iw.ROW_READY  # создаёт операцию на существующем Joint
            return
        if dup.duplicate_type == iw.DUP_EXISTING_OPERATION:
            row.matched_weld_operation_id = dup.matched_operation_id
            row.duplicate_type = iw.DUP_EXISTING_OPERATION
            row.status = iw.ROW_SKIPPED_DUPLICATE  # идемпотентно, операция не создаётся
            return
        # Ключ совпал, данные отличаются — конфликт ручного разрешения.
        row.matched_weld_operation_id = dup.matched_operation_id
        row.duplicate_type = iw.DUP_EXISTING_CONFLICT
        row.conflict_codes = list(dup.conflict_codes)
        row.status = iw.ROW_DUPLICATE

    @staticmethod
    def _op_signature(joint_id: UUID, op: WeldOperation) -> im.OperationSignature:
        normalized = {
            "performed_on": op.performed_on.isoformat() if op.performed_on else None,
            "welding_method": op.welding_method,
            "weld_stage": op.weld_stage,
            "welding_position": op.welding_position,
            "shielding_gas": op.shielding_gas,
            "started_at": op.started_at.isoformat() if op.started_at else None,
            "finished_at": op.finished_at.isoformat() if op.finished_at else None,
            "operation_note": op.operation_note,
        }
        return im.build_operation_signature(joint_id, normalized, op.actual_welder_id)

    def _intra_file_duplicates(
        self, session: ImportSession, rows: list[ImportRow]
    ) -> None:
        """Полные внутрисессионные дубли: первая рабочая, последующие — INTRA_FILE (§8)."""
        signatures: list[tuple[UUID, im.OperationSignature]] = []
        for row in rows:
            if row.status not in (iw.ROW_READY, iw.ROW_RESOLVED_CREATE_NEW,
                                  iw.ROW_RESOLVED_LINK_EXISTING,
                                  iw.ROW_RESOLVED_CREATE_NEW_JOINT):
                continue
            nd = row.normalized_data
            welder = self._repo.resolve_welder_by_stamp(nd.get("welder_stamp_code"))
            welder_key = welder.id if welder is not None else None
            joint_key = row.matched_joint_id or (
                "N", nd.get("line_code"), nd.get("isometric_no"),
                nd.get("revision_code"), row.normalized_joint_no,
            )
            signatures.append(
                (row.id, im.build_operation_signature(joint_key, nd, welder_key))
            )
        duplicates = im.find_intra_file_duplicates(signatures)
        by_id = {r.id: r for r in rows}
        for row_id in duplicates:
            row = by_id[row_id]
            row.duplicate_type = iw.DUP_INTRA_FILE
            row.status = iw.ROW_DUPLICATE
            if iw.DUP_INTRA_FILE not in row.conflict_codes:
                row.conflict_codes = [*row.conflict_codes, iw.DUP_INTRA_FILE]

    def _row_identity(self, row: ImportRow) -> tuple:
        if row.matched_joint_id is not None:
            return ("E", str(row.matched_joint_id))
        nd = row.normalized_data or {}
        return (
            "N", nd.get("line_code"), nd.get("isometric_no"),
            nd.get("revision_code"), row.normalized_joint_no,
        )

    def _rebuild_groups(self, session: ImportSession, actor: int) -> None:
        """Назначает неприменённые строки группам по идентичности Joint и
        пересчитывает статусы групп (§9). Применённые/отменённые группы не трогает."""
        rows = self._repo.list_rows(session.id)
        groups = self._repo.list_groups(session.id)
        # Липкие группы не пересчитываются автоматически: применённые/отменённые
        # (терминальные), а также FAILED и APPLYING — FAILED возвращает в READY
        # только CHIEF_WELDER (§10), APPLYING идёт внутри apply.
        sticky = iw.GROUP_TERMINAL_STATUSES | {iw.GROUP_FAILED, iw.GROUP_APPLYING}
        active_groups = {
            self._group_identity(g): g
            for g in groups
            if g.status not in sticky
        }
        for row in rows:
            if row.status == iw.ROW_CANCELLED:
                continue
            # Строка, чья группа липкая (применена/отменена/FAILED), остаётся в ней.
            if row.import_group_id is not None:
                existing = next(
                    (g for g in groups if g.id == row.import_group_id), None
                )
                if existing is not None and existing.status in sticky:
                    continue
            identity = self._row_identity(row)
            group = active_groups.get(identity)
            if group is None:
                group = self._create_group(session, row, identity, actor)
                active_groups[identity] = group
            row.import_group_id = group.id
        # Назначение import_group_id должно быть видимо запросам пересчёта
        # (autoflush выключен): фиксируем перед подсчётом статусов групп.
        self._db.flush()
        # Пересчёт статусов активных групп.
        for group in active_groups.values():
            self._recompute_group(group, actor)

    def _create_group(
        self, session: ImportSession, row: ImportRow, identity: tuple, actor: int
    ) -> ImportGroup:
        if identity[0] == "E":
            target_type = iw.GROUP_TARGET_EXISTING_JOINT
            target_joint_id = row.matched_joint_id
            prepared = None
        else:
            target_type = iw.GROUP_TARGET_NEW_JOINT
            target_joint_id = None
            nd = row.normalized_data or {}
            prepared = {
                "line_code": nd.get("line_code"),
                "isometric_no": nd.get("isometric_no"),
                "revision_code": nd.get("revision_code"),
                "joint_no": nd.get("joint_no"),
                "joint_no_normalized": row.normalized_joint_no,
            }
        group = ImportGroup(
            group_key=uuid4(),
            import_session_id=session.id,
            group_order=self._repo.next_group_order(session.id),
            target_type=target_type,
            target_joint_id=target_joint_id,
            prepared_joint_data=prepared,
            status=iw.GROUP_PENDING,
        )
        self._repo.add_group(group)
        self._event(
            session.id, iw.EVENT_ENTITY_GROUP, group.id, None,
            iw.GROUP_PENDING, actor=actor,
        )
        return group

    def _group_identity(self, group: ImportGroup) -> tuple:
        if group.target_type == iw.GROUP_TARGET_EXISTING_JOINT:
            return ("E", str(group.target_joint_id))
        p = group.prepared_joint_data or {}
        return (
            "N", p.get("line_code"), p.get("isometric_no"),
            p.get("revision_code"), p.get("joint_no_normalized"),
        )

    def _recompute_group(self, group: ImportGroup, actor: int) -> None:
        rows = self._repo.rows_by_group(group.id)
        statuses = [r.status for r in rows]
        new_status, reasons = iw.compute_group_status(statuses)
        if new_status != group.status or reasons != list(group.block_reasons):
            prev = group.status
            group.status = new_status
            group.block_reasons = reasons
            group.record_version += 1
            self._event(
                group.import_session_id, iw.EVENT_ENTITY_GROUP, group.id,
                prev, new_status, actor=None,
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Getters
    # ══════════════════════════════════════════════════════════════════════════
    def get_session(self, session_id: UUID) -> ImportSession:
        session = self._repo.get_session(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        return session

    def get_row(self, row_id: UUID) -> ImportRow:
        row = self._repo.get_row(row_id)
        if row is None:
            raise NotFoundError("Строка импорта", row_id)
        return row

    def get_group(self, group_id: UUID) -> ImportGroup:
        group = self._repo.get_group(group_id)
        if group is None:
            raise NotFoundError("Группа импорта", group_id)
        return group

    def list_sessions(
        self, *, project_id: UUID | None, status: str | None, skip: int, limit: int
    ) -> list[ImportSession]:
        return self._repo.list_sessions(
            project_id=project_id, status=status, skip=skip, limit=limit
        )

    def list_rows(self, session_id: UUID, **filters) -> list[ImportRow]:
        self.get_session(session_id)
        return self._repo.list_rows(session_id, **filters)

    def list_groups(self, session_id: UUID, *, status: str | None = None):
        self.get_session(session_id)
        return self._repo.list_groups(session_id, status=status)

    def list_row_changes(self, row_id: UUID):
        self.get_row(row_id)
        return self._repo.list_row_changes(row_id)

    def list_resolutions(self, row_id: UUID):
        self.get_row(row_id)
        return self._repo.list_resolutions(row_id)

    def list_parse_attempts(self, session_id: UUID):
        self.get_session(session_id)
        return self._repo.list_parse_attempts(session_id)

    def list_apply_attempts(self, session_id: UUID):
        self.get_session(session_id)
        return self._repo.list_apply_attempts(session_id)

    def list_provenance(self, session_id: UUID):
        self.get_session(session_id)
        return self._repo.list_provenance(session_id)

    def list_status_events(self, session_id: UUID, **filters):
        self.get_session(session_id)
        return self._repo.list_status_events(session_id, **filters)

    def download_link(self, session_id: UUID, actor: int):
        from app.engineering.import_schemas import FileDownloadLink

        session = self._repo.get_session(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        self._require_engineer(actor, session.project_id)
        return FileDownloadLink(
            storage_object_key=session.storage_object_key,
            original_filename=session.original_filename,
            file_sha256=session.file_sha256,
            expires_in_seconds=300,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Guard'ы состояния и версий
    # ══════════════════════════════════════════════════════════════════════════
    @staticmethod
    def _assert_session_open(session: ImportSession) -> None:
        if session.status == iw.SESSION_APPLYING:
            raise DomainError(
                409, iw.IMPORT_SESSION_LOCKED_DURING_APPLY,
                "Сессия применяется: изменения запрещены",
            )
        if session.status in iw.SESSION_TERMINAL_STATUSES:
            raise DomainError(
                409, iw.IMPORT_SESSION_INVALID_STATE,
                f"Сессия в конечном статусе {session.status}",
            )

    @staticmethod
    def _check_row_version(row: ImportRow, expected: int | None) -> None:
        if expected is not None and expected != row.row_version:
            raise VersionConflictError(
                iw.IMPORT_ROW_VERSION_CONFLICT,
                expected_version=expected, current_version=row.row_version,
            )

    @staticmethod
    def _check_group_version(group: ImportGroup, expected: int | None) -> None:
        if expected is not None and expected != group.record_version:
            raise VersionConflictError(
                iw.IMPORT_GROUP_VERSION_CONFLICT,
                expected_version=expected, current_version=group.record_version,
            )

    @staticmethod
    def _check_session_version(session: ImportSession, expected: int | None) -> None:
        if expected is not None and expected != session.record_version:
            raise VersionConflictError(
                iw.IMPORT_SESSION_VERSION_CONFLICT,
                expected_version=expected, current_version=session.record_version,
            )

    @staticmethod
    def _assert_row_mutable(row: ImportRow) -> None:
        if row.status in iw.ROW_TERMINAL_STATUSES:
            raise DomainError(
                409, iw.IMPORT_ROW_IMMUTABLE,
                f"Строка в конечном статусе {row.status} неизменяема",
            )

    def _session_has_applied_group(self, session_id: UUID) -> bool:
        return any(
            g.status == iw.GROUP_APPLIED
            for g in self._repo.list_groups(session_id)
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Редактирование staging-строки (§6)
    # ══════════════════════════════════════════════════════════════════════════
    def edit_row(self, row_id: UUID, data, *, actor: int, idempotency_key: str | None):
        row = self._repo.get_row_for_update(row_id)
        if row is None:
            raise NotFoundError("Строка импорта", row_id)
        session = self._repo.get_session_for_update(row.import_session_id)
        self._require_engineer(actor, session.project_id)
        self._assert_session_open(session)
        self._assert_row_mutable(row)

        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_EDIT_ROW, "row": str(row_id),
             "fields": data.fields, "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_EDIT_ROW,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return row
        self._check_row_version(row, data.expected_row_version)

        changed = {
            f: v for f, v in data.fields.items()
            if f in iw.NORMALIZED_FIELDS and (row.normalized_data or {}).get(f) != v
        }
        unknown = [f for f in data.fields if f not in iw.NORMALIZED_FIELDS]
        if unknown:
            raise ValidationError(
                "Недопустимые для редактирования поля: " + ", ".join(unknown)
            )
        if not changed:
            raise DomainError(
                422, iw.IMPORT_FIELD_NOT_EDITABLE, "Нет эффективных изменений"
            )
        if iw.comment_required_for_fields(list(changed)) and not (data.comment and data.comment.strip()):
            raise DomainError(
                422, iw.IMPORT_COMMENT_REQUIRED,
                "Комментарий обязателен при изменении ключевых полей",
            )

        nd = dict(row.normalized_data or {})
        for field, new_value in changed.items():
            self._repo.add_row_change(
                ImportRowChange(
                    import_row_id=row.id, field=field,
                    old_value=nd.get(field), new_value=new_value,
                    comment=data.comment, changed_by=actor,
                )
            )
            nd[field] = new_value
        row.normalized_data = nd
        if "joint_no" in changed:
            row.normalized_joint_no = (
                normalize_joint_no(nd["joint_no"]) if nd.get("joint_no") else None
            )
        # Сброс ручного разрешения и производного статуса: правка запускает полный
        # повторный цикл (§6).
        self._supersede_active_resolution(row, actor)
        row.duplicate_type = None
        row.matched_weld_operation_id = None
        row.status = iw.ROW_PENDING_MATCH
        row.updated_by = actor
        row.row_version += 1

        self._recheck_session(session, actor)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_EDIT_ROW,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(row.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def _supersede_active_resolution(self, row: ImportRow, actor: int) -> None:
        active = self._repo.active_resolution(row.id)
        if active is not None:
            active.is_superseded = True

    # ══════════════════════════════════════════════════════════════════════════
    # Разрешение конфликта (§6-8)
    # ══════════════════════════════════════════════════════════════════════════
    def resolve_row(
        self, row_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        row = self._repo.get_row_for_update(row_id)
        if row is None:
            raise NotFoundError("Строка импорта", row_id)
        session = self._repo.get_session_for_update(row.import_session_id)
        self._require_engineer(actor, session.project_id)
        self._assert_session_open(session)
        self._assert_row_mutable(row)

        if data.resolution_type not in iw.RESOLUTION_TYPES:
            raise ValidationError(
                f"Недопустимый тип решения: {data.resolution_type}"
            )
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_RESOLVE, "row": str(row_id),
             "type": data.resolution_type,
             "joint": str(data.selected_joint_id) if data.selected_joint_id else None,
             "op": str(data.selected_weld_operation_id)
             if data.selected_weld_operation_id else None,
             "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_RESOLVE,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return row
        self._check_row_version(row, data.expected_row_version)
        self._validate_resolution_target(session, data)

        prev = self._repo.active_resolution(row.id)
        if prev is not None:
            prev.is_superseded = True
        resolution = ImportResolution(
            import_row_id=row.id,
            resolution_type=data.resolution_type,
            comment=data.comment,
            resolved_by=actor,
            resolved_at=_now(),
            selected_joint_id=data.selected_joint_id,
            selected_weld_operation_id=data.selected_weld_operation_id,
            supersedes_resolution_id=prev.id if prev is not None else None,
            is_superseded=False,
        )
        self._repo.add_resolution(resolution)
        self._apply_resolution_effect(row, data)
        row.updated_by = actor
        row.row_version += 1
        self._rebuild_groups(session, actor)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_RESOLVE,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(row.id)},
            status_code=201,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def _validate_resolution_target(self, session: ImportSession, data) -> None:
        if data.resolution_type == iw.RES_LINK_EXISTING_JOINT:
            if data.selected_joint_id is None:
                raise DomainError(
                    422, iw.IMPORT_RESOLUTION_TARGET_REQUIRED,
                    "Требуется selected_joint_id",
                )
            joint = self._eng._repo.get_joint(data.selected_joint_id)
            if (
                joint is None or joint.project_id != session.project_id
                or joint.status in ("CANCELLED", "SUPERSEDED")
            ):
                raise DomainError(
                    422, iw.IMPORT_RESOLUTION_TARGET_INVALID,
                    "Выбранный Joint не найден/не в проекте/не действующий",
                )
        if data.resolution_type == iw.RES_MARK_OPERATION_DUPLICATE:
            if data.selected_weld_operation_id is None:
                raise DomainError(
                    422, iw.IMPORT_RESOLUTION_TARGET_REQUIRED,
                    "Требуется selected_weld_operation_id",
                )
            op = self._eng._repo.get_operation(data.selected_weld_operation_id)
            if op is None:
                raise DomainError(
                    422, iw.IMPORT_RESOLUTION_TARGET_INVALID,
                    "Выбранная операция не найдена",
                )

    def _apply_resolution_effect(self, row: ImportRow, data) -> None:
        rtype = data.resolution_type
        row.conflict_codes = []
        if rtype == iw.RES_LINK_EXISTING_JOINT:
            row.matched_joint_id = data.selected_joint_id
            row.duplicate_type = None
            row.matched_weld_operation_id = None
            row.status = iw.ROW_RESOLVED_LINK_EXISTING
        elif rtype == iw.RES_CREATE_NEW_JOINT:
            row.matched_joint_id = None
            row.duplicate_type = None
            row.status = iw.ROW_RESOLVED_CREATE_NEW_JOINT
        elif rtype == iw.RES_MARK_OPERATION_DUPLICATE:
            row.matched_weld_operation_id = data.selected_weld_operation_id
            row.status = iw.ROW_RESOLVED_AS_DUPLICATE
        elif rtype == iw.RES_CREATE_NEW_OPERATION:
            row.duplicate_type = None
            row.status = iw.ROW_RESOLVED_CREATE_NEW
        elif rtype == iw.RES_REJECT_ROW:
            row.status = iw.ROW_REJECTED

    def reject_row(
        self, row_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        from app.engineering.import_schemas import ResolutionCommand

        cmd = ResolutionCommand(
            resolution_type=iw.RES_REJECT_ROW,
            comment=data.comment,
            expected_row_version=data.expected_row_version,
        )
        return self._resolve_via(row_id, cmd, iw.CMD_REJECT_ROW, actor, idempotency_key)

    def _resolve_via(self, row_id, cmd, command_type, actor, idempotency_key):
        """Отклонение как REJECT_ROW-решение с отдельным типом идемпотентной команды."""
        row = self._repo.get_row_for_update(row_id)
        if row is None:
            raise NotFoundError("Строка импорта", row_id)
        session = self._repo.get_session_for_update(row.import_session_id)
        self._require_engineer(actor, session.project_id)
        self._assert_session_open(session)
        self._assert_row_mutable(row)
        payload_hash = _canonical_hash(
            {"cmd": command_type, "row": str(row_id), "comment": cmd.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=command_type,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return row
        self._check_row_version(row, cmd.expected_row_version)
        prev = self._repo.active_resolution(row.id)
        if prev is not None:
            prev.is_superseded = True
        self._repo.add_resolution(
            ImportResolution(
                import_row_id=row.id, resolution_type=iw.RES_REJECT_ROW,
                comment=cmd.comment, resolved_by=actor, resolved_at=_now(),
                supersedes_resolution_id=prev.id if prev is not None else None,
                is_superseded=False,
            )
        )
        row.status = iw.ROW_REJECTED
        row.updated_by = actor
        row.row_version += 1
        self._rebuild_groups(session, actor)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=command_type,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(row.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def return_row(
        self, row_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        """Возврат неприменённой строки в обработку с обязательным комментарием (§8)."""
        row = self._repo.get_row_for_update(row_id)
        if row is None:
            raise NotFoundError("Строка импорта", row_id)
        session = self._repo.get_session_for_update(row.import_session_id)
        self._require_engineer(actor, session.project_id)
        self._assert_session_open(session)
        if row.status in iw.ROW_TERMINAL_STATUSES and row.status != iw.ROW_REJECTED:
            raise DomainError(
                409, iw.IMPORT_ROW_IMMUTABLE,
                f"Строку в статусе {row.status} нельзя вернуть в обработку",
            )
        if not (data.comment and data.comment.strip()):
            raise DomainError(
                422, iw.IMPORT_COMMENT_REQUIRED,
                "Комментарий обязателен при возврате строки в обработку",
            )
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_RETURN_ROW, "row": str(row_id), "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_RETURN_ROW,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return row
        self._check_row_version(row, data.expected_row_version)
        prev = self._repo.active_resolution(row.id)
        if prev is not None:
            prev.is_superseded = True
        self._repo.add_row_change(
            ImportRowChange(
                import_row_id=row.id, field="__return__", old_value=row.status,
                new_value=iw.ROW_PENDING_MATCH, comment=data.comment,
                changed_by=actor,
            )
        )
        row.duplicate_type = None
        row.conflict_codes = []
        row.matched_weld_operation_id = None
        row.status = iw.ROW_PENDING_MATCH
        row.updated_by = actor
        row.row_version += 1
        self._recheck_session(session, actor)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_RETURN_ROW,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(row.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    # ══════════════════════════════════════════════════════════════════════════
    # Отмена группы и сессии (§12)
    # ══════════════════════════════════════════════════════════════════════════
    def cancel_group(
        self, group_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        group = self._repo.get_group_for_update(group_id)
        if group is None:
            raise NotFoundError("Группа импорта", group_id)
        session = self._repo.get_session_for_update(group.import_session_id)
        self._assert_session_open(session)
        # После первого применённой группы — только CHIEF_WELDER (§12).
        if self._session_has_applied_group(session.id):
            self._require_chief(actor, session.project_id)
        else:
            self._require_engineer(actor, session.project_id)
        if group.status in iw.GROUP_TERMINAL_STATUSES:
            raise DomainError(
                409, iw.IMPORT_GROUP_INVALID_STATE,
                f"Группа в конечном статусе {group.status}",
            )
        if not (data.comment and data.comment.strip()):
            raise DomainError(
                422, iw.IMPORT_COMMENT_REQUIRED, "Комментарий обязателен при отмене",
            )
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_CANCEL_GROUP, "group": str(group_id),
             "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_CANCEL_GROUP,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return group
        self._check_group_version(group, data.expected_record_version)
        self._cancel_group_internal(group, session, actor, data.comment)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_CANCEL_GROUP,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(group.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(group)
        return group

    def _cancel_group_internal(
        self, group: ImportGroup, session: ImportSession, actor: int, comment: str
    ) -> None:
        prev = group.status
        for row in self._repo.rows_by_group_for_update(group.id):
            if row.status not in iw.ROW_TERMINAL_STATUSES:
                row_prev = row.status
                row.status = iw.ROW_CANCELLED
                row.updated_by = actor
                row.row_version += 1
                self._event(
                    session.id, iw.EVENT_ENTITY_ROW, row.id, row_prev,
                    iw.ROW_CANCELLED, reason=comment, actor=actor,
                )
        group.status = iw.GROUP_CANCELLED
        group.record_version += 1
        self._event(
            session.id, iw.EVENT_ENTITY_GROUP, group.id, prev,
            iw.GROUP_CANCELLED, reason=comment, actor=actor,
        )

    def cancel_session(
        self, session_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        session = self._repo.get_session_for_update(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        self._assert_session_open(session)
        if self._session_has_applied_group(session.id):
            self._require_chief(actor, session.project_id)
        else:
            self._require_engineer(actor, session.project_id)
        if not (data.comment and data.comment.strip()):
            raise DomainError(
                422, iw.IMPORT_COMMENT_REQUIRED, "Комментарий обязателен при отмене",
            )
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_CANCEL_SESSION, "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_CANCEL_SESSION,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return session
        self._check_session_version(session, data.expected_record_version)
        for group in self._repo.list_groups_for_update(session.id):
            if group.status not in iw.GROUP_TERMINAL_STATUSES:
                self._cancel_group_internal(group, session, actor, data.comment)
        prev = session.status
        session.status = iw.SESSION_CANCELLED
        session.updated_by = actor
        session.record_version += 1
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, prev,
            iw.SESSION_CANCELLED, reason=data.comment, actor=actor,
        )
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_CANCEL_SESSION,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(session.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(session)
        return session

    # ══════════════════════════════════════════════════════════════════════════
    # Перевод в READY_FOR_APPLY (§10)
    # ══════════════════════════════════════════════════════════════════════════
    def to_ready_for_apply(
        self, session_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        session = self._repo.get_session_for_update(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        self._require_engineer(actor, session.project_id)
        if session.status not in (
            iw.SESSION_UNDER_REVIEW, iw.SESSION_PARTIALLY_APPLIED,
            iw.SESSION_PARTIALLY_APPLIED_WITH_FAILURES,
        ):
            raise DomainError(
                409, iw.IMPORT_SESSION_INVALID_STATE,
                f"Из статуса {session.status} нельзя перейти в READY_FOR_APPLY",
            )
        payload_hash = _canonical_hash({"cmd": iw.CMD_TO_READY_FOR_APPLY})
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION,
            command_type=iw.CMD_TO_READY_FOR_APPLY,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return session
        self._check_session_version(session, data.expected_record_version)
        self._assert_ready_preconditions(session)
        prev = session.status
        session.status = iw.SESSION_READY_FOR_APPLY
        session.updated_by = actor
        session.record_version += 1
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, prev,
            iw.SESSION_READY_FOR_APPLY, actor=actor,
        )
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION,
            command_type=iw.CMD_TO_READY_FOR_APPLY,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(session.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(session)
        return session

    def _assert_ready_preconditions(self, session: ImportSession) -> None:
        groups = self._repo.list_groups(session.id)
        ready = [g for g in groups if g.status == iw.GROUP_READY]
        blocking = [
            g for g in groups
            if g.status in (iw.GROUP_PENDING, iw.GROUP_BLOCKED, iw.GROUP_FAILED)
        ]
        if blocking:
            raise DomainError(
                409, iw.IMPORT_UNRESOLVED_GROUPS_EXIST,
                "Есть неурегулированные группы (PENDING/BLOCKED/FAILED)",
            )
        if not ready:
            raise DomainError(
                409, iw.IMPORT_NO_READY_GROUPS,
                "Нет ни одной готовой к применению группы",
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Атомарное применение (§9-11)
    # ══════════════════════════════════════════════════════════════════════════
    def apply(
        self, session_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        session = self._repo.get_session_for_update(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        self._require_chief(actor, session.project_id)
        payload_hash = _canonical_hash({"cmd": iw.CMD_APPLY})
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_APPLY,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return session
        if session.status != iw.SESSION_READY_FOR_APPLY:
            raise DomainError(
                409, iw.IMPORT_NOT_READY_FOR_APPLY,
                f"Применение возможно только из READY_FOR_APPLY (сейчас {session.status})",
            )
        self._check_session_version(session, data.expected_record_version)
        self._assert_ready_preconditions(session)

        prev = session.status
        session.status = iw.SESSION_APPLYING
        session.updated_by = actor
        session.record_version += 1
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, prev,
            iw.SESSION_APPLYING, actor=actor,
        )
        attempt = ImportApplyAttempt(
            import_session_id=session.id,
            attempt_no=self._repo.next_apply_attempt_no(session.id),
            initiated_by=actor,
            started_at=_now(),
        )
        self._repo.add_apply_attempt(attempt)
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION, command_type=iw.CMD_APPLY,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(session.id)},
            status_code=200,
        )
        self._db.commit()

        applied = failed = skipped = 0
        infra_stopped = False
        ready_group_ids = [
            g.id for g in self._repo.list_groups(session.id, status=iw.GROUP_READY)
        ]
        for group_id in ready_group_ids:
            outcome = self._apply_one_group(group_id, session.id, attempt.id, actor)
            if outcome == iw.APPLY_RESULT_APPLIED:
                applied += 1
            elif outcome == iw.APPLY_RESULT_FAILED:
                failed += 1
            elif outcome == "INFRA":
                infra_stopped = True
                break

        self._finalize_apply(
            session_id, attempt.id, actor,
            applied=applied, failed=failed, skipped=skipped,
            infra_stopped=infra_stopped,
        )
        return self._repo.get_session(session_id)

    def _apply_one_group(
        self, group_id: UUID, session_id: UUID, attempt_id: UUID, actor: int
    ) -> str:
        """Применяет одну группу в собственной транзакции. Возвращает APPLIED/FAILED/
        'INFRA'. Бизнес-ошибка → FAILED (группа откатывается, обработка продолжается);
        инфраструктурная/DB-ошибка → 'INFRA' (остановка попытки, откат текущей группы,
        ранее применённые не трогаются)."""
        group = self._repo.get_group_for_update(group_id)
        session = self._repo.get_session(session_id)
        prev = group.status
        group.status = iw.GROUP_APPLYING
        self._event(
            session_id, iw.EVENT_ENTITY_GROUP, group.id, prev,
            iw.GROUP_APPLYING, actor=actor,
        )
        try:
            created_joint, created_ops, skipped_rows = self._perform_group_apply(
                group, session, actor
            )
            group.status = iw.GROUP_APPLIED
            group.record_version += 1
            self._repo.add_apply_group_result(
                ImportApplyGroupResult(
                    import_apply_attempt_id=attempt_id,
                    import_group_id=group.id,
                    status=iw.APPLY_RESULT_APPLIED,
                    created_joint_id=(
                        created_joint.id
                        if group.target_type == iw.GROUP_TARGET_NEW_JOINT
                        else None
                    ),
                    selected_joint_id=(
                        created_joint.id
                        if group.target_type == iw.GROUP_TARGET_EXISTING_JOINT
                        else None
                    ),
                    created_weld_operation_ids=[str(o.id) for o in created_ops],
                    row_ids=[str(r.id) for r in self._repo.rows_by_group(group.id)],
                )
            )
            self._event(
                session_id, iw.EVENT_ENTITY_GROUP, group.id, iw.GROUP_APPLYING,
                iw.GROUP_APPLIED, actor=actor,
            )
            self._db.commit()
            return iw.APPLY_RESULT_APPLIED
        except HTTPException as exc:
            # Доменная (бизнес) ошибка группы: откат только её транзакции, FAILED,
            # продолжаем со следующими (§10).
            self._db.rollback()
            self._mark_group_failed(group_id, attempt_id, session_id, actor, exc)
            self._db.commit()
            return iw.APPLY_RESULT_FAILED
        except Exception as exc:  # noqa: BLE001 - инфраструктурная/DB ошибка
            self._db.rollback()
            self._record_infra_failure(group_id, attempt_id, session_id, actor, exc)
            self._db.commit()
            return "INFRA"

    def _perform_group_apply(
        self, group: ImportGroup, session: ImportSession, actor: int
    ):
        """Мутация одной атомарной группы без commit: один Joint + все применяемые
        операции. Пропущенные/дубликатные/отклонённые строки исключаются (§9)."""
        rows = self._repo.rows_by_group_for_update(group.id)
        applicable = [r for r in rows if r.status in iw.ROW_PRODUCTIVE_STATUSES]
        skipped_rows = [
            r for r in rows
            if r.status in (iw.ROW_SKIPPED_DUPLICATE, iw.ROW_RESOLVED_AS_DUPLICATE)
        ]
        if not applicable:
            raise DomainError(
                409, iw.IMPORT_GROUP_INVALID_STATE,
                "В группе нет применяемых строк",
            )
        # Целевой Joint: существующий (проверить, что действующий) или новый.
        if group.target_type == iw.GROUP_TARGET_EXISTING_JOINT:
            joint = self._eng._repo.get_joint(group.target_joint_id)
            if joint is None or joint.status in ("CANCELLED", "SUPERSEDED"):
                raise DomainError(
                    409, iw.IMPORT_GROUP_INVALID_STATE,
                    "Целевой Joint более не действующий",
                )
            self._provenance(
                session, group, None, iw.PROV_MATCHED_EXISTING,
                iw.PROV_TARGET_JOINT, joint_id=joint.id, actor=actor,
            )
        else:
            joint = self._create_new_joint(session, applicable[0], actor)
            self._provenance(
                session, group, applicable[0], iw.PROV_CREATED,
                iw.PROV_TARGET_JOINT, joint_id=joint.id, actor=actor,
            )

        created_ops: list[WeldOperation] = []
        for row in applicable:
            op = self._build_completed_operation(row, joint, actor)
            created_ops.append(op)
            self._provenance(
                session, group, row, iw.PROV_CREATED, iw.PROV_TARGET_WELD_OPERATION,
                operation_id=op.id, actor=actor,
            )
            row_prev = row.status
            row.status = iw.ROW_APPLIED
            row.matched_joint_id = joint.id
            row.updated_by = actor
            row.row_version += 1
            self._event(
                session.id, iw.EVENT_ENTITY_ROW, row.id, row_prev,
                iw.ROW_APPLIED, actor=actor,
            )
        # Провенанс для пропущенных дублей группы (§6: только при применении группы).
        for row in skipped_rows:
            link = (
                iw.PROV_RESOLVED_AS_DUPLICATE
                if row.status == iw.ROW_RESOLVED_AS_DUPLICATE
                else iw.PROV_SKIPPED_DUPLICATE
            )
            if row.matched_weld_operation_id is not None:
                self._provenance(
                    session, group, row, link, iw.PROV_TARGET_WELD_OPERATION,
                    operation_id=row.matched_weld_operation_id, actor=actor,
                )
        return joint, created_ops, skipped_rows

    def _create_new_joint(
        self, session: ImportSession, row: ImportRow, actor: int
    ) -> Joint:
        """Создаёт новый Joint через доменный EngineeringService (без дублирования)."""
        nd = row.normalized_data or {}
        project = self._projects.get_project(session.project_id)
        line = self._projects.get_line_by_project_and_no(
            session.project_id, nd.get("line_code")
        )
        if line is None:
            raise DomainError(
                409, "IMPORT_LINE_NOT_FOUND",
                f"Линия {nd.get('line_code')} не найдена в проекте",
            )
        document = self._eng._repo.get_document_by_project_and_no(
            session.project_id, nd.get("isometric_no")
        )
        if document is None:
            raise DomainError(
                409, "IMPORT_ISOMETRIC_NOT_FOUND",
                f"Изометрия {nd.get('isometric_no')} не найдена в проекте",
            )
        revision = self._eng._repo.get_revision_by_document_and_code(
            document.id, nd.get("revision_code")
        )
        if revision is None:
            raise DomainError(
                409, "IMPORT_REVISION_NOT_FOUND",
                f"Ревизия {nd.get('revision_code')} не найдена",
            )
        return self._eng.create_joint(
            JointCreate(
                project_id=session.project_id,
                line_id=line.id,
                document_revision_id=revision.id,
                joint_no=nd.get("joint_no"),
                created_by=actor,
            )
        )

    def _build_completed_operation(
        self, row: ImportRow, joint: Joint, actor: int
    ) -> WeldOperation:
        """Создаёт и завершает WeldOperation по строке импорта, переиспользуя доменные
        helpers WeldOperationService (без API-гейта ответственного: импорт — отдельный
        авторизованный путь; ответственным фиксируется применяющий актор)."""
        nd = row.normalized_data or {}
        welder = self._repo.resolve_welder_by_stamp(nd.get("welder_stamp_code"))
        if welder is None:
            raise DomainError(
                409, "IMPORT_WELDER_UNRESOLVED",
                f"Клеймо сварщика {nd.get('welder_stamp_code')} не разрешено",
            )
        performed_on = date.fromisoformat(nd["performed_on"])
        started_at = (
            datetime.fromisoformat(nd["started_at"]) if nd.get("started_at") else None
        )
        finished_at = (
            datetime.fromisoformat(nd["finished_at"]) if nd.get("finished_at") else None
        )
        op = WeldOperation(
            joint_id=joint.id,
            sequence_no=self._wos._repo.next_weld_operation_sequence(joint.id),
            lifecycle_status="DRAFT",
            weld_stage=nd["weld_stage"],
            welding_method=nd["welding_method"],
            performed_on=performed_on,
            started_at=started_at,
            finished_at=finished_at,
            actual_welder_id=welder.id,
            entered_stamp_code=nd.get("welder_stamp_code"),
            responsible_worker_id=actor,
            welding_position=nd.get("welding_position"),
            shielding_gas=nd.get("shielding_gas"),
            operation_note=nd.get("operation_note"),
            created_by=actor,
            updated_by=actor,
            record_version=1,
        )
        self._wos._apply_welder_snapshot(op, welder)
        self._wos._apply_executor_snapshot(op, actor)
        self._wos._repo.add_operation(op)
        self._wos._finalize_completion(op, joint, actor)
        self._wos._repo.save_operation(op)
        return op

    def _provenance(
        self,
        session: ImportSession,
        group: ImportGroup,
        row: ImportRow | None,
        link_type: str,
        target_type: str,
        *,
        joint_id: UUID | None = None,
        operation_id: UUID | None = None,
        actor: int,
    ) -> None:
        self._repo.add_provenance(
            ImportProvenance(
                import_session_id=session.id,
                import_row_id=row.id if row is not None else None,
                import_group_id=group.id,
                link_type=link_type,
                target_type=target_type,
                target_joint_id=joint_id,
                target_weld_operation_id=operation_id,
                created_by=actor,
            )
        )

    def _mark_group_failed(
        self, group_id, attempt_id, session_id, actor, exc: HTTPException
    ) -> None:
        group = self._repo.get_group_for_update(group_id)
        prev = group.status
        group.status = iw.GROUP_FAILED
        reasons = list(group.block_reasons)
        if iw.BLOCK_NON_RETRYABLE_FAILURE not in reasons:
            reasons.append(iw.BLOCK_NON_RETRYABLE_FAILURE)
        group.block_reasons = reasons
        group.record_version += 1
        code, message, category = self._error_detail(exc)
        self._repo.add_apply_group_result(
            ImportApplyGroupResult(
                import_apply_attempt_id=attempt_id,
                import_group_id=group.id,
                status=iw.APPLY_RESULT_FAILED,
                row_ids=[str(r.id) for r in self._repo.rows_by_group(group.id)],
                error_category=category,
                error_code=code,
                is_retryable=False,
                error_message=message,
            )
        )
        self._event(
            session_id, iw.EVENT_ENTITY_GROUP, group.id, prev, iw.GROUP_FAILED,
            reason=code, actor=actor,
        )

    def _record_infra_failure(
        self, group_id, attempt_id, session_id, actor, exc: Exception
    ) -> None:
        group = self._repo.get_group_for_update(group_id)
        # Инфраструктурная ошибка: текущая группа откатана, возвращается в READY
        # (не FAILED — причина не бизнес-независимая, §10).
        group.status = iw.GROUP_READY
        self._repo.add_apply_group_result(
            ImportApplyGroupResult(
                import_apply_attempt_id=attempt_id,
                import_group_id=group.id,
                status=iw.APPLY_RESULT_FAILED,
                row_ids=[str(r.id) for r in self._repo.rows_by_group(group.id)],
                error_category=iw.ERR_INFRASTRUCTURE,
                error_code=iw.IMPORT_APPLY_FAILED,
                is_retryable=True,
                error_message=f"{type(exc).__name__}: техническая ошибка применения",
            )
        )

    @staticmethod
    def _error_detail(exc: HTTPException) -> tuple[str, str, str]:
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", iw.IMPORT_APPLY_FAILED)
            message = detail.get("message", "Ошибка применения группы")
        else:
            code = iw.IMPORT_APPLY_FAILED
            message = str(detail)
        return code, message, iw.ERR_BUSINESS

    def _finalize_apply(
        self, session_id, attempt_id, actor, *, applied, failed, skipped, infra_stopped
    ) -> None:
        session = self._repo.get_session_for_update(session_id)
        groups = self._repo.list_groups(session.id)
        remaining = sum(
            1 for g in groups
            if g.status in (iw.GROUP_READY, iw.GROUP_PENDING, iw.GROUP_BLOCKED)
        )
        new_status = iw.session_status_after_apply(
            total_groups=len(groups), applied=applied, failed=failed,
            remaining_actionable=remaining, infra_stopped=infra_stopped,
        )
        # Обновление записи попытки.
        attempt = next(
            (a for a in self._repo.list_apply_attempts(session.id) if a.id == attempt_id),
            None,
        )
        if attempt is not None:
            attempt.finished_at = _now()
            attempt.groups_applied = applied
            attempt.groups_failed = failed
            attempt.groups_skipped = skipped
            if new_status == iw.SESSION_COMPLETED:
                attempt.outcome = iw.ATTEMPT_SUCCEEDED
            elif new_status == iw.SESSION_APPLY_FAILED:
                attempt.outcome = iw.ATTEMPT_FAILED
                attempt.error_category = iw.ERR_INFRASTRUCTURE
            else:
                attempt.outcome = iw.ATTEMPT_PARTIAL
        prev = session.status
        session.status = new_status
        session.updated_by = actor
        session.record_version += 1
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, prev, new_status,
            actor=actor,
        )
        self._db.commit()

    # ══════════════════════════════════════════════════════════════════════════
    # Возврат после сбоев (§10)
    # ══════════════════════════════════════════════════════════════════════════
    def return_session_after_apply_failed(
        self, session_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        session = self._repo.get_session_for_update(session_id)
        if session is None:
            raise NotFoundError("Сессия импорта", session_id)
        self._require_chief(actor, session.project_id)
        if session.status != iw.SESSION_APPLY_FAILED:
            raise DomainError(
                409, iw.IMPORT_SESSION_INVALID_STATE,
                "Возврат допустим только из APPLY_FAILED",
            )
        if not (data.comment and data.comment.strip()):
            raise DomainError(
                422, iw.IMPORT_COMMENT_REQUIRED, "Комментарий обязателен",
            )
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_RETURN_SESSION_AFTER_APPLY_FAILED, "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION,
            command_type=iw.CMD_RETURN_SESSION_AFTER_APPLY_FAILED,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return session
        self._check_session_version(session, data.expected_record_version)
        self._assert_ready_preconditions(session)
        prev = session.status
        session.status = iw.SESSION_READY_FOR_APPLY
        session.updated_by = actor
        session.record_version += 1
        self._event(
            session.id, iw.EVENT_ENTITY_SESSION, session.id, prev,
            iw.SESSION_READY_FOR_APPLY, reason=data.comment, actor=actor,
        )
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION,
            command_type=iw.CMD_RETURN_SESSION_AFTER_APPLY_FAILED,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(session.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(session)
        return session

    def return_group_after_failed(
        self, group_id: UUID, data, *, actor: int, idempotency_key: str | None
    ):
        group = self._repo.get_group_for_update(group_id)
        if group is None:
            raise NotFoundError("Группа импорта", group_id)
        session = self._repo.get_session_for_update(group.import_session_id)
        self._require_chief(actor, session.project_id)
        if group.status != iw.GROUP_FAILED:
            raise DomainError(
                409, iw.IMPORT_GROUP_INVALID_STATE,
                "Возврат допустим только из FAILED",
            )
        if not (data.comment and data.comment.strip()):
            raise DomainError(
                422, iw.IMPORT_COMMENT_REQUIRED, "Комментарий обязателен",
            )
        payload_hash = _canonical_hash(
            {"cmd": iw.CMD_RETURN_GROUP_AFTER_FAILED, "group": str(group_id),
             "comment": data.comment}
        )
        replay = self._check_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION,
            command_type=iw.CMD_RETURN_GROUP_AFTER_FAILED,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash,
        )
        if replay is not None:
            return group
        self._check_group_version(group, data.expected_record_version)
        # Возврат в READY только если пересчёт по строкам даёт READY (доказанное
        # устранение причины, §10). Иначе возврат запрещён.
        rows = self._repo.rows_by_group(group.id)
        computed, reasons = iw.compute_group_status([r.status for r in rows])
        if computed != iw.GROUP_READY:
            raise DomainError(
                409, iw.IMPORT_GROUP_RETURN_NOT_RETRYABLE,
                "Причина сбоя не устранена: группа не готова к применению",
            )
        prev = group.status
        group.status = iw.GROUP_READY
        group.block_reasons = []
        group.record_version += 1
        self._event(
            group.import_session_id, iw.EVENT_ENTITY_GROUP, group.id, prev,
            iw.GROUP_READY, reason=data.comment, actor=actor,
        )
        self._store_idempotency(
            scope=iw.IDEMPOTENCY_SCOPE_SESSION,
            command_type=iw.CMD_RETURN_GROUP_AFTER_FAILED,
            key=idempotency_key, session_id=session.id, user_id=actor,
            payload_hash=payload_hash, response_payload={"id": str(group.id)},
            status_code=200,
        )
        self._db.commit()
        self._db.refresh(group)
        return group
