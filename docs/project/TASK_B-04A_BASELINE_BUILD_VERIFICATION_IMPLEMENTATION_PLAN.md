# B-04A Baseline Build & Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать и доказать self-contained `canonical_baseline_v1` без изменения
active Alembic graph и без обращения к существующей рабочей БД.

**Architecture:** B-04A фиксирует schema source commit, frozen manifest и PostgreSQL
catalog fingerprint v1. Отдельный verification-only Alembic context генерирует baseline
candidate вне active `migrations/versions`; две одноразовые PostgreSQL 16.x доказывают
эквивалентность historical chain и baseline.

**Tech Stack:** Python 3.12, pytest 8, SQLAlchemy 2, Alembic, PostgreSQL 16,
`pg_dump`/`pg_restore`, SHA-256, canonical JSON.

## Global Constraints

- Canonical schemas: `hr`, `welding`, `project`, `engineering`, `quality`.
- Schema source commit:
  `6c56f99edbd4e7346264ee14658d2076b5fd0775`.
- Expected frozen graph: 31 revisions; root `20260702_02_hr_core`; head
  `20260724_27_qd_rbac_sod`.
- Expected canonical metadata: 12 modules and 73 tables.
- Baseline candidate must remain outside active `migrations/versions`.
- Do not modify `migrations/env.py`, `alembic.ini` or the active 31 revision files.
- Do not read `.env` as a fallback for disposable database credentials.
- Do not connect to the existing working database.
- Do not run application tests.
- Do not implement B-04B, runtime profile or TEST-DB Foundation.
- Every PostgreSQL command requires an explicit disposable DSN, exact opt-in and
  ownership token.
- Do not stage, commit or push without a separate user confirmation.

PowerShell commands below run from
`D:\WeldPassport\.worktrees\b04-baseline\09_Разработка\backend` and use:

```powershell
$PythonExe = "D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe"
```

---

### Task 1: Source cut and migration-freeze contract

**Files:**

- Create: `09_Разработка/backend/migrations/b04/source_contract.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_source_cut.py`
- Modify at acceptance: `docs/project/TASK_REGISTRY.md`

**Interfaces:**

- Consumes: exact schema source commit and active migration tree.
- Produces: constants `SCHEMA_SOURCE_COMMIT`, `HISTORICAL_ROOT`,
  `HISTORICAL_HEAD`, `HISTORICAL_REVISION_COUNT`.

- [ ] **Step 1: Obtain and verify the exact source**

Run in the repository root:

```powershell
git fetch origin docs/as-02-quality-decision-rbac-analysis
git cat-file -e 6c56f99edbd4e7346264ee14658d2076b5fd0775^{commit}
git show --no-patch --format="%H %P %s" 6c56f99edbd4e7346264ee14658d2076b5fd0775
```

Expected: the full SHA resolves and is the merge of PR #4. If it does not resolve,
stop; substituting another SHA is forbidden.

- [ ] **Step 2: Create the isolated implementation worktree**

After separate Git approval:

```powershell
Set-Location D:\WeldPassport
git worktree add .worktrees\b04-baseline `
  -b codex/b04a-baseline `
  6c56f99edbd4e7346264ee14658d2076b5fd0775
```

Expected: named branch `codex/b04a-baseline`, clean worktree.

- [ ] **Step 3: Write the failing source-cut contract**

Create a pure test that reads Git only through injected text fixtures and validates the
expected constants:

```python
SCHEMA_SOURCE_COMMIT = "6c56f99edbd4e7346264ee14658d2076b5fd0775"
HISTORICAL_ROOT = "20260702_02_hr_core"
HISTORICAL_HEAD = "20260724_27_qd_rbac_sod"
HISTORICAL_REVISION_COUNT = 31


def test_b04_cut_001_constants_match_accepted_snapshot() -> None:
    assert len(SCHEMA_SOURCE_COMMIT) == 40
    assert HISTORICAL_ROOT == "20260702_02_hr_core"
    assert HISTORICAL_HEAD == "20260724_27_qd_rbac_sod"
    assert HISTORICAL_REVISION_COUNT == 31
```

Add AST reuse of the existing graph parser and assert one root, one head, 31 IDs and
73 canonical tables.

