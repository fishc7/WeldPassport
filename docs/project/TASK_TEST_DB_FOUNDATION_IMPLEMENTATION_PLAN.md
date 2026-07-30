# TEST-DB Foundation Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Do not
> delegate unless the repository owner explicitly requests subagents. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, fail-closed TEST-DB-F1 bootstrap that selects and
authorizes a PostgreSQL test target before engine creation, routes Alembic to
that target, and provides an ownership-safe CI database lifecycle without
connecting to PostgreSQL in this gate.

**Architecture:** Pure URL and authorization code produces an immutable
`DatabaseTarget`; a bind-once registry fixes the process target before
`app.shared.db` creates its engine. Test collection binds the test target before
application imports, while live ownership and CI lifecycle logic depend on
injectable adapters so their complete behavior can be verified without a real
database.

**Tech Stack:** Python 3.14 runtime on this workstation, Python 3.12-compatible
source, SQLAlchemy 2, psycopg 3, Alembic, pytest, FastAPI test bootstrap,
PowerShell.

Статус: **IMPLEMENTED_UNVERIFIED / CODE ACCEPTED 2026-07-30**

## Global Constraints

- Accepted Specification:
  `docs/project/TASK_TEST_DB_FOUNDATION_SPEC.md`.
- Accepted architecture:
  `docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary.md`.
- Work only in:
  `D:\WeldPassport\.worktrees\b04b-maintenance-readiness`.
- Planning base HEAD:
  `7299824542bc705483d0be6e3a28575565e24484`.
- Preserve the accepted uncommitted architecture documentation.
- Use TDD and capture the focused RED before implementation for every task.
- Run only pure tests in `migration_contract_tests/`.
- Do not connect to PostgreSQL, resolve live credentials, run Alembic commands,
  application tests, or any CI create/drop operation.
- Do not modify canonical models, domain services, API behavior, migrations,
  revision files, baseline artifacts or workforce.
- Preserve the current search path and `POSTGRES_SCHEMA` behavior in F1; Runtime
  Compatibility Profile owns their later separation.
- Do not introduce a CI-provider workflow or runner binding in F1. Implement a
  provider-neutral lifecycle library and its pure contract only.
- The explicit future CI administrative DSN variable is
  `WELDPASSPORT_TEST_DB_ADMIN_URL`; F1 never reads or connects it.
- Provider/runner binding is deferred to the separately authorized
  `TEST-DB-F2-CI-BINDING` gate with the exact transient handoff contract in
  Task 5.
- Never render a full DSN, password, host, user or ownership token in errors,
  `repr`, logs or reports.
- Do not stage, commit or push without separate repository-owner authorization.
- Each task ends with a review checkpoint instead of an automatic commit.

## File map

Create:

- `09_Разработка/backend/app/shared/database_target.py` — pure URL parsing,
  normalization, offline safety checks and redacted errors.
- `09_Разработка/backend/app/shared/database_bootstrap.py` — bind-once target
  registry used before engine creation.
- `09_Разработка/backend/app/shared/test_database_ownership.py` — read-only live
  identity/marker verification through an injected query adapter.
- `09_Разработка/backend/test_support/__init__.py` — test infrastructure package.
- `09_Разработка/backend/test_support/ci_database_lifecycle.py` — exact owned
  ephemeral database orchestration through an injected admin adapter.
- `09_Разработка/backend/migration_contract_tests/test_database_target.py`.
- `09_Разработка/backend/migration_contract_tests/test_database_bootstrap.py`.
- `09_Разработка/backend/migration_contract_tests/test_test_database_ownership.py`.
- `09_Разработка/backend/migration_contract_tests/test_alembic_target_routing.py`.
- `09_Разработка/backend/migration_contract_tests/test_ci_database_lifecycle.py`.

Modify:

- `09_Разработка/backend/app/shared/db.py` — create engine from the bound target.
- `09_Разработка/backend/migrations/env.py` — use the same process target.
- `09_Разработка/backend/tests/conftest.py` — bind test target before application
  imports and verify ownership before Alembic.
