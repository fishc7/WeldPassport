# B-04B Repository Cut & Maintenance Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status:** `BLOCKED`. Do not execute any task until B-04A-R18 is separately
> accepted and a subsequent Maintenance Readiness Review returns `READY`.

**Goal:** Активировать принятый `canonical_baseline_v1` и атомарно принять
существующую PostgreSQL-БД через перенос version marker в `public`.

**Architecture:** B-04B выполняется только после отдельной приёмки B-04A-R18.
PG16 B-04A evidence сохраняется immutable со статусом `historical_non_authorizing`;
авторизующим является только PG18 fingerprint v2 evidence. Repository cut и
maintenance tooling готовятся на изолированной stacked-ветке; полный процесс сначала
репетируется на восстановленной копии backup. Рабочая БД изменяется только отдельным
разрешённым maintenance run.

**Tech Stack:** Python 3.12, pytest 8, SQLAlchemy 2, Alembic, PostgreSQL 18.x,
`pg_dump --format=custom`, `pg_restore`, SHA-256, canonical JSON.

## Global Constraints

- B-04A-R18 status must be accepted with evidence digest and exact accepted head SHA.
- `evidence-index.json` must identify one active-authorizing PG18 fingerprint v2
  evidence set; PG16 evidence remains historical and non-authorizing.
- Migration freeze remains active through B-04B closure.
- Active historical head before adoption:
  `20260724_27_qd_rbac_sod`.
- New active head after cut: `canonical_baseline_v1`.
- Canonical version table after cut: `public.alembic_version`.
- `public.alembic_version` shape:
  `version_num varchar(32) NOT NULL` with primary key `alembic_version_pkc`.
- The transaction removes only `test.alembic_version`; schema `test` and legacy tables
  remain unchanged.
- No automatic repair, fallback DSN, repeated stamp or manual partial completion.
- No application tests or TEST-DB Foundation work.
- Production execution requires a new explicit maintenance confirmation even if code and
  rehearsal were approved earlier.
- Do not stage, commit or push without a separate user confirmation.

PowerShell commands below run from the B-04B backend worktree and use:

```powershell
$PythonExe = "D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe"
```

---

### Task 1: Adoption state machine and report contract

**Files:**

- Create: `09_Разработка/backend/migrations/b04/adoption_state.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_adoption_state.py`
- Create: `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/adoption-report.schema.json`

**Interfaces:**

- Produces:
  - `AdoptionState` enum;
  - `MarkerSnapshot` dataclass;
  - `classify_marker_state(snapshot: MarkerSnapshot) -> AdoptionState`;
  - `PreparedEvidence` dataclass;
  - `AdoptionReport` dataclass;
  - `canonical_report_bytes(report: AdoptionReport) -> bytes`.

- [ ] **Step 1: Write failing state tests**

Exact states:

```python
class AdoptionState(StrEnum):
    READY = "READY"
    ALREADY_ADOPTED = "ALREADY_ADOPTED"
    AMBIGUOUS = "AMBIGUOUS"
    COMMITTED_UNVERIFIED = "COMMITTED_UNVERIFIED"
    ACCEPTED = "ACCEPTED"
```

Required classification:

- public absent + test one row old head → `READY`;
- public one row baseline/newer + test absent → `ALREADY_ADOPTED`;
- both tables, no tables, empty table, multiple rows or unexpected values → `AMBIGUOUS`;
- accepted report is append-only and cannot be overwritten.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_adoption_state.py -q
```

Expected: missing module/schema.

- [ ] **Step 3: Implement immutable typed state**

Use frozen dataclasses. Report serialization must reuse
`migrations.b04.manifest.canonical_json_bytes`. The JSON schema must require adoption ID,
database identity, source SHA, old/new marker, backup digest, manifest/fingerprint/seed
digests, attempt status, timestamps and verification results.

- [ ] **Step 4: Verify GREEN**

Run the focused test. Expected: all state and schema tests pass.

- [ ] **Step 5: Review checkpoint**

Provide diff and proposed commit:
`feat(migrations): define B-04 adoption state`.
Do not commit without separate confirmation.

---

### Task 2: Read-only maintenance preflight

**Files:**

- Create: `09_Разработка/backend/migrations/b04/preflight.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_preflight.py`

**Interfaces:**

- Consumes fingerprint, manifest, seed and adoption-state contracts from B-04A.
- Produces:
  - `PreflightConfig`;
  - `run_preflight(connection: Connection, config: PreflightConfig) -> PreparedEvidence`;
  - `verify_backup_manifest(path: Path) -> BackupEvidence`.

- [ ] **Step 1: Write failing preflight tests**

Dependency-injected tests must reject:

- wrong DB identity or PostgreSQL major;
- target/restored exact `server_version_num` mismatch;
- missing/mismatched active-authorizing fingerprint v2 evidence index;
- missing/invalid `pg_dump` SHA-256;
- missing successful `pg_restore` evidence;
- source/manifest/fingerprint/seed digest mismatch;
- historical marker not exactly one old-head row;
- any existing public marker object;
- live fingerprint mismatch;
- unknown canonical object;
- active DDL/migration session or long transaction;
- missing maintenance approval or stopped-writers evidence.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_preflight.py -q
```

Expected: missing preflight module.

- [ ] **Step 3: Implement read-only queries**

All object names are fixed literals or validated against the accepted fingerprint.
Credentials, URL, host and usernames must never enter logs or reports.

The maintenance role must prove visibility of `pg_stat_activity` equivalent to
`pg_read_all_stats` and ownership/DDL rights for both marker tables. Missing visibility
or privileges is a preflight failure, not a reason to skip a check.

Marker queries:

```sql
SELECT to_regclass('test.alembic_version');
SELECT version_num FROM test.alembic_version;
SELECT to_regclass('public.alembic_version');
```

Session checks must read `pg_stat_activity` and reject non-approved active migration/DDL
sessions and long-running transactions according to exact bounded thresholds stored in
`PreflightConfig`.

- [ ] **Step 4: Verify GREEN**

Run focused tests. Expected: all failure paths stop before any mutating adapter call.

- [ ] **Step 5: Review checkpoint**

Provide query inventory and proposed commit:
`feat(migrations): add B-04 maintenance preflight`.
Do not commit without separate confirmation.

---

### Task 3: Repository cut

**Files:**

- Move unchanged:
  `09_Разработка/backend/migrations/versions/*.py`
  → `09_Разработка/backend/migrations/archive/canonical_baseline_v1/revisions/`
- Move unchanged:
  `09_Разработка/backend/migrations/baseline_candidates/canonical_baseline_v1.py`
  → `09_Разработка/backend/migrations/versions/canonical_baseline_v1.py`
- Create:
  `09_Разработка/backend/migrations/archive/canonical_baseline_v1/README.md`
- Modify: `09_Разработка/backend/alembic.ini`
- Modify: `09_Разработка/backend/migrations/env.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_migration_graph.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_alembic_cli_contract.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_migration_import_policy.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_offline_policy.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_archive.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_marker_config.py`

**Interfaces:**

- Produces one active root/head and byte-identical immutable archive.

- [ ] **Step 1: Write failing cut contracts before moving files**

Require:

- active graph count 1;
- root/head `canonical_baseline_v1`;
- archived IDs are not resolvable by active Alembic;
- archive has exactly 31 files and all hashes match manifest;
- active import/offline debt is zero;
- `version_locations` points exactly to `migrations/versions`;
- online/offline marker schema is literal `public`;
- `version_table_pk=True`.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_archive.py `
  migration_contract_tests/test_b04_marker_config.py `
  migration_contract_tests/test_migration_graph.py `
  migration_contract_tests/test_alembic_cli_contract.py -q
```

Expected: old active graph and marker configuration fail the new contracts.

- [ ] **Step 3: Verify source hashes immediately before move**

```powershell
& $PythonExe -m migrations.b04.manifest `
  --verify-source `
  --manifest migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.json
```

Expected: all 31 hashes match. Any mismatch stops the cut.

- [ ] **Step 4: Move files without rewriting bytes**

Use Git-aware moves only after exact source/target lists are reviewed. Never move
`__pycache__`, `.pyc` or unrelated files.

- [ ] **Step 5: Activate baseline and configuration**

