# B-04A-R18 — PostgreSQL 18 Re-verification Specification

Дата: 2026-07-28

Статус: **ACCEPTED / VERIFIED**

Дата приёмки: 2026-07-29

Связано:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/ADR-030-postgresql-18-b04-evidence-versioning|ADR-030]];
- [[docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC|B-04 master specification]];
- [[docs/project/TASK_B-04A_R18_POSTGRESQL_18_REVERIFICATION_IMPLEMENTATION_PLAN|B-04A-R18 implementation plan]];
- [[docs/project/TASK_B-04A_R18_POSTGRESQL_18_REVERIFICATION_CLAUDE_CODE_PROMPT|B-04A-R18 Claude Code prompt]].

## 1. Цель

B-04A-R18 должен повторно доказать эквивалентность frozen historical chain и
`canonical_baseline_v1` на PostgreSQL 18.x. Результат — fingerprint format v2 и
отдельный immutable PG18 evidence set, который может стать authorizing только после
отдельной приёмки владельцем.

B-04A-R18 не выполняет repository cut, marker transfer или adoption.

## 2. Базовые commits и неизменяемые факты

- schema source cut:
  `6c56f99edbd4e7346264ee14658d2076b5fd0775`;
- B-04A-R18 code baseline:
  `e87800e771f5a39bd55cd745c532657c89f06516`;
- ADR-030 documentation commit:
  `4c93a3bac94272ae454ca1423d135df2d5e38bc3`;
- historical root: `20260702_02_hr_core`;
- historical head: `20260724_27_qd_rbac_sod`;
- frozen revisions: `31`;
- baseline revision: `canonical_baseline_v1`;
- canonical schemas: `engineering`, `hr`, `project`, `quality`, `welding`;
- canonical tables: `73`;
- governed seeds: `15`.

Commit `4c93a3b` имеет родителя `e87800e`; между schema source cut и текущим planning
head новые migration revisions отсутствуют.

## 3. Неизменяемый PG16 evidence

Следующие семь файлов являются historical evidence и не изменяются ни на один байт.
Их SHA-256 вычисляется по каноническим bytes Git blobs с LF. Репозиторный
`.gitattributes` закрепляет `eol=lf` для JSON/SHA-256 evidence, поэтому clean checkout
обязан быть byte-identical Git blob независимо от `core.autocrlf`:

| Artifact | SHA-256 |
|---|---|
| `cut.json` | `6ca7959ae2f25c6d9c0c9b02272aacda34a09e035515fcb25773cba9f5bd46dc` |
| `expected-fingerprint.json` | `ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6` |
| `expected-fingerprint.sha256` | `c4ac2c98c18778a9428dbeeb0e53246279daa7837e2b1673596b3d5148353b1e` |
| `frozen-revision-manifest.json` | `8e791f4204b3b68b2dfb7ac8409f3b55124547a9df4e8c5487e128b66a22ec8d` |
| `frozen-revision-manifest.sha256` | `7f9531008ba5d1fcb3ed2544fb3da1212aad9ec4dd98c343090e1586c0d69eaa` |
| `seed-manifest.json` | `64aa1533c00f940405ed7fd7cbee7a60d831f5f952ec56961034f0b5570b679d` |
| `verification-report.json` | `563d65195cd1e381acccccf7caa31c48b09ef22fb2fda12235d705e1fbfd8487` |

Их статус в resolver:

```text
historical_non_authorizing
```

PG16 fingerprint v1 digest
`ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6`
не обязан совпадать с PG18 fingerprint v2.

## 4. Границы реализации

Разрешено изменять только B-04 verification tooling, его pure contract tests, новый
versioned PG18 evidence subtree и репозиторный `.gitattributes`, закрепляющий
канонические LF bytes evidence.

Запрещено:

- изменять 31 frozen revision;
- изменять `canonical_baseline_v1.py`;
- изменять семь PG16 artifacts;
- изменять `migrations/env.py`, `alembic.ini` или active marker contract;
- читать application `.env` как fallback;
- подключаться к working DB;
- запускать application tests;
- реализовывать B-04B, TEST-DB Foundation или runtime profile;
- создавать commit, push или cleanup без отдельного подтверждения.

## 5. PostgreSQL 18 safety contract

Оба verification endpoints должны:

- быть явно переданы как `postgresql+psycopg` URL без query/fragment;
- иметь exact host `127.0.0.1` и explicit TCP port;
- иметь точные disposable names:
  `wp_b04_r18_historical_disposable` и `wp_b04_r18_baseline_disposable`;
- пройти opt-in `YES` и secret-like ownership token;
- пройти `SHOW server_version_num` до первого Alembic subprocess;
- иметь major `18`;
- иметь одинаковую точную `server_version_num`.

Любая ошибка останавливает run до schema mutation. URL, пароль, ownership token и
полный connection string не входят в logs или evidence.

## 6. Fingerprint format v2

Fingerprint v2 сохраняет canonical scope v1 и использует PostgreSQL 18 system catalogs.

Обязательные constants:

```python
FINGERPRINT_FORMAT_VERSION = 2
SUPPORTED_POSTGRES_MAJOR = 18
```

Top-level shape остаётся:

```text
format_version + schemas + tables + sequences + seeds
```

Допускаются только нормализации доказанного PG18 deparse/catalog representation.
Запрещено:

- скрывать реальный schema drift;
- добавлять wildcard allowlist;
- удалять объект из fingerprint ради совпадения;
- менять baseline candidate или historical migration;
- копировать PG16 digest как PG18 expected digest.

