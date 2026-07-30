"""HTTP API выполнения метода контроля и лабораторного заключения (Task 9C, 9C-6B).

Только транспорт: маршруты поверх существующих Pydantic-схем и сервисов. Бизнес-
логики здесь нет — API не проверяет lifecycle, не считает оценку, не проверяет
лабораторию, не пишет аудит и не меняет статусы напрямую. Всё это делает сервисный
слой; API лишь конвертирует схему в service-DTO, вызывает сервис и сериализует
результат response-моделью. `DomainError` (подкласс HTTPException) отдаётся FastAPI
как есть — отдельный mapping не нужен.

Actor берётся из server-authenticated actor worker id (`get_current_user_id`), не из тела запроса.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.quality.execution_schemas import (
    CancelExecutionCommand,
    ConfirmExecutionCommand,
    CreateExecutionRevisionCommand,
    ExcludeResultItemCommand,
    MarkPerformedCommand,
    MethodExecutionCreate,
    MethodExecutionRead,
    ParticipantCreate,
    ParticipantRead,
    RecordResultCommand,
    ResultItemCreate,
    ResultItemRead,
    StartExecutionCommand,
)
from app.quality.laboratory_conclusion_schemas import (
    AddConclusionExecutionCommand,
    ApproveConclusionCommand,
    CancelConclusionCommand,
    ConclusionCreate,
    ConclusionExecutionRead,
    ConclusionRead,
    CreateConclusionRevisionCommand,
    IssueConclusionCommand,
    PrepareConclusionCommand,
)
from app.quality.laboratory_conclusion_services import (
    ApproveConclusionInput,
    CancelConclusionInput,
    ConclusionCreateInput,
    IssueConclusionInput,
    LaboratoryConclusionRevisionService,
    LaboratoryConclusionService,
)
from app.quality.method_execution_services import (
    CancelExecutionInput,
    ConfirmInput,
    ExecutionCreateInput,
    MarkPerformedInput,
    MethodExecutionResultService,
    MethodExecutionRevisionService,
    MethodExecutionService,
    ParticipantInput,
    ResultItemInput,
)
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(tags=["quality"])


def _exec(db: Session = Depends(get_db)) -> MethodExecutionService:
    return MethodExecutionService(db)


def _result(db: Session = Depends(get_db)) -> MethodExecutionResultService:
    return MethodExecutionResultService(db)


def _exec_rev(db: Session = Depends(get_db)) -> MethodExecutionRevisionService:
    return MethodExecutionRevisionService(db)


def _conc(db: Session = Depends(get_db)) -> LaboratoryConclusionService:
    return LaboratoryConclusionService(db)


def _conc_rev(db: Session = Depends(get_db)) -> LaboratoryConclusionRevisionService:
    return LaboratoryConclusionRevisionService(db)


# ── MethodExecution: создание, чтение, lifecycle ────────────────────────────────


@router.post(
    "/method-assignments/{assignment_id}/executions",
    response_model=MethodExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution(
    assignment_id: UUID,
    data: MethodExecutionCreate,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_execution(
        assignment_id, ExecutionCreateInput(**data.model_dump()), actor_worker_id=uid
    )


@router.get(
    "/method-assignments/{assignment_id}/executions",
    response_model=list[MethodExecutionRead],
)
def list_executions(
    assignment_id: UUID,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_executions(assignment_id, actor_worker_id=uid)


@router.get(
    "/method-executions/{execution_id}", response_model=MethodExecutionRead
)
def get_execution(
    execution_id: UUID,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_execution(execution_id, actor_worker_id=uid)


@router.post(
    "/method-executions/{execution_id}/start", response_model=MethodExecutionRead
)
def start_execution(
    execution_id: UUID,
    data: StartExecutionCommand,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.start(execution_id, data.expected_version, actor_worker_id=uid)


@router.post(
    "/method-executions/{execution_id}/mark-performed",
    response_model=MethodExecutionRead,
)
def mark_performed(
    execution_id: UUID,
    data: MarkPerformedCommand,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.mark_performed(
        execution_id, MarkPerformedInput(**data.model_dump()), actor_worker_id=uid
    )


@router.post(
    "/method-executions/{execution_id}/record-result",
    response_model=MethodExecutionRead,
)
def record_result(
    execution_id: UUID,
    data: RecordResultCommand,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.record_result(
        execution_id, data.expected_version, actor_worker_id=uid
    )


@router.post(
    "/method-executions/{execution_id}/confirm", response_model=MethodExecutionRead
)
def confirm_execution(
    execution_id: UUID,
    data: ConfirmExecutionCommand,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.confirm(
        execution_id, ConfirmInput(**data.model_dump()), actor_worker_id=uid
    )


@router.post(
    "/method-executions/{execution_id}/cancel", response_model=MethodExecutionRead
)
def cancel_execution(
    execution_id: UUID,
    data: CancelExecutionCommand,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel(
        execution_id, CancelExecutionInput(**data.model_dump()), actor_worker_id=uid
    )


# ── Участники ───────────────────────────────────────────────────────────────────


@router.post(
    "/method-executions/{execution_id}/participants",
    response_model=ParticipantRead,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    execution_id: UUID,
    data: ParticipantCreate,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_participant(
        execution_id, ParticipantInput(**data.model_dump()), actor_worker_id=uid
    )


@router.delete(
    "/method-execution-participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_participant(
    participant_id: UUID,
    svc: MethodExecutionService = Depends(_exec),
    uid: int = Depends(get_current_user_id),
):
    svc.delete_participant(participant_id, actor_worker_id=uid)


# ── Локальные результаты ────────────────────────────────────────────────────────


@router.post(
    "/method-executions/{execution_id}/result-items",
    response_model=ResultItemRead,
    status_code=status.HTTP_201_CREATED,
)
def add_result_item(
    execution_id: UUID,
    data: ResultItemCreate,
    svc: MethodExecutionResultService = Depends(_result),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_result_item(
        execution_id, ResultItemInput(**data.model_dump()), actor_worker_id=uid
    )


@router.post(
    "/method-result-items/{item_id}/complete", response_model=ResultItemRead
)
def complete_result_item(
    item_id: UUID,
    svc: MethodExecutionResultService = Depends(_result),
    uid: int = Depends(get_current_user_id),
):
    return svc.complete_result_item(item_id, actor_worker_id=uid)


@router.post(
    "/method-result-items/{item_id}/exclude", response_model=ResultItemRead
)
def exclude_result_item(
    item_id: UUID,
    data: ExcludeResultItemCommand,
    svc: MethodExecutionResultService = Depends(_result),
    uid: int = Depends(get_current_user_id),
):
    return svc.exclude_result_item(item_id, data.reason, actor_worker_id=uid)


# ── Редакции выполнения ─────────────────────────────────────────────────────────


@router.post(
    "/method-executions/{execution_id}/revisions",
    response_model=MethodExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution_revision(
    execution_id: UUID,
    data: CreateExecutionRevisionCommand,
    svc: MethodExecutionRevisionService = Depends(_exec_rev),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_revision(
        execution_id,
        correction_reason=data.correction_reason,
        expected_version=data.expected_version,
        actor_worker_id=uid,
    )


@router.get(
    "/method-executions/{execution_id}/revisions",
    response_model=list[MethodExecutionRead],
)
def list_execution_revisions(
    execution_id: UUID,
    svc: MethodExecutionRevisionService = Depends(_exec_rev),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_revisions(execution_id, actor_worker_id=uid)


# ── LaboratoryConclusion ────────────────────────────────────────────────────────


@router.post(
    "/laboratory-conclusions",
    response_model=ConclusionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_conclusion(
    data: ConclusionCreate,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_conclusion(
        ConclusionCreateInput(**data.model_dump()), actor_worker_id=uid
    )


@router.get(
    "/laboratory-conclusions/{conclusion_id}", response_model=ConclusionRead
)
def get_conclusion(
    conclusion_id: UUID,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.get_conclusion(conclusion_id, actor_worker_id=uid)


@router.post(
    "/laboratory-conclusions/{conclusion_id}/executions",
    response_model=ConclusionExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def add_conclusion_execution(
    conclusion_id: UUID,
    data: AddConclusionExecutionCommand,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_execution(
        conclusion_id, data.method_execution_id, actor_worker_id=uid
    )


@router.post(
    "/laboratory-conclusions/{conclusion_id}/prepare",
    response_model=ConclusionRead,
)
def prepare_conclusion(
    conclusion_id: UUID,
    data: PrepareConclusionCommand,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.prepare(conclusion_id, data.expected_version, actor_worker_id=uid)


@router.post(
    "/laboratory-conclusions/{conclusion_id}/approve",
    response_model=ConclusionRead,
)
def approve_conclusion(
    conclusion_id: UUID,
    data: ApproveConclusionCommand,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.approve(
        conclusion_id,
        ApproveConclusionInput(
            expected_version=data.expected_version,
            lab_approver_person_id=data.lab_approver_person_id,
        ),
        actor_worker_id=uid,
    )


@router.post(
    "/laboratory-conclusions/{conclusion_id}/issue", response_model=ConclusionRead
)
def issue_conclusion(
    conclusion_id: UUID,
    data: IssueConclusionCommand,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.issue(
        conclusion_id, IssueConclusionInput(**data.model_dump()), actor_worker_id=uid
    )


@router.post(
    "/laboratory-conclusions/{conclusion_id}/cancel", response_model=ConclusionRead
)
def cancel_conclusion(
    conclusion_id: UUID,
    data: CancelConclusionCommand,
    svc: LaboratoryConclusionService = Depends(_conc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel(
        conclusion_id,
        CancelConclusionInput(
            expected_version=data.expected_version, reason=data.reason
        ),
        actor_worker_id=uid,
    )


@router.post(
    "/laboratory-conclusions/{conclusion_id}/revisions",
    response_model=ConclusionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_conclusion_revision(
    conclusion_id: UUID,
    data: CreateConclusionRevisionCommand,
    svc: LaboratoryConclusionRevisionService = Depends(_conc_rev),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_revision(
        conclusion_id,
        correction_reason=data.correction_reason,
        expected_version=data.expected_version,
        conclusion_number=data.conclusion_number,
        actor_worker_id=uid,
    )


@router.get(
    "/laboratory-conclusions/{conclusion_id}/revisions",
    response_model=list[ConclusionRead],
)
def list_conclusion_revisions(
    conclusion_id: UUID,
    svc: LaboratoryConclusionRevisionService = Depends(_conc_rev),
    uid: int = Depends(get_current_user_id),
):
    return svc.list_revisions(conclusion_id, actor_worker_id=uid)
