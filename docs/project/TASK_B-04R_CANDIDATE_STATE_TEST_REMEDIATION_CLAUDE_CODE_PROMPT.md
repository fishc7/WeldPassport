# B-04R Candidate-State Test Remediation — Cursor / Claude Code Prompt

Статус: **EVIDENCE PROMOTED / PROMOTION COMMIT AUTHORIZED 2026-07-29**

Работай только в:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness
```

Ветка:

```text
codex/b04b-maintenance-readiness-review
```

Принятый runtime implementation HEAD:

```text
65f3a28855eb0830077117fa26d9bbf789f50cb5
```

## Цель

Исправить только B-04R pure test harness для текущего repository-state
`candidate_pending_acceptance`.

После исправления focused и полный `migration_contract_tests` должны проходить
в текущем worktree, при этом runtime-код, пять candidate artifacts,
`restore-evidence-index.json`, existing live evidence и PostgreSQL остаются
byte/state-identical.

## Обязательные источники

Прочитай полностью:

```text
docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_SPEC.md
docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_IMPLEMENTATION_PLAN.md
docs/project/ADR-031-b04-dual-state-live-restore-evidence.md
09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py
09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py
09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py
```

Specification и Implementation Plan обязательны. Не расширяй scope.

## Разрешено менять

Ровно три файла:

```text
09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py
09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py
09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py
```

## Запрещено

- менять `09_Разработка/backend/migrations/b04/**`;
- менять пять файлов
  `migrations/baselines/canonical_baseline_v1/postgresql-18/restore-roundtrip-v1/**`;
- менять
  `migrations/baselines/canonical_baseline_v1/restore-evidence-index.json`;
- менять existing live evidence, `evidence-index.json`, frozen revisions,
  migrations, baseline candidates или archive;
- подключаться к PostgreSQL;
- запускать Alembic, `pg_dump`, `pg_restore`, operator scripts или application
  tests;
- clean/drop обе disposable БД;
- создавать acceptance или promotion;
- менять documentation/status files;
- исправлять unrelated issues;
- stage, commit или push.

Существующие owner documentation и candidate evidence changes в worktree не
твои. Не перезаписывай, не stage и не удаляй их.

## Обязательный RED

Перед изменением тестов из `09_Разработка/backend` запусти:

```powershell
$PythonExe = "C:\Users\Andrey\AppData\Local\Programs\Python\Python314\python.exe"
$RedRoot = "D:\WeldPassport_Backups\B04B\b04r_candidate_test_remediation_red"
New-Item -ItemType Directory -Path $RedRoot -Force | Out-Null
& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  --basetemp (Join-Path $RedRoot "pytest-prompt-001") -q
```

Ожидается:

```text
44 passed, 15 failed
```

Если counts или причины отличаются, остановись и сообщи фактический результат.

## Изменение 1 — restore-evidence fixtures

В `test_b04_restore_evidence.py`:

1. Замени empty repository-state test на exact pending-state test.
2. Требуй:
   - canonical restore index;
   - ровно одну entry;
   - exact evidence ID;
   - `status=candidate_pending_acceptance`;
   - `acceptance is None`;
   - exact five artifact names;
   - физическое совпадение SHA-256 каждого файла с outer index;
   - `resolve_restore_authorizing_evidence()` отклоняет pending state exact
     кодом `B04R-ACCEPTANCE`.
3. Добавь:

```python
def _copy_live_evidence_only(root: Path) -> Path:
    live_dir = root / "postgresql-18"
    live_dir.mkdir()
    for name in LIVE_ARTIFACT_SHA256:
        source = ARTIFACT_ROOT / "postgresql-18" / name
        target = live_dir / name
        if source.is_symlink() or not source.is_file() or target.exists():
            raise AssertionError("B04R test fixture live artifact boundary")
        shutil.copy2(source, target)
    if (live_dir / "restore-roundtrip-v1").exists():
        raise AssertionError("B04R test fixture inherited restore evidence")
    return live_dir
```

4. `_write_candidate_artifacts()` должен использовать этот helper и потом
   сам создать `restore-roundtrip-v1`.
5. `shutil.copytree()` для repository `postgresql-18/` запрещён.

Не разрешай repository-state test принимать одновременно pending и active.

## Изменение 2 — publication fixtures

В `test_b04_restore_roundtrip_runner.py`:

1. Импортируй:

```python
from migrations.b04.manifest import canonical_json_bytes
```

2. Добавь exact allowlist:

```python
LIVE_ARTIFACT_NAMES = (
    "contract.json",
    "expected-fingerprint.json",
    "expected-fingerprint.sha256",
    "verification-report.json",
)
```

3. Добавь `_empty_restore_index()` с exact значением:

```python
{
    "format_version": 1,
    "baseline_id": "canonical_baseline_v1",
    "live_evidence_id": "postgresql-18-fingerprint-v2",
    "evidence_sets": [],
}
```

4. Добавь local `_copy_live_evidence_only(root: Path) -> Path`, который
   `copy2()` копирует только четыре allowlisted regular files, отклоняет
   symlink/missing/preexisting target и подтверждает отсутствие
   `restore-roundtrip-v1`.
5. `_publication_root()` должен:
   - создать isolated root;
   - копировать только `evidence-index.json`;
   - записать собственный restore index через
     `canonical_json_bytes(_empty_restore_index())`;
   - вызвать live-only helper;
   - не читать repository pending restore index;
   - не использовать `copytree()` для `postgresql-18/`.

## Изменение 3 — PG18 repository directory shape

В `test_b04_evidence_versioning.py` измени только stale assertion в
`test_b04_r18_evidence_002_repository_index_is_active_authorizing`:

```python
assert {
    path.name for path in evidence_dir.iterdir() if path.is_file()
} == set(PG18_ARTIFACT_NAMES)
assert {
    path.name for path in evidence_dir.iterdir() if path.is_dir()
} == {"restore-roundtrip-v1"}
```

Не меняй hash/index/status/resolver assertions. Дополнительные regular files и
directories остаются запрещены.

## GREEN проверки

Каждый запуск использует новый внешний `basetemp`:

```powershell
$GreenRoot = "D:\WeldPassport_Backups\B04B\b04r_candidate_test_remediation_green"
New-Item -ItemType Directory -Path $GreenRoot -Force | Out-Null

& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  --basetemp (Join-Path $GreenRoot "pytest-evidence-prompt-001") -q

& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  --basetemp (Join-Path $GreenRoot "pytest-runner-prompt-001") -q

& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  --basetemp (Join-Path $GreenRoot "pytest-combined-prompt-001") -q

& $PythonExe -m pytest `
  migration_contract_tests/test_b04_evidence_versioning.py::test_b04_r18_evidence_002_repository_index_is_active_authorizing `
  --basetemp (Join-Path $GreenRoot "pytest-versioning-prompt-001") -q

& $PythonExe -m pytest `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  migration_contract_tests/test_b04_evidence_versioning.py `
  --basetemp (Join-Path $GreenRoot "pytest-three-files-prompt-001") -q

& $PythonExe -m pytest migration_contract_tests `
  --basetemp (Join-Path $GreenRoot "pytest-full-prompt-001") -q

& $PythonExe -m py_compile `
  migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py `
  migration_contract_tests/test_b04_evidence_versioning.py

git diff --check
```

Expected combined focused result:

```text
59 passed
```

Expected full result:

```text
379 passed, 1 skipped
```

## Immutable proof

До и после правок вычисли SHA-256 для:

```text
restore-evidence-index.json
evidence-index.json
postgresql-18/{contract.json,expected-fingerprint.json,expected-fingerprint.sha256,verification-report.json}
postgresql-18/restore-roundtrip-v1/{contract.json,expected-fingerprint.json,expected-fingerprint.sha256,equivalence-map.json,verification-report.json}
```

Все 11 hashes до/после обязаны совпасть.

Secret scan пяти candidate artifacts не должен находить DSN, password, host,
port, user или transient environment names.

## Формат результата

Верни:

1. base/head SHA и branch;
2. точный список трёх изменённых test-файлов;
3. RED counts и причины;
4. GREEN counts каждого focused запуска;
5. full suite result;
6. 11 immutable before/after hashes;
7. `py_compile` и `git diff --check`;
8. полный diff только трёх test-файлов;
9. подтверждение: DB connections, Alembic, restore, cleanup, promotion, stage,
   commit и push не выполнялись;
10. явную остановку для code acceptance.

## Scope amendment — accepted 2026-07-29

После реализации двух разрешённых файлов получено:

```text
focused: 59 passed
full: 378 passed, 1 skipped, 1 failed
```

Оставшийся failure находится в
`migration_contract_tests/test_b04_evidence_versioning.py`: test ожидает
только четыре entries в `postgresql-18/` и не учитывает согласованный
`restore-roundtrip-v1`.

В `test_b04_evidence_versioning.py` разрешено заменить только stale
directory-shape assertion на:

```python
assert {
    path.name for path in evidence_dir.iterdir() if path.is_file()
} == set(PG18_ARTIFACT_NAMES)
assert {
    path.name for path in evidence_dir.iterdir() if path.is_dir()
} == {"restore-roundtrip-v1"}
```

Не ослабляй hash/index/status/resolver assertions и не разрешай другие entries.
Scope amendment, continuation pure implementation, code acceptance,
implementation commit и SHA
`1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b` приняты владельцем.
Получено: exact `1 passed`, three-file `98 passed`, full
`379 passed, 1 skipped`. Evidence promotion отдельно разрешён и выполнен с
`accepted_at_utc=2026-07-29T08:55:32Z`,
`accepted_by=repository_owner` и report SHA
`5480a2e4e02a085f8378ee9617da0b9ad4c04aca4a42fd0a52b933b4b75554be`.
Остановись перед commit и новым READ-ONLY Maintenance Readiness Review.
