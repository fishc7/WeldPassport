# B-04R Restore-Roundtrip Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

Статус: **EVIDENCE PROMOTED — active_restore_authorizing; promotion commit authorized**

Accepted candidate-state remediation SHA:
`1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b`.

Promotion acceptance:
`repository_owner`, `2026-07-29T08:55:32Z`, report SHA
`5480a2e4e02a085f8378ee9617da0b9ad4c04aca4a42fd0a52b933b4b75554be`.

Implementation base:
`08bc6a09974e0272ff27938511af5d4d6ba33403`.

Pure verification after remediation: focused `59 passed`; полный
`migration_contract_tests` — `379 passed, 1 skipped`; real read-only preflight —
`B04R-PREFLIGHT-OK`. Restore и генерация evidence не выполнялись.

**Goal:** Реализовать отдельный fail-closed PostgreSQL 18 restore-roundtrip
evidence contract, который сохраняет live evidence byte-identical, доказывает
двухкратный restore fixed point и публикует только pending evidence до отдельной
приёмки владельца.

**Architecture:** Новый `restore_evidence.py` владеет versioned index, exact-key
artifact contracts, typed structural diff и authorizing resolver. Новый
`verify_restore_roundtrip.py` владеет explicit-input runner: открывает working DB
только в read-only transaction, восстанавливает принятый custom archive в две
owned disposable DB, проверяет fixed point и атомарно публикует candidate artifacts.
Существующие `fingerprint.py`, live evidence и B-04B repository/adoption code не
изменяются.

**Tech Stack:** Python 3.12, pytest 8, SQLAlchemy 2, psycopg 3, PostgreSQL 18.3,
`pg_dump`/`pg_restore` 18.x, SHA-256, canonical JSON, PowerShell.

## Global Constraints

- Accepted architecture: ADR-031.
- Accepted specification:
  `TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_SPEC.md`, accepted 2026-07-29.
- Current review ancestor:
  `e3fad73145a41077052520e2cba9eb649e3716ce`.
- Implementation starts only from the exact owner-approved documentation commit
  containing ADR-031, accepted Spec, accepted plan and final Prompt.
- Schema source cut:
  `6c56f99edbd4e7346264ee14658d2076b5fd0775`.
- Existing live evidence ID: `postgresql-18-fingerprint-v2`.
- Existing live digest:
  `e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a`.
- New restore evidence ID: `postgresql-18-restore-roundtrip-v1`.
- PostgreSQL major: `18`; accepted live `server_version_num`: `180003`.
- Fingerprint format remains `2`.
- Canonical scope: 5 schemas, 73 tables, 6 sequences, 15 governed seeds.
- Existing seven PG16 artifacts, `evidence-index.json` and four PG18 live artifacts
  remain byte-identical.
- `migrations/b04/fingerprint.py`, baseline candidate, frozen revisions and active
  migration graph remain byte-identical.
- Working DB is read-only; B-04R never creates its backup and never changes domain
  data or Alembic markers.
- Exact disposable names:
  `wp_b04_r18_restore_first_disposable` and
  `wp_b04_r18_restore_second_disposable`.
- Application `.env` is never a fallback.
- Application pytest, Alembic upgrade/downgrade, repository cut, marker adoption and
  B-04B are forbidden.
- Migration freeze remains active.
- Stage, commit, push, DB run, evidence promotion and disposable cleanup require
  their own owner-authorized gate.

PowerShell commands run from:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness\09_Разработка\backend
```

Python is supplied explicitly:

```powershell
$PythonExe = $env:B04R_PYTHON_EXE
if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "B04R_PYTHON_EXE must point to the explicitly approved project Python interpreter"
}
```

---

### Pre-Task: Accepted-source and immutable-artifact gate

**Files:**

- Read:
  `docs/project/ADR-031-b04-dual-state-live-restore-evidence.md`
- Read:
  `docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_SPEC.md`
- Read:
  `docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_IMPLEMENTATION_PLAN.md`
- Read:
  `docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_CLAUDE_CODE_PROMPT.md`
- Read:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/`