- `09_Разработка/backend/tests/test_db_safety.py` — compatibility re-export of
  the new pure guard during F1; removal is deferred.
- `09_Разработка/backend/migration_contract_tests/test_test_db_safety_interlock.py`
  — update the accepted ADR-029 fixture-order contract to the new ownership
  gate.
- `09_Разработка/backend/.env.example`.
- `09_Разработка/.env.example`.

No other implementation file is in scope.

---

### Task 1: Immutable database target and offline safety contract

**Files:**

- Create:
  `09_Разработка/backend/app/shared/database_target.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_database_target.py`

**Interfaces:**

- Produces:
  `DatabasePurpose`, `DatabaseIdentity`, `DatabaseTarget`,
  `TestDatabaseAuthorization`, `DatabaseTargetError`,
  `parse_database_target()` and `authorize_test_database()`.
- Consumed by Tasks 2–5.

- [ ] **Step 1: Add failing type and normalization tests**

Create tests that import:

```python
from app.shared.database_target import (
    DatabasePurpose,
    DatabaseTargetError,
    authorize_test_database,
    parse_database_target,
)
```

Use this safe URL fixture:

```python
WORKING_URL = "postgresql+psycopg://worker:secret@db.example:5432/weldpassport"
TEST_URL = "postgresql+psycopg://tester:other@DB.EXAMPLE/wp_test_run_001"
```

Assert:

```python
target = parse_database_target(TEST_URL, DatabasePurpose.TEST)
assert target.purpose is DatabasePurpose.TEST
assert target.database_name == "wp_test_run_001"
assert target.identity.host == "db.example"
assert target.identity.port == 5432
assert "secret" not in repr(target)
assert "other" not in repr(target)
```

Parameterize rejection of:

- missing/blank `TEST_DATABASE_URL`;
- non-PostgreSQL and `postgresql+psycopg2` drivers;
- missing host or database name;
- `postgres`, `template0`, `template1`, `weldpassport`;
- names outside `^(?:test_.+|.+_test|.+_test_.+)$`;
- missing or non-exact `YES`;
- missing/mismatched confirmation;
- missing/blank ownership token;
- normalized test/work identity collision;
- same database name as working target even when host strings differ.

Every failure must expose a stable code but none of:

```text
secret
other
db.example
worker
tester
ownership token value
```

- [ ] **Step 2: Run focused RED**

From `09_Разработка/backend`:

```powershell
$PythonExe = "C:\Users\Andrey\AppData\Local\Programs\Python\Python314\python.exe"
& $PythonExe -m pytest migration_contract_tests/test_database_target.py -q
```

Expected: collection fails because `app.shared.database_target` does not exist.

- [ ] **Step 3: Implement the exact value objects**

Use these public shapes:

```python
class DatabasePurpose(StrEnum):
    WORKING = "working"
    TEST = "test"


@dataclass(frozen=True)
class DatabaseIdentity:
    drivername: str
    host: str
    port: int
    database: str


@dataclass(frozen=True)
class DatabaseTarget:
    purpose: DatabasePurpose
    url: URL = field(repr=False)
    identity: DatabaseIdentity
    database_name: str


@dataclass(frozen=True)
class TestDatabaseAuthorization:
    target: DatabaseTarget
    ownership_token: str = field(repr=False)
```

`DatabaseTargetError` must store `code` and a safe constant/detail string.
Its string form is:

```python
f"{self.code}: {self.safe_detail}"
```

Accepted driver is exactly `postgresql+psycopg`. Normalize host with
`casefold()`, default port to `5432`, and compare identities without username,
password or query parameters.

- [ ] **Step 4: Implement offline authorization**

Use:

```python
def parse_database_target(
    raw_url: str,
    purpose: DatabasePurpose,
) -> DatabaseTarget:
    ...


def authorize_test_database(
    *,
    test_database_url: str | None,
    working_database_url: str,
    destructive_opt_in: str | None,
    confirmed_database_name: str | None,
    ownership_token: str | None,
) -> TestDatabaseAuthorization:
    ...
```