`alembic.ini`:

```ini
[alembic]
script_location = migrations
version_locations = %(here)s/migrations/versions
```

Both `context.configure` calls in `env.py` must use:

```python
version_table_schema="public",
version_table_pk=True,
```

- [ ] **Step 6: Verify GREEN**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m alembic heads
& $PythonExe -m alembic history
git diff --check
```

Expected: one active revision/head, archive invisible, all pure contracts pass.

- [ ] **Step 7: Review checkpoint**

Provide exact rename detection and checksum proof. Proposed commit:
`refactor(migrations): activate canonical baseline v1`.
Do not commit or deploy without separate confirmation.

---

### Task 4: Atomic marker-transfer transaction

**Files:**

- Create: `09_Разработка/backend/migrations/b04/adopt.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_adopt_transaction.py`

**Interfaces:**

- Consumes `PreparedEvidence` and an already-open SQLAlchemy connection.
- Produces:
  - `transfer_marker(connection: Connection, evidence: PreparedEvidence) -> MarkerTransferResult`;
  - no internal engine creation;
  - no internal commit outside the caller-owned transaction.

- [ ] **Step 1: Write failing ordered-call tests**

Use a recording fake connection and require this exact sequence:

```text
SERIALIZABLE transaction
→ SET LOCAL timeouts/search_path
→ advisory transaction lock
→ DB identity recheck
→ deterministic SHARE locks for canonical tables
→ ACCESS EXCLUSIVE lock historical marker
→ marker recheck
→ fingerprint under locks
→ create public marker
→ insert baseline
→ drop historical marker
→ marker/fingerprint recheck
→ caller commit
```

Inject a failure at every boundary and prove no later command executes.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_adopt_transaction.py -q
```

Expected: missing transfer function.

- [ ] **Step 3: Implement the transaction**

Fixed marker DDL:

```sql
CREATE TABLE public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO public.alembic_version (version_num)
VALUES ('canonical_baseline_v1');
DROP TABLE test.alembic_version;
```

Use `pg_advisory_xact_lock` with one frozen B-04 lock key. Quote canonical table names
with SQLAlchemy dialect identifier preparer after verifying each pair belongs to the
accepted fingerprint. Never concatenate unvalidated input.

- [ ] **Step 4: Verify GREEN**

Run focused pure tests. Expected: all order/failure-injection cases pass.

- [ ] **Step 5: Review checkpoint**

Provide full SQL inventory and proposed commit:
`feat(migrations): add atomic baseline adoption`.
Do not commit without separate confirmation.

---

### Task 5: Postflight and append-only reporting

**Files:**

- Create: `09_Разработка/backend/migrations/b04/postflight.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_postflight.py`

**Interfaces:**

- Produces:
  - `run_postflight(connection_factory, evidence: PreparedEvidence) -> AdoptionReport`;
  - statuses `COMMITTED_UNVERIFIED`, `ADOPTION_ACCEPTED`, `ADOPTION_FAILED`;
  - report digest without secrets.

- [ ] **Step 1: Write failing postflight tests**

Require exact public marker, absent historical marker, unchanged fingerprint, successful
`heads/current/history/check`, read-only smoke and append-only report behavior.

- [ ] **Step 2: Verify RED**

Run focused test. Expected: missing postflight module.

- [ ] **Step 3: Implement postflight**

The report writer must use create-new semantics and fail if the target path already
exists. It may write only to the operator-provided external report directory. Git receives
only a sanitized digest record after acceptance.

- [ ] **Step 4: Verify GREEN**

Run focused tests. Expected: failure after transaction produces
`COMMITTED_UNVERIFIED`; it never retries marker transfer.

- [ ] **Step 5: Review checkpoint**

Proposed commit:
`feat(migrations): add B-04 postflight evidence`.
Do not commit without separate confirmation.

---

### Task 6: Restored-backup rehearsal

**Files:**

- Create: `09_Разработка/backend/migrations/b04/rehearse_adoption.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_rehearsal.py`
- Generate externally: backup manifest, restore evidence and rehearsal report.

**Interfaces:**

