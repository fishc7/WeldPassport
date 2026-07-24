# ADR-028 — QualityDecision RBAC Consolidation

**Дата:** 2026-07-24  
**Статус:** ACCEPTED  
**Статус реализации:** IMPLEMENTED / VERIFIED 2026-07-24  
**Контур:** AS-02 / QualityDecision person-level SoD / authorization evidence  
**Основание:** ADR-024, ADR-027, Task 10A Recovery Addendum

## A. Контекст

Task 10A реализовал `QualityDecision` с ролевым разделением:

- `OGS_ENGINEER` создаёт, редактирует и отправляет решение;
- `OTK_INSPECTOR` возвращает или принимает решение;
- `CHIEF_WELDER` не участвует и не является fallback.

После завершения Task 10A аудит AS-02 подтвердил три остаточных риска:

1. разделение действует по ролям, но один работник с двумя ролями может выполнить обе
   стороны review;
2. `quality_audit_events` не хранит доказуемый снимок конкретного назначения роли и scope;
3. совмещение `OGS_ENGINEER` и `OTK_INSPECTOR` не выявляется как governance-риск.

ADR-028 закрывает эти риски, не меняя authority-модель ADR-027 и не создавая общий
policy engine для всех модулей.

## B. Решение

### B.1. Person-level separation of duties

Независимость определяется относительно отправителя **текущего цикла review**, а не
первоначального создателя:

```text
actor_worker_id != review_submitted_by_worker_id
```

Работник, выполнивший последний `SUBMIT`, не может выполнить ни `RETURN`, ни `DECIDE`
в том же цикле. Нарушение возвращает `409 QD_SAME_ACTOR_REVIEW`.

В `quality.quality_decisions` вводится nullable-поле
`review_submitted_by_worker_id` без FK, по действующей конвенции исторических actor-полей:

- `CREATE` / `UPDATE_DRAFT`: `NULL`;
- `SUBMIT`: устанавливается в `actor_worker_id`;
- `RETURN`: очищается после записи предыдущего значения в audit;
- следующий `SUBMIT`: устанавливается в нового отправителя;
- `DECIDE` и последующий `SUPERSEDED`: сохраняется.

DB-инвариант:

```text
DRAFT                                      -> review_submitted_by_worker_id IS NULL
UNDER_REVIEW / DECIDED / SUPERSEDED        -> review_submitted_by_worker_id IS NOT NULL
```

Проверка `RETURN`/`DECIDE` выполняется после row lock, проверки effective authority,
состояния и `expected_version`, в той же транзакции, что переход и audit.

### B.2. Доказуемое предоставленное полномочие

`shared.permissions` получает неизменяемый value object `AuthorizationGrant`, содержащий:

- `actor_worker_id`;
- `actor_role_code`;
- `worker_role_assignment_id`;
- `scope_type` / `scope_id`;
- `role_valid_from` / `role_valid_to`.

Новый resolver возвращает конкретные effective `WorkerRole`, покрывающие Joint.
Существующая функция `worker_role_codes_for_joint` сохраняется как совместимая оболочка.

Если Joint покрывают несколько назначений одной роли, выбор детерминирован:

```text
ENGINEERING_DOCUMENT > LINE > PROJECT > GLOBAL
```

При одинаковой специфичности выбирается минимальный `WorkerRole.id`.
`COMPANY` не предоставляет write-authority командам `QualityDecision`; `SITE` не
предоставляет authority, пока физическая связь SITE → Joint отсутствует.

### B.3. Immutable authorization context

В `quality.quality_audit_events` вводится nullable JSONB
`authorization_context`. Для всех событий `entity_type = QUALITY_DECISION` оно обязательно.

Новый успешный mutating event сохраняет:

```json
{
  "schema_version": 1,
  "authorization_snapshot_status": "VERIFIED",
  "policy_result": "AUTHORIZED",
  "action": "DECIDE",
  "actor_worker_id": 123,
  "actor_role_code": "OTK_INSPECTOR",
  "worker_role_assignment_id": 456,
  "scope_type": "PROJECT",
  "scope_id": "uuid-or-null",
  "role_valid_from": "2026-01-01",
  "role_valid_to": null,
  "checked_at": "server-timestamptz",
  "project_id": "uuid",
  "joint_id": "uuid",
  "governance_warnings": []
}
```

Снимок обязателен для `CREATED`, `SUBMITTED`, `RETURNED`, `DECIDED` и системного
`SUPERSEDED`; последний использует полномочие исходной команды `DECIDE`.
Неуспешный запрос не создаёт доменное событие. Невозможность сформировать полный снимок
для успешной команды откатывает транзакцию.