The function must apply the accepted regex and denylist, exact confirmation,
exact opt-in, non-empty token, normalized identity inequality and conservative
same-database-name rejection.

- [ ] **Step 5: Run focused GREEN and redaction scan**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_database_target.py -q
rg -n "password|ownership_token|render_as_string" `
  app/shared/database_target.py `
  migration_contract_tests/test_database_target.py
```

Expected: focused tests pass; any matched line is reviewed to prove no secret is
rendered.

- [ ] **Step 6: Review checkpoint**

Report test count, public interfaces and exact error codes. Do not stage or
commit.

---

### Task 2: Bind-once process bootstrap and engine boundary

**Files:**

- Create:
  `09_Разработка/backend/app/shared/database_bootstrap.py`
- Modify:
  `09_Разработка/backend/app/shared/db.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_database_bootstrap.py`

**Interfaces:**

- Consumes: `DatabaseTarget`, `DatabasePurpose`, `parse_database_target()`.
- Produces: `DatabaseTargetRegistry`, `bind_database_target()`,
  `get_bound_database_target()` and `get_or_bind_working_target()`.

- [ ] **Step 1: Add failing registry tests**

Test a fresh instance, not the module-global registry:

```python
registry = DatabaseTargetRegistry()
bound = registry.bind(test_target)
assert bound is test_target
assert registry.require_bound() is test_target
```

Then assert:

```python
with pytest.raises(DatabaseTargetError) as exc:
    registry.bind(another_target)
assert exc.value.code == "DATABASE-TARGET-ALREADY-BOUND"
```

Also assert that repeated bind of the same object is rejected; there is no reset
or mutation method.

- [ ] **Step 2: Run focused RED**

```powershell
& $PythonExe -m pytest migration_contract_tests/test_database_bootstrap.py -q
```

Expected: missing module/import failure.

- [ ] **Step 3: Implement the registry**

Use an instance-level `threading.Lock` and:

```python
class DatabaseTargetRegistry:
    def bind(self, target: DatabaseTarget) -> DatabaseTarget:
        ...

    def require_bound(self) -> DatabaseTarget:
        ...

    def get_or_bind_working(self, working_url: str) -> DatabaseTarget:
        ...
```

Export a single private module instance through the three module functions.
Do not expose a reset helper.

- [ ] **Step 4: Route `app.shared.db` through the registry**

Replace direct `settings.database_url` engine creation with:

```python
database_target = get_or_bind_working_target(settings.database_url)
engine = create_engine(
    database_target.url.render_as_string(hide_password=False)
)
```

Preserve unchanged:

- exported `engine`, `SessionLocal`, `get_db`, `Base`, `SCHEMA`;
- current connect listener and search path;
- sessionmaker options.

- [ ] **Step 5: Add an import-boundary subprocess test**

Run a fresh Python subprocess with no test bind and assert importing
`app.shared.db` binds `DatabasePurpose.WORKING`. Run another subprocess whose
script authorizes/binds a safe test target before importing `app.shared.db` and
asserts the engine URL database is `wp_test_run_001`.

The subprocess must only construct SQLAlchemy engines; it must not call
`connect()`.

- [ ] **Step 6: Run focused GREEN**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_database_target.py `
  migration_contract_tests/test_database_bootstrap.py -q
```

Expected: all focused tests pass without PostgreSQL access.

- [ ] **Step 7: Review checkpoint**

Show that no engine exists before the registry choice in the test subprocess
and that the existing DB public API remains available. Do not stage or commit.

---

### Task 3: Live identity/ownership verifier and pytest import order

**Files:**

- Create:
  `09_Разработка/backend/app/shared/test_database_ownership.py`
- Modify:
  `09_Разработка/backend/tests/conftest.py`
- Modify:
  `09_Разработка/backend/tests/test_db_safety.py`
- Modify:
  `09_Разработка/backend/migration_contract_tests/test_test_db_safety_interlock.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_test_database_ownership.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_database_bootstrap.py`

**Interfaces:**

- Consumes: `TestDatabaseAuthorization`, `bind_database_target()`.
- Produces: `LiveDatabaseIdentity`, `read_live_database_identity()` and
  `verify_test_database_ownership()`.

Use these exact public signatures:

```python
@dataclass(frozen=True)
class LiveDatabaseIdentity:
    database_name: str
    server_address: str
    server_port: int
    database_comment: str | None


