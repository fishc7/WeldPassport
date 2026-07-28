# B-04 — Canonical Baseline Adoption

Статус: **ACCEPTED**

Дата проектирования: 2026-07-24
Дата приёмки: 2026-07-24

Архитектурное основание:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 — Migration Governance and Legacy Schema Boundary]];
- [[docs/project/TASK_B-03_MIGRATION_FOUNDATION_SPEC|B-03 — Migration Foundation]];
- [[docs/project/ADR-029-test-db-safety-interlock|ADR-029 — Test DB Safety Interlock]].

## 1. Цель

Заменить историческую цепочку canonical Alembic одним self-contained root
`canonical_baseline_v1`, доказать эквивалентность итоговой PostgreSQL-схемы и
безопасно принять существующую БД без повторного выполнения baseline DDL.

B-04 не меняет доменную логику, API, runtime composition или legacy business rules.

## 2. Source cut и фактический снимок

Кандидат source cut — merge commit
`6c56f99edbd4e7346264ee14658d2076b5fd0775`.

До начала реализации B-04A commit обязан быть получен в локальный object store и
проверен. Предполагаемый снимок не считается доказательством.

Ожидаемые факты, подлежащие повторной фиксации на source cut:

- canonical-схемы: `hr`, `welding`, `project`, `engineering`, `quality`;
- canonical-таблицы: 73;
- model modules: 12;
- historical revisions: 31;
- historical root: `20260702_02_hr_core`;
- historical head: `20260724_27_qd_rbac_sod`;
- обязательные системные seeds:
  - 8 строк `quality.defect_types`;
  - 7 строк `quality.defect_location_types`;
- governed DB-only index:
  `hr.worker_roles.uq_hr_worker_roles_active_scope`.

Любое несовпадение останавливает cut и требует обновления спецификации до реализации.

## 3. Migration freeze

После подтверждения source cut вводится migration freeze:

- freeze объявляет владелец репозитория отдельной записью в `TASK_REGISTRY.md`;
- запрещены создание, изменение, удаление и merge новых migration-файлов;
- запрещены изменения canonical metadata, влияющие на DDL;
- параллельные ветки со schema changes не принимаются;
- freeze действует до формальной приёмки B-04B;
- снятие freeze фиксируется отдельным closure evidence.

Появление новой revision или изменение checksum после cut аннулирует весь evidence
B-04A.

## 4. Декомпозиция

### 4.1. B-04A — Baseline Build & Verification

B-04A:

- создаёт baseline-кандидат вне active Alembic scan;
- создаёт frozen revision manifest;
- создаёт versioned canonical fingerprint contract;
- создаёт seed manifest;
- доказывает эквивалентность historical chain и baseline на одноразовых PostgreSQL-БД;
- не меняет active graph;
- не меняет `migrations/env.py`;
- не переносит и не удаляет version marker;
- не подключается к существующей рабочей БД.

Приёмка B-04A не разрешает B-04B автоматически.

### 4.2. B-04B — Repository Cut & Maintenance Adoption

B-04B:

- перемещает frozen historical revisions в immutable archive без изменения байтов;
- активирует проверенный baseline-кандидат;
- фиксирует единственный active `version_locations`;
- переключает canonical marker на `public.alembic_version`;
- предоставляет fail-closed maintenance adoption tool;
- сначала репетирует adoption на восстановленной копии backup;
- затем выполняет отдельный разрешённый maintenance run;
- формирует immutable adoption report.

## 5. Структура B-04A

```text
09_Разработка/backend/
  migrations/
    versions/
      <31 historical revisions остаются active до B-04B>
    baseline_candidates/
      canonical_baseline_v1.py
    baselines/
      canonical_baseline_v1/
        cut.json
        frozen-revision-manifest.json
        frozen-revision-manifest.sha256
        seed-manifest.json
        expected-fingerprint.json
        expected-fingerprint.sha256
        verification-report.json
    b04/
      manifest.py
      fingerprint.py
      verify_baseline.py
```

