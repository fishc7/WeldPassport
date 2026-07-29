from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.engineering.heat_treatment_services import HeatTreatmentService
from app.engineering.models import Joint
from app.quality import inspection_workflow as iw
from app.quality.repository import QualityRepo
from app.quality.schemas import InspectionReadinessRead, ReasonItem


def evaluate_readiness(
    db: Session,
    joint: Joint,
    *,
    exclude_inspection_id: UUID | None = None,
    production_ready_confirmed: bool = False,
) -> InspectionReadinessRead:
    """Вычисляет готовность Joint к контролю (§12).

    Блокирующие причины запрещают создание/отправку; предупреждения — нет. Расчёт
    опирается на реальные статусы и связи существующих моделей (Joint,
    WeldOperation, канон Task 8F), а не на сохранённые флаги, и выполняется заново
    при каждом вызове (§12, §21.6.8). Endpoint readiness ничего не изменяет.
    """
    repo = QualityRepo(db)
    blocking: list[ReasonItem] = []
    warnings: list[ReasonItem] = []

    # 1. Joint должен быть ACTIVE (§12.1).
    if joint.status != "ACTIVE":
        blocking.append(ReasonItem(**iw.readiness_reason(iw.READINESS_JOINT_NOT_ACTIVE)))

    # 2. Актуальная завершённая сварочная операция (§12.1).
    current_weld = repo.current_completed_weld_operation(joint.id)
    weld_operation_id = current_weld.id if current_weld is not None else None
    if current_weld is None:
        if repo.has_completed_weld_operation_history(joint.id):
            # Завершённая операция существовала, но заменена (SUPERSEDED) — не
            # актуальна: неактуальная производственная версия (§12.1.3).
            blocking.append(
                ReasonItem(
                    **iw.readiness_reason(iw.READINESS_WELD_OPERATION_NOT_CURRENT)
                )
            )
        else:
            blocking.append(
                ReasonItem(
                    **iw.readiness_reason(iw.READINESS_NO_COMPLETED_WELD_OPERATION)
                )
            )

    # 3. Обязательная термообработка выполнена и принята (канон Task 8F, §12.1.4).
    # Используем существующее правило dependent_steps_ready: контроль — зависимый
    # этап, доступный только когда ТО не требуется либо принята. Новое правило
    # обязательности ТО не вводим.
    ht_state = HeatTreatmentService(db).joint_state(joint.id)
    heat_treatment_operation_id = ht_state.current_operation_id
    if not ht_state.dependent_steps_ready:
        blocking.append(
            ReasonItem(
                **iw.readiness_reason(iw.READINESS_HEAT_TREATMENT_NOT_ACCEPTED)
            )
        )

    # ── Предупреждения (§12.2) ────────────────────────────────────────────────
    if not production_ready_confirmed:
        warnings.append(
            ReasonItem(
                **iw.readiness_reason(iw.WARNING_PRODUCTION_READINESS_NOT_CONFIRMED)
            )
        )
    if current_weld is not None and current_weld.ogs_review_status == "PENDING":
        warnings.append(
            ReasonItem(**iw.readiness_reason(iw.WARNING_OPEN_OGS_WELD_REVIEW))
        )
    if repo.has_other_active_inspection(
        joint.id, exclude_id=exclude_inspection_id
    ):
        warnings.append(
            ReasonItem(
                **iw.readiness_reason(iw.WARNING_OTHER_ACTIVE_INSPECTION_EXISTS)
            )
        )

    return InspectionReadinessRead(
        joint_id=joint.id,
        ready_for_inspection=not blocking,
        blocking_reasons=blocking,
        warnings=warnings,
        weld_operation_id=weld_operation_id,
        heat_treatment_operation_id=heat_treatment_operation_id,
    )