def read_live_database_identity(
    connection: Connection,
) -> LiveDatabaseIdentity:
    ...


def verify_test_database_ownership(
    connection: Connection,
    authorization: TestDatabaseAuthorization,
    *,
    resolved_host_addresses: frozenset[str] | None = None,
) -> None:
    ...
```

When `resolved_host_addresses` is `None`, the function resolves the target host
with `socket.getaddrinfo`. Tests always inject a fixed set.

- [ ] **Step 1: Add failing live-verifier tests with a fake connection**

The query adapter returns:

```python
{
    "database_name": "wp_test_run_001",
    "server_address": "127.0.0.1",
    "server_port": 5432,
    "database_comment": "weldpassport-test-db:owner-token-001",
}
```

Test success plus failures for:

- wrong database name;
- server port mismatch;
- server address outside injected resolved address set;
- missing comment;
- wrong marker prefix;
- wrong token.

Expected failure codes are `TEST-DB-TARGET-UNSAFE` or
`TEST-DB-OWNERSHIP-MISMATCH`. Error text must not include address, port, host or
token.

- [ ] **Step 2: Run focused RED**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_test_database_ownership.py -q
```

Expected: missing module/import failure.

- [ ] **Step 3: Implement the read-only verifier**

Use one SQLAlchemy `text()` statement against `pg_catalog.pg_database`:

```sql
SELECT
    current_database() AS database_name,
    inet_server_addr()::text AS server_address,
    inet_server_port() AS server_port,
    shobj_description(d.oid, 'pg_database') AS database_comment
FROM pg_catalog.pg_database AS d
WHERE d.datname = current_database()
```

Expected marker:

```python
f"weldpassport-test-db:{authorization.ownership_token}"
```

Inject the resolved host-address set into verification. Production resolution
uses `socket.getaddrinfo`; tests pass a fixed set. No raw DB exception is copied
into a public error.

- [ ] **Step 4: Move offline bind before application imports in conftest**

The first project imports in `tests/conftest.py` must be limited to:

```python
from app.shared.config import settings
from app.shared.database_bootstrap import bind_database_target
from app.shared.database_target import (
    DatabaseTargetError,
    authorize_test_database,
)
```

At module import:

```python
try:
    TEST_DATABASE_AUTHORIZATION = authorize_test_database(
        test_database_url=os.getenv("TEST_DATABASE_URL"),
        working_database_url=settings.database_url,
        destructive_opt_in=os.getenv("WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS"),
        confirmed_database_name=os.getenv("WELDPASSPORT_TEST_DB_CONFIRM"),
        ownership_token=os.getenv("WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN"),
    )
    bind_database_target(TEST_DATABASE_AUTHORIZATION.target)
except DatabaseTargetError as exc:
    raise pytest.UsageError(str(exc)) from None
```

Only after this block import canonical metadata, `app.main`, domain models and
`app.shared.db`.

- [ ] **Step 5: Put live verification before Alembic**

Import `engine` after bind. Replace the temporary session safety fixture with a
session-scoped autouse fixture that:

```python
with engine.connect() as connection:
    verify_test_database_ownership(
        connection,
        TEST_DATABASE_AUTHORIZATION,
    )
```

Make `_apply_migrations` depend on this fixture. Preserve the current application
fixtures and row cleanup unchanged.

- [ ] **Step 6: Keep the old helper as a compatibility re-export**

`tests/test_db_safety.py` must contain no independent policy. Re-export or wrap
the new offline authorization function only as needed by existing pure
contracts. Do not keep a second regex or denylist.

- [ ] **Step 7: Add AST/import-order assertions**

Extend `test_database_bootstrap.py` to assert:

- `authorize_test_database` and `bind_database_target` occur before
  `app.shared.canonical_metadata`, `app.main` and `app.shared.db` imports;