Обязательное равенство:

```text
historical fingerprint v2
    == baseline fingerprint v2
    == re-upgrade fingerprint v2
```

## 7. Versioned evidence contract

Структура:

```text
migrations/baselines/canonical_baseline_v1/
├── <семь PG16 artifacts без изменений>
├── evidence-index.json
└── postgresql-18/
    ├── contract.json
    ├── expected-fingerprint.json
    ├── expected-fingerprint.sha256
    └── verification-report.json
```

`contract.json` фиксирует:

- `evidence_id = postgresql-18-fingerprint-v2`;
- source cut и B-04A-R18 implementation commit;
- `postgres_major = 18`;
- `fingerprint_format_version = 2`;
- immutable SHA-256 shared artifacts;
- canonical table/seed counts;
- exact expected artifact names.

`evidence-index.json` имеет exact top-level keys:

```text
format_version + baseline_id + evidence_sets
```

Каждый evidence entry имеет exact keys:

```text
evidence_id
status
postgres_major
fingerprint_format_version
artifact_sha256
contract_path
acceptance
```

Для PG16 `contract_path` и `acceptance` равны `null`, а `artifact_sha256` содержит
точные семь hashes из §3. Для PG18 до evidence run `artifact_sha256` пуст,
`contract_path = postgresql-18/contract.json`, `acceptance = null`.

`verification-report.json` фиксирует:

- `status = B04A_VERIFIED`;
- `evidence_id`;
- source и implementation SHA;
- `postgres_major = 18`;
- точную `server_version_num`;
- `fingerprint_format_version = 2`;
- sanitized disposable database names;
- historical, baseline и re-upgrade digests;
- shared artifact digests;
- `73` tables, `15` seeds и governed index.

Publication использует create-new semantics. Частично опубликованный evidence set при
ошибке удаляется целиком; существующий accepted/pending evidence не перезаписывается.

## 8. Evidence index и отдельная приёмка

До реального evidence run:

```text
postgresql-16-fingerprint-v1 = historical_non_authorizing
postgresql-18-fingerprint-v2 = candidate_pending_verification
```

После успешного run, но до пользовательской приёмки:

```text
postgresql-18-fingerprint-v2 = candidate_pending_acceptance
```

Только отдельная приёмка владельцем разрешает:

```text
postgresql-18-fingerprint-v2 = active_authorizing
```

При promotion поле `acceptance` получает exact keys:

```text
accepted_at_utc
accepted_by = repository_owner
verification_report_sha256
```

Runner не может сам назначить `active_authorizing` или заполнить `acceptance`.

Structural validation индекса не обращается к filesystem. Отдельный authorizing
resolver обязан получить explicit artifact root, проверить существование contract и
report, SHA-256 report против `acceptance.verification_report_sha256`, согласованность
major/format/evidence ID и только затем вернуть active evidence. Отсутствующий,
неоднозначный или повреждённый active set является fail-closed ошибкой.

## 9. Последовательность

```text
spec/plan/prompt acceptance
  → pure RED contracts
  → PG18 tooling GREEN
  → full migration_contract_tests
  → implementation review
  → separately approved implementation commit
  → two owned disposable PG18 databases
  → one evidence run
  → immutable PG18 artifacts
  → evidence review
  → separate B-04A-R18 acceptance
  → evidence-index promotion to active_authorizing
  → new READ-ONLY Maintenance Readiness Review
```

## 10. Stop conditions

Работа немедленно останавливается при:

- изменении любого PG16 artifact SHA-256;
- изменении frozen revision или baseline candidate;
- наличии новой migration после source cut;
- non-PG18 endpoint;
- различии exact `server_version_num` двух disposable endpoints;
- fingerprint mismatch;
- попытке overwrite evidence;
- неясном или частичном publication state;
- working DB identity;
- попытке активировать B-04B или снять migration freeze.

## 11. Критерии приёмки specification

- fingerprint v2 и PG18 safety contract определены;
- exact minor фиксируется, но не становится permanent architecture pin;
- семь PG16 artifacts защищены точными hashes;
- source cut, 31 revisions и baseline неизменны;
- resolver не допускает self-authorization;
- working DB и B-04B исключены;
- реализация разделена на pure code review, disposable evidence и отдельную приёмку.

## 12. Closure evidence

B-04A-R18 принят 2026-07-29 со следующими неизменяемыми фактами:

- implementation commit:
  `f5245ba80698bdddfc64d2071061c2299a1c20f8`;
- accepted evidence commit:
  `b34538f5ddd4ed31d8094bc5d96f42ada7d1f28d`;
- PostgreSQL `server_version_num = 180003` (PostgreSQL 18.3);
- fingerprint format version: `2`;
- historical, baseline и re-upgrade fingerprint digest:
  `e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a`;
- verification report status: `B04A_VERIFIED`;
- verification report SHA-256:
  `f2ab657c702852d68e2c58620faab1d56434088bbbab63307ded27a39d1b8c17`;
- evidence index status: `active_authorizing`;
- owner acceptance:
  `repository_owner`, `2026-07-29T05:51:15Z`;
- pure verification: `314 passed, 1 skipped`;
- семь PG16 artifacts подтверждены byte-identical;
- рабочая БД не подключалась и не изменялась.

Принятие B-04A-R18 не разрешает B-04B автоматически. Следующий gate — новый
READ-ONLY Maintenance Readiness Review. До его verdict `READY` B-04B остаётся
`BLOCKED`, а migration freeze — active.
