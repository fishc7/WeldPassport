# TEST-DB-F2 Pure Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать pure-tested fail-closed coordinator/worker protocol для
трёх последовательных TEST-DB-F2 rehearsal roles без запуска PostgreSQL,
Alembic CLI или application tests.

**Architecture:** Immutable protocol/value objects отделены от source/target
preflight, evidence publisher, subprocess boundary и one-role worker.
Coordinator pure-проверяет всю тройку до первого process call, затем запускает
fresh workers в фиксированном порядке и принимает только create-exclusive
digest-linked artifacts.

**Tech Stack:** Python 3.12+, dataclasses, StrEnum, pathlib, hashlib, json,
subprocess, SQLAlchemy URL/F1 contracts, pytest 8.3+.

## Global Constraints

- Рабочий каталог Python-команд:
  `09_Разработка/backend`.
- Не подключаться к PostgreSQL и не запускать Alembic CLI или `tests/`.
- Не создавать, удалять, переименовывать или reset-ить DB.
- Не изменять Alembic graph, domain/API или Runtime Compatibility contracts.
- Использовать существующие `authorize_test_database`,
  `bind_database_target` и live ownership verifier; ослабленные копии запрещены.
- Secrets поступают только из transient environment и запрещены в argv,
  repr, exceptions, logs и evidence.
- Parent environment не наследуется целиком.
- Порядок ролей неизменяем:
  `canonical → legacy_compatible → legacy_negative`.
- Каждый task выполняется RED → GREEN и проходит отдельный review.
- Commit разрешены ранее данным владельцем разрешением; push выполняется только
  после полного pure closure.

---

## File Structure

### Production

- `app/testing/__init__.py` — package boundary без side effects.
- `app/testing/f2_contract.py` — roles, statuses, immutable inputs/results,
  safe error и environment parser.
- `app/testing/f2_evidence.py` — namespace safety, canonical JSON,
  create-exclusive publication и digest chain.
- `app/testing/f2_preflight.py` — Git/source/operator/target validation и
  immutable offline plan.
- `app/testing/f2_process.py` — child environment builder, secret guard,
  process executor и timeout mapping.
- `app/testing/f2_coordinator.py` — fixed role state machine и artifact
  validation.
- `app/testing/f2_worker.py` — one-role process entrypoint, bind-before-import
  boundary и injected role adapter.
- `app/testing/f2_role_adapters.py` — exact command/fixture protocol consumed by
  the worker; no command executes at import.
- `scripts/run_test_db_f2.py` — thin coordinator CLI.

### Pure tests

- `migration_contract_tests/test_f2_contract.py`
- `migration_contract_tests/test_f2_evidence.py`
- `migration_contract_tests/test_f2_preflight.py`
- `migration_contract_tests/test_f2_process.py`
- `migration_contract_tests/test_f2_coordinator.py`
- `migration_contract_tests/test_f2_worker.py`
- `migration_contract_tests/test_f2_governance.py`

---

### Task 1: Immutable protocol and transient environment contract

**Files:**

- Create: `09_Разработка/backend/app/testing/__init__.py`
- Create: `09_Разработка/backend/app/testing/f2_contract.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_contract.py`

**Interfaces:**

- `F2Role(StrEnum)` with exact values `canonical`, `legacy_compatible`,
  `legacy_negative`.
- `F2MachineStatus(StrEnum)` with four specification outcomes.
- `F2Error(code: str, safe_detail: str)`.
- `F2TargetInput(role, test_database_url, confirmed_name, ownership_token)` with
  secret fields excluded from repr.
- `F2ParentInputs(working_database_url, evidence_root, authorization,
  destructive_opt_in, targets)`.
- `F2WorkerRequest(protocol_version, run_id, source_sha, role, artifact_name)`.
- `load_parent_inputs(environment: Mapping[str, str]) -> F2ParentInputs`.

- [ ] **Step 1: Write RED protocol tests**

