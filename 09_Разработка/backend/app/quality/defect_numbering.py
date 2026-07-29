"""Конкурентно безопасная выдача per-joint номера дефекта (Task 9D-3A; Spec §7.4/§14).

Единственная ответственность модуля — атомарная выдача `defect_no` через
`INSERT ... ON CONFLICT (joint_id) DO UPDATE ... RETURNING` (паттерн
`QualityFindingRepo.next_finding_sequence`). Это НЕ полноценный `DefectRepository`
(бизнес-операции, lifecycle, события — блок 9D-3B); здесь только счётчик, без которого
невозможно протестировать нумерацию.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.quality.defect_models import DEFECT_SEQUENCES_TABLE, QUALITY_SCHEMA


def next_defect_sequence(db: Session, joint_id: UUID) -> int:
    """Атомарно выдаёт следующий номер дефекта в пределах `Joint`.

    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` берёт блокировку строки счётчика:
    параллельные транзакции сериализуются, гонки `MAX()+1` нет. Выполняется в текущей
    транзакции; при rollback номер не считается выданным. Стартовое значение 0, первая
    выдача → 1; номера не переиспользуются.
    """
    result = db.execute(
        text(
            f"""
            INSERT INTO {QUALITY_SCHEMA}.{DEFECT_SEQUENCES_TABLE}
                (joint_id, last_value, updated_at)
            VALUES (CAST(:jid AS uuid), 1, now())
            ON CONFLICT (joint_id)
            DO UPDATE SET
                last_value =
                    {QUALITY_SCHEMA}.{DEFECT_SEQUENCES_TABLE}.last_value + 1,
                updated_at = now()
            RETURNING last_value
            """
        ),
        {"jid": str(joint_id)},
    )
    return int(result.scalar_one())
