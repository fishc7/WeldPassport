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

## Что создать

Модуль `09_Разработка/backend/app/quality/`:
- `engineering_evaluation_workflow.py` — константы (статусы, enum, роли, коды ошибок) и
  pure-функции проверок (без БД);
- `engineering_evaluation_models.py` — 6 ORM-таблиц схемы `quality` (Spec §3);
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

`DRAFT → PREPARED → FIXED → EFFECTIVE → SUPERSEDED` (+ `RETURNED_FOR_REVISION`, `WITHDRAWN`,
`PENDING_APPROVAL`). Подготовка (`prepare`) — роль `WELDING_ENGINEER` (`OGS_ENGINEER`);
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

1. Все 6 моделей, схемы, репозиторий, сервис, API, миграция, тесты созданы.
2. `alembic upgrade head` проходит; таблицы 9D-1 не затронуты.
3. `pytest backend/tests/test_engineering_evaluation_api.py` зелёный, включая тест-инвариант
   9D-2-C01 (после `set-effective`: `QualityFinding.status` не изменён, объекты исполнения и
   `FindingDisposition` не созданы).
4. Линтер чист; канон ADR-021 и Spec не редактировались кодом.
5. Коммит: `feat(quality): implement EngineeringEvaluation core (Task 9D-2)` — **только по явной
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

Уточнять у владельца до кода только при новых неоднозначностях (модель/миграции/роли).
