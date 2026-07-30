# Authentication Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace production trust in `X-User-Id` with local accounts, opaque
server-side sessions, CSRF protection and a server-derived
`AuthenticatedActor`.

**Architecture:** A new `app.identity` module owns credentials, sessions and
authentication audit. `app.shared.auth` composes an authenticated account with
an HR worker-status port, while business RBAC remains in `hr.worker_roles`.
Existing endpoints retain a temporary server-derived integer adapter; the
header adapter exists only in `tests/`.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL 18.3, Alembic,
Pydantic 2, `argon2-cffi`, pytest.

## Global Constraints

- Production code must not read or trust `X-User-Id`.
- `user_account`, `worker` and `worker_roles` remain separate concepts.
- Password hashing is Argon2id; raw passwords and tokens never enter DB/logs.
- Session tokens contain 256 random bits; only SHA-256 digests are persisted.
- Cookies default to `Secure`, `HttpOnly` for session and `SameSite=Lax`.
- Unsafe methods require session-bound CSRF.
- Identity does not duplicate HR role/scope policy.
- No production account is seeded by migration.
- Domain Model, Migration, Service/API and Tests are separate commits/gates.
- Live PostgreSQL commands require a new separately authorized owned disposable
  test DB; pure tasks do not imply that authorization.

---

## File Structure

Create:

- `app/identity/__init__.py` — package boundary and router export;
- `app/identity/constants.py` — stable statuses, event types and error codes;
- `app/identity/domain.py` — immutable actor/principal values and policies;
- `app/identity/security.py` — Argon2id and token/hash primitives;
- `app/identity/models.py` — three canonical ORM tables;
- `app/identity/repository.py` — account/session/event persistence;
- `app/identity/services.py` — login/session/password/operator use cases;
- `app/identity/schemas.py` — Pydantic HTTP contracts;
- `app/identity/api.py` — `/auth` routes and cookie handling;
- `app/identity/operator_cli.py` — explicit offline account lifecycle;
- `app/hr/actor_port.py` — HR-owned worker-status adapter;
- `migrations/versions/20260730_28_identity.py` — additive identity migration;
- `migration_contract_tests/test_identity_domain.py`;
- `migration_contract_tests/test_identity_models.py`;
- `migration_contract_tests/test_identity_migration.py`;
- `migration_contract_tests/test_identity_services.py`;
- `migration_contract_tests/test_identity_http_boundary.py`;
- `migration_contract_tests/test_identity_operator_cli.py`;
- `tests/auth_support.py` — test-only `X-User-Id` dependency override;
- `tests/test_identity_api.py` — live API integration tests.

Modify:

- `requirements.txt` — add Argon2 dependency;
- `app/shared/config.py` — fail-closed auth settings;
- `app/shared/auth.py` — session-derived dependencies;
- `app/shared/canonical_metadata.py` — identity schema/module and table count;
- `app/shared/db.py` — identity search path;
- `migrations/env.py` — identity search path;
- `migrations/canonical_boundary.py` — identity managed schema;
- `app/shared/application_factory.py` — include identity router;
- `tests/conftest.py` — install test-only header override;
- canonical project documentation and `TASK_REGISTRY.md`.

---

### Task 1: Security primitives and actor domain

**Files:**

- Create: `09_Разработка/backend/app/identity/__init__.py`
- Create: `09_Разработка/backend/app/identity/constants.py`
- Create: `09_Разработка/backend/app/identity/domain.py`
- Create: `09_Разработка/backend/app/identity/security.py`
- Modify: `09_Разработка/backend/requirements.txt`
- Modify: `09_Разработка/backend/app/shared/config.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_identity_domain.py`

**Interfaces:**

- Produces:
  - `AuthenticatedPrincipal(account_id: UUID, auth_method: str)`
  - `AuthenticatedActor(account_id, session_id, worker_id, authenticated_at, auth_method, must_change_password)`
  - `AuthenticationProvider.authenticate(login, password, now) -> AuthenticatedPrincipal`
  - `PasswordHasher.hash_password(str) -> str`
  - `PasswordHasher.verify_password(str, str) -> bool`
  - `generate_secret() -> str`
  - `digest_secret(str) -> str`
  - `validate_new_password(str) -> None`