**Interfaces:**

- Consumes: exact owner-approved documentation commit and current immutable
  artifact bytes.
- Produces: recorded base SHA and before-hash manifest used again in Task 6.

- [x] **Step 1: Verify the execution base**

```powershell
git status --short
git rev-parse HEAD
git merge-base --is-ancestor e3fad73145a41077052520e2cba9eb649e3716ce HEAD
```

Expected: only explicitly authorized B-04R implementation files may be dirty; the
ancestor check returns exit code 0. Stop if the accepted documentation is not in
`HEAD`.

- [x] **Step 2: Record immutable before-hashes**

Compute SHA-256 for:

```text
migrations/baselines/canonical_baseline_v1/evidence-index.json
migrations/baselines/canonical_baseline_v1/cut.json
migrations/baselines/canonical_baseline_v1/expected-fingerprint.json
migrations/baselines/canonical_baseline_v1/expected-fingerprint.sha256
migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.json
migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.sha256
migrations/baselines/canonical_baseline_v1/seed-manifest.json
migrations/baselines/canonical_baseline_v1/verification-report.json
migrations/baselines/canonical_baseline_v1/postgresql-18/contract.json
migrations/baselines/canonical_baseline_v1/postgresql-18/expected-fingerprint.json
migrations/baselines/canonical_baseline_v1/postgresql-18/expected-fingerprint.sha256
migrations/baselines/canonical_baseline_v1/postgresql-18/verification-report.json
migrations/b04/fingerprint.py
```

Save the command output outside the repository as review evidence. Do not create a
repository file.

- [x] **Step 3: Run the pre-change pure suite**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
```

Expected: the current accepted suite passes. Stop before Task 1 on any failure.

---

### Task 1: Restore evidence index, artifacts and authorizing resolver

**Files:**

- Create:
  `09_Разработка/backend/migrations/b04/restore_evidence.py`
- Create:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py`
- Create:
  `09_Разработка/backend/migrations/baselines/canonical_baseline_v1/restore-evidence-index.json`

**Interfaces:**

- Consumes:
  `canonical_json_bytes()`, `sha256_hex()`, `resolve_authorizing_evidence()` and
  live evidence constants from `migrations.b04.evidence`.
- Produces:
  - `RestoreEvidenceError(ValueError)`;
  - `RestoreEvidenceStatus(StrEnum)`;
  - `RestoreEvidenceSet` frozen dataclass;
  - `validate_restore_evidence_index(value: Mapping[str, object]) -> None`;
  - `validate_restore_contract(value: Mapping[str, object]) -> None`;
  - `validate_equivalence_map(value: Mapping[str, object]) -> None`;
  - `validate_restore_report(value: Mapping[str, object]) -> None`;
  - `build_pending_restore_index(value: Mapping[str, object], artifact_sha256: Mapping[str, str]) -> dict[str, object]`;
  - `build_accepted_restore_index(value: Mapping[str, object], *, accepted_at_utc: str, accepted_by: str, verification_report_sha256: str) -> dict[str, object]`;
  - `resolve_restore_authorizing_evidence(value: Mapping[str, object], artifact_root: Path, live_index: Mapping[str, object]) -> RestoreEvidenceSet`.

- [x] **Step 1: Write exact-key failing tests**

The initial repository index is exactly:

```json
{
  "format_version": 1,
  "baseline_id": "canonical_baseline_v1",
  "live_evidence_id": "postgresql-18-fingerprint-v2",
  "evidence_sets": []
}
```

Add parameterized tests rejecting unknown/missing keys, duplicate IDs, unknown
statuses, non-PG18 entries, path traversal/symlinks, zero or multiple active entries,
acceptance without `repository_owner`, report digest mismatch and mutation of any
existing live artifact.

```python
def test_b04r_index_001_repository_index_is_empty_and_non_authorizing() -> None:
    value = json.loads(RESTORE_INDEX.read_text(encoding="utf-8"))
    validate_restore_evidence_index(value)
    assert value["evidence_sets"] == []


def test_b04r_index_002_runner_transition_stops_pending_acceptance() -> None:
    updated = build_pending_restore_index(
        _empty_index(),
        {name: "a" * 64 for name in RESTORE_EXPECTED_ARTIFACTS},
    )
    assert updated["evidence_sets"][0]["status"] == "candidate_pending_acceptance"
    assert updated["evidence_sets"][0]["acceptance"] is None
```

