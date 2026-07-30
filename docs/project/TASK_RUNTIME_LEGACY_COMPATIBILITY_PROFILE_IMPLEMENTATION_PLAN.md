# RUNTIME-COMPAT-1 Pure Runtime Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать `canonical` фактическим runtime default, физически отделить
legacy workforce metadata и добавить fail-closed `legacy_compatibility`
composition с pure/read-only preflight contracts без запуска PostgreSQL.

**Architecture:** Environment сначала разрешается в immutable
`RuntimeConfiguration`. Application factory лениво загружает canonical routers,
а workforce metadata/router — только для explicit legacy profile. Lifespan
выполняет canonical marker preflight, затем при legacy profile read-only
contract/privilege preflight и только после успеха подключает workforce router.

**Tech Stack:** Python 3.12+, FastAPI 0.115+, SQLAlchemy 2, Alembic 1.14+,
Pydantic Settings 2.7+, pytest 8.3+, PostgreSQL catalog contracts.

## Global Constraints

- Рабочий каталог: `09_Разработка/backend`.
- Реализация только `RUNTIME-COMPAT-1`; PostgreSQL, Alembic CLI и application
  `tests/` не запускать.
- Не изменять Alembic revisions, `canonical_baseline_v1`, domain models,
  canonical services/API или поведение workforce endpoints.
- Не создавать schema/table, не выполнять DDL/DML, auto-repair, `create_all`,
  migration, stamp или fallback.
- Canonical metadata остаётся ровно 73 таблицы в схемах
  `hr`, `welding`, `project`, `engineering`, `quality`.
- `WELDPASSPORT_RUNTIME_PROFILE` отсутствует — `canonical`; explicit empty и
  unknown — `RUNTIME-PROFILE-UNKNOWN`.
- `WELDPASSPORT_LEGACY_SCHEMA` читается только для legacy profile; default
  `test`; значение обязано быть PostgreSQL identifier.
- Diagnostics не содержат DSN, host, user, password, ownership token или raw DB
  exception.
- Каждый task начинается RED test, заканчивается focused GREEN и отдельной
  приёмкой.
- Команды commit в плане являются checkpoint-предложениями. Не выполнять
  `git add`, `git commit` или push без отдельного разрешения владельца.

---

## File Structure

### Новые production modules

- `app/shared/runtime_profile.py` — enum, immutable configuration, environment
  resolver и safe runtime error.
- `app/shared/runtime_marker.py` — active Alembic head resolver и read-only
  canonical marker preflight.
- `app/shared/application_factory.py` — lazy canonical composition, lifespan и
  guarded OpenAPI readiness.
- `app/workforce/legacy_orm.py` — отдельный `LegacyBase` и bind-once schema.
- `app/workforce/legacy_contract.py` — deterministic expected executable
  contract, выведенный из `LegacyBase.metadata`.
- `app/workforce/legacy_preflight.py` — read-only catalog/privilege snapshot,
  comparator и stable failures.

### Изменяемые production files

- `app/shared/config.py` — raw environment inputs profile/schema.
- `app/main.py` — compatible ASGI export через application factory.
- `app/workforce/models.py` — только перенос с canonical `Base/SCHEMA` на
  `LegacyBase/bound legacy schema`.

### Pure tests

- `migration_contract_tests/test_runtime_profile.py`
- `migration_contract_tests/test_legacy_metadata_boundary.py`
- `migration_contract_tests/test_legacy_contract.py`
- `migration_contract_tests/test_legacy_preflight.py`
- `migration_contract_tests/test_runtime_marker.py`
- `migration_contract_tests/test_application_factory.py`

### Existing tests/docs

- `migration_contract_tests/test_canonical_metadata.py` — усилить invariant,
  что explicit workforce import не меняет canonical metadata.
- `migration_contract_tests/test_alembic_boundary.py` — сохранить exact
  canonical metadata boundary.
- `tests/conftest.py` — удалить временный import-order workaround; сами
  application tests в этом gate не запускать.
- `09_Разработка/.env.example`, `09_Разработка/backend/.env.example` —
  документировать profile inputs без значений/секретов.
- `docs/ARCHITECTURE.md`, `docs/project/DECISIONS.md`,
  `docs/project/TASK_REGISTRY.md`,
  `docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC.md` — closure
  только после приёмки кода.

