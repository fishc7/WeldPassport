# Prompt для Claude Code / Cursor — B-04R Restore-Roundtrip Evidence

> **Статус:** `OPERATOR REMEDIATION COMMITTED — awaiting SHA acceptance`.
> Implementation base:
> `08bc6a09974e0272ff27938511af5d4d6ba33403`.
> DB run, evidence generation, implementation commit и B-04B остаются запрещены
> до отдельных явных разрешений.

## Цель

Реализовать ADR-031: отдельный versioned evidence contract для стабильного
PostgreSQL 18 custom-format restore fingerprint, не изменяя live fingerprint v2 и
существующие accepted evidence.

## Обязательные источники

- `AGENTS.md`;
- `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md`;
- `docs/project/ADR-030-postgresql-18-b04-evidence-versioning.md`;
- `docs/project/ADR-031-b04-dual-state-live-restore-evidence.md`;
- `docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC.md`;
- `docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_SPEC.md`;
- `docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_IMPLEMENTATION_PLAN.md`;
- current `migrations/b04/evidence.py`, `fingerprint.py`, `verify_baseline.py`;
- immutable B-04A/B-04A-R18 artifacts.

Если Spec/plan не имеют отдельной приёмки, HEAD не является согласованным base SHA или
worktree содержит неоговорённые изменения — остановись.

## Целевой scope кода

Разрешено после plan acceptance:

- создать `migrations/b04/restore_evidence.py`;
- создать `migrations/b04/verify_restore_roundtrip.py`;
- создать focused pure tests в `migration_contract_tests/`;
- минимально расширить exact disposable-name allowlist в
  `migrations/b04/disposable.py` и его pure tests только двумя B-04R DB names;
- добавить только новый `restore-evidence-index.json` initial contract;
- подготовить atomic generation новых files под
  `postgresql-18/restore-roundtrip-v1/`;
- минимально интегрировать accepted restore resolver в будущий B-04B preflight;
- обновить только согласованные B-04 docs/status files;
- предоставить diff и proposed commits.

## Жёстко запрещено

- изменять `migrations/b04/fingerprint.py`;
- нормализовать expressions regex/string replacements;
- игнорировать CHECK/predicate definitions;
- менять существующий `evidence-index.json`;
- менять любой существующий PG16 или PG18 artifact;
- менять baseline candidate, frozen revisions или active migration graph;
- менять working DB, marker или domain data;
- выполнять repository cut/adoption;
- реализовывать остальные B-04B Tasks;
- запускать application tests;
- использовать application `.env` как fallback;
- хранить/log credentials или DSN;
- commit/push без отдельного разрешения.

## Обязательный TDD flow

1. Написать focused failing pure tests.
2. Показать RED с ожидаемыми missing interfaces.
3. Реализовать минимальный contract.
4. Показать GREEN focused suite.
5. Запустить полный `migration_contract_tests`.
6. Выполнить `compileall`.
7. Показать `git diff --check`, список файлов и полный diff.
8. Остановиться для code acceptance.

DB run и evidence generation до принятого implementation SHA запрещены.

## Contract requirements

### Live evidence

- resolve ровно один `postgresql-18-fingerprint-v2`;
- status `active_authorizing`;
- live digest остаётся неизменным;
- existing artifacts проверяются byte-for-byte.

### Restore evidence

- evidence ID `postgresql-18-restore-roundtrip-v1`;
- statuses:
  `candidate_pending_verification`,
  `candidate_pending_acceptance`,
  `active_restore_authorizing`;
- новый отдельный `restore-evidence-index.json`;
- exact five-artifact set;
- owner acceptance не может быть создан runner.

### Typed diff

Допускаются только exact leaves:

```text
check_definition_deparser_roundtrip
index_predicate_deparser_roundtrip
```

Каждый item содержит exact object identity, JSON pointers и SHA-256 обеих expression
strings. После исключения ровно mapped leaves полный structural diff обязан быть пуст.
Wildcard, regex и общие ignore rules запрещены.

### Runner

Порядок fail-closed:

```text
artifact preflight
→ live evidence resolution
→ exact server/tool version checks
→ working READ ONLY fingerprint
→ first/second disposable safety
→ first restore/fingerprint
→ second dump/restore/fingerprint
→ fixed-point equality
→ exact typed diff
→ atomic candidate publication
→ stop before acceptance
```

Working identity никогда не может совпадать с disposable identity.

## Pure acceptance

```powershell
$PythonExe = $env:B04R_PYTHON_EXE
if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "B04R_PYTHON_EXE must point to the explicitly approved project Python interpreter"
}

& $PythonExe -m pytest migration_contract_tests/test_b04_restore_evidence.py -q
& $PythonExe -m pytest migration_contract_tests/test_b04_restore_roundtrip_runner.py -q
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall migrations/b04
git diff --check
```

Не запускай PostgreSQL/Alembic/application tests на code-acceptance этапе.

## Критерии приёмки

- existing accepted evidence hashes не изменились;
- pure tests покрывают все stop conditions;
- working connection read-only устанавливается до catalog queries;
- two-restore fixed point обязателен;
- structural differences вне exact typed map отклоняются;
- output publication atomic/create-new;
- secrets отсутствуют в errors/reports;
- runner публикует только `candidate_pending_acceptance`;
- полный diff ограничен B-04R;
- B-04B остаётся `BLOCKED`;
- commit/push отсутствуют без отдельного подтверждения.

## Формат результата

1. base/head SHA;
2. список изменённых файлов;
3. RED evidence;
4. GREEN evidence и counts;
5. immutable-artifact hash proof;
6. `compileall` и `git diff --check`;
7. полный diff;
8. stop-condition inventory;
9. proposed commit(s);
10. явная остановка до DB run/evidence acceptance.
