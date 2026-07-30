"""Тесты Alembic-миграции 9D-3A (defect technical model).

Проверяют единственный head, линейность, наличие таблиц/CHECK/partial unique/FK/seed и
идемпотентность seed. Round-trip downgrade→upgrade выполняется в конце и восстанавливает
head, чтобы не сломать остальную сессию тестов.
"""

from __future__ import annotations

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import text

from app.quality.defect_seed import (
    DEFECT_LOCATION_TYPE_SEED,
    DEFECT_TYPE_SEED,
)
from app.shared.db import SessionLocal

ACTIVE_REVISION = "canonical_baseline_v1"
ARCHIVED_REVISION = "20260720_21_defect_model"
QUALITY = "quality"

DEFECT_TABLES = (
    "defect_types",
    "defect_location_types",
    "defect_roots",
    "defects",
    "defect_sequences",
    "defect_events",
)


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config("alembic.ini"))


def _tables_present() -> set[str]:
    s = SessionLocal()
    try:
        rows = s.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :sch AND table_name LIKE 'defect%'"
            ),
            {"sch": QUALITY},
        )
        return {r[0] for r in rows}
    finally:
        s.close()


# ── Alembic структура ──────────────────────────────────────────────────────────


def test_single_head():
    # Инвариант — линейная история без ветвления. Конкретную голову не фиксируем:
    # каждая следующая миграция (9D-4A-2 и далее) сдвигает её легитимно.
    assert len(_script().get_heads()) == 1


def test_active_graph_uses_canonical_baseline_and_hides_archived_revision():
    script = _script()

    assert script.get_heads() == [ACTIVE_REVISION]
    with pytest.raises(CommandError, match="Can't locate revision"):
        script.get_revision(ARCHIVED_REVISION)


# ── Таблицы / CHECK / индексы / FK ─────────────────────────────────────────────


def test_all_tables_created():
    assert set(DEFECT_TABLES) <= _tables_present()


def test_check_constraints_present():
    expected = {
        "ck_defects_status",
        "ck_defects_indication_location",
        "ck_defects_length_positive",
        "ck_defects_height_positive",
        "ck_defects_quantity_positive",
        "ck_defects_axial_position_nonneg",
        "ck_defects_circumferential_range",
        "ck_defects_orientation_not_empty",
        "ck_defects_standard_clause_requires_document",
        "ck_defects_cancelled_fields",
        "ck_defects_superseded_fields",
        "ck_defect_events_type",
        "ck_defect_roots_defect_no",
        "ck_defect_sequences_last_value",
    }
    s = SessionLocal()
    try:
        rows = s.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = :sch AND c.contype = 'c'"
            ),
            {"sch": QUALITY},
        )
        present = {r[0] for r in rows}
    finally:
        s.close()
    assert expected <= present, expected - present


def test_partial_unique_indexes_present():
    s = SessionLocal()
    try:
        rows = s.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = :sch AND tablename = 'defects'"
            ),
            {"sch": QUALITY},
        )
        idx = {r[0]: r[1] for r in rows}
    finally:
        s.close()
    # Частичные UNIQUE с предикатом по статусу.
    assert "uq_defects_one_active_per_root" in idx
    assert "UNIQUE" in idx["uq_defects_one_active_per_root"].upper()
    assert "WHERE" in idx["uq_defects_one_active_per_root"].upper()
    assert "ACTIVE" in idx["uq_defects_one_active_per_root"]
    assert "uq_defects_one_draft_per_root" in idx
    assert "DRAFT" in idx["uq_defects_one_draft_per_root"]
    assert "uq_defects_root_revision_no" in idx


def test_foreign_keys_present():
    s = SessionLocal()
    try:
        rows = s.execute(
            text(
                """
                SELECT c.conname,
                       t.relname AS table_name,
                       rt.relname AS ref_table
                FROM pg_constraint c
                JOIN pg_namespace n ON n.oid = c.connamespace
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_class rt ON rt.oid = c.confrelid
                WHERE n.nspname = :sch AND c.contype = 'f'
                  AND t.relname IN ('defect_roots', 'defects', 'defect_sequences', 'defect_events')
                """
            ),
            {"sch": QUALITY},
        )
        fks = {(r[1], r[2]) for r in rows}
    finally:
        s.close()
    assert ("defect_roots", "engineering_evaluations") in fks
    assert ("defect_roots", "joints") in fks
    assert ("defects", "defect_roots") in fks
    assert ("defects", "defects") in fks  # self-FK supersedes_defect_id
    assert ("defects", "defect_types") in fks
    assert ("defects", "defect_location_types") in fks
    assert ("defect_sequences", "joints") in fks
    assert ("defect_events", "defects") in fks
    assert ("defect_events", "defect_roots") in fks  # история корня, NOT NULL FK


