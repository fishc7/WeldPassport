# Implementation Spec — Task 9D-2 · EngineeringEvaluation Core

Канон: [[DECISIONS#ADR-021. EngineeringEvaluation Core Canon (Task 9D-2)|ADR-021]]
(решение **9D-2-C01**) · опирается на
[[DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019]] ·
план [[IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP|IMPLEMENTATION_PLAN]] (строка 9D-2).

Статус: **NOT IMPLEMENTED.** Реализован только предыдущий блок 9D-1 (`QualityFinding` Core).
Этот документ переводит канон ADR-021 в реализуемую структуру и **не** меняет канон.

> **Главное правило (9D-2-C01), пронизывает весь spec.**
> `EngineeringEvaluation` фиксирует **что установлено** (`evaluation_outcome`) и
> **необязывающую рекомендацию** (`recommended_disposition`). `recommended_disposition`
> **никогда не**: меняет статус `QualityFinding`; создаёт `Repair` / `Rework` /
> `Inspection` / `ProductionHold` или иные объекты исполнения; **не заменяет**
> `FindingDisposition`. Единственный источник официального исполняемого решения по
> finding — отдельная сущность `FindingDisposition` (Task 9D-4).

---

## 1. Границы Task 9D-2

**Входит** (ADR-021 §6): логическая оценка и ревизии; lifecycle ревизии; поля исхода и
рекомендации (`evaluation_outcome`, `recommended_disposition`); источники оценки; проверка
ревизионных и неревизионных источников (хэш значимых полей); критерии
(`EngineeringEvaluationCriterion`); `EngineeringException`; уровень уверенности; остаточный
риск; срок пересмотра; базовые события и аудит; RBAC; API; миграция; тесты; контрактные поля
для будущего согласования и исполнения.

**Не входит:** универсальный `ApprovalRoute` и версии маршрутов; решения внешних согласующих;
`ApprovalCondition`; исполнение условий согласования; полный workflow `EvaluationDirective`;
создание ремонта/переделки/доп. контроля; управление версиями политик; `PolicyImpactAssessment`;
кампании массовой переоценки; автоматическое закрытие производственных workflow; файлы,
печатные формы и импорт. `FindingDisposition` — **не** в этой задаче (9D-4); здесь только
контрактная граница.

---

## 2. Соглашения (наследуются от 9A–9D-1)

- Модульный split в `09_Разработка/backend/app/quality/`:
  `engineering_evaluation_workflow.py` (константы/pure-функции),
  `engineering_evaluation_models.py` (ORM), `engineering_evaluation_schemas.py` (Pydantic),
  `engineering_evaluation_repository.py`, `engineering_evaluation_services.py`,
  `engineering_evaluation_api.py`.
- Схема БД — `quality`. Перечисления — **CHECK-ограничениями**, без native enum.
- Actor-поля — `*_by_worker_id` типа `Integer` **без FK** (переходный период, как 9A–9D-1).
- Optimistic locking — `version` (≥1). Физического удаления нет, кроме `DRAFT`-ревизии.
- Числа — `numeric`, даты — `timestamptz`. Файлов/бинарей нет.
- Роли — существующие `role_code` из `inspection_workflow`, **новых не вводим**
  (ADR-019). Маппинг: `WELDING_ENGINEER ↔ OGS_ENGINEER`, `CHIEF_WELDER ↔ CHIEF_WELDER`.
- Бизнес-действия — **команды**, не универсальный PATCH. Актор из `X-User-Id`,
  RBAC/scope — на backend.
- Коды ошибок — UPPERCASE, HTTP-семантика: 403 роль/scope; 404 не найдено/скрыто scope;
  409 конфликт версии/недопустимый переход; 422 структурно недопустимая команда/несоответствие
  ссылок или незакрытая проверка комплектности.

---

## 3. Сущности и таблицы (схема `quality`)

| Сущность | Таблица | Назначение |
|---|---|---|
| `EngineeringEvaluation` | `engineering_evaluations` | Логическая оценка, 1 к 1 с `QualityFinding` (цепочка ревизий) |
| `EngineeringEvaluationRevision` | `engineering_evaluation_revisions` | Ревизия оценки (носитель исхода/рекомендации/обоснования) |
| `EngineeringEvaluationSource` | `engineering_evaluation_sources` | Структурированная ссылка на источник (ревизионный/неревизионный) |
| `EngineeringEvaluationCriterion` | `engineering_evaluation_criteria` | Применимый критерий приёмки |
| `EngineeringException` | `engineering_exceptions` | Отступление от одного критерия |
| `EngineeringEvaluationEvent` | `engineering_evaluation_events` | Неизменяемое событие истории (append-only) |

Дочерние сущности (`sources`, `criteria`, `exceptions`) принадлежат **ревизии**, а не
логической оценке, и проходят её границу неизменяемости (§6).

### 3.1. EngineeringEvaluation

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `project_id` | uuid FK projects RESTRICT | денормализация для scope/индексов |
| `finding_id` | uuid FK quality_findings RESTRICT | **UNIQUE** — одна логическая оценка на finding (инвариант 1) |
| `current_revision_id` | uuid null | текущая рабочая/последняя ревизия |
| `effective_revision_id` | uuid null | действующая ревизия (не более одной; инвариант 2) |
| `created_by_worker_id` / `created_at` / `updated_by_worker_id` / `updated_at` / `version` | audit | канон 9A–9D-1 |

`UNIQUE(finding_id)` физически гарантирует «не более одной логической цепочки на finding».

### 3.2. EngineeringEvaluationRevision

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `evaluation_id` | uuid FK engineering_evaluations RESTRICT | |
| `revision_no` | int ≥1 | монотонно в пределах оценки; `UNIQUE(evaluation_id, revision_no)` |
| `previous_revision_id` | uuid null FK self | связь с предыдущей ревизией (инвариант 4/6) |
| `status` | text CHECK | lifecycle §5 |
| `evaluation_outcome` | text CHECK | **что установлено** (§4.1) |
| `recommended_disposition` | text CHECK | **необязывающая рекомендация** (§4.2) |
| `rationale` | text NOT NULL, trim>0 | обязательное инженерное обоснование |
| `confidence_level` | text null CHECK | `HIGH/MEDIUM/LOW`, обязателен по §7.4 |
| `confidence_note` | text null | обязателен при `LOW` |
| `residual_risk` | text null | обязателен по §7.5 |
| `application_conditions` | text null | условия/ограничения применения; **обязателен при `CONDITIONALLY_ACCEPTABLE`** (§7.5b) |
| `review_due_at` | timestamptz null | обязателен по §7.6 |
| `revision_reason` | text null | причина пересмотра (обязательна при `revision_no > 1`) |
| `supersedes_impact` | text null | влияние на ранее созданные/выполненные действия при пересмотре |
| `prepared_by_worker_id` / `prepared_at` | | переход DRAFT→PREPARED (`WELDING_ENGINEER`) |
| `fixed_by_worker_id` / `fixed_at` | | переход PREPARED/PENDING_APPROVAL→FIXED (`CHIEF_WELDER`) |
| `withdrawn_by_worker_id` / `withdrawn_at` / `withdrawal_reason` | | конечный `WITHDRAWN` |
| `effective_at` / `superseded_at` | timestamptz null | вступление/замещение |
| `created_*` / `updated_*` / `version` | audit | |

CHECK-инварианты уровня строки:
- `revision_no = 1 OR revision_reason IS NOT NULL` (пересмотр обоснован);
- `status <> 'WITHDRAWN' OR (withdrawn_at IS NOT NULL AND withdrawn_by_worker_id IS NOT NULL AND length(trim(withdrawal_reason))>0)`;
- `confidence_level IS NULL OR confidence_level IN (...)`;
- `confidence_level <> 'LOW' OR length(trim(confidence_note))>0`.

Полная проверка комплектности (§8) — на сервисе, т.к. зависит от дочерних записей.

### 3.3. EngineeringEvaluationSource

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `revision_id` | uuid FK revisions RESTRICT | принадлежит ревизии |
| `source_role` | text CHECK | §4.4 |
| `source_entity_type` | text CHECK | тип проверяемой сущности |
| `source_entity_id` | uuid NOT NULL | |
| `source_revision_id` | uuid null | **обязателен** для ревизионного источника (§7.1) |
| `source_hash` | text null | **обязателен** для неревизионного источника |
| `hash_schema_version` | text null | версия профиля значимых полей (§7.2) |
| `verified_at` | timestamptz null | момент последней успешной сверки |
| `applicability_note` | text null | обязателен для основного/спорного/отклонённого (§4.4) |
| `created_*` | audit | |

CHECK: `(source_revision_id IS NOT NULL) OR (source_hash IS NOT NULL AND hash_schema_version IS NOT NULL)`
— источник либо ревизионный, либо покрыт хэшем.

### 3.4. EngineeringEvaluationCriterion

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `revision_id` | uuid FK revisions RESTRICT | |
| `requirement_ref` | text NOT NULL | нормативный/проектный/технический источник |
| `clause` | text null | раздел/пункт/таблица/требование |
| `parameter` | text NOT NULL | проверяемый параметр |
| `actual_value` | text null | фактическое значение (строкой для разнотипности; числа дублируются в `actual_num`) |
| `actual_num` | numeric null | числовой факт, если применимо |
| `allowed_value` | text null | допустимое значение/условие |
| `allowed_num_min` / `allowed_num_max` | numeric null | числовой диапазон |
| `unit` | text null | единица измерения |
| `comparison_result` | text CHECK | §4.3 |
| `applicability_comment` | text null | **обязателен при `comparison_result = NOT_APPLICABLE`** (§8) |
| `engineer_comment` | text null | общий инженерный комментарий (опционально) |
| `created_*` | audit | |

### 3.5. EngineeringException

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `revision_id` | uuid FK revisions RESTRICT | |
| `criterion_id` | uuid FK criteria RESTRICT | **одно исключение — один критерий** (инвариант 10); `UNIQUE(revision_id, criterion_id)` |
| `basis` | text NOT NULL | основание |
| `justification` | text NOT NULL | инженерное обоснование |
| `residual_risk` | text NOT NULL | остаточный риск исключения |
| `conditions` | text null | условия/ограничения применения |
| `required_approval_route` | text null | требуемый маршрут согласования (контрактное поле, исполнение — 9D-3) |
| `is_draft_copy` | bool default false | скопировано в новую ревизию как черновая заготовка (§7.7) |
| `created_*` | audit | |

### 3.6. EngineeringEvaluationEvent (append-only)

Поля по канону 9D-1 `QualityFindingEvent`: `id`, `evaluation_id`, `revision_id` (null для
событий уровня оценки), `event_type` (CHECK, §9), `actor_worker_id` (Integer, без FK),
`actor_role` (text), `reason` (text null), `event_metadata` (JSONB, колонка `metadata`),
`correlation_id` (uuid null), `revision_status_after` (text null), `created_at`.
API изменения/удаления событий нет; пишется в одной транзакции с командой.

---

## 4. Перечисления (CHECK-справочники) — согласованный enum 9D-2-C01

### 4.1. evaluation_outcome — что установлено

```text
ACCEPTABLE                — соответствует применимым критериям
NONCONFORMING             — установлено несоответствие
CONDITIONALLY_ACCEPTABLE  — приемлемо при выполнении условий/ограничений
INSUFFICIENT_DATA         — данных недостаточно для окончательного вывода
NOT_APPLICABLE            — применимые критерии отсутствуют / оценка неприменима
```

### 4.2. recommended_disposition — необязывающая рекомендация ОГС

```text
NONE                    — дополнительных действий не требуется
ACCEPT_AS_IS            — рекомендовано принять как есть
REPAIR                  — рекомендован ремонт
REWORK                  — рекомендована переделка
ADDITIONAL_INSPECTION   — рекомендован дополнительный контроль
REJECT                  — рекомендовано отклонение/выбраковка
```

> `AS_IS` присутствует **только** в `recommended_disposition` (`ACCEPT_AS_IS`).
> Исход-приёмка называется `ACCEPTABLE` — **не** `ACCEPTABLE_AS_IS`.

### 4.3. criterion.comparison_result

```text
COMPLIES · DOES_NOT_COMPLY · CONDITIONALLY_COMPLIES · NOT_APPLICABLE · INSUFFICIENT_DATA
```

### 4.4. source_role

```text
PRIMARY_EVIDENCE · SUPPORTING_EVIDENCE · ACCEPTANCE_CRITERIA · CONTEXT · REJECTED_EVIDENCE
```

`applicability_note` обязателен для `PRIMARY_EVIDENCE`, спорного и `REJECTED_EVIDENCE`.

### 4.5. confidence_level

```text
HIGH · MEDIUM · LOW
```

---

## 5. Lifecycle ревизии

```text
DRAFT → PREPARED → FIXED → EFFECTIVE → SUPERSEDED
```

Дополнительные: `RETURNED_FOR_REVISION`, `WITHDRAWN`, `PENDING_APPROVAL`.

| Переход | Команда | Роль | Условия |
|---|---|---|---|
| — → DRAFT | `create-revision` | `WELDING_ENGINEER` | нет незакрытой (не-FIXED/EFFECTIVE) ревизии, кроме случая после WITHDRAWN |
| DRAFT → DRAFT | `update-revision` | `WELDING_ENGINEER` | ревизия в DRAFT |
| DRAFT → PREPARED | `prepare-revision` | `WELDING_ENGINEER` | проверка комплектности §8 + сверка источников §7.3 |
| PREPARED → RETURNED_FOR_REVISION → DRAFT | `return-revision` | `CHIEF_WELDER` | возврат **не** создаёт новую ревизию (§6); та же ревизия в DRAFT, факт — событием |
| PREPARED → PENDING_APPROVAL | (контракт 9D-3) | — | если требуется внешнее согласование; в 9D-2 только статус+событие |
| PREPARED/PENDING_APPROVAL → FIXED | `fix-revision` | `CHIEF_WELDER` | повторная сверка источников §7.3; подготовка и фиксация — **разными** акторами |
| FIXED → EFFECTIVE | `set-effective` | `CHIEF_WELDER` | если согласование не требуется — сразу после фиксации; ретроактивно запрещено |
| PREPARED/PENDING_APPROVAL/FIXED(не EFFECTIVE) → WITHDRAWN | `withdraw-revision` | `WELDING_ENGINEER`/`CHIEF_WELDER` | конечный статус; в DRAFT не возвращается |
| EFFECTIVE(предыдущая) → SUPERSEDED | авто при `set-effective` новой | — | только после вступления новой (инвариант 11) |

Инварианты lifecycle: редактируется только `DRAFT`; после `PREPARED` содержание неизменяемо;
`WITHDRAWN` конечный; `SUPERSEDED` только после вступления новой; одновременно `EFFECTIVE` —
одна ревизия.

---

## 6. Граница неизменяемости

После `prepare-revision` неизменяемы: `evaluation_outcome`, `recommended_disposition`,
`rationale`, все `sources`, все `criteria`, все `exceptions`, `confidence_*`,
`residual_risk`, `review_due_at`. Возврат на доработку (`return-revision`) до окончательной
фиксации **не создаёт новую ревизию** — текущая ревизия возвращается в `DRAFT`, факт возврата
пишется событием `EVALUATION_RETURNED`. Новая ревизия создаётся только после `FIXED` предыдущей
либо после её `WITHDRAWN`.

---

## 7. Правила источников, уверенности, риска, пересмотра

- **7.1.** Ревизионный источник → обязателен `source_revision_id` на конкретную ревизию.
- **7.2.** Неревизионный источник → `source_hash` по версионируемому профилю значимых полей
  (`hash_schema_version`). Состав полей — системный профиль на `source_entity_type`;
  пользователь поля не выбирает. **Для первой реализации 9D-2 обязательные неревизионные
  профили — `QUALITY_FINDING` и `JOINT`** (оба не имеют ревизионной сущности, только `version`).
  Другие `source_entity_type` добавляются **только после проверки реальных моделей и их
  ревизионности**: ревизионные источники используют `source_revision_id` (§7.1), а не хэш;
  неревизионный тип без утверждённого профиля в 9D-2 не принимается (`EVAL_SOURCE_REVISION_REQUIRED`
  либо отказ по неизвестному профилю).
- **7.3.** Перед `prepare-revision` **и** перед `fix-revision` сервис повторно сверяет
  источники: доступность + соответствие сохранённой ревизии/хэшу. Расхождение/недоступность
  → блок фиксации (`EVAL_SOURCE_STALE` / `EVAL_SOURCE_UNAVAILABLE`). Автоподмена источника и
  автообновление хэша **запрещены** (только явная перепроверка `reverify-source`).
- **7.4.** `confidence_level` обязателен при: `INSUFFICIENT_DATA` (исход или критерий);
  `CONDITIONALLY_ACCEPTABLE`; наличии `EngineeringException`; неполных/косвенных доказательствах;
  повышенном остаточном риске. При `LOW` — обязателен `confidence_note` (причины + меры).
- **7.5.** `residual_risk` обязателен при: `EngineeringException`; `CONDITIONALLY_ACCEPTABLE`;
  `confidence_level ∈ {MEDIUM, LOW}`; условиях эксплуатации/временных мерах; рекомендации
  `ACCEPT_AS_IS` при отклонении.
- **7.5b.** `application_conditions` обязателен при исходе `CONDITIONALLY_ACCEPTABLE`
  (приемлемость обусловлена выполнением ограничений). Для прочих исходов — опционально.
- **7.6.** `review_due_at` обязателен для условных и риск-ориентированных решений
  (`CONDITIONALLY_ACCEPTABLE`; наличие исключений; `residual_risk` заполнен), а также при
  `recommended_disposition = ADDITIONAL_INSPECTION` или когда требуется будущее подтверждение.
  Окончательный `REJECT` из-за отсутствия обязательных доказательств `review_due_at` **не
  требует**. `INSUFFICIENT_DATA` сам по себе `review_due_at` не навязывает — обязательность
  определяется перечисленными условиями. Наступление срока — событие `REVIEW_OVERDUE`, оценку
  автоматически не отменяет.
- **7.7.** При новой ревизии исключения могут копироваться только как черновые заготовки
  (`is_draft_copy = true`); действительность/согласования/подтверждения не наследуются.
- **7.8. Подтверждение пересмотра (двухролевой workflow, без внешнего согласования).**
  Когда наступает `review_due_at`, а инженерное содержание действующей (`EFFECTIVE`) ревизии
  не изменилось, пересмотр оформляется без создания новой ревизии:
  1. `WELDING_ENGINEER` инициирует — команда `request-review-confirmation` (событие
     `REVIEW_CONFIRMATION_REQUESTED`); при необходимости задаёт новый `review_due_at`;
  2. `CHIEF_WELDER` подтверждает — команда `confirm-review` (событие `REVIEW_CONFIRMED`),
     новый `review_due_at` вступает в силу.

  Инициатор и подтверждающий — **разные** роли (тот же принцип, что prepare/fix). Внешнего
  согласования в 9D-2 нет. Если изменились источники/критерии/решение/исключения/риск/условия —
  подтверждение недопустимо, требуется **новая ревизия** (`EVAL_REVIEW_CONTENT_CHANGED`).
  Наступивший и не подтверждённый срок фиксируется событием `REVIEW_OVERDUE`, но оценку
  автоматически не отменяет.

---

## 8. Validation matrix (пересобрана под 9D-2-C01)

Проверка выполняется на `prepare-revision`. Минимальная комплектность (всегда):
структурированный `evaluation_outcome`; `recommended_disposition` (когда исход предполагает
маршрут); `rationale`; ≥1 источник; ≥1 критерий; `applicability_comment` для каждого
`NOT_APPLICABLE`-критерия; доступность источников; актуальность
ссылок/хэшей (§7.3); обязательные `applicability_note`; необходимые исключения; `confidence_level`
(§7.4); `residual_risk` (§7.5); `application_conditions` (§7.5b); `review_due_at` (§7.6).

Матрица по исходу:

| `evaluation_outcome` | Условие по критериям | Допустимые `recommended_disposition` | `EngineeringException` | `confidence` | `residual_risk` | `application_conditions` | `review_due_at` |
|---|---|---|---|---|---|---|---|
| `ACCEPTABLE` | все `COMPLIES`/`NOT_APPLICABLE` | `NONE`, `ACCEPT_AS_IS` | **не требуется** | нет | нет | нет | нет |
| `CONDITIONALLY_ACCEPTABLE` | есть `DOES_NOT_COMPLY`/`CONDITIONALLY_COMPLIES`, **покрытые** исключением | `ACCEPT_AS_IS`, `REPAIR`, `REWORK`, `ADDITIONAL_INSPECTION` | **да** — на каждый критерий, принятый с отступлением | **да** | **да** | **да** | **да** |
| `NONCONFORMING` | есть `DOES_NOT_COMPLY` | `REPAIR`, `REWORK`, `REJECT`, `ADDITIONAL_INSPECTION` | — | если `LOW`/косвенные | если риск сохраняется | если заданы условия | если риск-ориентировано |
| `INSUFFICIENT_DATA` | есть `INSUFFICIENT_DATA`/неполнота | `ADDITIONAL_INSPECTION` (норма); `REPAIR`/`REWORK`/`REJECT` (обоснованно) | — | **да** | если `MEDIUM`/`LOW`, сохраняющийся риск, врем. компенсирующие меры или условное решение | если заданы условия | если нужно будущее подтверждение или `ADDITIONAL_INSPECTION`; для окончательного `REJECT` из-за нехватки обязательных доказательств — **необязателен** |
| `NOT_APPLICABLE` | ≥1 критерий, **все** применимые `comparison_result = NOT_APPLICABLE`; каждому обязателен `applicability_comment` | только `NONE` | — | нет | нет | нет | нет |

Сквозные правила:
1. **`recommended_disposition = ACCEPT_AS_IS` не ограничивается только `CONDITIONALLY_ACCEPTABLE`.**
   Он допустим при **двух** исходах: `ACCEPTABLE` — **без** `EngineeringException` (отклонения
   от критериев нет); `CONDITIONALLY_ACCEPTABLE` — **с обязательным** `EngineeringException` на
   каждый критерий, принятый с отступлением.
2. Исход `ACCEPTABLE` допускается только при всех критериях `COMPLIES`/`NOT_APPLICABLE`; при
   наличии `DOES_NOT_COMPLY`/`CONDITIONALLY_COMPLIES`/`INSUFFICIENT_DATA` — используется
   `CONDITIONALLY_ACCEPTABLE` / `NONCONFORMING` / `INSUFFICIENT_DATA`
   (`EVAL_OUTCOME_CRITERIA_MISMATCH`).
3. `ACCEPT_AS_IS` при исходе `CONDITIONALLY_ACCEPTABLE` без оформленного `EngineeringException`
   на каждый отклонённый критерий → `EVAL_ACCEPT_WITHOUT_EXCEPTION`.
4. Каждый `EngineeringException` ссылается ровно на один критерий с результатом
   `DOES_NOT_COMPLY`/`CONDITIONALLY_COMPLIES` (иначе `EVAL_EXCEPTION_CRITERION_INVALID`).
5. `CONDITIONALLY_ACCEPTABLE` требует полного набора: `EngineeringException` (на каждый
   отклонённый критерий), `confidence`, `residual_risk`, `application_conditions`, `review_due_at`.
6. `INSUFFICIENT_DATA` в критерии сам по себе фиксацию не блокирует — допустимость определяется
   строкой матрицы.
7. `NOT_APPLICABLE`: в ревизии **≥1** `EngineeringEvaluationCriterion`; **все** применимые
   критерии имеют `comparison_result = NOT_APPLICABLE`; для каждого такого критерия обязателен
   `applicability_comment` (`EVAL_APPLICABILITY_COMMENT_REQUIRED`); `recommended_disposition`
   допускается **только `NONE`** (иначе `EVAL_DISPOSITION_NOT_ALLOWED`). Формулировка «нет
   критериев» недопустима.
8. Для `INSUFFICIENT_DATA` **не** действует универсальное правило `residual_risk = да` /
   `review_due_at = да`: `residual_risk` обязателен по §7.5, `review_due_at` — по §7.6, по
   фактическим условиям. Окончательный `REJECT` из-за отсутствия обязательных доказательств не
   требует `review_due_at`.

> **Инвариант влияния (9D-2-C01).** Ни `prepare`, ни `fix`, ни `set-effective`, ни любое
> значение `recommended_disposition` **не** меняют `QualityFinding.status`, **не** создают
> `Repair`/`Rework`/`Inspection`/`ProductionHold` и **не** создают/не заменяют
> `FindingDisposition`. Влияние на finding — только через контур `FindingDisposition` (9D-4),
> который может читать `recommended_disposition` как вход. В 9D-2 запрещены любые вызовы,
> изменяющие сущности вне контура `EngineeringEvaluation*`.

---

## 9. События (append-only)

```text
EVALUATION_CREATED   EVALUATION_UPDATED   EVALUATION_PREPARED   EVALUATION_RETURNED
EVALUATION_FIXED     EVALUATION_WITHDRAWN EVALUATION_BECAME_EFFECTIVE   EVALUATION_SUPERSEDED
SOURCE_ADDED         SOURCE_REMOVED       SOURCE_REVERIFIED
REVIEW_OVERDUE       REVIEW_CONFIRMATION_REQUESTED   REVIEW_CONFIRMED
```

`REVIEW_CONFIRMATION_REQUESTED` — расширение поверх минимального набора ADR-021 §4 (для
двухролевого workflow §7.8; ADR-021 §4 задаёт минимум, дополнения допускаются).

---

## 10. API (команды, префикс `/api/v1`)

| Метод/путь | Команда | Роль |
|---|---|---|
| `POST /quality/findings/{finding_id}/engineering-evaluation` | создать логическую оценку + первую `DRAFT`-ревизию | `WELDING_ENGINEER` |
| `POST /quality/engineering-evaluation-revisions/{id}/update` | правка `DRAFT` | `WELDING_ENGINEER` |
| `POST …/{id}/sources` · `DELETE …/sources/{sid}` | источники ревизии (`DRAFT`) | `WELDING_ENGINEER` |
| `POST …/{id}/criteria` · `…/exceptions` | критерии/исключения (`DRAFT`) | `WELDING_ENGINEER` |
| `POST …/{id}/reverify-sources` | явная перепроверка источников | `WELDING_ENGINEER` |
| `POST …/{id}/prepare` | DRAFT→PREPARED (проверка §8) | `WELDING_ENGINEER` |
| `POST …/{id}/return` | PREPARED→DRAFT (возврат) | `CHIEF_WELDER` |
| `POST …/{id}/fix` | →FIXED (повторная сверка §7.3) | `CHIEF_WELDER` |
| `POST …/{id}/set-effective` | FIXED→EFFECTIVE (+SUPERSEDED предыдущей) | `CHIEF_WELDER` |
| `POST …/{id}/withdraw` | →WITHDRAWN | `WELDING_ENGINEER`/`CHIEF_WELDER` |
| `POST …/{id}/request-review-confirmation` | инициировать пересмотр без изменения содержания (§7.8) | `WELDING_ENGINEER` |
| `POST …/{id}/confirm-review` | REVIEW_CONFIRMED без изменения содержания (§7.8) | `CHIEF_WELDER` |
| `GET /quality/findings/{finding_id}/engineering-evaluation` | чтение оценки с ревизиями | READ-роли |
| `GET …/engineering-evaluation-revisions/{id}` · `…/events` | ревизия/журнал | READ-роли |

Все команды несут `expected_version` (optimistic locking) и `actor` из `X-User-Id`.
Создание новой ревизии-пересмотра — `POST …/{finding_id}/engineering-evaluation/revisions`
(после `FIXED`/`WITHDRAWN` предыдущей).

---

## 11. Коды ошибок (машинные)

```text
EVAL_NOT_FOUND · EVAL_ROLE_DENIED · EVAL_VERSION_CONFLICT
EVAL_FINDING_NOT_FOUND · EVAL_FINDING_STATE_INVALID · EVAL_ALREADY_EXISTS
EVAL_REVISION_NOT_DRAFT · EVAL_INVALID_TRANSITION · EVAL_PREPARE_INCOMPLETE
EVAL_OUTCOME_CRITERIA_MISMATCH · EVAL_ACCEPT_WITHOUT_EXCEPTION · EVAL_EXCEPTION_CRITERION_INVALID
EVAL_DISPOSITION_NOT_ALLOWED · EVAL_CONFIDENCE_REQUIRED · EVAL_RESIDUAL_RISK_REQUIRED
EVAL_CONDITIONS_REQUIRED · EVAL_APPLICABILITY_COMMENT_REQUIRED · EVAL_REVIEW_DUE_REQUIRED
EVAL_SOURCE_STALE · EVAL_SOURCE_UNAVAILABLE
EVAL_SOURCE_REVISION_REQUIRED · EVAL_SAME_ACTOR_PREPARE_FIX · EVAL_ALREADY_EFFECTIVE
EVAL_REVIEW_CONTENT_CHANGED · EVAL_SAME_ACTOR_REVIEW
```

HTTP: 403 (`ROLE_DENIED`); 404 (`NOT_FOUND`); 409 (`VERSION_CONFLICT`,
`INVALID_TRANSITION`, `ALREADY_EFFECTIVE`, `SAME_ACTOR_PREPARE_FIX`); 422 (все проверки
комплектности/матрицы/источников).

---

## 12. Миграция

Одна Alembic-ревизия `engineering_evaluation_core`. **Номер/префикс ревизии заранее не
фиксируется** — определяется во время реализации через `alembic heads`: должен быть ровно
один текущий head, он и становится `down_revision`. Если heads несколько — сначала свести к
одному, только потом создавать ревизию. Содержимое: 6 таблиц схемы `quality`, все
CHECK/UNIQUE/индексы
(`finding_id` unique; `(evaluation_id, revision_no)` unique; индексы по `project_id`,
`finding_id`, `status`, `evaluation_id`, `created_at`). Downgrade — drop в обратном порядке
с учётом FK. Существующие таблицы не трогать; данных для бэкофилла нет.

---

## 13. Тесты (pytest, как `test_quality_findings_api.py`)

- lifecycle: create→update→prepare→fix→set-effective; return→prepare заново; withdraw;
  supersede при новой effective;
- запрет редактирования не-DRAFT; optimistic `version`-конфликт;
- RBAC: prepare (`WELDING_ENGINEER`), fix (`CHIEF_WELDER`); `EVAL_SAME_ACTOR_PREPARE_FIX`;
- validation matrix: каждая строка §8 (валид/невалид); `ACCEPTABLE`+`ACCEPT_AS_IS` → **валидно,
  без исключения**; `ACCEPTABLE`+`ACCEPT_AS_IS` при наличии `DOES_NOT_COMPLY` →
  `EVAL_OUTCOME_CRITERIA_MISMATCH`; `CONDITIONALLY_ACCEPTABLE`+`ACCEPT_AS_IS` без исключения →
  `EVAL_ACCEPT_WITHOUT_EXCEPTION`; `CONDITIONALLY_ACCEPTABLE` без `application_conditions` →
  `EVAL_CONDITIONS_REQUIRED`; исход vs критерии;
- `NOT_APPLICABLE`: 0 критериев → `EVAL_PREPARE_INCOMPLETE`; смешанный результат (не все
  `NOT_APPLICABLE`) → `EVAL_OUTCOME_CRITERIA_MISMATCH`; `NOT_APPLICABLE`-критерий без
  `applicability_comment` → `EVAL_APPLICABILITY_COMMENT_REQUIRED`; `recommended_disposition ≠ NONE`
  → `EVAL_DISPOSITION_NOT_ALLOWED`;
- `INSUFFICIENT_DATA`: `confidence` обязателен; `residual_risk` **не** обязателен при
  `confidence = HIGH` без сохраняющегося риска; `review_due_at` обязателен при
  `ADDITIONAL_INSPECTION`; окончательный `REJECT` из-за нехватки доказательств без
  `review_due_at`/`residual_risk` → **валидно**;
- источники: ревизионный без `source_revision_id`; неревизионный без хэша; профили `QUALITY_FINDING`
  и `JOINT`; неизвестный неревизионный профиль отклоняется; сверка на prepare и на fix
  (`EVAL_SOURCE_STALE`); `reverify-sources`;
- уверенность/риск/условия/срок: обязательность по §7.4–7.6;
- review-workflow (§7.8): `request-review-confirmation` (`WELDING_ENGINEER`) → `confirm-review`
  (`CHIEF_WELDER`); тот же актор для обоих → `EVAL_SAME_ACTOR_REVIEW`; подтверждение при
  изменившемся содержании → `EVAL_REVIEW_CONTENT_CHANGED`; `REVIEW_OVERDUE` не отменяет оценку;
- **инвариант 9D-2-C01**: после `set-effective` `QualityFinding.status` не изменился, объекты
  исполнения не созданы, `FindingDisposition` не появился;
- события: тип, `revision_id`, actor/role в журнале по каждой команде.

---

## 14. Контрактная граница на будущее (не реализуется в 9D-2)

- `EngineeringException.required_approval_route` — поле-контракт для 9D-3 (Approval Workflow);
  сам маршрут/решения согласующих — вне 9D-2.
- Статус `PENDING_APPROVAL` — присутствует в CHECK, переходы в него/из него — контур 9D-3.
- `recommended_disposition` — вход для `FindingDisposition` (9D-4); связь только на чтение,
  без создания объектов из 9D-2.

---

## 15. Definition of Done

Код реализует §3–§11; миграция §12 применяется идемпотентно; тесты §13 зелёные; линтер чист;
канон ADR-021 не изменялся; в модуле 9D-2 нет ни одного пути, меняющего статус `QualityFinding`
или создающего объекты исполнения/`FindingDisposition`.
