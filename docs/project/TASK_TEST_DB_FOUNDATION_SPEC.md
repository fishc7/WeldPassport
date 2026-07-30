# TEST-DB-FOUNDATION — Implementation Specification

Статус: **ACCEPTED / IMPLEMENTED_UNVERIFIED / CODE ACCEPTED 2026-07-30**

Архитектурное основание:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/ADR-029-test-db-safety-interlock|ADR-029]];
- [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032]].

## 1. Цель

Ввести отдельный fail-closed PostgreSQL test target, который выбирается до
создания engine, никогда не использует working DSN как fallback и поддерживает:

- заранее созданную owned disposable DB для локального pytest;
- уникальную owned ephemeral DB с create/drop lifecycle только для CI;
- canonical clean-install application acceptance после реализации Runtime
  Compatibility Profile.

## 2. Delivery gates

### TEST-DB-F1 — Pure Foundation Core

Реализовать pure target/safety contracts, process bootstrap, Alembic routing и
CI lifecycle adapters. PostgreSQL, Alembic и application tests не запускать.

Итоговый статус: `IMPLEMENTED_UNVERIFIED`.

### TEST-DB-F2 — Isolated PostgreSQL Acceptance

Отдельно разрешаемый gate после принятой реализации Runtime Compatibility Profile.
Использует только owned disposable PostgreSQL и переводит Foundation в `ACCEPTED`
только после полного evidence contract.

## 3. Разрешённый scope

- `09_Разработка/backend/app/shared/config.py`;
- `09_Разработка/backend/app/shared/db.py`;
- новые узкие модули target/bootstrap/safety в
  `09_Разработка/backend/app/shared/`;
- `09_Разработка/backend/migrations/env.py`;
- `09_Разработка/backend/tests/conftest.py`;
- `09_Разработка/backend/tests/test_db_safety.py`;
- focused pure tests в `migration_contract_tests/`;
- dedicated test infrastructure/CI lifecycle scripts и workflow, если они
  отдельно перечислены в принятом Implementation Plan;
- `.env.example` и относящаяся к задаче документация.

Любой дополнительный production/test file требует scope amendment до изменения.

## 4. Запрещённый scope

- canonical models, services, repositories и API;
- новые или изменённые Alembic revision files;
- изменение `canonical_baseline_v1`, active head или marker;
- legacy schema provisioning в runtime;
- использование working/production DB;
- fallback на `POSTGRES_*` при `DatabasePurpose=test`;
- автоматическое local create/drop database;
- schema-wide reset или расширение текущей cleanup-логики без отдельного решения;
- unrelated test repair;
- commit и push без отдельного подтверждения.

## 5. Pure target contract

Целевая модель:

```python
class DatabasePurpose(StrEnum):
    WORKING = "working"
    TEST = "test"


@dataclass(frozen=True)
class DatabaseTarget:
    purpose: DatabasePurpose
    url: URL
    normalized_identity: DatabaseIdentity
    database_name: str
```

Имена могут быть уточнены Implementation Plan, но семантика обязательна:

- value object immutable;
- URL разбирается штатным SQLAlchemy URL parser;
- `repr`/exception не раскрывают credentials;
- target фиксируется до engine;
- повторная bind/reconfigure после engine запрещена.

## 6. Test environment contract

Обязательные переменные:

```text
TEST_DATABASE_URL
WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES
WELDPASSPORT_TEST_DB_CONFIRM=<exact database name>
WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN=<exact marker token>
```

Для CI дополнительно обязателен отдельный
`WELDPASSPORT_TEST_DB_ADMIN_URL`. Его transient-передача фиксируется в
Implementation Plan; fallback на application `.env` запрещён. Конкретное
подключение provider-neutral lifecycle к admin DSN и child-process test
environment принадлежит отдельному operational gate
`TEST-DB-F2-CI-BINDING`, а не pure F1.

Secrets и полные DSN запрещено писать в repository, pytest output, reports и
exceptions.

## 7. Offline safety gate

До первого соединения Foundation обязан:

1. потребовать `TEST_DATABASE_URL`;
2. разрешить только PostgreSQL и принятый driver;
3. извлечь exact database name;
4. применить test-name pattern;
5. применить denylist как минимум к `postgres`, `template0`, `template1`,
   `weldpassport`;