- [ ] **Step 1: Write failing domain/security tests**

```python
def test_password_hash_is_argon2id_and_verifies():
    encoded = PasswordHasher().hash_password("correct horse battery")
    assert encoded.startswith("$argon2id$")
    assert PasswordHasher().verify_password("correct horse battery", encoded)
    assert not PasswordHasher().verify_password("wrong password", encoded)


def test_secret_digest_is_stable_without_storing_secret():
    secret = generate_secret()
    assert len(secret) >= 43
    assert digest_secret(secret) == digest_secret(secret)
    assert secret not in digest_secret(secret)


def test_actor_is_immutable():
    actor = AuthenticatedActor(
        account_id=uuid4(),
        session_id=uuid4(),
        worker_id=1,
        authenticated_at=datetime.now(UTC),
        auth_method="LOCAL_PASSWORD",
        must_change_password=False,
    )
    with pytest.raises(FrozenInstanceError):
        actor.worker_id = 2
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest migration_contract_tests/test_identity_domain.py -q
```

Expected: collection fails because `app.identity.domain` and
`app.identity.security` do not exist.

- [ ] **Step 3: Add dependency and exact settings**

Add `argon2-cffi>=23.1.0` to `requirements.txt`.

Add settings with these names/defaults:

```python
auth_cookie_secure: bool = True
auth_session_idle_minutes: int = 30
auth_session_absolute_hours: int = 12
auth_session_touch_minutes: int = 5
auth_max_failed_logins: int = 5
auth_lock_minutes: int = 15
auth_password_min_length: int = 12
deployment_environment: Literal["production", "development"] = "production"
```

Add `validate_auth_configuration()` which raises
`RuntimeContractError("AUTH-CONFIG-UNSAFE", "production authentication cookies must be Secure")` when
`deployment_environment == "production"` and `auth_cookie_secure is not True`.

- [ ] **Step 4: Implement immutable values and primitives**

Use `@dataclass(frozen=True)`. `generate_secret()` uses
`secrets.token_urlsafe(32)`. `digest_secret()` returns lowercase SHA-256 hex.
Configure `argon2.PasswordHasher` with `type=Type.ID`.

`validate_new_password()` raises:

```python
DomainError(
    422,
    "PASSWORD_POLICY_FAILED",
    "Пароль не соответствует политике безопасности",
)
```

Never interpolate the rejected password.

- [ ] **Step 5: Run GREEN and dependency audit**

```powershell
python -m pytest migration_contract_tests/test_identity_domain.py -q
python -m compileall -q app/identity app/shared/config.py
```

Expected: all tests pass; compile exit 0.

- [ ] **Step 6: Commit Domain primitives**

```powershell
git add 09_Разработка/backend/requirements.txt `
  09_Разработка/backend/app/shared/config.py `
  09_Разработка/backend/app/identity `
  09_Разработка/backend/migration_contract_tests/test_identity_domain.py
git commit -m "feat(identity): add authentication domain primitives"
```

---

### Task 2: Canonical identity ORM model

**Files:**

- Create: `09_Разработка/backend/app/identity/models.py`
- Modify: `09_Разработка/backend/app/shared/canonical_metadata.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_identity_models.py`
- Test: existing canonical metadata contract tests

**Interfaces:**

- Produces ORM classes `UserAccount`, `IdentitySession`,
  `AuthenticationEvent`.
- Table names: `identity.user_accounts`, `identity.sessions`,
  `identity.authentication_events`.

- [ ] **Step 1: Write failing metadata/model tests**

Tests assert:

```python
assert set(identity_tables) == {
    "identity.user_accounts",
    "identity.sessions",
    "identity.authentication_events",
}
assert UserAccount.__table__.c.worker_id.unique is True
assert UserAccount.__table__.c.normalized_login.unique is True
assert "password" not in IdentitySession.__table__.c
assert IdentitySession.__table__.c.token_hash.type.length == 64
assert IdentitySession.__table__.c.csrf_token_hash.type.length == 64
```

Also assert canonical schemas include `identity`, model modules include
`app.identity.models`, and canonical table count is `76`.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest migration_contract_tests/test_identity_models.py -q
```

