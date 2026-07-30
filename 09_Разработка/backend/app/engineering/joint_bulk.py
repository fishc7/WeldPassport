"""Массовое создание Joint (Task 7, ADR-010).

Bulk — альтернативный способ выполнения существующего сценария создания Joint, а
не отдельная предметная модель. Оркестрация (двухфазный алгоритм, идемпотентность,
атомарность) вынесена в `JointBulkService`, но вся доменная логика (нормализация
`joint_no`, построение Joint, ORIGIN/PRIMARY-снимок, выдача `system_code`)
переиспользуется из `EngineeringService` (`_stage_joint`) — параллельной реализации
нет.

Двухфазный алгоритм:
  Фаза 1 — полная бизнес-валидация без записи (сбор ВСЕХ ошибок с `row_index`).
  Фаза 2 — атомарное создание Joint строго по `row_index` в одной транзакции;
           `system_code` выдаётся только после успешной валидации всего пакета.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from app.engineering import joint_workflow as jw
from app.engineering.models import JointBulkRequest
from app.engineering.schemas import (
    JointBulkCreate,
    JointBulkResponse,
    JointBulkResultItem,
    JointBulkValidationError,
)
from app.engineering.services import (
    _JOINT_ENGINEERING_FIELDS,
    EngineeringService,
    normalize_joint_no,
)
from app.shared.errors import DomainError
from app.shared.permissions import JointScopeContext, worker_role_codes_for_joint


# ── Канонический request hash (§8 задания) ────────────────────────────────────


def canonicalize_bulk_request(payload: JointBulkCreate) -> str:
    """Каноническое JSON-представление валидированного тела без `idempotency_key`.

    Ключи объектов сортируются (порядок ключей входного JSON не влияет на hash);
    порядок `items` сохраняется (перестановка строк меняет hash). UUID → строка,
    Decimal → стабильная строка, date/datetime → ISO — обеспечивает Pydantic
    `model_dump(mode="json")`; компактные separators и UTF-8 фиксируют байты.
    """
    data = payload.model_dump(mode="json", exclude={"idempotency_key"})
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def calculate_bulk_request_hash(payload: JointBulkCreate) -> str:
    canonical = canonicalize_bulk_request(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class JointBulkExecutionResult:
    """Результат выполнения пакета. `replayed` различает новое создание (201) и
    идемпотентный повтор (200); `response_payload` — сохранённый/собранный JSON."""

    response_payload: dict
    replayed: bool


class JointBulkService(EngineeringService):
    """Оркестрация bulk-импорта поверх доменной логики EngineeringService."""

    def create_bulk(
        self, *, payload: JointBulkCreate, actor_worker_id: int
    ) -> JointBulkExecutionResult:
        request_hash = calculate_bulk_request_hash(payload)
        key = payload.idempotency_key  # уже обрезан схемой (strip)

        # Идемпотентность: до создания ищем запись по (project_id, key) (§9).
        existing = self._repo.get_joint_bulk_request(payload.project_id, key)
        if existing is not None:
            if existing.request_hash == request_hash:
                return JointBulkExecutionResult(
                    existing.response_payload, replayed=True
                )
            raise self._idempotency_conflict()

        # Фаза 1 — полная валидация без записи; собираем ВСЕ ошибки.
        errors = self._collect_bulk_validation_errors(payload, actor_worker_id)
        if errors:
            raise DomainError(
                422,
                jw.BULK_VALIDATION_FAILED,
                "Массовое создание отклонено: есть ошибки валидации",
                errors=[e.model_dump(exclude_none=True) for e in errors],
            )

        # Фаза 2 — атомарное создание (проект гарантированно существует).
        project = self._projects.get_project(payload.project_id)
        return self._execute_bulk(payload, project, request_hash=request_hash, key=key)

    # ── Ошибки ────────────────────────────────────────────────────────────────

    @staticmethod
    def _idempotency_conflict() -> DomainError:
        return DomainError(
            409,
            jw.IDEMPOTENCY_KEY_CONFLICT,
            "Ключ идемпотентности уже использован для другого содержимого",
        )

    # ── Фаза 1: валидация ───────────────────────────────────────────────────────

    def _collect_bulk_validation_errors(
        self, payload: JointBulkCreate, actor_worker_id: int
    ) -> list[JointBulkValidationError]:
        """Собирает ошибки: сначала общий контекст (без row_index), затем строки
        по возрастанию row_index (§10 задания)."""
        general = self._validate_bulk_context(payload, actor_worker_id)
        rows = self._validate_bulk_items(payload)
        return general + rows

    def _validate_bulk_context(
        self, payload: JointBulkCreate, actor_worker_id: int
    ) -> list[JointBulkValidationError]:
        errors: list[JointBulkValidationError] = []

        def add(code: str, field: str, message: str) -> None:
            errors.append(
                JointBulkValidationError(field=field, code=code, message=message)
            )

        # created_by == server-authenticated actor worker id: создание от имени другого работника запрещено.
        if payload.created_by != actor_worker_id:
            add(
                jw.CREATED_BY_MISMATCH,
                "created_by",
                "created_by должен совпадать с server-authenticated actor worker id",
            )

        project = self._projects.get_project(payload.project_id)
        if project is None:
            add(jw.PROJECT_NOT_FOUND, "project_id", "Проект не найден")

        line = self._projects.get_line(payload.line_id)
        if line is None:
            add(jw.LINE_NOT_FOUND, "line_id", "Линия не найдена")
        elif project is not None and line.project_id != project.id:
            add(
                jw.LINE_PROJECT_MISMATCH,
                "line_id",
                "Линия принадлежит другому проекту",
            )

        revision = self._repo.get_revision(payload.document_revision_id)
        document = None
        if revision is None:
            add(
                jw.DOCUMENT_REVISION_NOT_FOUND,
                "document_revision_id",
                "Ревизия документа не найдена",
            )
        else:
            document = self._repo.get_document(revision.engineering_document_id)
            if document is None or (
                project is not None and document.project_id != project.id
            ):
                add(
                    jw.DOCUMENT_PROJECT_MISMATCH,
                    "document_revision_id",
                    "Ревизия принадлежит документу другого проекта",
                )
            else:
                if (
                    document.line_id is not None
                    and document.line_id != payload.line_id
                ):
                    add(
                        jw.DOCUMENT_LINE_MISMATCH,
                        "document_revision_id",
                        "Линия документа-основания не совпадает с линией стыка",
                    )
                # Единое правило источника Joint (общий доменный helper, тот же,
                # что у одиночного создания): и документ, и ревизия — APPROVED.
                if (
                    jw.joint_source_status_error(document.status, revision.status)
                    is not None
                ):
                    add(
                        jw.DOCUMENT_REVISION_NOT_ALLOWED,
                        "document_revision_id",
                        "Создание Joint возможно только из APPROVED документа и "
                        "ревизии",
                    )

        # Роль/scope актора — только если проект существует (нужен контекст).
        if project is not None and not self._actor_can_create(
            project, payload.line_id, document, actor_worker_id
        ):
            add(
                jw.INSUFFICIENT_SCOPE,
                "created_by",
                "У актора нет роли создания Joint в подходящем scope",
            )
        return errors

    def _actor_can_create(
        self, project, line_id, document, actor_worker_id: int
    ) -> bool:
        """Есть ли у актора роль создания Joint (Task 5A + admin), покрывающая
        контекст по иерархии scope (§7 задания, §19 ADR-011)."""
        engineering_document_id = document.id if document is not None else None
        ctx = JointScopeContext(
            project_id=project.id,
            line_id=line_id,
            engineering_document_id=engineering_document_id,
            company_ids=frozenset(self._projects.active_company_ids(project.id)),
        )
        granted = worker_role_codes_for_joint(
            self._db, actor_worker_id, jw.BULK_CREATE_ROLES, ctx
        )
        return bool(granted)

    def _validate_bulk_items(
        self, payload: JointBulkCreate
    ) -> list[JointBulkValidationError]:
        """Построчная валидация: дубли внутри пакета (для ВСЕХ конфликтующих строк)
        и конфликт с активными Joint ревизии (batch-запросом, без N+1)."""
        errors: list[JointBulkValidationError] = []
        normalized = [normalize_joint_no(item.joint_no) for item in payload.items]
        counts = Counter(normalized)

        existing: set[str] = set()
        revision = self._repo.get_revision(payload.document_revision_id)
        if revision is not None:
            existing = self._repo.find_active_joint_numbers_for_revision(
                payload.document_revision_id, set(normalized)
            )

        for idx, norm in enumerate(normalized):
            # Стабильный порядок внутри строки: дубль-в-пакете, затем конфликт-в-ревизии.
            if counts[norm] > 1:
                errors.append(
                    JointBulkValidationError(
                        row_index=idx,
                        field="joint_no",
                        code=jw.DUPLICATE_JOINT_NO_IN_BATCH,
                        message="Обозначение Joint повторяется внутри пакета",
                    )
                )
            if norm in existing:
                errors.append(
                    JointBulkValidationError(
                        row_index=idx,
                        field="joint_no",
                        code=jw.JOINT_NO_ALREADY_EXISTS_IN_REVISION,
                        message="Стык с таким номером уже существует в этой ревизии",
                    )
                )
        return errors

    # ── Фаза 2: атомарное создание ──────────────────────────────────────────────

    def _execute_bulk(
        self, payload: JointBulkCreate, project, *, request_hash: str, key: str
    ) -> JointBulkExecutionResult:
        try:
            result_items: list[JointBulkResultItem] = []
            for idx, item in enumerate(payload.items):
                engineering_values = item.model_dump(
                    include=set(_JOINT_ENGINEERING_FIELDS)
                )
                joint = self._stage_joint(
                    project,
                    line_id=payload.line_id,
                    revision_id=payload.document_revision_id,
                    joint_no=item.joint_no,
                    engineering_values=engineering_values,
                    created_by=payload.created_by,
                )
                result_items.append(
                    JointBulkResultItem(
                        row_index=idx,
                        id=joint.id,
                        system_code=joint.system_code,
                        joint_no=item.joint_no,
                    )
                )

            bulk_request = JointBulkRequest(
                project_id=payload.project_id,
                idempotency_key=key,
                request_hash=request_hash,
                status="COMPLETED",
                created_by=payload.created_by,
                response_payload={},  # заполняется ниже (нужен id записи)
            )
            self._repo.add_joint_bulk_request(bulk_request)

            response = JointBulkResponse(
                bulk_request_id=bulk_request.id,
                project_id=payload.project_id,
                line_id=payload.line_id,
                document_revision_id=payload.document_revision_id,
                created_by=payload.created_by,
                created_count=len(result_items),
                items=result_items,
            )
            response_payload = response.model_dump(mode="json")
            bulk_request.response_payload = response_payload

            self._db.commit()
            return JointBulkExecutionResult(response_payload, replayed=False)
        except IntegrityError:
            # UNIQUE(project_id, idempotency_key) или конфликт joint_no ревизии —
            # последняя защита при гонке. Откат всего пакета, затем разбор.
            self._db.rollback()
            return self._resolve_integrity(payload, request_hash=request_hash, key=key)
        except Exception:
            # Любая иная ошибка фазы 2 — полный откат, частичного импорта нет.
            self._db.rollback()
            raise

    def _resolve_integrity(
        self, payload: JointBulkCreate, *, request_hash: str, key: str
    ) -> JointBulkExecutionResult:
        """Разбор IntegrityError после отката: гонка ключа → replay/409; иначе —
        конкурентный конфликт joint_no во второй фазе → контролируемый 409 (§9,§12)."""
        existing = self._repo.get_joint_bulk_request(payload.project_id, key)
        if existing is not None:
            if existing.request_hash == request_hash:
                return JointBulkExecutionResult(
                    existing.response_payload, replayed=True
                )
            raise self._idempotency_conflict()
        raise DomainError(
            409,
            jw.JOINT_NO_CONFLICT,
            "Конфликт номера стыка при конкурентном создании пакета",
        )