Use literal environment fixtures for all three prefixes. Assert exact order,
missing/blank/extra inputs, exact operator authorization
`I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL`, exact `YES`, immutable dataclasses and
absence of secret values from repr/errors.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_contract.py -q
```

Expected: `ModuleNotFoundError: app.testing.f2_contract`.

- [ ] **Step 3: Implement minimal contract**

```python
F2_PROTOCOL_VERSION = "test-db-f2/v1"
F2_ROLE_ORDER = (
    F2Role.CANONICAL,
    F2Role.LEGACY_COMPATIBLE,
    F2Role.LEGACY_NEGATIVE,
)
F2_OPERATOR_AUTHORIZATION = "I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL"
```

Parser reads only the exact names from Specification §5. Unknown
`WELDPASSPORT_F2_*` variables fail `TEST-DB-F2-AUTHORIZATION-MISSING`; raw
values never enter diagnostics.

- [ ] **Step 4: Run GREEN and compile**

```powershell
python -m pytest migration_contract_tests/test_f2_contract.py -q
python -m compileall app/testing/f2_contract.py
```

- [ ] **Step 5: Review and commit**

```text
feat(testing): add TEST-DB-F2 protocol contract
```

---

### Task 2: Create-exclusive evidence and digest chain

**Files:**

- Create: `09_Разработка/backend/app/testing/f2_evidence.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_evidence.py`

**Interfaces:**

- `PublishedArtifact(name: str, digest: str)`.
- `canonical_json_bytes(payload: Mapping[str, object]) -> bytes`.
- `reserve_run_namespace(root: Path, run_id: UUID) -> Path`.
- `publish_artifact(path: Path, payload: Mapping[str, object])
  -> PublishedArtifact`.
- `verify_artifact(path: Path, expected_name: str, expected_run_id: UUID,
  expected_source_sha: str, expected_previous_digest: str | None)
  -> PublishedArtifact`.

- [ ] **Step 1: Write RED evidence tests**

Assert sorted compact JSON, UTF-8/LF, NaN rejection, UUIDv4, pre-existing root,
atomic new namespace, existing namespace rejection, symlink/reparse rejection,
`xb` create-exclusive writes, stable SHA-256, chain mutation detection and
recursive forbidden-key/value scan.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_evidence.py -q
```

- [ ] **Step 3: Implement namespace safety**

Use `Path.mkdir(mode=0o700, exist_ok=False)` and inspect every existing path
component with `os.lstat`; reject `stat.FILE_ATTRIBUTE_REPARSE_POINT` when the
attribute exists and reject `Path.is_symlink()` on every platform.

- [ ] **Step 4: Implement canonical publisher**

```python
json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

Write with `path.open("xb")`, flush, `os.fsync`, then compute digest from the
exact bytes. Never overwrite or unlink.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest migration_contract_tests/test_f2_evidence.py -q
python -m compileall app/testing/f2_evidence.py
```

```text
feat(testing): add TEST-DB-F2 evidence chain
```

---

### Task 3: Full offline source and target preflight

**Files:**

- Create: `09_Разработка/backend/app/testing/f2_preflight.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_preflight.py`

**Interfaces:**

- `GitState(source_sha: str, tracked_clean: bool)`.
- `GitInspector` protocol with `read_state() -> GitState`.
- `F2AuthorizedTarget(role: F2Role,
  authorization: TestDatabaseAuthorization, identity_digest: str)`.
- `F2OfflinePlan(run_id, source_sha, namespace, targets)`.
- `build_offline_plan(inputs, git_inspector, uuid_factory)
  -> F2OfflinePlan`.

- [ ] **Step 1: Write RED preflight matrix**

Assert dirty staged/unstaged tracked state, malformed SHA, missing evidence root,
all F1 unsafe target inputs, working collision, each of three pairwise
collisions, duplicate/missing roles and evidence reservation failure.
Use a process/connection sentinel that raises if called; every failure must
leave its call count at zero.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_preflight.py -q
```

- [ ] **Step 3: Implement Git inspector**

Default inspector runs only:

```text
git rev-parse HEAD
git status --porcelain --untracked-files=no
```

Use argument arrays, `shell=False`, sanitized output and repository root fixed
at construction. Nonzero exit maps to `TEST-DB-F2-SOURCE-UNSAFE`.

- [ ] **Step 4: Reuse F1 authorization**

Call `authorize_test_database` exactly once per role. Compare immutable
normalized `DatabaseIdentity` values against working and each other. Identity
digest:

```python
sha256(b"weldpassport:test-db-f2:identity:v1\0" + canonical_identity_bytes)
```

Canonical identity bytes contain normalized driver/host/port/database but are
never published directly.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest migration_contract_tests/test_f2_preflight.py -q
python -m compileall app/testing/f2_preflight.py
```

