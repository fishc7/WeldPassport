"""Тесты публичного read-only слоя справочников Defect (Task 9D-3C-2, Spec 9D-3C §10).

Покрывают repository- и service-примитивы чтения `DefectType`/`DefectLocationType`:
list с `active_only`, стабильную сортировку по `code`, detail (в т.ч. неактивных),
каноническую 404 при отсутствии и отсутствие Joint-scope/RBAC/actor на этом слое.
HTTP/authentication здесь не тестируются (Task 9D-3C-3/4).

Тестовые строки справочников вставляются через `flush()` (без commit) — они видны
методам в той же сессии и откатываются teardown-ом фикстуры `db`, не загрязняя общий
seeded-каталог.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.quality import defect_workflow as dw
from app.quality.defect_models import DefectLocationType, DefectType
from app.quality.defect_repository import DefectRepository
from app.quality.defect_schemas import DefectLocationTypeRead, DefectTypeRead
from app.quality.defect_services import DefectService
from app.shared.errors import DomainError


def _repo(db: Session) -> DefectRepository:
    return DefectRepository(db)


def _svc(db: Session) -> DefectService:
    return DefectService(db)


def _uid() -> str:
    return uuid4().hex[:8].upper()


def _add_type(db: Session, *, code: str, is_active: bool) -> DefectType:
    obj = DefectType(code=code, name=f"Тип {code}", is_active=is_active)
    db.add(obj)
    db.flush()
    return obj


def _add_location(db: Session, *, code: str, is_active: bool) -> DefectLocationType:
    obj = DefectLocationType(code=code, name=f"Расположение {code}", is_active=is_active)
    db.add(obj)
    db.flush()
    return obj


# Единый описатель кейса для параметризации по обоим справочникам.
TYPE_CASE = {
    "model": DefectType,
    "add": _add_type,
    "repo_list": "list_defect_types",
    "repo_detail": "get_defect_type_for_read",
    "svc_list": "list_defect_types",
    "svc_detail": "get_defect_type_for_read",
    "not_found": dw.DEFECT_TYPE_NOT_FOUND,
    "inactive_code": dw.DEFECT_TYPE_INACTIVE,
    "seed_code": "CRACK",
}
LOCATION_CASE = {
    "model": DefectLocationType,
    "add": _add_location,
    "repo_list": "list_defect_location_types",
    "repo_detail": "get_defect_location_type_for_read",
    "svc_list": "list_defect_location_types",
    "svc_detail": "get_defect_location_type_for_read",
    "not_found": dw.DEFECT_LOCATION_TYPE_NOT_FOUND,
    "inactive_code": dw.DEFECT_LOCATION_TYPE_INACTIVE,
    "seed_code": "WELD_METAL",
}
CASES = [pytest.param(TYPE_CASE, id="type"), pytest.param(LOCATION_CASE, id="location")]


# ── Repository ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_repo_list_active_only_default(db: Session, case):
    repo = _repo(db)
    active = case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    inactive = case["add"](db, code=f"ZINA_{_uid()}", is_active=False)
    rows = getattr(repo, case["repo_list"])(active_only=True)
    ids = {r.id for r in rows}
    assert active.id in ids
    assert inactive.id not in ids
    assert all(r.is_active for r in rows)


@pytest.mark.parametrize("case", CASES)
def test_repo_list_active_only_false_returns_both(db: Session, case):
    repo = _repo(db)
    active = case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    inactive = case["add"](db, code=f"ZINA_{_uid()}", is_active=False)
    rows = getattr(repo, case["repo_list"])(active_only=False)
    ids = {r.id for r in rows}
    assert active.id in ids
    assert inactive.id in ids


@pytest.mark.parametrize("case", CASES)
def test_repo_list_sorted_by_code_asc(db: Session, case):
    repo = _repo(db)
    case["add"](db, code=f"ZB_{_uid()}", is_active=True)
    case["add"](db, code=f"ZA_{_uid()}", is_active=True)
    case["add"](db, code=f"ZC_{_uid()}", is_active=False)
    codes = [r.code for r in getattr(repo, case["repo_list"])(active_only=False)]
    assert codes == sorted(codes)


@pytest.mark.parametrize("case", CASES)
def test_repo_list_empty_returns_list(db: Session, case):
    """Пустой активный набор → [] (не None, не ошибка). Все строки временно гасим в savepoint."""
    repo = _repo(db)
    nested = db.begin_nested()
    try:
        db.execute(update(case["model"]).values(is_active=False))
        db.flush()
        rows = getattr(repo, case["repo_list"])(active_only=True)
        assert rows == []
        assert isinstance(rows, list)
    finally:
        nested.rollback()


@pytest.mark.parametrize("case", CASES)
def test_repo_detail_active(db: Session, case):
    repo = _repo(db)
    active = case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    got = getattr(repo, case["repo_detail"])(active.id)
    assert got is not None and got.id == active.id


@pytest.mark.parametrize("case", CASES)
def test_repo_detail_inactive(db: Session, case):
    repo = _repo(db)
    inactive = case["add"](db, code=f"ZINA_{_uid()}", is_active=False)
    got = getattr(repo, case["repo_detail"])(inactive.id)
    assert got is not None and got.id == inactive.id and got.is_active is False


@pytest.mark.parametrize("case", CASES)
def test_repo_detail_missing_returns_none(db: Session, case):
    repo = _repo(db)
    assert getattr(repo, case["repo_detail"])(uuid4()) is None


@pytest.mark.parametrize("case", CASES)
def test_repo_read_has_no_side_effects(db: Session, case):
    repo = _repo(db)
    case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    before = len(getattr(repo, case["repo_list"])(active_only=False))
    getattr(repo, case["repo_detail"])(uuid4())
    getattr(repo, case["repo_list"])(active_only=True)
    after = len(getattr(repo, case["repo_list"])(active_only=False))
    assert before == after


# ── Service ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES)
def test_service_list_default_active_only(db: Session, case):
    svc = _svc(db)
    active = case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    inactive = case["add"](db, code=f"ZINA_{_uid()}", is_active=False)
    rows = getattr(svc, case["svc_list"])()  # default active_only=True
    ids = {r.id for r in rows}
    assert active.id in ids
    assert inactive.id not in ids


@pytest.mark.parametrize("case", CASES)
def test_service_list_all(db: Session, case):
    svc = _svc(db)
    inactive = case["add"](db, code=f"ZINA_{_uid()}", is_active=False)
    rows = getattr(svc, case["svc_list"])(active_only=False)
    assert inactive.id in {r.id for r in rows}


@pytest.mark.parametrize("case", CASES)
def test_service_detail_active(db: Session, case):
    svc = _svc(db)
    active = case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    got = getattr(svc, case["svc_detail"])(active.id)
    assert got.id == active.id


@pytest.mark.parametrize("case", CASES)
def test_service_detail_inactive_no_inactive_error(db: Session, case):
    """Неактивная запись читается без ошибки; `*_INACTIVE` не поднимается."""
    svc = _svc(db)
    inactive = case["add"](db, code=f"ZINA_{_uid()}", is_active=False)
    got = getattr(svc, case["svc_detail"])(inactive.id)
    assert got.id == inactive.id and got.is_active is False


@pytest.mark.parametrize("case", CASES)
def test_service_detail_missing_raises_canonical_404(db: Session, case):
    svc = _svc(db)
    with pytest.raises(DomainError) as exc:
        getattr(svc, case["svc_detail"])(uuid4())
    err = exc.value
    assert err.status_code == 404
    assert err.code == case["not_found"]
    # inactive-код никогда не используется для публичного чтения
    assert err.code != case["inactive_code"]


@pytest.mark.parametrize("case", CASES)
def test_service_read_methods_have_no_actor_or_joint(case):
    """Структурная граница доступа: методы без actor_worker_id и без joint_id."""
    for name in (case["svc_list"], case["svc_detail"]):
        params = set(inspect.signature(getattr(DefectService, name)).parameters)
        assert "actor_worker_id" not in params
        assert "joint_id" not in params


@pytest.mark.parametrize("case", CASES)
def test_service_read_does_not_mutate(db: Session, case):
    svc = _svc(db)
    case["add"](db, code=f"ZACT_{_uid()}", is_active=True)
    before = len(getattr(svc, case["svc_list"])(active_only=False))
    getattr(svc, case["svc_list"])()
    after = len(getattr(svc, case["svc_list"])(active_only=False))
    assert before == after


def test_reference_read_returns_only_reference_types(db: Session):
    """Справочный слой не раскрывает Defect: методы возвращают только reference-типы,
    их сигнатуры не принимают joint_id и не вызывают listing дефектов."""
    svc = _svc(db)
    types = svc.list_defect_types(active_only=False)
    locations = svc.list_defect_location_types(active_only=False)
    assert all(isinstance(t, DefectType) for t in types)
    assert all(isinstance(loc, DefectLocationType) for loc in locations)
    # Read-схемы справочников не несут Defect-данных.
    assert "defect_root_id" not in DefectTypeRead.model_fields
    assert "joint_id" not in DefectLocationTypeRead.model_fields


# ── Schema compatibility ─────────────────────────────────────────────────────────

_REQUIRES_FLAGS = (
    "requires_description",
    "requires_length",
    "requires_width",
    "requires_height",
    "requires_depth",
    "requires_area",
    "requires_quantity",
    "requires_known_indication_location",
)


def test_defect_type_read_serializes_all_requires_flags(db: Session):
    repo = _repo(db)
    orm = repo.get_defect_type_for_read(
        next(t.id for t in repo.list_defect_types(active_only=False) if t.code == "CRACK")
    )
    read = DefectTypeRead.model_validate(orm)
    for flag in _REQUIRES_FLAGS:
        assert hasattr(read, flag)
        assert isinstance(getattr(read, flag), bool)
    # Все восемь флагов присутствуют в модели схемы.
    assert set(_REQUIRES_FLAGS).issubset(DefectTypeRead.model_fields)


def test_defect_location_type_read_serializes(db: Session):
    repo = _repo(db)
    orm = repo.get_defect_location_type_for_read(
        next(
            loc.id
            for loc in repo.list_defect_location_types(active_only=False)
            if loc.code == "WELD_METAL"
        )
    )
    read = DefectLocationTypeRead.model_validate(orm)
    assert read.code == "WELD_METAL"
    assert set(DefectLocationTypeRead.model_fields) == {
        "id",
        "code",
        "name",
        "description",
        "is_active",
    }
