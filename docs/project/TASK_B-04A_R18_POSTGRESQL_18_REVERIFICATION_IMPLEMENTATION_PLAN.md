# B-04A-R18 PostgreSQL 18 Re-verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести B-04 verification tooling на PostgreSQL 18 fingerprint v2 и
опубликовать отдельный immutable evidence set без изменения PG16 evidence, baseline,
active migration graph или working DB.

**Architecture:** Existing B-04A runner сохраняет two-database equivalence flow.
Версионные constants и fail-closed endpoint preflight переводятся на PG18, а новый
evidence layer отделяет immutable PG16 history от pending/accepted PG18 evidence.
Authorizing status назначается только отдельным acceptance change после evidence review.

**Tech Stack:** Python 3.12, pytest 8, SQLAlchemy 2, Alembic, PostgreSQL 18.x,
psycopg 3, SHA-256, canonical JSON.

## Global Constraints

- Implementation code baseline:
  `e87800e771f5a39bd55cd745c532657c89f06516`.
- Documentation parent: `4c93a3bac94272ae454ca1423d135df2d5e38bc3`.
- Schema source cut:
  `6c56f99edbd4e7346264ee14658d2076b5fd0775`.
- Frozen graph: 31 revisions; root `20260702_02_hr_core`; head
  `20260724_27_qd_rbac_sod`.
- Baseline candidate: `canonical_baseline_v1.py`, byte-identical.
- Fingerprint format: `2`; supported PostgreSQL major: `18`.
- Canonical scope: 5 schemas, 73 tables, 15 governed seeds.
- Seven PG16 artifacts and their hashes from the specification are immutable.
- Working DB, application `.env`, application tests and B-04B are forbidden.
- Migration freeze remains active.
- No stage, commit, push, Docker cleanup or evidence promotion without a separate
  user confirmation.

PowerShell commands run from:

```text
D:\WeldPassport\.worktrees\b04a-r18-reverification\09_Разработка\backend
```

Implementation branch:

```text
codex/b04a-r18-reverification
```

Python:

```powershell
$PythonExe = "D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe"
```

---

### Task 1: Immutable source and evidence-versioning contracts

**Files:**

- Create: `09_Разработка/backend/migrations/b04/evidence.py`
- Create: `09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py`
- Create: `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/evidence-index.json`

**Interfaces:**

- Consumes: source constants, shared artifact paths and canonical JSON serializer.
- Produces:
  - `EvidenceStatus` string enum;
  - `EvidenceSet` frozen dataclass;
  - `Pg18EvidenceContract` frozen dataclass;
  - `validate_evidence_index(value: Mapping[str, object]) -> None`;
  - `validate_pg18_contract(value: Mapping[str, object]) -> None`;
  - `resolve_authorizing_evidence(value: Mapping[str, object], artifact_root: Path) -> EvidenceSet`;
  - `PG16_ARTIFACT_SHA256: Mapping[str, str]`.

- [ ] **Step 1: Write failing immutable-evidence tests**

Tests must load all seven PG16 artifacts and compare exact SHA-256 values from the
specification. Structural tests reject unknown keys, duplicate evidence IDs, more than
one `active_authorizing` set, PG16 authorization and PG18 authorization without exact
acceptance fields. Resolver tests reject absent contract/report, report digest mismatch,
evidence ID/major/format mismatch and path escape outside `artifact_root`.

```python
def test_b04_r18_evidence_001_pg16_artifacts_are_byte_identical() -> None:
    for name, expected in PG16_ARTIFACT_SHA256.items():
        assert hashlib.sha256((ARTIFACT_DIR / name).read_bytes()).hexdigest() == expected


def test_b04_r18_evidence_002_initial_index_is_not_authorizing() -> None:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    validate_evidence_index(index)
    statuses = {item["evidence_id"]: item["status"] for item in index["evidence_sets"]}
    assert statuses["postgresql-16-fingerprint-v1"] == "historical_non_authorizing"
    assert statuses["postgresql-18-fingerprint-v2"] == "candidate_pending_verification"
```

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_evidence_versioning.py -q
```

Expected: missing `migrations.b04.evidence` and `evidence-index.json`.

- [ ] **Step 3: Implement strict typed validators**

```python
class EvidenceStatus(StrEnum):
    HISTORICAL_NON_AUTHORIZING = "historical_non_authorizing"
    CANDIDATE_PENDING_VERIFICATION = "candidate_pending_verification"
    CANDIDATE_PENDING_ACCEPTANCE = "candidate_pending_acceptance"
    ACTIVE_AUTHORIZING = "active_authorizing"