```text
feat(testing): add TEST-DB-F2 offline preflight
```

---

### Task 4: Minimal child environment and process executor

**Files:**

- Create: `09_Разработка/backend/app/testing/f2_process.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_process.py`

**Interfaces:**

- `ProcessResult(exit_code: int, stdout: str, stderr: str, timed_out: bool)`.
- `ProcessExecutor.run(argv: tuple[str, ...], environment: Mapping[str, str],
  timeout_seconds: int) -> ProcessResult`.
- `build_worker_environment(plan, target, artifact_path, parent_environment)
  -> dict[str, str]`.
- `build_worker_argv(python_executable, request) -> tuple[str, ...]`.

- [ ] **Step 1: Write RED environment/process tests**

Assert parent sentinel variables do not pass, exact runtime allowlist, only one
generic target bundle, no secrets in argv, canonical profile absence, exact
legacy profile/schema, `shell=False`, timeout mapping, redacted stdout/stderr
and no retry.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_process.py -q
```

- [ ] **Step 3: Implement environment whitelist**

Allowed inherited keys:

```text
SystemRoot, WINDIR, SystemDrive, TEMP, TMP, PATH,
PYTHONUTF8, PYTHONIOENCODING
```

Add only protocol keys and generic F1 keys. Run a recursive secret guard before
calling executor.

- [ ] **Step 4: Implement subprocess executor**

Use `subprocess.run(..., shell=False, check=False, capture_output=True,
text=True, timeout=...)`. Catch `TimeoutExpired` and return safe
`timed_out=True`; never include exception text.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest migration_contract_tests/test_f2_process.py -q
python -m compileall app/testing/f2_process.py
```

```text
feat(testing): isolate TEST-DB-F2 worker processes
```

---

### Task 5: Fixed-order coordinator and artifact state machine

**Files:**

- Create: `09_Разработка/backend/app/testing/f2_coordinator.py`
- Create: `09_Разработка/backend/scripts/run_test_db_f2.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_coordinator.py`

**Interfaces:**

- `F2CoordinatorDependencies(preflight, executor, clock, publisher)`.
- `F2RunResult(run_id, source_sha, status, manifest_digest)`.
- `run_f2(environment, dependencies=None) -> F2RunResult`.
- CLI exits `0` only for `TEST_DB_F2_REHEARSAL_VERIFIED`.

- [ ] **Step 1: Write RED state-machine tests**

Cover exact success order, fresh call per role, artifact verification before
next call, each role nonzero/timeout/missing/malformed/duplicate/digest failure,
no subsequent call, no retry, failure precedence, three artifacts required for
verified and owner acceptance absence.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_coordinator.py -q
```

- [ ] **Step 3: Implement coordinator**

Publish `00_preflight.json`, then consume exact names:

```text
10_canonical.json
20_legacy_compatible.json
30_legacy_negative.json
```

After three verified artifacts publish `90_manifest.json`. On ordinary failure
best-effort publish `99_failure.json`; evidence publication failure returns
`TEST_DB_F2_EVIDENCE_FAILED` without claiming an authoritative artifact.

- [ ] **Step 4: Implement thin CLI**

CLI reads `os.environ`, calls `run_f2`, prints only `run_id`, safe status and
manifest digest, and never catches errors into success.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest migration_contract_tests/test_f2_coordinator.py -q
python -m compileall app/testing/f2_coordinator.py scripts/run_test_db_f2.py
```

```text
feat(testing): orchestrate TEST-DB-F2 rehearsal roles
```

---

### Task 6: One-role worker and operational adapter boundary

**Files:**

- Create: `09_Разработка/backend/app/testing/f2_worker.py`
- Create: `09_Разработка/backend/app/testing/f2_role_adapters.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_worker.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_f2_governance.py`

**Interfaces:**

- `WorkerDependencies(authorize, bind, live_gate, version_gate,
  empty_gate, role_adapter, publisher)`.
- `run_worker(request, environment, dependencies=None) -> PublishedArtifact`.
- `RoleAdapter.run(role: F2Role) -> Mapping[str, object]`.
- Default operational adapter uses injected `CommandExecutor`; no command runs
  at module import.

- [ ] **Step 1: Write RED bind/order tests**