Expected: import failure for missing `app.identity.models`.

- [ ] **Step 3: Implement tables**

Use `Base` from `app.shared.orm`; UUID PKs use
`postgresql.UUID(as_uuid=True)` with Python `uuid4`.

Required DB checks:

```text
status IN ('ACTIVE', 'DISABLED')
failed_login_count >= 0
record_version > 0
idle_expires_at <= absolute_expires_at
revocation_reason IS NULL OR revoked_at IS NOT NULL
event_type IN accepted event set
length(token_hash) = 64
length(csrf_token_hash) = 64
```

Use FK `identity.user_accounts.worker_id → hr.workers.id ON DELETE RESTRICT`,
unique nullable worker binding, and `sessions.account_id → user_accounts.id
ON DELETE RESTRICT`.

- [ ] **Step 4: Register canonical boundary**

Modify:

```python
CANONICAL_SCHEMAS = frozenset(
    {"identity", "hr", "welding", "project", "engineering", "quality"}
)
CANONICAL_MODEL_MODULES = (
    "app.identity.models",
    "app.hr.models",
    "app.welding.models",
    "app.projects.models",
    "app.engineering.models",
    "app.engineering.import_models",
    "app.quality.models",
    "app.quality.execution_models",
    "app.quality.quality_finding_models",
    "app.quality.engineering_evaluation_models",
    "app.quality.defect_models",
    "app.quality.defect_disposition_models",
    "app.quality.quality_decision_models",
)
_CURRENT_CANONICAL_TABLE_COUNT = 76
```

- [ ] **Step 5: Run GREEN and full metadata contracts**

```powershell
python -m pytest migration_contract_tests/test_identity_models.py `
  migration_contract_tests/test_canonical_metadata.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit Domain Model**

```powershell
git add 09_Разработка/backend/app/identity/models.py `
  09_Разработка/backend/app/shared/canonical_metadata.py `
  09_Разработка/backend/migration_contract_tests/test_identity_models.py
git commit -m "feat(identity): add canonical account and session model"
```

---

### Task 3: Additive Alembic migration

**Files:**

- Create: `09_Разработка/backend/migrations/versions/20260730_28_identity.py`
- Modify: `09_Разработка/backend/migrations/env.py`
- Modify: `09_Разработка/backend/app/shared/db.py`
- Modify: `09_Разработка/backend/migrations/canonical_boundary.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_identity_migration.py`

**Interfaces:**

- Revision: `20260730_28_identity`
- Down revision: `canonical_baseline_v1`
- Produces the exact three tables from Task 2.

- [ ] **Step 1: Write failing migration governance tests**

Tests parse the revision and assert:

```python
assert revision == "20260730_28_identity"
assert down_revision == "canonical_baseline_v1"
assert created_schemas == ["identity"]
assert created_tables == [
    "user_accounts",
    "sessions",
    "authentication_events",
]
assert not seeded_credentials
```

Assert downgrade first executes a PostgreSQL block that raises when any identity
table is non-empty, then drops tables in reverse FK order and drops schema.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest migration_contract_tests/test_identity_migration.py -q
```

Expected: migration file missing.

- [ ] **Step 3: Write exact migration**

Create schema with:

```python
op.execute(sa.text('CREATE SCHEMA "identity"'))
```

Create tables/checks/indexes matching ORM. Do not insert accounts, password
hashes or sessions.

Downgrade guard:

```sql
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM identity.user_accounts LIMIT 1)
     OR EXISTS (SELECT 1 FROM identity.sessions LIMIT 1)
     OR EXISTS (SELECT 1 FROM identity.authentication_events LIMIT 1)
  THEN
    RAISE EXCEPTION 'identity downgrade refused: tables are not empty';
  END IF;
END
$$;
```

- [ ] **Step 4: Add identity to migration/runtime search path and boundary**

Both `migrations/env.py` and `app/shared/db.py` use:

```text
"identity", project, engineering, hr, welding, quality, public
```

Update `canonical_boundary.py` managed schema allowlist to include `identity`.

- [ ] **Step 5: Run pure migration contracts**

```powershell
python -m pytest migration_contract_tests/test_identity_migration.py `
  migration_contract_tests/test_canonical_metadata.py `
  migration_contract_tests/test_b04_active_graph.py -q
