# B-04R Candidate-State Test Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Do not
> delegate unless the repository owner explicitly requests subagents. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make B-04R pure contract tests pass in the exact
`candidate_pending_acceptance` repository state without changing runtime code,
candidate evidence bytes, restore index bytes or PostgreSQL state.

**Architecture:** Test sandboxes copy only the four immutable live PG18
artifacts by explicit allowlist and create their own canonical empty restore
index. The repository-state test remains lifecycle-exact: this plan changes it
from pre-generation empty-state to the current pending-state and proves pending
evidence is physically valid but non-authorizing.

**Tech Stack:** Python 3, pytest, pathlib, shutil, hashlib, canonical JSON,
Git/PowerShell.

Статус: **COMPLETED / PROMOTION COMMIT ACCEPTED / B-04B-1 READINESS READY 2026-07-29**

## Global Constraints

- Accepted Specification:
  `docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_SPEC.md`.
- Accepted runtime implementation SHA:
  `65f3a28855eb0830077117fa26d9bbf789f50cb5`.
- Current restore evidence status:
  `active_restore_authorizing`; exact repository-owner acceptance recorded at
  `2026-07-29T08:55:32Z`.
- Modify test code only in:
  - `migration_contract_tests/test_b04_restore_evidence.py`;
  - `migration_contract_tests/test_b04_restore_roundtrip_runner.py`;
  - `migration_contract_tests/test_b04_evidence_versioning.py`.
- Do not modify `migrations/b04/**`.
- Do not modify the five candidate artifacts, `restore-evidence-index.json`,
  existing live evidence or `evidence-index.json`.
- Do not connect to PostgreSQL, run Alembic, repeat restore or clean disposable
  databases.
- Do not stage, commit, push or promote evidence without separate owner
  authorization.
- Preserve existing owner documentation and candidate-evidence working-tree
  changes.
- Do not include line-ending-only or unrelated files.

---

### Task 1: Freeze exact candidate state and preserve RED evidence

**Files:**

- Read:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/restore-evidence-index.json`
- Read:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/restore-roundtrip-v1/*`
- Read:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/postgresql-18/{contract.json,expected-fingerprint.json,expected-fingerprint.sha256,verification-report.json}`
- Read:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py`
- Read:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py`

**Interfaces:**

- Consumes: current owner-generated pending index and artifact files.
- Produces: external before-hash manifest and exact RED result; no repository
  writes.

- [ ] **Step 1: Verify the execution base**

```powershell
git rev-parse HEAD
git status --short
```

Require HEAD:

```text
65f3a28855eb0830077117fa26d9bbf789f50cb5
```

Existing working-tree changes must include pending restore evidence and owner
documentation only. Stop if either test file is already modified or staged.

- [ ] **Step 2: Create an external immutable before-hash manifest**

Run from `09_Разработка/backend`:

```powershell
$PythonExe = "C:\Users\Andrey\AppData\Local\Programs\Python\Python314\python.exe"
@'
import hashlib
import json
from pathlib import Path

root = Path("migrations/baselines/canonical_baseline_v1")
paths = [
    root / "restore-evidence-index.json",
    root / "evidence-index.json",
    root / "postgresql-18/contract.json",
    root / "postgresql-18/expected-fingerprint.json",
    root / "postgresql-18/expected-fingerprint.sha256",
    root / "postgresql-18/verification-report.json",
    root / "postgresql-18/restore-roundtrip-v1/contract.json",
    root / "postgresql-18/restore-roundtrip-v1/expected-fingerprint.json",
    root / "postgresql-18/restore-roundtrip-v1/expected-fingerprint.sha256",
    root / "postgresql-18/restore-roundtrip-v1/equivalence-map.json",
    root / "postgresql-18/restore-roundtrip-v1/verification-report.json",
]
value = {
    path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in paths
}
output = Path(
    r"D:\WeldPassport_Backups\B04B\b04r_candidate_test_remediation_before.json"
)
if output.exists():
    raise RuntimeError("B04R before-hash manifest target already exists")