- [ ] **Step 4: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_source_cut.py -q
```

Expected: collection failure because the B-04 source contract module does not exist.

- [ ] **Step 5: Add the source contract**

Create `migrations/b04/source_contract.py`:

```python
from __future__ import annotations

SCHEMA_SOURCE_COMMIT = "6c56f99edbd4e7346264ee14658d2076b5fd0775"
HISTORICAL_ROOT = "20260702_02_hr_core"
HISTORICAL_HEAD = "20260724_27_qd_rbac_sod"
HISTORICAL_REVISION_COUNT = 31
CANONICAL_TABLE_COUNT = 73
CANONICAL_MODEL_MODULE_COUNT = 12
BASELINE_REVISION = "canonical_baseline_v1"
```

The test must import these constants rather than duplicate them.

- [ ] **Step 6: Verify GREEN and declare freeze**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_source_cut.py -q
```

Expected: all source-cut tests pass.

Record `B-04 migration freeze active` in `TASK_REGISTRY.md`. Do not change task status
to done.

- [ ] **Step 7: Review checkpoint**

Provide diff and proposed commit:
`docs(migrations): start B-04A source cut`.
Do not commit without separate confirmation.

---

### Task 2: Frozen revision manifest

**Files:**

- Create: `09_Разработка/backend/migrations/b04/__init__.py`
- Create: `09_Разработка/backend/migrations/b04/manifest.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_manifest.py`
- Generate: `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.json`
- Generate: `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.sha256`
- Generate: `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/cut.json`

**Interfaces:**

- Consumes: `migrations.b04.source_contract`.
- Produces:
  - `canonical_json_bytes(value: object) -> bytes`;
  - `sha256_hex(data: bytes) -> str`;
  - `parse_revision(path: Path) -> RevisionRecord`;
  - `build_frozen_manifest(versions_dir: Path) -> dict[str, object]`;
  - `verify_manifest_files(manifest: Mapping[str, object], root: Path, *, archived: bool) -> None`.

- [ ] **Step 1: Write failing pure tests**

Tests must prove:

- canonical JSON is UTF-8, sorted, compact and newline-terminated;
- revision/down_revision are read with AST, never by importing revision modules;
- raw byte SHA-256 changes after any byte edit;
- manifest has exactly 31 unique revisions and a closed linear graph;
- source and future archive paths are exact;
- manifest digest verifies;
- verification rejects missing, extra or changed files.

Representative test:

```python
def test_b04_manifest_001_is_deterministic() -> None:
    left = canonical_json_bytes({"b": 2, "a": [3, 1]})
    right = canonical_json_bytes({"a": [3, 1], "b": 2})
    assert left == right == b'{"a":[3,1],"b":2}\n'
```

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_manifest.py -q
```

Expected: import failure for `migrations.b04.manifest`.

- [ ] **Step 3: Implement deterministic manifest primitives**

Core implementation:

```python
def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
```

`parse_revision` must use `ast.literal_eval` for `revision` and `down_revision`.
Manifest entries must contain `revision`, `down_revision`, `filename`, `source_path`,
`archive_path`, `byte_size` and `sha256`.

- [ ] **Step 4: Verify GREEN**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_manifest.py -q
```

Expected: all manifest tests pass without importing application runtime or touching DB.

- [ ] **Step 5: Generate and verify artifacts**

```powershell
& $PythonExe -m migrations.b04.manifest `
  --versions-dir migrations/versions `
  --output-dir migrations/baselines/canonical_baseline_v1
```

Expected:

- 31 entries;
- exact root/head;
- `source_commit` equals the accepted SHA;
- digest file contains lowercase SHA-256 and filename;
- rerun produces byte-identical files.

- [ ] **Step 6: Review checkpoint**

Provide generated artifact diff and proposed commit:
`chore(migrations): freeze B-04 historical manifest`.
Do not commit without separate confirmation.

---

### Task 3: Frozen seed manifest

**Files:**

- Create: `09_Разработка/backend/migrations/b04/seeds.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_seeds.py`
- Generate: `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/seed-manifest.json`

**Interfaces:**

- Produces:
  - `EXPECTED_DEFECT_TYPES: tuple[Mapping[str, object], ...]`;
  - `EXPECTED_DEFECT_LOCATION_TYPES: tuple[Mapping[str, object], ...]`;
  - `seed_manifest() -> dict[str, object]`;
  - `seed_digest() -> str`.

