# AS-02 QualityDecision RBAC Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** закрыть person-level SoD, сохранить доказуемый authorization snapshot и
выявлять dual-role governance warning для `QualityDecision`.

**Architecture:** ADR-028 сохраняет OGS → OTK authority ADR-027. Общий permission resolver
возвращает конкретный `AuthorizationGrant`, а `QualityDecision` хранит отправителя текущего
review-cycle и запрещает ему `RETURN`/`DECIDE`. Общий audit получает отдельный JSONB
authorization context без массовой миграции остальных модулей.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Pydantic v2,
pytest.

**Execution Prompt:**
`docs/project/TASK_AS_02_QUALITY_DECISION_RBAC_IMPLEMENTATION_PROMPT.md`.

## Global Constraints

- Канон: `docs/project/ADR-028-quality-decision-rbac-consolidation.md`.
- Не изменять revisions 25/26; новая revision следует за
  `20260724_26_qd_idempotency`.
- Не использовать SQLite; runtime и DB acceptance — только PostgreSQL.
- Не расширять роли и не добавлять `CHIEF_WELDER` fallback.
- `COMPANY`/`SITE` не дают write-authority `QualityDecision`.
- Не создавать глобальный HR role-conflict blocker или новый governance endpoint.
- Не менять URL, request body, lifecycle, result values или пять event types.
- Исторический scope не выдумывать; использовать `LEGACY_AUTHORIZATION_SNAPSHOT`.
- Этапы принимаются отдельно; не переходить к следующему gate без review.
- Commit и push — только по отдельному подтверждению владельца.

## File map

**Create**

- `09_Разработка/backend/migrations/versions/20260724_27_qd_rbac_sod.py` — correcting
  migration.
- `09_Разработка/backend/migration_contract_tests/test_qd_rbac_sod_migration.py` —
  offline/AST migration contract.
- `09_Разработка/backend/tests/test_quality_decision_rbac_domain.py` — pure SoD and ORM
  metadata contracts without PostgreSQL.
- `09_Разработка/backend/tests/test_authorization_grants.py` — isolated resolver,
  evidence and deterministic-selection contracts without application bootstrap.

**Modify**

- `09_Разработка/backend/app/shared/permissions.py` — `AuthorizationGrant`, resolver и
  deterministic selection.
- `09_Разработка/backend/app/quality/quality_decision_models.py` — current-cycle
  submitter и DB metadata constraint.
- `09_Разработка/backend/app/quality/execution_models.py` — authorization JSONB.
- `09_Разработка/backend/app/quality/quality_decision_workflow.py` — SoD error/pure rule.
- `09_Разработка/backend/app/quality/quality_decision_services.py` — grant orchestration,
  SoD, snapshots and warnings.
- `09_Разработка/backend/app/quality/quality_decision_schemas.py` — additive read fields.
- `09_Разработка/backend/tests/test_quality_decision_services.py` — lifecycle/audit/
  idempotency/concurrency.
- `09_Разработка/backend/tests/test_quality_decision_api.py` — HTTP contract.
- `09_Разработка/backend/migration_contract_tests/test_migration_graph.py` — expected head.
- `09_Разработка/backend/migration_contract_tests/test_alembic_cli_contract.py` —
  expected head.
- Canonical project documents — completion evidence only after final acceptance.

---

### Task 1: Domain Model and pure SoD rule

**Files:**

- Modify: `09_Разработка/backend/app/quality/quality_decision_models.py`
- Modify: `09_Разработка/backend/app/quality/execution_models.py`
- Modify: `09_Разработка/backend/app/quality/quality_decision_workflow.py`
- Create: `09_Разработка/backend/tests/test_quality_decision_rbac_domain.py`

**Interfaces:**

- Produces:
  `QualityDecision.review_submitted_by_worker_id: int | None`,
  `QualityAuditEvent.authorization_context: dict | None`,
  `validate_review_separation(actor_worker_id: int,
  review_submitted_by_worker_id: int | None) -> str | None`.

- [x] **Step 1: add failing metadata tests**