- the live fixture is a dependency of `_apply_migrations`;
- no connection or Alembic call occurs at collection time.

- [ ] **Step 8: Run focused GREEN**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_database_target.py `
  migration_contract_tests/test_database_bootstrap.py `
  migration_contract_tests/test_test_database_ownership.py -q
```

Expected: all tests pass without PostgreSQL access.

- [ ] **Step 9: Review checkpoint**

Report the exact import order and demonstrate that live verification precedes
`command.upgrade`. Do not run `tests/`. Do not stage or commit.

---

### Task 4: Alembic target routing

**Files:**

- Modify:
  `09_Разработка/backend/migrations/env.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_alembic_target_routing.py`

**Interfaces:**

- Consumes: `get_or_bind_working_target()` and the process-bound target.
- Produces: identical offline/online Alembic URL routing through
  `DatabaseTarget`.

- [ ] **Step 1: Add failing source-contract tests**

Assert that `migrations/env.py`:

- obtains one `database_target`;
- sets `sqlalchemy.url` from that target;
- creates the online engine from the same target;
- does not reference `settings.database_url` in either engine/config call;
- preserves `canonical_metadata`, `include_name`, `include_object`,
  `version_table_schema="public"` and the existing connect listener;
- contains no `TEST_DATABASE_URL`, fallback or database creation logic.

- [ ] **Step 2: Run focused RED**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_alembic_target_routing.py -q
```

Expected: assertions fail because `migrations/env.py` still uses
`settings.database_url` directly.

- [ ] **Step 3: Implement one-target routing**

After loading settings:

```python
database_target = get_or_bind_working_target(settings.database_url)
database_url = database_target.url.render_as_string(hide_password=False)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
```

Use `database_url` for online `create_engine()`. Do not change migration
metadata, filters, transaction behavior or search path.

- [ ] **Step 4: Run focused GREEN and existing Alembic contracts**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_alembic_target_routing.py `
  migration_contract_tests/test_alembic_cli_contract.py `
  migration_contract_tests/test_alembic_boundary.py -q
```

Expected: all selected pure tests pass; no Alembic command is executed.

- [ ] **Step 5: Review checkpoint**

Show the single URL source for offline and online paths. Do not stage or commit.

---

### Task 5: Provider-neutral CI ephemeral database lifecycle

**Files:**

- Create:
  `09_Разработка/backend/test_support/__init__.py`
- Create:
  `09_Разработка/backend/test_support/ci_database_lifecycle.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_ci_database_lifecycle.py`

**Interfaces:**

- Consumes: `DatabaseTargetError`, accepted name/marker contract.
- Produces: `CiAdminAdapter`, `EphemeralDatabaseLease`,
  `CiDatabaseLifecycle.provision()` and `CiDatabaseLifecycle.cleanup()`.

**Deferred CI binding contract:**

- exact admin input:
  `WELDPASSPORT_TEST_DB_ADMIN_URL`;
- only `TEST-DB-F2-CI-BINDING` may read/connect this value;
- after `provision()`, the F2 runner derives a test URL by parsing the admin URL
  with SQLAlchemy and replacing only its database component with
  `lease.database_name`;
- it launches the application-test child process with a fresh explicit
  environment containing:

```text
TEST_DATABASE_URL=<derived transient URL>
WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES
WELDPASSPORT_TEST_DB_CONFIRM=<lease.database_name>
WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN=<lease.ownership_token>
```

- these values are never written to `.env`, repository files, logs or reports;
- the child environment is discarded before marker recheck and cleanup;
- provider-specific workflow and concrete admin connection remain outside F1.

- [ ] **Step 1: Add failing orchestration tests**

Define a fake adapter recording calls. Test:

```python
lease = lifecycle.provision(run_id="4815", nonce="a1b2c3d4")
assert lease.database_name == "wp_test_4815_a1b2c3d4"
assert fake.calls == [
    ("create", lease.database_name),
    ("write_marker", lease.database_name, lease.marker),
    ("read_marker", lease.database_name),
]
```

Test cleanup requires:

```python
fake.marker = lease.marker
lifecycle.cleanup(lease)
assert fake.calls[-2:] == [
    ("read_marker", lease.database_name),
    ("drop", lease.database_name),
]
```

Also test refusal for:

- invalid run id/nonce characters;
- name longer than PostgreSQL 63-byte identifier limit;
- pre-existing generated name;
- marker write/read mismatch;
- altered lease;
- foreign database name;
- cleanup called twice;
- adapter failure.

No API may list databases or delete by prefix.

- [ ] **Step 2: Run focused RED**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_ci_database_lifecycle.py -q
```