- [ ] **Step 1: Write failing tests**

Tests must require exactly 8 defect types and 7 location types, stable UUIDs, unique
codes and `OTHER.requires_description is True`.

Required UUID anchors:

```python
assert by_code["CRACK"]["id"] == "e854686d-bbe4-52f3-86bc-b77b56b56163"
assert by_code["OTHER"]["id"] == "b0a460c4-c9f2-51e9-a493-b34acd3930da"
assert locations["WELD_METAL"]["id"] == "fba998ec-5405-5b87-8076-c6b121d38660"
assert locations["OTHER"]["id"] == "1f9e81a9-57af-5e88-b312-1f2f4b239c55"
```

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_seeds.py -q
```

Expected: import failure for `migrations.b04.seeds`.

- [ ] **Step 3: Implement frozen literals**

Copy all 15 accepted rows as JSON-compatible literals into `seeds.py`. Do not import
`app.quality.defect_seed`. Include every `requires_*` flag for defect types.

- [ ] **Step 4: Verify GREEN and artifact stability**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_seeds.py -q
& $PythonExe -m migrations.b04.seeds `
  --output migrations/baselines/canonical_baseline_v1/seed-manifest.json
```

Expected: tests pass; rerun is byte-identical.

- [ ] **Step 5: Review checkpoint**

Provide diff and proposed commit:
`chore(migrations): freeze canonical baseline seeds`.
Do not commit without separate confirmation.

---

### Task 4: PostgreSQL catalog fingerprint v1

**Files:**

- Create: `09_Разработка/backend/migrations/b04/fingerprint.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_fingerprint.py`

**Interfaces:**

- Consumes: source contract and seed policy.
- Produces:
  - `normalize_deparsed_expression(value: str | None) -> str | None`;
  - `canonicalize_fingerprint(value: Mapping[str, object]) -> bytes`;
  - `fingerprint_digest(value: Mapping[str, object]) -> str`;
  - `extract_fingerprint(connection: Connection) -> dict[str, object]`;
  - `assert_supported_catalog(fingerprint: Mapping[str, object]) -> None`.

- [ ] **Step 1: Write failing normalization tests**

Tests must prove:

- only whitespace outside quoted literals is normalized;
- casts, parentheses and operators are preserved;
- arrays are deterministically sorted except ordered column/key lists;
- OID, owner, ACL, stats, row counts and sequence counters are absent;
- unknown object classes fail closed.

```python
def test_b04_fp_001_digest_is_order_independent_for_named_objects() -> None:
    left = {"tables": [{"schema": "welding", "name": "b"}, {"schema": "hr", "name": "a"}]}
    right = {"tables": list(reversed(left["tables"]))}
    assert fingerprint_digest(left) == fingerprint_digest(right)
```

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_fingerprint.py -q
```

Expected: import failure for `migrations.b04.fingerprint`.

- [ ] **Step 3: Implement catalog extraction**

Use parameterized SQL against `pg_namespace`, `pg_class`, `pg_attribute`,
`pg_constraint`, `pg_index`, `pg_sequence` and `pg_depend`. Expressions must come from
`pg_get_expr`, `pg_get_constraintdef` and `pg_get_indexdef`.

The extractor must:

```python
CANONICAL_SCHEMAS = ("engineering", "hr", "project", "quality", "welding")
FINGERPRINT_FORMAT_VERSION = 1
SUPPORTED_POSTGRES_MAJOR = 16


def extract_fingerprint(connection: Connection) -> dict[str, object]:
    major = int(connection.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000
    if major != SUPPORTED_POSTGRES_MAJOR:
        raise FingerprintError("B04-FP-POSTGRES-MAJOR")
    # Execute the fixed catalog queries, assemble typed records, query exact seeds,
    # reject unsupported canonical relkinds/object classes, then return sorted data.
```

No query may use interpolated schema values; pass the exact schema array as a bound
parameter.

