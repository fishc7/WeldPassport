# TEST-DB-F2 Operator Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать отдельный offline operator preflight, который без
PostgreSQL/Alembic/application I/O проверяет source, prerequisites, transient F2
environment, три target identity и внешний evidence boundary.

**Architecture:** Новый `f2_operator_preflight.py` использует strict F2 parser,
выделенную pure target-authorization функцию и общие canonical evidence
primitives. Thin CLI только читает `os.environ`, печатает safe result и
возвращает `0` исключительно для `TEST_DB_F2_OPERATOR_PREFLIGHT_READY`.

**Tech Stack:** Python 3.12+, dataclasses, `StrEnum`, `pathlib`, `subprocess`,
UUIDv4, SHA-256, pytest, существующие F1/F2 contracts.

## Global Constraints

- Worktree:
  `D:\WeldPassport\.worktrees\b04b-maintenance-readiness`.
- Branch: `codex/b04b-maintenance-readiness-review`.
- PostgreSQL connection, socket/DNS lookup, worker, Alembic CLI и application
  suite запрещены.
- Разрешены только fixed read-only Git subprocess с argument arrays и
  `shell=False`.
- Никаких create/drop/reset/rename DB, retry, repair или cleanup.
- Secrets только в transient environment; они запрещены в argv, repr, errors,
  stdout/stderr и JSON.
- Все filesystem writes — только create-exclusive external evidence и
  согласованные repository files.
- Pure tests — только `migration_contract_tests/`.
- Полный pure pytest использует
  `--basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'`.
- Каждый implementation task завершается focused GREEN, compile/diff check и
  отдельным Conventional Commit.

---

## File structure

- Modify `app/testing/f2_preflight.py` — выделить pure target authorization без
  namespace reservation.
- Modify `app/testing/f2_evidence.py` — безопасная проверка внешнего root и
  create-exclusive named namespace.
- Create `app/testing/f2_operator_preflight.py` — authorization contract,
  source/prerequisite inspection, state machine и redacted artifact.
- Create `scripts/run_test_db_f2_operator_preflight.py` — thin CLI.
- Create `migration_contract_tests/test_f2_operator_preflight_contract.py` —
  authorization/source/target tests.
- Create `migration_contract_tests/test_f2_operator_preflight_runner.py` —
  state machine/evidence/CLI tests.
- Create `migration_contract_tests/test_f2_operator_preflight_governance.py` —
  AST/scope/secret/process prohibitions.
- Modify both `.env.example` files — commented preflight variable name only.
- Modify specification, registry, roadmap and decisions — closure evidence.

---

### Task 1: Reusable pure target authorization

**Files:**

- Modify: `09_Разработка/backend/app/testing/f2_preflight.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_f2_preflight.py`

**Interfaces:**

- Produce:
  `authorize_offline_targets(inputs: F2ParentInputs)
  -> tuple[F2AuthorizedTarget, ...]`.
- Preserve:
  `build_offline_plan(inputs, git_inspector, uuid_factory) -> F2OfflinePlan`.

- [ ] **Step 1: Write RED extraction tests**

Add tests proving `authorize_offline_targets`:

```python
targets = authorize_offline_targets(_inputs(tmp_path))
assert tuple(item.role for item in targets) == F2_ROLE_ORDER
assert len({item.identity_digest for item in targets}) == 3
```

Cover duplicate/missing roles, working collision and all three pairwise
collisions. Use a connection/process sentinel and assert zero calls.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_preflight.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

Expected: import/attribute failure for `authorize_offline_targets`.

- [ ] **Step 3: Extract minimal implementation**

Move the existing exact role/F1/collision loop into
`authorize_offline_targets`. `build_offline_plan` must call it before UUID
generation and namespace reservation. No change to error codes or secret
handling.

- [ ] **Step 4: Run GREEN and compile**

```powershell
python -m pytest migration_contract_tests/test_f2_preflight.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
python -m compileall app/testing/f2_preflight.py
git diff --check
```

- [ ] **Step 5: Commit**

```text
refactor(testing): expose TEST-DB-F2 offline target authorization
```

---

### Task 2: External operator-preflight evidence boundary

**Files:**

- Modify: `09_Разработка/backend/app/testing/f2_evidence.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_f2_evidence.py`

**Interfaces:**

- Produce:
  `validate_external_evidence_root(root: Path, repository_root: Path) -> Path`.
- Produce:
  `reserve_named_namespace(root: Path, namespace_name: str) -> Path`.

- [ ] **Step 1: Write RED filesystem matrix**