```python
def test_quality_decision_has_review_submitter_and_state_constraint():
    table = QualityDecision.__table__
    assert table.c.review_submitted_by_worker_id.nullable is True
    sql = " ".join(str(c.sqltext) for c in table.constraints)
    assert "review_submitted_by_worker_id" in sql


def test_quality_audit_event_has_authorization_context():
    column = QualityAuditEvent.__table__.c.authorization_context
    assert column.nullable is True
    assert isinstance(column.type, JSONB)
```

- [x] **Step 2: add failing pure SoD tests**

```python
def test_review_submitter_cannot_review_own_cycle():
    assert qdw.validate_review_separation(42, 42) == qdw.QD_SAME_ACTOR_REVIEW


def test_different_worker_can_review_cycle():
    assert qdw.validate_review_separation(43, 42) is None
```

- [x] **Step 3: run only the new pure/metadata tests**

Run from `09_Разработка/backend`:

```powershell
python -m pytest tests/test_quality_decision_rbac_domain.py -q
```

Expected: FAIL because the fields/rule do not exist.

- [x] **Step 4: implement the minimal domain contract**

Add the nullable integer field and model CHECK:

```python
review_submitted_by_worker_id: Mapped[int | None] = mapped_column(Integer)
```

```python
CheckConstraint(
    "(status = 'DRAFT' AND review_submitted_by_worker_id IS NULL) OR "
    "(status IN ('UNDER_REVIEW', 'DECIDED', 'SUPERSEDED') "
    "AND review_submitted_by_worker_id IS NOT NULL)",
    name="ck_quality_decisions_review_submitter_state",
)
```

Add to `QualityAuditEvent`:

```python
authorization_context: Mapped[dict | None] = mapped_column(JSONB)
```

Add to workflow:

```python
QD_SAME_ACTOR_REVIEW = "QD_SAME_ACTOR_REVIEW"
QD_ERROR_MESSAGES[QD_SAME_ACTOR_REVIEW] = (
    "Сотрудник, отправивший решение на рассмотрение, не может вернуть "
    "или принять его в том же цикле проверки"
)


def validate_review_separation(
    actor_worker_id: int,
    review_submitted_by_worker_id: int | None,
) -> str | None:
    if (
        review_submitted_by_worker_id is not None
        and actor_worker_id == review_submitted_by_worker_id
    ):
        return QD_SAME_ACTOR_REVIEW
    return None
```

- [x] **Step 5: rerun the targeted tests**

Expected: PASS without connecting to PostgreSQL. Stop for Domain Model review.

---

### Task 2: Correcting migration 27

**Files:**

- Create: `09_Разработка/backend/migrations/versions/20260724_27_qd_rbac_sod.py`
- Create:
  `09_Разработка/backend/migration_contract_tests/test_qd_rbac_sod_migration.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_migration_graph.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_alembic_cli_contract.py`

**Interfaces:**

- Consumes the exact columns/constraint names from Task 1.
- Produces revision `20260724_27_qd_rbac_sod` with
  `down_revision = "20260724_26_qd_idempotency"`.

- [x] **Step 1: write the failing AST contract**

The test must parse source without importing the migration and assert:

```python
assert revision == "20260724_27_qd_rbac_sod"
assert down_revision == "20260724_26_qd_idempotency"
assert "review_submitted_by_worker_id" in source
assert "authorization_context" in source
assert "LEGACY_AUTHORIZATION_SNAPSHOT" in source
assert "ck_quality_decisions_review_submitter_state" in source
assert "ck_quality_audit_qd_authorization_context" in source
```

Update both `EXPECTED_HEAD` constants to:

```python
EXPECTED_HEAD = "20260724_27_qd_rbac_sod"
```

- [x] **Step 2: run migration contracts and confirm failure**

```powershell
python -m pytest migration_contract_tests/test_qd_rbac_sod_migration.py `
  migration_contract_tests/test_migration_graph.py `
  migration_contract_tests/test_alembic_cli_contract.py -q
```

Expected: FAIL because revision 27 does not exist.

- [x] **Step 3: create self-contained migration**

The migration must:

```python
op.add_column(
    "quality_decisions",
    sa.Column("review_submitted_by_worker_id", sa.Integer(), nullable=True),
    schema="quality",
)
op.add_column(
    "quality_audit_events",
    sa.Column(
        "authorization_context",
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    ),
    schema="quality",
)
```