output.write_text(
    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print(f"B04R_BEFORE_HASHES={len(value)}")
'@ | & $PythonExe -
```

Expected:

```text
B04R_BEFORE_HASHES=11
```

- [ ] **Step 3: Confirm current pending state**

```powershell
@'
import json
from pathlib import Path

path = Path("migrations/baselines/canonical_baseline_v1/restore-evidence-index.json")
value = json.loads(path.read_bytes())
entry = value["evidence_sets"][0]
assert len(value["evidence_sets"]) == 1
assert entry["status"] == "candidate_pending_acceptance"
assert entry["acceptance"] is None
assert len(entry["artifact_sha256"]) == 5
print("B04R_PENDING_STATE_OK")
'@ | & $PythonExe -
```

- [ ] **Step 4: Reproduce the accepted RED**

Use a new external `basetemp`:

```powershell
$RedRoot = "D:\WeldPassport_Backups\B04B\b04r_candidate_test_remediation_red"
New-Item -ItemType Directory -Path $RedRoot -Force | Out-Null
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  --basetemp (Join-Path $RedRoot "pytest-001") -q
```

Expected current-state evidence:

```text
44 passed, 15 failed
```

Failures must be limited to:

- the empty repository-index assertion;
- `_write_candidate_artifacts()` inheriting repository restore artifacts;
- `_publication_root()` inheriting pending index/restore artifacts.

- [ ] **Step 5: Review checkpoint**

Report HEAD, the 11 before hashes, exact RED counts and failure ownership. Stop
if any failure has another cause.

---

### Task 2: Isolate restore-evidence test fixtures and assert exact pending state

**Files:**

- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py`

**Interfaces:**

- Consumes: `LIVE_ARTIFACT_SHA256`, `ARTIFACT_ROOT`, `RESTORE_INDEX`,
  `LIVE_INDEX`, `canonical_json_bytes()`,
  `validate_restore_evidence_index()` and
  `resolve_restore_authorizing_evidence()`.
- Produces:
  `_copy_live_evidence_only(root: Path) -> Path` and an exact pending
  repository-state contract test.

- [ ] **Step 1: Replace the pre-generation repository assertion with pending-state RED**

Rename:

```python
test_b04r_index_001_repository_index_is_empty_and_non_authorizing
```

to:

```python
test_b04r_index_001_repository_candidate_is_exact_and_non_authorizing
```

The test must:

```python
raw = RESTORE_INDEX.read_bytes()
value = json.loads(raw)
assert raw == canonical_json_bytes(value)
validate_restore_evidence_index(value)
assert len(value["evidence_sets"]) == 1
entry = value["evidence_sets"][0]
assert entry["evidence_id"] == "postgresql-18-restore-roundtrip-v1"
assert entry["status"] == "candidate_pending_acceptance"
assert entry["acceptance"] is None
assert set(entry["artifact_sha256"]) == set(RESTORE_EXPECTED_ARTIFACTS)

restore_dir = ARTIFACT_ROOT / "postgresql-18" / "restore-roundtrip-v1"
for name, expected in entry["artifact_sha256"].items():
    assert hashlib.sha256((restore_dir / name).read_bytes()).hexdigest() == expected

live_index = json.loads(LIVE_INDEX.read_bytes())
with pytest.raises(RestoreEvidenceError, match="B04R-ACCEPTANCE"):
    resolve_restore_authorizing_evidence(value, ARTIFACT_ROOT, live_index)
```

Do not accept both pending and active statuses.

- [ ] **Step 2: Add the live-only fixture helper**

Add:

```python
def _copy_live_evidence_only(root: Path) -> Path:
    live_dir = root / "postgresql-18"
    live_dir.mkdir()
    for name in LIVE_ARTIFACT_SHA256:
        source = ARTIFACT_ROOT / "postgresql-18" / name
        target = live_dir / name
        if source.is_symlink() or not source.is_file() or target.exists():
            raise AssertionError("B04R test fixture live artifact boundary")
        shutil.copy2(source, target)
    if (live_dir / "restore-roundtrip-v1").exists():
        raise AssertionError("B04R test fixture inherited restore evidence")
    return live_dir
```

The helper uses the existing four-key `LIVE_ARTIFACT_SHA256` allowlist. It must
not call `copytree()`.

- [ ] **Step 3: Use the helper in `_write_candidate_artifacts()`**

Replace:

```python
shutil.copytree(ARTIFACT_ROOT / "postgresql-18", root / "postgresql-18")
restore_dir = root / "postgresql-18" / "restore-roundtrip-v1"
```

with:

```python
live_dir = _copy_live_evidence_only(root)
restore_dir = live_dir / "restore-roundtrip-v1"
```

Keep the existing `restore_dir.mkdir()` and generated test payload logic.

- [ ] **Step 4: Run the restore-evidence focused file**

```powershell
$GreenRoot = "D:\WeldPassport_Backups\B04B\b04r_candidate_test_remediation_green"
New-Item -ItemType Directory -Path $GreenRoot -Force | Out-Null
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  --basetemp (Join-Path $GreenRoot "pytest-evidence-001") -q
```

Expected: every test in this file passes. Do not infer runner-file success.

- [ ] **Step 5: Review checkpoint**

Return the exact diff for this file and its focused count. Do not stage or
commit.

---

### Task 3: Isolate publication fixtures from repository lifecycle state

**Files:**

- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py`

**Interfaces:**

- Consumes: `ARTIFACT_ROOT`, `canonical_json_bytes()`, `shutil.copy2`.
- Produces:
  `_empty_restore_index() -> dict[str, object]`,
  `_copy_live_evidence_only(root: Path) -> Path`, and lifecycle-independent
  `_publication_root(tmp_path: Path) -> Path`.

- [ ] **Step 1: Import canonical JSON support**

Add:

```python
from migrations.b04.manifest import canonical_json_bytes
```

- [ ] **Step 2: Define the exact live artifact allowlist and empty index**

Add near the existing constants:

```python
LIVE_ARTIFACT_NAMES = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "verification-report.json",
)