Assert rejection of missing/file/symlink/reparse root, root inside repository,
repository root itself, path traversal name, slash/backslash name and existing
namespace. Assert success only for
`operator-preflight-<lowercase UUIDv4>`.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest migration_contract_tests/test_f2_evidence.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

- [ ] **Step 3: Implement fail-closed helpers**

Reuse the existing lstat/reparse inspection. Resolve root and repository root;
reject when root equals repository root or is relative to it. Match namespace
with:

```python
re.fullmatch(
    r"operator-preflight-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    namespace_name,
)
```

Create with `mkdir(mode=0o700, exist_ok=False)` and never remove it.

- [ ] **Step 4: Run GREEN and compile**

```powershell
python -m pytest migration_contract_tests/test_f2_evidence.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
python -m compileall app/testing/f2_evidence.py
git diff --check
```

- [ ] **Step 5: Commit**

```text
feat(testing): add TEST-DB-F2 preflight evidence boundary
```

---

### Task 3: Authorization and source/prerequisite contract

**Files:**

- Create: `09_Разработка/backend/app/testing/f2_operator_preflight.py`
- Create:
  `09_Разработка/backend/migration_contract_tests/test_f2_operator_preflight_contract.py`

**Interfaces:**

- `F2_OPERATOR_PREFLIGHT_PROTOCOL =
  "test-db-f2-operator-preflight/v1"`.
- `F2_OPERATOR_PREFLIGHT_AUTHORIZATION =
  "I_AUTHORIZE_TEST_DB_F2_OPERATOR_PREFLIGHT"`.
- `F2OperatorPreflightStatus(StrEnum)` with exact `READY`, `FAILED`,
  `EVIDENCE_FAILED` machine values from the specification.
- `OperatorSourceState(source_sha, branch, tracked_clean, prerequisites)`.
- `OperatorSourceInspector.read_state(
  prerequisites: tuple[str, ...]) -> OperatorSourceState`.
- `load_operator_preflight_inputs(environment) -> F2ParentInputs`.

- [ ] **Step 1: Write RED contract tests**

Test exact preflight authorization, rejection of rehearsal authorization,
unknown/blank inputs, absence of secrets from repr/errors, Python version floor
and immutable values.

Test a fake source inspector for clean/wrong branch/dirty/malformed SHA/missing
ancestor. Test the default inspector by monkeypatching `subprocess.run` and
assert exact commands:

```text
git rev-parse HEAD
git status --porcelain --untracked-files=no
git branch --show-current
git merge-base --is-ancestor <sha> HEAD
```

Assert `shell=False`, one call per command, no secret environment and no retry.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_operator_preflight_contract.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

- [ ] **Step 3: Implement strict parser and inspector**

Require the preflight-only variable, reject any supplied rehearsal
authorization key, copy the mapping, remove the preflight key, insert the
internal F2 parser constant and call `load_parent_inputs`. Never echo raw
values.

Default source inspector uses `cwd=repository_root`, argument tuples,
`shell=False`, `check=False`, `capture_output=True`, `text=True`. Any OSError or
nonzero code returns only `TEST-DB-F2-SOURCE-UNSAFE`.

- [ ] **Step 4: Run GREEN and compile**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_operator_preflight_contract.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
python -m compileall app/testing/f2_operator_preflight.py
git diff --check
```

- [ ] **Step 5: Commit**

```text
feat(testing): add TEST-DB-F2 operator preflight contract
```

---

### Task 4: Offline state machine, artifact and CLI

**Files:**

- Modify: `09_Разработка/backend/app/testing/f2_operator_preflight.py`
- Create:
  `09_Разработка/backend/scripts/run_test_db_f2_operator_preflight.py`
- Create:
  `09_Разработка/backend/migration_contract_tests/test_f2_operator_preflight_runner.py`

**Interfaces:**

- `OperatorPreflightDependencies(source_inspector, uuid_factory, clock,
  publisher)`.
- `OperatorPreflightResult(preflight_id, source_sha, status,
  artifact_digest)`.
- `run_operator_preflight(environment, dependencies=None)
  -> OperatorPreflightResult`.
- CLI exit `0` only for `TEST_DB_F2_OPERATOR_PREFLIGHT_READY`.

- [ ] **Step 1: Write RED state-machine tests**

Success must prove exact order:

```text
parse authorization
→ source/prerequisites
→ Python >= 3.12
→ authorize all targets
→ external evidence root
→ UUIDv4 namespace
→ one canonical artifact
```

Cover every failure boundary, publisher failure precedence, existing namespace,
malformed UUID, safe result and recursive absence of environment secrets.
Sentinels for socket, connection, worker executor, Alembic and application
imports must remain unused.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_operator_preflight_runner.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

- [ ] **Step 3: Implement runner**

Use prerequisite tuple:

```python
F2_OPERATOR_PREFLIGHT_PREREQUISITES = (
    "20c7ea7",
    "03d4c59",
    "32ffec8",
)
```

Use branch `codex/b04b-maintenance-readiness-review`. Reserve
`operator-preflight-{preflight_id}` only after every non-filesystem check.
Publish `00_operator_preflight.json` with safe booleans, version tuple, ordered
role identity digests and `READY`. Catch failures into safe results; inability
to reserve/publish maps to `EVIDENCE_FAILED`.

- [ ] **Step 4: Implement thin CLI**

Print one compact sorted JSON object:

```json
{"artifact_digest":null,"preflight_id":null,"status":"TEST_DB_F2_OPERATOR_PREFLIGHT_FAILED"}
```

Never print exception text or environment values.

- [ ] **Step 5: Run GREEN and compile**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_operator_preflight_runner.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
python -m compileall `
  app/testing/f2_operator_preflight.py `
  scripts/run_test_db_f2_operator_preflight.py
git diff --check
```

