# B-04R Candidate-State Test Remediation — Specification

Дата: 2026-07-29
Статус: **COMPLETED / PROMOTION COMMIT ACCEPTED / B-04B-1 READINESS READY 2026-07-29**

Accepted implementation SHA:
`1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b`.

## 1. Контекст

Принятый runtime implementation SHA:
`65f3a28855eb0830077117fa26d9bbf789f50cb5`.

Повторный operator run завершён:

```text
B04_RESTORE_ROUNDTRIP_VERIFIED
```

Runner опубликовал пять артефактов
`postgresql-18/restore-roundtrip-v1/` и перевёл
`restore-evidence-index.json` в точное состояние
`candidate_pending_acceptance`. Artifact schema/hash review, secret scan,
fixed-point и typed map прошли.

После публикации focused suite в текущем candidate-state дал:

```text
44 passed, 15 failed
```

Причина всех 15 failures относится к test harness:

1. `test_b04r_index_001_repository_index_is_empty_and_non_authorizing`
   жёстко требует pre-generation empty index.
2. `_write_candidate_artifacts()` копирует repository `postgresql-18/` целиком,
   наследует уже опубликованный `restore-roundtrip-v1/` и затем повторно вызывает
   `restore_dir.mkdir()`.
3. `_publication_root()` копирует текущие pending index и `postgresql-18/`
   целиком, поэтому publication tests начинают не с пустого isolated state.

Clean Git clone exact implementation SHA без candidate artifacts подтверждает:

```text
379 passed, 1 skipped
```

## 2. Решение

Принят **вариант 1: explicit lifecycle-state tests + isolated live-only fixtures**.

Test fixtures обязаны создавать собственное начальное состояние и не зависеть от
того, находится repository в pre-generation, pending или active state.

Repository-state test, наоборот, обязан проверять ровно текущий governance stage:

- до promotion — exact `candidate_pending_acceptance`;
- после отдельно разрешённого promotion — exact
  `active_restore_authorizing`.

Общий тест вида «разрешён pending или active» запрещён: он не обнаружит
непреднамеренный lifecycle rollback.

## 3. Границы изменения

Разрешено изменить только:

```text
09_Разработка/backend/migration_contract_tests/test_b04_restore_evidence.py
09_Разработка/backend/migration_contract_tests/test_b04_restore_roundtrip_runner.py
09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py
docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_SPEC.md
docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_IMPLEMENTATION_PLAN.md
docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_CLAUDE_CODE_PROMPT.md
docs/project/TASK_REGISTRY.md
docs/project/PROJECT_STATUS.yaml
docs/project/ROADMAP.md
docs/project/PROJECT_SUMMARY.md
docs/project/CHAT_INDEX.md
docs/project/DECISIONS.md
```

Запрещено изменять:

- `migrations/b04/**`;
- пять файлов `postgresql-18/restore-roundtrip-v1/**`;
- `restore-evidence-index.json`;
- existing live evidence и `evidence-index.json`;
- `migrations/versions/**`, `migrations/baseline_candidates/**`,
  `migrations/archive/**`;
- backup и обе disposable БД;
- application/runtime/Alembic код;
- credentials, DSN или transient operator environment.

PostgreSQL connection, повторный restore, cleanup, evidence acceptance,
promotion, stage, commit и push не входят в эту remediation.

## 4. Test-fixture architecture

### 4.1 Live-only copy

Оба test-файла должны использовать явный allowlist четырёх immutable live
artifacts:

```text
contract.json
expected-fingerprint.json
expected-fingerprint.sha256
verification-report.json
```

Fixture создаёт новый `postgresql-18/` и копирует каждый allowlisted regular
file через `shutil.copy2`. Копирование directory tree запрещено.

Fixture должна fail closed, если:

- исходный allowlisted файл отсутствует;
- target уже существует;
- в target появился `restore-roundtrip-v1` до действия теста.

### 4.2 Empty publication index

Publication fixtures не копируют repository `restore-evidence-index.json`.
Они записывают через `canonical_json_bytes()` точный empty index:

```json
{
  "format_version": 1,
  "baseline_id": "canonical_baseline_v1",
  "live_evidence_id": "postgresql-18-fingerprint-v2",
  "evidence_sets": []
}
```

Это тестовый sandbox state. Оно не изменяет repository pending index.

### 4.3 Pending repository-state assertion

Текущий repository-state test должен:

1. подтвердить canonical JSON текущего restore index;
2. вызвать `validate_restore_evidence_index()`;
3. потребовать ровно одну запись;
4. потребовать:
   `evidence_id=postgresql-18-restore-roundtrip-v1`;
5. потребовать:
   `status=candidate_pending_acceptance`;
6. потребовать `acceptance is None`;
7. потребовать exact пять artifact names;
8. физически пересчитать SHA-256 всех пяти файлов и сравнить с outer index;
9. потребовать, чтобы `resolve_restore_authorizing_evidence()` завершался
   `B04R-ACCEPTANCE`.