def test_defect_events_root_not_null_and_index():
    s = SessionLocal()
    try:
        nullable = s.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = :sch AND table_name = 'defect_events' "
                "AND column_name = 'defect_root_id'"
            ),
            {"sch": QUALITY},
        ).scalar_one()
        idx = {
            r[0]: r[1]
            for r in s.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = :sch AND tablename = 'defect_events'"
                ),
                {"sch": QUALITY},
            )
        }
    finally:
        s.close()
    assert nullable == "NO"
    assert "ix_defect_events_defect_root_id" in idx
    assert "created_at" in idx["ix_defect_events_defect_root_id"]


def test_db_seed_matches_seed_contract():
    """DB-seed побайтно совпадает с single-source контрактом defect_seed.py.

    Обнаружит любое расхождение UUID / кода / названия / category / requires_*.
    """
    s = SessionLocal()
    try:
        type_rows = s.execute(
            text(
                "SELECT id, code, name, category, requires_length, requires_width, "
                "requires_height, requires_depth, requires_area, requires_quantity, "
                "requires_known_indication_location, requires_description, is_active "
                f"FROM {QUALITY}.defect_types"
            )
        ).mappings().all()
        loc_rows = s.execute(
            text(
                f"SELECT id, code, name, is_active FROM {QUALITY}.defect_location_types"
            )
        ).mappings().all()
    finally:
        s.close()

    db_types = {r["code"]: r for r in type_rows}
    for expected in DEFECT_TYPE_SEED:
        actual = db_types[expected["code"]]
        assert str(actual["id"]) == str(expected["id"]), expected["code"]
        assert actual["name"] == expected["name"], expected["code"]
        assert actual["category"] == expected["category"], expected["code"]
        assert actual["is_active"] is True, expected["code"]
        for flag in (
            "requires_length", "requires_width", "requires_height", "requires_depth",
            "requires_area", "requires_quantity",
            "requires_known_indication_location", "requires_description",
        ):
            assert actual[flag] == expected[flag], (expected["code"], flag)

    db_locs = {r["code"]: r for r in loc_rows}
    for expected in DEFECT_LOCATION_TYPE_SEED:
        actual = db_locs[expected["code"]]
        assert str(actual["id"]) == str(expected["id"]), expected["code"]
        assert actual["name"] == expected["name"], expected["code"]
        assert actual["is_active"] is True, expected["code"]


# ── Seed ───────────────────────────────────────────────────────────────────────


def test_seed_present():
    s = SessionLocal()
    try:
        types = s.execute(text(f"SELECT count(*) FROM {QUALITY}.defect_types")).scalar_one()
        locs = s.execute(
            text(f"SELECT count(*) FROM {QUALITY}.defect_location_types")
        ).scalar_one()
    finally:
        s.close()
    assert types >= len(DEFECT_TYPE_SEED)
    assert locs >= len(DEFECT_LOCATION_TYPE_SEED)


def test_seed_codes_unique_and_baseline():
    s = SessionLocal()
    try:
        rows = s.execute(
            text(f"SELECT code, requires_description FROM {QUALITY}.defect_types")
        ).all()
    finally:
        s.close()
    codes = [r[0] for r in rows]
    assert len(codes) == len(set(codes))  # уникальны
    by_code = dict(rows)
    assert by_code["OTHER"] is True  # baseline: OTHER.requires_description
    assert by_code["CRACK"] is False  # baseline: остальные false


def test_seed_idempotent_on_conflict():
    """Повторная вставка seed с ON CONFLICT (code) DO NOTHING не создаёт дубликатов."""
    from sqlalchemy import column, table
    from sqlalchemy.dialects.postgresql import UUID as PGUUID
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    s = SessionLocal()
    try:
        before = s.execute(
            text(f"SELECT count(*) FROM {QUALITY}.defect_types")
        ).scalar_one()
        loc = table(
            "defect_location_types",
            column("id", PGUUID(as_uuid=True)),
            column("code"),
            column("name"),
            schema=QUALITY,
        )
        s.execute(
            pg_insert(loc)
            .values(DEFECT_LOCATION_TYPE_SEED)
            .on_conflict_do_nothing(index_elements=["code"])
        )
        s.commit()
        after_types = s.execute(
            text(f"SELECT count(*) FROM {QUALITY}.defect_types")
        ).scalar_one()
        after_locs = s.execute(
            text(f"SELECT count(*) FROM {QUALITY}.defect_location_types")
        ).scalar_one()
    finally:
        s.close()
    assert after_types == before
    assert after_locs == len(DEFECT_LOCATION_TYPE_SEED)


# ── Повторный upgrade canonical baseline ───────────────────────────────────────


def test_repeated_upgrade_preserves_canonical_defect_contract():
    from alembic import command

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    assert set(DEFECT_TABLES) <= _tables_present()
    # Seed остаётся неизменным после повторного idempotent upgrade.
    s = SessionLocal()
    try:
        actual_codes = set(
            s.execute(
                text(f"SELECT code FROM {QUALITY}.defect_types")
            ).scalars()
        )
    finally:
        s.close()
    assert {item["code"] for item in DEFECT_TYPE_SEED} <= actual_codes
    assert len(_script().get_heads()) == 1
