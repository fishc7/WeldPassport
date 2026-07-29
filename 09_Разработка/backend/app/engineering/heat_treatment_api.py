"""HTTP-слой термической обработки (Task 8F).

Отдельный роутер под существующим префиксом engineering (§26). Actor — только из
X-User-Id. Бизнес-действия оформлены командами (plan/start/complete/review/close/
cancel), а не универсальным update. Физического DELETE нет.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.engineering.heat_treatment_schemas import (
    HeatTreatmentBatchCancelCommand,
    HeatTreatmentBatchCompleteCommand,
    HeatTreatmentBatchCloseCommand,
    HeatTreatmentBatchCreate,
    HeatTreatmentBatchListFilters,
    HeatTreatmentBatchListResponse,
    HeatTreatmentBatchPlanCommand,
    HeatTreatmentBatchRead,
    HeatTreatmentBatchReviewCommand,
    HeatTreatmentBatchStartCommand,
    HeatTreatmentBatchUpdate,
    HeatTreatmentDeviationCreate,
    HeatTreatmentDeviationDecisionCommand,
    HeatTreatmentDeviationRead,
    HeatTreatmentJournalResponse,
    HeatTreatmentOperationCreate,
    HeatTreatmentOperationEvaluateCommand,
    HeatTreatmentOperationExcludeCommand,
    HeatTreatmentOperationRead,
    HeatTreatmentOperationUpdate,
    HeatTreatmentRecordCreate,
    HeatTreatmentRecordRead,
    JointHeatTreatmentStateRead,
    ProcedureRevisionCreate,
    ProcedureRevisionRead,
)
from app.engineering.heat_treatment_services import HeatTreatmentService
from app.engineering.heat_treatment_workflow import OperationResult
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(prefix="/engineering", tags=["engineering-heat-treatment"])


def _svc(db: Session = Depends(get_db)) -> HeatTreatmentService:
    return HeatTreatmentService(db)


# ── Технологическая карта (минимальная ссылочная сущность) ────────────────────


@router.post(
    "/heat-treatment-procedures",
    response_model=ProcedureRevisionRead,
    status_code=201,
)
def create_procedure(
    data: ProcedureRevisionCreate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_procedure(data, actor_worker_id=uid)


@router.get(
    "/heat-treatment-procedures/{revision_id}",
    response_model=ProcedureRevisionRead,
)
def get_procedure(
    revision_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_procedure(revision_id)


@router.post(
    "/heat-treatment-procedures/{revision_id}/approve",
    response_model=ProcedureRevisionRead,
)
def approve_procedure(
    revision_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.approve_procedure(revision_id, actor_worker_id=uid)


@router.post(
    "/heat-treatment-procedures/{revision_id}/cancel",
    response_model=ProcedureRevisionRead,
)
def cancel_procedure(
    revision_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_procedure(revision_id, actor_worker_id=uid)


# ── Циклы ─────────────────────────────────────────────────────────────────────


@router.post(
    "/heat-treatment-batches",
    response_model=HeatTreatmentBatchRead,
    status_code=201,
)
def create_batch(
    data: HeatTreatmentBatchCreate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.create_batch(data, actor_worker_id=uid)


def _batch_filters(
    project_id: UUID | None = Query(default=None),
    procedure_revision_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    review_result: str | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> HeatTreatmentBatchListFilters:
    return HeatTreatmentBatchListFilters(
        project_id=project_id,
        procedure_revision_id=procedure_revision_id,
        status=status,
        review_result=review_result,
        batch_no=batch_no,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/heat-treatment-batches", response_model=HeatTreatmentBatchListResponse
)
def list_batches(
    filters: HeatTreatmentBatchListFilters = Depends(_batch_filters),
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_batches(filters)


@router.get(
    "/heat-treatment-batches/{batch_id}", response_model=HeatTreatmentBatchRead
)
def get_batch(
    batch_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_batch(batch_id)


@router.patch(
    "/heat-treatment-batches/{batch_id}", response_model=HeatTreatmentBatchRead
)
def update_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchUpdate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_batch(batch_id, data, actor_worker_id=uid)


# ── Workflow цикла ────────────────────────────────────────────────────────────


@router.post(
    "/heat-treatment-batches/{batch_id}/plan",
    response_model=HeatTreatmentBatchRead,
)
def plan_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchPlanCommand = HeatTreatmentBatchPlanCommand(),
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.plan_batch(batch_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-batches/{batch_id}/start",
    response_model=HeatTreatmentBatchRead,
)
def start_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchStartCommand = HeatTreatmentBatchStartCommand(),
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.start_batch(batch_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-batches/{batch_id}/complete",
    response_model=HeatTreatmentBatchRead,
)
def complete_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchCompleteCommand = HeatTreatmentBatchCompleteCommand(),
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.complete_batch(batch_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-batches/{batch_id}/review",
    response_model=HeatTreatmentBatchRead,
)
def review_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchReviewCommand,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.review_batch(batch_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-batches/{batch_id}/close",
    response_model=HeatTreatmentBatchRead,
)
def close_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchCloseCommand = HeatTreatmentBatchCloseCommand(),
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.close_batch(batch_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-batches/{batch_id}/cancel",
    response_model=HeatTreatmentBatchRead,
)
def cancel_batch(
    batch_id: UUID,
    data: HeatTreatmentBatchCancelCommand,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.cancel_batch(batch_id, data, actor_worker_id=uid)


# ── Операции по соединениям ───────────────────────────────────────────────────


@router.post(
    "/heat-treatment-batches/{batch_id}/operations",
    response_model=HeatTreatmentOperationRead,
    status_code=201,
)
def add_operation(
    batch_id: UUID,
    data: HeatTreatmentOperationCreate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_operation(batch_id, data, actor_worker_id=uid)


@router.get(
    "/heat-treatment-batches/{batch_id}/operations",
    response_model=list[HeatTreatmentOperationRead],
)
def list_operations(
    batch_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_operations(batch_id)


@router.get(
    "/heat-treatment-operations/{operation_id}",
    response_model=HeatTreatmentOperationRead,
)
def get_operation(
    operation_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.get_operation(operation_id)


@router.patch(
    "/heat-treatment-operations/{operation_id}",
    response_model=HeatTreatmentOperationRead,
)
def update_operation(
    operation_id: UUID,
    data: HeatTreatmentOperationUpdate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.update_operation(operation_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-operations/{operation_id}/exclude",
    response_model=HeatTreatmentOperationRead,
)
def exclude_operation(
    operation_id: UUID,
    data: HeatTreatmentOperationExcludeCommand,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.exclude_operation(operation_id, data, actor_worker_id=uid)


@router.post(
    "/heat-treatment-operations/{operation_id}/evaluate",
    response_model=HeatTreatmentOperationRead,
)
def evaluate_operation(
    operation_id: UUID,
    data: HeatTreatmentOperationEvaluateCommand,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.evaluate_operation(operation_id, data, actor_worker_id=uid)


# ── Документы ─────────────────────────────────────────────────────────────────


@router.post(
    "/heat-treatment-batches/{batch_id}/records",
    response_model=HeatTreatmentRecordRead,
    status_code=201,
)
def add_record(
    batch_id: UUID,
    data: HeatTreatmentRecordCreate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_record(batch_id, data, actor_worker_id=uid)


@router.get(
    "/heat-treatment-batches/{batch_id}/records",
    response_model=list[HeatTreatmentRecordRead],
)
def list_records(
    batch_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_records(batch_id)


@router.post(
    "/heat-treatment-records/{record_id}/verify",
    response_model=HeatTreatmentRecordRead,
)
def verify_record(
    record_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.verify_record(record_id, actor_worker_id=uid)


@router.post(
    "/heat-treatment-records/{record_id}/reject",
    response_model=HeatTreatmentRecordRead,
)
def reject_record(
    record_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.reject_record(record_id, actor_worker_id=uid)


# ── Отклонения ────────────────────────────────────────────────────────────────


@router.post(
    "/heat-treatment-batches/{batch_id}/deviations",
    response_model=HeatTreatmentDeviationRead,
    status_code=201,
)
def add_deviation(
    batch_id: UUID,
    data: HeatTreatmentDeviationCreate,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.add_deviation(batch_id, data, actor_worker_id=uid)


@router.get(
    "/heat-treatment-batches/{batch_id}/deviations",
    response_model=list[HeatTreatmentDeviationRead],
)
def list_deviations(
    batch_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.list_deviations(batch_id)


@router.post(
    "/heat-treatment-deviations/{deviation_id}/decision",
    response_model=HeatTreatmentDeviationRead,
)
def decide_deviation(
    deviation_id: UUID,
    data: HeatTreatmentDeviationDecisionCommand,
    svc: HeatTreatmentService = Depends(_svc),
    uid: int = Depends(get_current_user_id),
):
    return svc.decide_deviation(deviation_id, data, actor_worker_id=uid)


# ── Журнал термообработки ─────────────────────────────────────────────────────


@router.get(
    "/heat-treatment-journal", response_model=HeatTreatmentJournalResponse
)
def heat_treatment_journal(
    project_id: UUID | None = Query(default=None),
    line_id: UUID | None = Query(default=None),
    joint_id: UUID | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    result: OperationResult | None = Query(default=None),
    performed_from: datetime | None = Query(default=None),
    performed_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.journal(
        project_id=project_id,
        line_id=line_id,
        joint_id=joint_id,
        batch_no=batch_no,
        result=result,
        performed_from=performed_from,
        performed_to=performed_to,
        limit=limit,
        offset=offset,
    )


# ── Интеграция с Joint (§23) ──────────────────────────────────────────────────


@router.get(
    "/joints/{joint_id}/heat-treatment-state",
    response_model=JointHeatTreatmentStateRead,
)
def joint_heat_treatment_state(
    joint_id: UUID,
    svc: HeatTreatmentService = Depends(_svc),
    _uid: int = Depends(get_current_user_id),
):
    return svc.joint_state(joint_id)