- Consumes a custom-format backup and isolated restored PostgreSQL 18.x target whose
  exact `server_version_num` matches the target DB.
- Produces `B04B_REHEARSAL_ACCEPTED` report or a fail-closed finding.

- [ ] **Step 1: Write failing orchestration tests**

Require:

```text
backup checksum
→ pg_restore isolated target
→ restored fingerprint
→ preflight
→ marker transaction
→ postflight
→ restore-recovery rehearsal
→ immutable report
```

- [ ] **Step 2: Verify RED**

Run focused test. Expected: missing rehearsal runner.

- [ ] **Step 3: Implement the runner**

The runner accepts explicit paths and DSN through approved environment variables,
redacts credentials and refuses the working database identity.

- [ ] **Step 4: Run pure GREEN**

Run focused tests. Expected: all orchestration/failure paths pass without DB.

- [ ] **Step 5: Perform the rehearsal**

Only against the approved isolated restored copy:

```powershell
& $PythonExe -m migrations.b04.rehearse_adoption
```

Expected:

- restore verified;
- fingerprint equals B-04A-R18 active-authorizing fingerprint v2 digest;
- restored and target `server_version_num` values match exactly;
- marker transaction and postflight pass;
- recovery from a separately restored backup is demonstrated;
- report status `B04B_REHEARSAL_ACCEPTED`.

- [ ] **Step 6: Full code acceptance**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall migrations/b04 migrations/versions
git diff --check
```

Expected: zero failures.

- [ ] **Step 7: Maintenance gate**

Stop. Present all evidence and request a new explicit confirmation that identifies:

- exact target database;
- exact target/restored `server_version_num`;
- maintenance window;
- backup digest;
- accepted rehearsal digest;
- recovery owner;
- external report destination.

No agent may infer this confirmation from earlier general authorization.

---

### Task 7: Production maintenance adoption

**Files:**

- No source changes during the maintenance run.
- External append-only evidence only.

**Interfaces:**

- Consumes the exact approved target and one-time adoption token.
- Produces signed `ADOPTION_ACCEPTED` or restored pre-B-04 state.

- [ ] **Step 1: Re-run read-only preflight**

Expected: exact target identity, old marker, fingerprint, backup and freeze all match.

- [ ] **Step 2: Execute one marker transaction**

Run the approved adoption command once. Do not retry on ambiguous output.

- [ ] **Step 3: Run postflight**

Expected: public baseline marker, absent historical marker, unchanged fingerprint,
successful Alembic checks and read-only smoke.

- [ ] **Step 4: Sign acceptance**

The repository owner signs the immutable report as `ADOPTION_ACCEPTED`.

- [ ] **Step 5: Failure handling**

- before transaction: stop with no DB change;
- transaction failure: verify rollback, otherwise restore backup;
- post-commit/pre-acceptance failure: keep writers stopped and restore backup plus previous
  release/config;
- after acceptance: use a separately approved forward-remediation incident process.

---

### Task 8: B-04 closure and freeze release

**Files:**

- Modify: `docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC.md`
- Modify: `docs/project/TASK_B-04B_CUT_MAINTENANCE_ADOPTION_IMPLEMENTATION_PLAN.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/project/PROJECT_STATUS.yaml`
- Modify: `docs/project/ROADMAP.md`

**Interfaces:**

- Consumes signed adoption report digest.
- Produces canonical B-04 status `done` and explicit freeze release.

- [ ] **Step 1: Record exact evidence**

Record commits, source/adoption SHA, manifest/fingerprint/seed/backup/rehearsal/report
digests, PostgreSQL version, test counts and maintenance timestamps without secrets.

- [ ] **Step 2: Release migration freeze**

Only after `ADOPTION_ACCEPTED`, record that future migrations must use
`down_revision = "canonical_baseline_v1"` or its latest descendant.

- [ ] **Step 3: Final verification**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m alembic heads
& $PythonExe -m alembic history
git diff --check
```

Expected: one graph, one head, no archived IDs active, no documentation contradiction.

- [ ] **Step 4: Final review checkpoint**

Provide full diff and proposed closure commit:
`docs(migrations): close B-04 canonical baseline adoption`.
Do not commit or push without separate confirmation.
