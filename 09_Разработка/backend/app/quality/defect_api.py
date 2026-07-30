"""HTTP-слой технической модели Defect и справочников (Task 9D-3C-3; Spec 9D-3C).

Тонкий транспорт поверх `DefectService` (9D-3B/9D-3C-2): маршрутизация, Pydantic-валидация,
сериализация ORM и извлечение актора из `server-authenticated actor worker id`. Доменные проверки (CONFIRMED_DEFECT,
Joint-инвариант, lifecycle, supersede, version, RBAC, обязательность полей ACTIVE) — в сервисе;
здесь не дублируются. `DomainError` наследует `HTTPException`, поэтому ошибки сервиса проходят
без ручного remapping (в проекте нет exception_handler'ов).

Маршруты монтируются под `/api/v1` в `app/main.py`; namespace `/quality/defects…` — в пути.
Бизнес-действия оформлены командами (activate/supersede/cancel), а не универсальным PATCH статуса.
Справочники — authenticated global read-only: требуют `server-authenticated actor worker id`, но актор в reference-сервисы
не передаётся (нет Joint-scope) — аутентификация выражена route-level `dependencies`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.quality.defect_schemas import (
    DefectActivateCommand,
    DefectCancelCommand,
    DefectCreateRequest,
    DefectEventRead,
    DefectLocationTypeRead,
    DefectRead,
    DefectSupersedeCommand,
    DefectTypeRead,
    DefectUpdateRequest,
)
from app.quality.defect_services import DefectService
from app.shared.auth import get_current_user_id
from app.shared.db import get_db

router = APIRouter(tags=["Quality — Defects"])


def _svc(db: Session = Depends(get_db)) -> DefectService:
    return DefectService(db)


# ── Defect: создание ──────────────────────────────────────────────────────────────


@router.post("/quality/defects", response_model=DefectRead, status_code=201)
def create_defect(
    payload: DefectCreateRequest,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    # Технические поля без контекста/управления; явный null сохраняется (exclude_unset),
    # непереданное поле в fields не попадает. exclude_none НЕ используется.
    fields = payload.model_dump(
        exclude={"joint_id", "engineering_evaluation_id", "activate"},
        exclude_unset=True,
    )
    if payload.activate:
        return svc.create_active(
            joint_id=payload.joint_id,
            engineering_evaluation_id=payload.engineering_evaluation_id,
            actor_worker_id=actor_worker_id,
            fields=fields,
        )
    return svc.create_draft(
        joint_id=payload.joint_id,
        engineering_evaluation_id=payload.engineering_evaluation_id,
        actor_worker_id=actor_worker_id,
        fields=fields,
    )


# ── Defect: список по стыку (обязательный joint_id; только ACTIVE — контракт сервиса) ─


@router.get("/quality/defects", response_model=list[DefectRead])
def list_defects(
    joint_id: UUID = Query(...),
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.list_by_joint(joint_id, actor_worker_id=actor_worker_id)


# ── Defect: получение одной ревизии ───────────────────────────────────────────────


@router.get("/quality/defects/{defect_id}", response_model=DefectRead)
def get_defect(
    defect_id: UUID,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.get(defect_id, actor_worker_id=actor_worker_id)


# ── Defect: правка DRAFT ──────────────────────────────────────────────────────────


@router.patch("/quality/defects/{defect_id}", response_model=DefectRead)
def update_defect(
    defect_id: UUID,
    payload: DefectUpdateRequest,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    fields = payload.model_dump(
        exclude={"expected_version", "reason"}, exclude_unset=True
    )
    return svc.update_draft(
        defect_id,
        expected_version=payload.expected_version,
        actor_worker_id=actor_worker_id,
        fields=fields,
        reason=payload.reason,
    )


# ── Defect: активация DRAFT → ACTIVE ──────────────────────────────────────────────


@router.post("/quality/defects/{defect_id}/activate", response_model=DefectRead)
def activate_defect(
    defect_id: UUID,
    payload: DefectActivateCommand,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.activate(
        defect_id,
        expected_version=payload.expected_version,
        actor_worker_id=actor_worker_id,
    )


# ── Defect: supersede (ACTIVE → SUPERSEDED + новая DRAFT; активация отдельной командой) ─


@router.post("/quality/defects/{defect_id}/supersede", response_model=DefectRead)
def supersede_defect(
    defect_id: UUID,
    payload: DefectSupersedeCommand,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    fields = payload.model_dump(
        exclude={"expected_version", "reason"}, exclude_unset=True
    )
    return svc.supersede(
        defect_id,
        expected_version=payload.expected_version,
        actor_worker_id=actor_worker_id,
        fields=fields,
        reason=payload.reason,
    )


# ── Defect: отмена ────────────────────────────────────────────────────────────────


@router.post("/quality/defects/{defect_id}/cancel", response_model=DefectRead)
def cancel_defect(
    defect_id: UUID,
    payload: DefectCancelCommand,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.cancel(
        defect_id,
        expected_version=payload.expected_version,
        actor_worker_id=actor_worker_id,
        reason=payload.reason,
    )


# ── Defect: история цепочки (append-only) ─────────────────────────────────────────


@router.get(
    "/quality/defects/{defect_id}/history", response_model=list[DefectEventRead]
)
def defect_history(
    defect_id: UUID,
    svc: DefectService = Depends(_svc),
    actor_worker_id: int = Depends(get_current_user_id),
):
    return svc.history(defect_id, actor_worker_id=actor_worker_id)


# ── Справочники (authenticated global read-only; актор не передаётся в сервис) ─────


@router.get(
    "/quality/defect-types",
    response_model=list[DefectTypeRead],
    dependencies=[Depends(get_current_user_id)],
)
def list_defect_types(
    active_only: bool = Query(default=True),
    svc: DefectService = Depends(_svc),
):
    return svc.list_defect_types(active_only=active_only)


@router.get(
    "/quality/defect-types/{defect_type_id}",
    response_model=DefectTypeRead,
    dependencies=[Depends(get_current_user_id)],
)
def get_defect_type(
    defect_type_id: UUID,
    svc: DefectService = Depends(_svc),
):
    return svc.get_defect_type_for_read(defect_type_id)


@router.get(
    "/quality/defect-location-types",
    response_model=list[DefectLocationTypeRead],
    dependencies=[Depends(get_current_user_id)],
)
def list_defect_location_types(
    active_only: bool = Query(default=True),
    svc: DefectService = Depends(_svc),
):
    return svc.list_defect_location_types(active_only=active_only)


@router.get(
    "/quality/defect-location-types/{defect_location_type_id}",
    response_model=DefectLocationTypeRead,
    dependencies=[Depends(get_current_user_id)],
)
def get_defect_location_type(
    defect_location_type_id: UUID,
    svc: DefectService = Depends(_svc),
):
    return svc.get_defect_location_type_for_read(defect_location_type_id)
