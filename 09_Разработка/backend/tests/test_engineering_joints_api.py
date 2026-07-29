"""Интеграционные тесты Joint Core (Task 5A, ADR-010).

Ядро стыка без lifecycle-переходов согласования (Task 5B), истории снимков
(Task 6) и bulk (Task 7). Проверяются: автогенерация system_code (отдельная
последовательность на проект, без переиспользования), нормализация joint_no,
запрет дубля в ревизии, согласованность иерархии Project → Line /
DocumentRevision, вычисляемые поля (ready_for_welding, missing_welding_requirements,
production_state), optimistic locking и защита полей при PATCH.

Роли/scope в Task 5A не проверяются (Task 5B): актор (created_by/updated_by)
приходит в теле запроса; X-User-Id обязателен как аутентификация модуля.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument
from app.hr.models import Worker
from app.projects.models import Line, Project

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"

# Минимальный набор инженерных полей, дающих ready_for_welding=True (сервис).
READY_FIELDS: dict = {
    "geometry_type": "BUTT",
    "weld_joint_type": "BW",
    "dn_1": 100,
    "thickness_1": 6,
    "required_root_method": "141",
    "required_fill_method": "111",
    "required_cap_method": "111",
}


# ── Хелперы данных (через ORM, без ролей) ─────────────────────────────────────


def _worker(db: Session, *, suffix: str) -> Worker:
    worker = Worker(
        last_name=f"Jnt{suffix}",
        first_name="Тест",
        company_id=TEST_COMPANY_ID,
        employment_status="active",
        hire_date=date.today(),
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def _project(db: Session, *, author_id: int, code: str) -> Project:
    project = Project(
        code=code, name=f"Проект {code}", status="active", created_by=author_id
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _line(db: Session, *, project_id: UUID, author_id: int, line_no: str) -> Line:
    line = Line(
        project_id=project_id,
        line_no=line_no,
        status="active",
        required_inspection_types=[],
        created_by=author_id,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def _document(
    db: Session, *, project_id: UUID, author_id: int, document_no: str, line_id=None
) -> EngineeringDocument:
    doc = EngineeringDocument(
        project_id=project_id,
        line_id=line_id,
        document_no=document_no,
        document_type="ISOMETRIC",
        status="APPROVED",
        created_by=author_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _revision(
    db: Session, *, document_id: UUID, author_id: int, revision_code: str = "R0"
) -> DocumentRevision:
    rev = DocumentRevision(
        engineering_document_id=document_id,
        revision_code=revision_code,
        status="APPROVED",
        created_by=author_id,
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)
    return rev


class Context:
    """Полный контекст для создания стыка."""

    def __init__(self, db: Session, *, code: str, doc_has_line: bool = True) -> None:
        self.worker = _worker(db, suffix=code)
        self.project = _project(db, author_id=self.worker.id, code=code)
        self.line = _line(
            db, project_id=self.project.id, author_id=self.worker.id, line_no=f"L-{code}"
        )
        self.document = _document(
            db,
            project_id=self.project.id,
            author_id=self.worker.id,
            document_no=f"DOC-{code}",
            line_id=self.line.id if doc_has_line else None,
        )
        self.revision = _revision(
            db, document_id=self.document.id, author_id=self.worker.id
        )

    def headers(self) -> dict[str, str]:
        return {"X-User-Id": str(self.worker.id)}

    def payload(self, **overrides) -> dict:
        data: dict = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": "J-1",
            "created_by": self.worker.id,
        }
        data.update(overrides)
        return data


def _create(client: TestClient, ctx: Context, **overrides) -> dict:
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(**overrides),
        headers=ctx.headers(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Создание ──────────────────────────────────────────────────────────────────


def test_create_joint_success(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="CJ1")
    body = _create(client, ctx, joint_no="J-100")
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    assert body["joint_no"] == "J-100"
    assert body["created_by"] == ctx.worker.id
    assert body["updated_by"] == ctx.worker.id
    # origin == current при создании.
    assert body["origin_document_revision_id"] == str(ctx.revision.id)
    assert body["current_document_revision_id"] == str(ctx.revision.id)
    assert body["production_state"] == "NOT_STARTED"
    UUID(body["id"])


def test_system_code_generated_not_accepted_from_user(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="SC1")
    body = _create(client, ctx)
    # Формат <project_code>-JNT-<sequence>.
    assert body["system_code"].startswith(f"{ctx.project.code}-JNT-")
    # Даже если клиент попытается прислать system_code — extra=forbid → 422.
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="J-2", system_code="HACK"),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_sequential_codes_within_project(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="SEQ")
    first = _create(client, ctx, joint_no="J-1")
    second = _create(client, ctx, joint_no="J-2")
    third = _create(client, ctx, joint_no="J-3")
    assert first["system_code"] == f"{ctx.project.code}-JNT-0001"
    assert second["system_code"] == f"{ctx.project.code}-JNT-0002"
    assert third["system_code"] == f"{ctx.project.code}-JNT-0003"


def test_independent_sequences_per_project(client: TestClient, db: Session) -> None:
    ctx_a = Context(db, code="INDA")
    ctx_b = Context(db, code="INDB")
    a1 = _create(client, ctx_a, joint_no="A-1")
    b1 = _create(client, ctx_b, joint_no="B-1")
    a2 = _create(client, ctx_a, joint_no="A-2")
    assert a1["system_code"] == f"{ctx_a.project.code}-JNT-0001"
    assert a2["system_code"] == f"{ctx_a.project.code}-JNT-0002"
    assert b1["system_code"] == f"{ctx_b.project.code}-JNT-0001"


def test_original_joint_no_preserved(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="ORIG")
    raw = "  Ст—1   a "
    body = _create(client, ctx, joint_no=raw)
    assert body["joint_no"] == raw
    assert body["joint_no_normalized"] == "СТ-1 A"


def test_joint_no_normalization_variants(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="NORM")
    body = _create(client, ctx, joint_no="a–b")  # en dash
    assert body["joint_no_normalized"] == "A-B"


def test_duplicate_joint_no_in_revision_conflict(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="DUP")
    _create(client, ctx, joint_no="J-1")
    # Тот же номер в другом регистре/с типографским дефисом → тот же нормализ.
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="j–1"),
        headers=ctx.headers(),
    )
    assert resp.status_code == 409


def test_same_joint_no_allowed_in_other_revision(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="DUP2")
    _create(client, ctx, joint_no="J-1")
    other_rev = _revision(
        db, document_id=ctx.document.id, author_id=ctx.worker.id, revision_code="R1"
    )
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="J-1", document_revision_id=str(other_rev.id)),
        headers=ctx.headers(),
    )
    assert resp.status_code == 201, resp.text


# ── Иерархия ──────────────────────────────────────────────────────────────────


def test_unknown_project_404(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="UP")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(project_id=str(uuid4())),
        headers=ctx.headers(),
    )
    assert resp.status_code == 404


def test_invalid_line_422(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="BADLINE")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(line_id=str(uuid4())),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_line_of_other_project_422(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="XLINE")
    other = Context(db, code="XLINE2")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(line_id=str(other.line.id)),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_revision_of_other_project_422(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="XREV")
    other = Context(db, code="XREV2")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(document_revision_id=str(other.revision.id)),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_unknown_revision_404(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="NOREV")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(document_revision_id=str(uuid4())),
        headers=ctx.headers(),
    )
    assert resp.status_code == 404


def test_document_with_matching_line_ok(client: TestClient, db: Session) -> None:
    # Документ привязан к линии стыка → допустимо.
    ctx = Context(db, code="MLINE", doc_has_line=True)
    body = _create(client, ctx, joint_no="J-1")
    assert body["line_id"] == str(ctx.line.id)


def test_document_with_other_line_422(client: TestClient, db: Session) -> None:
    # Документ привязан к другой линии проекта → несоответствие.
    ctx = Context(db, code="OLINE", doc_has_line=False)
    other_line = _line(
        db, project_id=ctx.project.id, author_id=ctx.worker.id, line_no="L-OTHER"
    )
    # Пересоздаём документ с чужой линией.
    doc = _document(
        db,
        project_id=ctx.project.id,
        author_id=ctx.worker.id,
        document_no="DOC-OLINE2",
        line_id=other_line.id,
    )
    rev = _revision(db, document_id=doc.id, author_id=ctx.worker.id)
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(document_revision_id=str(rev.id)),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_document_without_line_ok(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="NLINE", doc_has_line=False)
    body = _create(client, ctx, joint_no="J-1")
    assert body["line_id"] == str(ctx.line.id)


# ── Единое правило источника Joint: только APPROVED document + APPROVED revision ─


def _source_status_rejected(
    client: TestClient, ctx: Context
) -> None:
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="J-1"),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "DOCUMENT_REVISION_NOT_ALLOWED"


def test_create_rejects_draft_document(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="SRCDD")
    ctx.document.status = "DRAFT"
    db.add(ctx.document)
    db.commit()
    _source_status_rejected(client, ctx)


def test_create_rejects_draft_revision(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="SRCDR")
    ctx.revision.status = "DRAFT"
    db.add(ctx.revision)
    db.commit()
    _source_status_rejected(client, ctx)


def test_create_rejects_cancelled_document(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="SRCCD")
    ctx.document.status = "CANCELLED"
    db.add(ctx.document)
    db.commit()
    _source_status_rejected(client, ctx)


def test_create_rejects_superseded_revision(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="SRCSR")
    ctx.revision.status = "SUPERSEDED"
    db.add(ctx.revision)
    db.commit()
    _source_status_rejected(client, ctx)


def test_create_allows_approved_document_and_revision(
    client: TestClient, db: Session
) -> None:
    # APPROVED + APPROVED (значения по умолчанию в Context) → создание разрешено.
    ctx = Context(db, code="SRCOK")
    assert ctx.document.status == "APPROVED"
    assert ctx.revision.status == "APPROVED"
    body = _create(client, ctx, joint_no="J-1")
    assert body["status"] == "DRAFT"


# ── Валидация схемы ───────────────────────────────────────────────────────────


def test_blank_joint_no_422(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="BLANK")
    for bad in ("", "   "):
        resp = client.post(
            f"{ENGINEERING_URL}/joints",
            json=ctx.payload(joint_no=bad),
            headers=ctx.headers(),
        )
        assert resp.status_code == 422, resp.text


def test_coordinates_require_coordinate_system_422(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="COORD")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="J-1", position_x="10.5"),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_coordinates_with_system_ok(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="COORD2")
    body = _create(
        client,
        ctx,
        joint_no="J-1",
        position_x="10.5",
        position_y="4",
        coordinate_system="DWG",
    )
    assert body["coordinate_system"] == "DWG"


def test_negative_dn_422(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="NEGDN")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="J-1", dn_1="-5"),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_invalid_geometry_type_422(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="BADGEO")
    resp = client.post(
        f"{ENGINEERING_URL}/joints",
        json=ctx.payload(joint_no="J-1", geometry_type="ROUND"),
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_create_requires_user_id_401(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="NOAUTH")
    resp = client.post(f"{ENGINEERING_URL}/joints", json=ctx.payload())
    assert resp.status_code == 401


# ── Чтение / список / фильтры / сортировка / пагинация ────────────────────────


def test_get_joint_by_id(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="GET")
    created = _create(client, ctx, joint_no="J-1")
    resp = client.get(
        f"{ENGINEERING_URL}/joints/{created['id']}", headers=ctx.headers()
    )
    assert resp.status_code == 200
    assert resp.json()["system_code"] == created["system_code"]


def test_get_missing_joint_404(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="GETMISS")
    resp = client.get(
        f"{ENGINEERING_URL}/joints/{uuid4()}", headers=ctx.headers()
    )
    assert resp.status_code == 404


def test_list_and_filters(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="LIST")
    _create(client, ctx, joint_no="J-1", geometry_type="BUTT")
    _create(client, ctx, joint_no="J-2", geometry_type="FILLET")

    # Фильтр по project_id.
    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={"project_id": str(ctx.project.id)},
        headers=ctx.headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    # Фильтр по geometry_type.
    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={"project_id": str(ctx.project.id), "geometry_type": "FILLET"},
        headers=ctx.headers(),
    )
    nos = {j["joint_no"] for j in resp.json()["items"]}
    assert nos == {"J-2"}

    # Фильтр по line_id / current_document_revision_id / system_code / joint_no.
    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={"line_id": str(ctx.line.id)},
        headers=ctx.headers(),
    )
    assert resp.json()["total"] == 2

    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={"joint_no": "j-1"},  # нормализуется
        headers=ctx.headers(),
    )
    nos = {j["joint_no"] for j in resp.json()["items"]}
    assert nos == {"J-1"}


def test_filter_ready_for_welding(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="RDYF")
    _create(client, ctx, joint_no="READY", **READY_FIELDS)
    _create(client, ctx, joint_no="NOTREADY")

    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={"project_id": str(ctx.project.id), "ready_for_welding": "true"},
        headers=ctx.headers(),
    )
    nos = {j["joint_no"] for j in resp.json()["items"]}
    assert nos == {"READY"}

    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={"project_id": str(ctx.project.id), "ready_for_welding": "false"},
        headers=ctx.headers(),
    )
    nos = {j["joint_no"] for j in resp.json()["items"]}
    assert nos == {"NOTREADY"}


def test_sorting_by_system_code_desc(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="SORT")
    _create(client, ctx, joint_no="J-1")
    _create(client, ctx, joint_no="J-2")
    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={
            "project_id": str(ctx.project.id),
            "sort_by": "system_code",
            "sort_order": "desc",
        },
        headers=ctx.headers(),
    )
    codes = [j["system_code"] for j in resp.json()["items"]]
    assert codes == sorted(codes, reverse=True)


def test_pagination(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="PAGE")
    for i in range(3):
        _create(client, ctx, joint_no=f"J-{i}")
    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={
            "project_id": str(ctx.project.id),
            "limit": 2,
            "offset": 0,
            "sort_by": "system_code",
        },
        headers=ctx.headers(),
    )
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    resp = client.get(
        f"{ENGINEERING_URL}/joints",
        params={
            "project_id": str(ctx.project.id),
            "limit": 2,
            "offset": 2,
            "sort_by": "system_code",
        },
        headers=ctx.headers(),
    )
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1


# ── Вычисляемые поля ──────────────────────────────────────────────────────────


def test_ready_for_welding_false_lists_missing(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="MISS")
    body = _create(client, ctx, joint_no="J-1")
    assert body["ready_for_welding"] is False
    assert set(body["missing_welding_requirements"]) == {
        "geometry_type",
        "weld_joint_type",
        "dn_1",
        "thickness_1",
        "required_root_method",
        "required_fill_method",
        "required_cap_method",
    }
    assert body["production_state"] == "NOT_STARTED"


def test_ready_for_welding_true_when_complete(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="RDYT")
    body = _create(client, ctx, joint_no="J-1", **READY_FIELDS)
    assert body["ready_for_welding"] is True
    assert body["missing_welding_requirements"] == []


# ── PATCH ─────────────────────────────────────────────────────────────────────


def test_patch_updates_and_increments_version(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="PATCH")
    created = _create(client, ctx, joint_no="J-1")
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{created['id']}",
        json={
            "expected_version": 1,
            "updated_by": ctx.worker.id,
            "geometry_type": "TEE",
            "dn_1": "50",
        },
        headers=ctx.headers(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 2
    assert body["geometry_type"] == "TEE"
    assert str(body["dn_1"]) in ("50", "50.0", "50.00000")
    assert body["updated_by"] == ctx.worker.id


def test_patch_optimistic_lock_conflict(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="LOCK")
    created = _create(client, ctx, joint_no="J-1")
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{created['id']}",
        json={
            "expected_version": 99,
            "updated_by": ctx.worker.id,
            "geometry_type": "TEE",
        },
        headers=ctx.headers(),
    )
    assert resp.status_code == 409


def test_patch_recomputes_normalized_joint_no(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="PNORM")
    created = _create(client, ctx, joint_no="J-1")
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{created['id']}",
        json={
            "expected_version": 1,
            "updated_by": ctx.worker.id,
            "joint_no": "  new—no ",
        },
        headers=ctx.headers(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["joint_no"] == "  new—no "
    assert body["joint_no_normalized"] == "NEW-NO"


def test_patch_rejects_protected_fields(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="PROT")
    created = _create(client, ctx, joint_no="J-1")
    for field, value in (
        ("system_code", "HACK"),
        ("project_id", str(uuid4())),
        ("status", "ACTIVE"),
        ("origin_document_revision_id", str(uuid4())),
        ("current_document_revision_id", str(uuid4())),
        ("created_by", 1),
        ("version", 5),
    ):
        resp = client.patch(
            f"{ENGINEERING_URL}/joints/{created['id']}",
            json={
                "expected_version": 1,
                "updated_by": ctx.worker.id,
                field: value,
            },
            headers=ctx.headers(),
        )
        assert resp.status_code == 422, f"{field}: {resp.text}"


def test_patch_coordinates_require_system_422(
    client: TestClient, db: Session
) -> None:
    ctx = Context(db, code="PCOORD")
    created = _create(client, ctx, joint_no="J-1")
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{created['id']}",
        json={
            "expected_version": 1,
            "updated_by": ctx.worker.id,
            "position_x": "3",
        },
        headers=ctx.headers(),
    )
    assert resp.status_code == 422


def test_patch_missing_joint_404(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="PMISS")
    resp = client.patch(
        f"{ENGINEERING_URL}/joints/{uuid4()}",
        json={"expected_version": 1, "updated_by": ctx.worker.id},
        headers=ctx.headers(),
    )
    assert resp.status_code == 404


# ── Отсутствие DELETE ─────────────────────────────────────────────────────────


def test_no_delete_joint_endpoint(client: TestClient, db: Session) -> None:
    ctx = Context(db, code="NODEL")
    created = _create(client, ctx, joint_no="J-1")
    resp = client.delete(
        f"{ENGINEERING_URL}/joints/{created['id']}", headers=ctx.headers()
    )
    assert resp.status_code == 405
