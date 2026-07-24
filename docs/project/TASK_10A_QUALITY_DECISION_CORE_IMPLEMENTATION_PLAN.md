# Task 10A QualityDecision Core Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` and execute tasks in order with review gates.

**Goal:** Restore Task 10A governance and complete the approved
`QualityDecision Core` contract through migration, service remediation, and API.

**Architecture:** Preserve ADR-027 lifecycle and authority. Add a domain-local
idempotency record in PostgreSQL, keep transaction ownership in the service,
store immutable command response snapshots, and expose thin command endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2,
PostgreSQL 16, pytest.

**Execution status (2026-07-24):** plan executed, accepted and committed as
`c1b551e`. Evidence is recorded in the Recovery Specification §14 and Task
Registry. The checklists below preserve the original execution sequence;
canonical status is `done`.

## Global Constraints

- PostgreSQL only; never introduce SQLite.
- Do not modify migration revision 25.
- Keep AS-02, B-04, runtime profile and TEST-DB Foundation out of scope.
- Do not create Defect/Disposition/Repair/Reinspection side effects.
- Do not commit or push.
- Execute Governance → Migration → Service → API → Acceptance.

---

### Task 1: Governance recovery

**Files:**

- Create: `docs/project/TASK_10A_QUALITY_DECISION_CORE_RECOVERY_SPEC.md`
- Create: `docs/project/TASK_10A_QUALITY_DECISION_CORE_PROMPT.md`
- Create: `docs/project/TASK_10A_QUALITY_DECISION_CORE_IMPLEMENTATION_PLAN.md`
- Modify: `docs/project/ADR-027-quality-decision-core-canon.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/PROJECT_STATUS.yaml`
- Modify: `docs/project/ROADMAP.md`
- Modify: `docs/project/PROJECT_SUMMARY.md`

**Produces:** Canonical Q-D9/Q-D5 recovery contract and truthful `in_progress`
status.

- [ ] Add a dated recovery addendum to ADR-027; preserve original accepted text.
- [ ] Register 10A-R/10A-1/10A-1R/10A-2/10A-2R/10A-3.
- [ ] Synchronize derivative documents without marking code accepted.
- [ ] Search for stale `Services/API ... not implemented` claims and correct them.
- [ ] Run Markdown/reference and placeholder scans.

### Task 2: Idempotency model and migration

**Files:**

- Modify: `09_Разработка/backend/app/quality/quality_decision_models.py`
- Modify: `09_Разработка/backend/app/quality/models.py`
- Create: `09_Разработка/backend/migrations/versions/20260724_26_qd_idempotency.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_qd_idempotency_migration.py`

**Produces:** `QualityDecisionIdempotencyRecord` and self-contained revision 26.

- [ ] Write a failing contract test asserting revision/down_revision, table,
  columns, CHECK, FK, index and UNIQUE scope.
- [ ] Run only that contract test and confirm RED because revision 26 is absent.
- [ ] Add the SQLAlchemy model with exact constraints from the recovery spec.
- [ ] Add revision 26 without importing application models or connecting at
  import time.
- [ ] Re-run the contract test and canonical metadata tests to GREEN.
- [ ] Run offline migration-policy and graph tests.

### Task 3: Pure idempotency workflow

**Files:**

- Modify: `09_Разработка/backend/app/quality/quality_decision_workflow.py`
- Create: `09_Разработка/backend/tests/test_quality_decision_idempotency_policy.py`

**Produces:** Command/target constants, key normalization, deterministic request
hash and `QD_IDEMPOTENCY_CONFLICT`.

- [ ] Write failing pure tests for missing/blank/oversize keys, stable hashes,
  sorted basis IDs and payload differences.
- [ ] Confirm RED for missing functions/constants.
- [ ] Implement minimal pure helpers with canonical JSON and SHA-256.
- [ ] Confirm GREEN and run existing workflow tests.

### Task 4: Repository and service replay

**Files:**

- Modify: `09_Разработка/backend/app/quality/quality_decision_repository.py`
- Modify: `09_Разработка/backend/app/quality/quality_decision_services.py`
- Modify: `09_Разработка/backend/tests/test_quality_decision_services.py`
- Modify: `09_Разработка/backend/tests/conftest.py`

**Produces:** Atomic idempotency replay/conflict and exact command snapshots for
all five mutations.

- [ ] Write one failing service test for CREATE replay with no second sequence,
  row or CREATED event.
- [ ] Implement repository get/add and CREATE replay/store.
- [ ] Repeat RED/GREEN for UPDATE_DRAFT, SUBMIT, RETURN and DECIDE.
- [ ] Add same-key/different-payload conflict tests.
- [ ] Add rollback and concurrent duplicate tests.
- [ ] Ensure cleanup deletes idempotency rows before decisions.
- [ ] Run the complete QualityDecision service suite.

### Task 5: SUBMIT content snapshot

**Files:**

- Modify: `09_Разработка/backend/tests/test_quality_decision_services.py`
- Modify: `09_Разработка/backend/app/quality/quality_decision_services.py`

**Produces:** `QUALITY_DECISION_SUBMITTED.new_values` containing version,
summary and canonical basis IDs.

- [ ] Write a failing test that edits/returns/resubmits and asserts two distinct
  immutable submission snapshots.
- [ ] Confirm RED because the current event stores status only.
- [ ] Add the final-content snapshot to SUBMIT audit construction.
- [ ] Confirm GREEN and run lifecycle/audit regression tests.

### Task 6: Schemas and command API

**Files:**

- Create: `09_Разработка/backend/app/quality/quality_decision_schemas.py`
- Create: `09_Разработка/backend/app/quality/quality_decision_api.py`
- Modify: `09_Разработка/backend/app/main.py`
- Create: `09_Разработка/backend/tests/test_quality_decision_api.py`

**Produces:** Thin API for create/read/bases/events/update/submit/return/decide.

- [ ] Write failing API tests for route absence and response contracts.
- [ ] Add Pydantic v2 request/read models with `extra="forbid"`.
- [ ] Add the router and include it under `/api/v1`.
- [ ] Add mandatory `Idempotency-Key` dependency to five mutating endpoints.
- [ ] Add success, 401/404/409/422, role/scope and direct-status-rejection tests.
- [ ] Add API replay/conflict tests for every mutation.
- [ ] Run the complete QD API suite and OpenAPI route assertion.

### Task 7: Acceptance

**Files:** All scoped files above.

**Produces:** Evidence-backed acceptance report and Diff.

- [ ] Run migration-contract tests relevant to revisions 25/26 and canonical
  metadata.
- [ ] Run pure policy tests.
- [ ] Run service and API suites.
- [ ] Run applicable quality regression tests.
- [ ] Run Python compilation and `git diff --check`.
- [ ] Inspect the complete scoped Diff for AS-02/B-04/TEST-DB leakage.
- [ ] Update Task registry status only to the level supported by fresh evidence.
- [ ] Report changed files, Diff summary, commands/results, residual risks and
  confirm no commit/push.
