# TEST-DB-F2-PURE-RUNNER — Implementation Specification

Статус: **IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED**

Дата: 2026-07-30

Архитектурное основание:

- [[docs/project/ADR-029-test-db-safety-interlock|ADR-029]];
- [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032]];
- [[docs/project/ADR-033-test-db-f2-local-rehearsal|ADR-033]];
- [[docs/project/TASK_TEST_DB_FOUNDATION_SPEC|TEST-DB Foundation Specification]];
- [[docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC|Runtime Compatibility Profile Specification]].

## 1. Цель

Реализовать pure-tested coordinator/worker protocol для локального
`TEST-DB-F2-LOCAL-REHEARSAL`, не выполняя PostgreSQL, Alembic или application
tests на этапе разработки и приёмки tooling.

Runner обязан:

- полностью проверить три target bundle до первого соединения;
- запускать три свежих worker-процесса строго последовательно;
- переиспользовать принятые F1 target/ownership gates;
- формировать create-exclusive redacted evidence с SHA-256 chain;
- завершаться fail closed без retry, repair, cleanup или перехода к следующей
  роли после ошибки.

Pure implementation не присваивает Foundation или Runtime Compatibility Profile
статус `ACCEPTED`.

## 2. Delivery boundary

```text
TEST-DB-F2-PURE-RUNNER
→ read-only review and remediation
→ accepted tooling commit
→ TEST-DB-F2-OPERATOR-PREFLIGHT
→ separate PostgreSQL authorization
→ TEST-DB-F2-LOCAL-REHEARSAL
→ evidence review
→ owner TEST_DB_F2_ACCEPTED
```

Эта specification разрешает проектирование и последующую pure-реализацию
runner. Она не разрешает:

- подключение к PostgreSQL;
- Alembic CLI;
- application test suite;
- создание, удаление, переименование или reset DB;
- operational preflight или rehearsal;
- CI binding;
- push без отдельного разрешения.

## 3. Выбранная архитектура

Принят вариант **pure orchestration library + thin coordinator CLI + isolated
worker entrypoint**.

Компоненты:

- `app/testing/f2_contract.py` — immutable protocol/value objects, roles,
  statuses, environment names и safe errors;
- `app/testing/f2_preflight.py` — pure Git/source/environment/target validation;
- `app/testing/f2_evidence.py` — canonical JSON, create-exclusive publication,
  SHA-256 chain и manifest;
- `app/testing/f2_coordinator.py` — ordering, subprocess lifecycle,
  short-circuit и final status;
- `app/testing/f2_worker.py` — one-role/one-target process boundary;
- `scripts/run_test_db_f2.py` — тонкий operator-facing coordinator entrypoint.

Operational role adapters отделяются от coordinator protocol. Coordinator не
содержит PostgreSQL, Alembic или application-test business logic. Worker не
выбирает следующую роль и не может сменить target.

## 4. Roles и строгий порядок

```text
canonical
legacy_compatible
legacy_negative
```

Порядок является частью protocol version и не конфигурируется. Parallel run,
skip роли и продолжение после failure запрещены.

Каждая роль запускается новым Python-процессом. В процессе разрешён bind ровно
одного `DatabaseTarget`; reset/reconfigure hook отсутствует.

## 5. Parent environment contract

Coordinator получает secrets только через transient environment.

Общие inputs:

```text
WELDPASSPORT_F2_WORKING_DATABASE_URL
WELDPASSPORT_F2_EVIDENCE_DIR
WELDPASSPORT_F2_OPERATOR_AUTHORIZATION
WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES
```

Exact operator authorization:

```text
I_AUTHORIZE_TEST_DB_F2_LOCAL_REHEARSAL
```

Role-prefixed bundles:

```text
WELDPASSPORT_F2_CANONICAL_TEST_DATABASE_URL
WELDPASSPORT_F2_CANONICAL_DATABASE_CONFIRM
WELDPASSPORT_F2_CANONICAL_OWNERSHIP_TOKEN

WELDPASSPORT_F2_LEGACY_COMPATIBLE_TEST_DATABASE_URL
WELDPASSPORT_F2_LEGACY_COMPATIBLE_DATABASE_CONFIRM
WELDPASSPORT_F2_LEGACY_COMPATIBLE_OWNERSHIP_TOKEN

WELDPASSPORT_F2_LEGACY_NEGATIVE_TEST_DATABASE_URL
WELDPASSPORT_F2_LEGACY_NEGATIVE_DATABASE_CONFIRM
WELDPASSPORT_F2_LEGACY_NEGATIVE_OWNERSHIP_TOKEN
```

DSN, user, password, database name и ownership token запрещены в argv, logs,
exceptions и evidence.

## 6. Source и namespace reservation

До target validation coordinator:

1. получает exact `HEAD` SHA;
2. требует отсутствие staged/unstaged tracked changes;
3. не считает untracked files частью source state;
4. проверяет существующий внешний evidence root;
5. генерирует UUIDv4 `run_id`;
6. атомарно создаёт отсутствующий `<evidence-root>/<run_id>/`.

Symlink/reparse-point evidence root или run namespace запрещён. Existing
namespace не переиспользуется. Coordinator не удаляет namespace после ошибки.

## 7. Offline target preflight

Для каждого bundle вызывается существующий F1
`authorize_test_database(...)`. Ослабленная копия resolver запрещена.

До первого subprocess coordinator доказывает:

- exact destructive opt-in;
- exact confirmation имени;
- непустой ownership token;
- test-name/denylist contract;
- отсутствие normalized collision с working target;
- попарочную уникальность трёх test target identity;
- наличие всех трёх ролей без extras/duplicates.

Любая ошибка даёт `TEST_DB_F2_PRECHECK_FAILED`. Ни один worker не запускается.

## 8. Child environment

Parent environment целиком не наследуется. Coordinator строит новый mapping из:

- минимального Windows/Python runtime allowlist;
- безопасных `run_id`, role, source SHA и protocol version;
- exact output artifact path;
- одного generic F1 target bundle:
  `TEST_DATABASE_URL`, `WELDPASSPORT_TEST_DB_CONFIRM`,
  `WELDPASSPORT_TEST_DB_OWNERSHIP_TOKEN`,
  `WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS`;
- `WELDPASSPORT_F2_WORKING_DATABASE_URL` только для повторного вызова exact F1
  authorization внутри worker; значение остаётся transient, не попадает в
  argv, output или evidence;
- role-specific runtime profile.

Для `canonical` переменная `WELDPASSPORT_RUNTIME_PROFILE` отсутствует, чтобы
доказать фактический default. Для двух legacy-ролей передаются:

```text
WELDPASSPORT_RUNTIME_PROFILE=legacy_compatibility
WELDPASSPORT_LEGACY_SCHEMA=test
```

Worker argv содержит только module/command, role и `run_id`. Secret-bearing
values передаются только через child environment.

## 9. Worker protocol

Worker проверяет:

- exact protocol version;
- UUID `run_id`;
- одну допустимую role;
- соответствие role runtime profile;
- exact source SHA;
- отсутствующий output artifact.

Затем worker:

1. повторно выполняет F1 offline authorization своего generic bundle;
2. bind-ит target один раз до импорта `app.shared.db`/`app.main`;
3. перед первым operational действием вызывает существующий live ownership
   verifier;
4. требует exact `server_version_num = 180003`;
5. требует пустое начальное состояние;
6. вызывает ровно один role adapter;
7. закрывает все соединения;
8. create-exclusive публикует один result artifact.

Pure tests используют injected worker adapter и connection/process doubles.
Реальный PostgreSQL adapter не запускается в pure gate.

## 10. Role adapter contracts

### Canonical

- clean `alembic upgrade head`;
- exact current heads;
- `alembic check`;
- default canonical startup;
- workforce routes/metadata отсутствуют;
- exact canonical metadata;
- полный application suite.

### Legacy compatible