Assert offline authorization → bind → DB import/live gate → version 180003 →
empty gate → one adapter → close → artifact. Test every failure boundary,
bind-once, wrong role/profile/source/protocol, existing output and safe errors.

- [ ] **Step 2: Write RED role-command tests**

Assert canonical, compatible and negative command/event sequences exactly match
Specification §10. Commands use `sys.executable -m alembic` and
`sys.executable -m pytest`, never bare executables or shell strings. Fakes
return results; commands are not executed.

- [ ] **Step 3: Write RED governance tests**

AST/command inspection rejects:

- `CREATE DATABASE`, `DROP DATABASE`, reset/rename;
- wildcard DB discovery;
- retry loops;
- shell execution;
- secret-bearing argv;
- application `.env` fallback;
- importing `app.shared.db` before bind.

- [ ] **Step 4: Implement worker**

Default worker imports F1 resolver/binder first. Import `app.shared.db` and
operational adapters only inside the post-bind function. All connections use
context managers and close before artifact publication.

- [ ] **Step 5: Implement adapter command plans**

Represent each role as an immutable tuple of named commands/callables. Legacy
fixture creation is a test-only callable and never belongs to runtime startup.
Negative fixture omits one required constraint rather than dropping/repairing a
runtime-created object.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_worker.py `
  migration_contract_tests/test_f2_governance.py -q
python -m compileall `
  app/testing/f2_worker.py `
  app/testing/f2_role_adapters.py
```

```text
feat(testing): add TEST-DB-F2 isolated worker
```

---

### Task 7: Full pure verification, review and closure

**Files:**

- Modify: `09_Разработка/.env.example`
- Modify: `09_Разработка/backend/.env.example`
- Modify: `docs/project/TASK_TEST_DB_F2_PURE_RUNNER_SPEC.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/ROADMAP.md`
- Modify: `docs/project/DECISIONS.md`

- [ ] **Step 1: Add commented environment names**

Document names only. Do not add active assignments, DSN, token or database
example.

- [ ] **Step 2: Run focused suite**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_contract.py `
  migration_contract_tests/test_f2_evidence.py `
  migration_contract_tests/test_f2_preflight.py `
  migration_contract_tests/test_f2_process.py `
  migration_contract_tests/test_f2_coordinator.py `
  migration_contract_tests/test_f2_worker.py `
  migration_contract_tests/test_f2_governance.py -q
```

- [ ] **Step 3: Run complete pure suite**

```powershell
python -m pytest migration_contract_tests -q
```

- [ ] **Step 4: Compile and scope audit**

```powershell
python -m compileall app/testing scripts/run_test_db_f2.py
git diff --check
git status --short
git diff --name-only
```

Confirm no PostgreSQL connection, Alembic CLI, application suite, DB lifecycle,
revision/domain/API change or secret-bearing output occurred.

- [ ] **Step 5: Read-only review and remediation**

Review spec coverage, process/environment boundary, evidence failure precedence,
secret redaction, no-I/O-before-preflight and command governance. Verdict:
`APPROVED`, `WITH FIXES` or `BLOCKED`. Every finding receives a RED → GREEN
remediation cycle and repeated full pure verification.

- [ ] **Step 6: Record closure**

Use status:

```text
IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED
```

Record exact focused/full counts and implementation commits. Do not claim
PostgreSQL or operational acceptance.

- [ ] **Step 7: Commit and push**

Final closure commit:

```text
docs(testing): record TEST-DB-F2 pure runner verification
```

Push `codex/b04b-maintenance-readiness-review` only after clean final
verification, using the owner's explicit permission from 2026-07-30.

---

## Plan Self-Review Checklist

- [x] Specification §§1–18 map to Tasks 1–7.
- [x] All secrets enter only through transient environment.
- [x] All three target bundles pass offline validation before process I/O.
- [x] Fixed role order, fresh process and short-circuit are explicit.
- [x] Worker bind-before-import and exact version/empty/live gates are explicit.
- [x] Evidence is canonical, create-exclusive and digest-linked.
- [x] Evidence publication failure cannot produce verified status.
- [x] No DB create/drop/reset, retry, wildcard discovery or shell execution.
- [x] Pure verification runs no PostgreSQL, Alembic CLI or application suite.
- [x] Operational acceptance and owner signature remain separate gates.
