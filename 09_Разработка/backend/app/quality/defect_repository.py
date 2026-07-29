"""Репозиторий технической модели Defect (Task 9D-3B; ADR-022, Spec).

Только persistence/query primitives: чтение/запись `DefectRoot`/`Defect`/`DefectEvent`,
атомарная выдача `defect_no`, row-lock для конкурентных команд и read-only чтение
родительских сущностей (`EngineeringEvaluation`/revision/`QualityFinding`/справочники),
нужных доменной валидации. Без доменной политики, RBAC и HTTP-логики — они в сервисе.
Стиль Tasks 9A–9D-2 (SQLAlchemy 2): add/flush без commit; save — commit.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.quality.defect_models import (
    Defect,
    DefectEvent,
    DefectLocationType,
    DefectRoot,
    DefectType,
)
from app.quality.defect_numbering import next_defect_sequence
from app.quality.defect_workflow import DEFECT_ACTIVE, DEFECT_DRAFT
from app.quality.engineering_evaluation_models import (
    EngineeringEvaluation,
    EngineeringEvaluationRevision,
)
from app.quality.quality_finding_models import QualityFinding


class DefectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Нумерация ──────────────────────────────────────────────────────────────

    def next_defect_no(self, joint_id: UUID) -> int:
        return next_defect_sequence(self.db, joint_id)

    # ── DefectRoot ─────────────────────────────────────────────────────────────

    def get_root_by_id(self, root_id: UUID) -> DefectRoot | None:
        return self.db.get(DefectRoot, root_id)

    def get_root_by_evaluation_id(self, evaluation_id: UUID) -> DefectRoot | None:
        return (
            self.db.query(DefectRoot)
            .filter(DefectRoot.engineering_evaluation_id == evaluation_id)
            .first()
        )

    def get_root_by_joint_and_defect_no(
        self, joint_id: UUID, defect_no: int
    ) -> DefectRoot | None:
        return (
            self.db.query(DefectRoot)
            .filter(
                DefectRoot.joint_id == joint_id, DefectRoot.defect_no == defect_no
            )
            .first()
        )

    def list_roots_by_joint(self, joint_id: UUID) -> list[DefectRoot]:
        return (
            self.db.query(DefectRoot)
            .filter(DefectRoot.joint_id == joint_id)
            .order_by(DefectRoot.defect_no)
            .all()
        )

    def lock_root_for_update(self, root_id: UUID) -> DefectRoot | None:
        """Блокирует строку корня (SELECT … FOR UPDATE) для сериализации команд."""
        return (
            self.db.query(DefectRoot)
            .filter(DefectRoot.id == root_id)
            .with_for_update()
            .first()
        )

    def create_root(self, root: DefectRoot) -> DefectRoot:
        self.db.add(root)
        self.db.flush()
        return root

    # ── Defect (ревизии) ───────────────────────────────────────────────────────

    def get_defect_by_id(self, defect_id: UUID) -> Defect | None:
        return self.db.get(Defect, defect_id)

    def get_current_active_revision(self, root_id: UUID) -> Defect | None:
        return (
            self.db.query(Defect)
            .filter(
                Defect.defect_root_id == root_id, Defect.status == DEFECT_ACTIVE
            )
            .first()
        )

    def lock_current_active_revision(self, root_id: UUID) -> Defect | None:
        return (
            self.db.query(Defect)
            .filter(
                Defect.defect_root_id == root_id, Defect.status == DEFECT_ACTIVE
            )
            .with_for_update()
            .first()
        )

    def get_open_draft_revision(self, root_id: UUID) -> Defect | None:
        return (
            self.db.query(Defect)
            .filter(
                Defect.defect_root_id == root_id, Defect.status == DEFECT_DRAFT
            )
            .first()
        )

    def list_revisions(self, root_id: UUID) -> list[Defect]:
        return (
            self.db.query(Defect)
            .filter(Defect.defect_root_id == root_id)
            .order_by(Defect.revision_no)
            .all()
        )

    def max_revision_no(self, root_id: UUID) -> int:
        from sqlalchemy import func

        value = (
            self.db.query(func.max(Defect.revision_no))
            .filter(Defect.defect_root_id == root_id)
            .scalar()
        )
        return int(value or 0)

    def create_revision(self, defect: Defect) -> Defect:
        self.db.add(defect)
        self.db.flush()
        return defect

    def get_defect_with_refs(
        self, defect_id: UUID
    ) -> tuple[Defect, DefectType | None, DefectLocationType | None] | None:
        """Загружает ревизию + тип + расположение одним запросом (без N+1)."""
        row = (
            self.db.query(Defect, DefectType, DefectLocationType)
            .outerjoin(DefectType, Defect.defect_type_id == DefectType.id)
            .outerjoin(
                DefectLocationType, Defect.location_type_id == DefectLocationType.id
            )
            .filter(Defect.id == defect_id)
            .first()
        )
        return (row[0], row[1], row[2]) if row is not None else None

    def list_active_defects_by_joint(self, joint_id: UUID) -> list[Defect]:
        """Действующие (ACTIVE) ревизии по стыку — один запрос (root+revision), без N+1."""
        rows = (
            self.db.query(Defect)
            .join(DefectRoot, Defect.defect_root_id == DefectRoot.id)
            .filter(
                DefectRoot.joint_id == joint_id, Defect.status == DEFECT_ACTIVE
            )
            .order_by(DefectRoot.defect_no)
            .all()
        )
        return rows

    # ── Справочники (read-only; сервис их не изменяет) ─────────────────────────

    def get_defect_type(self, type_id: UUID) -> DefectType | None:
        return self.db.get(DefectType, type_id)

    def get_defect_location_type(
        self, location_type_id: UUID
    ) -> DefectLocationType | None:
        return self.db.get(DefectLocationType, location_type_id)

    # ── Публичное чтение справочников (Task 9D-3C-2; без domain policy/RBAC) ────
    # Отдельные от internal-валидации методы: list с фильтром активности и стабильной
    # сортировкой по code; detail — семантическая обёртка над get_*, возвращает запись
    # независимо от is_active. Правило «reference must be active» (DEFECT_*_INACTIVE)
    # к публичному чтению НЕ применяется — оно остаётся только в create/activate-валидации.

    def list_defect_types(self, *, active_only: bool = True) -> list[DefectType]:
        stmt = select(DefectType)
        if active_only:
            stmt = stmt.where(DefectType.is_active.is_(True))
        stmt = stmt.order_by(DefectType.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_defect_type_for_read(
        self, defect_type_id: UUID
    ) -> DefectType | None:
        return self.get_defect_type(defect_type_id)

    def list_defect_location_types(
        self, *, active_only: bool = True
    ) -> list[DefectLocationType]:
        stmt = select(DefectLocationType)
        if active_only:
            stmt = stmt.where(DefectLocationType.is_active.is_(True))
        stmt = stmt.order_by(DefectLocationType.code.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_defect_location_type_for_read(
        self, location_type_id: UUID
    ) -> DefectLocationType | None:
        return self.get_defect_location_type(location_type_id)

    # ── Родительские сущности (read-only, для доменной валидации) ──────────────

    def get_evaluation(self, evaluation_id: UUID) -> EngineeringEvaluation | None:
        return self.db.get(EngineeringEvaluation, evaluation_id)

    def get_evaluation_revision(
        self, revision_id: UUID
    ) -> EngineeringEvaluationRevision | None:
        return self.db.get(EngineeringEvaluationRevision, revision_id)

    def get_finding(self, finding_id: UUID) -> QualityFinding | None:
        return self.db.get(QualityFinding, finding_id)

    # ── Аудит (append-only) ─────────────────────────────────────────────────────

    def append_event(self, event: DefectEvent) -> DefectEvent:
        self.db.add(event)
        self.db.flush()
        return event

    def list_events(self, root_id: UUID) -> list[DefectEvent]:
        return (
            self.db.query(DefectEvent)
            .filter(DefectEvent.defect_root_id == root_id)
            .order_by(DefectEvent.created_at, DefectEvent.defect_version)
            .all()
        )

    def list_events_for_defect(self, defect_id: UUID) -> list[DefectEvent]:
        return (
            self.db.query(DefectEvent)
            .filter(DefectEvent.defect_id == defect_id)
            .order_by(DefectEvent.created_at)
            .all()
        )

    # ── Фиксация ────────────────────────────────────────────────────────────────

    def save(self) -> None:
        self.db.commit()