```

Expected: all pass; active head is `20260730_28_identity`.

- [ ] **Step 6: Commit Migration**

```powershell
git add 09_Разработка/backend/migrations/versions/20260730_28_identity.py `
  09_Разработка/backend/migrations/env.py `
  09_Разработка/backend/app/shared/db.py `
  09_Разработка/backend/migrations/canonical_boundary.py `
  09_Разработка/backend/migration_contract_tests/test_identity_migration.py
git commit -m "feat(migrations): add identity authentication schema"
```

---

### Task 4: Repository and authentication services

**Files:**

- Create: `09_Разработка/backend/app/identity/repository.py`
- Create: `09_Разработка/backend/app/identity/services.py`
- Create: `09_Разработка/backend/app/hr/actor_port.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_identity_services.py`

**Interfaces:**

- `IdentityRepository.get_account_by_normalized_login(login) -> UserAccount | None`
- `IdentityRepository.get_account(account_id) -> UserAccount | None`
- `IdentityRepository.get_session_by_hash(token_hash) -> IdentitySession | None`
- `IdentityRepository.add_session(session) -> None`
- `IdentityRepository.revoke_session(session, reason, now) -> None`
- `IdentityRepository.revoke_account_sessions(account_id, reason, now) -> int`
- `IdentityRepository.add_event(event) -> None`
- `HrActorPort.require_active_worker(worker_id: int) -> None`
- `IdentityService.login(login, password, now) -> IssuedSession`
- `IdentityService.resolve_actor(session_token, now) -> AuthenticatedActor`
- `IdentityService.logout(session_token, csrf_token, now) -> None`
- `IdentityService.logout_all(actor, csrf_token, now) -> int`
- `IdentityService.change_password(actor, current, new, csrf, now) -> None`
- `LocalPasswordAuthenticationProvider.authenticate(login, password, now) -> AuthenticatedPrincipal`

- [ ] **Step 1: Write service RED tests with fakes**

Cover:

- generic failure for unknown login and bad password;
- fifth failure sets `locked_until = now + 15 minutes`;
- successful login clears failure state and returns two raw secrets only in
  `IssuedSession`;
- DB-facing objects contain only hashes;
- disabled/locked accounts fail generically;
- expired/revoked session returns stable 401 code;
- CSRF mismatch returns `CSRF_VALIDATION_FAILED`;
- password change revokes every account session;
- touch occurs only after 5 minutes;
- inactive worker is rejected by `HrActorPort`.
- `must_change_password` actor is rejected by the business worker adapter with
  `PASSWORD_CHANGE_REQUIRED`.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest migration_contract_tests/test_identity_services.py -q
```

Expected: missing repository/service modules.

- [ ] **Step 3: Implement normalization and constant-time failure path**

`normalize_login(value)` returns `value.strip().casefold()` and rejects blank
input. For an unknown account, verify the supplied password against one fixed
startup-generated Argon2id dummy hash before returning generic failure.

- [ ] **Step 4: Implement transactional service methods**

Each public method receives one SQLAlchemy session/repository and commits only
at the API/operator boundary. Use SQLAlchemy `with_for_update()` row locking
for login failure counter, password change and session revocation.

`IssuedSession` is frozen and contains:

```python
actor: AuthenticatedActor
session_token: str = field(repr=False)
csrf_token: str = field(repr=False)
idle_expires_at: datetime
absolute_expires_at: datetime
```

- [ ] **Step 5: Implement HR adapter**

`HrActorPort` queries only inside `app.hr`, treats missing/dismissed/suspended
worker as `ACTOR_WORKER_INACTIVE`, and exposes no HR ORM object to identity.

- [ ] **Step 6: Run GREEN**

```powershell
python -m pytest migration_contract_tests/test_identity_services.py -q
python -m compileall -q app/identity app/hr/actor_port.py
```

- [ ] **Step 7: Commit Service layer**

