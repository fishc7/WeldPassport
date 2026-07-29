# B-04A Volatile Endpoint Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать B-04A operator/evidence flow устойчивым к переназначению
динамического Docker host-порта после перезапуска Docker Desktop.

**Architecture:** Owned container остаётся источником identity и текущего
runtime endpoint. `StartOwnedContainer` атомарно reconciles только порт двух
session URL, а `RunEquivalenceEvidence` остаётся read-only относительно session
и fail-closed проверяет mapping и TCP до Alembic. Python runner и оба Alembic
context получают ограниченные таймауты.

**Tech Stack:** Windows PowerShell 5.1, Docker Desktop, PostgreSQL 16, Python
3.12, SQLAlchemy 2, psycopg 3, Alembic, pytest.

## Global Constraints

- Рабочий каталог: `D:\WeldPassport\.worktrees\b04-baseline`.
- Только disposable container с точными ID, name и ownership label.
- Mapping принимается только как единственная строка `127.0.0.1:<port>`.
- Не наследовать application `.env` и не ослаблять B-04 destructive interlock.
- Не выводить URL, пароль или ownership token.
- Не изменять migration 23, frozen historical revisions, baseline candidate,
  fingerprint policy или B-04B.
- `RunEquivalenceEvidence` не обновляет session и не делает retry.
- Commit, push и cleanup — только после отдельного подтверждения владельца.

---

## File map

**Modify**

- `.superpowers/sdd/task-6-provision-and-autogenerate.ps1` — ownership,
  port-mapping, atomic session refresh и operator preflight.
- `.superpowers/sdd/test_task_6_operator_helper.py` — pure contracts helper.
- `09_Разработка/backend/migrations/b04/verify_baseline.py` — bounded
  subprocess/connect operations.
- `09_Разработка/backend/migrations/b04/historical_context/env.py` — bounded
  historical connection.
- `09_Разработка/backend/migrations/b04/candidate_context/env.py` — bounded
  candidate connection.
- `09_Разработка/backend/migration_contract_tests/test_b04_verify_runner.py` —
  runner timeout contracts.
- `09_Разработка/backend/migration_contract_tests/test_b04_historical_context.py`
  — historical context contract.
- `09_Разработка/backend/migration_contract_tests/test_b04_candidate_context.py`
  — candidate context contract.
- `.superpowers/sdd/task-7-report.md` и `.superpowers/sdd/progress.md` —
  ignored execution evidence.
- `docs/project/TASK_B-04A_BASELINE_BUILD_VERIFICATION_IMPLEMENTATION_PLAN.md`
  — итоговый Task 7 status после operator gate.

**Create**

- `docs/project/TASK_B-04A_VOLATILE_ENDPOINT_RECOVERY_CLAUDE_CODE_PROMPT.md` —
  точный execution prompt.

---

### Task 1: Pure port-mapping and session URL contracts

**Files:**

- Modify: `.superpowers/sdd/task-6-provision-and-autogenerate.ps1`
- Test: `.superpowers/sdd/test_task_6_operator_helper.py`

**Interfaces:**

- Produces:
  - `Get-OwnedPublishedPort([string]$ContainerId) -> [int]`
  - `Get-B04SessionUrlPort([string]$Url, [string]$ExpectedDatabase) -> [int]`
  - `Set-B04SessionUrlPort([string]$Url, [string]$ExpectedDatabase,
    [int]$Port) -> [string]`

- [ ] **Step 1: Add failing mapping contracts**

Add tests that inspect the helper and require:

```python
assert "function Get-OwnedPublishedPort" in helper
assert "& docker port $ContainerId 5432/tcp" in helper
assert "^127\\.0\\.0\\.1:(\\d+)$" in helper
assert "B04-OPERATOR-HOST-PORT" in helper
```

Also require one mapping only, port range `1..65535`, full container ID and no
container-name fallback.

- [ ] **Step 2: Verify RED**

Run:

```powershell
& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest .superpowers/sdd/test_task_6_operator_helper.py -q
```

Expected: the new mapping/session tests fail because the functions are absent.

- [ ] **Step 3: Implement exact mapping parser**

Implement:

```powershell
function Get-OwnedPublishedPort {
    param([string]$ContainerId)
    Assert-OwnedContainerRunning -ContainerId $ContainerId
    $lines = @(& docker port $ContainerId 5432/tcp)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw 'B04-OPERATOR-HOST-PORT'
    }
    $mapping = $lines[0].Trim()
    if ($mapping -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'B04-OPERATOR-HOST-PORT'
    }
    $port = [int]$Matches[1]
    if ($port -lt 1 -or $port -gt 65535) {
        throw 'B04-OPERATOR-HOST-PORT'
    }
    return $port
}
```

Session URL functions must accept only:

```text
postgresql+psycopg://<existing-userinfo>@127.0.0.1:<port>/<expected-db>
```

They may replace only the numeric port. Driver, userinfo, host and database
must be byte-for-byte preserved.

- [ ] **Step 4: Verify GREEN**

Run the focused helper suite. Expected: all helper contracts pass.