- [x] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_evidence.py -q
```

Expected: collection fails because `migrations.b04.restore_evidence` and
`restore-evidence-index.json` do not exist.

- [x] **Step 3: Implement exact states and immutable models**

```python
RESTORE_EVIDENCE_ID = "postgresql-18-restore-roundtrip-v1"
RESTORE_CONTRACT_PATH = "postgresql-18/restore-roundtrip-v1/contract.json"
RESTORE_EXPECTED_ARTIFACTS = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "equivalence-map.json",
    "verification-report.json",
)


class RestoreEvidenceStatus(StrEnum):
    CANDIDATE_PENDING_VERIFICATION = "candidate_pending_verification"
    CANDIDATE_PENDING_ACCEPTANCE = "candidate_pending_acceptance"
    ACTIVE_RESTORE_AUTHORIZING = "active_restore_authorizing"


@dataclass(frozen=True, slots=True)
class RestoreEvidenceSet:
    evidence_id: str
    status: RestoreEvidenceStatus
    postgres_major: int
    contract_path: str
    artifact_sha256: Mapping[str, str]
    acceptance: Mapping[str, str] | None
```

All JSON validators use exact key sets and canonical bytes. The initial index has no
entry. Only `build_pending_restore_index()` may add one
`candidate_pending_acceptance` entry. Only
`build_accepted_restore_index()` may transition that exact entry to
`active_restore_authorizing`, and only with:

```text
accepted_at_utc = valid UTC Z timestamp
accepted_by = repository_owner
verification_report_sha256 = exact report artifact digest
```

`resolve_restore_authorizing_evidence()` first resolves the existing live
`active_authorizing` evidence, then validates all five restore files, all digests,
contract/report cross-fields and acceptance digest. It never treats pending evidence
as authorizing.

Use these exact key sets:

```python
_RESTORE_ENTRY_KEYS = frozenset({
    "evidence_id", "status", "postgres_major", "contract_path",
    "artifact_sha256", "acceptance",
})
_RESTORE_CONTRACT_KEYS = frozenset({
    "evidence_id", "baseline_id", "live_evidence_id", "source_sha",
    "implementation_sha", "postgres_major", "server_version_num",
    "pg_dump_version", "pg_restore_version",
    "live_fingerprint_format_version", "restore_fingerprint_format_version",
    "live_expected_fingerprint_sha256", "restore_expected_fingerprint_sha256",
    "equivalence_map_sha256", "shared_artifact_sha256",
    "payload_artifact_sha256", "canonical_table_count",
    "canonical_sequence_count", "governed_seed_count", "expected_artifacts",
})
_EQUIVALENCE_MAP_KEYS = frozenset({
    "format_version", "live_evidence_id", "restore_evidence_id",
    "live_fingerprint_sha256", "restore_fingerprint_sha256",
    "difference_count", "differences",
})
_DIFFERENCE_KEYS = frozenset({
    "kind", "schema", "table", "object_name", "live_json_pointer",
    "restore_json_pointer", "live_expression_sha256",
    "restore_expression_sha256",
})
_RESTORE_REPORT_KEYS = frozenset({
    "status", "evidence_id", "live_evidence_id", "source_sha",
    "implementation_sha", "postgres_major", "server_version_num",
    "pg_dump_version", "pg_restore_version", "working_database",
    "first_restore_database", "second_restore_database", "backup_sha256",
    "live_digest", "first_restore_digest", "second_restore_digest",
    "difference_counts", "marker_state", "canonical_table_count",
    "canonical_sequence_count", "governed_seed_count", "artifact_sha256",
    "first_restore_equals_second", "live_equals_authorizing",
    "typed_diff_equals_map",
})
```

- [x] **Step 4: Verify GREEN**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_evidence.py -q
```