---

### Task 1: Runtime profile and immutable configuration

**Files:**

- Create: `09_Разработка/backend/app/shared/runtime_profile.py`
- Modify: `09_Разработка/backend/app/shared/config.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_runtime_profile.py`

**Interfaces:**

- Produces:
  - `RuntimeProfile(StrEnum)`
  - `RuntimeConfiguration(profile: RuntimeProfile, legacy_schema: str | None)`
  - `RuntimeContractError(code: str, safe_detail: str)`
  - `validate_legacy_schema_identifier(raw: str) -> str`
  - `resolve_runtime_configuration(*, runtime_profile: str | None,
    legacy_schema: str | None) -> RuntimeConfiguration`
- Later tasks consume `RuntimeConfiguration` and `RuntimeContractError`.

- [ ] **Step 1: Write RED tests for exact profile parsing**

```python
def test_runtime_001_absent_profile_is_canonical() -> None:
    config = resolve_runtime_configuration(
        runtime_profile=None,
        legacy_schema='ignored invalid "schema"',
    )
    assert config == RuntimeConfiguration(
        profile=RuntimeProfile.CANONICAL,
        legacy_schema=None,
    )


@pytest.mark.parametrize("raw", ["", "CANONICAL", "unknown", " canonical "])
def test_runtime_002_explicit_invalid_profile_fails(raw: str) -> None:
    with pytest.raises(RuntimeContractError) as exc_info:
        resolve_runtime_configuration(runtime_profile=raw, legacy_schema=None)
    assert exc_info.value.code == "RUNTIME-PROFILE-UNKNOWN"
```

- [ ] **Step 2: Run the focused test and confirm RED**

```powershell
python -m pytest migration_contract_tests/test_runtime_profile.py -q
```

Expected: collection fails because `app.shared.runtime_profile` is absent.

- [ ] **Step 3: Implement the immutable resolver**

```python
class RuntimeProfile(StrEnum):
    CANONICAL = "canonical"
    LEGACY_COMPATIBILITY = "legacy_compatibility"


@dataclass(frozen=True)
class RuntimeConfiguration:
    profile: RuntimeProfile
    legacy_schema: str | None


class RuntimeContractError(RuntimeError):
    def __init__(self, code: str, safe_detail: str) -> None:
        self.code = code
        self.safe_detail = safe_detail
        super().__init__(f"{code}: {safe_detail}")
```

Resolver requirements:

```python
_POSTGRES_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_legacy_schema_identifier(raw: str) -> str:
    if _POSTGRES_IDENTIFIER.fullmatch(raw) is None:
        raise RuntimeContractError(
            "LEGACY-CONTRACT-MISMATCH",
            "legacy schema identifier is invalid",
        )
    return raw


def resolve_runtime_configuration(
    *,
    runtime_profile: str | None,
    legacy_schema: str | None,
) -> RuntimeConfiguration:
    if runtime_profile is None:
        profile = RuntimeProfile.CANONICAL
    else:
        try:
            profile = RuntimeProfile(runtime_profile)
        except ValueError:
            raise RuntimeContractError(
                "RUNTIME-PROFILE-UNKNOWN",
                "runtime profile is not supported",
            ) from None

    if profile is RuntimeProfile.CANONICAL:
        return RuntimeConfiguration(profile=profile, legacy_schema=None)

    resolved_schema = "test" if legacy_schema is None else legacy_schema
    validate_legacy_schema_identifier(resolved_schema)
    return RuntimeConfiguration(profile=profile, legacy_schema=resolved_schema)
```

`config.py` получает только raw fields:

```python
runtime_profile: str | None = Field(
    default=None,
    validation_alias="WELDPASSPORT_RUNTIME_PROFILE",
)
legacy_schema: str | None = Field(
    default=None,
    validation_alias="WELDPASSPORT_LEGACY_SCHEMA",
)
```

Не валидировать legacy schema внутри `Settings`: canonical profile обязан
полностью игнорировать этот input.

- [ ] **Step 4: Add redaction tests**

Проверить, что `repr(config)` не содержит legacy secret-like input после
canonical resolution, а `RuntimeContractError` не включает raw input.

- [ ] **Step 5: Run focused GREEN**