def _empty_restore_index() -> dict[str, object]:
    return {
        "format_version": 1,
        "baseline_id": "canonical_baseline_v1",
        "live_evidence_id": "postgresql-18-fingerprint-v2",
        "evidence_sets": [],
    }
```

- [ ] **Step 3: Add a local live-only copy helper**

Add:

```python
def _copy_live_evidence_only(root: Path) -> Path:
    live_dir = root / "postgresql-18"
    live_dir.mkdir()
    for name in LIVE_ARTIFACT_NAMES:
        source = ARTIFACT_ROOT / "postgresql-18" / name
        target = live_dir / name
        if source.is_symlink() or not source.is_file() or target.exists():
            raise AssertionError("B04R publication fixture live artifact boundary")
        shutil.copy2(source, target)
    if (live_dir / "restore-roundtrip-v1").exists():
        raise AssertionError("B04R publication fixture inherited restore evidence")
    return live_dir
```

- [ ] **Step 4: Rebuild `_publication_root()` from isolated inputs**

The function must become:

```python
def _publication_root(tmp_path: Path) -> Path:
    root = tmp_path / "canonical_baseline_v1"
    root.mkdir()
    shutil.copy2(
        ARTIFACT_ROOT / "evidence-index.json",
        root / "evidence-index.json",
    )
    (root / "restore-evidence-index.json").write_bytes(
        canonical_json_bytes(_empty_restore_index())
    )
    _copy_live_evidence_only(root)
    return root
```

Do not read or copy the repository pending restore index.

- [ ] **Step 5: Run the runner focused file**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  --basetemp (Join-Path $GreenRoot "pytest-runner-001") -q
```

Expected: every test in this file passes.

