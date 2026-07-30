# ADR-033. TEST-DB-F2 Local Isolated PostgreSQL Rehearsal

Дата: 2026-07-30

Статус: **ACCEPTED**

Связанные решения:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]];
- [[docs/project/ADR-029-test-db-safety-interlock|ADR-029]];
- [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032]];
- [[docs/project/TASK_TEST_DB_FOUNDATION_SPEC|TEST-DB-FOUNDATION]];
- [[docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC|RUNTIME-LEGACY-COMPATIBILITY-PROFILE]].

## Контекст

`TEST-DB-F1` реализован и зафиксирован commit
`20c7ea701a059fae3c207777f81aa068a99793ab` со статусом
`IMPLEMENTED_UNVERIFIED / CODE ACCEPTED`. Он предоставляет pure fail-closed
target/bootstrap/ownership contracts, но не подтверждает работу на PostgreSQL.

Следующий operational gate должен доказать clean install, canonical runtime и
legacy compatibility только на owned disposable PostgreSQL. Локальный rehearsal
не должен автоматически создавать или удалять DB. CI create/drop и привязка
`WELDPASSPORT_TEST_DB_ADMIN_URL` остаются отдельным будущим gate
`TEST-DB-F2-CI-BINDING`.

Operational execution зависит от принятой и зафиксированной реализации
`RUNTIME-COMPAT-1`. До этого разрешены только архитектура и pure tooling.

## Рассмотренные варианты

### A. Coordinator и три независимых worker-процесса

Каждый sub-gate получает отдельную заранее созданную owned DB и запускается в
свежем процессе. Coordinator проверяет общие инварианты, управляет
последовательностью и связывает immutable evidence.

Вариант принят: он сохраняет bind-once `DatabaseTarget`, физически разделяет
canonical/positive/negative состояния и даёт единый fail-closed evidence
contract.

### B. Три независимые ручные команды

Вариант отклонён как основной: он уменьшает объём tooling, но повышает риск
ошибки порядка, различий environment и разрозненного evidence. Ручные команды
могут существовать только как operator-facing wrapper над теми же worker
entrypoints.

### C. Один процесс с переключением DB

Вариант отклонён: он нарушает immutable bind-once target и создаёт путь к
неявному reconfigure/fallback.

## Решение

### 1. Gate и prerequisites

Gate называется `TEST-DB-F2-LOCAL-REHEARSAL`.

До operational preflight обязательны:

1. принятый и зафиксированный `TEST-DB-F1`;
2. принятый и зафиксированный `RUNTIME-COMPAT-1`;
3. принятый pure `TEST-DB-F2-PURE-RUNNER`;
4. независимый read-only review и remediation pure tooling;
5. отдельное разрешение владельца на operator preflight;
6. после preflight — отдельное разрешение на PostgreSQL rehearsal.

Архитектурная приёмка не разрешает подключение, Alembic, application tests,
создание/удаление DB, stage, commit или push.

### 2. Target topology

Оператор заранее создаёт три разные owned disposable DB:

```text
canonical
legacy_compatible
legacy_negative
```

Для каждой DB обязательны:

- отдельный `TEST_DATABASE_URL`;
- exact `WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES`;
- exact confirmation имени;
- уникальный server-side ownership marker;
- имя, проходящее F1 test-name/denylist contract;
- normalized identity, отличная от working target и двух других test targets;
- пустое начальное состояние без пользовательских relations и
  `alembic_version`;
- точный `server_version_num = 180003`, равный активному B-04 evidence
  (PostgreSQL 18.3).

Working DB только разбирается pure resolver для collision check и никогда не
подключается. DSN и tokens передаются только через transient environment, не
через argv, repository, report или exception.

### 3. Coordinator boundary

До первого соединения coordinator:

1. резервирует уникальный `run_id` и внешний evidence namespace;
2. проверяет source SHA и отсутствие staged/unstaged tracked changes;
3. проверяет prerequisites и operator authorization;
4. pure-валидирует все три target/confirmation/token bundles;
5. доказывает попарочную уникальность test targets и отсутствие working
   collision;
6. формирует redacted child environments.

После успешного общего preflight coordinator последовательно запускает три
свежих worker-процесса. Каждый worker bind-ит ровно один `DatabaseTarget`.
Параллельный запуск и смена target запрещены.

Ошибка останавливает текущий и все последующие sub-gates. DB следующих ролей
после ошибки не открываются.

### 4. Общий live gate worker

Первое соединение worker направляется только к уже прошедшему offline gate
target. До Alembic, fixture, session или startup read-only проверяются:

- `current_database()` и server-reported endpoint;
- exact ownership marker;
- exact PostgreSQL `server_version_num`;
- пустое начальное состояние DB.

Несовпадение завершает worker fail closed. F1-коды target/ownership
переиспользуются; повторная реализация ослабленного live gate запрещена.

### 5. Canonical sub-gate

На DB `canonical` выполняются:

1. clean `alembic upgrade head`;
2. exact `current == heads`;
3. успешный `alembic check`;
4. startup при отсутствующем `WELDPASSPORT_RUNTIME_PROFILE`, доказывающий
   настоящий default `canonical`;
5. проверка отсутствия workforce routes и legacy metadata;
6. exact canonical metadata contract;
7. полный application suite.

### 6. Compatible legacy sub-gate

