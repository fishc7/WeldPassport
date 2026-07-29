# ADR-030. PostgreSQL 18 Target and B-04 Evidence Versioning

Дата: 2026-07-28

Статус: **ACCEPTED**

Уточнено:
[[docs/project/ADR-031-b04-dual-state-live-restore-evidence|ADR-031]] разделяет
live migration-built и restore-roundtrip authorizing evidence без изменения
принятого fingerprint v2.

Связано:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC|B-04 Canonical Baseline Adoption]];
- [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

## Контекст

Канонический `docs/ARCHITECTURE.md` фиксирует PostgreSQL 18 как целевую СУБД проекта.
При этом B-04A был реализован и принят на PostgreSQL 16.14:

- source commit `6c56f99edbd4e7346264ee14658d2076b5fd0775`;
- 31 frozen historical revision;
- 73 canonical tables;
- 15 governed seeds;
- fingerprint v1
  `ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6`;
- immutable status `B04A_VERIFIED`.

Fingerprint v1 намеренно привязан к PostgreSQL major 16. B-04 tooling отклоняет другой
major version. Следовательно, принятое PG16 evidence остаётся корректным историческим
доказательством, но не может разрешать adoption рабочей PostgreSQL 18.

READ-ONLY Maintenance Readiness Review от 2026-07-28 подтвердил:

- рабочая БД имеет PostgreSQL 18.3;
- рабочая БД содержит данные и не является одноразовой;
- historical marker остаётся
  `test.alembic_version = 20260724_27_qd_rbac_sod`;
- `public.alembic_version` отсутствует;
- новых revision после migration freeze нет;
- B-04B не готов к запуску без отдельного PG18 verification evidence.

Понижение рабочей БД с PostgreSQL 18 до 16 отклонено: это отдельный рискованный
data-migration project, который не нужен для достижения целевой архитектуры.

## Решение

### 1. Целевая версия

PostgreSQL **18.x** является единственной целевой major-версией WeldPassport.

Точная `server_version_num`:

- записывается в verification, rehearsal и adoption evidence;
- не зашивается как единственная допустимая minor-версия;
- обязана совпадать между target DB и restored rehearsal DB;
- при изменении после rehearsal требует повторного restore/rehearsal.

Обычное minor update не требует повторения B-04A-R18, если fingerprint v2 остаётся
идентичным принятому evidence.

### 2. Неизменяемость PG16 evidence

Существующие семь B-04A PG16 artifacts не перемещаются, не редактируются и не
перегенерируются. Они получают классификацию:

```text
historical_non_authorizing
```

Эта классификация означает: evidence подтверждает выполненную PG16-проверку, но не
разрешает B-04B adoption на целевой PostgreSQL 18.

### 3. Новый PG18 evidence contract

`canonical_baseline_v1` остаётся тем же schema baseline. Не создаются:

- новая baseline revision;
- новый source cut;
- новая historical migration chain.

Для PostgreSQL 18 вводится fingerprint format version `2` и отдельный evidence set:

```text
migrations/baselines/canonical_baseline_v1/
├── <существующие PG16 artifacts — без изменений>
├── evidence-index.json
└── postgresql-18/
    ├── contract.json
    ├── expected-fingerprint.json
    ├── expected-fingerprint.sha256
    └── verification-report.json
```

`evidence-index.json` различает:

- PG16 evidence — `historical_non_authorizing`;
- PG18 evidence — единственный возможный `active_authorizing` после отдельной приёмки.

Version-independent artifacts (`cut.json`, frozen revision manifest, seed manifest)
не дублируются. PG18 `contract.json` ссылается на их SHA-256.

PG18 `verification-report.json` обязан содержать:

- `status = B04A_VERIFIED`;
- `postgres_major = 18`;
- точную `server_version_num`;
- `fingerprint_format_version = 2`;
- source и implementation commit;
- shared artifact digests;
- historical, baseline и re-upgrade digests.

Новый PG18 digest не обязан совпадать с PG16 fingerprint v1.

### 4. Отдельный gate B-04A-R18

Вводится самостоятельный блок:

```text
B-04A-R18 — PostgreSQL 18 Re-verification
```

Его реализация начинается от merge commit
`e87800e771f5a39bd55cd745c532657c89f06516`.

B-04A-R18:

1. вводит fail-closed PostgreSQL 18 guard;
2. вводит fingerprint format v2;
3. сохраняет baseline candidate и 31 historical revision byte-identical;
4. выполняет historical replay и clean baseline на двух owned disposable PG18.x;
5. доказывает:

```text
historical fingerprint v2
    == baseline fingerprint v2
    == re-upgrade fingerprint v2
    == expected PG18 fingerprint v2
```

6. публикует отдельное immutable PG18 evidence;
7. требует отдельной приёмки.

Рабочая БД не подключается и не изменяется в B-04A-R18.

### 5. Влияние на B-04B

B-04B остаётся `BLOCKED`, а migration freeze — active, пока одновременно не выполнены:

- B-04A-R18 принят;
- PG18 evidence выбран как `active_authorizing`;
- повторный Maintenance Readiness Review дал `READY`.

После принятия B-04A-R18 B-04B preflight принимает только evidence с:

```text
status = B04A_VERIFIED
postgres_major = 18
fingerprint_format_version = 2
evidence_index_status = active_authorizing
```

Backup создаётся PostgreSQL 18 `pg_dump --format=custom`. Restore и rehearsal
выполняются на отдельной PostgreSQL 18 с той же точной `server_version_num`, что target.

## Stop conditions

Работа немедленно останавливается при:

- изменении frozen revisions или baseline schema ради совпадения;
- изменении существующих PG16 evidence artifacts;
- fingerprint mismatch;
- non-PG18 verification endpoint;
- подключении рабочей БД в B-04A-R18;
- попытке начать B-04B до отдельной приёмки B-04A-R18;
- несовпадении target и rehearsal `server_version_num`;
- изменении target minor version после rehearsal без повторного rehearsal.

## Последовательность

```text
ADR-030
  → отдельный spec/plan/prompt B-04A-R18
  → pure contract implementation and review
  → two-database disposable PG18 verification
  → immutable PG18 evidence
  → отдельная приёмка B-04A-R18
  → новый READ-ONLY Maintenance Readiness Review
  → ADR-031 / B-04R restore-roundtrip evidence
  → отдельная приёмка B-04R
  → повторный READ-ONLY Maintenance Readiness Review
  → READY
  → B-04B-1
  → review
  → B-04B-2
  → review
  → maintenance approval
  → B-04B-3
  → ADOPTION_ACCEPTED
  → closure
  → release migration freeze
```

## Явно вне решения

- repository cut;
- marker transfer;
- production adoption;
- изменение working DB;
- backup/restore рабочей БД;
- TEST-DB Foundation;
- runtime legacy compatibility profile;
- изменения доменных моделей, API или бизнес-логики.

## Последствия

Положительные:

- устраняется противоречие между целевой архитектурой PostgreSQL 18 и B-04 tooling;
- сохраняется неизменяемый аудит PG16;
- adoption разрешается только evidence целевой major-версии;
- исключается риск понижения рабочей БД.

Отрицательные:

- требуется отдельная реализация и приёмка B-04A-R18;
- B-04B остаётся заблокированным;
- при изменении target minor после rehearsal нужно повторить restore/rehearsal.

## Критерии архитектурной приёмки

- PostgreSQL 18.x зафиксирован как единственная target major-version;
- PG16 evidence не переписан и классифицирован как historical non-authorizing;
- fingerprint v2 и отдельный PG18 evidence set определены;
- B-04A-R18 отделён от B-04B;
- frozen source cut, revisions, baseline и marker state не меняются;
- migration freeze остаётся active;
- реализация, commit и adoption не разрешаются самим фактом принятия ADR.