Тест не создаёт acceptance и не вызывает `build_accepted_restore_index()`.

## 5. Promotion boundary

Эта remediation не выполняет promotion.

После отдельного owner acceptance и отдельного разрешения на promotion
repository-state test должен быть изменён в promotion diff:

- exact status `active_restore_authorizing`;
- exact `accepted_by=repository_owner`;
- valid `accepted_at_utc`;
- exact `verification_report_sha256`;
- физический resolver возвращает единственный authorizing restore evidence.

Fixture isolation из §4.1–4.2 после promotion не меняется.

## 6. TDD и проверки

RED evidence уже получен на неизменённом candidate-state:

```text
44 passed, 15 failed
```

После реализации обязательны:

```powershell
pytest migration_contract_tests/test_b04_restore_evidence.py `
  migration_contract_tests/test_b04_restore_roundtrip_runner.py -q
pytest migration_contract_tests -q
python -m compileall migration_contract_tests
git diff --check
```

Дополнительно:

- secret scan пяти candidate artifacts;
- byte/hash equality пяти candidate artifacts до/после;
- byte/hash equality existing live evidence до/после;
- byte equality pending `restore-evidence-index.json` до/после;
- отсутствие изменений runtime migration code;
- отсутствие PostgreSQL connections.

## 7. Критерии приёмки

- оба test sandbox строятся только из live-only allowlist;
- test sandbox всегда начинает publication с exact empty restore index;
- текущий repository-state test строго проверяет pending state и физические
  hashes;
- pending evidence остаётся non-authorizing;
- все 15 state-transition failures устранены без изменения production code или
  evidence bytes;
- focused и полный `migration_contract_tests` проходят в текущем candidate
  worktree;
- B-04R переведён в `active_restore_authorizing`;
- B-04B остаётся `BLOCKED`;
- promotion выполнен по отдельному owner authorization; promotion commit,
  cleanup и Maintenance Readiness Review не выполнены.

## 8. Отклонённые варианты

### Вариант 2 — проверять тесты только в clean clone

Отклонён: скрывает невозможность запускать regression suite после promotion и
не устраняет зависимость fixtures от repository state.

### Вариант 3 — разрешить repository test принимать pending или active

Отклонён: ослабляет governance и не обнаруживает rollback active evidence в
pending state.

## 9. Accepted scope amendment: PG18 live-directory assertion

Pure implementation двух разрешённых test-файлов дала:

```text
test_b04_restore_evidence.py: 32 passed
test_b04_restore_roundtrip_runner.py: 27 passed
combined: 59 passed
```

Полный suite выявил ещё один pre-restore repository assumption:

```text
378 passed, 1 skipped, 1 failed
```

`test_b04_evidence_versioning.py::
test_b04_r18_evidence_002_repository_index_is_active_authorizing`
требует, чтобы `postgresql-18/` содержал только четыре live artifact names.
После согласованной B-04R publication каталог также содержит ровно один
versioned child directory `restore-roundtrip-v1`.

Первоначальная Specification разрешала менять только два B-04R test-файла,
поэтому третий файл не был изменён в первой implementation части.

Scope amendment принят владельцем 2026-07-29:

- добавить
  `09_Разработка/backend/migration_contract_tests/test_b04_evidence_versioning.py`;
- сохранить exact четыре live regular files;
- потребовать exact один child directory:
  `restore-roundtrip-v1`;
- не разрешать другие files/directories;
- не менять live evidence resolver, hashes или runtime code.

Точная assertion после продолжения implementation:

```python
assert {
    path.name for path in evidence_dir.iterdir() if path.is_file()
} == set(PG18_ARTIFACT_NAMES)
assert {
    path.name for path in evidence_dir.iterdir() if path.is_dir()
} == {"restore-roundtrip-v1"}
```

Scope amendment и continuation pure implementation разрешены владельцем.
Третий test-файл изменён только в принятой assertion boundary; exact test дал
`1 passed`, three-file regression — `98 passed`, полный suite —
`379 passed, 1 skipped`. Code acceptance, implementation commit и resulting
SHA `1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b` отдельно приняты владельцем
2026-07-29. Evidence promotion отдельно разрешён и выполнен:

```text
status=active_restore_authorizing
accepted_at_utc=2026-07-29T08:55:32Z
accepted_by=repository_owner
verification_report_sha256=5480a2e4e02a085f8378ee9617da0b9ad4c04aca4a42fd0a52b933b4b75554be
```

Promotion commit `abaada5aad7e53d94c00395adb1a0ff742c27dd5`
принят. Новый READ-ONLY Maintenance Readiness Review выполнен отдельно;
verdict `READY` к B-04B-1 принят 2026-07-29. Marker transfer, production
adoption и DB run этим verdict не разрешены.
