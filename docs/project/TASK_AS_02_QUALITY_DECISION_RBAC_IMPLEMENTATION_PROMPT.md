# Prompt — AS-02 QualityDecision RBAC Consolidation

## Роль исполнителя

Ты работаешь в `D:\WeldPassport` над AS-02 по принятому
[[docs/project/ADR-028-quality-decision-rbac-consolidation|ADR-028]].
Канонический пошаговый план:
[[docs/project/TASK_AS_02_QUALITY_DECISION_RBAC_IMPLEMENTATION_PLAN|AS-02 Implementation Plan]].

Работай строго по одному review gate за раз:

```text
Domain Model → Migration → Shared Authorization Resolver → Workflow → Service → API → Tests
```

После каждого gate остановись и представь владельцу:

- список изменённых файлов;
- diff;
- точные команды и результаты проверок;
- найденные риски;
- запрос на приёмку следующего gate.

## Цель

Закрыть три риска `QualityDecision`:

1. запретить отправителю последнего `SUBMIT` текущего review-cycle самостоятельно выполнять
   `RETURN` или `DECIDE`;
2. сохранять в каждом новом событии `QUALITY_DECISION_*` доказуемый immutable snapshot
   конкретного effective role assignment и scope;
3. выявлять совмещение `OGS_ENGINEER` + `OTK_INSPECTOR` для того же Joint как
   `QD_DUAL_ROLE_ASSIGNMENT`, не запрещая само HR-назначение.

## Разрешено

- менять только файлы, перечисленные в File map Implementation Plan;
- создать новую self-contained migration
  `20260724_27_qd_rbac_sod.py` после revision 26;
- добавить `review_submitted_by_worker_id` и `authorization_context`;
- добавить `AuthorizationGrant`, evidence-bearing resolver и совместимую оболочку;
- добавить `QD_SAME_ACTOR_REVIEW`;
- аддитивно расширить read-схемы и тесты;
- обновить canonical documentation только после технической приёмки;
- использовать только PostgreSQL для DB acceptance.

## Запрещено

- изменять migrations 25/26;
- менять authority/lifecycle/result/event-type контракты ADR-027;
- добавлять `CHIEF_WELDER` fallback;
- давать `COMPANY` или неразрешимому `SITE` write-authority;
- вводить глобальный HR role-conflict blocker или новый governance endpoint;
- переписывать другие quality-модули на новый resolver;
- выдумывать исторический scope/assignment из текущего HR-состояния;
- менять request body или URL команд;
- выполнять B-04, runtime profile, TEST-DB Foundation, 9D-4A-5, ProductionHold или
  Identity/Auth hardening;
- исправлять несвязанные legacy-проблемы;
- выполнять commit или push без отдельного подтверждения владельца.

## Обязательные инварианты

```text
DRAFT                               -> review_submitted_by_worker_id IS NULL
UNDER_REVIEW / DECIDED / SUPERSEDED -> review_submitted_by_worker_id IS NOT NULL
RETURN/DECIDE actor                 != review_submitted_by_worker_id
```

Grant selection:

```text
ENGINEERING_DOCUMENT > LINE > PROJECT > GLOBAL
tie -> minimum WorkerRole.id
```

Новые события имеют:

```text
authorization_snapshot_status = VERIFIED
policy_result = AUTHORIZED
```

Исторические события имеют:

```text
authorization_snapshot_status = LEGACY_AUTHORIZATION_SNAPSHOT
```

и не получают недоказанные scope/assignment/validity.

## Порядок выполнения команды

Сохрани существующую idempotency-семантику. Для нового запроса:

1. visibility;
2. idempotency replay/conflict;
3. effective role assignment;
4. state/input validation;
5. expected version;
6. person-level SoD;
7. transition + audit + idempotency record;
8. одна транзакция.

## Критерии приёмки

- migration graph имеет ровно один head: revision 27;
- оба существующих `EXPECTED_HEAD` синхронизированы;
- pure migration governance suite проходит;
- backfill доказывает последнего submitter либо останавливает migration;
- один dual-role worker может `SUBMIT`, но не может сам `RETURN`/`DECIDE`;
- другой effective OTK может выполнить обе команды;
- `RETURN` очищает submitter, новый `SUBMIT` создаёт новый цикл;
- все пять событий получают корректный context;
- supersede использует authorization исходного `DECIDE`;
- idempotency replay не создаёт повторных эффектов;
- конкурентные команды не обходят SoD;
- HTTP возвращает `409 QD_SAME_ACTOR_REVIEW`;
- focused и full regression suites проходят;
- PostgreSQL downgrade/upgrade rehearsal выполняется только на disposable TEST-DB;
- документация синхронизируется только после свежей технической приёмки.

## Первый разрешённый execution gate

Начни только с **Task 1: Domain Model and pure SoD rule** из Implementation Plan.
Не создавай migration и не переходи к resolver/service/API до отдельной приёмки Task 1.