Исторические события получают только честный:

```json
{
  "schema_version": 1,
  "authorization_snapshot_status": "LEGACY_AUTHORIZATION_SNAPSHOT",
  "actor_worker_id": 123,
  "actor_role_code": "role-if-recorded"
}
```

Исторические assignment/scope/validity не реконструируются из текущего HR-состояния.

### B.4. Совмещение ролей

Одновременное назначение `OGS_ENGINEER` и `OTK_INSPECTOR` не блокируется. Если обе
effective-роли покрывают тот же Joint, новый snapshot содержит:

```json
{"governance_warnings": ["QD_DUAL_ROLE_ASSIGNMENT"]}
```

Предупреждение не даёт дополнительных полномочий и не отменяет person-level SoD.
Глобальный HR-запрет и отдельный административный endpoint в AS-02 не входят.

## C. Миграция и совместимость

Создаётся новая self-contained revision после `20260724_26_qd_idempotency`; revisions
25/26 не изменяются.

Upgrade:

1. добавить обе nullable-колонки;
2. восстановить `review_submitted_by_worker_id` для `UNDER_REVIEW`/`DECIDED`/
   `SUPERSEDED` по `QUALITY_DECISION_SUBMITTED` с наибольшей сохранённой `version`;
3. остановить миграцию, если отправитель недоказуем;
4. заполнить historical authorization context статусом
   `LEGACY_AUTHORIZATION_SNAPSHOT`;
5. добавить DB CHECK состояния и обязательности context для QualityDecision events.

Публичные command URL и request body не меняются. В read-схемы аддитивно добавляются:

- `QualityDecisionRead.review_submitted_by_worker_id: int | None`;
- `QualityDecisionEventRead.authorization_context: dict | None`.

Старые idempotency response snapshots не переписываются и могут вернуть новое поле как
`null`; новые snapshots сохраняют поле. Статусы, результаты, роли и пять event types не
изменяются.

## D. Порядок ошибок

1. невидимый объект — `404`;
2. отсутствующая effective authority — `403`;
3. idempotency/state/version/SoD conflict — `409`;
4. неверное значение команды — `422`.

SoD проверяется только для видимого объекта и actor с требуемой effective-role.
При stale `expected_version` возвращается version conflict до SoD.

## E. Границы

Входит: domain invariant, correcting migration, grant resolver, QualityDecision service,
audit context, additive API fields, migration/domain/service/API/concurrency tests и
синхронизация документации.

Не входит: изменение authority ADR-027, `CHIEF_WELDER` fallback, глобальная матрица
несовместимых ролей, HR blocking, новый governance endpoint, аутентификация вместо
`X-User-Id`, остальные quality-агрегаты, B-04/runtime profile/TEST-DB/9D-4A-5.

`X-User-Id` остаётся отдельным риском Identity/Auth; ADR-028 усиливает authorization и
evidence, но не изображается решением аутентификации.

## F. Последствия

Положительные:

- один человек не может выполнить обе стороны review;
- audit доказывает конкретное полномочие на момент действия;
- dual-role staffing остаётся возможным, но явно отмечается;
- существующие permission-consumers не требуют массового рефакторинга.

Стоимость:

- новая миграция и два поля;
- QualityDecision service должен работать с grant, а не только с кодом роли;
- исторические события остаются честно маркированными как legacy.

## G. Приёмка

Решение принимается только после раздельных gate:

1. Domain Model;
2. Migration;
3. Shared Authorization Resolver;
4. Workflow;
5. Service;
6. API;
7. финальные tests/documentation.

Точный порядок и команды проверки:
[[docs/project/TASK_AS_02_QUALITY_DECISION_RBAC_IMPLEMENTATION_PLAN|AS-02 Implementation Plan]].
Точный execution prompt:
[[docs/project/TASK_AS_02_QUALITY_DECISION_RBAC_IMPLEMENTATION_PROMPT|AS-02 Implementation Prompt]].

## H. Implementation evidence

Реализация завершена 2026-07-24:

- self-contained revision `20260724_27_qd_rbac_sod` следует за revision 26; revisions
  25/26 не изменены;
- PostgreSQL-схема `test` приняла revision 27; репетиция `27 → 26 → 27` подтвердила
  симметричное удаление и восстановление двух колонок и двух CHECK-ограничений;
- migration governance: `35 passed`;
- AS-02 focused regression: `100 passed`;
- полный backend regression: `1590 passed`;
- API, idempotency, concurrency, person-level SoD, dual-role warning и immutable
  authorization evidence покрыты тестами.