```powershell
python -m pytest migration_contract_tests/test_runtime_profile.py -q
python -m compileall app/shared/runtime_profile.py app/shared/config.py
```

- [ ] **Step 6: Review checkpoint**

Подтвердить: absent и explicit canonical различимы от empty; legacy schema не
читается canonical profile; exception безопасен.

- [ ] **Step 7: Commit permission gate**

Предложение: `feat(runtime): add explicit runtime profile contract`.
Остановиться и запросить отдельное разрешение до commit.

---

### Task 2: Isolate workforce metadata behind bind-once LegacyBase

**Files:**

- Create: `09_Разработка/backend/app/workforce/legacy_orm.py`
- Modify: `09_Разработка/backend/app/workforce/models.py`
- Modify: `09_Разработка/backend/migration_contract_tests/test_canonical_metadata.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_legacy_metadata_boundary.py`

**Interfaces:**

- Consumes: `RuntimeContractError`.
- Produces:
  - `LegacyBase(DeclarativeBase)`
  - `bind_legacy_schema(schema: str) -> str`
  - `get_or_bind_legacy_schema(default: str = "test") -> str`
  - `get_bound_legacy_schema() -> str`
- `app.workforce.models` exports the existing ORM class names unchanged.

- [ ] **Step 1: Write RED tests for physical metadata isolation**

Run the assertions in a fresh subprocess so prior module imports cannot hide
registry contamination:

```python
code = """
from app.shared.orm import Base
before = tuple(sorted(Base.metadata.tables))
from app.workforce.legacy_orm import bind_legacy_schema, LegacyBase
bind_legacy_schema("legacy_fixture")
import app.workforce.models
assert tuple(sorted(Base.metadata.tables)) == before
assert len(LegacyBase.metadata.tables) == 7
assert {t.schema for t in LegacyBase.metadata.tables.values()} == {"legacy_fixture"}
"""
subprocess.run([sys.executable, "-c", code], check=True, cwd=BACKEND_DIR)
```

Also assert repeated same-value bind is idempotent and different-value bind
fails with `LEGACY-CONTRACT-MISMATCH`.

- [ ] **Step 2: Run and confirm RED**

```powershell
python -m pytest `
  migration_contract_tests/test_legacy_metadata_boundary.py `
  migration_contract_tests/test_canonical_metadata.py -q
```

Expected: missing `legacy_orm` and current workforce tables contaminate
canonical `Base.metadata`.

- [ ] **Step 3: Implement isolated registry**

```python
class LegacyBase(DeclarativeBase):
    """Declarative registry used only by deprecated workforce compatibility."""


_schema_lock = Lock()
_bound_schema: str | None = None


def bind_legacy_schema(schema: str) -> str:
    validate_legacy_schema_identifier(schema)
    with _schema_lock:
        global _bound_schema
        if _bound_schema is None:
            _bound_schema = schema
        elif _bound_schema != schema:
            raise RuntimeContractError(
                "LEGACY-CONTRACT-MISMATCH",
                "legacy schema is already bound",
            )
        return _bound_schema
```

`get_or_bind_legacy_schema()` exists only to preserve explicit standalone
legacy imports and binds default `test`; no reset hook is allowed.

- [ ] **Step 4: Move workforce models without semantic edits**

Replace only:

```python
from app.workforce.legacy_orm import LegacyBase, get_or_bind_legacy_schema

SCHEMA = get_or_bind_legacy_schema()
Base = LegacyBase
```

All existing class names, columns, relationships, strings and endpoint behavior
remain byte-for-byte equivalent except the declarative registry/schema source.

- [ ] **Step 5: Strengthen canonical invariant**

Add a subprocess test that imports canonical metadata, then explicit workforce
models, and still observes exactly 73 canonical tables and unchanged canonical
keys.

- [ ] **Step 6: Run focused GREEN**

```powershell
python -m pytest `
  migration_contract_tests/test_legacy_metadata_boundary.py `
  migration_contract_tests/test_canonical_metadata.py -q
python -c "from app.workforce.repository import SvarshchikRepo; assert SvarshchikRepo.__name__ == 'SvarshchikRepo'"
```