- [ ] **Step 6: Run the combined focused suite**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  --basetemp (Join-Path $GreenRoot "pytest-combined-001") -q
```

Expected:

```text
59 passed
```

- [ ] **Step 7: Review checkpoint**

Return both focused counts and the exact two-file diff. Do not stage or commit.

---

### Task 4: Assert exact live files and versioned restore directory

**Files:**

- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py`

**Interfaces:**

- Consumes: `PG18_ARTIFACT_NAMES` and `ARTIFACT_DIR` already defined by the
  PG18 evidence-versioning contract tests.
- Produces: an exact repository directory-shape assertion: four live regular
  files and one versioned restore directory, with no other entries.

- [ ] **Step 1: Preserve the observed RED evidence**

Use the already observed full-suite result:

```text
378 passed, 1 skipped, 1 failed
```

The exact failing test is:

```text
migration_contract_tests/test_b04_evidence_versioning.py::test_b04_r18_evidence_002_repository_index_is_active_authorizing
```

- [ ] **Step 2: Replace only the stale directory-shape assertion**

Replace the assertion that compares all `evidence_dir.iterdir()` names directly
with `PG18_ARTIFACT_NAMES` by:

```python
assert {
    path.name for path in evidence_dir.iterdir() if path.is_file()
} == set(PG18_ARTIFACT_NAMES)
assert {
    path.name for path in evidence_dir.iterdir() if path.is_dir()
} == {"restore-roundtrip-v1"}
```

Do not weaken any hash, index, status or resolver assertion in that test.

- [ ] **Step 3: Run the exact repaired test**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_evidence_versioning.py::test_b04_r18_evidence_002_repository_index_is_active_authorizing `
  --basetemp (Join-Path $GreenRoot "pytest-versioning-001") -q
```

Expected:

```text
1 passed
```

- [ ] **Step 4: Run the three-file focused regression**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  migration_contract_tests/test_b04_evidence_versioning.py `
  --basetemp (Join-Path $GreenRoot "pytest-three-files-001") -q
```

Expected: every test in the three files passes.

- [ ] **Step 5: Review checkpoint**

Return the exact one-file diff for
`migration_contract_tests/test_b04_evidence_versioning.py` and stop before the
full regression task.

---

### Task 5: Prove full regression and immutable evidence

**Files:**

- Modify after code review only:
  `docs/project/PROJECT_STATUS.yaml`
- Modify after code review only:
  `docs/project/TASK_REGISTRY.md`
- Modify after code review only:
  `docs/project/ROADMAP.md`
- Modify after code review only:
  `docs/project/PROJECT_SUMMARY.md`
- Modify after code review only:
  `docs/project/CHAT_INDEX.md`

**Interfaces:**

- Consumes: three accepted test diffs and the Task 1 before-hash manifest.
- Produces: complete remediation review packet and explicit stop before stage,
  commit or evidence acceptance.

- [ ] **Step 1: Run the full pure suite**

```powershell
& $PythonExe -m pytest migration_contract_tests `
  --basetemp (Join-Path $GreenRoot "pytest-full-001") -q
```

Expected:

```text
379 passed, 1 skipped
```

- [ ] **Step 2: Compile the modified test files**

```powershell
& $PythonExe -m py_compile `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  migration_contract_tests/test_b04_evidence_versioning.py
```

- [ ] **Step 3: Verify all immutable bytes against the before manifest**

```powershell
@'
import hashlib
import json
from pathlib import Path

before_path = Path(
    r"D:\WeldPassport_Backups\B04B\b04r_candidate_test_remediation_before.json"
)
before = json.loads(before_path.read_text(encoding="utf-8"))
after = {
    name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
    for name in before
}
assert after == before
print(f"B04R_IMMUTABLE_HASHES_OK={len(after)}")
'@ | & $PythonExe -
```

Expected:

```text
B04R_IMMUTABLE_HASHES_OK=11
```

- [ ] **Step 4: Verify scope and secrets**

