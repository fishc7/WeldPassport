# RUNTIME-LEGACY-COMPATIBILITY-PROFILE — Implementation Specification

Статус: **ACCEPTED / IMPLEMENTATION NOT STARTED**

Архитектурное основание:

- [[docs/project/ADR-005-legacy-workforce-deprecation|ADR-005]];
- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032]].

## 1. Цель

Сделать canonical runtime profile фактическим default, полностью исключить
workforce router и legacy metadata из canonical startup и предоставить явный
fail-closed `legacy_compatibility` profile с read-only preflight.

Задача не развивает workforce и не возвращает его в canonical architecture.

## 2. Delivery gates

### RUNTIME-COMPAT-1 — Pure implementation

Реализовать profile parsing, application composition, isolated legacy metadata и
preflight contracts с pure/TDD verification. PostgreSQL не запускать.

Итоговый статус: `IMPLEMENTED_UNVERIFIED`.

### RUNTIME-COMPAT-2 — Isolated PostgreSQL acceptance

Выполняется как отдельный sub-gate TEST-DB-F2 только на owned disposable test DB.
Лишь его успешное завершение переводит profile в `ACCEPTED`.

## 3. Разрешённый scope

- `09_Разработка/backend/app/main.py`;
- `09_Разработка/backend/app/shared/config.py`;
- `09_Разработка/backend/app/shared/db.py` только в части согласованной bootstrap
  boundary;
- новые узкие runtime profile/composition modules в `app/shared/`;
- `09_Разработка/backend/app/workforce/models.py`;
- новые `LegacyBase`, compatibility contract и preflight modules в
  `app/workforce/`;
- focused pure tests в `migration_contract_tests/` и/или отдельной pure test
  группе;
- profile-specific integration tests, исполняемые только в
  RUNTIME-COMPAT-2;
- `.env.example` и относящаяся документация.

Любой дополнительный production file требует scope amendment.

## 4. Запрещённый scope

- изменение поведения workforce endpoints, schemas, repositories и services,
  кроме технически необходимой смены metadata/schema dependency;
- новые workforce features;
- canonical domain models, services или API;
- Alembic revision files, baseline, head или marker transfer;
- включение legacy metadata в canonical Alembic;
- `create_all`, DDL, auto-repair или data migration;
- создание/изменение legacy schema в runtime;
- fallback profile;
- работа с working/production DB в pure gate;
- commit и push без отдельного подтверждения.

## 5. Runtime profile contract

```python
class RuntimeProfile(StrEnum):
    CANONICAL = "canonical"
    LEGACY_COMPATIBILITY = "legacy_compatibility"
```

`WELDPASSPORT_RUNTIME_PROFILE`:

- отсутствует — `canonical`;
- exact accepted value — соответствующий profile;
- пустое явно заданное или неизвестное значение — `RUNTIME-PROFILE-UNKNOWN`.

`WELDPASSPORT_LEGACY_SCHEMA`:

- читается только для `legacy_compatibility`;
- default — `test`;
- обязан быть валидным PostgreSQL identifier;
- не влияет на canonical search path или canonical metadata.

## 6. Canonical composition

Canonical profile:

- не импортирует `app.workforce.api`;
- не импортирует workforce models;
- не регистрирует workforce routes;
- не создаёт `LegacyBase.metadata`;
- не требует существования schema `test`;
- сохраняет canonical metadata exact boundary из 73 таблиц;
- перед обслуживанием requests read-only проверяет canonical marker.

## 7. Canonical marker preflight

Startup обязан проверить:

- существует `public.alembic_version`;
- содержит ровно ожидаемый current canonical head;
- head определяется из active Alembic graph, а не дублируется вручную;
- нет ambiguity/multiple current markers.

Проверка read-only. Upgrade, stamp, repair и fallback запрещены.
Несовпадение даёт `CANONICAL-MARKER-MISMATCH`.

## 8. Legacy metadata isolation

Workforce models обязаны использовать отдельную declarative base:

```text
LegacyBase.metadata != canonical Base.metadata
```

Все legacy table/FK schema references используют resolved legacy schema, а не
общий canonical `SCHEMA`.

Canonical metadata validation остаётся неизменной и не зависит от выбранного
runtime profile. `migrations/env.py` получает только canonical metadata.