Не запускать `tests/test_legacy_workforce_import.py` через pytest: родительский
`tests/conftest.py` активирует PostgreSQL application bootstrap. Прямой
`python -c` выше проверяет тот же import contract без pytest/conftest.

- [ ] **Step 7: Review checkpoint**

Inspect `git diff -- app/workforce/models.py`; reject any column, relationship,
endpoint or schema-default behavior change beyond registry/schema dependency.

- [ ] **Step 8: Commit permission gate**

Предложение: `refactor(runtime): isolate legacy workforce metadata`.
Остановиться и запросить отдельное разрешение до commit.

---

### Task 3: Build one deterministic legacy executable contract

**Files:**

- Create: `09_Разработка/backend/app/workforce/legacy_contract.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_legacy_contract.py`

**Interfaces:**

- Consumes: `LegacyBase.metadata`, bound schema.
- Produces immutable ordered types:
  - `LegacyColumnContract`
  - `LegacyUniqueContract`
  - `LegacyForeignKeyContract`
  - `LegacySequencePrivilegeContract`
  - `LegacyTableContract`
  - `LegacyExecutableContract`
  - `build_legacy_executable_contract() -> LegacyExecutableContract`
  - `normalize_postgresql_type(raw: str) -> str`

- [ ] **Step 1: Write RED deterministic-contract tests**

Tests must assert:

- seven exact table names from `LegacyBase.metadata`;
- sorted columns with normalized type and nullable;
- PK/UNIQUE/FK content independent of declaration iteration order;
- extra observed objects are not part of expected contract;
- writable tables are exactly `РАБОТНИКИ` and `СВАРЩИКИ`;
- all tables require `SELECT`;
- writable tables require `INSERT`, `UPDATE` and owned-PK sequence access;
- canonical metadata is not imported or mutated.

- [ ] **Step 2: Run and confirm RED**

```powershell
python -m pytest migration_contract_tests/test_legacy_contract.py -q
```

- [ ] **Step 3: Implement canonical contract dataclasses**

Use tuples sorted by UTF-8 table/column names; never sets/dicts in public
serialized form.

```python
@dataclass(frozen=True, order=True)
class LegacyColumnContract:
    name: str
    type_name: str
    nullable: bool


@dataclass(frozen=True)
class LegacyTableContract:
    name: str
    columns: tuple[LegacyColumnContract, ...]
    primary_key: tuple[str, ...]
    unique_constraints: tuple[LegacyUniqueContract, ...]
    foreign_keys: tuple[LegacyForeignKeyContract, ...]
    required_privileges: tuple[str, ...]
```

- [ ] **Step 4: Derive structure only from LegacyBase.metadata**

Compile expected SQLAlchemy types with PostgreSQL dialect, then normalize both
expected and future observed `format_type(...)` strings:

```python
_TYPE_ALIASES = {
    "varchar": "character varying",
    "int4": "integer",
    "int2": "smallint",
    "bool": "boolean",
}
```

Preserve length, e.g. `VARCHAR(150)` and `character varying(150)` both become
`character varying(150)`.

Для FK на legacy relation, не представленную ORM-классом (текущая
`ОБЪЕКТЫ`), читать `ForeignKey.target_fullname` без разрешения
`foreign_key.column`. Контракт обязан сохранить target schema/table/column и
проверить реальный FK в catalog, но не добавлять фиктивную ORM table.

The single explicit operation policy is:

```python
_WRITABLE_TABLES = frozenset({"РАБОТНИКИ", "СВАРЩИКИ"})
```

No second hand-written list of columns, PK, UNIQUE or FK is allowed.
Sequence privilege contract описывается как owned/autoincrement PK column, а не
как вручную угаданное имя sequence; observed sequence определяется catalog
relation/ownership.

- [ ] **Step 5: Run deterministic mutation tests**

Build a copied metadata fixture with one changed nullable/type/constraint and
assert exactly one corresponding contract difference.

- [ ] **Step 6: Run focused GREEN**

```powershell
python -m pytest `
  migration_contract_tests/test_legacy_contract.py `
  migration_contract_tests/test_legacy_metadata_boundary.py -q
```

- [ ] **Step 7: Review checkpoint**

Confirm the contract has one structural source (`LegacyBase.metadata`) and one
small explicit privilege policy; no full legacy fingerprint was introduced.