Expected: all Task 1 tests pass.

- [x] **Step 5: Review checkpoint**

Provide the new index, public interfaces, focused test result and diff. Do not stage
or commit.

---

### Task 2: Exact typed live/restore structural diff

**Files:**

- Modify:
  `09_Разработка/backend/migrations/b04/restore_evidence.py`
- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py`

**Interfaces:**

- Consumes: two already validated fingerprint-v2 mappings.
- Produces:
  - `ExpressionDifference` frozen dataclass;
  - `build_typed_equivalence_map(live: Mapping[str, object], restored: Mapping[str, object]) -> dict[str, object]`;
  - `assert_typed_equivalence(live: Mapping[str, object], restored: Mapping[str, object], equivalence_map: Mapping[str, object]) -> None`.

- [x] **Step 1: Write failing typed-diff tests**

Construct minimal fingerprint-v2 fixtures with named tables, CHECK definitions and
partial-index predicates. Test:

```python
def test_b04r_diff_001_accepts_only_exact_expression_leaves() -> None:
    result = build_typed_equivalence_map(LIVE, RESTORED)
    assert [item["kind"] for item in result["differences"]] == [
        "check_definition_deparser_roundtrip",
        "index_predicate_deparser_roundtrip",
    ]


@pytest.mark.parametrize(
    "mutation",
    ["column_type", "missing_check", "extra_index", "index_unique", "seed_value"],
)
def test_b04r_diff_002_rejects_every_non_expression_difference(mutation: str) -> None:
    with pytest.raises(RestoreEvidenceError, match="B04R-DIFF-KIND"):
        build_typed_equivalence_map(LIVE, mutate(RESTORED, mutation))
```

Also reject missing/extra/duplicate map entries, mutated pointers, wildcard/regex
keys, wrong object identity and either expression SHA mismatch.

- [x] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_evidence.py -q
```

Expected: new tests fail because the typed-diff functions are absent.

- [x] **Step 3: Implement recursive leaf comparison**

Walk dictionaries by exact key and lists by exact length/index. A differing leaf is
allowed only when its RFC 6901 pointer resolves to one of:

```text
/tables/{table_index}/checks/{check_index}/definition
/tables/{table_index}/indexes/{index_index}/predicate
```

The named parent objects must exist at the same indices in both fingerprints and have
identical `schema`, table `name` and CHECK/index `name`. Emit:

```python
@dataclass(frozen=True, slots=True)
class ExpressionDifference:
    kind: str
    schema: str
    table: str
    object_name: str
    live_json_pointer: str
    restore_json_pointer: str
    live_expression_sha256: str
    restore_expression_sha256: str
```

Sort items by:

```text
(kind, schema, table, object_name, live_json_pointer, restore_json_pointer)
```

After validating every mapped pointer and hash,
`assert_typed_equivalence()` replaces only those exact two string leaves in copies
with one sentinel and requires complete JSON equality. It rejects non-string leaves,
`null` predicates, path prefixes, wildcards and any unmapped difference.

- [x] **Step 4: Verify GREEN**

Run the focused file and confirm all negative mutations fail with
`B04R-DIFF-KIND` or `B04R-DIFF-MAP`.

- [x] **Step 5: Review checkpoint**

Provide fixtures demonstrating one accepted deparser-only difference and one rejected
structural difference. Do not stage or commit.

---

### Task 3: Endpoint safety, exact versions and working read-only proof

**Files:**

- Modify:
  `09_Разработка/backend/migrations/b04/disposable.py`
- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_disposable_safety.py`
- Create:
  `09_Разработка/backend/migrations/b04/verify_restore_roundtrip.py`
- Create:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py`

**Interfaces:**

- Consumes:
  `assert_disposable_database()`, `assert_postgresql_18()`,
  `extract_fingerprint()`, `canonicalize_fingerprint()` and the Task 1 resolver.