@dataclass(frozen=True, slots=True)
class EvidenceSet:
    evidence_id: str
    status: EvidenceStatus
    postgres_major: int
    fingerprint_format_version: int
    artifact_sha256: Mapping[str, str]
    contract_path: str | None
    acceptance: Mapping[str, str] | None


@dataclass(frozen=True, slots=True)
class Pg18EvidenceContract:
    evidence_id: str
    source_sha: str
    implementation_sha: str
    postgres_major: int
    fingerprint_format_version: int
    shared_artifact_sha256: Mapping[str, str]
```

Structural validation uses exact-key sets. The initial index contains PG16 historical
and PG18 pending-verification entries only. The PG18 index entry names
`postgresql-18/contract.json`, but the contract must not exist before an accepted
implementation SHA is available. Initial `acceptance` is `null`; structurally, an
`active_authorizing` entry is valid only with exact acceptance keys
`accepted_at_utc`, `accepted_by`, `verification_report_sha256`, where
`accepted_by = repository_owner`. `resolve_authorizing_evidence()` then performs
filesystem existence, containment and digest checks before returning the active set.
Absent/ambiguous active evidence raises `EvidenceError("B04-EVIDENCE-NO-ACTIVE")`;
invalid paths or digests raise stable `B04-EVIDENCE-*` errors and never return `None`.

- [ ] **Step 4: Verify GREEN**

Run the focused test and confirm all negative cases pass.

- [ ] **Step 5: Review checkpoint**

Provide `evidence-index.json`, exact PG16 hash proof and diff. Do not commit.

---

### Task 2: PostgreSQL 18 endpoint preflight before Alembic

**Files:**

- Modify: `09_Разработка/backend/migrations/b04/disposable.py`
- Modify: `09_Разработка/backend/migrations/b04/candidate_context/env.py`
- Modify: `09_Разработка/backend/migrations/b04/verify_baseline.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_b04_disposable_safety.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_b04_candidate_context.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_b04_verify_runner.py`

**Interfaces:**

- Produces:
  - `PostgresVersion(server_version_num: int, major: int)`;
  - `assert_postgresql_18(connection: Any) -> PostgresVersion`;
  - `VerificationConfig.version_validator`;
  - preflight equality of historical/baseline exact versions.

- [ ] **Step 1: Write failing PG18 safety tests**

```python
def test_b04_r18_version_001_accepts_postgresql_18() -> None:
    result = assert_postgresql_18(_FakeConnection("180003"))
    assert result == PostgresVersion(server_version_num=180003, major=18)


@pytest.mark.parametrize("value", ["160014", "170009", "190001"])
def test_b04_r18_version_002_rejects_every_non_18_major(value: object) -> None:
    with pytest.raises(ValueError, match="B04-DISPOSABLE-POSTGRESQL-18"):
        assert_postgresql_18(_FakeConnection(value))


@pytest.mark.parametrize("value", ["invalid", None, True])
def test_b04_r18_version_003_rejects_malformed_version(value: object) -> None:
    with pytest.raises(ValueError, match="B04-DISPOSABLE-POSTGRESQL-VERSION"):
        assert_postgresql_18(_FakeConnection(value))
```

Runner tests record events and prove both version checks occur before
`historical-upgrade`. A mismatch such as `180003` versus `180004` must raise
`B04-VERIFY-POSTGRESQL-VERSION-MISMATCH` before any command-runner event.
Disposable URL tests must accept only host `127.0.0.1` and reject `localhost`, IPv6 and
every remote hostname/address before a connection is opened.

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_disposable_safety.py `
  migration_contract_tests/test_b04_candidate_context.py `
  migration_contract_tests/test_b04_verify_runner.py -q
```

Expected: missing PG18 interface and old PG16 assertions.

- [ ] **Step 3: Implement exact version validation**