B-04A не создаёт копии historical revision-файлов. Это предотвращает дублирование
исполняемого migration-кода. Manifest заранее фиксирует будущий archive path.

Baseline candidate проверяется отдельной B-04A verification-конфигурацией, которая
физически видит только candidate-файл и принимает только disposable DSN. Обычный
`alembic.ini` и active `migrations/versions` при этом не изменяются. Verification-контекст
не является вторым production migration lifecycle и удаляется либо блокируется после
приёмки B-04B.

## 6. Baseline-кандидат

`canonical_baseline_v1.py`:

- `revision = "canonical_baseline_v1"`;
- `down_revision = None`;
- является одним self-contained файлом;
- импортирует только Python standard library, Alembic, SQLAlchemy и PostgreSQL dialect;
- не импортирует `app.*`, `migrations.*` или mutable application constants;
- не использует `Base.metadata.create_all`;
- не выполняет runtime inspection или чтение существующих данных;
- полностью offline-renderable;
- строго создаёт пять canonical-схем;
- создаёт 73 canonical-таблицы в детерминированном порядке;
- создаёт PK, FK, UNIQUE, CHECK, обычные и partial indexes;
- явно создаёт `uq_hr_worker_roles_active_scope`;
- создаёт implicit/owned sequences через утверждённые column definitions;
- вставляет 15 обязательных seed-строк как frozen literals;
- не создаёт workforce, schema `test` или legacy objects;
- не создаёт `public.alembic_version` собственным DDL.

Historical backfill не переносится в baseline. Baseline создаёт сразу конечную структуру
пустой canonical-БД.

Destructive downgrade допускается только для B-04A disposable database и удаляет только
созданные baseline canonical objects в обратном порядке. Production recovery через
baseline downgrade запрещён.

## 7. Frozen revision manifest

Manifest сериализуется как canonical JSON UTF-8:

- ключи объектов сортируются;
- массив revisions сортируется по graph order;
- переносы строк фиксированы;
- digest — SHA-256 raw bytes итогового файла.

Manifest содержит:

- format version;
- полный source commit;
- baseline revision;
- historical root/head/count;
- checksum algorithm;
- для каждой revision:
  - revision ID;
  - `down_revision`;
  - filename;
  - source path;
  - future archive path;
  - byte size;
  - SHA-256 raw repository bytes.

После B-04B checksum каждого архивного файла обязан совпасть с manifest.

## 8. Canonical fingerprint v1

### 8.1. Источник

Authority fingerprint строится из PostgreSQL system catalogs. SQLAlchemy metadata и
нормализованный `pg_dump --schema-only` используются только как дополнительные
cross-checks.

Fingerprint v1 фиксируется для PostgreSQL 16.x. Другой major version является stop
condition и требует новой версии fingerprint contract.

Fingerprint включает:

- schemas;
- tables;
- columns:
  - ordinal;
  - name;
  - `format_type`;
  - nullable;
  - collation;
  - normalized server default;
  - identity/generated attributes;
- PK/UNIQUE:
  - name;
  - ordered columns;
  - deferrability;
  - validation;
  - `NULLS NOT DISTINCT`, если поддерживается;
- FK:
  - source/target schema-qualified columns;
  - match type;
  - update/delete actions;
  - deferrability;
  - validation;
- CHECK:
  - name;
  - normalized expression;
  - validation;
  - `NO INHERIT`;
- indexes:
  - name;
  - access method;
  - ordered keys/expressions;
  - INCLUDE;
  - uniqueness;
  - predicate;
  - validity/readiness;
  - backing constraint;
- sequences:
  - numeric type;
  - start/min/max/increment/cache/cycle;
  - owned-by table/column;
  - identity kind;
- exact governed seeds.

Не включаются:

- OID;
- owner и ACL;
- statistics;
- row counts;
- physical storage location;
- sequence `last_value` и `is_called`;
- audit timestamps seed-строк.

Expressions извлекаются PostgreSQL deparser functions. Нормализатор может удалять только
незначимые пробелы. Regex-переписывание casts, operators или parentheses запрещено.