Expected: missing package/module failure.

- [ ] **Step 3: Implement exact lifecycle types**

Use:

```python
class CiAdminAdapter(Protocol):
    def database_exists(self, database_name: str) -> bool: ...
    def create_database(self, database_name: str) -> None: ...
    def write_marker(self, database_name: str, marker: str) -> None: ...
    def read_marker(self, database_name: str) -> str | None: ...
    def drop_database(self, database_name: str) -> None: ...


@dataclass(frozen=True)
class EphemeralDatabaseLease:
    database_name: str
    ownership_token: str = field(repr=False)
    marker: str = field(repr=False)


class CiDatabaseLifecycle:
    def provision(
        self,
        *,
        run_id: str,
        nonce: str,
    ) -> EphemeralDatabaseLease:
        ...

    def cleanup(self, lease: EphemeralDatabaseLease) -> None:
        ...
```

`CiDatabaseLifecycle` accepts an adapter and a token generator. Generated names
must match `wp_test_<run_id>_<nonce>`, use only lowercase ASCII letters/digits/
underscore, and stay within 63 bytes.

- [ ] **Step 4: Implement fail-closed provision and cleanup**

Provision order is exact:

1. validate/generate name and token;
2. reject if `database_exists(name)`;
3. create exact name;
4. write exact `weldpassport-test-db:<token>` marker;
5. read it back;
6. return lease only after exact match.

Cleanup order is exact:

1. validate immutable lease fields and name pattern;
2. read exact target marker;
3. reject mismatch;
4. drop exact target;
5. mark the lifecycle instance cleaned to reject a second cleanup.

If marker publication fails after create, return a stable failure and do not
attempt an unverified drop in F1 orchestration.

- [ ] **Step 5: Prove absence of broad deletion**

Add source assertions rejecting:

```text
list_databases
pg_database scan for cleanup
LIKE
startswith-based deletion
wildcard
```

The adapter may check existence and read the exact named database only.

- [ ] **Step 6: Run focused GREEN**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_ci_database_lifecycle.py -q
```

Expected: all focused tests pass with the fake adapter; no database calls occur.

- [ ] **Step 7: Review checkpoint**

Report exact provision/cleanup traces and all refusal cases. Do not add a CI
workflow, stage or commit.

---

### Task 6: Environment documentation and pure acceptance

**Files:**

- Modify:
  `09_Разработка/backend/.env.example`
- Modify:
  `09_Разработка/.env.example`
- Review all files listed in this plan.

**Interfaces:**

- Consumes: completed Tasks 1–5.
- Produces: operator-visible variable contract and TEST-DB-F1 verification
  evidence.

- [ ] **Step 1: Document placeholders without secrets**

Append to both examples:

```dotenv
# Required only for PostgreSQL application/integration pytest.
TEST_DATABASE_URL=
WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=
WELDPASSPORT_TEST_DB_CONFIRM=
WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN=
```

Do not provide a real URL, username, password, database name or token.

- [ ] **Step 2: Run all focused Foundation tests**

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_database_target.py `
  migration_contract_tests/test_database_bootstrap.py `
  migration_contract_tests/test_test_database_ownership.py `
  migration_contract_tests/test_alembic_target_routing.py `
  migration_contract_tests/test_ci_database_lifecycle.py -q
```

Expected: all pass.

- [ ] **Step 3: Run the complete pure migration contract suite**

```powershell
& $PythonExe -m pytest migration_contract_tests -q
```

Expected: all tests pass; existing intentional skip count is reported exactly.

- [ ] **Step 4: Compile changed Python**

