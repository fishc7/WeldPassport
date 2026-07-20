# Исполняемый промпт для Claude Code — Task 9D-2 · EngineeringEvaluation Core

> Копируй блок ниже как задачу для реализации. Промпт самодостаточен, но опирается на
> канон [[DECISIONS#ADR-021. EngineeringEvaluation Core Canon (Task 9D-2)|ADR-021]]
> (решение **9D-2-C01**) и на
> [[TASK_9D-2_ENGINEERING_EVALUATION_SPEC|Implementation Spec 9D-2]]. При расхождении
> приоритет: ADR-021 → Spec → этот промпт.

---

## Роль и контекст

Ты реализуешь **Task 9D-2 — EngineeringEvaluation Core** в backend WeldPassport
(FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL, схема `quality`). Предыдущий блок
**9D-1 QualityFinding Core** уже реализован — строго повторяй его паттерны
(`09_Разработка/backend/app/quality/quality_finding_*.py`).

Перед началом прочитай: `docs/project/DECISIONS.md` (ADR-021 целиком),
`docs/project/TASK_9D-2_ENGINEERING_EVALUATION_SPEC.md`, а также модуль 9D-1
(`quality_finding_workflow.py`, `_models.py`, `_schemas.py`, `_repository.py`,
`_services.py`, `_api.py`) и `app/quality/inspection_workflow.py` (роли/READ-scope).

## Ключевое архитектурное правило (не нарушать)

`EngineeringEvaluation` фиксирует **что установлено** (`evaluation_outcome`) и
**необязывающую рекомендацию** (`recommended_disposition`). Заменяемого поля `decision_type`
**нет** — оно разделено на два поля (решение 9D-2-C01).

`recommended_disposition` **НИКОГДА**:
- не меняет `QualityFinding.status`;
- не создаёт `Repair` / `Rework` / `Inspection` / `ProductionHold` и любые объекты исполнения;
- не создаёт и не заменяет `FindingDisposition` (это отдельная сущность Task 9D-4).

В модуле 9D-2 не должно быть ни одного вызова, изменяющего сущности вне `EngineeringEvaluation*`.
`FindingDisposition` читает `recommended_disposition` как вход — но это контур 9D-4, не эта задача.

## Инварианты 9D-2-C02 … C10 (обязательны при реализации)

- **C02 — классификация в ревизии.** `confirmed_severity` и `impact_scope` — поля
  `EngineeringEvaluationRevision`, обязательны на `prepare`, редактируются только в `DRAFT`, после
  `PREPARED` неизменяемы. Новая ревизия может изменить классификацию. Актуальные значения читаются
  **только из `EFFECTIVE`-ревизии**; поля `QualityFinding` ими **не переписываются**. Enum — канон
  ADR-019 (ниже), новые не вводить.
- **C03 — терминология.** Действующая оценка — **`EFFECTIVE` `EngineeringEvaluationRevision`**;
  статус `APPROVED` **не вводить** (`FIXED` = «зафиксировано», `EFFECTIVE` = «действует»).
  **Обязательно** исправить устаревший forward reference в комментарии
  `app/quality/quality_finding_workflow.py` (≈стр. 129): «APPROVED EngineeringEvaluation» →
  «EFFECTIVE EngineeringEvaluationRevision». Это **правка комментария**, поведение 9D-1 не меняется.
- **C04 — lifecycle finding.** Task 9D-2 **не меняет** `QualityFinding.status`. После
  `EFFECTIVE`-оценки finding остаётся `UNDER_EVALUATION`. **Запрещено** переводить finding в
  `DISPOSITION_PENDING` из 9D-2 — это контур `FindingDisposition` (Task 9D-4).
  `recommended_disposition` не создаёт `FindingDisposition`; `impact_scope` не создаёт
  `ProductionHold` и не вычисляет состояние `Joint` (тоже 9D-4).
- **C06 — lifecycle оценки.** `EngineeringEvaluationRevision`:
  `DRAFT → PREPARED → FIXED → EFFECTIVE → SUPERSEDED` (при обязательном согласовании
  `FIXED → PENDING_APPROVAL → EFFECTIVE`; возврат `PREPARED → DRAFT`; `WITHDRAWN` из
  `PREPARED`/`FIXED`/`PENDING_APPROVAL`). Статус `APPROVED` для `EngineeringEvaluation` **не
  вводить** (это термин ADR-019). Статус `APPROVED` у `FindingDisposition` не трогать.
- **C07 — classification.** Поле `classification` в `EngineeringEvaluationRevision` (enum ниже),
  обязательно на `prepare`, изменяемо только в `DRAFT`, актуально из `EFFECTIVE`-ревизии, поля
  `QualityFinding` не меняет. **Обязательная согласованность `classification → evaluation_outcome`**
  (матрица ниже), иначе `EVAL_CLASSIFICATION_OUTCOME_MISMATCH`. `CONFIRMED_DEFECT` **не** создаёт
  `Defect` в 9D-2.
- **C08 — единая структурная миграция.** 9D-2A создаёт **7** таблиц одной миграцией; `sources`/
  `criteria`/`exceptions` — структурно (поведение 9D-2B/2C). Плановых `ALTER TABLE` для уже
  известных полей **не** использовать.
- **C09 — возврат.** `RETURNED_FOR_REVISION` **не** добавлять как статус. lifecycle CHECK — ровно
  семь: `DRAFT`, `PREPARED`, `FIXED`, `PENDING_APPROVAL`, `EFFECTIVE`, `SUPERSEDED`, `WITHDRAWN`.
  Возврат = `PREPARED → DRAFT` + событие `EVALUATION_RETURNED`, причина обязательна.
- **C10 — полная схема Revision сразу.** Все скалярные поля ревизии (классификация/исход/judgement
  + `required_approval_route`) создаются в 9D-2A, **nullable в `DRAFT`**; enum-CHECK при `NOT NULL`;
  обязательность/матрица — на `prepare`. `rationale` **не** делать безусловным DB `NOT NULL`.

## Что создать

Модуль `09_Разработка/backend/app/quality/`:
- `engineering_evaluation_workflow.py` — константы (статусы, enum, роли, коды ошибок) и
  pure-функции проверок (без БД);
- `engineering_evaluation_models.py` — **7** ORM-таблиц схемы `quality` (Spec §3; C08:
  `evaluations`, `revisions`, `sources`, `criteria`, `exceptions`, `events`, `sequences`);
- `engineering_evaluation_schemas.py` — Pydantic-команды/DTO;
- `engineering_evaluation_repository.py` — доступ к данным;
- `engineering_evaluation_services.py` — команды lifecycle + validation matrix + сверка источников;
- `engineering_evaluation_api.py` — маршруты `/api/v1` (Spec §10), смонтировать в `app/main.py`
  рядом с роутером 9D-1;
- миграция `migrations/versions/<auto>_engineering_evaluation_core.py`
  (префикс/номер **не фиксировать заранее** — определить через `alembic heads`, см. решение A);
- тесты `backend/tests/test_engineering_evaluation_api.py` (Spec §13).

## Enum (строго; Spec §4)

```text
evaluation_outcome:       ACCEPTABLE · NONCONFORMING · CONDITIONALLY_ACCEPTABLE · INSUFFICIENT_DATA · NOT_APPLICABLE
recommended_disposition:  NONE · ACCEPT_AS_IS · REPAIR · REWORK · ADDITIONAL_INSPECTION · REJECT
criterion.comparison_result: COMPLIES · DOES_NOT_COMPLY · CONDITIONALLY_COMPLIES · NOT_APPLICABLE · INSUFFICIENT_DATA
source_role:              PRIMARY_EVIDENCE · SUPPORTING_EVIDENCE · ACCEPTANCE_CRITERIA · CONTEXT · REJECTED_EVIDENCE
confidence_level:         HIGH · MEDIUM · LOW
confirmed_severity:       NOT_APPLICABLE · MINOR · MAJOR · CRITICAL                 (канон ADR-019, реш. 3)
impact_scope:             NO_OPERATIONAL_IMPACT · DOCUMENT_HANDOVER_BLOCK · INSPECTION_ACCEPTANCE_BLOCK ·
                          FURTHER_PROCESSING_BLOCK · TECHNICAL_ACCEPTANCE_BLOCK · FULL_JOINT_BLOCK   (канон ADR-019, реш. 10)
classification:           CONFIRMED_DEFECT · NOT_CONFIRMED · TECHNOLOGICAL_DEVIATION · DOCUMENTATION_NONCONFORMITY ·
                          INSPECTION_PROCESS_NONCONFORMITY · MATERIAL_TRACEABILITY_NONCONFORMITY ·
                          PERSONNEL_QUALIFICATION_NONCONFORMITY · REQUIRES_ADDITIONAL_EVIDENCE · OUT_OF_SCOPE   (канон ADR-019 «Evaluation Classification»)
```

Матрица согласованности `classification → evaluation_outcome` (C07; иные → `EVAL_CLASSIFICATION_OUTCOME_MISMATCH`):

```text
CONFIRMED_DEFECT                       → NONCONFORMING | CONDITIONALLY_ACCEPTABLE
NOT_CONFIRMED                          → ACCEPTABLE
TECHNOLOGICAL_DEVIATION                → NONCONFORMING | CONDITIONALLY_ACCEPTABLE
DOCUMENTATION_NONCONFORMITY            → NONCONFORMING | CONDITIONALLY_ACCEPTABLE
INSPECTION_PROCESS_NONCONFORMITY       → NONCONFORMING | CONDITIONALLY_ACCEPTABLE
MATERIAL_TRACEABILITY_NONCONFORMITY    → NONCONFORMING | CONDITIONALLY_ACCEPTABLE
PERSONNEL_QUALIFICATION_NONCONFORMITY  → NONCONFORMING | CONDITIONALLY_ACCEPTABLE
REQUIRES_ADDITIONAL_EVIDENCE           → INSUFFICIENT_DATA
OUT_OF_SCOPE                           → NOT_APPLICABLE
```

Запрещено: `decision_type`, `ACCEPTABLE_AS_IS`, `NON_CONFORMING`, `REJECTABLE`, `INDETERMINATE`.
`AS_IS` встречается только в `recommended_disposition = ACCEPT_AS_IS`; исход-приёмка — `ACCEPTABLE`.

## Validation matrix (реализуй как pure-функции + проверки сервиса; Spec §8)

Проверка на `prepare-revision` (и повторная сверка источников на `fix`):

| `evaluation_outcome` | Критерии | Допустимые `recommended_disposition` | Exception | confidence | residual_risk | conditions | review_due |
|---|---|---|---|---|---|---|---|
| `ACCEPTABLE` | все `COMPLIES`/`NOT_APPLICABLE` | `NONE`, `ACCEPT_AS_IS` | **не требуется** | — | — | — | — |
| `CONDITIONALLY_ACCEPTABLE` | есть откл., покрытые исключением | `ACCEPT_AS_IS`,`REPAIR`,`REWORK`,`ADDITIONAL_INSPECTION` | да (на каждый откл. критерий) | да | да | да | да |
| `NONCONFORMING` | есть `DOES_NOT_COMPLY` | `REPAIR`,`REWORK`,`REJECT`,`ADDITIONAL_INSPECTION` | — | если LOW/косвенно | если риск | если заданы | если риск-ориентир. |
| `INSUFFICIENT_DATA` | есть `INSUFFICIENT_DATA` | `ADDITIONAL_INSPECTION`; обоснованно `REPAIR`/`REWORK`/`REJECT` | — | да | если MEDIUM/LOW/риск/врем.меры/условно | если заданы | если нужно будущее подтверждение или `ADDITIONAL_INSPECTION` (оконч. `REJECT` из-за нехватки доказательств — необяз.) |
| `NOT_APPLICABLE` | ≥1 критерий, **все** `comparison_result=NOT_APPLICABLE`, каждому `applicability_comment` | только `NONE` | — | — | — | — | — |

Сквозные правила:
- **`ACCEPT_AS_IS` не ограничивается только `CONDITIONALLY_ACCEPTABLE`.** Допустим при `ACCEPTABLE`
  (**без** Exception — отклонения нет) и при `CONDITIONALLY_ACCEPTABLE` (**с обязательным**
  Exception на каждый отклонённый критерий).
- `ACCEPTABLE` при наличии `DOES_NOT_COMPLY`/`CONDITIONALLY_COMPLIES`/`INSUFFICIENT_DATA` →
  `EVAL_OUTCOME_CRITERIA_MISMATCH`.
- `CONDITIONALLY_ACCEPTABLE`+`ACCEPT_AS_IS` без Exception → `EVAL_ACCEPT_WITHOUT_EXCEPTION`.
- `CONDITIONALLY_ACCEPTABLE` без `application_conditions` → `EVAL_CONDITIONS_REQUIRED`
  (также обязательны `confidence`, `residual_risk`, `review_due_at`).
- Одно `EngineeringException` — один критерий (`EVAL_EXCEPTION_CRITERION_INVALID`).
- `NOT_APPLICABLE`: ≥1 критерий, **все** `comparison_result=NOT_APPLICABLE`, каждому обязателен
  `applicability_comment` (`EVAL_APPLICABILITY_COMMENT_REQUIRED`); `recommended_disposition` только
  `NONE`. Формулировка «нет критериев» недопустима.
- `INSUFFICIENT_DATA`: **без** универсального `residual_risk=да`/`review_due_at=да` — обязательность
  по фактическим условиям (риск → `residual_risk`; будущее подтверждение/`ADDITIONAL_INSPECTION` →
  `review_due_at`). Окончательный `REJECT` из-за нехватки обязательных доказательств `review_due_at`
  не требует.

## Lifecycle и роли (Spec §5)

`DRAFT → PREPARED → FIXED → EFFECTIVE → SUPERSEDED` (+ `WITHDRAWN`, `PENDING_APPROVAL`; возврат
`PREPARED → DRAFT` событием `EVALUATION_RETURNED`, причина обязательна; `RETURNED_FOR_REVISION`
**не статус** — C09; набор статусов ровно семь). Подготовка (`prepare`) — роль `WELDING_ENGINEER` (`OGS_ENGINEER`);
фиксация (`fix`)/возврат/`set-effective` — `CHIEF_WELDER`. Подготовка и фиксация — **разными**
акторами (`EVAL_SAME_ACTOR_PREPARE_FIX`). Редактируется только `DRAFT`; после `PREPARED`
содержание неизменяемо; `return` не создаёт новую ревизию; `WITHDRAWN` конечный; одновременно
`EFFECTIVE` — одна ревизия; ретроактивное вступление запрещено.

**Подтверждение пересмотра (входит в 9D-2, Spec §7.8):** базовый двухролевой workflow без
внешнего согласования. `request-review-confirmation` (`WELDING_ENGINEER`, событие
`REVIEW_CONFIRMATION_REQUESTED`) → `confirm-review` (`CHIEF_WELDER`, событие `REVIEW_CONFIRMED`,
новый `review_due_at`). Инициатор и подтверждающий — разные роли (`EVAL_SAME_ACTOR_REVIEW`). Если
содержание изменилось — не подтверждать, а создавать новую ревизию (`EVAL_REVIEW_CONTENT_CHANGED`).
`REVIEW_OVERDUE` оценку не отменяет.

## Источники (Spec §7)

Ревизионный источник → обязателен `source_revision_id`. Неревизионный → `source_hash` +
`hash_schema_version` (профиль значимых полей — системный, не выбирается пользователем).
**Обязательные неревизионные профили первой реализации — `QUALITY_FINDING` и `JOINT`** (оба без
ревизионной сущности). Другие `source_entity_type` вводить только после проверки реальных
моделей и их ревизионности; неизвестный неревизионный тип не принимается. Сервис сверяет
источники перед `prepare` и перед `fix`; расхождение/недоступность блокируют
(`EVAL_SOURCE_STALE`/`EVAL_SOURCE_UNAVAILABLE`). Автоподмена/автообновление хэша запрещены —
только явный `reverify-sources`.

## Конвенции (обязательно)

- Схема `quality`; перечисления — CHECK, не native enum.
- Actor — `*_by_worker_id` Integer **без FK**; `version` optimistic locking; событий журнала
  не удалять/не менять (append-only), писать в одной транзакции с командой.
- Команды, не PATCH; `expected_version` в каждой команде; актор из `X-User-Id`; RBAC/scope на backend.
- Коды ошибок UPPERCASE (Spec §11); HTTP 403/404/409/422 по семантике 9D-1.
- Числа `numeric`, даты `timestamptz`. Русские комментарии/докстринги.

## Definition of Done

1. Все **7** моделей, схемы, репозиторий, сервис, API, миграция, тесты созданы.
2. `alembic upgrade head` проходит; таблицы 9D-1 не затронуты.
3. `pytest backend/tests/test_engineering_evaluation_api.py` зелёный, включая тесты-инварианты
   **C01/C04** (после `set-effective`: `QualityFinding.status` остаётся `UNDER_EVALUATION`, в
   `DISPOSITION_PENDING` не переходит, объекты исполнения и `FindingDisposition` не созданы) и
   **C02** (обязательность/согласованность/неизменяемость `confirmed_severity`, `impact_scope`;
   чтение из `EFFECTIVE`-ревизии).
4. **C03**: исправлен устаревший комментарий в `app/quality/quality_finding_workflow.py`
   (APPROVED → EFFECTIVE EngineeringEvaluationRevision); это единственная допустимая правка
   backend-кода 9D-1, поведение не меняется.
5. Линтер чист; канон ADR-021 и Spec не редактировались кодом; существующие 1057 тестов не падают.
6. Коммит: `feat(quality): implement EngineeringEvaluation core (Task 9D-2)` — **только по явной
   команде владельца**, отдельной веткой `feature/…`; push не выполнять без запроса.

## Зафиксированные решения (ранее открытые вопросы)

- **A. Номер Alembic-ревизии** — заранее **не фиксируется**. Во время реализации через
  `alembic heads` убедиться, что head ровно один, и взять его как `down_revision`; при
  нескольких heads сначала свести к одному.
- **B. Подтверждение пересмотра** — базовый двухролевой workflow `REVIEW_CONFIRMED`
  **входит в 9D-2** (без внешнего согласования; см. блок «Подтверждение пересмотра»).
- **C. Профили хэша источников** — для первой реализации обязательные неревизионные профили
  **`QUALITY_FINDING` и `JOINT`**; прочие типы — только после проверки реальных моделей и
  их ревизионности.

### Блок 9D-2B/2C — решения валидации и исключений (C11–C17)

Приняты при реализации 9D-2C (канон — ADR-021, детали — Spec §8). Последовательно C11 → C17:

- **C11. Агрегированный `ValidationResult`** — `prepare` возвращает все нарушения сразу, не first-fail.
- **C12. Read-only checker** — `check_prepare_completeness` без БД/записи `verified_at`/коммитов;
  свежесть источников передаётся из repository.
- **C13. `recommended_disposition` обязателен всегда** — при любом исходе; `NONE` — валидное значение.
- **C14. `INSUFFICIENT_DATA`** — обоснован наличием критерия `comparison_result=INSUFFICIENT_DATA`.
- **C15. Deviated criterion** — `comparison_result ∈ {DOES_NOT_COMPLY, CONDITIONALLY_COMPLIES}`
  (только он несёт `EngineeringException`).
- **C16. `confidence_level=LOW` → `confidence_note`** обязателен (`EVAL_CONFIDENCE_NOTE_REQUIRED`).
- **C17. Дубль `EngineeringException`** — repository pre-check + DB `UNIQUE(revision_id, criterion_id)`.

### Блок 9D-2E — решения хардненинга (зафиксировано 2026-07-19)

9D-2A–2D реализованы. Блок **9D-2E** дорабатывает три контура (канон ADR-021 не меняется,
схема БД не расширяется). Детали алгоритмов — Spec §16; канон — DECISIONS/ADR-021 (C18–C20).

- **C18. Копирование содержимого при `create_revision`** — новая ревизия копирует источники/
  критерии/исключения предыдущей: новые `id`/`revision_id`; исключения `is_draft_copy=true` c
  переназначением `criterion_id` на копию критерия; источники с `verified_at=NULL`; действующая
  ревизия **не** `SUPERSEDED` до `set_effective`; одна транзакция; одно событие `EVALUATION_CREATED`
  со счётчиками копий.
- **C19. `REVIEW_OVERDUE` идемпотентно** — не на `GET`, а команда `check-review-overdue`
  (`POST …/{id}/check-review-overdue`); одно событие на просроченный review-цикл
  (ключ — текущий `review_due_at`); `status`/`QualityFinding` не меняются; метод пригоден для
  планировщика.
- **C20. Fingerprint пересмотра** — `request` создаёт `correlation_id`, сохраняет
  `content_fingerprint`+`proposed_review_due_at`+`revision_version` в metadata; `confirm`
  пересчитывает fingerprint (расхождение → `EVAL_REVIEW_CONTENT_CHANGED`), применяет
  `proposed_review_due_at` из запроса, связывается тем же `correlation_id`; повторное
  подтверждение закрытого запроса запрещено (`EVAL_REVIEW_NOT_REQUESTED`); `EVAL_SAME_ACTOR_REVIEW`
  сохраняется.
  Состав fingerprint (детерминированный `sha256`, алгоритм — Spec §16): **decision — 13 полей**
  (`evaluation_outcome`, `classification`, `recommended_disposition`, `confirmed_severity`,
  `impact_scope`, `rationale`, `confidence_level`, `confidence_note`, `residual_risk`,
  `application_conditions`, `required_approval_route`, `revision_reason`, `supersedes_impact`);
  **sources — 8 полей** (`id`, `source_role`, `source_entity_type`, `source_entity_id`,
  `source_revision_id`, `source_hash`, `hash_schema_version`, `applicability_note`); плюс `criteria`
  и `exceptions` (Spec §16). **Исключены:** `status`/`version`; audit actor/time; `verified_at`;
  `review_due_at`; `is_draft_copy`; события и review-metadata.

Уточнять у владельца до кода только при новых неоднозначностях (модель/миграции/роли).