Backfill the submitter from the greatest numeric submitted `new_values.version`,
then `occurred_at`, then event `id`. Before adding the state constraint, execute a
static PostgreSQL guard that raises when a non-DRAFT decision remains null.

Historical QD events must be populated only with:

```sql
jsonb_strip_nulls(jsonb_build_object(
  'schema_version', 1,
  'authorization_snapshot_status', 'LEGACY_AUTHORIZATION_SNAPSHOT',
  'actor_worker_id', actor_worker_id,
  'actor_role_code', changed_fields ->> 'actor_role'
))
```

Add:

```python
op.create_check_constraint(
    "ck_quality_decisions_review_submitter_state",
    "quality_decisions",
    "(status = 'DRAFT' AND review_submitted_by_worker_id IS NULL) OR "
    "(status IN ('UNDER_REVIEW', 'DECIDED', 'SUPERSEDED') "
    "AND review_submitted_by_worker_id IS NOT NULL)",
    schema="quality",
)
op.create_check_constraint(
    "ck_quality_audit_qd_authorization_context",
    "quality_audit_events",
    "entity_type <> 'QUALITY_DECISION' OR authorization_context IS NOT NULL",
    schema="quality",
)
```

Downgrade order: drop audit constraint, drop decision constraint, drop
`authorization_context`, drop `review_submitted_by_worker_id`.

- [x] **Step 4: run all pure migration governance tests**

```powershell
python -m pytest migration_contract_tests -q
```

Expected: PASS; exact one head is revision 27; no forbidden runtime imports or
`op.get_bind`.

- [x] **Step 5: stop for Migration review**

Do not run upgrade against an owner database. TEST-DB execution occurs only in the
approved PostgreSQL acceptance environment.

---

### Task 3: Evidence-bearing authorization resolver

**Files:**

- Modify: `09_Разработка/backend/app/shared/permissions.py`
- Create: `09_Разработка/backend/tests/test_authorization_grants.py`

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True)
class AuthorizationGrant:
    actor_worker_id: int
    actor_role_code: str
    worker_role_assignment_id: int
    scope_type: str
    scope_id: str | None
    role_valid_from: date | None
    role_valid_to: date | None
```

```python
def worker_authorization_grants_for_joint(
    db: Session,
    worker_id: int,
    role_codes: Iterable[str],
    ctx: JointScopeContext,
    *,
    on_date: date | None = None,
) -> tuple[AuthorizationGrant, ...]: ...


def select_preferred_authorization_grant(
    grants: Iterable[AuthorizationGrant],
    role_code: str,
) -> AuthorizationGrant | None: ...
```

- [x] **Step 1: write failing resolver tests**

Cover effective/inactive/expired roles, foreign scope, and deterministic precedence:

```python
assert selected.scope_type == "ENGINEERING_DOCUMENT"
assert selected.worker_role_assignment_id == min(same_specificity_ids)
assert {g.actor_role_code for g in grants} == {
    "OGS_ENGINEER",
    "OTK_INSPECTOR",
}
```

- [x] **Step 2: confirm the tests fail**

```powershell
python -m pytest --noconftest -p no:cacheprovider `
  tests/test_authorization_grants.py -q
```

Expected: FAIL because the API does not exist.

- [x] **Step 3: implement resolver and compatibility wrapper**

Use specificity:

```python
_JOINT_SCOPE_PRIORITY = {
    "ENGINEERING_DOCUMENT": 0,
    "LINE": 1,
    "PROJECT": 2,
    "GLOBAL": 3,
}
```

Return every effective covering assignment except unsupported `SITE`; QD callers pass a
context without company IDs, so `COMPANY` cannot grant write access. Sort by:

```python
(
    _JOINT_SCOPE_PRIORITY.get(grant.scope_type, 99),
    grant.worker_role_assignment_id,
)
```

Refactor the old wrapper without changing its signature:

```python
return {
    grant.actor_role_code
    for grant in worker_authorization_grants_for_joint(
        db, worker_id, role_codes, ctx, on_date=on_date
    )
}
```

- [x] **Step 4: run resolver and existing permission tests**

```powershell
python -m pytest --noconftest -p no:cacheprovider `
  tests/test_authorization_grants.py -q
