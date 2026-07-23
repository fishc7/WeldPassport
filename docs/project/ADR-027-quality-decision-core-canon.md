# ADR-027 — QualityDecision Core Canon (Task 10A)

Дата: 2026-07-23 (v1) / 2026-07-23 (v2) / 2026-07-23 (ACCEPTED)

Статус: **ACCEPTED**

Дата принятия: 2026-07-23.

Принято владельцем непосредственно перед стартом Task 10A Implementation Block 1
(Models + Migration), с явным решением по открытым точкам §K, необходимым для схемы БД
блока 1 (Q-D1, Q-D2, Q-D8 — см. «Решение по открытым точкам ACCEPTED» ниже). Q-D5
(Idempotency-Key) и Q-D9 (правка `DRAFT`) не относятся к моделям/миграции и остаются
открытыми до Block 2 (Services/API).

**Уточнение Q-D2 (Block 1 Correction, 2026-07-23, после архитектурного review).** Первая
редакция Block 1 ошибочно реализовала Q-D2 как partial unique `UNIQUE(joint_id) WHERE
status IN ('DRAFT','UNDER_REVIEW')` («не более одной открытой версии на Joint»). Это не
соответствовало принятому решению. Уточнённое решение Q-D2: ограничение по количеству на
один `Joint` действует **только** для `DECIDED` (не более одной записи одновременно —
`UNIQUE(joint_id) WHERE status = 'DECIDED'`, без изменений). `DRAFT` и `UNDER_REVIEW`
количеством на `Joint` **не ограничиваются** — допускается несколько `DRAFT` и/или
несколько `UNDER_REVIEW` одновременно на один `Joint`. Ошибочный индекс удалён из модели и
миграции Block 1 корректирующим изменением того же (ещё не закоммиченного) Block 1.

Документ подготовлен исполнителем по прямому запросу владельца в рамках Task 10A. v2
включал корректировки владельца по итогам review v1.

## Решение по открытым точкам ACCEPTED (2026-07-23, Q-D2 уточнено тем же днём)

| № | Вопрос | Решение владельца |
|---|---|---|
| Q-D1 | `EngineeringEvaluationRevision`-основание должно иметь статус `EFFECTIVE` на момент `CREATE`/`SUBMIT_FOR_REVIEW`? | **Да** — обязательна. Проверка — service-level (Block 2), не CHECK. |
| Q-D2 | Ограничивать ли количество `QualityDecision` на `Joint` по статусу? | **Только `DECIDED`** — `UNIQUE(joint_id) WHERE status = 'DECIDED'`. `DRAFT`/`UNDER_REVIEW` — без ограничения количества на `Joint` (уточнено после review; исходная редакция ACCEPTED ошибочно добавляла ограничение и для `DRAFT`/`UNDER_REVIEW`). |
| Q-D8 | `RETURNED` — атомарная команда `RETURN` (`UNDER_REVIEW → DRAFT`, без отдельного статуса) или отдельный 5-й статус `RETURNED` + `REOPENED`? | **Атомарный `RETURN`** — ровно 4 персистентных статуса (`DRAFT`/`UNDER_REVIEW`/`DECIDED`/`SUPERSEDED`), как в §D. |
| Q-D5 | `Idempotency-Key` для мутирующих команд? | Не рассмотрено сейчас — не влияет на модели/миграцию; решить перед Block 2 (Services/API). |
| Q-D9 | API правки `DRAFT` без отдельного audit-события? | Не рассмотрено сейчас — не влияет на модели/миграцию; решить перед Block 2 (Services/API). |

Q-D3, Q-D4, Q-D6, Q-D7 из v1 — закрыты решением владельца в v2 (см. «Изменения v2» ниже),
без изменений при принятии ACCEPTED.

Контур: Quality / QualityDecision governance.