```powershell
git diff --check
git diff --name-status
git diff -- `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  migration_contract_tests/test_b04_evidence_versioning.py
rg -n -i `
  "(postgresql\+psycopg://|password|passwd|secret|PGPASSWORD|127\.0\.0\.1|localhost)" `
  migrations/baselines/canonical_baseline_v1/postgresql-18/restore-roundtrip-v1
```

The artifact secret scan must return no matches. Existing credential-like fake
test values outside the generated artifacts are not part of this artifact scan.

- [ ] **Step 5: Confirm no forbidden operation occurred**

Require:

```text
PostgreSQL connections: 0
Alembic runs: 0
candidate artifact changes: 0
restore index changes by remediation: 0
runtime code changes: 0
staged files: 0
commits: 0
```

- [ ] **Step 6: Prepare the acceptance packet**

Return:

1. HEAD and branch;
2. exact three test files changed;
3. RED `44 passed, 15 failed`;
4. GREEN focused counts;
5. full `379 passed, 1 skipped`;
6. 11 immutable before/after hashes;
7. compile and `git diff --check`;
8. full three-file diff;
9. candidate status remains `candidate_pending_acceptance`;
10. explicit stop before stage/commit/evidence acceptance/promotion.

---

## Proposed commit boundary

Proposal only:

```text
test(migrations): isolate B-04R candidate-state fixtures
```

Do not create the commit without separate owner authorization.

## Plan acceptance criteria

- Specification sections 1–9 are covered.
- Only the three named test files change during code implementation.
- Existing 15 failures are the RED evidence.
- Fixtures copy only four explicit live artifact files.
- Publication fixtures use an exact canonical empty restore index.
- Repository-state test requires exact pending state and physical hashes.
- PG18 evidence-versioning test requires exactly four live regular files and
  exactly one directory named `restore-roundtrip-v1`.
- Pending resolver fails exactly `B04R-ACCEPTANCE`.
- Focused suite returns `59 passed`.
- Full suite returns `379 passed, 1 skipped`.
- Eleven governed evidence/index files remain byte-identical.
- No DB, promotion, cleanup, stage, commit or push occurs.

## Accepted scope amendment checkpoint

Observed after the accepted two-file implementation:

```text
focused: 59 passed
full: 378 passed, 1 skipped, 1 failed
```

The remaining failure was the exact live-directory assertion in
`migration_contract_tests/test_b04_evidence_versioning.py`.

The owner accepted the scope amendment on 2026-07-29. It adds only that test
file and changes its directory-shape assertion to require:

```python
assert {
    path.name for path in evidence_dir.iterdir() if path.is_file()
} == set(PG18_ARTIFACT_NAMES)
assert {
    path.name for path in evidence_dir.iterdir() if path.is_dir()
} == {"restore-roundtrip-v1"}
```

The owner separately authorized continuation pure implementation. The exact
test now returns `1 passed`, the three-file regression returns `98 passed`, and
the full suite returns `379 passed, 1 skipped`. The owner accepted the code,
separately authorized the implementation commit, and accepted SHA
`1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b` on 2026-07-29. No other code
or artifact change is permitted; evidence promotion requires a separate owner
authorization.

## Promotion completion checkpoint

The owner separately authorized evidence acceptance/promotion. The repository
index is canonical and exact:

```text
status=active_restore_authorizing
accepted_at_utc=2026-07-29T08:55:32Z
accepted_by=repository_owner
verification_report_sha256=5480a2e4e02a085f8378ee9617da0b9ad4c04aca4a42fd0a52b933b4b75554be
```

Promotion verification: exact `1 passed`, focused `98 passed`, full
`379 passed, 1 skipped`; ten non-index governed files remain byte-identical.
Promotion commit `abaada5aad7e53d94c00395adb1a0ff742c27dd5` was
separately accepted. The subsequent READ-ONLY Maintenance Readiness Review
returned owner-accepted `READY` for B-04B-1 on 2026-07-29. This does not
authorize marker transfer, production adoption, a DB run, commit, or push.
