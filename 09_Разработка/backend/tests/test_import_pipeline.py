"""Интеграционные тесты контура импорта XLSX (Task 8E).

Покрывают: разбор/структурные ошибки, сопоставление Joint, дубликаты операций,
группы и атомарное применение, права (OGS_ENGINEER vs CHIEF_WELDER), идемпотентность,
провенанс и историю статусов.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engineering import import_parse as ip
from app.engineering.models import DocumentRevision, EngineeringDocument
from app.engineering.schemas import JointCreate
from app.engineering.services import EngineeringService
from app.hr.models import Worker, WorkerRole
from app.projects.models import Line, Project
from app.welding.models import Welder

from tests.conftest import TEST_COMPANY_ID

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMPORTS = "/api/v1/engineering/imports"


@dataclass
class Ctx:
    project_id: str
    line_no: str
    iso_no: str
    rev_code: str
    revision_id: str
    stamp: str
    engineer_id: int
    chief_id: int
    outsider_id: int


def _worker(db: Session, suffix: str) -> Worker:
    w = Worker(
        last_name=f"Имп{suffix}", first_name="Тест", company_id=TEST_COMPANY_ID,
        employment_status="active", hire_date=date.today(),
    )
    db.add(w)
    db.flush()
    return w


def _role(db: Session, worker_id: int, code: str) -> None:
    db.add(WorkerRole(
        worker_id=worker_id, role_code=code, scope_type="GLOBAL",
        is_active=True, valid_from=date.today(),
    ))
    db.flush()


@pytest.fixture
def ctx(db: Session) -> Ctx:
    engineer = _worker(db, "Eng")
    chief = _worker(db, "Chief")
    outsider = _worker(db, "Out")
    _role(db, engineer.id, "OGS_ENGINEER")
    _role(db, chief.id, "CHIEF_WELDER")

    project = Project(code="IMP-P1", name="Импорт проект", status="active",
                      created_by=engineer.id)
    db.add(project)
    db.flush()
    line = Line(project_id=project.id, line_no="L-1", status="active",
                created_by=engineer.id)
    db.add(line)
    document = EngineeringDocument(
        project_id=project.id, document_no="ISO-1", document_type="ISOMETRIC",
        status="APPROVED", created_by=engineer.id, approved_by=engineer.id,
    )
    db.add(document)
    db.flush()
    revision = DocumentRevision(
        engineering_document_id=document.id, revision_code="R1", status="APPROVED",
        created_by=engineer.id, approved_by=engineer.id,
    )
    db.add(revision)
    db.add(Welder(worker_id=engineer.id, stamp_code="W-IMP-1", status="active"))
    db.commit()
    return Ctx(
        project_id=str(project.id), line_no="L-1", iso_no="ISO-1", rev_code="R1",
        revision_id=str(revision.id), stamp="W-IMP-1",
        engineer_id=engineer.id, chief_id=chief.id, outsider_id=outsider.id,
    )


def _row(ctx: Ctx, joint_no: str, stage: str = "ROOT", **over) -> dict:
    base = {
        "project_code": "IMP-P1", "line_code": ctx.line_no, "isometric_no": ctx.iso_no,
        "revision_code": ctx.rev_code, "joint_no": joint_no, "weld_stage": stage,
        "welding_method": "141", "welder_stamp_code": ctx.stamp,
        "performed_on": "2026-07-10",
    }
    base.update(over)
    return base


def _hdr(uid: int, idem: str | None = None) -> dict:
    h = {"X-User-Id": str(uid)}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def _upload(client: TestClient, ctx: Ctx, rows, uid=None, idem=None, data=None, **wb_kwargs):
    uid = uid if uid is not None else ctx.engineer_id
    # openpyxl не детерминирован по байтам (метки времени zip): для проверки
    # идемпотентности загрузки переиспользуем один и тот же массив байт.
    if data is None:
        data = ip.build_workbook(rows, **wb_kwargs)
    return client.post(
        IMPORTS,
        data={"project_id": ctx.project_id},
        files={"file": ("import.xlsx", data, MIME)},
        headers=_hdr(uid, idem),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Разбор и структурные ошибки
# ══════════════════════════════════════════════════════════════════════════════
def test_upload_valid_creates_staging_and_group(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-1", "ROOT"), _row(ctx, "J-1", "FILL")])
    assert resp.status_code == 201, resp.text
    session = resp.json()
    assert session["status"] == "UNDER_REVIEW"
    sid = session["id"]

    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    assert len(rows["items"]) == 2
    assert all(r["status"] == "READY" for r in rows["items"])

    groups = client.get(f"{IMPORTS}/{sid}/groups", headers=_hdr(ctx.engineer_id)).json()
    assert len(groups["items"]) == 1
    g = groups["items"][0]
    assert g["target_type"] == "NEW_JOINT"
    assert g["status"] == "READY"


def test_missing_required_column_parse_failed(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-1")], omit_columns=("joint_no",))
    assert resp.status_code == 201
    sid = resp.json()["id"]
    assert resp.json()["status"] == "PARSE_FAILED"
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    assert rows["items"] == []
    attempts = client.get(
        f"{IMPORTS}/{sid}/parse-attempts", headers=_hdr(ctx.engineer_id)
    ).json()
    assert attempts[0]["error_code"] == "IMPORT_MISSING_REQUIRED_COLUMN"


def test_unsupported_template_version_parse_failed(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-1")], template_version="9.9")
    assert resp.json()["status"] == "PARSE_FAILED"


def test_partial_row_is_validation_error(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-1", welding_method="")])
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    assert rows["items"][0]["status"] == "VALIDATION_ERROR"
    groups = client.get(f"{IMPORTS}/{sid}/groups", headers=_hdr(ctx.engineer_id)).json()
    assert groups["items"][0]["status"] == "BLOCKED"
    assert "ROW_VALIDATION_ERROR" in groups["items"][0]["block_reasons"]


def test_empty_rows_ignored_but_counted(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-1"), {}, {}])
    sid = resp.json()["id"]
    attempts = client.get(
        f"{IMPORTS}/{sid}/parse-attempts", headers=_hdr(ctx.engineer_id)
    ).json()
    assert attempts[0]["rows_empty"] == 2
    assert attempts[0]["rows_created"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Сопоставление Joint
# ══════════════════════════════════════════════════════════════════════════════
def _make_existing_joint(db: Session, ctx: Ctx, joint_no: str) -> str:
    eng = EngineeringService(db)
    from uuid import UUID

    joint = eng.create_joint(JointCreate(
        project_id=UUID(ctx.project_id),
        line_id=db.query(Line).filter(Line.line_no == ctx.line_no).first().id,
        document_revision_id=UUID(ctx.revision_id),
        joint_no=joint_no,
        created_by=ctx.engineer_id,
    ))
    db.commit()
    return str(joint.id)


def test_exact_match_links_existing_joint(client: TestClient, db: Session, ctx: Ctx):
    joint_id = _make_existing_joint(db, ctx, "J-EX")
    resp = _upload(client, ctx, [_row(ctx, "J-EX")])
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    r = rows["items"][0]
    assert r["match_classification"] == "EXACT_MATCH"
    assert r["matched_joint_id"] == joint_id
    assert r["status"] == "READY"
    groups = client.get(f"{IMPORTS}/{sid}/groups", headers=_hdr(ctx.engineer_id)).json()
    assert groups["items"][0]["target_type"] == "EXISTING_JOINT"


def test_revision_mismatch_is_conflict(client: TestClient, db: Session, ctx: Ctx):
    _make_existing_joint(db, ctx, "J-CONF")
    resp = _upload(client, ctx, [_row(ctx, "J-CONF", revision_code="R2")])
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    r = rows["items"][0]
    assert r["status"] == "MATCH_CONFLICT"
    assert "REVISION_MISMATCH" in r["conflict_codes"]


def test_no_match_creates_new_joint_group(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-NEW")])
    sid = resp.json()["id"]
    groups = client.get(f"{IMPORTS}/{sid}/groups", headers=_hdr(ctx.engineer_id)).json()
    assert groups["items"][0]["target_type"] == "NEW_JOINT"
    assert groups["items"][0]["status"] == "READY"


# ══════════════════════════════════════════════════════════════════════════════
# Дубликаты WeldOperation
# ══════════════════════════════════════════════════════════════════════════════
def test_intra_file_full_duplicate(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-D"), _row(ctx, "J-D")])
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    statuses = sorted(r["status"] for r in rows["items"])
    assert statuses == ["DUPLICATE", "READY"]
    dup = next(r for r in rows["items"] if r["status"] == "DUPLICATE")
    assert dup["duplicate_type"] == "INTRA_FILE_DUPLICATE"


# ══════════════════════════════════════════════════════════════════════════════
# Полное применение, провенанс, права
# ══════════════════════════════════════════════════════════════════════════════
def _drive_to_apply(client: TestClient, ctx: Ctx, sid: str):
    ready = client.post(
        f"{IMPORTS}/{sid}/ready-for-apply", json={}, headers=_hdr(ctx.engineer_id)
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY_FOR_APPLY"
    return client.post(f"{IMPORTS}/{sid}/apply", json={}, headers=_hdr(ctx.chief_id))


def test_full_apply_creates_joint_operation_and_provenance(
    client: TestClient, ctx: Ctx
):
    resp = _upload(client, ctx, [_row(ctx, "J-APPLY", "ROOT")])
    sid = resp.json()["id"]
    applied = _drive_to_apply(client, ctx, sid)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "COMPLETED"

    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    assert rows["items"][0]["status"] == "APPLIED"

    prov = client.get(f"{IMPORTS}/{sid}/provenance", headers=_hdr(ctx.engineer_id)).json()
    link_types = sorted(p["link_type"] for p in prov)
    target_types = sorted(p["target_type"] for p in prov)
    assert link_types == ["CREATED", "CREATED"]
    assert target_types == ["JOINT", "WELD_OPERATION"]


def test_apply_requires_chief(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-A2")])
    sid = resp.json()["id"]
    client.post(f"{IMPORTS}/{sid}/ready-for-apply", json={}, headers=_hdr(ctx.engineer_id))
    denied = client.post(f"{IMPORTS}/{sid}/apply", json={}, headers=_hdr(ctx.engineer_id))
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "IMPORT_APPLY_ROLE_DENIED"


def test_upload_denied_without_role(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-X")], uid=ctx.outsider_id)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "IMPORT_ROLE_DENIED"


def test_existing_operation_idempotent_skip(client: TestClient, ctx: Ctx):
    # Первый импорт создаёт операцию.
    r1 = _upload(client, ctx, [_row(ctx, "J-IDEM", "ROOT")])
    sid1 = r1.json()["id"]
    assert _drive_to_apply(client, ctx, sid1).json()["status"] == "COMPLETED"
    # Повторный импорт той же строки → дубль существующей операции → пропуск.
    r2 = _upload(client, ctx, [_row(ctx, "J-IDEM", "ROOT")])
    sid2 = r2.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid2}/rows", headers=_hdr(ctx.engineer_id)).json()
    r = rows["items"][0]
    assert r["status"] == "SKIPPED_DUPLICATE"
    assert r["duplicate_type"] == "EXISTING_OPERATION_DUPLICATE"


# ══════════════════════════════════════════════════════════════════════════════
# Разрешение конфликтов
# ══════════════════════════════════════════════════════════════════════════════
def test_reject_conflict_row(client: TestClient, db: Session, ctx: Ctx):
    _make_existing_joint(db, ctx, "J-REJ")
    resp = _upload(client, ctx, [_row(ctx, "J-REJ", revision_code="R2")])
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    row_id = rows["items"][0]["id"]
    rej = client.post(
        f"{IMPORTS}/rows/{row_id}/reject", json={"comment": "не нужен"},
        headers=_hdr(ctx.engineer_id),
    )
    assert rej.status_code == 200
    assert rej.json()["status"] == "REJECTED"


def test_resolve_link_existing_joint(client: TestClient, db: Session, ctx: Ctx):
    joint_id = _make_existing_joint(db, ctx, "J-LINK")
    resp = _upload(client, ctx, [_row(ctx, "J-LINK", revision_code="R2")])
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    row_id = rows["items"][0]["id"]
    res = client.post(
        f"{IMPORTS}/rows/{row_id}/resolutions",
        json={"resolution_type": "LINK_EXISTING_JOINT", "selected_joint_id": joint_id,
              "comment": "тот же стык"},
        headers=_hdr(ctx.engineer_id),
    )
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "RESOLVED_LINK_EXISTING"
    assert res.json()["matched_joint_id"] == joint_id


# ══════════════════════════════════════════════════════════════════════════════
# Идемпотентность
# ══════════════════════════════════════════════════════════════════════════════
def test_apply_idempotent_replay(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-APIDEM")])
    sid = resp.json()["id"]
    client.post(f"{IMPORTS}/{sid}/ready-for-apply", json={}, headers=_hdr(ctx.engineer_id))
    a1 = client.post(f"{IMPORTS}/{sid}/apply", json={}, headers=_hdr(ctx.chief_id, "apply-1"))
    assert a1.json()["status"] == "COMPLETED"
    a2 = client.post(f"{IMPORTS}/{sid}/apply", json={}, headers=_hdr(ctx.chief_id, "apply-1"))
    assert a2.status_code == 200
    attempts = client.get(
        f"{IMPORTS}/{sid}/apply-attempts", headers=_hdr(ctx.engineer_id)
    ).json()
    assert len(attempts) == 1  # повтор не создал новую попытку


def test_upload_idempotent_same_key_same_file(client: TestClient, ctx: Ctx):
    data = ip.build_workbook([_row(ctx, "J-UPIDEM")])
    r1 = _upload(client, ctx, None, idem="up-1", data=data)
    r2 = _upload(client, ctx, None, idem="up-1", data=data)
    assert r1.status_code == 201, r1.text
    assert r1.json()["id"] == r2.json()["id"]


def test_upload_same_key_different_payload_conflict(client: TestClient, ctx: Ctx):
    _upload(client, ctx, [_row(ctx, "J-C1")], idem="dup-key")
    r2 = _upload(client, ctx, [_row(ctx, "J-C2")], idem="dup-key")
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"


# ══════════════════════════════════════════════════════════════════════════════
# История статусов и отмена
# ══════════════════════════════════════════════════════════════════════════════
def test_status_history_records_transitions(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-HIST")])
    sid = resp.json()["id"]
    events = client.get(
        f"{IMPORTS}/{sid}/status-events?entity_type=SESSION",
        headers=_hdr(ctx.engineer_id),
    ).json()
    seq = [e["new_status"] for e in events]
    assert seq[:3] == ["UPLOADED", "PARSING", "UNDER_REVIEW"]


def test_cancel_session_before_apply(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-CAN")])
    sid = resp.json()["id"]
    cancelled = client.post(
        f"{IMPORTS}/{sid}/cancel", json={"comment": "отмена"},
        headers=_hdr(ctx.engineer_id),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    # После отмены изменения запрещены.
    again = client.post(
        f"{IMPORTS}/{sid}/ready-for-apply", json={}, headers=_hdr(ctx.engineer_id)
    )
    assert again.status_code == 409


# ══════════════════════════════════════════════════════════════════════════════
# Parse: повреждённый файл, неизвестные колонки, повторный разбор
# ══════════════════════════════════════════════════════════════════════════════
def test_corrupted_xlsx_parse_failed(client: TestClient, ctx: Ctx):
    resp = client.post(
        IMPORTS,
        data={"project_id": ctx.project_id},
        files={"file": ("import.xlsx", b"not-a-zip", MIME)},
        headers=_hdr(ctx.engineer_id),
    )
    assert resp.status_code == 201
    sid = resp.json()["id"]
    assert resp.json()["status"] == "PARSE_FAILED"
    attempts = client.get(
        f"{IMPORTS}/{sid}/parse-attempts", headers=_hdr(ctx.engineer_id)
    ).json()
    assert attempts[0]["error_code"] == "IMPORT_FILE_CORRUPT"


def test_unknown_columns_are_warning_only(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-UNK")], extra_columns=("extra_col",))
    sid = resp.json()["id"]
    rows = client.get(f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)).json()
    row = rows["items"][0]
    assert row["status"] == "READY"
    # Неизвестная колонка есть в исходном снимке, но не в нормализованных полях.
    assert "extra_col" in row["raw_snapshot"]
    assert "extra_col" not in row["normalized_data"]


def test_reparse_after_parse_failed_creates_new_attempt(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-RP")], template_version="9.9")
    sid = resp.json()["id"]
    assert resp.json()["status"] == "PARSE_FAILED"
    rep = client.post(f"{IMPORTS}/{sid}/reparse", headers=_hdr(ctx.engineer_id))
    assert rep.status_code == 200
    attempts = client.get(
        f"{IMPORTS}/{sid}/parse-attempts", headers=_hdr(ctx.engineer_id)
    ).json()
    assert len(attempts) == 2


def test_reparse_not_allowed_when_staged(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-RP2")])
    sid = resp.json()["id"]  # UNDER_REVIEW со staging
    rep = client.post(f"{IMPORTS}/{sid}/reparse", headers=_hdr(ctx.engineer_id))
    assert rep.status_code == 409
    assert rep.json()["detail"]["code"] == "IMPORT_REPARSE_NOT_ALLOWED"


# ══════════════════════════════════════════════════════════════════════════════
# Optimistic locking, неизменяемость, комментарии
# ══════════════════════════════════════════════════════════════════════════════
def test_optimistic_locking_row_version(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-OL")])
    sid = resp.json()["id"]
    row_id = client.get(
        f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)
    ).json()["items"][0]["id"]
    bad = client.patch(
        f"{IMPORTS}/rows/{row_id}",
        json={"fields": {"operation_note": "x"}, "expected_row_version": 999},
        headers=_hdr(ctx.engineer_id),
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "IMPORT_ROW_VERSION_CONFLICT"


def test_edit_requires_comment_for_key_field(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-CM")])
    sid = resp.json()["id"]
    row_id = client.get(
        f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)
    ).json()["items"][0]["id"]
    no_comment = client.patch(
        f"{IMPORTS}/rows/{row_id}",
        json={"fields": {"joint_no": "J-CM2"}},
        headers=_hdr(ctx.engineer_id),
    )
    assert no_comment.status_code == 422
    assert no_comment.json()["detail"]["code"] == "IMPORT_COMMENT_REQUIRED"


def test_edit_rematches_and_records_change(client: TestClient, db: Session, ctx: Ctx):
    joint_id = _make_existing_joint(db, ctx, "J-RM")
    resp = _upload(client, ctx, [_row(ctx, "J-OTHER")])
    sid = resp.json()["id"]
    row_id = client.get(
        f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)
    ).json()["items"][0]["id"]
    edited = client.patch(
        f"{IMPORTS}/rows/{row_id}",
        json={"fields": {"joint_no": "J-RM"}, "comment": "исправление номера"},
        headers=_hdr(ctx.engineer_id),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["matched_joint_id"] == joint_id
    assert edited.json()["status"] == "READY"
    changes = client.get(
        f"{IMPORTS}/rows/{row_id}/changes", headers=_hdr(ctx.engineer_id)
    ).json()
    assert any(c["field"] == "joint_no" and c["comment"] for c in changes)


def test_applied_objects_are_immutable(client: TestClient, ctx: Ctx):
    resp = _upload(client, ctx, [_row(ctx, "J-IMM")])
    sid = resp.json()["id"]
    row_id = client.get(
        f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)
    ).json()["items"][0]["id"]
    assert _drive_to_apply(client, ctx, sid).json()["status"] == "COMPLETED"
    edit = client.patch(
        f"{IMPORTS}/rows/{row_id}",
        json={"fields": {"operation_note": "x"}},
        headers=_hdr(ctx.engineer_id),
    )
    assert edit.status_code == 409


# ══════════════════════════════════════════════════════════════════════════════
# История решений (supersede) и provenance matched
# ══════════════════════════════════════════════════════════════════════════════
def test_resolution_history_supersede(client: TestClient, db: Session, ctx: Ctx):
    joint_id = _make_existing_joint(db, ctx, "J-RES")
    resp = _upload(client, ctx, [_row(ctx, "J-RES", revision_code="R2")])
    sid = resp.json()["id"]
    row_id = client.get(
        f"{IMPORTS}/{sid}/rows", headers=_hdr(ctx.engineer_id)
    ).json()["items"][0]["id"]
    client.post(
        f"{IMPORTS}/rows/{row_id}/resolutions",
        json={"resolution_type": "LINK_EXISTING_JOINT", "selected_joint_id": joint_id,
              "comment": "первое"},
        headers=_hdr(ctx.engineer_id),
    )
    client.post(
        f"{IMPORTS}/rows/{row_id}/resolutions",
        json={"resolution_type": "REJECT_ROW", "comment": "передумал"},
        headers=_hdr(ctx.engineer_id),
    )
    res = client.get(
        f"{IMPORTS}/rows/{row_id}/resolutions", headers=_hdr(ctx.engineer_id)
    ).json()
    assert len(res) == 2
    first, second = res[0], res[1]
    assert first["is_superseded"] is True
    assert second["is_superseded"] is False
    assert second["supersedes_resolution_id"] == first["id"]


def test_provenance_matched_existing(client: TestClient, db: Session, ctx: Ctx):
    _make_existing_joint(db, ctx, "J-PM")
    resp = _upload(client, ctx, [_row(ctx, "J-PM")])
    sid = resp.json()["id"]
    assert _drive_to_apply(client, ctx, sid).json()["status"] == "COMPLETED"
    prov = client.get(
        f"{IMPORTS}/{sid}/provenance", headers=_hdr(ctx.engineer_id)
    ).json()
    assert sorted(p["link_type"] for p in prov) == ["CREATED", "MATCHED_EXISTING"]
    matched = next(p for p in prov if p["link_type"] == "MATCHED_EXISTING")
    assert matched["target_type"] == "JOINT"


# ══════════════════════════════════════════════════════════════════════════════
# Частичное применение с FAILED-группой и восстановление
# ══════════════════════════════════════════════════════════════════════════════
def test_partial_apply_with_failed_group_and_recovery(
    client: TestClient, ctx: Ctx
):
    resp = _upload(client, ctx, [
        _row(ctx, "J-OK"),
        _row(ctx, "J-BAD", isometric_no="NONEXISTENT-ISO"),
    ])
    sid = resp.json()["id"]
    result = _drive_to_apply(client, ctx, sid)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "PARTIALLY_APPLIED_WITH_FAILURES"

    groups = client.get(
        f"{IMPORTS}/{sid}/groups", headers=_hdr(ctx.engineer_id)
    ).json()["items"]
    statuses = sorted(g["status"] for g in groups)
    assert statuses == ["APPLIED", "FAILED"]
    failed = next(g for g in groups if g["status"] == "FAILED")
    assert "NON_RETRYABLE_FAILURE" in failed["block_reasons"]

    # Независимость транзакций: успешная группа применена, у неё есть провенанс.
    attempts = client.get(
        f"{IMPORTS}/{sid}/apply-attempts", headers=_hdr(ctx.engineer_id)
    ).json()
    assert attempts[0]["groups_applied"] == 1
    assert attempts[0]["groups_failed"] == 1

    # Восстановление: инженер правит staging, chief возвращает группу в READY.
    failed_row = client.get(
        f"{IMPORTS}/{sid}/rows?group_id={failed['id']}",
        headers=_hdr(ctx.engineer_id),
    ).json()["items"][0]
    fixed = client.patch(
        f"{IMPORTS}/rows/{failed_row['id']}",
        json={"fields": {"isometric_no": "ISO-1"}, "comment": "исправлена изометрия"},
        headers=_hdr(ctx.engineer_id),
    )
    assert fixed.status_code == 200, fixed.text

    # Инженер не может вернуть FAILED-группу.
    eng_return = client.post(
        f"{IMPORTS}/groups/{failed['id']}/return-after-failed",
        json={"comment": "готово"}, headers=_hdr(ctx.engineer_id),
    )
    assert eng_return.status_code == 403

    chief_return = client.post(
        f"{IMPORTS}/groups/{failed['id']}/return-after-failed",
        json={"comment": "проверено"}, headers=_hdr(ctx.chief_id),
    )
    assert chief_return.status_code == 200, chief_return.text
    assert chief_return.json()["status"] == "READY"

    # Повторное применение завершает сессию.
    client.post(
        f"{IMPORTS}/{sid}/ready-for-apply", json={}, headers=_hdr(ctx.engineer_id)
    )
    final = client.post(f"{IMPORTS}/{sid}/apply", json={}, headers=_hdr(ctx.chief_id))
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "COMPLETED"