- canonical clean install/check;
- test-only compatible legacy fixture;
- successful explicit legacy startup;
- workforce router появляется после preflight;
- minimal read/write smoke;
- повторный canonical `alembic check`.

### Legacy negative

- canonical clean install;
- test-only fixture без одного обязательного constraint;
- startup завершается `LEGACY-CONTRACT-MISMATCH`;
- workforce router отсутствует;
- requests не обслуживаются;
- before/after catalog/data snapshots доказывают отсутствие runtime repair,
  DDL и DML.

Fixture builders принадлежат operational adapter layer, не runtime application.

## 11. Subprocess lifecycle

Coordinator использует injected `ProcessExecutor` contract:

```text
run(role, safe_argv, child_environment, timeout) -> ProcessResult
```

Требования:

- только последовательные blocking calls;
- exact timeout на роль;
- timeout не вызывает retry;
- stdout/stderr проходят redaction до диагностики;
- ненулевой exit code немедленно останавливает run;
- после process success coordinator требует exact result artifact;
- отсутствие, duplicate, malformed artifact или digest mismatch считается
  rehearsal failure.

Следующая роль не запускается до полной проверки artifact предыдущей.

## 12. Evidence contract

Run namespace содержит:

```text
00_preflight.json
10_canonical.json
20_legacy_compatible.json
30_legacy_negative.json
90_manifest.json         # только после трёх verified roles
99_failure.json          # best effort при failure
```

Каждый файл:

- создаётся create-exclusive;
- UTF-8 без BOM, LF;
- canonical JSON: sorted keys, compact separators, без NaN;
- digest считается по exact bytes;
- содержит protocol version, source SHA, `run_id`, UTC timestamps, role,
  safe gate results, `server_version_num`, previous artifact digest и собственный
  payload digest;
- не содержит connection coordinates, database name, DSN или tokens.

Target представлен stable identity digest, вычисленным из normalized identity
через domain-separated SHA-256. Digest не используется как credential.

Final manifest фиксирует ordered artifact names/digests и status
`TEST_DB_F2_REHEARSAL_VERIFIED`. Он создаётся только после трёх verified role
artifacts.

Machine outcomes:

- `TEST_DB_F2_PRECHECK_FAILED`;
- `TEST_DB_F2_REHEARSAL_FAILED`;
- `TEST_DB_F2_EVIDENCE_FAILED`;
- `TEST_DB_F2_REHEARSAL_VERIFIED`.

Для precheck/rehearsal failure coordinator best-effort публикует
`99_failure.json`, если evidence publisher остаётся доступен. При
`TEST_DB_F2_EVIDENCE_FAILED` authoritative failure artifact или manifest не
обещается: единственный допустимый результат — ненулевой exit и safe
diagnostic. Отсутствие authoritative final manifest никогда не трактуется как
verified.

`TEST_DB_F2_ACCEPTED` создаётся только отдельной owner-signature процедурой и не
является output runner.

## 13. Failure precedence

1. Невозможность безопасно опубликовать обязательный artifact:
   `TEST_DB_F2_EVIDENCE_FAILED`.
2. Ошибка до первого worker:
   `TEST_DB_F2_PRECHECK_FAILED`.
3. Worker/process/protocol/sub-gate failure:
   `TEST_DB_F2_REHEARSAL_FAILED`.
4. Только три verified роли:
   `TEST_DB_F2_REHEARSAL_VERIFIED`.

Runner не перезаписывает ранее созданный artifact, не откатывает DB, не удаляет
evidence и не продолжает цепочку.

## 14. Stable error codes

- `TEST-DB-F2-SOURCE-UNSAFE`;
- `TEST-DB-F2-AUTHORIZATION-MISSING`;
- `TEST-DB-F2-EVIDENCE-UNSAFE`;
- `TEST-DB-F2-TARGET-COLLISION`;
- `TEST-DB-F2-TARGET-NOT-EMPTY`;
- `TEST-DB-F2-VERSION-MISMATCH`;
- `TEST-DB-F2-WORKER-PROTOCOL`;
- `TEST-DB-F2-WORKER-TIMEOUT`;
- `TEST-DB-F2-ALEMBIC-FAILED`;
- `TEST-DB-F2-RUNTIME-FAILED`;
- `TEST-DB-F2-EVIDENCE-FAILED`.