- Produces:
  - `RestoreVerificationError(RuntimeError)`;
  - `DatabaseSnapshot` frozen dataclass;
  - `PreflightResult` frozen dataclass;
  - `RestoreVerificationConfig` dataclass with explicit adapters;
  - `read_working_snapshot(connection: Any, *, fingerprint_extractor: FingerprintExtractor) -> DatabaseSnapshot`;
  - `preflight_restore_verification(config: RestoreVerificationConfig) -> PreflightResult`;
  - exact disposable-name support without relaxing any existing prohibited name.

Use these immutable result types:

```python
@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    database: str
    server_version_num: int
    transaction_read_only: str
    historical_marker: str
    public_marker: str | None
    fingerprint: Mapping[str, object]
    fingerprint_bytes: bytes
    fingerprint_digest: str
    canonical_table_count: int
    canonical_sequence_count: int
    governed_seed_count: int


@dataclass(frozen=True, slots=True)
class PreflightResult:
    working: DatabaseSnapshot
    first_identity: DatabaseIdentity
    second_identity: DatabaseIdentity
    pg_dump_version: str
    pg_restore_version: str
    live_evidence: EvidenceSet
```

- [x] **Step 1: Write failing safety and ordering tests**

Add only these names to `_R18_DISPOSABLE_DATABASES`:

```python
"wp_b04_r18_restore_first_disposable"
"wp_b04_r18_restore_second_disposable"
```

Tests must reject swapping expected names, working/disposable identity collision,
non-owner disposable DB, non-empty disposable DB, non-180003 server, tool version
mismatch and any missing environment input.

```python
def test_b04r_readonly_001_begin_is_first_working_statement() -> None:
    connection = RecordingConnection(snapshot=WORKING_SNAPSHOT)
    snapshot = read_working_snapshot(connection, fingerprint_extractor=_fingerprint)
    assert connection.statements[0] == (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert snapshot.transaction_read_only == "on"
```

- [x] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_disposable_safety.py migration_contract_tests/test_b04_restore_roundtrip_runner.py -q
```

Expected: new disposable names are rejected and the runner module is absent.

- [x] **Step 3: Implement explicit configuration**

`RestoreVerificationConfig.from_environment()` requires every value below and rejects
missing/empty inputs without reading application `.env`:

```text
WELDPASSPORT_B04R_WORKING_URL
WELDPASSPORT_B04R_FIRST_URL
WELDPASSPORT_B04R_SECOND_URL
WELDPASSPORT_B04R_ALLOW_DESTRUCTIVE
WELDPASSPORT_B04R_OWNERSHIP_TOKEN
WELDPASSPORT_B04R_FIRST_EXPECTED_DATABASE
WELDPASSPORT_B04R_SECOND_EXPECTED_DATABASE
WELDPASSPORT_B04R_BACKUP_PATH
WELDPASSPORT_B04R_ARTIFACT_ROOT
WELDPASSPORT_B04R_IMPLEMENTATION_SHA
WELDPASSPORT_B04R_PG_DUMP_EXE
WELDPASSPORT_B04R_PG_RESTORE_EXE
WELDPASSPORT_B04R_EXPECTED_PG_DUMP_VERSION
WELDPASSPORT_B04R_EXPECTED_PG_RESTORE_VERSION
```

The config exposes injectable `connection_factory`, `command_runner`,
`version_probe`, `safety_validator`, `fingerprint_extractor`, `temporary_writer`,
`artifact_linker` and `index_replacer`.

- [x] **Step 4: Implement read-only and disposable database preflight**

The first working statement is the explicit read-only transaction. Within that same
transaction read:

```text
SHOW transaction_read_only
SHOW server_version_num
SELECT current_database()
SELECT version_num FROM test.alembic_version
SELECT to_regclass('public.alembic_version')
fingerprint
```

Require `transaction_read_only = on`, version `180003`, historical marker
`20260724_27_qd_rbac_sod`, no public marker, live digest equal to the physically
resolved live evidence.

For both disposable endpoints run socket-free safety first, then require current
operator ownership and zero non-system relations before any restore command.
Compare actual `(database, host, port, username)` identities and reject any collision.

- [x] **Step 5: Verify GREEN**

Run both focused files. Confirm every failure stops before the first tool command and
only stable secret-free `B04R-*` codes escape.

- [x] **Step 6: Review checkpoint**

Provide statement-order evidence, exact environment-name list and negative identity
matrix. Do not stage, commit or connect to a real DB.

---

### Task 4: Custom archive, two restores and fixed-point verification

**Files:**

- Modify:
  `09_Разработка/backend/migrations/b04/verify_restore_roundtrip.py`
- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py`