- [ ] **Step 4: Verify GREEN**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_fingerprint.py -q
```

Expected: all pure fixture/normalization tests pass without DB access.

- [ ] **Step 5: Review checkpoint**

Provide query list, diff and proposed commit:
`feat(migrations): add canonical fingerprint v1`.
Do not commit without separate confirmation.

---

### Task 5: Verification-only Alembic context and safety interlock

**Files:**

- Create: `09_Разработка/backend/migrations/b04/candidate_alembic.ini`
- Create: `09_Разработка/backend/migrations/b04/candidate_context/env.py`
- Create: `09_Разработка/backend/migrations/b04/candidate_context/script.py.mako`
- Create directory: `09_Разработка/backend/migrations/baseline_candidates/`
- Create: `09_Разработка/backend/migrations/b04/disposable.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_disposable_safety.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_candidate_context.py`

**Interfaces:**

- Produces:
  - `assert_disposable_database(database_url: str, *, opt_in: str | None, ownership_token: str | None, expected_database: str | None) -> DatabaseIdentity`;
  - candidate context using only `WELDPASSPORT_B04_DATABASE_URL`.

- [ ] **Step 1: Write failing safety tests**

Reject:

- missing `WELDPASSPORT_B04_ALLOW_DESTRUCTIVE=YES`;
- missing ownership token;
- database-name mismatch;
- system/production names;
- URLs equal to ordinary application settings;
- non-PostgreSQL URLs;
- PostgreSQL major other than 16.

Accept only a name beginning `wp_b04_` and ending `_disposable`.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_disposable_safety.py `
  migration_contract_tests/test_b04_candidate_context.py -q
```

Expected: missing modules/context.

- [ ] **Step 3: Implement the fail-closed boundary**

The candidate context must:

- read only `WELDPASSPORT_B04_DATABASE_URL`;
- call `assert_disposable_database` before `create_engine`;
- use `canonical_metadata`;
- use the accepted canonical `include_name` and `include_object` filters;
- use `version_table_schema="public"` and `version_table_pk=True`;
- set `include_schemas=True`;
- point `version_locations` only to `migrations/baseline_candidates`;
- never import active revision modules;
- never fall back to `settings.database_url`.

- [ ] **Step 4: Verify GREEN**

Run the same pure tests. Expected: all pass without opening a socket.

- [ ] **Step 5: Review checkpoint**

Provide diff and proposed commit:
`test(migrations): add B-04 disposable candidate context`.
Do not commit without separate confirmation.

---

### Task 6: Generate and harden `canonical_baseline_v1`

**Files:**

- Generate: `09_Разработка/backend/migrations/baseline_candidates/canonical_baseline_v1.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_baseline_candidate.py`

**Interfaces:**

- Consumes: candidate context, frozen seeds and governed DB-only index contract.
- Produces: self-contained revision `canonical_baseline_v1`.

- [ ] **Step 1: Write failing AST contracts**

Require:

- exact revision and `down_revision=None`;
- no `app.*`, `migrations.*`, filesystem reads, bind inspection or `create_all`;
- five strict `CREATE SCHEMA` operations before tables;
- 73 `op.create_table` calls;
- governed index and 15 literal seeds;
- offline-safe operations only;
- downgrade touches only canonical schemas.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_baseline_candidate.py -q
```

Expected: candidate file is absent.

- [ ] **Step 3: Generate the candidate**

Against a verified empty disposable database:

```powershell
& $PythonExe -m alembic `
  -c migrations/b04/candidate_alembic.ini `
  revision --autogenerate `
  --rev-id canonical_baseline_v1 `
  -m "canonical baseline v1"
```

Expected: one file under `migrations/baseline_candidates`, `down_revision=None`.

- [ ] **Step 4: Apply deterministic hardening**

Before generated table operations add strict schema creation:

```python
for schema in ("hr", "welding", "project", "engineering", "quality"):
    op.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
```

Add the exact DB-only partial index and 15 literal seed inserts. Remove any import of
application modules. Downgrade must drop canonical objects in reverse dependency order
and never drop `public` or `test`.

- [ ] **Step 5: Verify GREEN**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_baseline_candidate.py -q
& $PythonExe -m alembic `
  -c migrations/b04/candidate_alembic.ini `
  upgrade canonical_baseline_v1 --sql | Out-Null