```powershell
git add 09_Разработка/backend/app/identity/repository.py `
  09_Разработка/backend/app/identity/services.py `
  09_Разработка/backend/app/hr/actor_port.py `
  09_Разработка/backend/migration_contract_tests/test_identity_services.py
git commit -m "feat(identity): add account and session services"
```

---

### Task 5: HTTP authentication boundary and test-only adapter

**Files:**

- Create: `09_Разработка/backend/app/identity/schemas.py`
- Create: `09_Разработка/backend/app/identity/api.py`
- Modify: `09_Разработка/backend/app/identity/__init__.py`
- Modify: `09_Разработка/backend/app/shared/auth.py`
- Modify: `09_Разработка/backend/app/shared/application_factory.py`
- Create: `09_Разработка/backend/tests/auth_support.py`
- Modify: `09_Разработка/backend/tests/conftest.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_identity_http_boundary.py`
- Test: `09_Разработка/backend/tests/test_identity_api.py`

**Interfaces:**

- `get_authenticated_actor(request, db) -> AuthenticatedActor`
- `get_current_user_id(actor, hr_port) -> int`
- routes `/api/v1/auth/login`, `/me`, `/logout`, `/logout-all`,
  `/change-password`.

- [ ] **Step 1: Write pure boundary RED tests**

AST/import tests assert:

```python
assert "X-User-Id" not in production_auth_source
assert "Header(" not in production_auth_source
assert "app.identity.api" in CANONICAL_ROUTER_SPECS
```

Dependency tests assert missing/invalid cookies return the stable codes and no
fallback reads request headers.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest migration_contract_tests/test_identity_http_boundary.py -q
```

- [ ] **Step 3: Implement schemas and cookie policy**

`LoginRequest` forbids extras and constrains login/password length without
echoing values. Response contains account/worker ids and expiry only.

Cookie calls:

```python
response.set_cookie(
    "wp_session",
    issued.session_token,
    httponly=True,
    secure=settings.auth_cookie_secure,
    samesite="lax",
    path="/",
    max_age=12 * 60 * 60,
)
response.set_cookie(
    "wp_csrf",
    issued.csrf_token,
    httponly=False,
    secure=settings.auth_cookie_secure,
    samesite="lax",
    path="/",
    max_age=12 * 60 * 60,
)
```

- [ ] **Step 4: Replace production header dependency**

`app.shared.auth.get_current_user_id` depends on
`get_authenticated_actor` and `HrActorPort`; it never declares a Header
parameter. It rejects `must_change_password=True` before worker/RBAC lookup.
Existing business endpoints remain source-compatible.

Call `validate_auth_configuration()` while constructing the application.
Pure tests assert production plus insecure cookies fails before router use,
while development plus insecure cookies is explicitly allowed.

- [ ] **Step 5: Add test-only override**

`tests/auth_support.py` is the only file that parses:

```python
async def test_current_user_id(
    x_user_id: int | None = Header(None, alias="X-User-Id"),
) -> int:
    if x_user_id is None:
        raise HTTPException(401, "test actor required")
    return x_user_id
```

`tests/conftest.py` installs:

```python
app.dependency_overrides[get_current_user_id] = test_current_user_id
```

and clears/reinstalls it without removing `get_db` overrides.

- [ ] **Step 6: Add live API integration tests**

Tests create one account/worker through repository fixtures, login over HTTPS
TestClient, verify cookie flags, `/me`, CSRF failure, logout, revoked session,
generic login failure, temporary-password business rejection,
password-change session revocation, normalized-login uniqueness and concurrent
lockout serialization.

- [ ] **Step 7: Run pure GREEN**

```powershell
python -m pytest migration_contract_tests/test_identity_http_boundary.py -q
```

Do not run `tests/test_identity_api.py` until separately authorized PostgreSQL
is available.

- [ ] **Step 8: Commit Service/API gate**

```powershell
git add 09_Разработка/backend/app/identity `
  09_Разработка/backend/app/shared/auth.py `
  09_Разработка/backend/app/shared/application_factory.py `
  09_Разработка/backend/tests/auth_support.py `
  09_Разработка/backend/tests/conftest.py `
  09_Разработка/backend/tests/test_identity_api.py `
  09_Разработка/backend/migration_contract_tests/test_identity_http_boundary.py
git commit -m "feat(identity): enforce server authenticated API actors"
```