**Interfaces:**

- Consumes: successful Task 3 preflight and Task 2 typed diff.
- Produces:
  - `RestoreRoundtripResult` frozen dataclass containing `working`, `first_restore`,
    `second_restore`, `backup_sha256`, `pg_dump_version`, `pg_restore_version` and
    `equivalence_map`;
  - `execute_restore_roundtrip(config: RestoreVerificationConfig, preflight: PreflightResult) -> RestoreRoundtripResult`;
  - sanitized `DatabaseSnapshot` for working, first restore and second restore;
  - exact backup SHA-256 and tool version evidence.

- [x] **Step 1: Write failing command-sequence tests**

Use fake adapters; no PostgreSQL process is started. Assert exact phase order:

```text
artifact/index preflight
→ live evidence resolution
→ pg_dump/pg_restore version probes
→ working READ ONLY snapshot
→ both disposable safety/ownership/emptiness checks
→ pg_restore --list initial backup
→ restore first
→ first READ ONLY snapshot
→ dump first to temporary custom archive
→ restore second
→ second READ ONLY snapshot
→ fixed-point equality
→ typed diff
→ publication
```

Assert no command contains a password or full DSN. Connection values are passed only
through a fresh exact `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`
environment. Command arguments contain only sanitized database names and paths.

- [x] **Step 2: Verify RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_roundtrip_runner.py -q
```

Expected: command-sequence and fixed-point tests fail.

- [x] **Step 3: Implement archive validation and restore commands**

Require an existing regular non-symlink backup, compute SHA-256, and validate custom
format using the exact configured `pg_restore --list` executable before connecting
restore commands.

First restore:

```text
pg_restore --exit-on-error --no-owner --no-privileges
           --dbname=wp_b04_r18_restore_first_disposable $BackupPath
```

Create the second archive only from the first restored DB:

```text
pg_dump --format=custom --no-owner --no-privileges
        --file=$SecondArchivePath
        --dbname=wp_b04_r18_restore_first_disposable
```

Create that path with
`tempfile.mkstemp(prefix=".b04r-roundtrip-", suffix=".dump", dir=config.artifact_root.parent)`
and close the returned descriptor before invoking `pg_dump`; the resulting absolute
path is `SecondArchivePath`.

Second restore:

```text
pg_restore --exit-on-error --no-owner --no-privileges
           --dbname=wp_b04_r18_restore_second_disposable $SecondArchivePath
```

Delete only the exact runner-created temporary second archive in `finally`; never
delete the operator-provided backup or either database.

- [x] **Step 4: Implement snapshot equality**

First and second snapshots must have identical:

```text
server_version_num
historical marker
absence of public marker
canonical fingerprint bytes and digest
73 table count
6 sequence count
15 governed seeds
```

Require `first_digest == second_digest`. Then build the exact typed map between live
and first restore and verify it again between live and second restore. Any difference
outside the two expression kinds stops with `B04R-DIFF-KIND`; fixed-point mismatch
stops with `B04R-FIXED-POINT`.

- [x] **Step 5: Verify GREEN**

Run the focused runner tests. Confirm injected failure at every phase prevents all
later phases and prevents artifact publication.

- [x] **Step 6: Review checkpoint**

Provide the exact fake command trace, backup ownership boundary and fixed-point
negative test. Do not run the real DB sequence.

---

### Task 5: Acyclic artifacts and atomic candidate publication

**Files:**

- Modify:
  `09_Разработка/backend/migrations/b04/restore_evidence.py`
- Modify:
  `09_Разработка/backend/migrations/b04/verify_restore_roundtrip.py`
- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py`
- Modify:
  `09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py`

**Interfaces:**

