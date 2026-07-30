# Prompt for Cursor / Claude Code — TEST-DB-F2 Operator Preflight

Статус: **ACCEPTED**

Дата: 2026-07-30

## Цель

Реализовать отдельный offline `TEST-DB-F2-OPERATOR-PREFLIGHT` по:

- `docs/project/TASK_TEST_DB_F2_OPERATOR_PREFLIGHT_SPEC.md`;
- `docs/project/TASK_TEST_DB_F2_OPERATOR_PREFLIGHT_IMPLEMENTATION_PLAN.md`;
- ADR-029, ADR-032 и ADR-033.

## Обязательный порядок

Выполняй Tasks 1–5 implementation plan строго последовательно. Для каждого
task используй RED → GREEN → compile/diff check → отдельный commit. После
реализации проведи read-only review, remediation и повторный полный pure suite.

## Разрешено

- менять только перечисленные в implementation plan testing modules, pure tests,
  `.env.example` и closure docs;
- выделить `authorize_offline_targets(...)` без изменения F1 semantics;
- добавить безопасные external evidence helpers;
- выполнять fixed read-only Git subprocess:
  `rev-parse`, `status --porcelain --untracked-files=no`,
  `branch --show-current`, `merge-base --is-ancestor`;
- запускать только `migration_contract_tests`, `compileall` и Git read-only
  checks;
- создавать commits и выполнить push после полного closure.

## Запрещено

- подключаться к PostgreSQL или выполнять DNS/socket lookup;
- запускать TEST-DB-F2 worker, Alembic CLI или `tests/`;
- создавать, удалять, reset-ить или переименовывать DB;
- менять Alembic revisions, domain/API/runtime contracts;
- ослаблять F1/F2 authorization, ownership, collision или bind-once gates;
- наследовать parent environment целиком;
- помещать DSN, credentials, database names или ownership tokens в argv, repr,
  errors, logs, stdout/stderr, repository или evidence;
- использовать `shell=True`, retry, repair, cleanup или wildcard discovery;
- присваивать `TEST_DB_F2_REHEARSAL_VERIFIED` или `TEST_DB_F2_ACCEPTED`;
- объявлять operator preflight `READY` без полного transient environment.

## Точные contracts

```text
protocol = test-db-f2-operator-preflight/v1
authorization = I_AUTHORIZE_TEST_DB_F2_OPERATOR_PREFLIGHT
branch = codex/b04b-maintenance-readiness-review
prerequisites = 20c7ea7, 03d4c59, 32ffec8
namespace = operator-preflight-<UUIDv4>
artifact = 00_operator_preflight.json
```

Machine statuses:

```text
TEST_DB_F2_OPERATOR_PREFLIGHT_READY
TEST_DB_F2_OPERATOR_PREFLIGHT_FAILED
TEST_DB_F2_OPERATOR_PREFLIGHT_EVIDENCE_FAILED
```

`READY` означает только возможность запросить отдельное разрешение на
PostgreSQL rehearsal.

## Проверки

Focused:

```powershell
python -m pytest `
  migration_contract_tests/test_f2_preflight.py `
  migration_contract_tests/test_f2_evidence.py `
  migration_contract_tests/test_f2_operator_preflight_contract.py `
  migration_contract_tests/test_f2_operator_preflight_runner.py `
  migration_contract_tests/test_f2_operator_preflight_governance.py -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

Full pure:

```powershell
python -m pytest migration_contract_tests -q `
  --basetemp='C:\Users\Andrey\.codex\tmp\weldpassport-runtime-compat-019fb148'
```

Затем:

```powershell
python -m compileall app/testing scripts/run_test_db_f2_operator_preflight.py
git diff --check
git status --short
git diff --name-only
```

## Результат

Предоставь:

- список изменённых файлов;
- diff summary;
- focused/full counts;
- review verdict и remediation;
- commits;
- safe operator-preflight status, только если transient environment реально
  присутствовал;
- подтверждение отсутствия PostgreSQL/Alembic/application/worker/DB lifecycle;
- push SHA и чистый synchronized worktree.