- [ ] **Step 8: Commit permission gate**

Предложение: `feat(runtime): define legacy executable contract`.
Остановиться и запросить отдельное разрешение до commit.

---

### Task 4: Implement read-only legacy catalog and privilege preflight

**Files:**

- Create: `09_Разработка/backend/app/workforce/legacy_preflight.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_legacy_preflight.py`

**Interfaces:**

- Consumes: `LegacyExecutableContract`, `RuntimeContractError`.
- Produces:
  - `ObservedLegacyContract`
  - `read_observed_legacy_contract(connection: Connection, schema: str)
    -> ObservedLegacyContract`
  - `compare_legacy_contract(expected, observed) -> None`
  - `run_legacy_preflight(connection: Connection, schema: str) -> None`

- [ ] **Step 1: Write RED comparator tests**

Cover exact safe codes:

- missing schema → `LEGACY-SCHEMA-MISSING`;
- missing relation/column, wrong type/nullability, missing PK/UNIQUE/FK →
  `LEGACY-CONTRACT-MISMATCH`;
- missing schema/table/sequence privilege →
  `LEGACY-PRIVILEGE-MISSING`;
- extra relation/column/index/constraint → allowed;
- raw adapter exceptions → safe contract error without raw text.

- [ ] **Step 2: Add read-only SQL governance test**

Parse every SQL literal from the module and assert the first keyword is
`SELECT` or `WITH`. Reject literals containing:

```text
INSERT UPDATE DELETE CREATE ALTER DROP TRUNCATE GRANT REVOKE COMMENT
```

Also mutation-test the denylist so the governance assertion cannot pass
vacuously.

- [ ] **Step 3: Run and confirm RED**

```powershell
python -m pytest migration_contract_tests/test_legacy_preflight.py -q
```

- [ ] **Step 4: Implement catalog snapshot queries**

Use fixed `sqlalchemy.text()` statements with bound `:schema_name`; never
interpolate the schema into SQL. Read:

- `pg_namespace` for schema existence;
- `pg_class`, `pg_attribute`, `format_type()` for relations/columns;
- `pg_constraint` plus ordered `conkey/confkey` expansion for PK/UNIQUE/FK;
- `has_schema_privilege`, `has_table_privilege`,
  `has_sequence_privilege` for the current runtime role.

All queries are catalog/privilege reads. Do not use `information_schema` fields
that lose ordered constraint-column identity.

- [ ] **Step 5: Implement deterministic comparator**

Comparison order:

1. schema;
2. sorted required relations;
3. sorted columns;
4. PK;
5. UNIQUE;
6. FK;
7. schema/table/sequence privileges.

Return on the first stable mismatch. Safe detail may name schema object and
contract field but not connection coordinates or raw exception.

- [ ] **Step 6: Run focused GREEN**

```powershell
python -m pytest `
  migration_contract_tests/test_legacy_preflight.py `
  migration_contract_tests/test_legacy_contract.py -q
python -m compileall `
  app/workforce/legacy_contract.py `
  app/workforce/legacy_preflight.py
```

- [ ] **Step 7: Review checkpoint**

Inspect AST/SQL governance evidence; confirm there is no execution path for DDL,
DML, repair, `create_all` or missing-object provisioning.

- [ ] **Step 8: Commit permission gate**

Предложение: `feat(runtime): add read-only legacy preflight`.
Остановиться и запросить отдельное разрешение до commit.

---

### Task 5: Add canonical marker preflight from the active Alembic graph

**Files:**

- Create: `09_Разработка/backend/app/shared/runtime_marker.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_runtime_marker.py`

**Interfaces:**

- Consumes: `RuntimeContractError`.
- Produces:
  - `resolve_active_alembic_head(config_path: Path | None = None) -> str`
  - `read_canonical_marker(connection: Connection) -> tuple[str, ...]`
  - `verify_canonical_marker(connection: Connection, expected_head: str)
    -> None`

- [ ] **Step 1: Write RED tests**

Cover:

- exactly one active graph head is returned;
- zero/multiple graph heads fail `CANONICAL-MARKER-MISMATCH`;
- missing `public.alembic_version` fails;
- zero, multiple or nonmatching rows fail;
- exact one matching row succeeds;
- raw SQL/Alembic exceptions are redacted;
- SQL governance rejects DDL/DML.