- Consumes: verified live/first/second snapshots and equivalence map.
- Produces exactly:
  - `RestoreVerificationReport` frozen dataclass with exactly the
    `_RESTORE_REPORT_KEYS` fields defined in Task 1;
  - `verify_restore_roundtrip(config: RestoreVerificationConfig) -> RestoreVerificationReport`;
  - `postgresql-18/restore-roundtrip-v1/contract.json`;
  - `postgresql-18/restore-roundtrip-v1/expected-fingerprint.json`;
  - `postgresql-18/restore-roundtrip-v1/expected-fingerprint.sha256`;
  - `postgresql-18/restore-roundtrip-v1/equivalence-map.json`;
  - `postgresql-18/restore-roundtrip-v1/verification-report.json`;
  - updated `restore-evidence-index.json` with
    `candidate_pending_acceptance`.

- [x] **Step 1: Write failing artifact-graph tests**

Tests assert:

```text
fingerprint / sha file / equivalence map
    → contract
    → verification report
    → restore evidence index
```

`contract.json` has no self/report digest. Report has no self digest. Only the outer
index hashes all five artifacts. Reject partial targets, existing targets, symlinked
directories, noncanonical JSON, path escape, racing foreign files and publication
failure at every link/replace step.

- [x] **Step 2: Verify RED**

Run both B-04R focused files. Expected: artifact construction/publication tests fail.

- [x] **Step 3: Build exact contract and report**

Contract records exact source/implementation SHA, server/tool versions, live and
restore digests, equivalence-map digest, existing immutable live/shared artifact
digests, fingerprint/sha/map digests, counts and five expected names.

Report status is exactly:

```text
B04_RESTORE_ROUNDTRIP_VERIFIED
```

Report contains database names only—no hosts, ports, users, DSNs or credentials—and
records backup SHA, three fingerprint digests, marker/count results, two typed
difference counts and all three boolean proof fields.

- [x] **Step 4: Implement create-new atomic publication**

Write all six new payloads to same-directory temporary files. Hard-link each of five
artifacts create-new, then atomically replace only the new restore index. On failure,
remove only temporary files and artifacts created by this invocation; preserve any
racing foreign file and the prior index.

The runner calls only `build_pending_restore_index()`. It has no code path to
`build_accepted_restore_index()`.

- [x] **Step 5: Verify GREEN**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_evidence.py migration_contract_tests/test_b04_restore_roundtrip_runner.py -q
```

Expected: all focused tests pass, including atomic rollback and secret scans.

- [x] **Step 6: Review checkpoint**

Provide schemas, digest graph, rollback matrix and focused results. Stop for code
acceptance; DB run and evidence generation remain forbidden.

---

### Task 6: Pure regression, immutable proof and documentation handoff

**Files:**

- Modify after implementation review:
  `docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_CLAUDE_CODE_PROMPT.md`
- Modify after implementation review:
  `docs/project/TASK_REGISTRY.md`
- Modify after implementation review:
  `docs/project/PROJECT_STATUS.yaml`
- Modify after implementation review:
  `docs/project/ROADMAP.md`
- Do not create the five generated evidence artifacts during the pure-code gate.

**Interfaces:**

- Consumes: Tasks 1–5 accepted code.
- Produces: complete code-review packet and an explicit stop before operator DB work.

- [x] **Step 1: Run focused and full pure suites**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_evidence.py -q
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_roundtrip_runner.py -q
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall migrations/b04
git diff --check
```

No application, PostgreSQL or Alembic tests run at this gate.

- [x] **Step 2: Recompute immutable after-hashes**

Recompute the Pre-Task list and require byte equality for every existing artifact and
`fingerprint.py`. Also require no changes under:

```text
migrations/versions/
migrations/baseline_candidates/
migrations/archive/
```

- [x] **Step 3: Perform secret and scope scans**

```powershell
rg -n "(postgresql\\+psycopg://|password=|PGPASSWORD|WELDPASSPORT_B04R_.*URL)" `
  migrations/b04 migration_contract_tests `
  migrations/baselines/canonical_baseline_v1/restore-evidence-index.json
git diff --name-status
git diff
```

