"""Интеграционные тесты Joint ↔ DocumentRevision History (Task 6, ADR-010/011).

Покрывают таблицу `engineering.joint_document_revisions`: автоматическую ORIGIN-
связь при создании Joint с неизменяемым снимком инженерных параметров, добавление
дополнительных связей, аннулирование без физического удаления, смену текущей ревизии
(`set-current-revision`) с восстановлением полей Joint из снимка, выборочный сброс
согласований ПТО/ОГС по классификации полей Task 5B и optimistic locking по трём
версиям (record/approval/workflow).

Тесты проверяют не только HTTP-ответы, но и фактическое состояние БД
(`JointDocumentRevision`, `Joint`) после команд.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering.models import (
    DocumentRevision,
    EngineeringDocument,
    Joint,
    JointDocumentRevision,
)
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"
TODAY = date.today()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Rev{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=TODAY,
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _assign_role(
    db: Session,
    worker_id: int,
    role_code: str,
    *,
    scope_type: str = "GLOBAL",
    scope_id: str | None = None,
) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=True,
        valid_from=TODAY,
    )
    db.add(role)
    db.commit()
    return role


def _role_worker(db: Session, suffix: str, role_code: str, **scope) -> Worker:
    w = _worker(db, suffix)
    _assign_role(db, w.id, role_code, **scope)
    return w


class Ctx:
    """Проект/линия/документ/ревизия + типовые ролевые работники."""

    def __init__(self, db: Session, code: str) -> None:
        self.db = db
        self.creator = _worker(db, f"{code}Creator")
        self.project = Project(
            code=code, name=f"Проект {code}", status="active",
            created_by=self.creator.id,
        )
        db.add(self.project)
        db.commit()
        db.refresh(self.project)
        self.line = Line(
            project_id=self.project.id, line_no=f"L-{code}", status="active",
            required_inspection_types=[], created_by=self.creator.id,
        )
        db.add(self.line)
        db.commit()
        db.refresh(self.line)
        self.document = self._new_document(f"DOC-{code}")
        self.revision = self.add_revision("R0")
        self.pto = _role_worker(db, f"{code}Pto", "PTO_ENGINEER")
        self.ogs = _role_worker(db, f"{code}Ogs", "OGS_ENGINEER")

    def _new_document(self, document_no: str) -> EngineeringDocument:
        doc = EngineeringDocument(
            project_id=self.project.id, line_id=self.line.id,
            document_no=document_no, document_type="ISOMETRIC",
            status="APPROVED", created_by=self.creator.id,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def add_revision(
        self, revision_code: str, document: EngineeringDocument | None = None
    ) -> DocumentRevision:
        rev = DocumentRevision(
            engineering_document_id=(document or self.document).id,
            revision_code=revision_code, status="APPROVED",
            created_by=self.creator.id,
        )
        self.db.add(rev)
        self.db.commit()
        self.db.refresh(rev)
        return rev

    def add_document_and_revision(
        self, code: str
    ) -> tuple[EngineeringDocument, DocumentRevision]:
        doc = self._new_document(f"DOC-{code}")
        rev = self.add_revision("RX", document=doc)
        return doc, rev

    def headers(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def create_joint(self, client: TestClient, joint_no: str = "J-1", **overrides):
        payload = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": joint_no,
            "created_by": self.creator.id,
        }
        payload.update(overrides)
        resp = client.post(
            f"{ENGINEERING_URL}/joints", json=payload,
            headers=self.headers(self.creator),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()


def _post(client, url, headers, json=None):
    return client.post(url, json=json or {}, headers=headers)


def _links(client, ctx: Ctx, jid: str, worker: Worker | None = None, **params):
    return client.get(
        f"{ENGINEERING_URL}/joints/{jid}/document-revisions",
        headers=ctx.headers(worker or ctx.pto), params=params,
    )


def _create_link(
    client, ctx: Ctx, jid: str, revision_id: str, *,
    revision_role: str = "CONFIRMED", document_role: str = "ADDITIONAL",
    worker: Worker | None = None, **extra,
):
    body = {
        "document_revision_id": revision_id,
        "revision_role": revision_role,
        "document_role": document_role,
    }
    body.update(extra)
    return _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/document-revisions",
        ctx.headers(worker or ctx.pto), body,
    )


def _invalidate(client, ctx: Ctx, jid: str, link_id: str, *,
                reason: str = "аннулирование", worker: Worker | None = None, **extra):
    body = {"reason": reason}
    body.update(extra)
    return _post(
        client,
        f"{ENGINEERING_URL}/joints/{jid}/document-revisions/{link_id}/invalidate",
        ctx.headers(worker or ctx.pto), body,
    )


def _set_current(client, ctx: Ctx, jid: str, link_id: str,
                 worker: Worker | None = None, **extra):
    body = {"link_id": link_id}
    body.update(extra)
    return _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/set-current-revision",
        ctx.headers(worker or ctx.pto), body,
    )


def _origin_link(client, ctx: Ctx, jid: str) -> dict:
    links = _links(client, ctx, jid).json()
    return next(link for link in links if link["revision_role"] == "ORIGIN")


def _db_links(db: Session, jid: str) -> list[JointDocumentRevision]:
    return (
        db.query(JointDocumentRevision)
        .filter(JointDocumentRevision.joint_id == jid)
        .order_by(JointDocumentRevision.created_at, JointDocumentRevision.id)
        .all()
    )


# ══ A. ORIGIN-связь при создании Joint ════════════════════════════════════════


def test_origin_link_created_on_joint_create(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AORIG")
    j = ctx.create_joint(client)
    jid = j["id"]
    links = _links(client, ctx, jid).json()
    assert len(links) == 1
    origin = links[0]
    assert origin["revision_role"] == "ORIGIN"
    assert origin["document_role"] == "PRIMARY"
    assert origin["link_status"] == "ACTIVE"
    assert origin["document_revision_id"] == str(ctx.revision.id)
    assert origin["document_revision_id"] == j["origin_document_revision_id"]
    assert j["current_document_revision_id"] == str(ctx.revision.id)
    # Фактическое состояние БД.
    db_links = _db_links(db, jid)
    assert len(db_links) == 1
    assert db_links[0].revision_role == "ORIGIN"
    assert db_links[0].link_status == "ACTIVE"


def test_origin_snapshot_matches_joint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ASNAP")
    j = ctx.create_joint(
        client, joint_no="Ж-10 ", dn_1="100", thickness_1="6",
        geometry_type="BUTT", weld_joint_type="BW", connection_code="C",
        required_root_method="141", component_text_1="фланец",
        heat_treatment_required=True, heat_treatment_type="PWHT",
    )
    jid = j["id"]
    origin = _origin_link(client, ctx, jid)
    assert origin["snapshot_joint_no"] == "Ж-10 "  # исходное значение сохранено
    assert origin["snapshot_joint_no_normalized"] == "Ж-10"
    assert origin["snapshot_line_id"] == str(ctx.line.id)
    assert Decimal(str(origin["snapshot_dn_1"])) == Decimal("100")
    assert Decimal(str(origin["snapshot_thickness_1"])) == Decimal("6")
    assert origin["snapshot_geometry_type"] == "BUTT"
    assert origin["snapshot_weld_joint_type"] == "BW"
    assert origin["snapshot_connection_code"] == "C"
    assert origin["snapshot_required_root_method"] == "141"
    assert origin["snapshot_component_text_1"] == "фланец"
    assert origin["snapshot_heat_treatment_required"] is True
    assert origin["snapshot_heat_treatment_type"] == "PWHT"


def test_origin_snapshot_immutable_after_joint_edit(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "AIMM")
    j = ctx.create_joint(client, dn_1="100")
    jid = j["id"]
    # Значимая правка Joint в DRAFT.
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": j["record_version"], "updated_by": ctx.pto.id,
              "dn_1": "250"},
        headers=ctx.headers(ctx.pto),
    )
    assert resp.status_code == 200, resp.text
    # Снимок ORIGIN не изменился.
    origin = _origin_link(client, ctx, jid)
    assert Decimal(str(origin["snapshot_dn_1"])) == Decimal("100")
    db.expire_all()
    db_link = _db_links(db, jid)[0]
    assert db_link.snapshot_dn_1 == Decimal("100")


def test_joint_and_origin_link_atomic(client: TestClient, db: Session) -> None:
    """Дубль номера в ревизии → Joint не создаётся и связь тоже (атомарность)."""
    ctx = Ctx(db, "AATOM")
    ctx.create_joint(client, joint_no="DUP")
    before = db.query(Joint).filter(Joint.project_id == ctx.project.id).count()
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json={
            "project_id": str(ctx.project.id), "line_id": str(ctx.line.id),
            "document_revision_id": str(ctx.revision.id), "joint_no": "DUP",
            "created_by": ctx.creator.id,
        },
        headers=ctx.headers(ctx.creator),
    )
    assert resp.status_code == 409
    after = db.query(Joint).filter(Joint.project_id == ctx.project.id).count()
    assert after == before


# ══ B. Дополнительные связи ════════════════════════════════════════════════════


def test_create_additional_link(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BADD")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    resp = _create_link(client, ctx, jid, str(rev1.id))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["revision_role"] == "CONFIRMED"
    assert body["document_role"] == "ADDITIONAL"
    assert body["link_status"] == "ACTIVE"
    assert body["document_revision_id"] == str(rev1.id)
    assert len(_db_links(db, jid)) == 2


def test_additional_link_does_not_change_current(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "BCUR")
    j = ctx.create_joint(client)
    jid = j["id"]
    rev1 = ctx.add_revision("R1")
    _create_link(client, ctx, jid, str(rev1.id))
    got = client.get(
        f"{ENGINEERING_URL}/joints/{jid}", headers=ctx.headers(ctx.pto)
    ).json()
    assert got["current_document_revision_id"] == str(ctx.revision.id)
    # PRIMARY по-прежнему ORIGIN.
    origin = _origin_link(client, ctx, jid)
    assert origin["document_role"] == "PRIMARY"


def test_additional_link_snapshots_current_state(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "BSNAP")
    j = ctx.create_joint(client, dn_1="100")
    jid = j["id"]
    # Правим Joint (DRAFT), затем создаём связь — снимок фиксирует новое состояние.
    client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": j["record_version"], "updated_by": ctx.pto.id,
              "dn_1": "300"},
        headers=ctx.headers(ctx.pto),
    )
    rev1 = ctx.add_revision("R1")
    body = _create_link(client, ctx, jid, str(rev1.id)).json()
    assert Decimal(str(body["snapshot_dn_1"])) == Decimal("300")
    # ORIGIN-снимок остался прежним.
    origin = _origin_link(client, ctx, jid)
    assert Decimal(str(origin["snapshot_dn_1"])) == Decimal("100")


def test_create_link_primary_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BPRIM")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    resp = _create_link(client, ctx, jid, str(rev1.id), document_role="PRIMARY")
    assert resp.status_code == 422


def test_create_link_origin_role_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BORIG")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    resp = _create_link(client, ctx, jid, str(rev1.id), revision_role="ORIGIN")
    assert resp.status_code == 422


def test_create_link_foreign_project_revision_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "BFOR")
    jid = ctx.create_joint(client)["id"]
    other = Ctx(db, "BFOR2")
    resp = _create_link(client, ctx, jid, str(other.revision.id))
    assert resp.status_code == 422


def test_create_link_no_role_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BROLE")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    plain = _worker(db, "BPlain")
    resp = _create_link(client, ctx, jid, str(rev1.id), worker=plain)
    assert resp.status_code == 403


def test_create_link_ogs_engineer_allowed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BOGS")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    resp = _create_link(client, ctx, jid, str(rev1.id), worker=ctx.ogs)
    assert resp.status_code == 201, resp.text


def test_duplicate_normalized_in_revision_rejected(
    client: TestClient, db: Session
) -> None:
    """Один нормализованный номер не может дважды присутствовать в активной ревизии."""
    ctx = Ctx(db, "BDUP")
    j1 = ctx.create_joint(client, joint_no="A-1")
    j2 = ctx.create_joint(client, joint_no="A-2")
    rev1 = ctx.add_revision("R1")
    assert _create_link(client, ctx, j1["id"], str(rev1.id)).status_code == 201
    # У j2 снимок номера "A-2" — конфликта нет.
    assert _create_link(client, ctx, j2["id"], str(rev1.id)).status_code == 201
    # Ещё одна активная связь j1 с той же ревизией и тем же номером — конфликт.
    dup = _create_link(
        client, ctx, j1["id"], str(rev1.id), document_role="REFERENCE"
    )
    assert dup.status_code == 409


# ══ C. Список истории ══════════════════════════════════════════════════════════


def test_history_list_returns_all_links(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "CLIST")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    rev2 = ctx.add_revision("R2")
    _create_link(client, ctx, jid, str(rev1.id))
    _create_link(client, ctx, jid, str(rev2.id))
    links = _links(client, ctx, jid).json()
    assert len(links) == 3
    # Сортировка по created_at, затем id — ORIGIN первым.
    assert links[0]["revision_role"] == "ORIGIN"


def test_history_list_filters(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "CFILT")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    _invalidate(client, ctx, jid, link["id"])
    active = _links(client, ctx, jid, link_status="ACTIVE").json()
    assert all(link_["link_status"] == "ACTIVE" for link_ in active)
    assert len(active) == 1
    invalid = _links(client, ctx, jid, link_status="INVALIDATED").json()
    assert len(invalid) == 1
    origins = _links(client, ctx, jid, revision_role="ORIGIN").json()
    assert len(origins) == 1


# ══ D. Аннулирование связи ═════════════════════════════════════════════════════


def test_invalidate_active_link(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DINV")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _invalidate(client, ctx, jid, link["id"], reason="ошибочная привязка")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["link_status"] == "INVALIDATED"
    assert body["invalidated_reason"] == "ошибочная привязка"
    assert body["invalidated_by"] == ctx.pto.id
    assert body["invalidated_at"] is not None
    assert body["updated_by"] == ctx.pto.id
    assert body["updated_at"] is not None
    # Снимок не тронут.
    assert body["snapshot_joint_no"] == "J-1"


def test_invalidate_reason_required(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DREAS")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _invalidate(client, ctx, jid, link["id"], reason="   ")
    assert resp.status_code == 422


def test_invalidate_twice_conflict(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DTWICE")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    assert _invalidate(client, ctx, jid, link["id"]).status_code == 200
    again = _invalidate(client, ctx, jid, link["id"])
    assert again.status_code == 409


def test_invalidated_link_stays_in_db_and_history(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "DSTAY")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    _invalidate(client, ctx, jid, link["id"])
    # Физически запись есть.
    db.expire_all()
    db_links = _db_links(db, jid)
    assert len(db_links) == 2
    # И в GET-истории.
    assert any(
        link_["id"] == link["id"] and link_["link_status"] == "INVALIDATED"
        for link_ in _links(client, ctx, jid).json()
    )


def test_no_physical_delete_endpoint(client: TestClient, db: Session) -> None:
    """Физического удаления истории нет: DELETE-операции отсутствуют в API.

    Каноническое требование — отсутствие DELETE-маршрута, а не конкретный код.
    Проверяем OpenAPI (ни одна document-revisions операция не поддерживает DELETE),
    а сам HTTP DELETE отсутствующего маршрута возвращает 404 либо 405.
    """
    ctx = Ctx(db, "DNODEL")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    openapi = client.get("/openapi.json").json()
    for path, operations in openapi["paths"].items():
        if "document-revisions" in path:
            assert "delete" not in operations, f"неожиданный DELETE на {path}"
    resp = client.delete(
        f"{ENGINEERING_URL}/joints/{jid}/document-revisions/{link['id']}",
        headers=ctx.headers(ctx.pto),
    )
    assert resp.status_code in (404, 405)


def test_cannot_invalidate_current_primary(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DPRIM")
    jid = ctx.create_joint(client)["id"]
    origin = _origin_link(client, ctx, jid)
    resp = _invalidate(client, ctx, jid, origin["id"])
    assert resp.status_code == 409


def test_cannot_invalidate_origin_after_demotion(
    client: TestClient, db: Session
) -> None:
    """ORIGIN нельзя аннулировать даже после того, как она перестала быть PRIMARY."""
    ctx = Ctx(db, "DORIG")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    assert _set_current(client, ctx, jid, link["id"]).status_code == 200
    # Теперь ORIGIN не PRIMARY, но аннулировать её всё равно нельзя.
    origin = _origin_link(client, ctx, jid)
    assert origin["document_role"] != "PRIMARY"
    resp = _invalidate(client, ctx, jid, origin["id"])
    assert resp.status_code == 409


def test_invalidate_foreign_link_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "DFOR")
    jid1 = ctx.create_joint(client, joint_no="J-1")["id"]
    jid2 = ctx.create_joint(client, joint_no="J-2")["id"]
    rev1 = ctx.add_revision("R1")
    link2 = _create_link(client, ctx, jid2, str(rev1.id)).json()
    # Пытаемся аннулировать связь j2 через j1.
    resp = _invalidate(client, ctx, jid1, link2["id"])
    assert resp.status_code in (404, 409)


def test_reuse_number_after_invalidation(client: TestClient, db: Session) -> None:
    """После аннулирования старой связи номер можно использовать повторно."""
    ctx = Ctx(db, "DREUSE")
    jid = ctx.create_joint(client, joint_no="RE-1")["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    # Повтор той же ревизии/номера отклоняется.
    assert _create_link(
        client, ctx, jid, str(rev1.id), document_role="REFERENCE"
    ).status_code == 409
    # После аннулирования — повтор разрешён.
    _invalidate(client, ctx, jid, link["id"])
    ok = _create_link(client, ctx, jid, str(rev1.id), document_role="REFERENCE")
    assert ok.status_code == 201, ok.text


# ══ E. set-current-revision ════════════════════════════════════════════════════


def test_set_current_switches_primary(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ESWAP")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _set_current(client, ctx, jid, link["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_document_revision_id"] == str(rev1.id)
    # Новая связь — единственная активная PRIMARY.
    db.expire_all()
    primaries = [
        link_ for link_ in _db_links(db, jid)
        if link_.document_role == "PRIMARY" and link_.link_status == "ACTIVE"
    ]
    assert len(primaries) == 1
    assert str(primaries[0].id) == link["id"]
    assert str(primaries[0].document_revision_id) == str(rev1.id)


def test_set_current_old_primary_snapshot_unchanged(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "EOLD")
    j = ctx.create_joint(client, dn_1="100")
    jid = j["id"]
    origin_before = _origin_link(client, ctx, jid)
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    _set_current(client, ctx, jid, link["id"])
    origin_after = _origin_link(client, ctx, jid)
    # Старая PRIMARY перестала быть PRIMARY, но снимок не изменился.
    assert origin_after["document_role"] != "PRIMARY"
    assert origin_after["revision_role"] == "ORIGIN"
    assert Decimal(str(origin_after["snapshot_dn_1"])) == Decimal(
        str(origin_before["snapshot_dn_1"])
    )


def test_set_current_restores_engineering_fields(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "EREST")
    # DRAFT: joint_no A / dn_1 100.
    j = ctx.create_joint(client, joint_no="A", dn_1="100")
    jid = j["id"]
    rv = j["record_version"]
    # DRAFT-правка идентичности и данных: joint_no B / dn_1 200.
    patched = client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": rv, "updated_by": ctx.pto.id,
              "joint_no": "B", "dn_1": "200"},
        headers=ctx.headers(ctx.pto),
    ).json()
    # Связь на R1 со снимком B/200.
    rev1 = ctx.add_revision("R1")
    link1 = _create_link(client, ctx, jid, str(rev1.id)).json()
    assert _set_current(client, ctx, jid, link1["id"]).status_code == 200
    # Ещё правка: joint_no C / dn_1 999.
    got = client.get(
        f"{ENGINEERING_URL}/joints/{jid}", headers=ctx.headers(ctx.pto)
    ).json()
    client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": got["record_version"], "updated_by": ctx.pto.id,
              "joint_no": "C", "dn_1": "999"},
        headers=ctx.headers(ctx.pto),
    )
    # Возврат к ORIGIN-снимку (A/100).
    origin = _origin_link(client, ctx, jid)
    resp = _set_current(client, ctx, jid, origin["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["joint_no"] == "A"
    assert body["joint_no_normalized"] == "A"
    assert Decimal(str(body["dn_1"])) == Decimal("100")
    assert body["current_document_revision_id"] == str(ctx.revision.id)
    # Фактическое состояние Joint в БД.
    db.expire_all()
    joint = db.query(Joint).filter(Joint.id == jid).one()
    assert joint.joint_no == "A"
    assert joint.joint_no_normalized == "A"
    assert joint.dn_1 == Decimal("100")
    assert str(joint.current_document_revision_id) == str(ctx.revision.id)


def test_set_current_invalidated_link_rejected(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "EINV")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    _invalidate(client, ctx, jid, link["id"])
    resp = _set_current(client, ctx, jid, link["id"])
    assert resp.status_code == 409


def test_set_current_foreign_link_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "EFOR")
    jid1 = ctx.create_joint(client, joint_no="J-1")["id"]
    jid2 = ctx.create_joint(client, joint_no="J-2")["id"]
    rev1 = ctx.add_revision("R1")
    link2 = _create_link(client, ctx, jid2, str(rev1.id)).json()
    resp = _set_current(client, ctx, jid1, link2["id"])
    assert resp.status_code in (404, 409)


def test_set_current_idempotent_returns_conflict(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "EIDEM")
    jid = ctx.create_joint(client)["id"]
    origin = _origin_link(client, ctx, jid)
    # ORIGIN уже текущая PRIMARY — назначить её же → контролируемый 409.
    resp = _set_current(client, ctx, jid, origin["id"])
    assert resp.status_code == 409


def test_set_current_requires_rights_on_new_document(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "ENEWD")
    jid = ctx.create_joint(client)["id"]
    new_doc, new_rev = ctx.add_document_and_revision("ENEWD2")
    link = _create_link(client, ctx, jid, str(new_rev.id)).json()
    # Актор с ролью только на СТАРЫЙ документ — прав на новый нет.
    scoped = _role_worker(
        db, "ENewOld", "PTO_ENGINEER", scope_type="ENGINEERING_DOCUMENT",
        scope_id=str(ctx.document.id),
    )
    resp = _set_current(client, ctx, jid, link["id"], worker=scoped)
    assert resp.status_code == 403


def test_set_current_requires_rights_on_old_document(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "EOLDD")
    jid = ctx.create_joint(client)["id"]
    new_doc, new_rev = ctx.add_document_and_revision("EOLDD2")
    link = _create_link(client, ctx, jid, str(new_rev.id)).json()
    # Актор с ролью только на НОВЫЙ документ — прав на старый нет.
    scoped = _role_worker(
        db, "EOldNew", "PTO_ENGINEER", scope_type="ENGINEERING_DOCUMENT",
        scope_id=str(new_doc.id),
    )
    resp = _set_current(client, ctx, jid, link["id"], worker=scoped)
    assert resp.status_code == 403


# ══ F. Сброс согласований при set-current ══════════════════════════════════════


def _make_active(client, ctx: Ctx, jid: str) -> dict:
    assert _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/submit-for-review",
        ctx.headers(ctx.pto),
    ).status_code == 200
    assert _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/approve-pto",
        ctx.headers(ctx.pto),
    ).status_code == 200
    resp = _post(
        client, f"{ENGINEERING_URL}/joints/{jid}/approve-ogs",
        ctx.headers(ctx.ogs),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ACTIVE"
    return body


def _reset_scenario(
    client, ctx: Ctx, jid: str, field: str, value_x: str, value_y: str
):
    """Готовит связь L1 со снимком value_x и ACTIVE Joint со значением value_y.

    set-current на L1 восстановит value_x → значимое изменение → сброс согласований.
    """
    # DRAFT: поле = value_x → связь L1 фиксирует value_x.
    j = client.get(
        f"{ENGINEERING_URL}/joints/{jid}", headers=ctx.headers(ctx.pto)
    ).json()
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    # Меняем поле на value_y (DRAFT).
    client.patch(
        f"{ENGINEERING_URL}/joints/{jid}",
        json={"expected_version": j["record_version"], "updated_by": ctx.pto.id,
              field: value_y},
        headers=ctx.headers(ctx.pto),
    )
    # Делаем ACTIVE.
    _make_active(client, ctx, jid)
    return link


def test_set_current_pto_field_resets_only_pto(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "FPTO")
    j = ctx.create_joint(client, component_text_1="X")
    jid = j["id"]
    link = _reset_scenario(client, ctx, jid, "component_text_1", "X", "Y")
    body = _set_current(client, ctx, jid, link["id"]).json()
    assert body["component_text_1"] == "X"
    assert body["pto_status"] == "PENDING"
    assert body["pto_pending_reason"] == "REVALIDATION"
    assert body["ogs_status"] == "APPROVED"
    assert body["status"] == "PENDING_REVIEW"


def test_set_current_ogs_field_resets_only_ogs(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "FOGS")
    j = ctx.create_joint(client, required_root_method="141")
    jid = j["id"]
    link = _reset_scenario(client, ctx, jid, "required_root_method", "141", "111")
    body = _set_current(client, ctx, jid, link["id"]).json()
    assert body["required_root_method"] == "141"
    assert body["ogs_status"] == "PENDING"
    assert body["pto_status"] == "APPROVED"
    assert body["status"] == "PENDING_REVIEW"


def test_set_current_common_field_resets_both(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "FBOTH")
    j = ctx.create_joint(client, dn_1="100")
    jid = j["id"]
    link = _reset_scenario(client, ctx, jid, "dn_1", "100", "200")
    body = _set_current(client, ctx, jid, link["id"]).json()
    assert Decimal(str(body["dn_1"])) == Decimal("100")
    assert body["pto_status"] == "PENDING"
    assert body["ogs_status"] == "PENDING"
    assert body["status"] == "PENDING_REVIEW"


# ══ G. Версии при set-current ══════════════════════════════════════════════════


def test_set_current_bumps_record_and_workflow(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "GVER")
    j = ctx.create_joint(client)
    jid = j["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    before = client.get(
        f"{ENGINEERING_URL}/joints/{jid}", headers=ctx.headers(ctx.pto)
    ).json()
    body = _set_current(client, ctx, jid, link["id"]).json()
    assert body["record_version"] == before["record_version"] + 1
    assert body["workflow_version"] == before["workflow_version"] + 1


def test_set_current_significant_bumps_approval(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "GAPP")
    j = ctx.create_joint(client, dn_1="100")
    jid = j["id"]
    link = _reset_scenario(client, ctx, jid, "dn_1", "100", "200")
    before = client.get(
        f"{ENGINEERING_URL}/joints/{jid}", headers=ctx.headers(ctx.pto)
    ).json()
    body = _set_current(client, ctx, jid, link["id"]).json()
    assert body["approval_version"] == before["approval_version"] + 1


def test_set_current_non_significant_keeps_approval(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "GNOAP")
    j = ctx.create_joint(client, location_note="a")
    jid = j["id"]
    rev1 = ctx.add_revision("R1")
    # Связь со снимком идентичных значимых полей.
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    before = client.get(
        f"{ENGINEERING_URL}/joints/{jid}", headers=ctx.headers(ctx.pto)
    ).json()
    body = _set_current(client, ctx, jid, link["id"]).json()
    assert body["approval_version"] == before["approval_version"]


def test_set_current_stale_record_version_conflict(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "GREC")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _set_current(client, ctx, jid, link["id"], expected_record_version=999)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "RECORD_VERSION_CONFLICT"


def test_set_current_stale_approval_version_conflict(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "GAPPC")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _set_current(client, ctx, jid, link["id"], expected_approval_version=999)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "APPROVAL_VERSION_CONFLICT"


def test_set_current_stale_workflow_version_conflict(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "GWFC")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _set_current(client, ctx, jid, link["id"], expected_workflow_version=999)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WORKFLOW_VERSION_CONFLICT"


# ══ H. Инварианты БД ═══════════════════════════════════════════════════════════


def test_single_active_primary_per_joint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "HPRIM")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    rev2 = ctx.add_revision("R2")
    link1 = _create_link(client, ctx, jid, str(rev1.id)).json()
    link2 = _create_link(client, ctx, jid, str(rev2.id)).json()
    _set_current(client, ctx, jid, link1["id"])
    _set_current(client, ctx, jid, link2["id"])
    db.expire_all()
    primaries = [
        link_ for link_ in _db_links(db, jid)
        if link_.document_role == "PRIMARY" and link_.link_status == "ACTIVE"
    ]
    assert len(primaries) == 1
    assert str(primaries[0].id) == link2["id"]


def test_set_current_no_role_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "HROLE")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    plain = _worker(db, "HPlain")
    resp = _set_current(client, ctx, jid, link["id"], worker=plain)
    assert resp.status_code == 403


def test_set_current_ogs_engineer_allowed(client: TestClient, db: Session) -> None:
    """OGS_ENGINEER в допустимом scope может менять текущую ревизию (§7 канона)."""
    ctx = Ctx(db, "HOGS")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    resp = _set_current(client, ctx, jid, link["id"], worker=ctx.ogs)
    assert resp.status_code == 200, resp.text


def test_set_current_engineering_document_scope_allowed(
    client: TestClient, db: Session
) -> None:
    """ENGINEERING_DOCUMENT-scoped ПТО покрывает старый и новый документ (одна изометрия)."""
    ctx = Ctx(db, "HEDOC")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")  # ревизия того же документа
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    scoped = _role_worker(
        db, "HEDocOk", "PTO_ENGINEER", scope_type="ENGINEERING_DOCUMENT",
        scope_id=str(ctx.document.id),
    )
    resp = _set_current(client, ctx, jid, link["id"], worker=scoped)
    assert resp.status_code == 200, resp.text


def test_set_current_foreign_project_scope_forbidden(
    client: TestClient, db: Session
) -> None:
    ctx = Ctx(db, "HSCOPE")
    jid = ctx.create_joint(client)["id"]
    rev1 = ctx.add_revision("R1")
    link = _create_link(client, ctx, jid, str(rev1.id)).json()
    foreign = _role_worker(
        db, "HForeign", "PTO_ENGINEER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = _set_current(client, ctx, jid, link["id"], worker=foreign)
    assert resp.status_code == 403


# ══ I. Регрессия ═══════════════════════════════════════════════════════════════


def test_joint_not_found(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "INF")
    resp = _links(client, ctx, str(uuid4()))
    assert resp.status_code == 404