- [ ] **Step 2: Run and confirm RED**

```powershell
python -m pytest migration_contract_tests/test_runtime_marker.py -q
```

- [ ] **Step 3: Resolve the head dynamically**

```python
def resolve_active_alembic_head(config_path: Path | None = None) -> str:
    resolved_path = (
        Path(__file__).resolve().parents[2] / "alembic.ini"
        if config_path is None
        else config_path
    )
    config = Config(str(resolved_path))
    heads = tuple(
        sorted(ScriptDirectory.from_config(config).get_heads())
    )
    if len(heads) != 1:
        raise RuntimeContractError(
            "CANONICAL-MARKER-MISMATCH",
            "active Alembic graph does not have exactly one head",
        )
    return heads[0]
```

Do not duplicate `canonical_baseline_v1` or a future head in application code.
Default `config_path` вычислять от `runtime_marker.py` до backend
`alembic.ini`, а не из process current directory.

- [ ] **Step 4: Implement two-step read-only marker verification**

First query `to_regclass('public.alembic_version')`; only when present query
ordered `version_num`. Require the exact tuple `(expected_head,)`.

- [ ] **Step 5: Run focused GREEN**

```powershell
python -m pytest `
  migration_contract_tests/test_runtime_marker.py `
  migration_contract_tests/test_alembic_cli_contract.py `
  migration_contract_tests/test_alembic_boundary.py -q
```

These tests inspect graph/code only; do not invoke Alembic CLI.

- [ ] **Step 6: Review checkpoint**

Confirm active head comes from `ScriptDirectory`, SQL is read-only and no
upgrade/stamp/repair path exists.

- [ ] **Step 7: Commit permission gate**

Предложение: `feat(runtime): verify canonical marker at startup`.
Остановиться и запросить отдельное разрешение до commit.

---

### Task 6: Compose FastAPI through a fail-closed application factory

**Files:**

- Create: `09_Разработка/backend/app/shared/application_factory.py`
- Modify: `09_Разработка/backend/app/main.py`
- Test:
  `09_Разработка/backend/migration_contract_tests/test_application_factory.py`

**Interfaces:**

- Consumes:
  - `RuntimeConfiguration`
  - `verify_canonical_marker`
  - `run_legacy_preflight`
  - bind-once legacy schema
- Produces:
  - `CanonicalRouterBinding`
  - `RuntimeDependencies`
  - `create_app(configuration: RuntimeConfiguration, *,
    dependencies: RuntimeDependencies | None = None) -> FastAPI`
  - compatible `app.main.app`.

- [ ] **Step 1: Write RED canonical composition tests**

Use injected fake routers/preflights; never import `app.shared.db` or connect.
In a fresh subprocess assert:

- default canonical `app.main` does not load any `app.workforce.*` module;
- canonical routes are present;
- workforce route paths are absent;
- canonical marker preflight runs before readiness;
- failure prevents lifespan yield;
- OpenAPI is unavailable before successful lifespan and contains canonical
  routes afterward.

- [ ] **Step 2: Write RED legacy composition tests**

Assert ordered events:

```text
canonical_marker
bind_legacy_schema
legacy_contract
load_workforce_router
attach_workforce_router
runtime_ready
```

Assert:

- router is absent before preflight;
- failed legacy preflight never calls loader;
- successful preflight attaches router once;
- a second lifespan reruns read-only preflight but does not duplicate routes;
- `app.openapi_schema` is invalidated after first attachment;
- no partial canonical fallback occurs after explicit legacy failure.

- [ ] **Step 3: Run and confirm RED**

```powershell
python -m pytest migration_contract_tests/test_application_factory.py -q
```

- [ ] **Step 4: Implement lazy canonical router loading**

Keep canonical module paths in one immutable tuple inside
`application_factory.py`; import them inside the default loader, not at module
import. Preserve existing prefixes and order from `app/main.py`.

```python
CANONICAL_ROUTER_SPECS = (
    ("app.hr.api", "router", "/api/v1"),
    ("app.welding.api", "router", "/api/v1"),
    ("app.projects.api", "router", "/api/v1"),
    ("app.engineering.api", "router", "/api/v1"),
    ("app.engineering.heat_treatment_api", "router", "/api/v1"),
    ("app.engineering.import_api", "router", "/api/v1"),
    ("app.quality.api", "router", "/api/v1"),
    ("app.quality.execution_api", "router", "/api/v1"),
    ("app.quality.quality_finding_api", "router", "/api/v1"),
    ("app.quality.quality_decision_api", "router", "/api/v1"),
    ("app.quality.engineering_evaluation_api", "router", "/api/v1"),
    ("app.quality.defect_api", "router", "/api/v1"),
    ("app.quality.defect_disposition_api", "router", "/api/v1"),
)
```

The plan implementer must copy all current canonical routers; no API path,
prefix, tag or order change is allowed.

- [ ] **Step 5: Implement injectable runtime dependencies**

```python
@dataclass(frozen=True)
class CanonicalRouterBinding:
    router: APIRouter
    prefix: str


