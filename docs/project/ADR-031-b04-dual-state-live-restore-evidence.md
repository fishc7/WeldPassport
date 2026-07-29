# ADR-031. B-04 Dual-State Live and Restore-Roundtrip Evidence

Дата: 2026-07-29

Статус: **ACCEPTED**

Связано:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/ADR-030-postgresql-18-b04-evidence-versioning|ADR-030]];
- [[docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC|B-04 Canonical Baseline Adoption]];
- [[docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_SPEC|B-04R Specification]];
- [[docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_IMPLEMENTATION_PLAN|B-04R Implementation Plan]];
- [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

## Контекст

После приёмки B-04A-R18 новый READ-ONLY Maintenance Readiness Review подтвердил:

- working PostgreSQL 18.3 имеет принятый live fingerprint v2
  `e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a`;
- historical marker остаётся
  `test.alembic_version = 20260724_27_qd_rbac_sod`;
- `public.alembic_version` отсутствует;
- 73 canonical tables, 6 sequences и 15 governed seeds совпадают с accepted evidence;
- custom-format backup успешно восстанавливается в отдельную PostgreSQL 18.3.

При этом fingerprint первой восстановленной копии равен
`3a9e682cbb0546638a23aaf5ef27dc720daa32ce9a8c2dd466a6c47a91453038`,
а не live digest. Повторный `pg_dump --format=custom` и второй restore дают тот же
`3a9e682c...`, то есть restore-состояние стабильно.

Точный structural diff содержит только:

- 133 `CHECK` definitions;
- 2 predicates частичных индексов.

PostgreSQL повторно разбирает DDL, сериализованный `pg_dump`, и deparser меняет
текстовую форму casts/arrays при сохранении смысла выражений. Данные, seeds, marker,
таблицы, columns, keys, foreign keys, sequences и прочие fingerprint-разделы не
расходятся.

ADR-030 и B-04B до этого требовали прямого равенства live и restored fingerprint.
Это требование невыполнимо для принятого PostgreSQL 18.3 schema state без ослабления
fingerprint или разрушительной перестройки working DB.

## Решение

### 1. Два разных authorizing состояния

B-04 использует два связанных, но невзаимозаменяемых evidence contract:

1. **Live migration-built state**
   - существующий evidence ID `postgresql-18-fingerprint-v2`;
   - status `active_authorizing`;
   - fingerprint format v2;
   - разрешает только preflight текущей working DB.
2. **Restore-roundtrip state**
   - новый evidence ID `postgresql-18-restore-roundtrip-v1`;
   - отдельный status `active_restore_authorizing` после приёмки;
   - разрешает только проверку DB, созданной из принятого custom-format backup.

Restore evidence не может разрешить working DB, а live evidence не может само по себе
разрешить restored rehearsal DB.

### 2. Неизменяемость принятого evidence

Остаются byte-identical:

- семь PG16 artifacts;
- `evidence-index.json`;
- четыре принятых PG18 artifacts в `postgresql-18/`;
- live fingerprint format v2 и digest;
- source cut, 31 frozen revisions и `canonical_baseline_v1`.

Новый contract добавляется только новыми файлами:

```text
migrations/baselines/canonical_baseline_v1/
├── evidence-index.json                         # без изменений
├── postgresql-18/
│   ├── contract.json                           # без изменений
│   ├── expected-fingerprint.json               # без изменений
│   ├── expected-fingerprint.sha256             # без изменений
│   ├── verification-report.json                # без изменений
│   └── restore-roundtrip-v1/
│       ├── contract.json
│       ├── expected-fingerprint.json
│       ├── expected-fingerprint.sha256
│       ├── equivalence-map.json
│       └── verification-report.json
└── restore-evidence-index.json
```

### 3. Exact typed equivalence map

`equivalence-map.json` не является allowlist и не игнорирует expressions. Он обязан
содержать ровно каждое наблюдаемое отличие:

- тип: `check_definition_deparser_roundtrip` или
  `index_predicate_deparser_roundtrip`;
- schema/table/object identity;
- JSON pointer live и restored expression;
- SHA-256 обеих точных expression strings.

Полные strings сохраняются в двух immutable expected-fingerprint artifacts.
Wildcard, regex-нормализация, удаление casts/operators/parentheses и правило
«игнорировать все CHECK/predicate» запрещены.

Любое отличие вне exact map, отсутствующий элемент map, дополнительный элемент map
или изменившийся expression SHA останавливает процесс.

### 4. Restore-roundtrip verification

Формальное B-04R evidence создаётся только после приёмки реализации и доказывает:

```text
working live fingerprint
    == active-authorizing PG18 fingerprint v2

first restore fingerprint
    == second restore fingerprint
    == restore-roundtrip expected fingerprint

typed_diff(live, first restore)
    == accepted equivalence-map
```

Обязательны:

- PostgreSQL major 18;
- одинаковый exact `server_version_num` working, first restore и second restore;
- точные версии `pg_dump` и `pg_restore`;
- custom-format backup и SHA-256;
- working DB подключается только read-only;
- first/second restore DB заранее подтверждены как owned, empty и disposable;
- 15 governed seeds и marker state совпадают во всех трёх DB;
- evidence сначала получает `candidate_pending_acceptance`;
- `active_restore_authorizing` назначается только отдельной приёмкой владельца.

Изменение exact server/tool version или любого digest требует нового B-04R
verification. Оно не требует повторения B-04A-R18, пока live fingerprint v2 не
изменился.

### 5. Влияние на B-04B

B-04B остаётся `BLOCKED`, пока одновременно не выполнены:

- B-04A-R18 `active_authorizing`;
- B-04R `active_restore_authorizing`;
- новый Maintenance Readiness Review дал `READY`.

B-04B preflight проверяет live target только по live digest, а restored rehearsal DB —
только по restore-roundtrip digest. Прямое равенство этих двух digests больше не
является требованием.

Backup/rehearsal конкретного maintenance run остаётся отдельным operational evidence:
его SHA-256, DB identity, exact version, restore result и adoption rehearsal не
подменяются B-04R contract.

## Отклонённые варианты

1. **Regex/string normalization fingerprint expressions.** Отклонено: может скрыть
   реальный semantic drift и противоречит принятому fail-closed contract.
2. **Игнорировать все CHECK definitions и partial-index predicates.** Отклонено:
   ослабляет canonical boundary.
3. **Перестроить working DB через restore.** Отклонено: разрушительно, меняет принятый
   live baseline без бизнес-необходимости.
4. **Считать любой restore digest допустимым.** Отклонено: только exact accepted
   restore fingerprint и exact typed map могут разрешать rehearsal.

## Stop conditions

- изменение существующих PG16/PG18 evidence artifacts;
- изменение `fingerprint.py` ради совпадения digests;
- изменение working schema/data/marker в B-04R;
- non-PG18 endpoint;
- несовпадение exact server/tool versions;
- live fingerprint не равен active-authorizing v2;
- first и second restore fingerprints различаются;
- diff содержит объект вне двух разрешённых typed kinds;
- число или identity diff не совпадает с accepted map;
- попытка использовать restore evidence для working target;
- попытка начать repository cut/adoption до нового `READY`.

## Последовательность

```text
ADR-031
  → B-04R spec
  → review
  → B-04R implementation plan
  → review
  → pure contract implementation
  → review
  → owned disposable restore verification
  → candidate evidence
  → отдельная приёмка evidence
  → active_restore_authorizing
  → новый Maintenance Readiness Review
  → READY
  → B-04B
```

## Явно вне решения

- repository cut;
- marker transfer/adoption;
- изменение working DB;
- изменение baseline/frozen revisions;
- application tests;
- TEST-DB Foundation;
- runtime compatibility profile;
- commit/push без отдельного подтверждения.

## Критерии архитектурной приёмки

- live и restore states разделены по назначению;
- existing accepted evidence остаётся byte-identical;
- restore contract добавляется только новыми versioned artifacts;
- exact typed map не является wildcard/allowlist;
- two-restore fixed-point proof обязателен;
- B-04B остаётся blocked до отдельного accepted B-04R evidence и нового `READY`;
- принятие ADR само по себе не разрешает реализацию, DB run, commit или adoption.