Любой неподдерживаемый объект внутри canonical boundary — view, trigger, function,
policy, enum/domain или иной class — останавливает процесс до расширения fingerprint
contract.

### 8.2. Platform allowlist

Allowlist внутри пяти canonical-схем по умолчанию пуст.

`public.alembic_version` проверяется отдельным marker contract и не входит в canonical
fingerprint. Owned sequences и `uq_hr_worker_roles_active_scope` входят в ожидаемый
fingerprint, а не скрываются allowlist.

Будущий allowlist может быть только exact typed:

```text
kind + schema + name + parent identity + definition_sha256 + reason
```

Wildcard и правило «игнорировать объект по имени» запрещены.

### 8.3. Seed policy

Для 15 defect seed-строк применяется exact-row policy:

- проверяются стабильные UUID и business fields;
- лишняя, отсутствующая или отличающаяся строка означает drift;
- `created_at` и `updated_at` не входят в digest;
- baseline использует frozen literals, а не `app.quality.defect_seed`.

## 9. B-04A verification

Используются две отдельные одноразовые PostgreSQL-БД:

1. Historical reference DB:
   - разворачивается frozen history до head 27;
   - создаёт reference fingerprint.
2. Baseline candidate DB:
   - разворачивается `canonical_baseline_v1`;
   - создаёт baseline fingerprint.

Обязательное равенство:

```text
historical reference fingerprint
    == baseline candidate fingerprint
    == expected-fingerprint.json
```

Дополнительные проверки baseline DB:

- `upgrade base → canonical_baseline_v1`;
- один current/head;
- `alembic check` без drift;
- destructive `downgrade base`;
- отсутствие canonical objects после downgrade;
- повторный upgrade;
- идентичный fingerprint после повторного upgrade.

B-04A disposable runner:

- требует отдельный DSN;
- требует exact destructive opt-in;
- требует ownership token;
- не читает обычный `.env` как fallback;
- не запускает application pytest;
- не является TEST-DB Foundation.

Невозможность чистого historical replay является stop condition и отдельным finding.
Переход только к metadata-сравнению запрещён.

## 10. Repository cut B-04B

После приёмки B-04A B-04B одним scoped change:

```text
migrations/versions/<31 files>
    → migrations/archive/canonical_baseline_v1/revisions/<31 files>

migrations/baseline_candidates/canonical_baseline_v1.py
    → migrations/versions/canonical_baseline_v1.py
```

Дополнительно:

- `alembic.ini` явно фиксирует active `version_locations`;
- active graph содержит ровно один root/head/revision:
  `canonical_baseline_v1`;
- archive находится вне `versions` и не загружается Alembic;
- `env.py` использует literal `public` как `version_table_schema` online и offline;
- Alembic configure явно задаёт `version_table_pk=True`;
- historical archive checksums повторно сравниваются с manifest;
- новые migrations создаются только поверх `canonical_baseline_v1`.

В archive запрещены redirect/stub-файлы внутри active `versions`.

## 11. B-04B preflight

Preflight не изменяет БД и требует:

1. утверждённое maintenance window;
2. действующий migration freeze;
3. остановленные application writers и migrators;
4. точную DB identity и PostgreSQL 16.x;
5. backup PostgreSQL custom format, созданный `pg_dump --format=custom`, и manifest с
   SHA-256;
6. доказанный `pg_restore` этого backup в отдельную изолированную БД;
7. успешную полную adoption rehearsal на restored copy;
8. доступный source commit и совпадающие manifest digests;
9. `test.alembic_version`:
   - существует;
   - имеет ожидаемую shape;
   - содержит ровно одну строку;
   - значение равно `20260724_27_qd_rbac_sod`;
10. `public.alembic_version` полностью отсутствует;
11. live canonical fingerprint точно равен ожидаемому;
12. 15 governed seeds совпадают точно;
13. неизвестные canonical objects отсутствуют;
14. активные DDL/migration sessions и долгие transactions отсутствуют.