F1 target/ownership codes сохраняются без переименования. Safe error не содержит
raw adapter exception или secret-bearing input.

## 15. Pure TDD matrix

Pure tests обязаны доказать:

- no connection/process call до полной проверки всех трёх bundles;
- exact role order и fresh process per role;
- bind-once target per worker;
- canonical profile variable отсутствует;
- legacy profile exact;
- parent environment не наследуется;
- secrets отсутствуют в argv, repr, logs, exceptions и JSON;
- collision с working и между любыми двумя test targets;
- missing/duplicate/extra role rejection;
- dirty tracked source rejection;
- unsafe evidence root/namespace rejection;
- UUIDv4 и create-exclusive reservation;
- short-circuit после каждой возможной role failure;
- timeout без retry;
- exact version gate;
- empty-state gate;
- malformed/missing/duplicate worker artifact rejection;
- canonical JSON determinism;
- create-exclusive publication;
- digest-chain mutation detection;
- evidence failure precedence;
- verified status невозможен без трёх exact artifacts;
- новый run не может использовать существующий namespace;
- AST/command governance запрещает create/drop/reset DB и wildcard discovery.

Обязательные финальные проверки:

```powershell
python -m pytest <focused TEST-DB-F2 pure tests> -q
python -m pytest migration_contract_tests -q
python -m compileall <changed Python files>
git diff --check
```

PostgreSQL, Alembic CLI и `tests/` suite в pure gate запрещены.

## 16. Разрешённый scope реализации

- новые узкие modules в `09_Разработка/backend/app/testing/`;
- новый thin script `09_Разработка/backend/scripts/run_test_db_f2.py`;
- focused tests только в `migration_contract_tests/`;
- `.env.example` только с commented variable names, без values/secrets;
- project closure docs после приёмки.

## 17. Запрещённый scope

- Alembic revisions/graph;
- domain models, services, repositories и API;
- изменение F1 safety contracts в сторону ослабления;
- изменение Runtime Compatibility contracts;
- развитие workforce;
- DB admin lifecycle или CI provider binding;
- автоматические retry/repair/cleanup;
- реальные DB/Alembic/application runs;
- secrets или connection coordinates в repository/evidence/output;
- stage, commit или push без соответствующего разрешения.

## 18. Acceptance criteria

Pure runner может получить только статус:

```text
IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED
```

До operational gates остаются истинными:

- ни одна PostgreSQL DB не открывалась;
- никакая DB не создавалась и не удалялась;
- Alembic/application suite не запускались;
- Foundation и Runtime Compatibility Profile не `ACCEPTED`;
- push выполняется только по отдельному разрешению.

## 19. Pure implementation closure

Дата: 2026-07-30

Результат: **IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED**.

Implementation commits:

- `5cee57a` — immutable protocol и transient parent environment;
- `dc85aec` — create-exclusive canonical evidence и digest chain;
- `a8bdd05` — полный offline source/target preflight;
- `8b18f6b` — minimal child environment и process isolation;
- `38f587a` — fixed-order coordinator и thin CLI;
- `048bcd9` — one-role worker и operational adapter boundary;
- `e7ed0dc` — review remediation: secret guard, operational handlers,
  dotenv isolation и expanded failure matrix.

Evidence:

- focused TEST-DB-F2 pure suite: `52 passed, 1 skipped`;
- полный `migration_contract_tests`: `790 passed, 3 skipped`;
- `compileall`, `git diff --check` и scope/security audit успешны;
- read-only review после remediation: `APPROVED`, открытых Critical/Important
  findings нет.

Pure closure не запускал PostgreSQL, Alembic CLI или application suite, не
создавал и не удалял БД и не является operational acceptance. Следующий
отдельный gate — `TEST-DB-F2-OPERATOR-PREFLIGHT`, после него требуется новое
разрешение на local PostgreSQL rehearsal.