@dataclass(frozen=True)
class RuntimeDependencies:
    load_canonical_routers: Callable[
        [], tuple[CanonicalRouterBinding, ...]
    ]
    run_canonical_preflight: Callable[[], None]
    bind_legacy_schema: Callable[[str], str]
    run_legacy_preflight: Callable[[str], None]
    load_workforce_router: Callable[[], APIRouter]
```

`create_app()` вызывает `load_canonical_routers()` и регистрирует bindings в
полученном порядке. Default dependencies лениво импортируют canonical router
modules, `app.shared.db.engine`, active head и preflights. Workforce imports
происходят внутри legacy-only default callables, никогда при импорте
`application_factory.py`. Tests supply fakes.

- [ ] **Step 6: Implement lifespan ordering and idempotence**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    deps.run_canonical_preflight()
    if configuration.profile is RuntimeProfile.LEGACY_COMPATIBILITY:
        schema = cast(str, configuration.legacy_schema)
        deps.bind_legacy_schema(schema)
        deps.run_legacy_preflight(schema)
        if not app.state.workforce_router_attached:
            app.include_router(deps.load_workforce_router(), prefix="/api/v1")
            app.state.workforce_router_attached = True
            app.openapi_schema = None
    app.state.runtime_ready = True
    try:
        yield
    finally:
        app.state.runtime_ready = False
```

Do not catch `RuntimeContractError` into a partial app. Raw adapter errors are
converted to safe errors inside preflight boundaries.

- [ ] **Step 7: Guard runtime OpenAPI**

Wrap the original `app.openapi` so it raises safe
`RUNTIME-STARTUP-INCOMPLETE` until `app.state.runtime_ready is True`.
Documentation requests after startup use the normal FastAPI generator.

- [ ] **Step 8: Replace main.py with compatible export**

`app/main.py` must:

1. import `settings`;
2. resolve `RuntimeConfiguration`;
3. call `create_app`;
4. export `app`.

It must contain no workforce import and no router registration list.

- [ ] **Step 9: Run focused GREEN**

```powershell
python -m pytest `
  migration_contract_tests/test_application_factory.py `
  migration_contract_tests/test_runtime_profile.py `
  migration_contract_tests/test_runtime_marker.py `
  migration_contract_tests/test_legacy_preflight.py -q
python -m compileall app/main.py app/shared/application_factory.py
```

- [ ] **Step 10: Review checkpoint**

Inspect import graph in fresh subprocesses. Canonical must not contain any
`app.workforce` module; explicit legacy failure must not expose routes or
OpenAPI.

- [ ] **Step 11: Commit permission gate**

Предложение: `feat(runtime): add fail-closed application composition`.
Остановиться и запросить отдельное разрешение до commit.

---

### Task 7: Remove the temporary import workaround and close pure verification

**Files:**

- Modify: `09_Разработка/backend/tests/conftest.py`
- Modify: `09_Разработка/.env.example`
- Modify: `09_Разработка/backend/.env.example`
- Modify after code acceptance:
  - `docs/ARCHITECTURE.md`
  - `docs/project/DECISIONS.md`
  - `docs/project/TASK_REGISTRY.md`
  - `docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC.md`
- Test: all six new pure test files plus existing migration contracts.

**Interfaces:**

- Consumes all previous tasks.
- Produces accepted pure implementation evidence only; operational status
  remains `IMPLEMENTED_UNVERIFIED`.