- [ ] **Step 5: Review gate**

Reviewer checks non-loopback, multiple mappings, malformed URL, wrong database,
port bounds and absence of secret output. Do not proceed on Critical/Important
findings.

---

### Task 2: Atomic protected-session reconciliation

**Files:**

- Modify: `.superpowers/sdd/task-6-provision-and-autogenerate.ps1`
- Test: `.superpowers/sdd/test_task_6_operator_helper.py`

**Interfaces:**

- Consumes Task 1 port and URL functions.
- Produces:
  - `Update-B04SessionEndpointAtomically([string]$SessionPath,
    [int]$Port) -> void`
  - `Assert-B04SessionEndpoint([int]$Port) -> void`

- [ ] **Step 1: Write failing preservation tests**

Require tests proving the refresh path:

```python
for token in (
    "WELDPASSPORT_B04_OWNERSHIP_TOKEN",
    "WELDPASSPORT_B04_CONTAINER_ID",
    "WELDPASSPORT_B04_BASELINE_URL",
    "WELDPASSPORT_B04_HISTORICAL_URL",
    "New-B04SessionContent",
    "New-ProtectedFile",
    "[IO.File]::Replace",
):
    assert token in refresh_function
```

Require same-directory temporary file, cleanup in `finally`,
`Assert-B04SessionContent` before replacement, exact
`[IO.File]::Replace(..., $false)` and no printing of session content. A
post-replace `Set-CurrentUserOnlyAcl` call is forbidden: Windows must preserve
the original DACL during the non-ignoring replace.

- [ ] **Step 2: Verify RED**

Expected: refresh-contract tests fail because no atomic reconciliation exists.

- [ ] **Step 3: Implement minimal atomic refresh**

Algorithm:

```text
load already validated env values
derive baseline URL with new port
derive historical URL with new port
regenerate complete session content
create same-directory protected temp file
write UTF-8 without BOM
parse/validate content
File.Replace(temp, session, no backup, do not ignore metadata/ACL errors)
update only current-process URL env values
always remove leftover temp file
```

If the current URLs already use the actual port, do not rewrite the file.

Any failure before/during replace emits a stable
`B04-OPERATOR-SESSION-REFRESH` family code. Do not perform a second
non-atomic rewrite or post-replace ACL mutation.

- [ ] **Step 4: Verify preservation**

Tests must execute the extracted actual PowerShell functions in a temporary
directory rather than only scanning source tokens. They must prove unchanged:

- ownership token;
- container ID;
- database username/password;
- baseline/historical database names;
- exact variable set.

Only the two URL port fields may differ. Also execute:

- no-op when both ports already match;
- successful atomic refresh;
- injected failure before replace leaves the original bytes unchanged;
- strict `File.Replace(..., $false)` contract;
- no output containing URL, password or token.

- [ ] **Step 5: Run helper suite and parser**

Run:

```powershell
& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest .superpowers/sdd/test_task_6_operator_helper.py -q

$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path '.superpowers/sdd/task-6-provision-and-autogenerate.ps1'),
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { throw 'PARSER-FAILED' }
```

- [ ] **Step 6: Review gate**

Reviewer verifies atomicity, ACL, cleanup boundaries and secret non-disclosure.

---

### Task 3: Start-mode reconciliation and evidence fail-fast preflight

**Files:**

- Modify: `.superpowers/sdd/task-6-provision-and-autogenerate.ps1`
- Test: `.superpowers/sdd/test_task_6_operator_helper.py`

**Interfaces:**

- Consumes Tasks 1–2.
- Produces:
  - `Test-B04TcpEndpoint([int]$Port, [int]$TimeoutMilliseconds) -> void`
  - stable mismatch/unreachable operator codes.

- [ ] **Step 1: Write failing mode-boundary tests**

`StartOwnedContainer` must call, in order:

```text
Assert-OwnedContainer
docker start <full ID>
pg_isready condition loop
Get-OwnedPublishedPort
Update-B04SessionEndpointAtomically
Assert-B04SessionEndpoint
Test-B04TcpEndpoint
PostgreSQL 16 check
success marker
```

`RunEquivalenceEvidence` must call:

```text
Assert-OwnedContainerRunning
Get-OwnedPublishedPort
Assert-B04SessionEndpoint
Test-B04TcpEndpoint
Python verifier
```

It must not call the update function, `docker start`, `docker rm`,
`Remove-Item` or session replacement.

- [ ] **Step 2: Verify RED**

Expected: new ordering and non-mutation assertions fail.

- [ ] **Step 3: Implement bounded TCP probe**

Use `System.Net.Sockets.TcpClient` and `ConnectAsync` with a fixed wait. Connect
only to literal `127.0.0.1` and the validated port. Dispose in `finally`.

On timeout/refusal emit:

```text
B04-OPERATOR-ENDPOINT-UNREACHABLE
```

- [ ] **Step 4: Wire start and evidence modes**

Start mode may reconcile the protected session. Evidence mode may only compare
and reject:

```text
B04-OPERATOR-SESSION-PORT-MISMATCH
```

Both modes clear all B-04 env variables in `finally`.

- [ ] **Step 5: Verify GREEN and legacy behavior**

Run all helper tests and confirm:

- Cleanup/Recover still use identity-only validation;
- stopped containers remain removable;
- offline SQL mode does not touch Docker;
- mode ambiguity still fails closed.

- [ ] **Step 6: Independent review**

Reviewer checks mode separation, ordering, full-ID-only Docker calls and
absence of new destructive paths.

---

### Task 4: Bounded Python/Alembic connections and subprocesses

**Files:**

- Modify: `09_Разработка/backend/migrations/b04/verify_baseline.py`
- Modify: `09_Разработка/backend/migrations/b04/historical_context/env.py`
- Modify: `09_Разработка/backend/migrations/b04/candidate_context/env.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_b04_verify_runner.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_b04_historical_context.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_b04_candidate_context.py`

**Interfaces:**

- Existing verifier API and phase codes remain unchanged.
- Connection timeout: `10` seconds.
- Alembic subprocess timeout: `300` seconds.

- [ ] **Step 1: Write failing timeout tests**

Require:

```python
assert connect_args == {"connect_timeout": 10}
assert subprocess_timeout == 300
```

Simulate `subprocess.TimeoutExpired` and assert `_run()` converts it to the
existing label-specific `B04-VERIFY-<PHASE>` code without command output,
environment or secrets.

- [ ] **Step 2: Verify RED**

Run the three focused contract files. Expected: timeout assertions fail.

- [ ] **Step 3: Implement minimal timeout wiring**

Runner:

```python
subprocess.run(
    command,
    env=dict(environment),
    check=True,
    capture_output=True,
    text=True,
    timeout=300,
)
```

Fingerprint connections:

```python
create_engine(
    url,
    future=True,
    connect_args={"connect_timeout": 10},
).connect()
```

Both online Alembic contexts use:

```python
create_engine(
    database_url,
    poolclass=pool.NullPool,
    connect_args={"connect_timeout": 10},
)
```

Historical Windows environment remains exactly six `POSTGRES_*` variables plus
validated `SYSTEMROOT`; no general environment inheritance is allowed.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest `
  migration_contract_tests/test_b04_verify_runner.py `
  migration_contract_tests/test_b04_historical_context.py `
  migration_contract_tests/test_b04_candidate_context.py -q
```

- [ ] **Step 5: Run full pure regression**

```powershell
& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest migration_contract_tests -q
& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m compileall -q migrations/b04 migration_contract_tests
git diff --check
```

- [ ] **Step 6: Independent review**

Reviewer verifies exact timeouts, unchanged fail-closed codes and no URL query
or application-env fallback.

---

### Task 5: Operator reconciliation and evidence acceptance

**Files:**

- Modify after evidence:
  `.superpowers/sdd/task-7-report.md`
- Modify after evidence:
  `.superpowers/sdd/progress.md`
- Modify after evidence:
  `docs/project/TASK_B-04A_BASELINE_BUILD_VERIFICATION_IMPLEMENTATION_PLAN.md`

**Interfaces:**

- Consumes the reviewed implementation from Tasks 1–4.
- Produces accepted fingerprint and verification report artifacts.

- [ ] **Step 1: Run start reconciliation once**

Operator command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
  "Set-Location -LiteralPath 'D:\WeldPassport\.worktrees\b04-baseline'; & '.\.superpowers\sdd\task-6-provision-and-autogenerate.ps1' -StartOwnedContainer"
```

Expected: `B04-OWNED-CONTAINER-RUNNING`.

- [ ] **Step 2: Verify mapping without secrets**

Confirm Docker mapping and sanitized session identities use the same
`127.0.0.1:<port>`, and TCP probe succeeds.

- [ ] **Step 3: Verify disposable DB state read-only**

Both databases must have no canonical schemas/tables or Alembic marker before
the evidence run. If state is non-empty, stop and diagnose; do not retry.

- [ ] **Step 4: Run one equivalence evidence**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
  "Set-Location -LiteralPath 'D:\WeldPassport\.worktrees\b04-baseline'; & '.\.superpowers\sdd\task-6-provision-and-autogenerate.ps1' -RunEquivalenceEvidence"
```

Expected: `B04-EQUIVALENCE-EVIDENCE-OK`.

- [ ] **Step 5: Verify accepted artifacts**

Require exactly:

```text
expected-fingerprint.json
expected-fingerprint.sha256
verification-report.json
```

Verify digest, `status=B04A_VERIFIED`, source SHA, both database identities,
73 canonical tables, 15 seed rows and governed index.

- [ ] **Step 6: Update closing documentation**

Record actual commands and fresh evidence. Do not mark B-04B active and do not
claim historical offline compatibility.

- [ ] **Step 7: Final diff and acceptance**

Report:

- changed files;
- diff summary;
- focused/full test results;
- operator evidence;
- remaining boundaries.

Do not stage, commit, push or cleanup until the owner provides separate
confirmation.
