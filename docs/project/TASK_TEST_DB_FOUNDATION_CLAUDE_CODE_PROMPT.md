# TEST-DB Foundation Core — Cursor / Claude Code Prompt

Статус: **EXECUTED / IMPLEMENTED_UNVERIFIED / CODE ACCEPTED 2026-07-30**

Работай только в:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness
```

Ветка:

```text
codex/b04b-maintenance-readiness-review
```

Planning base HEAD:

```text
7299824542bc705483d0be6e3a28575565e24484
```

В worktree уже находятся принятые, но не закоммиченные архитектурные документы.
Они принадлежат владельцу: не перезаписывай, не удаляй и не stage их.

## Цель

Реализовать только `TEST-DB-F1 Pure Foundation Core`:

- immutable PostgreSQL `DatabaseTarget`;
- offline fail-closed test authorization;
- bind-once bootstrap до engine;
- test target routing для `app.shared.db` и Alembic;
- read-only live identity/ownership verifier через тестируемый adapter;
- provider-neutral CI ephemeral database lifecycle contract.

Итог gate — только `IMPLEMENTED_UNVERIFIED`. Реальная PostgreSQL acceptance
выполняется отдельно.

## Обязательные источники

Перед изменениями прочитай полностью:

```text
docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary.md
docs/project/TASK_TEST_DB_FOUNDATION_SPEC.md
docs/project/TASK_TEST_DB_FOUNDATION_IMPLEMENTATION_PLAN.md
docs/project/ADR-029-test-db-safety-interlock.md
09_Разработка/backend/app/shared/config.py
09_Разработка/backend/app/shared/db.py
09_Разработка/backend/migrations/env.py
09_Разработка/backend/tests/conftest.py
09_Разработка/backend/tests/test_db_safety.py
```

Specification и Implementation Plan обязательны. Выполняй Plan task-by-task с
TDD и review checkpoint после каждой Task.

## Разрешено создавать

```text
09_Разработка/backend/app/shared/database_target.py
09_Разработка/backend/app/shared/database_bootstrap.py
09_Разработка/backend/app/shared/test_database_ownership.py
09_Разработка/backend/test_support/__init__.py
09_Разработка/backend/test_support/ci_database_lifecycle.py
09_Разработка/backend/migration_contract_tests/test_database_target.py
09_Разработка/backend/migration_contract_tests/test_database_bootstrap.py
09_Разработка/backend/migration_contract_tests/test_test_database_ownership.py
09_Разработка/backend/migration_contract_tests/test_alembic_target_routing.py
09_Разработка/backend/migration_contract_tests/test_ci_database_lifecycle.py
```

## Разрешено менять

```text
09_Разработка/backend/app/shared/db.py
09_Разработка/backend/migrations/env.py
09_Разработка/backend/tests/conftest.py
09_Разработка/backend/tests/test_db_safety.py
09_Разработка/backend/migration_contract_tests/test_test_db_safety_interlock.py
09_Разработка/backend/.env.example
09_Разработка/.env.example
```

Любой дополнительный implementation file требует scope amendment до изменения.

## Запрещено

- подключаться к любой PostgreSQL;
- запускать Alembic CLI или application `tests/`;
- создавать, очищать, мигрировать или удалять database/schema;
- читать обычный `.env` как fallback для test target;
- печатать или сохранять DSN, password, host, user или ownership token;
- менять `app/main.py`, runtime profile или workforce;
- менять canonical models, services, repositories или API;
- менять revision files, active graph, baseline или evidence;
- менять текущий search path и семантику `POSTGRES_SCHEMA`;
- добавлять GitHub Actions или другой provider-specific CI workflow;
- исправлять unrelated issues;
- stage, commit или push.

## Обязательный порядок

1. Проверь `git rev-parse HEAD` и `git status --short`.
2. Сохрани принятые documentation changes.
3. Для каждой Task сначала добавь focused failing tests.
4. Запусти focused RED и зафиксируй фактическую причину.
5. Реализуй минимальный контракт только этой Task.
6. Запусти focused GREEN.
7. Покажи diff/checkpoint до следующей Task.
8. После Tasks 1–5 выполни Task 6 pure acceptance.

Python:

```powershell
$PythonExe = "C:\Users\Andrey\AppData\Local\Programs\Python\Python314\python.exe"
```

Все pytest-команды запускай из:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness\09_Разработка\backend
```

## Обязательные контракты

### Offline target

- driver ровно `postgresql+psycopg`;
- default port `5432`;
- identity не содержит credentials;
- test-name pattern:
  `^(?:test_.+|.+_test|.+_test_.+)$`;
- denylist минимум:
  `postgres`, `template0`, `template1`, `weldpassport`;
- exact opt-in `YES`;
- exact confirmation;
- непустой ownership token;
- test/work normalized identities различаются;
- одинаковое имя working/test DB запрещено даже при разных host strings.

### Bind once

- target выбирается до engine;
- повторный bind запрещён;
- reset API отсутствует;
- ordinary app import выбирает working target;
- pytest bootstrap выбирает test target до `app.main`/`app.shared.db`.

### Live ownership

Используй только read-only query:

```sql
SELECT
    current_database() AS database_name,
    inet_server_addr()::text AS server_address,
    inet_server_port() AS server_port,
    shobj_description(d.oid, 'pg_database') AS database_comment
FROM pg_catalog.pg_database AS d
WHERE d.datname = current_database()
```

Marker:

```text
weldpassport-test-db:<exact ownership token>
```

Проверка обязана завершиться до `command.upgrade`.

### CI lifecycle

- future admin input is exactly
  `WELDPASSPORT_TEST_DB_ADMIN_URL`;
- exact generated name `wp_test_<run_id>_<nonce>`;
- максимум 63 bytes;
- create exact target, publish/read-back marker;
- cleanup только после повторного exact marker match;
- никакого list/prefix/wildcard cleanup;
- никакого provider-specific workflow в F1.

F1 не читает admin DSN и не формирует child environment. Это делает отдельный
`TEST-DB-F2-CI-BINDING`: он заменяет в parsed admin URL только database на
`lease.database_name` и передаёт дочернему процессу exact
`TEST_DATABASE_URL`, `WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES`,
`WELDPASSPORT_TEST_DB_CONFIRM` и `WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN`
только transient, без `.env`, logs или reports.

## Обязательные pure проверки

Focused:

```powershell
& $PythonExe -m pytest `
  migration_contract_tests/test_database_target.py `
  migration_contract_tests/test_database_bootstrap.py `
  migration_contract_tests/test_test_database_ownership.py `
  migration_contract_tests/test_alembic_target_routing.py `
  migration_contract_tests/test_ci_database_lifecycle.py -q
```

Полный pure suite:

```powershell
& $PythonExe -m pytest migration_contract_tests -q
```

Compile:

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

Diff:

```powershell
git diff --check
git status --short
git diff --name-only
```

## Итоговый отчёт

Предоставь:

1. список изменённых файлов;
2. RED evidence для каждой Task;
3. focused и полный pure test counts;
4. compile и `git diff --check`;
5. подтверждение отсутствия PostgreSQL/Alembic/application-test activity;
6. подтверждение отсутствия secrets;
7. итоговый статус `IMPLEMENTED_UNVERIFIED`;
8. diff для приёмки владельцем.

Не stage, не commit и не push.
