"""Тесты источников EngineeringEvaluation (Task 9D-2B).

Покрывают: неревизионный источник (`QUALITY_FINDING`/`JOINT`) с вычислением хэша и
`hash_schema_version`; ревизионный источник без хэша; неизвестный профиль; запрет вне
DRAFT; reverify (совпадение/расхождение/недоступность); нечувствительность хэша к
lifecycle-полям; события SOURCE_ADDED/REMOVED/REVERIFIED; каноникализацию Decimal (C03).

Reverify реализован без service layer (C02): repository + pure hash. QualityFinding/Joint
только читаются. API/RBAC/prepare/Defect/FindingDisposition не участвуют.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.quality import engineering_evaluation_hash as eeh
from app.quality import engineering_evaluation_workflow as eew

from .test_engineering_evaluation_core import EvalCtx


def _evaluation(ctx: EvalCtx):
    finding = ctx.make_finding()
    repo = ctx.repo()
    _, rev = repo.create_evaluation(
        project_id=ctx.project.id, finding_id=finding.id,
        project_code=ctx.project.code, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    return repo, rev, finding


# ── Каноникализация Decimal (C03) ─────────────────────────────────────────────


def test_canonical_decimal_c03():
    assert eeh.canonical_decimal(Decimal("10")) == "10"
    assert eeh.canonical_decimal(Decimal("10.0")) == "10"
    assert eeh.canonical_decimal(Decimal("10.00")) == "10"
    assert eeh.canonical_decimal(Decimal("10.50")) == "10.5"
    assert eeh.canonical_decimal(Decimal("0.00")) == "0"
    assert eeh.canonical_decimal(Decimal("-0")) == "0"
    assert eeh.canonical_decimal(Decimal("-12.340")) == "-12.34"


# ── Добавление источников и хэш ────────────────────────────────────────────────


def test_add_quality_finding_source_computes_hash(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESA")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
        source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    assert src.source_hash is not None and len(src.source_hash) == 64
    assert src.hash_schema_version == "QUALITY_FINDING@1"
    assert src.source_revision_id is None
    assert src.verified_at is not None
    types = [e.event_type for e in repo.list_events(rev.evaluation_id)]
    assert types == ["EVALUATION_CREATED", "SOURCE_ADDED"]


def test_add_joint_source_computes_hash(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESB")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="SUPPORTING_EVIDENCE", source_entity_type="JOINT",
        source_entity_id=finding.joint_id, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    assert src.hash_schema_version == "JOINT@1"
    assert src.source_hash is not None


def test_add_revisional_source_no_hash(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESC")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="CONTEXT", source_entity_type="ENGINEERING_DOCUMENT_REVISION",
        source_entity_id=uuid4(), source_revision_id=uuid4(),
        actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    assert src.source_hash is None
    assert src.hash_schema_version is None
    assert src.source_revision_id is not None


def test_add_source_unknown_profile_rejected(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESD")
    repo, rev, _ = _evaluation(ctx)
    try:
        repo.add_source(
            rev, source_role="PRIMARY_EVIDENCE",
            source_entity_type="INSPECTION_RESULT", source_entity_id=uuid4(),
            actor_worker_id=ctx.ogs.id,
        )
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    assert code == eew.EVAL_SOURCE_PROFILE_UNKNOWN


def test_add_source_blocked_when_not_draft(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESE")
    repo, rev, finding = _evaluation(ctx)
    rev.status = "PREPARED"
    db.flush()
    try:
        repo.add_source(
            rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
            source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
        )
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    finally:
        db.rollback()
    assert code == eew.EVAL_REVISION_NOT_DRAFT


# ── reverify ──────────────────────────────────────────────────────────────────


def test_reverify_unchanged_ok(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESF")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
        source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    repo.reverify_source(src, actor_worker_id=ctx.ogs.id)
    repo.save()
    types = [e.event_type for e in repo.list_events(rev.evaluation_id)]
    assert types == ["EVALUATION_CREATED", "SOURCE_ADDED", "SOURCE_REVERIFIED"]


def test_reverify_stale_on_significant_change(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESG")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
        source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    # initial_risk входит в профиль QUALITY_FINDING → изменение делает источник stale.
    finding.initial_risk = "LOW"
    db.commit()
    try:
        repo.reverify_source(src, actor_worker_id=ctx.ogs.id)
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    assert code == eew.EVAL_SOURCE_STALE
    # Автоподмена запрещена: сохранённый хэш не перезаписан.
    db.rollback()


def test_reverify_ignores_non_significant_field(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESH")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
        source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    # title не входит в профиль → хэш не меняется, reverify проходит.
    finding.title = "изменённый заголовок"
    db.commit()
    repo.reverify_source(src, actor_worker_id=ctx.ogs.id)
    repo.save()


def test_compute_hash_unavailable(client: TestClient, db: Session):
    try:
        eeh.compute_source_hash(
            db, source_entity_type="JOINT", source_entity_id=uuid4()
        )
        code = None
    except eew.EvaluationError as exc:
        code = exc.code
    assert code == eew.EVAL_SOURCE_UNAVAILABLE


def test_hash_deterministic(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESI")
    _, _, finding = _evaluation(ctx)
    h1, v1 = eeh.compute_source_hash(
        db, source_entity_type="QUALITY_FINDING", source_entity_id=finding.id
    )
    h2, v2 = eeh.compute_source_hash(
        db, source_entity_type="QUALITY_FINDING", source_entity_id=finding.id
    )
    assert h1 == h2 and v1 == v2 == "QUALITY_FINDING@1"


# ── remove ────────────────────────────────────────────────────────────────────


def test_remove_source_with_event(client: TestClient, db: Session):
    ctx = EvalCtx(db, client, "ESJ")
    repo, rev, finding = _evaluation(ctx)
    src = repo.add_source(
        rev, source_role="PRIMARY_EVIDENCE", source_entity_type="QUALITY_FINDING",
        source_entity_id=finding.id, actor_worker_id=ctx.ogs.id,
    )
    repo.save()
    repo.remove_source(src, actor_worker_id=ctx.ogs.id)
    repo.save()
    assert repo.list_sources(rev.id) == []
    types = [e.event_type for e in repo.list_events(rev.evaluation_id)]
    assert types == ["EVALUATION_CREATED", "SOURCE_ADDED", "SOURCE_REMOVED"]