```

Expected: PASS. Stop for Shared Authorization Resolver review.

---

### Task 4: QualityDecision workflow and service orchestration

**Files:**

- Modify: `09_Разработка/backend/app/quality/quality_decision_services.py`
- Modify: `09_Разработка/backend/tests/test_quality_decision_services.py`

**Interfaces:**

- Consumes `AuthorizationGrant`, preferred selection and
  `validate_review_separation`.
- Produces verified `authorization_context` schema version 1.

- [x] **Step 1: write failing lifecycle tests**

Add cases proving:

```text
SUBMIT -> review_submitted_by_worker_id = submit actor
RETURN by same actor -> 409 QD_SAME_ACTOR_REVIEW
DECIDE by same actor -> 409 QD_SAME_ACTOR_REVIEW
RETURN by another OTK -> DRAFT and submitter NULL
new SUBMIT -> new submitter
DECIDE by another OTK -> submitter retained
```

- [x] **Step 2: write failing audit tests**

For all five events assert `authorization_context` contains the exact grant, action,
project/joint IDs, `VERIFIED`, `AUTHORIZED`, ISO `checked_at`, and warning list.
For `SUPERSEDED`, assert `action == "DECIDE"` and the same assignment as `DECIDED`.

- [x] **Step 3: confirm focused failure**

```powershell
python -m pytest tests/test_quality_decision_services.py `
  -k "same_actor or review_submitter or authorization_context or dual_role" -q
```

- [x] **Step 4: replace role-code-only orchestration**

For each audited command:

1. resolve all grants for allowed roles;
2. derive `granted_roles`;
3. preserve idempotency replay before domain validation;
4. select the preferred grant for `pick_actor_role(...)`;
5. build a JSON-safe snapshot from that grant;
6. pass the snapshot explicitly to `_record_audit`.

Build context with:

```python
{
    "schema_version": 1,
    "authorization_snapshot_status": "VERIFIED",
    "policy_result": "AUTHORIZED",
    "action": action,
    "actor_worker_id": grant.actor_worker_id,
    "actor_role_code": grant.actor_role_code,
    "worker_role_assignment_id": grant.worker_role_assignment_id,
    "scope_type": grant.scope_type,
    "scope_id": grant.scope_id,
    "role_valid_from": (
        grant.role_valid_from.isoformat() if grant.role_valid_from else None
    ),
    "role_valid_to": (
        grant.role_valid_to.isoformat() if grant.role_valid_to else None
    ),
    "checked_at": checked_at.isoformat(),
    "project_id": str(decision.project_id),
    "joint_id": str(decision.joint_id),
    "governance_warnings": warnings,
}
```

Add `QD_DUAL_ROLE_ASSIGNMENT` when both effective role codes cover the same Joint.

- [x] **Step 5: enforce cycle state and SoD under lock**

`SUBMIT`:

```python
decision.review_submitted_by_worker_id = actor_worker_id
```

`RETURN` and `DECIDE`, after status/version checks:

```python
error = qdw.validate_review_separation(
    actor_worker_id,
    decision.review_submitted_by_worker_id,
)
if error is not None:
    self._deny(error, qdw.QD_ERROR_MESSAGES[error])
```

`RETURN` records the previous submitter in audit, then:

```python
decision.review_submitted_by_worker_id = None
```

`DECIDE` retains the field. Add it to current idempotency response snapshots and use
`snapshot.get("review_submitted_by_worker_id")` for legacy snapshots.

- [x] **Step 6: run service tests**

```powershell
python -m pytest tests/test_quality_decision_services.py -q
```

Expected: PASS, including concurrency and idempotency. Stop for Workflow/Service review.

---

### Task 5: Additive API contract

**Files:**

- Modify: `09_Разработка/backend/app/quality/quality_decision_schemas.py`
- Modify: `09_Разработка/backend/tests/test_quality_decision_api.py`

**Interfaces:**

- Produces nullable read fields without request/route changes.

- [x] **Step 1: write failing API tests**

```python
assert body["review_submitted_by_worker_id"] == submitter.id
assert event["authorization_context"]["authorization_snapshot_status"] == "VERIFIED"
assert conflict.status_code == 409
assert conflict.json()["detail"]["code"] == "QD_SAME_ACTOR_REVIEW"
```

- [x] **Step 2: confirm failure**

