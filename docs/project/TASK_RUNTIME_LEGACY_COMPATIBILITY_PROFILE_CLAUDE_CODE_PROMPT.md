# RUNTIME-COMPAT-1 — Prompt for Cursor / Claude Code

## Роль

Ты работаешь в репозитории `D:\WeldPassport`, в worktree
`D:\WeldPassport\.worktrees\b04b-maintenance-readiness`, ветка
`codex/b04b-maintenance-readiness-review`.

Рабочий каталог для Python-команд:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness\09_Разработка\backend
```

Перед любым изменением прочитай полностью:

1. `docs/00_PROJECT_CONTEXT.md`;
2. `docs/ARCHITECTURE.md`;
3. `docs/project/DECISIONS.md`;
4. `docs/project/TASK_REGISTRY.md`;
5. `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md`;
6. `docs/project/ADR-029-test-db-safety-interlock.md`;
7. `docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary.md`;
8. `docs/project/ADR-033-test-db-f2-local-rehearsal.md`;
9. `docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC.md`;
10. `docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_IMPLEMENTATION_PLAN.md`.

Implementation Plan является обязательным и выполняется task-by-task с TDD и
review checkpoint после каждого task.

## Цель

Реализовать только `RUNTIME-COMPAT-1`:

- фактический default profile `canonical`;
- отсутствие workforce imports/routes/metadata в canonical process;
- explicit fail-closed `legacy_compatibility`;
- отдельный bind-once `LegacyBase.metadata`;
- deterministic executable legacy contract;
- read-only canonical marker и legacy catalog/privilege preflights;
- application factory и lifespan composition;
- pure verification без PostgreSQL.

Итоговый статус этого gate:

```text
IMPLEMENTED_UNVERIFIED
```

Не присваивай `ACCEPTED`: это возможно только после отдельного
`TEST-DB-F2-LOCAL-REHEARSAL` и owner-signed evidence.

## Разрешённые изменения

Production:

- `09_Разработка/backend/app/main.py`;
- `09_Разработка/backend/app/shared/config.py`;
- новые:
  - `app/shared/runtime_profile.py`;
  - `app/shared/runtime_marker.py`;
  - `app/shared/application_factory.py`;
- `09_Разработка/backend/app/workforce/models.py` только для замены
  canonical `Base/SCHEMA` на isolated legacy registry/schema;
- новые:
  - `app/workforce/legacy_orm.py`;
  - `app/workforce/legacy_contract.py`;
  - `app/workforce/legacy_preflight.py`.

Tests:

- новые focused pure tests в `migration_contract_tests/`, перечисленные в
  Implementation Plan;
- точечное усиление `test_canonical_metadata.py` и
  `test_alembic_boundary.py`;
- `tests/conftest.py` только для удаления ставшего ненужным import-order
  workaround;
- direct `python -c` import-only проверка legacy repository без загрузки
  `tests/conftest.py`.

Configuration/docs:

- `09_Разработка/.env.example`;
- `09_Разработка/backend/.env.example`;
- closure docs только после отдельной приёмки реализации.

Любой другой production/test file требует остановки и отдельного scope
amendment до изменения.

## Запрещено

- подключаться к PostgreSQL;
- запускать application test suite;
- запускать Alembic CLI, `upgrade`, `stamp`, `downgrade`, migration или check
  против DB;
- создавать/изменять/удалять schema, table, constraint, sequence, marker или
  данные;
- использовать `create_all`, DDL, DML, auto-repair или fallback;
- менять Alembic revisions, graph, active head или
  `canonical_baseline_v1`;
- менять canonical domain models, services, repositories или API;
- менять поведение workforce endpoints, schemas, repositories или services;
- добавлять workforce features;
- ослаблять F1 `DatabaseTarget`, ownership gate или bind-once semantics;
- добавлять reset/reconfigure hooks;
- читать `WELDPASSPORT_LEGACY_SCHEMA` в canonical profile;
- импортировать workforce из canonical process;
- включать `LegacyBase.metadata` в canonical Alembic;
- раскрывать DSN, host, port, user, password, database name или ownership
  token в logs/errors/tests/docs;
- stage, commit или push без отдельного разрешения владельца.

## Обязательные архитектурные контракты

### Runtime profile

```text
WELDPASSPORT_RUNTIME_PROFILE absent -> canonical
WELDPASSPORT_RUNTIME_PROFILE=canonical -> canonical
WELDPASSPORT_RUNTIME_PROFILE=legacy_compatibility -> legacy
explicit empty/unknown -> RUNTIME-PROFILE-UNKNOWN
```

`WELDPASSPORT_LEGACY_SCHEMA`:

- игнорируется canonical profile;
- default `test` только для legacy profile;
- invalid identifier → `LEGACY-CONTRACT-MISMATCH`.

### Metadata

- canonical `Base.metadata`: ровно 73 таблицы;
- canonical schemas:
  `hr`, `welding`, `project`, `engineering`, `quality`;
- `LegacyBase.metadata is not Base.metadata`;
- explicit workforce import не меняет canonical metadata;
- legacy schema bind-once; reset запрещён.

### Legacy executable contract

- structural source — только `LegacyBase.metadata`;
- deterministic sorted relations/columns/types/nullability/PK/UNIQUE/FK;
- explicit writable policy — только `РАБОТНИКИ` и `СВАРЩИКИ`;
- дополнительные безопасные DB objects разрешены;
- полный fingerprint legacy schema не создаётся.

### Preflight

Canonical startup:

- active head определяется через Alembic `ScriptDirectory`;
- `public.alembic_version` существует;
- содержит ровно один exact current head;
- SQL только read-only;
- failure → `CANONICAL-MARKER-MISMATCH`.

Legacy startup order:

```text
canonical marker
→ resolve/bind legacy schema
→ load isolated legacy contract
→ read-only catalog/privilege preflight
→ import workforce router
→ attach router
→ runtime ready
```

Failures:

- missing schema → `LEGACY-SCHEMA-MISSING`;
- contract mismatch → `LEGACY-CONTRACT-MISMATCH`;
- privilege mismatch → `LEGACY-PRIVILEGE-MISSING`;
- никаких partial startup или fallback.

### Application factory

- сохранить compatible export `from app.main import app`;
- canonical routers лениво загружаются в прежнем составе, порядке и prefixes;
- workforce router загружается только после successful legacy preflight;
- повторный lifespan не дублирует routes;
- OpenAPI до успешного runtime preflight завершается safe code
  `RUNTIME-STARTUP-INCOMPLETE`;
- после legacy router attachment OpenAPI cache сбрасывается.

## TDD-порядок

Для каждого Task из Implementation Plan:

1. написать точный RED test;
2. запустить focused test и зафиксировать ожидаемый failure;
3. написать минимальную реализацию;
4. повторить focused test до GREEN;
5. выполнить self-review diff;
6. остановиться на review checkpoint;
7. не выполнять commit без отдельного разрешения.

Не писать production code до соответствующего RED.

## Обязательная итоговая проверка

Focused:

```powershell
python -m pytest `
  migration_contract_tests/test_runtime_profile.py `
  migration_contract_tests/test_legacy_metadata_boundary.py `
  migration_contract_tests/test_legacy_contract.py `
  migration_contract_tests/test_legacy_preflight.py `
  migration_contract_tests/test_runtime_marker.py `
  migration_contract_tests/test_application_factory.py -q
```

Полный pure suite:

```powershell
python -m pytest migration_contract_tests -q
```

Import-only compatibility без pytest application bootstrap:

```powershell
python -c "from app.workforce.repository import SvarshchikRepo; assert SvarshchikRepo.__name__ == 'SvarshchikRepo'"
```

Compile:

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

Diff:

```powershell
git diff --check
git status --short
git diff --name-only
```

PostgreSQL, Alembic CLI и application suite не запускать.

## Требуемый отчёт

Предоставь:

1. краткий результат и статус `IMPLEMENTED_UNVERIFIED`;
2. список изменённых файлов;
3. diff/stat и ключевые фрагменты;
4. RED → GREEN evidence по каждому Task;
5. focused и full pure test counts;
6. compile и `git diff --check`;
7. подтверждение, что PostgreSQL, Alembic CLI и application suite не
   запускались;
8. подтверждение отсутствия revisions/domain/API/workforce behavior changes;
9. найденные ограничения и риски;
10. proposed commit message без выполнения stage/commit/push.

Если requirement конфликтует с фактической архитектурой или требуется файл вне
разрешённого scope, остановись до изменения и сформулируй точный архитектурный
конфликт.
