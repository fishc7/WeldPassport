# B-04R Restore-Roundtrip Evidence Contract — Implementation Specification

Дата: 2026-07-29

Статус: **ACCEPTED 2026-07-29**

Архитектурное основание:
[[docs/project/ADR-031-b04-dual-state-live-restore-evidence|ADR-031 (ACCEPTED)]].

## 1. Цель

Реализовать отдельный fail-closed evidence contract для PostgreSQL 18
`pg_dump --format=custom` restore state, не изменяя принятый live fingerprint v2.

После отдельной приёмки B-04R должен разрешать B-04B rehearsal только когда:

- working DB совпадает с live `active_authorizing` evidence;
- restored DB совпадает с `active_restore_authorizing` evidence;
- exact typed live/restore diff совпадает с immutable equivalence map;
- первый и второй restore дают один и тот же fingerprint.

## 2. Исходное доказательство проблемы

Operator investigation 2026-07-29, не являющееся accepted evidence:

| Проверка | Результат |
|---|---|
| PostgreSQL | `server_version_num = 180003` |
| live fingerprint | `e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a` |
| first restore fingerprint | `3a9e682cbb0546638a23aaf5ef27dc720daa32ce9a8c2dd466a6c47a91453038` |
| second restore fingerprint | `3a9e682cbb0546638a23aaf5ef27dc720daa32ce9a8c2dd466a6c47a91453038` |
| exact leaf differences | 135 |
| CHECK definition differences | 133 |
| partial-index predicate differences | 2 |
| прочие differences | 0 |

Формальная реализация обязана воспроизвести результат заново. Эти числа нельзя
просто скопировать в accepted evidence без runner verification.

## 3. Границы

### В scope

- pure evidence/index/typed-diff contracts;
- pure tests;
- explicit runner для working read-only fingerprint и двух disposable restores;
- atomic publication только новых B-04R artifacts;
- отдельное promotion pending evidence после owner acceptance;
- обновление B-04/B-04B preflight resolver.

### Вне scope

- изменение `migrations/b04/fingerprint.py`;
- expression normalization;
- изменение любого принятого PG16/PG18 artifact;
- изменение baseline candidate или frozen revisions;
- repository cut;
- marker transaction/adoption;
- изменение working DB;
- application tests и TEST-DB Foundation;
- runtime compatibility profile;
- cleanup существующих domain data.

## 4. Artifact layout

Новые файлы:

```text
migrations/baselines/canonical_baseline_v1/
├── restore-evidence-index.json
└── postgresql-18/
    └── restore-roundtrip-v1/
        ├── contract.json
        ├── expected-fingerprint.json
        ├── expected-fingerprint.sha256
        ├── equivalence-map.json
        └── verification-report.json
```

Все существующие artifacts обязаны остаться byte-identical.

## 5. Restore evidence index

`restore-evidence-index.json`:

```json
{
  "format_version": 1,
  "baseline_id": "canonical_baseline_v1",
  "live_evidence_id": "postgresql-18-fingerprint-v2",
  "evidence_sets": []
}
```

Разрешён ровно один restore entry:

```text
evidence_id = postgresql-18-restore-roundtrip-v1
status = candidate_pending_verification
       | candidate_pending_acceptance
       | active_restore_authorizing
postgres_major = 18
contract_path = postgresql-18/restore-roundtrip-v1/contract.json
artifact_sha256 = exact five-artifact map
acceptance = null | exact owner acceptance
```

`active_restore_authorizing` требует:

```text
accepted_at_utc
accepted_by = repository_owner
verification_report_sha256
```

Runner не может сам назначить этот status.

## 6. Contract

`contract.json` фиксирует:

- evidence/baseline/live evidence IDs;
- source SHA и accepted implementation SHA;
- PostgreSQL major и exact `server_version_num`;
- exact `pg_dump`/`pg_restore` version strings;
- fingerprint format version live и restore;
- live expected fingerprint digest;
- restore expected fingerprint digest;
- equivalence map digest;
- digests существующих immutable live/shared artifacts, от которых зависит contract;
- digests `expected-fingerprint.json`, `expected-fingerprint.sha256` и
  `equivalence-map.json`;
- canonical table/sequence/governed seed counts;
- expected artifact names.

Не допускаются machine paths, credentials, hostnames или usernames.

Digest graph обязан быть ацикличным:

```text
expected fingerprint / sha file / equivalence map
    → contract
    → verification report
    → restore evidence index
```

`contract.json` не содержит digest самого себя или `verification-report.json`.

## 7. Exact typed equivalence map

Формат:

```text
format_version
live_evidence_id
restore_evidence_id
live_fingerprint_sha256
restore_fingerprint_sha256
difference_count
differences[]
```

Каждый `differences[]` содержит exact keys:

```text
kind
schema
table
object_name
live_json_pointer
restore_json_pointer
live_expression_sha256
restore_expression_sha256
```