Опирается на: [[docs/project/DECISIONS#ADR-021. EngineeringEvaluation Core Canon (Task 9D-2)|ADR-021]] ·
[[docs/project/DECISIONS#ADR-022. Defect Technical Model (Task 9D-3)|ADR-022]] ·
[[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024]] (конвенции
authority/audit/lifecycle, используемые как образец) ·
[[docs/project/ADR-006-domain-ownership-matrix|ADR-006]] (владение доменами).

Уточняет границу (не отменяет): [[docs/project/DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019]].
ADR-019 остаётся в силе целиком, включая решение 008-07-BQ о том, что «Quality Decision» как
исторический термин Session 008 (ADR-017) был декомпозирован и не является единой сущностью.
ADR-027 не отменяет это решение и не восстанавливает старую модель ADR-017. ADR-027 вводит
**новый**, отдельно поименованный объект `QualityDecision` — официальное решение по
результатам одной или нескольких `EngineeringEvaluationRevision`, отсутствовавшее в каноне
ADR-019/021/022/024 как самостоятельный шаг. Соответственно, остальные положения ADR-019
(`QualityFinding`, lifecycle и роли `EngineeringEvaluation`, историческая
`FindingDisposition` → `DefectDisposition` по ADR-024, `ProductionHold`,
`CustomerQualityDecision`, `CorrectiveActionLink`) не изменяются.

Task: Task 10A (вне канона `TASK_REGISTRY.md`; после `ACCEPTED` требует отдельной строки в
`TASK_REGISTRY.md` и `PROJECT_STATUS.yaml`).

---

## Изменения v2 относительно v1 (по решению владельца)

1. Явно зафиксировано: `QualityDecision` не является переименованием `DefectDisposition`,
   не заменяет `EngineeringEvaluation`, не является возвратом модели `Quality Decision` из
   ADR-017/ADR-019.
2. Связь с `EngineeringEvaluation` — не M:N напрямую. Введён промежуточный объект
   `DecisionBasis`, ссылающийся на конкретную `EngineeringEvaluationRevision` (не на header
   `EngineeringEvaluation`). Добавлен инвариант: одна `EngineeringEvaluationRevision` не может
   быть основанием более чем одного `DECIDED` `QualityDecision` одновременно.
3. Роли подтверждены без изменений (`WELDING_ENGINEER` / `OTK_INSPECTOR`, `CHIEF_WELDER` не
   участвует) — с явной причиной: «`QualityDecision` — независимое решение качества, а не
   производственное решение исполнения».
4. Аудит — только `quality_audit_events`; отдельная таблица не создаётся ни под именем
   `QualityDecisionEvent`, ни под именем `QualityDecisionHistory` (альтернатива из v1 §K
   отклонена). Зафиксирован закрытый список из пяти `event_type`.
5. Supersede — без статуса `ACTIVE`. При появлении нового `DECIDED` для того же `Joint` в
   одной транзакции: старый `DECIDED` → `SUPERSEDED`, новый → `DECIDED`.
6. Упрощён набор команд MVP (см. §D) до минимума, покрытого закрытым списком событий из
   пункта 4: убраны как отдельные аудируемые команды `UPDATE_DRAFT`, `LINK/UNLINK_EVALUATION`,
   `REOPEN`, `CANCEL`, присутствовавшие в v1. Обоснование — §D, сноска.

## A. Проблема и контекст (без изменений от v1)

Task 10A запросил `QualityDecision` как отдельную сущность, сославшись на «уже согласованный»
`ADR-027`, которого не существовало. Действующий канон (`ADR-019`, `ACCEPTED`) прямо
декомпозировал исторический термин «Quality Decision» и объявил его небудущей самостоятельной
сущностью (008-07-BQ). Рассмотрены и отклонены три альтернативы разместить функцию Task 10A
без новой сущности:

- `CustomerQualityDecision` (9D-5, planned) — не подходит: внешнее решение, без ролей
  `WELDING_ENGINEER`/`OTK_INSPECTOR` как исполнителей внутреннего workflow;
- доработка approval-шага `EngineeringEvaluation` — не подходит: означала бы изменение уже
  принятого и реализованного lifecycle/ролей ADR-021 (Task 9D-2, done);
- `DefectAcceptanceAssessment` (ADR-019/022, нереализован) — не подходит по кардинальности:
  оценивает приемлемость **после** подтверждения `Defect`, а `QualityDecision` работает
  **до** появления `Defect`.

Вывод v1, подтверждённый владельцем в v2: `QualityDecision` — новая сущность, размещённая
**над** `EngineeringEvaluation` и **перед** `Defect`, без изменения смежных контуров.

## B. Место в цепочке и границы объектов

```text
Joint → WeldOperation → Inspection → InspectionResult → QualityFinding
  → EngineeringEvaluation → EngineeringEvaluationRevision (что установлено)
  → QualityDecision (какое официальное решение принято, на основании ≥1 EE-ревизии)
  → Defect (если DEFECT_CONFIRMED — какое конкретное несоответствие зарегистрировано)
  → DefectDisposition (что делать с подтверждённым дефектом, ADR-024)
  → Repair
```

`QualityDecision` **не является** `EngineeringEvaluation`, **не является**
`DefectDisposition`, **не является** документом. Не переопределяет lifecycle, роли или данные
`EngineeringEvaluation`.

## C. Сущность и связи (изменено в v2)

### `quality.quality_decisions`

| Поле | Тип | Комментарий |
|---|---|---|
| `id` | UUID PK | |
| `joint_id` | UUID FK → `engineering.joints`, `RESTRICT` | `QualityDecision` принадлежит одному `Joint` |
| `project_id` | UUID FK → `project.projects` | Для нумерации и scope |
| `number` | text, unique per project | `<PROJECT_CODE>-QD-<SEQUENCE>` |
| `status` | text + CHECK | `DRAFT` / `UNDER_REVIEW` / `DECIDED` / `SUPERSEDED` (см. сноску §D о `RETURNED`) |
| `result` | text + CHECK, nullable до `DECIDED` | `ACCEPTED` / `NOT_CONFIRMED` / `DEFECT_CONFIRMED` |
| `summary` | text, обязателен при `SUBMIT_FOR_REVIEW` | Содержательная часть решения |
| `return_reason` | text, nullable | Заполняется командой `RETURN` |
| `supersedes_quality_decision_id` | UUID FK → себе, nullable | Заполняется системой в момент `DECIDE`, если у `Joint` уже был `DECIDED` (см. §G); не указывается вручную при создании |
| `created_by_worker_id` | integer, `NOT NULL`, без FK (конвенция проекта) | |
| `created_at` | timestamptz | |
| `approved_by_worker_id` | integer, nullable | Заполняется только при `DECIDE` |
| `approved_at` | timestamptz, nullable | |
| `approved_role` | text, nullable | Снимок role_code (`OTK_INSPECTOR`) |
| `version` | integer | Optimistic lock |

### `quality.quality_decision_bases` (заменяет M:N из v1)

```text
QualityDecision (1) → (N) DecisionBasis (N) → (1) EngineeringEvaluationRevision
```

| Поле | Тип | Комментарий |
|---|---|---|
| `id` | UUID PK | |
| `quality_decision_id` | UUID FK → `quality_decisions`, `RESTRICT` | |
| `engineering_evaluation_revision_id` | UUID FK → `quality.engineering_evaluation_revisions`, `RESTRICT` | Ссылка на конкретную ревизию, а не на header `EngineeringEvaluation` |
| `is_basis_of_decided` | boolean, `NOT NULL DEFAULT false` | `true`, только пока владеющий `QualityDecision.status = 'DECIDED'`; см. §F.3 |
| `linked_by_worker_id` | integer | |
| `linked_at` | timestamptz | |

Правила (по требованию владельца):

- `QualityDecision` требует минимум одной `DecisionBasis` — проверяется на `CREATE`;
- допускается несколько оснований (одна `QualityDecision` может ссылаться на несколько
  `EngineeringEvaluationRevision`, в том числе от разных `QualityFinding` того же `Joint`);
- валидация на уровне сервиса: каждая указанная `EngineeringEvaluationRevision` должна
  принадлежать тому же `Joint` (через `revision.evaluation.finding.joint_id ==
  quality_decision.joint_id`);
- **новый инвариант v2:** одна `EngineeringEvaluationRevision` не может быть основанием
  более чем одного `DECIDED` `QualityDecision` одновременно (механизм — §F.3).

Открытый вопрос (перенесён из v1 Q-D1, теперь узкий): требовать ли, чтобы указанная
`EngineeringEvaluationRevision` на момент `CREATE`/`SUBMIT_FOR_REVIEW` имела статус `EFFECTIVE`
(а не `DRAFT`/`PREPARED`/`FIXED`/`SUPERSEDED`)? Рекомендация без изменений: **да** — решение
не может опираться на незафиксированную или устаревшую техническую оценку. Требует
подтверждения (см. §K, Q-D1).

## D. Lifecycle и authority (упрощено в v2)

| From | Command | To | Role | Preconditions | Audit `event_type` |
|---|---|---|---|---|---|
| — | `CREATE` | `DRAFT` | `WELDING_ENGINEER` | `Joint` видим в scope; ≥1 `DecisionBasis` (EFFECTIVE-ревизии, см. §C); `summary` может быть пуст | `QUALITY_DECISION_CREATED` |
| `DRAFT` | `SUBMIT_FOR_REVIEW` | `UNDER_REVIEW` | `WELDING_ENGINEER` | `summary` заполнен; состав `DecisionBasis` на момент отправки фиксируется в событии | `QUALITY_DECISION_SUBMITTED` |
| `UNDER_REVIEW` | `RETURN` | `DRAFT` | `OTK_INSPECTOR` | `return_reason` обязателен | `QUALITY_DECISION_RETURNED` |
| `UNDER_REVIEW` | `DECIDE` | `DECIDED` | `OTK_INSPECTOR` | `result` передан; под lock `Joint` — если уже есть `DECIDED`, он атомарно → `SUPERSEDED` (см. §G) | `QUALITY_DECISION_DECIDED` (+ `QUALITY_DECISION_SUPERSEDED` для замененной записи, если была) |

**Сноска про `RETURNED`.** Task 10A описывает цепочку `UNDER_REVIEW → RETURNED → DRAFT`.
Закрытый список из пяти событий v2 не содержит отдельного `REOPENED`. Чтобы не вводить лишнюю
команду/событие сверх заданного списка, `RETURNED` реализуется **не как отдельный
персистентный статус**, а как единственная атомарная команда `RETURN`, которая сразу переводит
`UNDER_REVIEW → DRAFT` и оставляет след `QUALITY_DECISION_RETURNED` в audit trail (семантика
«возвращено на доработку» видна по типу события, а не по промежуточному значению `status`).
Итоговый набор персистентных статусов — 4 значения: `DRAFT`, `UNDER_REVIEW`, `DECIDED`,
`SUPERSEDED`. Это отличие от v1 (там `RETURNED` был отдельным статусом с отдельной командой
`REOPEN`). Требует подтверждения (см. §K, Q-D8) — альтернатива: сохранить `RETURNED` как 5-й
персистентный статус и добавить `REOPENED` как шестое, не входящее в исходный список, событие.

**Сноска про редактирование `DRAFT` и состав оснований.** v1 предполагал отдельные команды
`UPDATE_DRAFT`/`LINK_EVALUATION`/`UNLINK_EVALUATION` с собственными событиями. Закрытый список
v2 их не содержит. Принятое для v2 упрощение: содержимое `DRAFT` (`summary`, состав
`DecisionBasis`) можно свободно пересобирать без отдельного audit-события вплоть до
`SUBMIT_FOR_REVIEW`; правило истории («не редактировать после фиксации») обеспечивается тем,
что содержимое становится неизменяемым **после** `SUBMIT_FOR_REVIEW`, а не после каждого
изменения в `DRAFT`. Технически это требует API-метода для правки `DRAFT` (например
`PUT /quality-decisions/{id}` или `POST .../bases`), который не описан в терминах Task 10A, но
необходим для практической работы `WELDING_ENGINEER`. Требует подтверждения (см. §K, Q-D9).

`CANCEL` (`DRAFT → CANCELLED`) из v1 в v2 не включён — не входит в закрытый список событий.
Ошибочный `DRAFT` в MVP остаётся неотправленным без специального терминального статуса.

`APPROVED` как статус не используется. Approval хранится отдельно: `approved_by_worker_id`,
`approved_at`, `approved_role`, заполняемые только командой `DECIDE`. После `DECIDED` запись
неизменяема: новое решение — только новый `QualityDecision`.

## E. RBAC (подтверждено в v2 без изменений)

| Роль | Разрешено |
|---|---|
| `WELDING_ENGINEER` | `CREATE`, `SUBMIT_FOR_REVIEW`, правка `DRAFT` (см. §D сноску) |
| `OTK_INSPECTOR` | `RETURN`, `DECIDE` |
| `CHIEF_WELDER` | **не участвует** ни в одной команде `QualityDecision` |

Осознанное отступление от общего fallback-правила ADR-019 (008-07-BP: `CHIEF_WELDER` —
обязательный fallback при отсутствии effective `OTK_INSPECTOR`). Причина, зафиксированная
владельцем: `QualityDecision` — независимое решение по качеству, а не производственное решение
исполнения, поэтому производственная роль `CHIEF_WELDER` в нём не участвует ни в штатном
режиме, ни как fallback. Прецедент аналогичного локального исключения — `ADR-024`
(`DefectDisposition.APPROVE`).

**Прямое следствие, зафиксированное осознанно:** без реального effective `OTK_INSPECTOR` в
проекте ни один `QualityDecision` не может достичь `DECIDED`.

## F. Инварианты и ограничения БД

1. `QualityDecision` не создаётся без ≥1 `DecisionBasis` (проверка на `CREATE`).
2. Не более одной записи со статусом `DECIDED` на один `joint_id` одновременно —
   `UNIQUE(joint_id) WHERE status = 'DECIDED'` (partial index); обеспечивается транзакционным
   supersede при `DECIDE` (§G), не отдельной ручной командой.
3. **Одна `EngineeringEvaluationRevision` не может быть основанием более чем одного `DECIDED`
   `QualityDecision`.** Механизм: `is_basis_of_decided` на `DecisionBasis` выставляется
   `true` только для строк владеющей `DECIDED`-записи и `false` для всех остальных (в т.ч.
   при переходе владеющей записи в `SUPERSEDED`); ограничение —
   `UNIQUE(engineering_evaluation_revision_id) WHERE is_basis_of_decided = true` (partial
   index). Переключение выполняется в той же транзакции, что и переход `status → DECIDED` /
   `status → SUPERSEDED`, под `SELECT ... FOR UPDATE` по вовлечённым `DecisionBasis`.
4. `DECIDED` и `SUPERSEDED` терминальны для прямого редактирования полей решения; исправление
   — только новая запись.
5. История не удаляется; `SUPERSEDED` записи хранятся вечно.
6. **(Заменено Block 1 Correction, 2026-07-23.)** Количество «открытых» записей
   (`DRAFT`/`UNDER_REVIEW`) на один `joint_id` **не ограничивается**: допускается несколько
   `DRAFT` и/или несколько `UNDER_REVIEW` одновременно на один `Joint`. Первоначальная
   рекомендация v1/v2 («не более одной открытой записи на Joint») была отклонена владельцем
   после архитектурного review Block 1; единственное действующее ограничение количества по
   `joint_id` — пункт 2 (`DECIDED`).

## G. Supersede (изменено в v2 — без `ACTIVE`)

Правило, заданное владельцем: при выполнении команды `DECIDE` для нового `QualityDecision`,
если у того же `joint_id` уже существует запись со статусом `DECIDED`, то в одной транзакции:

1. Блокировать `joint_id` (`SELECT ... FOR UPDATE` по всем `quality_decisions` этого `Joint`
   в статусах `DECIDED`/`UNDER_REVIEW`, в детерминированном порядке по `id`).
2. Существующий `DECIDED` → `SUPERSEDED`; заполнить его `superseded_at`/аналог (поле
   уточняется Implementation Specification) и записать `QUALITY_DECISION_SUPERSEDED`.
3. Новая запись `UNDER_REVIEW → DECIDED`; заполнить `approved_*`; записать
   `QUALITY_DECISION_DECIDED`; проставить `supersedes_quality_decision_id` = id старой записи
   (для lineage — техническое поле, не отдельная бизнес-команда).
4. Для каждой `DecisionBasis` новой записи выполнить проверку и переключение
   `is_basis_of_decided` (§F.3) под тем же lock; при конфликте (ревизия уже занята другим
   `DECIDED`) — доменная ошибка `409`, транзакция откатывается целиком.

Отдельной самостоятельной команды `SUPERSEDE` нет: замена происходит только как побочный
эффект `DECIDE` новой записи. Статус `ACTIVE` не используется нигде в модели.

## H. Audit (изменено в v2 — закрытый список)

Используется существующая полиморфная `quality.quality_audit_events`
(`app/quality/execution_models.py`): `entity_type = 'QUALITY_DECISION'`, `entity_id =
quality_decision.id`. Отдельная таблица `QualityDecisionEvent`/`QualityDecisionHistory` не
создаётся (альтернатива v1 §K отклонена явно).

Закрытый список `event_type` (v2, по прямому указанию владельца):

- `QUALITY_DECISION_CREATED`;
- `QUALITY_DECISION_SUBMITTED`;
- `QUALITY_DECISION_RETURNED`;
- `QUALITY_DECISION_DECIDED`;
- `QUALITY_DECISION_SUPERSEDED`.

Расширение CHECK-констрейнтов `ck_quality_audit_entity_type` / `ck_quality_audit_event_type`
выполняется новой миграцией по образцу `20260721_24_disp_supersede.py`.

**Сохранённое ограничение (не переоткрывается).** Таблица `quality_audit_events` хранит
только `actor_worker_id`, без `actor_role_code`/`scope_type`/`scope_id`, которые `ADR-024`
требует как «immutable authorization snapshot» для решений по качеству. Для
`QUALITY_DECISION_DECIDED`/`_RETURNED` снимок роли/scope предлагается класть в `new_values`
JSONB (`{"authorization_snapshot": {...}}`), не расширяя общую таблицу.

## I. Idempotency (без изменений от v1 — не затронуто в v2)

Не упомянуто владельцем в v2. Рекомендация без изменений: применить тот же минимальный
`Idempotency-Key`-контракт, что `ADR-024` §I, к командам `CREATE`, `SUBMIT_FOR_REVIEW`,
`RETURN`, `DECIDE`. Требует подтверждения (см. §K, Q-D5).

## J. MVP / вне рамок (Task 10A, уточнено в v2)

**Входит:** модель `QualityDecision` + `quality_decision_bases`, миграция, схемы Pydantic v2,
repository, service (state machine §D: `CREATE`/`SUBMIT_FOR_REVIEW`/`RETURN`/`DECIDE`), API
(командные эндпоинты), RBAC (§E), supersede-механизм §G, audit через `quality_audit_events`
(§H), тесты lifecycle/RBAC/integrity из задания.

**Не входит:** `CANCEL`; отдельные команды/события `LINK_EVALUATION`/`UNLINK_EVALUATION`/
`UPDATE_DRAFT`/`REOPEN` (см. §D сноски); создание `Defect` по результату `DEFECT_CONFIRMED`
(только сохранение `result`, без side-effect на `Defect`/`DefectRoot`); `DefectDisposition`;
`Repair`; `Reinspection`; печатные формы/документы; импорт; аналитика. Будущая связь
`Defect.quality_decision_id` — не создаётся сейчас.

## K. Открытые точки, требующие подтверждения перед `ACCEPTED`

| № | Вопрос | Рекомендация | Статус |
|---|---|---|---|
| Q-D1 | Требовать ли, чтобы `EngineeringEvaluationRevision`-основание имело статус `EFFECTIVE` на момент `CREATE`/`SUBMIT_FOR_REVIEW`? | Да | **Подтверждено ACCEPTED** — да (см. «Решение по открытым точкам ACCEPTED») |
| Q-D2 | Ограничивать ли не более одной «открытой» `QualityDecision` на `Joint» одновременно? | Да | **Подтверждено ACCEPTED, затем уточнено Block 1 Correction** — ограничение только для `DECIDED`; `DRAFT`/`UNDER_REVIEW` без ограничения количества на Joint |
| Q-D5 | Требовать `Idempotency-Key` для мутирующих команд, как у `DefectDisposition`? | Да | Не рассмотрено при ACCEPTED — решить перед Block 2 |
| Q-D8 | `RETURNED` — атомарный переход `UNDER_REVIEW → DRAFT` одной командой `RETURN` (без персистентного статуса `RETURNED` и без `REOPEN`), как предложено в §D, или сохранить `RETURNED` отдельным статусом + добавить `REOPENED` сверх закрытого списка событий? | Атомарный `RETURN` (в рамках заданного списка из 5 событий) | **Подтверждено ACCEPTED** — атомарный `RETURN`, 4 статуса |
| Q-D9 | Нужен ли API-метод правки состава `DecisionBasis`/`summary` в статусе `DRAFT` без отдельного audit-события на каждое изменение (см. §D сноску), или основания фиксируются только один раз при `CREATE` и `DRAFT` больше не редактируется? | Разрешить правку `DRAFT` без отдельного события (иначе `WELDING_ENGINEER` не сможет исправить опечатку/состав оснований до отправки) | Не рассмотрено при ACCEPTED — решить перед Block 2 |

Q-D3 (supersede), Q-D4 (audit-таблица), Q-D6 (`CANCEL`), Q-D7 (roles) из v1 — закрыты
решением владельца в v2, см. «Изменения v2» выше.

## Связанные документы

После `ACCEPTED` — добавить строки в `docs/project/TASK_REGISTRY.md`,
`docs/project/PROJECT_STATUS.yaml`, `docs/project/ROADMAP.md`, `docs/project/PROJECT_SUMMARY.md`
и раздел `docs/ARCHITECTURE.md` (добавлен предварительный `PROPOSED`-раздел, см. §5 после
раздела 5.10) — по правилу фиксации решений `AGENTS.md`. Запись-указатель в
`docs/project/DECISIONS.md` — см. `## ADR-027`.
