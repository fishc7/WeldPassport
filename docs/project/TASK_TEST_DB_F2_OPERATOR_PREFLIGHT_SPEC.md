# TEST-DB-F2-OPERATOR-PREFLIGHT — Implementation Specification

Статус: **ACCEPTED / IMPLEMENTATION PLAN ACCEPTED / IMPLEMENTATION NOT STARTED**

Дата: 2026-07-30

Архитектурное основание:

- [[docs/project/ADR-029-test-db-safety-interlock|ADR-029]];
- [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032]];
- [[docs/project/ADR-033-test-db-f2-local-rehearsal|ADR-033]];
- [[docs/project/TASK_TEST_DB_F2_PURE_RUNNER_SPEC|TEST-DB-F2 Pure Runner Specification]].

## 1. Цель

Реализовать отдельный fail-closed operator-facing preflight, который доказывает
готовность repository/source/environment/evidence boundary к запросу отдельного
разрешения на `TEST-DB-F2-LOCAL-REHEARSAL`.

Preflight является полностью offline:

- не открывает PostgreSQL connection;
- не запускает worker/application/Alembic-процессы;
- не запускает Alembic CLI или application tests;
- не создаёт, не удаляет, не переименовывает и не reset-ит DB;
- не присваивает `TEST_DB_F2_REHEARSAL_VERIFIED` или `TEST_DB_F2_ACCEPTED`.

## 2. Delivery boundary

```text
TEST-DB-F2-PURE-RUNNER
→ TEST-DB-F2-OPERATOR-PREFLIGHT tooling
→ pure verification and review
→ accepted tooling commit and push
→ transient operator environment
→ offline operator preflight execution
→ TEST_DB_F2_OPERATOR_PREFLIGHT_READY
→ separate PostgreSQL authorization
→ TEST-DB-F2-LOCAL-REHEARSAL
```

Разрешение на этот task включает specification, plan, Prompt, pure
implementation, tests, review/remediation, commits и push. Оно не включает
PostgreSQL rehearsal.

## 3. Архитектура

Реализуется отдельный модуль и thin CLI:

```text
app/testing/f2_operator_preflight.py
scripts/run_test_db_f2_operator_preflight.py
```

Существующий rehearsal coordinator не получает флаг `--preflight-only` и не
ослабляется. Operator preflight переиспользует immutable F2 contracts, F1
offline target authorization, normalized identity collision checks и
create-exclusive evidence primitives.

## 4. Отдельная authorization boundary

Operator preflight требует отдельную transient переменную:

```text
WELDPASSPORT_F2_PREFLIGHT_AUTHORIZATION
```

Exact значение:

```text
I_AUTHORIZE_TEST_DB_F2_OPERATOR_PREFLIGHT
```

Preflight не требует и не принимает rehearsal authorization
`I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL` от оператора. Для переиспользования
существующего strict parent parser модуль после exact preflight authorization
строит внутренний mapping, удаляет preflight-only key и подставляет rehearsal
authorization только как локальную parser-константу. Значение не передаётся
процессу и не является разрешением на rehearsal.

Остальные inputs совпадают с F2 parent contract:

- working target URL;
- внешний evidence root;
- exact destructive opt-in `YES`;
- три role-prefixed target URL / confirmation / ownership token bundle.

Unknown `WELDPASSPORT_F2_*` key, missing/blank input или неверная exact
authorization завершают preflight fail closed. Raw values не попадают в
exception, output или evidence.

## 5. Source и prerequisite checks

До evidence reservation preflight проверяет:

1. branch `codex/b04b-maintenance-readiness-review`;
2. exact lowercase 40-character `HEAD` SHA;
3. отсутствие staged/unstaged tracked changes;
4. ancestry принятых prerequisite commits:
   - TEST-DB-F1 `20c7ea7`;
   - RUNTIME-COMPAT-1 closure `03d4c59`;
   - TEST-DB-F2 Pure Runner closure `32ffec8`;
5. Python runtime не ниже 3.12;
6. импортируемость pure operator-preflight dependencies без импорта
   `app.shared.db`/`app.main`.

Untracked files не входят в source identity.

