# Prompt для Claude Code / Cursor — B-04A-R18 PostgreSQL 18 Re-verification

## Стартовый gate

Начинай только после отдельной приёмки:

- [[docs/project/ADR-030-postgresql-18-b04-evidence-versioning|ADR-030]];
- [[docs/project/TASK_B-04A_R18_POSTGRESQL_18_REVERIFICATION_SPEC|B-04A-R18 specification]];
- [[docs/project/TASK_B-04A_R18_POSTGRESQL_18_REVERIFICATION_IMPLEMENTATION_PLAN|B-04A-R18 implementation plan]].

Используй отдельный worktree
`D:\WeldPassport\.worktrees\b04a-r18-reverification` и branch
`codex/b04a-r18-reverification` от clean documentation head, который содержит
accepted planning commit `a7bdaf813822bf242309be64b369c8968eef9463`.
Цепочка обязательных ancestors:

```text
a7bdaf813822bf242309be64b369c8968eef9463
  → 4c93a3bac94272ae454ca1423d135df2d5e38bc3
  → e87800e771f5a39bd55cd745c532657c89f06516
```

Если ancestry, clean status или source cut не совпадают, остановись.

## Цель

Реализовать fail-closed PostgreSQL 18 fingerprint v2 verification, доказать
эквивалентность frozen historical chain и `canonical_baseline_v1` на двух owned
disposable PG18 БД и подготовить отдельный immutable evidence set.

## Неизменяемые факты

- source cut:
  `6c56f99edbd4e7346264ee14658d2076b5fd0775`;
- historical graph: 31 revisions,
  `20260702_02_hr_core → 20260724_27_qd_rbac_sod`;
- baseline: `canonical_baseline_v1`;
- canonical scope: 5 schemas, 73 tables, 15 seeds;
- fingerprint version: `2`;
- PostgreSQL major: `18`;
- migration freeze: active;
- B-04B: `BLOCKED`.

## Разрешено

- изменять только файлы, перечисленные в implementation plan;
- TDD-правки B-04 disposable guard, candidate context, fingerprint и verifier;
- добавить strict versioned evidence/index contracts;
- выполнять pure `migration_contract_tests` и `compileall`;
- после отдельной code acceptance использовать две explicitly owned disposable PG18
  базы;
- публиковать PG18 evidence только create-new semantics;
- подготовить полный diff, test evidence и proposed commits.

## Запрещено

- изменять 31 frozen revision;
- изменять `canonical_baseline_v1.py`;
- изменять семь существующих PG16 artifacts;
- изменять active Alembic graph, `migrations/env.py`, `alembic.ini` или marker;
- использовать working DB или application `.env`;
- запускать application tests;
- выводить DSN, пароль или ownership token;
- скрывать fingerprint mismatch allowlist/normalization без доказанного PG18 catalog
  основания;
- автоматически повторять destructive/evidence run;
- присваивать `active_authorizing` без отдельной приёмки владельца;
- начинать B-04B, repository cut, marker transfer или adoption;
- снимать migration freeze;
- stage, commit, push или cleanup без отдельного разрешения.

## Обязательный процесс

Для каждого Task из implementation plan:

1. проверить exact file scope;
2. написать минимальный failing contract;
3. выполнить focused RED и записать точную причину failure;
4. реализовать минимальный GREEN;
5. выполнить focused tests;
6. показать diff и провести read-only review;
7. устранить Critical/Important findings;
8. остановиться на review checkpoint.

Не объединяй Tasks и не переходи к PostgreSQL evidence до отдельной приёмки pure code.

## Ключевые контракты

### PostgreSQL

- `assert_postgresql_18()` возвращает exact `server_version_num` и major;
- обе БД проверяются до первого Alembic subprocess;
- обе имеют major 18 и одинаковую exact version;
- оба URL имеют exact host `127.0.0.1`; `localhost`, IPv6 и remote host запрещены;
- DB names exact:
  `wp_b04_r18_historical_disposable`,
  `wp_b04_r18_baseline_disposable`;
- любой mismatch завершает run без schema mutation.

### Fingerprint v2

```text
FINGERPRINT_FORMAT_VERSION = 2
SUPPORTED_POSTGRES_MAJOR = 18

historical bytes == baseline bytes == re-upgrade bytes
```

Canonical scope, seed policy и baseline literals не меняются.

### Evidence

```text
canonical_baseline_v1/
├── <PG16 artifacts immutable>
├── evidence-index.json
└── postgresql-18/
    ├── contract.json
    ├── expected-fingerprint.json
    ├── expected-fingerprint.sha256
    └── verification-report.json
```

До owner acceptance PG18 status может быть только
`candidate_pending_verification` или `candidate_pending_acceptance`.
Structural index validation не заменяет filesystem resolver: active evidence требует
проверенных contract/report paths, containment и SHA-256 report.

## Проверки pure code

```powershell
Set-Location "D:\WeldPassport\.worktrees\b04a-r18-reverification\09_Разработка\backend"
$PythonExe = "D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe"

& $PythonExe -m pytest `
  migration_contract_tests/test_b04_evidence_versioning.py `
  migration_contract_tests/test_b04_disposable_safety.py `
  migration_contract_tests/test_b04_candidate_context.py `
  migration_contract_tests/test_b04_fingerprint.py `
  migration_contract_tests/test_b04_verify_runner.py -q

& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall -q migrations/b04 migration_contract_tests
git diff --check
```

Обязательно отдельно доказать:

- hashes семи PG16 artifacts не изменились;
- `migrations/versions` не изменён;
- baseline candidate не изменён;
- source cut и manifest совпадают;
- нет `.env` fallback;
- нет working DB connection path.

## Evidence gate

После pure code review остановись. Evidence run разрешён только новым подтверждением,
которое называет:

- accepted implementation commit;
- две exact disposable database identities;
- ownership mechanism;
- exact common `server_version_num`;
- external operator/session location без раскрытия секретов;
- cleanup owner.

Выполни один run:

```powershell
& $PythonExe -m migrations.b04.verify_baseline
```

Не retry. При ошибке сохрани sanitized finding и остановись.

## Формат результата

До evidence:

1. список файлов;
2. полный diff;
3. RED/GREEN evidence по каждому Task;
4. focused и full test counts;
5. PG16 hash proof;
6. source/migration/baseline immutability proof;
7. review findings;
8. proposed implementation commit;
9. явная остановка перед PostgreSQL.

После отдельно разрешённого evidence run:

1. sanitized identities и exact version;
2. три fingerprint digests;
3. четыре PG18 artifact hashes;
4. PG16 hash proof;
5. index status `candidate_pending_acceptance`;
6. immutable publication result;
7. cleanup plan;
8. явная остановка перед acceptance/promotion.

Runner не принимает собственный результат. `active_authorizing`, commit, cleanup и
переход к Maintenance Readiness требуют отдельных решений владельца.