`PGPASSWORD` and environment-variable names may occur only in code/tests that build
transient environments; no credential value, DSN, hostname or username may occur in
an artifact/report fixture.

- [x] **Step 4: Update status without claiming operational acceptance**

Set B-04R to `implemented / awaiting operator verification` only after code acceptance.
B-04B remains `planned / blocked`. Do not mark evidence active and do not report
Maintenance Readiness `READY`.

- [x] **Step 5: Prepare the code acceptance packet**

Return:

1. base/head SHA;
2. changed-file list;
3. RED evidence by Task;
4. GREEN focused/full counts;
5. immutable before/after hash proof;
6. compileall and `git diff --check`;
7. complete diff;
8. fail-code inventory;
9. proposed commit split;
10. explicit stop before stage/commit/DB run.

- [x] **Step 6: Stop for separate decisions**

After code acceptance, the remaining gates are strictly separate:

```text
owner-authorized implementation commit
→ accepted implementation SHA
→ owner-authorized operator DB preflight/run
→ candidate evidence review
→ owner-authorized evidence promotion
→ active_restore_authorizing
→ new READ-ONLY Maintenance Readiness Review
→ READY
→ B-04B
```

No later arrow is implied by acceptance of this plan.

---

## Proposed commit boundaries

Commits are proposals only; none may be created without a separate owner command.

1. `test(migrations): define B-04R restore evidence contracts`
2. `feat(migrations): add B-04R restore-roundtrip verifier`
3. `docs(migrations): record B-04R implementation review`

## Fail-code ownership

| Code | Owning Task |
|---|---|
| `B04R-EVIDENCE-INDEX` | Task 1 |
| `B04R-LIVE-EVIDENCE` | Tasks 1 and 3 |
| `B04R-SERVER-VERSION` | Task 3 |
| `B04R-TOOL-VERSION` | Tasks 3 and 4 |
| `B04R-WORKING-READONLY` | Task 3 |
| `B04R-WORKING-FINGERPRINT` | Task 3 |
| `B04R-DISPOSABLE-SAFETY` | Task 3 |
| `B04R-BACKUP` | Task 4 |
| `B04R-RESTORE` | Task 4 |
| `B04R-RESTORE-FINGERPRINT` | Task 4 |
| `B04R-FIXED-POINT` | Task 4 |
| `B04R-DIFF-KIND` | Task 2 |
| `B04R-DIFF-MAP` | Task 2 |
| `B04R-ARTIFACT-PUBLISH` | Task 5 |
| `B04R-ACCEPTANCE` | Tasks 1 and 5 |

All wrapped exceptions expose only the stable owning code. Original exceptions may
be chained for in-process diagnostics only when their text cannot escape CLI output;
the CLI prints only the stable `B04R-*` code.

## Specification coverage

| Spec section | Plan coverage |
|---|---|
| 1–3: goal, evidence origin, boundaries | Global Constraints, Pre-Task |
| 4: artifact layout | Task 5 |
| 5: restore index | Task 1 |
| 6: contract and acyclic digests | Tasks 1 and 5 |
| 7: exact typed map | Task 2 |
| 8: verification report | Tasks 1 and 5 |
| 9: explicit runner | Tasks 3 and 4 |
| 10: fail-closed codes | Fail-code ownership table |
| 11: pure tests | Tasks 1–5 |
| 12: acceptance sequence | Task 6 |
| 13: Definition of Done | Task 6 and Plan acceptance criteria |

## Plan acceptance criteria

- Every Spec section 1–13 maps to a Task above.
- Existing live evidence and `fingerprint.py` are immutable.
- Typed diff permits only exact CHECK-definition and partial-index-predicate leaves.
- Working read-only transaction precedes all catalog queries.
- Disposable ownership, emptiness, version and identity are checked before restore.
- First and second restore fingerprints must be byte-identical.
- Artifact digest dependencies are acyclic.
- Runner can publish only `candidate_pending_acceptance`.
- B-04B remains blocked through the pure-code gate.
- DB run, evidence promotion, commit and push remain separately authorized.