```python
@dataclass(frozen=True, slots=True)
class PostgresVersion:
    server_version_num: int
    major: int


def assert_postgresql_18(connection: Any) -> PostgresVersion:
    raw = connection.exec_driver_sql("SHOW server_version_num").scalar_one()
    value = str(raw)
    if isinstance(raw, bool) or re.fullmatch(r"[0-9]{6,}", value) is None:
        raise ValueError("B04-DISPOSABLE-POSTGRESQL-VERSION")
    number = int(value)
    if number // 10_000 != 18:
        raise ValueError("B04-DISPOSABLE-POSTGRESQL-18")
    return PostgresVersion(server_version_num=number, major=18)
```

`assert_disposable_database()` also requires `host == "127.0.0.1"`.
`verify_equivalence()` opens both injected connections, validates versions, closes
them, compares exact numbers and only then invokes historical Alembic.

- [ ] **Step 4: Verify GREEN**

Run the focused tests. Confirm the event list contains no Alembic call for every
rejected or mismatched version.

- [ ] **Step 5: Review checkpoint**

Provide the ordered preflight event proof and sanitized error inventory. Do not commit.

---

### Task 3: PostgreSQL 18 fingerprint format v2

**Files:**

- Modify: `09_Разработка/backend/migrations/b04/fingerprint.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_b04_fingerprint.py`

**Interfaces:**

- Produces unchanged public functions:
  - `extract_fingerprint(connection: Connection) -> dict[str, object]`;
  - `canonicalize_fingerprint(value: Mapping[str, object]) -> bytes`;
  - `fingerprint_digest(value: Mapping[str, object]) -> str`.
- Constants become `FINGERPRINT_FORMAT_VERSION = 2` and
  `SUPPORTED_POSTGRES_MAJOR = 18`.

- [ ] **Step 1: Write failing v2 tests**

Update fake connections to `180003`. Assert format version `2`, major guard `18`,
deterministic bytes under input reordering, exact-key rejection, unsupported-object
rejection, seed exactness and normalization idempotence.

```python
def test_b04_r18_fingerprint_001_emits_v2() -> None:
    value, _ = _extract(_complete_routes(), version="180003")
    assert value["format_version"] == 2


def test_b04_r18_fingerprint_002_rejects_pg16() -> None:
    with pytest.raises(FingerprintError, match="B04-FP-POSTGRES-MAJOR"):
        _extract(_complete_routes(), version="160014")
```

- [ ] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_fingerprint.py -q
```

- [ ] **Step 3: Implement minimal v2 contract**

Change only the version constants and PG18 catalog/deparse normalization proven by a
failing contract or real disposable PG18 observation. Do not alter canonical scope or
hide differing objects.

- [ ] **Step 4: Verify GREEN**

Run fingerprint, seed, baseline-candidate and metadata-alignment contracts together:

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_fingerprint.py `
  migration_contract_tests/test_b04_seeds.py `
  migration_contract_tests/test_b04_baseline_candidate.py `
  migration_contract_tests/test_b04_metadata_alignment.py -q
```

- [ ] **Step 5: Review checkpoint**

Provide every SQL/normalization change and explain the PG18 catalog fact that requires
it. Unexplained normalization changes are rejected.

---

### Task 4: Versioned PG18 report and atomic publication

**Files:**

- Modify: `09_Разработка/backend/migrations/b04/verify_baseline.py`
- Modify: `09_Разработка/backend/migrations/b04/evidence.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_b04_verify_runner.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py`
- Generate after implementation acceptance:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/contract.json`

**Interfaces:**

- `VerificationReport` adds:
  - `evidence_id`;
  - `implementation_sha`;
  - `postgres_major`;
  - `server_version_num`;
  - `fingerprint_format_version`;
  - `shared_artifact_sha256`.
- Output paths are confined to `canonical_baseline_v1/postgresql-18/`.

- [ ] **Step 1: Write failing report/publication tests**

Require exact report keys, exact `180003`, format `2`, three equal digests, matching
implementation SHA and shared hashes. Reject wrong directory, existing target,
symlink, partial target set and unknown report keys.