## 9. Legacy executable contract

Compatibility contract описывает только объекты, необходимые текущим workforce
read/write paths:

- relations;
- columns;
- normalized PostgreSQL types;
- nullable;
- PK;
- используемые UNIQUE и FK;
- schema/table/sequence privileges.

Contract должен быть deterministic и тестируемым без PostgreSQL. Дополнительные
объекты разрешены. Exact fingerprint всей legacy schema не требуется.

Implementation Plan обязан определить один источник expected contract и исключить
неконтролируемое расхождение между ним и `LegacyBase.metadata`.

## 10. Legacy preflight

Для `legacy_compatibility` startup sequence:

1. canonical marker preflight;
2. resolve/validate legacy schema name;
3. load isolated legacy contract/metadata;
4. выполнить read-only catalog/privilege checks;
5. только после success импортировать и подключить workforce router;
6. начать обслуживание requests.

Проверяются:

- schema existence;
- required relations/columns;
- type/nullability compatibility;
- required PK/UNIQUE/FK;
- `USAGE`, `SELECT`, `INSERT`, `UPDATE` и необходимые sequence privileges.

При failure приложение не стартует. Silent canonical fallback и запуск без
workforce запрещены.

## 11. Application factory and lifespan

Composition реализуется через application factory с сохранением совместимого
ASGI export `app`.

Preflight выполняется в lifespan до обслуживания requests. Подключение legacy
router должно быть:

- только после successful preflight;
- idempotent для одного app instance;
- без duplicate routes при повторном lifespan в тестах;
- завершено до генерации/использования runtime OpenAPI schema.

Точная механика фиксируется Implementation Plan и проверяется pure tests.

## 12. Diagnostics

Обязательные stable codes:

- `RUNTIME-PROFILE-UNKNOWN`;
- `CANONICAL-MARKER-MISMATCH`;
- `LEGACY-SCHEMA-MISSING`;
- `LEGACY-CONTRACT-MISMATCH`;
- `LEGACY-PRIVILEGE-MISSING`.

Diagnostics:

- называют profile и несовместимый object/contract field;
- не раскрывают DSN, host, user, password или ownership token;
- не содержат raw database exception text, если оно может раскрыть coordinates.

## 13. TDD и pure verification

RUNTIME-COMPAT-1 начинается с RED tests как минимум для:

- default canonical profile;
- explicit canonical profile;
- empty/unknown profile rejection;
- canonical composition без workforce import/routes;
- absence of legacy metadata in canonical process;
- distinct `LegacyBase.metadata`;
- invalid legacy schema identifier;
- deterministic compatible contract comparison;
- missing table/column/constraint/privilege cases;
- permitted extra objects;
- fail-closed startup result;
- router attachment only after success;
- idempotent lifespan composition;
- redacted diagnostics.

После GREEN выполняются:

- focused pure suite;
- полный `migration_contract_tests`;
- import/compile checks;
- canonical metadata exact contract;
- `git diff --check`.

PostgreSQL и Alembic в RUNTIME-COMPAT-1 запрещены.

## 14. Isolated PostgreSQL acceptance

RUNTIME-COMPAT-2 выполняется только после TEST-DB-F1 и отдельного разрешения:

### Canonical sub-gate

- owned disposable DB на canonical head;
- canonical startup successful;
- workforce routes отсутствуют;
- legacy schema не требуется;
- canonical metadata остаётся exact.

### Compatible legacy sub-gate

- test-only fixture создаёт compatible legacy schema вне runtime;
- preflight successful;
- workforce routes появляются;
- минимальный read/write smoke successful;
- canonical Alembic не видит legacy metadata.

### Negative legacy sub-gate

- test-only fixture содержит controlled contract incompatibility;
- startup завершается ожидаемым stable code;
- workforce routes не подключаются;
- repair/DDL/DML отсутствуют.

## 15. Acceptance criteria

- canonical является реальным default;
- canonical import/startup не загружает workforce;
- unknown profile и invalid legacy contract fail closed;
- explicit legacy profile не может частично стартовать;
- canonical и legacy metadata физически разделены;
- canonical Alembic boundary не изменена;
- preflight полностью read-only;
- isolated positive/negative evidence принято;
- нет новых revisions, domain/API changes или legacy features.