```powershell
& $PythonExe -m compileall `
  app/shared/database_target.py `
  app/shared/database_bootstrap.py `
  app/shared/test_database_ownership.py `
  app/shared/db.py `
  migrations/env.py `
  tests/conftest.py `
  test_support/ci_database_lifecycle.py
```

Expected: exit code 0.

- [ ] **Step 5: Verify forbidden activity and diff scope**

```powershell
git diff --check
git status --short
git diff --name-only
```

Confirm:

- only accepted architecture docs plus files listed in this plan changed;
- no application `tests/` were run;
- no Alembic CLI was run;
- no PostgreSQL connection/create/drop occurred;
- no revision, baseline, workforce or domain file changed;
- no secrets appear in diff.

- [ ] **Step 6: Produce the implementation report**

Report:

- changed files;
- RED evidence per task;
- focused and full pure test counts;
- compile and `git diff --check` results;
- explicit statement that PostgreSQL/Alembic/application tests were not run;
- status `IMPLEMENTED_UNVERIFIED`;
- proposed diff for owner acceptance.

Do not stage, commit or push.

## Self-review checklist

- Every requirement in Sections 5–13 of
  `TASK_TEST_DB_FOUNDATION_SPEC.md` maps to Tasks 1–6.
- Local automatic create/drop is absent.
- CI workflow/provider binding is absent; provider-neutral exact-target
  lifecycle is complete.
- Runtime profile, legacy metadata and workforce are untouched.
- The current `POSTGRES_SCHEMA`/search-path behavior is preserved for the next
  Runtime Compatibility Profile gate.
- All public signatures are defined before first consumption.
- No reset hook weakens the bind-once target.
- No raw exception or object representation can expose secret material.
- Gate closure remains `IMPLEMENTED_UNVERIFIED` until isolated PostgreSQL
  acceptance.

## Implementation checkpoint — 2026-07-30

Реализация TEST-DB-F1 выполнена inline по TDD без PostgreSQL и application
tests:

- Task 1: initial RED — missing `database_target`; GREEN — `19 passed`;
  дополнительный traceback-redaction RED подтверждён отдельно, итог —
  `20 passed`;
- Task 2: initial RED — missing `database_bootstrap`; combined GREEN —
  `25 passed`;
- Task 3: live verifier RED — missing module; conftest RED —
  `3 failed, 6 passed`; ADR-029 compatibility RED — `1 failed, 9 passed`;
  итоговый combined GREEN — `46 passed`;
- Task 4: Alembic routing RED — `1 failed, 1 passed`; GREEN —
  `14 passed`;
- Task 5: initial RED — missing `test_support`; GREEN — `14 passed`;
- final focused Foundation suite после independent-review remediation —
  `83 passed`;
- fresh full pure suite после всех изменений —
  `677 passed, 2 skipped`;
- changed Python compile — exit `0`;
- `git diff --check` — exit `0`.

Full pure suite выполняет существующие read-only Alembic graph commands
`heads/history`, но не выполняет connection, `upgrade`, `stamp` или migrations
execution. PostgreSQL, application `tests/`, CI create/drop и isolated
acceptance не запускались.

Текущий статус: `IMPLEMENTED_UNVERIFIED / CODE ACCEPTED 2026-07-30`.
Stage, commit и push не выполнялись.

### Independent review remediation

Read-only independent review verdict: `WITH FIXES`, no Critical findings.
Remediation:

- all SQLAlchemy URL query parameters are rejected before connection so psycopg
  cannot override authorized host/port/dbname;
- malformed, zero, negative and greater-than-65535 ports fail with the stable
  redacted code;
- token-factory exceptions and non-string values are sanitized;
- denylist coverage includes `template0` and `template1`;
- broad cleanup governance test includes a mutation check;
- catalog scan, regex, wildcard и SQL pattern variants также покрыты
  broad-cleanup mutation tests;
- exact `WELDPASSPORT_TEST_DB_ADMIN_URL` and transient child-environment
  contract are fixed above; concrete binding is named
  `TEST-DB-F2-CI-BINDING`.