```python
def test_b04_r18_report_001_is_pending_not_authorizing(tmp_path: Path) -> None:
    report = verify_equivalence(_config(tmp_path, implementation_sha="a" * 40))
    assert report.status == "B04A_VERIFIED"
    assert report.postgres_major == 18
    assert report.server_version_num == 180003
    assert report.fingerprint_format_version == 2
    report_path = tmp_path / "postgresql-18" / "verification-report.json"
    assert "active_authorizing" not in report_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Verify RED**

Run both focused test files.

- [ ] **Step 3: Implement versioned config and report**

`VerificationConfig.from_environment()` requires
`WELDPASSPORT_B04_IMPLEMENTATION_SHA` and points all generated artifacts to
`migrations/baselines/canonical_baseline_v1/postgresql-18/`.

Publication order after the implementation SHA is known:

```text
validate contract/index/shared hashes
→ create all temporary files in postgresql-18/
→ hard-link contract.json
→ hard-link expected-fingerprint.json
→ hard-link expected-fingerprint.sha256
→ hard-link verification-report.json
→ remove temporary files
→ change index only to candidate_pending_acceptance with acceptance=null
```

Any failure removes only files published by the current attempt and leaves PG16
artifacts and the prior index intact.

- [ ] **Step 4: Verify GREEN**

Run focused tests including failure injection at every publication boundary.

- [ ] **Step 5: Review checkpoint**

Provide canonical report bytes, digest line, index transition diff and failure-injection
results. Do not execute PostgreSQL and do not commit.

---

### Task 5: Pure code acceptance

**Files:**

- No new files beyond Tasks 1-4.

**Interfaces:**

- Produces reviewed code candidate only; no accepted evidence.

- [ ] **Step 1: Run focused suite**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_evidence_versioning.py `
  migration_contract_tests/test_b04_disposable_safety.py `
  migration_contract_tests/test_b04_candidate_context.py `
  migration_contract_tests/test_b04_fingerprint.py `
  migration_contract_tests/test_b04_verify_runner.py -q
```

- [ ] **Step 2: Run full pure migration suite**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall -q migrations/b04 migration_contract_tests
git diff --check
```

- [ ] **Step 3: Verify immutable boundaries**

```powershell
git diff --name-only 6c56f99edbd4e7346264ee14658d2076b5fd0775..HEAD -- migrations/versions
git diff -- migrations/baseline_candidates/canonical_baseline_v1.py
```

Expected: no output. Recompute all seven PG16 artifact hashes and compare with the spec.

- [ ] **Step 4: Independent read-only review**

Reviewer checks fail-closed ordering, secrets, exact-key JSON validation, immutable
publication, no working DB fallback and complete test coverage.

- [ ] **Step 5: Stop for implementation acceptance**

Provide changed files, full diff, exact test counts and proposed commit:

```text
feat(migrations): add PostgreSQL 18 baseline verification
```

Do not stage or commit without separate confirmation.

---

### Task 6: Disposable PG18 evidence and separate acceptance

**Files:**

- Generate:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/contract.json`
- Generate:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/expected-fingerprint.json`
- Generate:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/expected-fingerprint.sha256`
- Generate:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/verification-report.json`
- Modify after successful run:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/evidence-index.json`

**Interfaces:**

- Consumes: separately accepted implementation commit and two owned empty PG18
  disposable databases.
- Produces: `candidate_pending_acceptance` evidence only.

- [ ] **Step 1: Operator preflight**

Record sanitized identities, exact same `server_version_num`, empty canonical schemas,
ownership proof and implementation SHA. Stop on any mismatch.

- [ ] **Step 2: Run one equivalence verification**

Set only the explicit B-04 environment variables in the current PowerShell process and
run:

```powershell
& $PythonExe -m migrations.b04.verify_baseline
```

No automatic retry is allowed.

- [ ] **Step 3: Verify generated evidence**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_evidence_versioning.py `
  migration_contract_tests/test_b04_verify_runner.py -q
git diff --check
```

Confirm four PG18 artifact hashes, three equal v2 fingerprint digests, exact version,
report status `B04A_VERIFIED`, pending index status and unchanged PG16 hashes.

- [ ] **Step 4: Stop for evidence review**

Provide sanitized operator output, artifact hashes, full diff and database cleanup plan.
Do not clean up, stage, commit or promote the index.

- [ ] **Step 5: Separate B-04A-R18 acceptance**

Only after explicit owner acceptance, change the PG18 index entry from
`candidate_pending_acceptance` to `active_authorizing`, record the accepted evidence
commit in canonical status documents and rerun pure verification.

- [ ] **Step 6: Preserve the next gate**

B-04B remains `BLOCKED`. The next action is a new READ-ONLY Maintenance Readiness
Review; B-04B tooling or adoption must not start in this plan.