---

### Task 6: Offline operator lifecycle

**Files:**

- Create: `09_Разработка/backend/app/identity/operator_cli.py`
- Create: `09_Разработка/backend/scripts/manage_identity.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_identity_operator_cli.py`

**Interfaces:**

- Commands: `create-account`, `bind-worker`, `disable-account`,
  `unlock-account`, `set-temporary-password`, `revoke-sessions`.
- Password input only through `getpass.getpass`.
- Mutating commands require exact `--confirm-login`.

- [ ] **Step 1: Write CLI RED tests**

Inject parser, getpass and repository dependencies. Assert:

- password is absent from argv/help/result;
- wrong confirmation causes no repository calls;
- create normalizes login and sets `must_change_password=True`;
- disable and password reset revoke sessions;
- output contains only safe status, account id and event code;
- exception text is replaced by `IDENTITY_OPERATOR_FAILED`.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest migration_contract_tests/test_identity_operator_cli.py -q
```

- [ ] **Step 3: Implement CLI**

`scripts/manage_identity.py` performs only path bootstrap and calls
`app.identity.operator_cli.main()`. No password-bearing CLI option exists.
Every mutation writes an authentication event in the same transaction.

- [ ] **Step 4: Run GREEN and help smoke**

```powershell
python -m pytest migration_contract_tests/test_identity_operator_cli.py -q
python scripts/manage_identity.py --help
```

Expected: tests pass; help lists commands and contains no password option.

- [ ] **Step 5: Commit operator gate**

```powershell
git add 09_Разработка/backend/app/identity/operator_cli.py `
  09_Разработка/backend/scripts/manage_identity.py `
  09_Разработка/backend/migration_contract_tests/test_identity_operator_cli.py
git commit -m "feat(identity): add safe account operator lifecycle"
```

---

### Task 7: Pure closure, documentation and PostgreSQL handoff

**Files:**

- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/project/DECISIONS.md`
- Modify: `docs/project/PROJECT_STATUS.yaml`
- Modify: `docs/project/PROJECT_SUMMARY.md`
- Modify: `docs/project/ROADMAP.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/ADR-034-authentication-boundary.md`

**Interfaces:**

- Pure status: `IMPLEMENTED_UNVERIFIED / PURE VERIFIED`.
- Operational status remains pending until separately authorized PostgreSQL
  evidence and owner acceptance.

- [ ] **Step 1: Run focused pure suites**

```powershell
python -m pytest migration_contract_tests/test_identity_domain.py `
  migration_contract_tests/test_identity_models.py `
  migration_contract_tests/test_identity_migration.py `
  migration_contract_tests/test_identity_services.py `
  migration_contract_tests/test_identity_http_boundary.py `
  migration_contract_tests/test_identity_operator_cli.py -q
```

- [ ] **Step 2: Run full pure suite**

```powershell
python -m pytest migration_contract_tests -q
```

- [ ] **Step 3: Run compile/diff/secret checks**

```powershell
python -m compileall -q app/identity app/hr/actor_port.py app/shared/auth.py
git diff --check
git status --short
rg -n "X-User-Id" app
rg -n "password.*print|token.*print" app/identity scripts/manage_identity.py
```

Expected: `X-User-Id` has no production matches; unsafe print scan has no
matches.

- [ ] **Step 4: Record pure checkpoint**

Record changed files, commits, focused/full counts and explicit statements:

- PostgreSQL/Alembic/application suite not run in pure closure;
- `AUTHENTICATION_BOUNDARY_ACCEPTED` not assigned;
- next gate requires a new owned disposable PostgreSQL 18.3 DB and separate
  operator authorization.

- [ ] **Step 5: Commit pure closure**

```powershell
git add docs
git commit -m "docs(identity): record pure authentication verification"
```

- [ ] **Step 6: Stop at operational authorization boundary**

Do not create/reuse/drop a PostgreSQL DB. Present the exact live commands and
request separate authorization for a fresh isolated identity acceptance run.
