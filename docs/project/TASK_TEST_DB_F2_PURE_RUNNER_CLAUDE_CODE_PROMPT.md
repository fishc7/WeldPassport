# TEST-DB-F2-PURE-RUNNER — Prompt for Cursor / Claude Code

Работай в:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness
```

Python working directory:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness\09_Разработка\backend
```

Перед изменениями полностью прочитай:

1. `docs/00_PROJECT_CONTEXT.md`;
2. `docs/ARCHITECTURE.md`;
3. `docs/project/DECISIONS.md`;
4. `docs/project/TASK_REGISTRY.md`;
5. `docs/project/ADR-029-test-db-safety-interlock.md`;
6. `docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary.md`;
7. `docs/project/ADR-033-test-db-f2-local-rehearsal.md`;
8. `docs/project/TASK_TEST_DB_FOUNDATION_SPEC.md`;
9. `docs/project/TASK_TEST_DB_F2_PURE_RUNNER_SPEC.md`;
10. `docs/project/TASK_TEST_DB_F2_PURE_RUNNER_IMPLEMENTATION_PLAN.md`.

## Цель

Реализовать только `TEST-DB-F2-PURE-RUNNER` по Implementation Plan:

- pure full-trio offline preflight;
- fixed sequential fresh-worker protocol;
- bind-once one target per worker;
- minimal sanitized child environments;
- create-exclusive canonical JSON evidence и SHA-256 chain;
- strict short-circuit/failure precedence;
- pure-tested operational adapter boundary.

Итоговый статус:

```text
IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED
```

## Обязательный TDD

Для каждого task:

1. написать точный RED test;
2. запустить и зафиксировать ожидаемый failure;
3. реализовать минимальный production code;
4. получить focused GREEN;
5. проверить diff;
6. выполнить review checkpoint;
7. создать отдельный conventional commit.

Production code до соответствующего RED запрещён.

## Запрещено

- подключаться к PostgreSQL;
- запускать Alembic CLI или application `tests/`;
- создавать/удалять/reset/rename DB;
- менять migrations, domain, API или workforce behavior;
- ослаблять F1/Runtime Compatibility gates;
- передавать secrets через argv;
- наследовать полный parent environment;
- писать DSN, host, port, user, password, database name или token в
  output/evidence/errors;
- использовать shell execution, retry или wildcard DB discovery;
- выполнять push до полного pure closure.

## Обязательные проверки

Focused:

```powershell
python -m pytest `
  migration_contract_tests/test_f2_contract.py `
  migration_contract_tests/test_f2_evidence.py `
  migration_contract_tests/test_f2_preflight.py `
  migration_contract_tests/test_f2_process.py `
  migration_contract_tests/test_f2_coordinator.py `
  migration_contract_tests/test_f2_worker.py `
  migration_contract_tests/test_f2_governance.py -q
```

Full pure:

```powershell
python -m pytest migration_contract_tests -q
```

Compile/diff:

```powershell
python -m compileall app/testing scripts/run_test_db_f2.py
git diff --check
git status --short
git diff --name-only
```

## Требуемый отчёт

Предоставь:

1. статус;
2. изменённые файлы;
3. RED → GREEN evidence каждого task;
4. exact focused/full counts;
5. compile/diff result;
6. review verdict и remediation;
7. подтверждение отсутствия PostgreSQL/Alembic/application/DB lifecycle;
8. commits;
9. ограничения и следующий operational gate;
10. push result только после clean closure.