На независимой DB `legacy_compatible` выполняются:

1. canonical clean install и Alembic checks;
2. test-only fixture вне runtime создаёт compatible legacy schema;
3. explicit `legacy_compatibility` проходит read-only preflight;
4. workforce router появляется только после успешного preflight;
5. минимальный read/write smoke;
6. повторный `alembic check` доказывает, что canonical Alembic не видит
   `LegacyBase.metadata`.

Runtime не создаёт, не исправляет и не обновляет legacy fixture.

### 7. Negative legacy sub-gate

На независимой DB `legacy_negative` выполняются:

1. canonical clean install;
2. test-only fixture создаёт controlled incompatibility — отсутствие
   обязательного constraint;
3. explicit `legacy_compatibility` завершается
   `LEGACY-CONTRACT-MISMATCH`;
4. workforce router не подключается, приложение не обслуживает запросы;
5. catalog/data snapshots до и после startup подтверждают отсутствие repair,
   DDL и DML со стороны runtime.

Pure test matrix покрывает остальные классы несовместимости; operational gate
не превращается в полную live-матрицу отрицательных fixtures.

### 8. Evidence contract

Каждый завершённый шаг публикует отдельный canonical JSON artifact. Файлы:

- создаются только create-exclusive;
- пишутся в заранее существующий внешний каталог вне repository/worktrees;
- никогда не перезаписываются;
- связываются SHA-256 digests в строгом порядке
  `canonical → legacy_compatible → legacy_negative`.

Evidence содержит source SHA, `run_id`, UTC timestamps, роль DB, PostgreSQL
`server_version_num`, безопасные codes и результаты gates. Запрещены DSN, host,
port, user, password, database name и ownership token. Target представлен
stable identity digest.

Итоговые machine statuses:

- `TEST_DB_F2_PRECHECK_FAILED`;
- `TEST_DB_F2_REHEARSAL_FAILED`;
- `TEST_DB_F2_REHEARSAL_VERIFIED`.

Machine report не присваивает `ACCEPTED`. После независимого read-only review
владелец может create-exclusive подписать отдельный
`TEST_DB_F2_ACCEPTED`, ссылающийся на exact final manifest digest. Только эта
подпись переводит TEST-DB Foundation и Runtime Compatibility Profile в
`ACCEPTED`.

### 9. Failure and rerun policy

Автоматические retry, repair, migration rollback и продолжение со следующего
sub-gate запрещены. После успеха или ошибки:

- соединения закрываются;
- все три DB и ownership markers сохраняются;
- runner не создаёт, не удаляет, не переименовывает и не reset-ит DB;
- частично изменённая DB не переиспользуется для acceptance.

Новый run требует новый `run_id` и новую полную тройку пустых owned DB. Вся
цепочка начинается заново с `canonical`. Старые DB удаляются только отдельным
операторским действием после проверки evidence.

Стабильные F2-коды:

- `TEST-DB-F2-SOURCE-UNSAFE`;
- `TEST-DB-F2-TARGET-COLLISION`;
- `TEST-DB-F2-TARGET-NOT-EMPTY`;
- `TEST-DB-F2-VERSION-MISMATCH`;
- `TEST-DB-F2-ALEMBIC-FAILED`;
- `TEST-DB-F2-RUNTIME-FAILED`;
- `TEST-DB-F2-EVIDENCE-FAILED`.

Ошибка публикации evidence не может дать verified/accepted status.

### 10. Delivery decomposition

```text
TEST-DB-F2-A architecture
→ RUNTIME-COMPAT-1 pure implementation
→ TEST-DB-F2-PURE-RUNNER
→ independent review and remediation
→ accepted implementation commit
→ TEST-DB-F2-OPERATOR-PREFLIGHT
→ separate PostgreSQL authorization
→ TEST-DB-F2-LOCAL-REHEARSAL
→ evidence review
→ owner TEST_DB_F2_ACCEPTED
```

Pure runner TDD обязан доказать:

- отсутствие соединений до полной проверки трёх targets;
- fresh subprocess и bind-once для каждой роли;
- отсутствие secrets в argv/logs/exceptions/evidence;
- short-circuit после первого сбоя;
- запрет create/drop/reset DB и wildcard discovery;
- exact version gate;
- create-exclusive event journal и digest chain;
- fail-closed publication;
- требование новой полной тройки DB для нового run.

Pure implementation не запускает PostgreSQL, Alembic или application suite.

## Последствия

Положительные:

- canonical, compatible и negative evidence физически изолированы;
- bind-once target сохраняется без reset hooks;
- local rehearsal не требует административного `CREATEDB`;
- DB остаются доступны для расследования;
- machine verification и owner acceptance строго разделены.

Отрицательные:

- оператор заранее готовит три DB для каждого run;
- любой сбой требует новой полной тройки;
- patch-upgrade PostgreSQL требует нового F2 evidence;
- operational acceptance заблокирован до `RUNTIME-COMPAT-1`.

## Вне scope

- `TEST-DB-F2-CI-BINDING` и CI provider/workflow;
- автоматический local create/drop;
- подключение к working/production DB;
- изменение Alembic revision graph или `canonical_baseline_v1`;
- domain/API changes и развитие workforce;
- автоматический repair legacy schema;
- удаление rehearsal DB;
- actual PostgreSQL run, stage, commit и push без отдельных разрешений.
