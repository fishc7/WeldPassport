"""Интеграционные тесты WeldOperation Core (Task 8A, ADR-012 / Session 005).

Покрывают: хранение операции, создание черновика, редактирование, просмотр,
список с фильтрами, завершение, отмену черновика, неизменяемость завершённой
операции, разграничение доступа MASTER/FOREMAN по scope и системную нумерацию
внутри Joint. Проверки допуска, WPS, review ОГС, подтверждения сварщика,
корректировок и импорта в Task 8A НЕ входят (Tasks 8B–8E) — тесты подтверждают их
отсутствие, но не моделируют.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engineering.models import DocumentRevision, EngineeringDocument, WeldOperation
from app.hr.models import Worker, WorkerRole
from app.projects.models import Company, Line, Project, ProjectCompany
from app.welding.models import Welder

from .conftest import TEST_COMPANY_ID

ENGINEERING_URL = "/api/v1/engineering"
TODAY = date.today()
PERFORMED_ON = TODAY.isoformat()


# ── Помощники данных ──────────────────────────────────────────────────────────


def _worker(db: Session, suffix: str, *, company_id: int = TEST_COMPANY_ID) -> Worker:
    worker = Worker(
        last_name=f"WO{suffix}",
        first_name="Тест",
        company_id=company_id,
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
    is_active: bool = True,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> WorkerRole:
    role = WorkerRole(
        worker_id=worker_id,
        role_code=role_code,
        scope_type=scope_type,
        scope_id=scope_id,
        is_active=is_active,
        valid_from=valid_from or TODAY,
        valid_to=valid_to,
    )
    db.add(role)
    db.commit()
    return role


def _role_worker(db: Session, suffix: str, role_code: str, **scope) -> Worker:
    w = _worker(db, suffix)
    _assign_role(db, w.id, role_code, **scope)
    return w


def _welder(db: Session, suffix: str, stamp: str) -> Welder:
    worker = _worker(db, f"{suffix}Wkr")
    welder = Welder(worker_id=worker.id, stamp_code=stamp, status="active")
    db.add(welder)
    db.commit()
    db.refresh(welder)
    return welder


class Ctx:
    """Проект/линия/документ/ревизия (APPROVED) + типовые ролевые работники."""

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
        self.document = EngineeringDocument(
            project_id=self.project.id, line_id=self.line.id,
            document_no=f"DOC-{code}", document_type="ISOMETRIC",
            status="APPROVED", created_by=self.creator.id,
        )
        db.add(self.document)
        db.commit()
        db.refresh(self.document)
        self.revision = DocumentRevision(
            engineering_document_id=self.document.id, revision_code="R0",
            status="APPROVED", created_by=self.creator.id,
        )
        db.add(self.revision)
        db.commit()
        db.refresh(self.revision)
        # Ролевые работники: производственные (MASTER/FOREMAN) и ПТО для Joint.
        self.master = _role_worker(db, f"{code}Master", "MASTER")
        self.foreman = _role_worker(db, f"{code}Foreman", "FOREMAN")
        self.pto = _role_worker(db, f"{code}Pto", "PTO_ENGINEER")
        self.welder = _welder(db, f"{code}W", f"ST-{code}")

    def headers(self, worker: Worker) -> dict[str, str]:
        return {"X-User-Id": str(worker.id)}

    def create_joint(self, client: TestClient, joint_no: str = "J-1") -> dict:
        payload = {
            "project_id": str(self.project.id),
            "line_id": str(self.line.id),
            "document_revision_id": str(self.revision.id),
            "joint_no": joint_no,
            "created_by": self.creator.id,
        }
        resp = client.post(
            f"{ENGINEERING_URL}/joints", json=payload,
            headers=self.headers(self.pto),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def op_payload(self, **overrides) -> dict:
        payload = {
            "joint_id": self.joint_id,
            "responsible_worker_id": self.master.id,
            "actual_welder_id": str(self.welder.id),
            "entered_stamp_code": self.welder.stamp_code,
            "weld_stage": "ROOT",
            "welding_method": "RAD",
            "performed_on": PERFORMED_ON,
        }
        payload.update(overrides)
        return payload

    def prepare_joint(self, client: TestClient, joint_no: str = "J-1") -> str:
        self.joint_id = self.create_joint(client, joint_no=joint_no)["id"]
        return self.joint_id


def _create_op(client, ctx: Ctx, worker: Worker | None = None, **overrides):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations",
        json=ctx.op_payload(**overrides),
        headers=ctx.headers(worker or ctx.master),
    )


def _complete(client, ctx: Ctx, op_id: str, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/complete",
        json=body,
        headers=ctx.headers(worker or ctx.master),
    )


def _cancel(client, ctx: Ctx, op_id: str, worker: Worker | None = None, **body):
    return client.post(
        f"{ENGINEERING_URL}/weld-operations/{op_id}/cancel",
        json=body,
        headers=ctx.headers(worker or ctx.master),
    )


def _patch(client, ctx: Ctx, op_id: str, worker: Worker | None = None, **body):
    return client.patch(
        f"{ENGINEERING_URL}/weld-operations/{op_id}",
        json=body,
        headers=ctx.headers(worker or ctx.master),
    )


# ══ A. Позитивные сценарии ════════════════════════════════════════════════════


def test_master_global_creates_operation(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AMG")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lifecycle_status"] == "DRAFT"
    assert body["sequence_no"] == 1
    assert body["record_version"] == 1
    assert body["created_by"] == ctx.master.id


def test_foreman_project_scope_creates(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AFP")
    ctx.prepare_joint(client)
    foreman = _role_worker(
        db, "AFPfp", "FOREMAN", scope_type="PROJECT", scope_id=str(ctx.project.id)
    )
    resp = _create_op(client, ctx, worker=foreman, responsible_worker_id=foreman.id)
    assert resp.status_code == 201, resp.text


def test_master_line_scope_creates(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AML")
    ctx.prepare_joint(client)
    master = _role_worker(
        db, "AMLln", "MASTER", scope_type="LINE", scope_id=str(ctx.line.id)
    )
    resp = _create_op(client, ctx, worker=master, responsible_worker_id=master.id)
    assert resp.status_code == 201, resp.text


def test_sequence_assigned_by_system(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ASEQ")
    ctx.prepare_joint(client)
    first = _create_op(client, ctx, weld_stage="ROOT").json()
    second = _create_op(client, ctx, weld_stage="FILL").json()
    assert first["sequence_no"] == 1
    assert second["sequence_no"] == 2


def test_different_welders_different_stages(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ADIF")
    ctx.prepare_joint(client)
    other = _welder(db, "ADIFo", "ST-ADIF2")
    r1 = _create_op(client, ctx, weld_stage="ROOT")
    r2 = _create_op(
        client, ctx, weld_stage="FILL", actual_welder_id=str(other.id),
        entered_stamp_code=other.stamp_code,
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["actual_welder_id"] != r2.json()["actual_welder_id"]


def test_combined_welding_multiple_operations(client: TestClient, db: Session) -> None:
    """Комбинированная сварка — несколько операций: ROOT+RAD, FILL+RD, CAP+RD."""
    ctx = Ctx(db, "ACMB")
    ctx.prepare_joint(client)
    combos = [("ROOT", "RAD"), ("FILL", "RD"), ("CAP", "RD")]
    seqs = []
    for stage, method in combos:
        r = _create_op(client, ctx, weld_stage=stage, welding_method=method)
        assert r.status_code == 201, r.text
        seqs.append(r.json()["sequence_no"])
    assert seqs == [1, 2, 3]


def test_draft_can_be_edited(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AEDT")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _patch(
        client, ctx, op["id"], expected_record_version=op["record_version"],
        welding_method="RD", operation_note="уточнение",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["welding_method"] == "RD"
    assert body["operation_note"] == "уточнение"
    assert body["record_version"] == op["record_version"] + 1


def test_draft_can_be_completed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ACMP")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _complete(client, ctx, op["id"], expected_record_version=op["record_version"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lifecycle_status"] == "COMPLETED"
    assert body["completed_by"] == ctx.master.id
    assert body["completed_at"] is not None


def test_completed_available_via_get(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "AGET")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    _complete(client, ctx, op["id"])
    got = client.get(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}",
        headers=ctx.headers(ctx.master),
    )
    assert got.status_code == 200
    assert got.json()["lifecycle_status"] == "COMPLETED"


def test_draft_can_be_cancelled(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ACAN")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _cancel(client, ctx, op["id"], reason="ошибочная запись")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lifecycle_status"] == "CANCELLED"
    assert body["cancellation_reason"] == "ошибочная запись"
    assert body["cancelled_by"] == ctx.master.id


def test_list_filtered_by_joint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ALJ")
    ctx.prepare_joint(client)
    _create_op(client, ctx)
    resp = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"joint_id": ctx.joint_id},
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["joint_id"] == ctx.joint_id


def test_list_filtered_by_welder_and_status(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ALWS")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    _complete(client, ctx, op["id"])
    by_welder = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"actual_welder_id": str(ctx.welder.id)},
        headers=ctx.headers(ctx.master),
    ).json()
    assert by_welder["total"] == 1
    by_status = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"joint_id": ctx.joint_id, "lifecycle_status": "COMPLETED"},
        headers=ctx.headers(ctx.master),
    ).json()
    assert by_status["total"] == 1
    empty = client.get(
        f"{ENGINEERING_URL}/weld-operations",
        params={"joint_id": ctx.joint_id, "lifecycle_status": "DRAFT"},
        headers=ctx.headers(ctx.master),
    ).json()
    assert empty["total"] == 0


def test_list_by_joint_convenience_endpoint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "ALBC")
    ctx.prepare_joint(client)
    _create_op(client, ctx)
    resp = client.get(
        f"{ENGINEERING_URL}/joints/{ctx.joint_id}/weld-operations",
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_null_wps_does_not_block(client: TestClient, db: Session) -> None:
    """Task 8B не входит: nullable actual_wps_id не мешает создать и завершить."""
    ctx = Ctx(db, "AWPS")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx, actual_wps_id=None).json()
    assert op["actual_wps_id"] is None
    resp = _complete(client, ctx, op["id"])
    assert resp.status_code == 200, resp.text


def test_mismatched_stamp_does_not_block(client: TestClient, db: Session) -> None:
    """Task 8B/8C не входят: несовпадение клейма не блокирует завершение."""
    ctx = Ctx(db, "ASTP")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx, entered_stamp_code="OTHER-999").json()
    # Снимок профильного клейма сохранён отдельно от введённого; сравнение НЕ ведётся.
    assert op["entered_stamp_code"] == "OTHER-999"
    assert op["profile_stamp_snapshot"] == ctx.welder.stamp_code
    resp = _complete(client, ctx, op["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "COMPLETED"


def test_no_admission_check_blocks_completion(client: TestClient, db: Session) -> None:
    """Task 8B не входит: отсутствие допуска сварщика не блокирует завершение."""
    ctx = Ctx(db, "AADM")
    ctx.prepare_joint(client)
    # У сварщика нет ни одной записи допуска (welder_admissions) — операция всё равно
    # создаётся и завершается: квалификационная логика Task 8A не выполняется.
    op = _create_op(client, ctx).json()
    resp = _complete(client, ctx, op["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "COMPLETED"


# ══ B. Негативные сценарии ════════════════════════════════════════════════════


def test_no_role_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BNOR")
    ctx.prepare_joint(client)
    plain = _worker(db, "BNORp")  # активный работник без ролей
    resp = _create_op(client, ctx, worker=plain)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ROLE_DENIED"


def test_foreign_project_scope_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BFPR")
    ctx.prepare_joint(client)
    foreign = _role_worker(
        db, "BFPRf", "MASTER", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = _create_op(client, ctx, worker=foreign, responsible_worker_id=foreign.id)
    assert resp.status_code == 403


def test_foreign_line_scope_forbidden(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BFLN")
    ctx.prepare_joint(client)
    foreign = _role_worker(
        db, "BFLNf", "MASTER", scope_type="LINE", scope_id=str(uuid4())
    )
    resp = _create_op(client, ctx, worker=foreign, responsible_worker_id=foreign.id)
    assert resp.status_code == 403


def test_missing_joint_returns_404(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BJNF")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx, joint_id=str(uuid4()))
    assert resp.status_code == 404


def test_missing_welder_returns_404(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BWNF")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx, actual_welder_id=str(uuid4()))
    assert resp.status_code == 404


def test_responsible_without_role_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BRNR")
    ctx.prepare_joint(client)
    plain = _worker(db, "BRNRp")  # активный работник без ролей
    resp = _create_op(client, ctx, responsible_worker_id=plain.id)
    assert resp.status_code == 403


def test_responsible_wrong_scope_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BRWS")
    ctx.prepare_joint(client)
    other = _role_worker(
        db, "BRWSo", "FOREMAN", scope_type="PROJECT", scope_id=str(uuid4())
    )
    resp = _create_op(client, ctx, responsible_worker_id=other.id)
    assert resp.status_code == 403


def test_invalid_stage_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BSTG")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx, weld_stage="MIDDLE")
    assert resp.status_code == 422


def test_empty_method_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BMTD")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx, welding_method="   ")
    assert resp.status_code == 422


def test_finished_before_started_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BTIM")
    ctx.prepare_joint(client)
    resp = _create_op(
        client, ctx,
        started_at="2026-07-12T10:00:00+00:00",
        finished_at="2026-07-12T09:00:00+00:00",
    )
    assert resp.status_code == 422


def test_client_cannot_set_sequence_no(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BSEQ")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx, sequence_no=99)
    assert resp.status_code == 422


def test_client_cannot_create_completed(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCMP")
    ctx.prepare_joint(client)
    resp = _create_op(client, ctx, lifecycle_status="COMPLETED")
    assert resp.status_code == 422


def test_patch_completed_returns_409(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BPCM")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    completed = _complete(client, ctx, op["id"]).json()
    resp = _patch(
        client, ctx, op["id"],
        expected_record_version=completed["record_version"], welding_method="RD",
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "WELD_OPERATION_COMPLETED"


def test_double_complete_returns_409(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDCM")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    _complete(client, ctx, op["id"])
    resp = _complete(client, ctx, op["id"])
    assert resp.status_code == 409


def test_cancel_completed_returns_409(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCCM")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    _complete(client, ctx, op["id"])
    resp = _cancel(client, ctx, op["id"], reason="поздно")
    assert resp.status_code == 409


def test_cancel_without_reason_rejected(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BCNR")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _cancel(client, ctx, op["id"], reason="   ")
    assert resp.status_code == 422


def test_no_physical_delete_endpoint(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BDEL")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = client.delete(
        f"{ENGINEERING_URL}/weld-operations/{op['id']}",
        headers=ctx.headers(ctx.master),
    )
    assert resp.status_code == 405


def test_wrong_record_version_returns_409(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "BVER")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    resp = _patch(client, ctx, op["id"], expected_record_version=99, welding_method="RD")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "RECORD_VERSION_CONFLICT"


# ══ C. Конкурентная нумерация ═════════════════════════════════════════════════


def test_unique_joint_sequence_enforced_by_db(client: TestClient, db: Session) -> None:
    """Уникальность (joint_id, sequence_no) гарантируется БД (§19.3).

    Прямая вставка дубля номера в тот же Joint отклоняется ограничением уникальности
    вне зависимости от прикладной логики выделения номера."""
    ctx = Ctx(db, "CUNQ")
    ctx.prepare_joint(client)
    op = _create_op(client, ctx).json()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                """
                INSERT INTO engineering.weld_operations
                    (id, joint_id, sequence_no, lifecycle_status, weld_stage,
                     welding_method, performed_on, responsible_worker_id,
                     record_version, created_by, updated_by)
                VALUES (gen_random_uuid(), CAST(:jid AS uuid), :seq, 'DRAFT', 'FILL',
                        'RD', CAST(:pon AS date), :rw, 1, :cb, :cb)
                """
            ),
            {
                "jid": ctx.joint_id,
                "seq": op["sequence_no"],
                "pon": PERFORMED_ON,
                "rw": ctx.master.id,
                "cb": ctx.master.id,
            },
        )
    db.rollback()


def test_sequential_numbers_are_gap_free(client: TestClient, db: Session) -> None:
    ctx = Ctx(db, "CSEQ")
    ctx.prepare_joint(client)
    numbers = [
        _create_op(client, ctx, weld_stage=s).json()["sequence_no"]
        for s in ("ROOT", "FILL", "CAP", "BACK_WELD", "TACK")
    ]
    assert numbers == [1, 2, 3, 4, 5]
