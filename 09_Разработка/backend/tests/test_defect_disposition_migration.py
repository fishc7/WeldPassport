"""Тесты Alembic-миграции 9D-4A-2 (defect dispositions).

Проверяют линейность ревизии, наличие таблицы `quality.defect_dispositions`, состав
колонок и их типов (Integer actor без FK, timestamptz), CHECK-перечисления, FK на
`defect_roots`, self-FK supersede-цепочки, три индекса и частичный UNIQUE
«одно ACTIVE решение на дефект».
"""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.quality.defect_disposition_models import (
    DEFECT_DISPOSITION_DECISION_TYPES,
    DEFECT_DISPOSITION_STATUSES,
)
from app.shared.db import SessionLocal

REVISION = "20260721_22_defect_dispositions"
DOWN_REVISION = "20260720_21_defect_model"
QUALITY = "quality"
TABLE = "defect_dispositions"


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config("alembic.ini"))


def _fetch(sql: str) -> list[tuple]:
    s = SessionLocal()
    try:
        return [tuple(r) for r in s.execute(text(sql), {"sch": QUALITY, "tbl": TABLE})]
    finally:
        s.close()


# ── Alembic структура ──────────────────────────────────────────────────────────


def test_linear_down_revision():
    rev = _script().get_revision(REVISION)
    assert rev.down_revision == DOWN_REVISION


# ── Таблица и колонки ──────────────────────────────────────────────────────────


def test_table_created():
    rows = _fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :sch AND table_name = :tbl"
    )
    assert rows == [(TABLE,)]


def test_columns_and_types():
    actual = {
        name: (dtype, nullable)
        for name, dtype, nullable in _fetch(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = :sch AND table_name = :tbl"
        )
    }
    expected = {
        "id": ("uuid", "NO"),
        "defect_root_id": ("uuid", "NO"),
        "supersedes_disposition_id": ("uuid", "YES"),
        "decision_type": ("character varying", "NO"),
        "status": ("character varying", "NO"),
        "justification": ("text", "NO"),
        "comment": ("text", "YES"),
        "supersede_reason": ("text", "YES"),
        # Actor — Integer (hr.workers.id) БЕЗ FK: переходный период.
        "created_by_worker_id": ("integer", "NO"),
        "approved_by_worker_id": ("integer", "YES"),
        # Время — строго timestamptz (правило домена).
        "created_at": ("timestamp with time zone", "NO"),
        "approved_at": ("timestamp with time zone", "YES"),
    }
    assert actual == expected


# ── CHECK / FK / индексы ───────────────────────────────────────────────────────


def _constraints() -> dict[str, str]:
    return {
        name: definition
        for name, definition in _fetch(
            "SELECT con.conname, pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con "
            "JOIN pg_class cl ON cl.oid = con.conrelid "
            "JOIN pg_namespace ns ON ns.oid = cl.relnamespace "
            "WHERE ns.nspname = :sch AND cl.relname = :tbl"
        )
    }


def test_check_constraints_present():
    expected = {
        "ck_defect_dispositions_decision_type",
        "ck_defect_dispositions_status",
        "ck_defect_dispositions_justification_not_empty",
        "ck_defect_dispositions_no_self_supersede",
        "ck_defect_dispositions_approved_pair",
    }
    assert expected <= set(_constraints())


def test_enum_values_in_check_constraints():
    cons = _constraints()
    decision = cons["ck_defect_dispositions_decision_type"]
    for value in DEFECT_DISPOSITION_DECISION_TYPES:
        assert f"'{value}'" in decision
    status = cons["ck_defect_dispositions_status"]
    for value in DEFECT_DISPOSITION_STATUSES:
        assert f"'{value}'" in status


def test_foreign_keys():
    fks = [
        definition
        for name, definition in _constraints().items()
        if definition.startswith("FOREIGN KEY")
    ]
    assert any(
        "defect_root_id" in fk and "quality.defect_roots(id)" in fk for fk in fks
    ), fks
    # Self-FK supersede-цепочки.
    assert any(
        "supersedes_disposition_id" in fk
        and f"{QUALITY}.{TABLE}(id)" in fk
        for fk in fks
    ), fks


def _indexes() -> dict[str, str]:
    return {
        name: definition
        for name, definition in _fetch(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = :sch AND tablename = :tbl"
        )
    }


def test_indexes_present():
    expected = {
        "ix_defect_dispositions_defect_root_id",
        "ix_defect_dispositions_root_status",
        "ix_defect_dispositions_created_by",
        "uq_defect_dispositions_one_active_per_root",
    }
    assert expected <= set(_indexes())


def test_one_active_per_defect_is_partial_unique():
    definition = _indexes()["uq_defect_dispositions_one_active_per_root"]
    assert "UNIQUE INDEX" in definition
    assert "(defect_root_id)" in definition
    assert "WHERE" in definition and "'ACTIVE'" in definition