```

Expected: AST contracts pass and offline SQL renders without a database connection.

- [ ] **Step 6: Review checkpoint**

Provide the full generated diff and proposed commit:
`feat(migrations): add canonical baseline v1 candidate`.
Do not commit without separate confirmation.

---

### Task 7: Two-database equivalence runner

**Files:**

- Create: `09_Разработка/backend/migrations/b04/verify_baseline.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_verify_runner.py`
- Generate after execution:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/expected-fingerprint.json`
- Generate after execution:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/expected-fingerprint.sha256`
- Generate after execution:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/verification-report.json`

**Interfaces:**

- Consumes two explicit disposable URLs:
  `WELDPASSPORT_B04_HISTORICAL_URL` and `WELDPASSPORT_B04_BASELINE_URL`.
- Produces `verify_equivalence(config: VerificationConfig) -> VerificationReport`.

- [ ] **Step 1: Write failing orchestration tests**

Using fake command/connection adapters, require order:

```text
safety both DBs
→ historical upgrade head
→ historical fingerprint
→ baseline upgrade
→ baseline fingerprint
→ equality
→ baseline downgrade base
→ absence check
→ baseline re-upgrade
→ repeat fingerprint
→ report
```

Any failure must stop later steps and produce no accepted report.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_verify_runner.py -q
```

Expected: missing runner.

- [ ] **Step 3: Implement dependency-injected runner**

`VerificationConfig` must carry both URLs, tokens, expected database names, source SHA
and artifact paths. Subprocess calls must pass explicit environments and must not inherit
ordinary `POSTGRES_*` values.

For historical replay, parse only the already validated historical URL and construct a
fresh subprocess environment with exact `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_SCHEMA=test`. These values override
`.env`; none may be logged. The baseline subprocess receives only the candidate-context
variables and never ordinary `POSTGRES_*`.

- [ ] **Step 4: Verify pure GREEN**

Run the focused test. Expected: all orchestration/failure-injection tests pass.

- [ ] **Step 5: Run PostgreSQL evidence**

Only after the operator provisions two empty disposable PostgreSQL 16.x databases:

```powershell
$env:WELDPASSPORT_B04_ALLOW_DESTRUCTIVE = "YES"
if (-not $env:WELDPASSPORT_B04_OWNERSHIP_TOKEN) {
    throw "Ownership token must be supplied through the approved secret channel"
}
& $PythonExe -m migrations.b04.verify_baseline
```

The actual URLs and token are supplied through the approved secret channel and are never
printed or committed.

Expected:

- historical and baseline digests identical;
- 73 tables;
- 15 exact seeds;
- one governed DB-only index;
- baseline downgrade removes canonical objects only;
- re-upgrade digest identical;
- report status `B04A_VERIFIED`.

- [ ] **Step 6: Run complete B-04A acceptance**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall migrations/b04 migrations/baseline_candidates
git diff --check
```

Expected: zero failures and clean whitespace.

- [ ] **Step 7: Review checkpoint**

Provide:

- changed-file list;
- complete diff;
- pure test count;
- PostgreSQL evidence without credentials;
- artifact digests;
- proposed commit `test(migrations): verify canonical baseline equivalence`.

Do not commit without separate confirmation.

---

### Task 8: B-04A documentation closure

**Files:**

- Modify: `docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/project/PROJECT_STATUS.yaml`
- Modify: `docs/project/ROADMAP.md`

**Interfaces:**

- Consumes accepted B-04A evidence.
- Produces canonical status `B-04A done; B-04B blocked pending maintenance readiness`.

- [ ] **Step 1: Record only observed evidence**

Include exact commits, test counts, fingerprint digests, PostgreSQL version, source SHA
and explicit statement that active graph/marker/working DB were not changed.

- [ ] **Step 2: Verify documentation consistency**

```powershell
rg -n "B-04|canonical_baseline_v1|migration freeze" `
  docs/ARCHITECTURE.md `
  docs/project/DECISIONS.md `
  docs/project/TASK_REGISTRY.md `
  docs/project/PROJECT_STATUS.yaml `
  docs/project/ROADMAP.md
git diff --check
```

Expected: no contradictory statuses; freeze remains active.

- [ ] **Step 3: Final B-04A review checkpoint**

Do not activate the baseline and do not start B-04B until B-04A receives a separate
acceptance verdict.