- [ ] **Step 1: Remove only the obsolete conftest workaround**

Delete:

```python
import app.shared.canonical_metadata  # noqa: F401
```

and its comment explaining workforce contamination. Keep F1 target
authorization, bind-before-main ordering, ownership gate, Alembic invocation and
all cleanup logic unchanged.

- [ ] **Step 2: Document empty environment inputs**

Add to both `.env.example` files as commented examples. Do not add active empty
assignments: explicit empty runtime profile must fail closed.

```dotenv
# Runtime default is canonical when this variable is absent.
# WELDPASSPORT_RUNTIME_PROFILE=canonical
# Read only when profile is exactly legacy_compatibility; default is test.
# WELDPASSPORT_LEGACY_SCHEMA=test
```

These are documentation comments, not active environment assignments. No DSN,
credential or token value.

- [ ] **Step 3: Run the full focused RUNTIME-COMPAT-1 suite**

```powershell
python -m pytest `
  migration_contract_tests/test_runtime_profile.py `
  migration_contract_tests/test_legacy_metadata_boundary.py `
  migration_contract_tests/test_legacy_contract.py `
  migration_contract_tests/test_legacy_preflight.py `
  migration_contract_tests/test_runtime_marker.py `
  migration_contract_tests/test_application_factory.py -q
```

- [ ] **Step 4: Run complete pure migration contracts**

```powershell
python -m pytest migration_contract_tests -q
```

Do not run `tests/` as a suite. The only permitted file from that directory in
this gate is `tests/conftest.py`, and it is compiled but not executed. Legacy
repository import is checked by the direct `python -c` command from Task 2.

- [ ] **Step 5: Compile every changed Python file**

```powershell
python -m compileall `
  app/main.py `
  app/shared/config.py `
  app/shared/runtime_profile.py `
  app/shared/runtime_marker.py `
  app/shared/application_factory.py `
  app/workforce/legacy_orm.py `
  app/workforce/legacy_contract.py `
  app/workforce/legacy_preflight.py `
  app/workforce/models.py `
  tests/conftest.py
```

- [ ] **Step 6: Verify forbidden activity and diff scope**

```powershell
git diff --check
git status --short
git diff --name-only
```

Confirm:

- no revision/baseline/domain/API/workforce behavior files changed;
- no PostgreSQL connection occurred;
- no Alembic CLI, upgrade, stamp or application suite ran;
- no reset hook, `create_all`, DDL/DML or fallback was added;
- no secret or connection coordinate appears in diff/output;
- canonical metadata remains exactly 73 tables.

- [ ] **Step 7: Independent read-only review**

Reviewer checks spec coverage, import graph, fail-closed behavior, SQL
read-only governance, redaction and metadata isolation. Verdict categories:
`APPROVED`, `WITH FIXES`, `BLOCKED`. Any finding receives a separate TDD
remediation cycle and repeated full pure verification.

- [ ] **Step 8: Update closure documentation only after code acceptance**

Record exact test counts after verification. Record implementation SHA only
after the commit exists. Until then use status:

```text
IMPLEMENTED_UNVERIFIED / CODE ACCEPTED / COMMIT PENDING
```

Do not claim PostgreSQL/application acceptance.

- [ ] **Step 9: Final commit permission gate**

Proposed commit after acceptance:

```text
feat(runtime): add legacy compatibility profile
```

Request explicit stage/commit permission. Push remains a separate decision.

---

## Plan Self-Review Checklist

- [x] Every requirement in Sections 5–13 of
  `TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC.md` maps to Tasks 1–7.
- [x] Canonical default never imports workforce.
- [x] `LegacyBase.metadata` is physically distinct and invisible to Alembic.
- [x] Legacy contract has one structural source and deterministic ordering.
- [x] Preflight SQL is entirely read-only.
- [x] Router attachment occurs only after both marker and legacy preflight.
- [x] Lifespan is idempotent without duplicate routes.
- [x] OpenAPI cannot observe a pre-preflight legacy composition.
- [x] No PostgreSQL, Alembic CLI or application suite is used in the pure gate.
- [x] Operational status remains `IMPLEMENTED_UNVERIFIED` until ADR-033
  rehearsal and owner acceptance.