- [ ] **Step 6: Commit**

```text
feat(testing): run TEST-DB-F2 operator preflight offline
```

---

### Task 5: Governance, documentation and closure

**Files:**

- Create:
  `09_Разработка/backend/migration_contract_tests/test_f2_operator_preflight_governance.py`
- Modify: `09_Разработка/.env.example`
- Modify: `09_Разработка/backend/.env.example`
- Modify: `docs/project/TASK_TEST_DB_F2_OPERATOR_PREFLIGHT_SPEC.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/ROADMAP.md`
- Modify: `docs/project/DECISIONS.md`

- [ ] **Step 1: Write governance tests**

AST/source checks reject:

- imports of `app.shared.db`, `app.main`, Alembic or application tests;
- socket/DNS APIs;
- `shell=True`, retry loops and wildcard DB discovery;
- create/drop/reset/rename database text;
- secret-bearing argv/output/evidence;
- rehearsal/accepted status production.

Assert default subprocess calls are exactly the Git allowlist.

- [ ] **Step 2: Add environment documentation**

Add only:

```text
# WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION
```

No assignment, example token, DSN, database name or ownership token.

- [ ] **Step 3: Run focused suite**

```powershell
python -m pytest `
  migration_contract_tests/test_f2_preflight.py `
  migration_contract_tests/test_f2_evidence.py `
  migration_contract_tests/test_f2_operator_preflight_contract.py `
  migration_contract_tests/test_f2_operator_preflight_runner.py `
  migration_contract_tests/test_f2_operator_preflight_governance.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

- [ ] **Step 4: Run full pure suite**

```powershell
python -m pytest migration_contract_tests -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

- [ ] **Step 5: Compile and scope audit**

```powershell
python -m compileall app/testing scripts/run_test_db_f2_operator_preflight.py
git diff --check
git status --short
git diff --name-only
```

Confirm no PostgreSQL, Alembic CLI, application suite, worker, DB lifecycle or
secret-bearing output occurred.

- [ ] **Step 6: Read-only review and remediation**

Review specification coverage, authorization separation, Git allowlist,
no-I/O-before-validation, external evidence containment, failure precedence and
secret redaction. Findings receive RED → GREEN fixes and repeated full pure
verification. Verdict must be `APPROVED` before closure.

- [ ] **Step 7: Record closure**

Use:

```text
IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED
```

Record exact focused/full counts and commits. Do not claim operator `READY` if
transient environment is absent.

- [ ] **Step 8: Commit closure**

```text
docs(testing): record TEST-DB-F2 operator preflight verification
```

- [ ] **Step 9: Execute offline preflight if environment is present**

Check only presence/absence of required variable names without printing values.
If complete, run the CLI after a clean commit and record its safe status/digest
outside repository. If incomplete, record `OPERATOR ENVIRONMENT NOT PRESENT`;
do not synthesize values and do not claim `READY`.

- [ ] **Step 10: Push**

Push `codex/b04b-maintenance-readiness-review`, verify local and remote HEAD
match, and leave the worktree clean.

---

## Plan self-review

- [x] Specification sections 1–11 map to Tasks 1–5.
- [x] Preflight authorization remains distinct from rehearsal authorization.
- [x] Existing F1/F2 authorization and evidence logic is reused, not weakened.
- [x] Git is the only subprocess allowlist.
- [x] No PostgreSQL/Alembic/application/worker execution is permitted.
- [x] External evidence cannot be confused with rehearsal evidence.
- [x] `READY` never means rehearsal verified or accepted.
- [x] Missing transient environment cannot be papered over.