Успешный preflight создаёт immutable `PREPARED` evidence и одноразовый adoption token,
связанный с DB identity, old marker и digest всех утверждённых artifacts.

## 12. Marker transfer transaction

Adoption выполняется одной PostgreSQL transaction:

1. `BEGIN ISOLATION LEVEL SERIALIZABLE`;
2. bounded `lock_timeout` и `statement_timeout`;
3. безопасный `search_path=pg_catalog`;
4. transaction advisory lock B-04;
5. повторная проверка DB identity;
6. canonical tables блокируются в детерминированном порядке режимом `SHARE`;
7. `test.alembic_version` блокируется `ACCESS EXCLUSIVE`;
8. повторно проверяются оба marker state;
9. fingerprint пересчитывается под locks;
10. создаётся `public.alembic_version` со строгой shape:
    `version_num varchar(32) NOT NULL` и named primary key
    `alembic_version_pkc`;
11. вставляется единственная строка `canonical_baseline_v1`;
12. удаляется таблица `test.alembic_version`;
13. schema `test` и legacy business tables не изменяются;
14. внутри transaction повторно проверяются markers и fingerprint;
15. выполняется `COMMIT`.

Отдельный subprocess `alembic stamp` запрещён, потому что он не гарантирует общую
transaction. Допустимы:

- явный schema-qualified DDL/DML contract;
- Alembic `MigrationContext` на той же connection и transaction.

## 13. Postflight и acceptance

После commit на новом соединении:

- `public.alembic_version = canonical_baseline_v1`;
- `test.alembic_version` отсутствует;
- fingerprint совпадает с preflight и expected artifact;
- `alembic heads`, `current`, `history`, `check` успешны;
- read-only smoke подтверждает schemas, tables, constraints, indexes, sequences и seeds.

Adoption report содержит:

- adoption ID;
- DB identity без credentials;
- backup/restore evidence;
- source commit;
- old/new marker;
- manifest, fingerprint, allowlist и seed digests;
- tool/runtime versions;
- transaction и postflight evidence;
- timestamps;
- итоговый status.

Полные reports хранятся во внешнем append-only/WORM-compatible хранилище, выбранном
оператором. В Git фиксируются только безопасный digest, итоговый статус и ссылка без
credentials или персональных данных.

Только после подписания владельцем репозитория неизменяемой записи
`ADOPTION_ACCEPTED` B-04B считается принятой.

## 14. Re-entry и recovery

### 14.1. Сбой до transaction

- БД не изменена;
- attempt закрывается как failed;
- новый запуск требует полного preflight и нового token.

### 14.2. Сбой внутри transaction

- выполняется rollback;
- доказывается сохранность historical marker и отсутствие public marker;
- при неоднозначном состоянии БД восстанавливается из проверенного backup;
- ручной `stamp` или продолжение SQL запрещены.

### 14.3. Commit выполнен, но acceptance не подписан

Состояние классифицируется как `COMMITTED_UNVERIFIED`:

- transfer повторно не выполняется;
- writers остаются остановленными;
- незавершённый report может быть восстановлен по PREPARED evidence;
- если postflight не проходит, восстанавливается backup и предыдущий release/config.

### 14.4. После `ADOPTION_ACCEPTED`

- baseline downgrade не применяется;
- основной путь — отдельная forward remediation;
- backup recovery выполняется только как incident procedure с оценкой потери новых данных.

## 15. Бинарная приёмка

### B-04A

- source commit получен и проверен;
- freeze действует;
- manifest включает точный frozen graph;
- baseline self-contained и offline-safe;
- historical и baseline fingerprints равны;
- exact seeds совпадают;
- clean upgrade/downgrade/re-upgrade успешны;
- disposable safety contract доказан;
- verification report неизменяем и полон.

### B-04B

- archive byte-identical и невидим active Alembic;
- active graph имеет один root/head;
- marker configuration фиксирована на `public`;
- backup успешно восстановлен;
- rehearsal на restored copy успешна;
- production preflight успешен;
- marker transaction атомарна;
- postflight успешен;
- adoption report содержит `ADOPTION_ACCEPTED`;
- recovery owner и backup retention подтверждены.