Единственные допустимые subprocess на этом этапе — фиксированные read-only Git
команды `git rev-parse HEAD`, `git status --porcelain --untracked-files=no`,
`git branch --show-current` и `git merge-base --is-ancestor <sha> HEAD`. Они
используют argument arrays, `shell=False`, не получают secret environment и не
запускаются повторно.

## 6. Offline target checks

До любого process/connection I/O preflight:

1. требует ровно три роли в fixed order;
2. вызывает exact F1 `authorize_test_database(...)` один раз на роль;
3. проверяет collision каждой test identity с working target;
4. проверяет попарную уникальность трёх test identity;
5. формирует только domain-separated identity digest;
6. не делает DNS lookup и не открывает socket.

Для переиспользования логики `f2_preflight.py` разрешено выделить pure
`authorize_offline_targets(...)` без изменения существующего поведения
`build_offline_plan(...)`.

## 7. Evidence root и namespace

Evidence root обязан:

- существовать до запуска;
- быть каталогом вне repository/worktrees;
- не быть symlink/reparse point;
- не находиться внутри repository root;
- не содержать заранее существующий namespace выбранного `preflight_id`.

Preflight генерирует UUIDv4 `preflight_id` и create-exclusive резервирует:

```text
<evidence-root>/operator-preflight-<preflight_id>/
```

Это не rehearsal `run_id` и namespace не может быть принят runner как rehearsal
evidence.

## 8. Evidence artifact

При полном успехе create-exclusive публикуется:

```text
00_operator_preflight.json
```

Canonical JSON содержит:

- protocol version `test-db-f2-operator-preflight/v1`;
- `preflight_id`;
- source SHA и branch;
- UTC timestamp;
- prerequisite commit identifiers;
- Python major/minor/micro;
- ordered role и identity digest;
- safe check results;
- итоговый статус `TEST_DB_F2_OPERATOR_PREFLIGHT_READY`.

Запрещены DSN, host, port, username, password, database name, ownership token,
filesystem user path и raw exception.

Digest вычисляется по exact canonical bytes. Artifact и namespace никогда не
перезаписываются и не удаляются runner/preflight tooling.

## 9. Machine outcomes

- `TEST_DB_F2_OPERATOR_PREFLIGHT_READY`;
- `TEST_DB_F2_OPERATOR_PREFLIGHT_FAILED`;
- `TEST_DB_F2_OPERATOR_PREFLIGHT_EVIDENCE_FAILED`.

CLI возвращает `0` только для `READY` и печатает только `preflight_id`, status и
artifact digest. `READY` означает лишь право запросить отдельное разрешение на
PostgreSQL rehearsal.

Если failure произошёл до безопасной reservation, authoritative artifact может
отсутствовать. Evidence publication failure имеет высший приоритет и никогда не
может дать `READY`.

## 10. Pure test matrix

Обязательны pure tests:

- exact preflight authorization;
- rejection rehearsal authorization и unknown F2 keys;
- dirty/malformed/wrong-branch source;
- missing prerequisite ancestry;
- unsupported Python version;
- missing/unsafe/in-repository evidence root;
- UUIDv4 и create-exclusive namespace;
- все F1 unsafe inputs;
- working и все pairwise test collisions;
- exact three-role order;
- no connection/worker/application/Alembic/DNS call; разрешены только
  перечисленные fixed read-only Git subprocess;
- recursive secret absence в repr/errors/output/JSON;
- deterministic canonical artifact;
- evidence failure precedence;
- CLI exit contract;
- governance AST scan: no DB lifecycle, shell, retry, Alembic, application
  suite или eager DB import.

Pure tests располагаются только в `migration_contract_tests/`.

## 11. Acceptance

Tooling может получить статус:

```text
IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED
```

Фактический offline run может получить `READY` только если operator transient
environment уже присутствует. При отсутствии значений tooling остаётся
реализованным, но operational preflight не объявляется готовым.

После focused и full pure suite выполняются compile, diff/scope audit,
read-only review и remediation. Затем создаётся closure commit и выполняется
разрешённый push текущей ветки.

PostgreSQL, Alembic CLI, application suite и DB lifecycle на всём этом этапе
запрещены.
