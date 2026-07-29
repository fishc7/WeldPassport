# Test DB Safety Interlock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Остановить integration pytest до первого подключения к PostgreSQL, если
разрушительный запуск не подтверждён для явно тестовой БД.

**Architecture:** Pure guard расположен в `tests/test_db_safety.py`; он не создаёт engine
и не импортирует application DB layer. `tests/conftest.py` вызывает guard session fixture
как явную dependency `_apply_migrations`, поэтому Alembic физически не может стартовать
раньше проверки.

**Tech Stack:** Python 3.12, pytest 8, Pydantic Settings, PostgreSQL/Alembic без запуска в
этом gate.

## Global Constraints

- Не запускать application tests, Alembic или подключение к PostgreSQL.
- Не менять models, migrations, API или доменную логику.
- Выполнять TDD: RED должен быть наблюдён до production/test-bootstrap implementation.
- Полный TEST-DB Foundation остаётся после B-04 по ADR-025.

---

### Task 1: Pure safety contract

**Files:**
- Create: `09_Разработка/backend/migration_contract_tests/test_test_db_safety_interlock.py`
- Create later: `09_Разработка/backend/tests/test_db_safety.py`

**Interfaces:**
- Consumes: отсутствует.
- Produces: контракт `assert_safe_test_database(...) -> None`.

- [x] **Step 1: Write failing tests**

Проверить отказ без opt-in, без confirmation, при mismatch, denylist и отсутствии
test-маркера; проверить одну безопасную комбинацию.

- [x] **Step 2: Verify RED**

Run:
`python -m pytest migration_contract_tests/test_test_db_safety_interlock.py -q`

Expected: collection error `ModuleNotFoundError: tests.test_db_safety`.

- [x] **Step 3: Implement minimal pure guard**

Создать `tests/test_db_safety.py` без импорта `app.shared.db`, SQLAlchemy или Alembic.

- [x] **Step 4: Verify GREEN**

Run:
`python -m pytest migration_contract_tests/test_test_db_safety_interlock.py -q`

Expected: all tests pass.

### Task 2: Bootstrap ordering

**Files:**
- Modify: `09_Разработка/backend/tests/conftest.py`
- Test: `09_Разработка/backend/migration_contract_tests/test_test_db_safety_interlock.py`

**Interfaces:**
- Consumes: `assert_safe_test_database(...)`.
- Produces: `_test_database_safety_interlock` session fixture required by
  `_apply_migrations`.

- [x] **Step 1: Add static contract test**

AST-проверка должна доказать, что `_apply_migrations` зависит от interlock, а
`_db_available` и module-level `pytestmark` отсутствуют.

- [x] **Step 2: Verify RED**

Expected: assertions fail against original `conftest.py`.

- [x] **Step 3: Modify conftest minimally**

Удалить import-time connection probe и подключить guard до Alembic.

- [x] **Step 4: Verify GREEN**

Expected: focused pure suite passes without DB access.

### Task 3: Acceptance and closure

**Files:**
- Modify: `docs/project/DECISIONS.md`
- Modify: `docs/project/TASK_REGISTRY.md`
- Modify: `docs/project/PROJECT_STATUS.yaml`

**Interfaces:**
- Consumes: verified implementation evidence.
- Produces: canonical project status for the accepted interlock.

- [x] **Step 1: Run pure migration contract suite**

Run: `python -m pytest migration_contract_tests -q`

Expected: all tests pass without PostgreSQL.

- [x] **Step 2: Run compile and whitespace checks**

Run:
`python -m compileall tests/test_db_safety.py tests/conftest.py`

Run: `git diff --check` in a Git-backed review environment.

- [x] **Step 3: Record exact evidence**

Update registry/status only with actually observed counts and limitations.

- [x] **Step 4: Publish branch**

Create branch `codex/test-db-safety` from `24790bc` and publish the verified files.

- [ ] **Step 5: Open and accept PR**

Open a PR to the current integration branch. Do not merge without a separate
acceptance check.