Любой unchecked criterion блокирует соответствующий блок. Waiver во время maintenance
window запрещён.

## 16. Stop conditions

Работа немедленно останавливается при:

- недоступном или неподтверждённом source commit;
- новой revision после freeze;
- несовпадении checksum;
- более чем одном active root/head;
- загрузке archive active Alembic;
- импорте `app.*` baseline-файлом;
- использовании `create_all`;
- несовпадении fingerprints;
- неизвестном canonical object;
- несовпадении seeds;
- непроверенном restore backup;
- активных writers/migrators;
- неправильном historical marker;
- существующем или неоднозначном public marker;
- невозможности гарантировать одну marker transaction;
- неуспешном `alembic check`;
- невозможности доказать состояние после сбоя.

## 17. Явно вне B-04

- runtime legacy compatibility profile;
- полноценный TEST-DB Foundation;
- application pytest;
- CI application tests;
- доменные модели и API;
- Task 9D-4A-5;
- Identity и RBAC;
- удаление schema `test` или legacy workforce;
- automatic repair существующей БД.

## 18. Последовательность реализации

```text
B-04A-0 source verification + freeze
  → B-04A-1 manifest/fingerprint contracts
  → B-04A-2 baseline candidate
  → B-04A-3 pure verification
  → B-04A-4 disposable PostgreSQL equivalence
  → B-04A acceptance
  → B-04B-1 cut/adoption tooling
  → B-04B-2 restored-backup rehearsal
  → отдельное maintenance approval
  → B-04B-3 repository cut + production adoption
  → B-04B closure
  → снять migration freeze
```

Каждый блок требует отдельного списка файлов, diff, результатов проверок и приёмки.

## 19. Closure evidence B-04A

Дата фиксации: **2026-07-28**.

Статус блока: **B-04A технически завершён и принят свежими проверками; Git commit
отсутствует (`accepted_uncommitted`). B-04B заблокирован до отдельной maintenance
readiness и отдельного решения о старте.**

Наблюдаемое evidence:

- source commit: `6c56f99edbd4e7346264ee14658d2076b5fd0775`;
- frozen graph: root `20260702_02_hr_core`, head
  `20260724_27_qd_rbac_sod`, 31 revision;
- PostgreSQL: `16.14` (`server_version_num=160014`);
- canonical fingerprint SHA-256:
  `ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6`;
- historical, baseline и re-upgrade fingerprints равны указанному digest;
- verified canonical tables: `73`;
- verified exact governed seeds: `15`;
- governed index:
  `hr.worker_roles.uq_hr_worker_roles_active_scope`;
- immutable verification status: `B04A_VERIFIED`;
- artifact acceptance:
  `B04-ARTIFACT-ACCEPTANCE-OK|files=7|digest=ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6|tables=73|seeds=15|indexes=3`;
- disposable PostgreSQL equivalence:
  `B04-EQUIVALENCE-EVIDENCE-OK`;
- pure migration contract suite: `246 passed, 1 skipped`;
- `compileall` и `git diff --check`: exit code `0`.

Evidence опубликовано в
`09_Разработка/backend/migrations/baselines/canonical_baseline_v1/` ровно семью
файлами: `cut.json`, `frozen-revision-manifest.json`,
`frozen-revision-manifest.sha256`, `seed-manifest.json`,
`expected-fingerprint.json`, `expected-fingerprint.sha256`,
`verification-report.json`.

Границы подтверждённого результата:

- baseline-кандидат находится вне активного `migrations/versions`;
- active migration graph и действующая конфигурация version marker не изменены;
- перенос `test.alembic_version → public.alembic_version`, repository cut и
  production adoption не выполнялись;
- рабочая/production БД не подключалась и не изменялась; проверки выполнялись
  только в owned disposable PostgreSQL container;
- runtime compatibility profile и TEST-DB Foundation не входят в B-04A;
- migration freeze остаётся активным до принятого B-04B closure.
