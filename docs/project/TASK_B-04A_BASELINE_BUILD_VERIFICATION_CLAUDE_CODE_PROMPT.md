# Prompt для Claude Code / Cursor — B-04A Baseline Build & Verification

Работай только в отдельном worktree от schema source commit:

```text
6c56f99edbd4e7346264ee14658d2076b5fd0775
```

До начала убедись, что commit существует локально и является merge commit PR #4.
Если SHA не разрешается или фактический migration snapshot отличается от ожидаемого,
остановись и сообщи расхождение.

## Цель

Создать и доказать self-contained Alembic baseline candidate
`canonical_baseline_v1`, не изменяя active migration graph, version marker или
существующую рабочую БД.

## Обязательные источники

- `AGENTS.md`;
- `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md`;
- `docs/project/TASK_B-03_MIGRATION_FOUNDATION_SPEC.md`;
- `docs/project/ADR-029-test-db-safety-interlock.md`;
- `docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC.md`;
- `docs/project/TASK_B-04A_BASELINE_BUILD_VERIFICATION_IMPLEMENTATION_PLAN.md`;
- `09_Разработка/backend/app/shared/canonical_metadata.py`;
- `09_Разработка/backend/migrations/canonical_boundary.py`;
- `09_Разработка/backend/migrations/env.py`;
- `09_Разработка/backend/migrations/versions/`;
- `09_Разработка/backend/migration_contract_tests/`.

## Ожидаемый source snapshot

- 5 canonical schemas;
- 12 canonical model modules;
- 73 canonical tables;
- 31 historical revisions;
- root `20260702_02_hr_core`;
- head `20260724_27_qd_rbac_sod`;
- 8 `quality.defect_types` seeds;
- 7 `quality.defect_location_types` seeds;
- DB-only index `hr.worker_roles.uq_hr_worker_roles_active_scope`.

Любое отличие — stop condition.

## Разрешено

- создать `migrations/b04/`;
- создать verification-only candidate Alembic context;
- создать `migrations/baseline_candidates/canonical_baseline_v1.py`;
- создать B-04A manifest, seed and fingerprint artifacts;
- создать pure contract tests в `migration_contract_tests/`;
- использовать две явно подтверждённые одноразовые PostgreSQL 16.x базы;
- обновить документацию только после подтверждённой приёмки B-04A.

## Запрещено

- изменять `migrations/env.py` или `alembic.ini`;
- изменять, удалять или перемещать 31 active revision;
- создавать active baseline в `migrations/versions`;
- выполнять stamp или перенос `alembic_version`;
- читать `.env` как fallback;
- подключаться к существующей рабочей БД;
- запускать application tests;
- использовать `Base.metadata.create_all`;
- импортировать `app.*` из baseline revision;
- исправлять historical revisions;
- реализовывать B-04B, runtime profile или TEST-DB Foundation;
- staging, commit и push без отдельного разрешения.

## Обязательный подход

Работай строго по
`TASK_B-04A_BASELINE_BUILD_VERIFICATION_IMPLEMENTATION_PLAN.md`.

Для каждого task:

1. напиши failing test;
2. запусти его и зафиксируй ожидаемый RED;
3. реализуй минимальное решение;
4. запусти focused GREEN;
5. покажи список файлов и diff;
6. остановись на review checkpoint;
7. не переходи к следующему task до приёмки.

## Safety contract

Любая DB-команда требует одновременно:

- отдельный explicit B-04 DSN;
- `WELDPASSPORT_B04_ALLOW_DESTRUCTIVE=YES`;
- непустой ownership token;
- exact confirmation database name;
- имя БД начинается `wp_b04_` и заканчивается `_disposable`;
- DB identity не совпадает с ordinary application settings;
- PostgreSQL major = 16.

URL, password, host и username не должны попадать в output, exception или artifacts.

## Baseline contract

`canonical_baseline_v1.py`:

- `revision = "canonical_baseline_v1"`;
- `down_revision = None`;
- находится вне active `migrations/versions`;
- self-contained и offline-renderable;
- создаёт ровно утверждённый canonical result;
- включает schemas, constraints, indexes, owned sequences и 15 literal seeds;
- не создаёт legacy/test/workforce;
- destructive downgrade разрешён только disposable runner.

## Fingerprint contract

PostgreSQL catalog fingerprint v1 включает schemas, tables, columns/defaults,
PK/UQ/FK/CHECK, indexes/expressions/predicates, owned sequences и exact seeds.

Не включай OID, owner, ACL, stats, row counts и sequence counters. Неизвестный object
class останавливает процесс. Не маскируй расхождение automatic normalization.

## Приёмка

```powershell
$PythonExe = "D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe"
```

Pure:

```powershell
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall migrations/b04 migrations/baseline_candidates
git diff --check
```

PostgreSQL evidence:

- historical clean replay успешен;
- baseline clean upgrade успешен;
- historical fingerprint = baseline fingerprint;
- 73 tables и 15 seeds подтверждены;
- baseline downgrade удаляет только canonical objects;
- re-upgrade возвращает тот же digest;
- report status `B04A_VERIFIED`.

## Формат результата

Верни:

1. source SHA и snapshot;
2. список изменённых файлов;
3. полный diff;
4. RED/GREEN evidence по каждому task;
5. pure test counts;
6. PostgreSQL evidence без credentials;
7. manifest/fingerprint/seed/report digests;
8. ограничения и незакрытые findings;
9. предложенные commit messages.

Не заявляй B-04A завершённой без свежей полной verification.