Допустимы только:

- `check_definition_deparser_roundtrip`;
- `index_predicate_deparser_roundtrip`.

Требования:

- identities уникальны;
- pointers указывают на существующие string values;
- expression hashes пересчитываются и совпадают;
- diff полного JSON fingerprint после удаления mapped leaves пуст;
- map не принимает wildcard, regex или prefix matching;
- map не может скрывать отсутствующий/лишний object.

## 8. Verification report

Status успешного report:

```text
B04_RESTORE_ROUNDTRIP_VERIFIED
```

Report содержит:

- evidence/live evidence IDs;
- source/implementation SHA;
- exact server/tool versions;
- sanitized working/restore identities;
- backup SHA-256 и custom-format validation result;
- live, first restore и second restore digests;
- exact typed difference counts по kind;
- marker state каждой DB;
- canonical tables/sequences/seeds counts;
- digests `contract.json`, `expected-fingerprint.json`,
  `expected-fingerprint.sha256` и `equivalence-map.json`;
- `first_restore_digest == second_restore_digest`;
- `live_digest == active_authorizing_live_digest`;
- `typed_diff == equivalence_map`.

DB URLs, passwords, hosts и usernames в report запрещены.
Report не содержит digest самого себя. Digest всех пяти artifacts, включая report,
фиксируется только во внешнем `restore-evidence-index.json`.

## 9. Runner contract

Runner получает только explicit inputs:

- working DSN;
- first/second disposable DSN;
- backup path;
- exact destructive opt-in только для disposable endpoints;
- ownership tokens;
- artifact output directory;
- accepted implementation SHA.

Обычный application `.env` не используется как fallback.

Порядок:

```text
artifact/index preflight
→ existing accepted live evidence resolution
→ exact tool version
→ working connection READ ONLY
→ disposable ownership/emptiness/version preflight
→ custom backup checksum verification
→ first restore
→ first fingerprint
→ second dump/restore
→ second fingerprint
→ exact typed diff
→ atomic candidate artifact publication
→ candidate_pending_acceptance
→ stop
```

Working DB:

- только read-only repeatable-read transaction;
- marker и live fingerprint проверяются;
- DDL/DML/backup creation runner не выполняет.

Disposable endpoints:

- exact expected names;
- PostgreSQL 18;
- owned текущим operator role;
- empty до первого destructive command;
- никогда не совпадают с working identity;
- при ошибке evidence publication выполняется атомарный rollback файлов, но DB
  автоматически не переиспользуется.

## 10. Fail-closed codes

Минимальный набор:

```text
B04R-EVIDENCE-INDEX
B04R-LIVE-EVIDENCE
B04R-SERVER-VERSION
B04R-TOOL-VERSION
B04R-WORKING-READONLY
B04R-WORKING-FINGERPRINT
B04R-DISPOSABLE-SAFETY
B04R-BACKUP
B04R-RESTORE
B04R-RESTORE-FINGERPRINT
B04R-FIXED-POINT
B04R-DIFF-KIND
B04R-DIFF-MAP
B04R-ARTIFACT-PUBLISH
B04R-ACCEPTANCE
```

Сообщения не содержат secrets или DSN.

## 11. Pure contract tests

Обязательные группы:

1. exact restore index keys/status transitions;
2. existing accepted evidence byte identity;
3. exact contract/report keys;
4. typed diff accepts только два exact kinds;
5. rejection любого structural/non-expression difference;
6. rejection missing/extra/mutated map item;
7. JSON pointer and expression hash verification;
8. exact version mismatch;
9. working/disposable identity collision;
10. working connection read-only ordering;
11. first/second digest mismatch;
12. secret redaction;
13. atomic artifact publication/rollback;
14. runner не назначает `active_restore_authorizing`;
15. accepted resolver требует exact owner acceptance/report digest.

## 12. Acceptance sequence

```text
Spec acceptance
→ implementation plan acceptance
→ pure code RED/GREEN
→ code review
→ accepted implementation SHA
→ operator preflight
→ two-restore verification
→ candidate_pending_acceptance evidence
→ evidence review
→ separate owner acceptance
→ active_restore_authorizing
→ new READ-ONLY Maintenance Readiness Review
```

DB run, evidence promotion, commit и push требуют отдельных разрешений.

## 13. Definition of Done

- ADR-031 и Spec приняты;
- existing evidence artifacts byte-identical;
- pure tests и compileall проходят;
- working DB ни разу не изменялась runner;
- two-restore fixed point доказан на owned disposable PostgreSQL 18.x;
- exact typed map принят без wildcard/normalization;
- candidate evidence отдельно reviewed/promoted;
- resolver возвращает ровно один `active_restore_authorizing`;
- B-04B docs требуют и live, и restore evidence;
- новый Maintenance Readiness Review выполнен отдельно.

До выполнения всех пунктов B-04B остаётся `BLOCKED`, migration freeze — active.
