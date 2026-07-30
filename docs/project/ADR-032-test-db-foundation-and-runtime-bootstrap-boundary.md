# ADR-032. TEST-DB Foundation and Runtime Bootstrap Boundary

Дата: 2026-07-30

Статус: **ACCEPTED**

Связанные решения:

- [[docs/project/ADR-005-legacy-workforce-deprecation|ADR-005]];
- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/ADR-029-test-db-safety-interlock|ADR-029]].

## Контекст

B-04 завершён со статусом `ADOPTION_ACCEPTED`, active marker рабочей PostgreSQL
перенесён в `public.alembic_version`, migration freeze снят. Следующий prerequisite
перед Task 9D-4A-5A — совместно спроектированные `TEST-DB Foundation` и
`RUNTIME-LEGACY-COMPATIBILITY-PROFILE`.

Текущее приложение не реализует принятый ADR-025 runtime contract:

- `app.main` безусловно импортирует и подключает deprecated workforce router;
- workforce models регистрируются в общей `Base.metadata`;
- legacy schema определяется общим `POSTGRES_SCHEMA`;
- `app.shared.db` создаёт process-global engine из working `POSTGRES_*` при импорте.

Текущий integration pytest также не имеет целевого test database bootstrap:

- `TEST_DATABASE_URL` отсутствует;
- `tests/conftest.py` импортирует приложение и `SessionLocal` до выбора отдельной
  test database;
- Alembic использует тот же working settings object;
- предварительный ADR-029 проверяет имя БД, opt-in и confirmation, но не отделяет
  test/work DSN и не подтверждает server-side ownership.

Из-за общей import boundary невозможно независимо доказать canonical runtime,
legacy compatibility и безопасный application-test clean install.

## Рассмотренные варианты

### A. Минимальная условная загрузка

Условно импортировать workforce в `main.py`, а в pytest временно подменять
`POSTGRES_*` до импорта приложения.

Вариант отклонён: безопасность продолжает зависеть от порядка импортов и изменяемого
process environment; working и test target не получают явной границы.

### B. Явная bootstrap boundary

До создания engine разрешать два независимых выбора:

- `RuntimeProfile`: `canonical` или `legacy_compatibility`;
- `DatabasePurpose`: `working` или `test`.

После pure validation фиксировать неизменяемый process-level `DatabaseTarget`,
создавать engine ровно один раз и запрещать повторную конфигурацию. Runtime
composition выполнять через application factory и lifespan.

Вариант принят.

### C. Полная dependency injection

Удалить process-global `engine`/`SessionLocal` и передавать database context через
полный DI-container во все модули и тесты.

Вариант отложен: он существенно расширяет scope, затрагивает большое число
проверенных consumers и не требуется для безопасного следующего этапа.

## Решение

### 1. Общая bootstrap boundary

Вводятся два независимых enum-контракта:

```text
RuntimeProfile  = canonical | legacy_compatibility
DatabasePurpose = working   | test
```

`DatabaseTarget` является неизменяемым value object с разобранным URL,
нормализованной identity и purpose. Engine запрещено создавать до успешного
разрешения target. После создания engine target нельзя заменить.

Runtime приложения всегда использует `DatabasePurpose=working`. PostgreSQL
application/integration pytest обязан выбрать `DatabasePurpose=test` до импорта
`app.main` или `app.shared.db`.

### 2. Runtime profiles

`WELDPASSPORT_RUNTIME_PROFILE`:

- отсутствует — `canonical`;
- `canonical` — canonical API без workforce;
- `legacy_compatibility` — canonical API плюс workforce только после успешного
  read-only legacy preflight;
- любое другое или пустое явно заданное значение — startup failure.

Явно выбранный, но невалидный legacy profile блокирует startup целиком. Silent
fallback к canonical и частичный запуск без workforce запрещены.

Canonical startup обязан read-only проверить, что
`public.alembic_version` соответствует текущему единственному canonical head.
Проверка не выполняет stamp, upgrade, repair или иной DDL/DML.

### 3. Legacy metadata boundary

Workforce models переводятся на отдельную `LegacyBase.metadata`. Они не используют
canonical `Base.metadata` и не могут изменить принятый canonical contract из
73 таблиц.

`POSTGRES_SCHEMA` не определяет canonical runtime composition. Legacy schema
задаётся отдельным `WELDPASSPORT_LEGACY_SCHEMA`, читаемым только для
`legacy_compatibility`; default — `test`.

Canonical Alembic никогда не получает `LegacyBase.metadata`.

### 4. Legacy compatibility preflight

Preflight проверяет минимальный исполняемый контракт workforce:

- наличие legacy schema;
- обязательные relations и columns;
- совместимые PostgreSQL-типы и nullable;
- обязательные PK, UNIQUE и FK;
- необходимые schema, table и sequence privileges для реально поддерживаемых
  read/write operations.

Дополнительные безопасные relations, columns и constraints разрешены. Проверка
не требует exact fingerprint всей legacy schema.

Preflight выполняется только read-only catalog/privilege queries. `create_all`,
Alembic, DDL, data repair и автоматическое создание отсутствующих объектов
запрещены. Workforce router импортируется и подключается только после успешной
проверки в FastAPI lifespan до обслуживания запросов.

### 5. TEST-DB Foundation

Для любого PostgreSQL application/integration pytest обязательны:

- `TEST_DATABASE_URL`;
- `WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES`;
- `WELDPASSPORT_TEST_DB_CONFIRM`, точно равный имени test DB;
- `WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN`, точно равный server-side ownership
  marker этой test DB.

Fallback на working `POSTGRES_*`, обычный `.env` или default DSN запрещён.

До первого соединения pure gate проверяет:

- PostgreSQL URL и допустимый driver;
- test-name pattern и production/system denylist;
- exact opt-in и confirmation;
- отличие нормализованных test/work DSN;
- отсутствие credentials в diagnostics.

Working DB для сравнения не подключается.

После первого соединения только с test DB read-only identity gate проверяет:

- `current_database()` и server-reported target;
- точное имя ожидаемой test DB;
- exact server-side ownership marker.

Alembic, session creation и test cleanup разрешаются только после обоих gates.

### 6. Local и CI lifecycle

Локально оператор заранее создаёт disposable PostgreSQL database и ownership
marker. Local pytest не создаёт и не удаляет database, не меняет marker и не
выполняет schema-wide reset. Существующая предметная cleanup-стратегия на первом
этапе сохраняется, поскольку suite содержит реальные commit и concurrency cases.

CI использует отдельный explicit administrative DSN, создаёт уникальную ephemeral
database с run nonce и ownership token, выполняет clean install, а затем в
`finally` удаляет только database, созданную этим job. Перед drop повторно
проверяются exact name и ownership token. Поиск и удаление других БД по маске
запрещены.

Exact CI admin input — `WELDPASSPORT_TEST_DB_ADMIN_URL`. Его concrete
provider/runner binding и transient child-process environment принадлежат
отдельному operational gate `TEST-DB-F2-CI-BINDING`; pure F1 этот DSN не читает
и не подключает.

### 7. Alembic routing

`migrations/env.py` использует уже принятый `DatabaseTarget`:

- `working` — working target для обычного CLI;
- `test` — только `TEST_DATABASE_URL`.

Неявное переключение target, fallback и повторная конфигурация в одном процессе
запрещены. Test bootstrap обязан завершиться до Alembic command.

### 8. Диагностика

Fail-closed errors используют устойчивые коды, включая:

- `RUNTIME-PROFILE-UNKNOWN`;
- `CANONICAL-MARKER-MISMATCH`;
- `LEGACY-SCHEMA-MISSING`;
- `LEGACY-CONTRACT-MISMATCH`;
- `LEGACY-PRIVILEGE-MISSING`;
- `TEST-DB-URL-MISSING`;
- `TEST-DB-TARGET-UNSAFE`;
- `TEST-DB-TARGET-COLLISION`;
- `TEST-DB-OWNERSHIP-MISMATCH`;
- `DATABASE-TARGET-ALREADY-BOUND`.

Diagnostics могут назвать нарушенный объект или поле, но не раскрывают DSN,
password, host, user или ownership token.

## Декомпозиция delivery gates

### Gate 1 — TEST-DB Foundation Core

Pure/TDD implementation resolver, bootstrap, Alembic routing и CI lifecycle
contract. PostgreSQL и Alembic не запускаются.

### Gate 2 — Runtime Compatibility Profile

Pure/TDD implementation runtime composition, isolated legacy metadata и preflight
contract. PostgreSQL не запускается, legacy schema не создаётся.

### Gate 3 — Isolated PostgreSQL Acceptance

Отдельно разрешаемый operational gate на owned disposable PostgreSQL:

1. live identity/ownership verification;
2. clean `upgrade head`, `current`, `heads`, `check`;
3. canonical startup и полный application suite;
4. отдельно provisioned test-only legacy fixture;
5. positive и negative compatibility checks;
6. sanitized acceptance evidence.

До успешного Gate 3 обе реализации имеют статус `IMPLEMENTED_UNVERIFIED`.
Только Gate 3 может присвоить им `ACCEPTED`.

## Acceptance boundaries

Canonical clean-install acceptance подтверждает:

- новую пустую ephemeral database;
- `current == heads` после `upgrade head`;
- успешный `alembic check`;
- успешный canonical startup;
- отсутствие workforce routes;
- отсутствие legacy metadata;
- успешный полный application suite.

Legacy compatibility acceptance выполняется отдельно и подтверждает:

- successful preflight на test-only compatible fixture;
- появление workforce routes только после preflight;
- минимальный read/write smoke;
- невидимость legacy metadata для canonical Alembic;
- startup failure на несовместимом fixture.

## Последствия

Положительные:

- pytest больше не может неявно использовать working DSN;
- runtime profile и database purpose становятся независимыми;
- canonical metadata остаётся стабильной при любом runtime profile;
- CI clean-install получает owned ephemeral database lifecycle;
- legacy support остаётся явным, временным и fail-closed.

Отрицательные:

- startup получает обязательную read-only marker check;
- local application tests требуют заранее provisioned disposable DB и marker;
- conftest/import sequence и Alembic env требуют согласованного изменения;
- до isolated PostgreSQL acceptance обе реализации остаются непроверенными
  операционно.

## Вне scope

- новые Alembic revisions и изменение `canonical_baseline_v1`;
- изменение canonical domain models, services или API;
- развитие deprecated workforce;
- перенос, repair или удаление legacy data;
- массовый перевод suite на transaction rollback;
- подключение к working/production DB в implementation gates 1–2;
- Task 9D-4A-5A и оставшийся Quality-контур;
- commit и push без отдельного подтверждения.