6. проверить exact destructive opt-in;
7. проверить exact confirmation;
8. нормализовать test/work identity;
9. доказать, что test/work identities различаются;
10. сформировать redacted diagnostics.

Рабочая БД на этом этапе не подключается.

## 8. Live identity and ownership gate

Первое и единственное разрешённое pre-acceptance соединение направляется к уже
прошедшему offline gate test target. До Alembic/session/cleanup выполняются
read-only проверки:

- `current_database()` равно expected database name;
- server-reported endpoint/target согласован с parsed test target;
- server-side ownership marker существует;
- marker точно равен `WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN`.

Marker format и read-only query фиксируются в Implementation Plan. Token не
публикуется в diagnostics.

## 9. Import/bootstrap contract

`tests/conftest.py` обязан:

1. импортировать только pure safety/bootstrap code;
2. разрешить и bind test target;
3. только затем импортировать `app.main`, `app.shared.db`, `SessionLocal` и
   canonical models;
4. выполнить live identity/ownership gate;
5. только затем вызвать Alembic.

Collection/import тестового модуля не может создать working engine раньше этого
bootstrap. Попытка повторного bind завершается
`DATABASE-TARGET-ALREADY-BOUND`.

## 10. Alembic contract

`migrations/env.py` использует уже выбранный target:

- ordinary CLI process — working target;
- test process — только `TEST_DATABASE_URL`.

Запрещены:

- чтение working URL как test fallback;
- смена purpose внутри Alembic run;
- создание test DB из migration env;
- изменение revision graph.

## 11. Local lifecycle

Local pytest:

- требует заранее созданную disposable DB и marker;
- не требует `CREATEDB`;
- не создаёт, не удаляет и не переименовывает database;
- не создаёт и не изменяет marker;
- сохраняет текущую scoped row cleanup на первом этапе.

Provisioning local DB является отдельной operator action и не выполняется
Foundation автоматически.

## 12. CI lifecycle

CI job:

1. получает explicit administrative DSN;
2. генерирует unique database name с run nonce;
3. создаёт только эту database;
4. записывает unique ownership marker;
5. формирует transient test URL;
6. запускает acceptance;
7. в `finally` повторно проверяет exact name и marker;
8. удаляет только owned database.

Drop запрещён при любой неоднозначности. Запрещены discovery и cleanup по wildcard,
prefix scan или списку «старых» test DB.

## 13. TDD и verification

TEST-DB-F1 начинается с pure RED tests как минимум для:

- missing/invalid URL;
- unsupported driver;
- unsafe/test-name cases;
- denylist;
- missing/wrong opt-in;
- missing/wrong confirmation;
- normalized test/work collision;
- redaction;
- bind once;
- no pre-bootstrap engine creation;
- Alembic working/test routing;
- CI create/drop ownership mismatch;
- cleanup refusal for a foreign target.

После GREEN выполняются:

- focused pure suite;
- полный `migration_contract_tests`;
- import/compile checks;
- `git diff --check`.

PostgreSQL, Alembic CLI и application tests в TEST-DB-F1 запрещены.

## 14. Isolated PostgreSQL acceptance

TEST-DB-F2 требует отдельной operator authorization и:

- exact environment preflight без публикации secrets;
- live identity/ownership success;
- empty owned database;
- `alembic upgrade head`;
- exact `current == heads`;
- successful `alembic check`;
- canonical application startup;
- отсутствие workforce routes и legacy metadata;
- полный application suite;
- отдельный legacy compatibility sub-gate из профильной Specification;
- sanitized append-only evidence.

Любой failure оставляет статус `IMPLEMENTED_UNVERIFIED`.

## 15. Acceptance criteria

- test process не может использовать working DSN;
- unsafe target блокируется до первого connection;
- Alembic не запускается до live ownership verification;
- local lifecycle не создаёт и не удаляет DB;
- CI удаляет только exact owned DB;
- diagnostics не раскрывают secrets или connection coordinates;
- canonical clean-install и application suite подтверждены только в TEST-DB-F2;
- Runtime Compatibility Profile принят до application-test closure;
- нет изменений domain/API/revision graph.