```powershell
python -m pytest tests/test_quality_decision_api.py `
  -k "review_submitted or authorization_context or same_actor" -q
```

- [x] **Step 3: add schema fields**

```python
review_submitted_by_worker_id: int | None = None
```

```python
authorization_context: dict | None = None
```

Do not add request fields or new routes.

- [x] **Step 4: run the complete API file**

```powershell
python -m pytest tests/test_quality_decision_api.py -q
```

Expected: PASS. Stop for API review.

---

### Task 6: PostgreSQL acceptance, regression and documentation closure

**Files:**

- Modify only canonical documents that need final `done` evidence.

**Interfaces:**

- Consumes accepted Tasks 1–5.
- Produces final evidence; does not broaden scope.

- [x] **Step 1: run migration preflight on isolated PostgreSQL TEST-DB**

Verify current revision is 26, preserve row counts, execute upgrade to 27, and inspect:

```sql
SELECT status, review_submitted_by_worker_id
FROM quality.quality_decisions;

SELECT event_type, authorization_context
FROM quality.quality_audit_events
WHERE entity_type = 'QUALITY_DECISION';
```

Expected: state constraint satisfied; every historical QD event marked legacy; no
invented scope.

- [x] **Step 2: run focused application suite**

```powershell
python -m pytest tests/test_role_permissions.py `
  tests/test_quality_decision_rbac_domain.py `
  tests/test_quality_decision_services.py `
  tests/test_quality_decision_api.py -q
```

Expected: PASS.

- [x] **Step 3: run migration governance suite**

```powershell
python -m pytest migration_contract_tests -q
```

Expected: PASS with exactly one head, revision 27.

- [x] **Step 4: run full backend regression**

```powershell
python -m pytest tests -q
```

Expected: PASS; any unrelated pre-existing failure is reported separately and is not
silently repaired.

- [x] **Step 5: downgrade/upgrade rehearsal on disposable TEST-DB**

Run `27 → 26 → 27`; confirm only AS-02 columns/constraints disappear and return.
Never perform this rehearsal on an owner or production database.

- [x] **Step 6: synchronize completion evidence**

Only after fresh acceptance update ADR-028 implementation status,
`docs/ARCHITECTURE.md`, `docs/project/DECISIONS.md`,
`docs/project/PROJECT_SUMMARY.md`, `docs/project/ROADMAP.md`,
`docs/project/PROJECT_STATUS.yaml` and `docs/project/TASK_REGISTRY.md`.

- [x] **Step 7: present diff and obtain commit confirmation**

Report changed files, complete diff summary and exact test outputs. Do not commit or push
until the owner separately confirms.

## Closure evidence — 2026-07-24

- Domain/service/API TDD gates completed.
- Configured PostgreSQL schema: `test`; active revision:
  `20260724_27_qd_rbac_sod`.
- The test bootstrap had already applied revision 27 before the explicit preflight.
  An empty-schema rehearsal `27 → 26 → 27` therefore supplied the downgrade/upgrade
  proof: both AS-02 columns disappeared at 26 and both columns plus both CHECK constraints
  returned at 27.
- Migration governance: `35 passed`.
- Focused AS-02 and permission regression: `100 passed`.
- Complete backend regression: `1590 passed`.
- Owner explicitly authorized implementation, database acceptance, fixes, commit and push
  before execution; no additional commit confirmation was required.

## Self-review record

- Spec coverage: R-1/R-2/R-3, migration/backfill, legacy truthfulness, compatibility,
  errors, idempotency, concurrency and documentation gates are mapped to Tasks 1–6.
- Scope: no B-04, runtime profile, TEST-DB foundation implementation, 9D-4A-5,
  ProductionHold, global RBAC rewrite or Identity/Auth change.
- Type consistency: `review_submitted_by_worker_id`, `authorization_context`,
  `AuthorizationGrant`, `QD_SAME_ACTOR_REVIEW` and
  `QD_DUAL_ROLE_ASSIGNMENT` use one spelling throughout.
- Migration graph: both existing `EXPECTED_HEAD` declarations must move to revision 27.
- Historical evidence: missing scope remains explicitly legacy; current HR state is never
  used to manufacture past authority.
- Placeholder scan: no `TBD`, `TODO`, “similar to” or unspecified implementation step.
