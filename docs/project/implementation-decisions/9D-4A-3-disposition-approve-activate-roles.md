# Task 9D-4A-3 — DefectDisposition Approve/Activate Implementation Decision

Дата: 2026-07-21

Статус: **ACTIVE — implementation pending alignment with ADR-024; изменение реализации
запрещено до создания и принятия Task Implementation Specification.**

Task: `Task 9D-4A-3` · [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

Архитектурное основание:
[[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 (ACCEPTED) — DefectDisposition Lifecycle and Authority Model]].
Модель хранения: [[docs/project/DECISIONS#ADR-023. DefectDisposition — модель хранения уровня данных (Task 9D-4A-2)|ADR-023]].

Task Implementation Specification: [[docs/project/TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC|создана, DRAFT — awaiting independent review]]. Настоящий файл не заменяет её и не
разрешает изменение backend, моделей, миграций, API или тестов.

Контур: Quality / DefectDisposition workflow.

Этот файл не устанавливает термины, lifecycle, роли, scope, separation of duties,
override eligibility, CANCEL policy или доменные инварианты. Их источник — ADR-024.
Здесь фиксируется только ожидаемое техническое отображение команд на API, services,
audit и тесты при будущем приведении реализации к принятому ADR.

## Endpoint/action mapping

| Команда ADR-024 | Ожидаемый HTTP mapping | Service method | Event |
|---|---|---|---|
| `UPDATE_DRAFT` | `PATCH /quality/defect-dispositions/{id}` без status/actor/root/lineage | `update_draft(...)` | `DISPOSITION_DRAFT_UPDATED` |
| `PREPARE` | `POST /quality/defect-dispositions/{id}/transition`, `action=PREPARE` | `transition(..., action="PREPARE")` | `DISPOSITION_PREPARED` |
| `APPROVE` | тот же transition endpoint, `action=APPROVE` | `approve(...)` | `DISPOSITION_APPROVED` |
| `ACTIVATE` | тот же transition endpoint, `action=ACTIVATE` | `activate(...)` | `DISPOSITION_ACTIVATED` |
| `CANCEL` | тот же transition endpoint, `action=CANCEL` | `cancel(...)` | `DISPOSITION_CANCELLED` |

`APPROVE_OVERRIDE`, отдельный override endpoint и
`DISPOSITION_APPROVAL_OVERRIDDEN` **не входят в MVP**.

Actor для всех endpoint получается из `get_current_user_id`; actor/role/status/root/lineage
из request body не принимаются. Конкретные schemas и allow-list UPDATE определит будущая
Implementation Specification.

## Service/policy mapping

- workflow хранит action/event codes и переходы, импортированные из принятого ADR;
- policy ordinary APPROVE принимает только effective OTK role согласно authority/scope
  ADR; собственных исключений этот ID не вводит;
- policy APPROVE и ACTIVATE fail-closed подтверждает действующий OTK-route; ACTIVATE
  повторяет эту проверку под root lock непосредственно перед переходом;
- service UPDATE разрешает только allow-list DRAFT-полей и обеспечивает полный доказуемый
  before/after каждого изменения по ADR §D.1; no-op доменного события не создаёт;
- service CANCEL применяет creator-only OGS DRAFT rule и CHIEF rule из ADR;
- actor/effective role проверяются повторно после root/disposition locks;
- каждое mutating event получает immutable authorization snapshot роли/scope по ADR §E.1;
- исторический APPROVE проверяется по snapshot момента команды, а ACTIVATE отдельно
  проверяет текущий OTK-route, не требуя активной роли прежнего approver;
- все mutating-команды требуют `Idempotency-Key` и следуют command matrix ADR §I.

## Visibility, locks и transaction order

Техническая реализация обязана буквально следовать двухфазной схеме ADR-024 §F:
visibility-scoped lookup и базовое право до lock; затем transaction, root-first lock,
повторная загрузка и повторные ownership/status/effective-role checks.

Этот ID не определяет допустимые scope самостоятельно. Lock order:
`DefectRoot → current ACTIVE → open/replacement`; две disposition — UUID order. Один
commit включает state, event и idempotency record.

## API error mapping

| Ситуация | HTTP | Машинный код |
|---|---:|---|
| Ресурс отсутствует или невидим | 404 | `DISPOSITION_NOT_FOUND` |
| Недостаточно authority в разрешённом ADR scope | 403 | `DISPOSITION_PERMISSION_DENIED` |
| Состояние изменилось / переход недопустим | 409 | `DISPOSITION_INVALID_TRANSITION` |
| Повтор idempotency key с другим payload | 409 | `DISPOSITION_IDEMPOTENCY_CONFLICT` |
| Не указана обязательная причина | 422 | `DISPOSITION_REASON_REQUIRED` |
| Некорректное action/payload | 422 | `DISPOSITION_INVALID_ACTION` либо schema validation |

## Технические последствия приведения к ADR

- новый `UPDATE_DRAFT` endpoint/service/event;
- monotonic disposition version или эквивалентный optimistic token; UPDATE под root и
  disposition locks, гонки с PREPARE/CANCEL завершаются одним победителем и `409` для второй
  команды;
- UPDATE audit восстанавливает все изменённые поля и before/after; no-op не увеличивает
  version и не создаёт доменное событие;
- ordinary APPROVE без `CHIEF_WELDER`;
- отсутствие override endpoint/service/event в MVP;
- root-first lock для CREATE/UPDATE/transitions;
- creator identity check для OGS CANCEL DRAFT;
- idempotency persistence, response snapshot, payload hash и UNIQUE conflict handling для
  каждой mutating-команды;
- audit schema migration: immutable actor role/scope/assignment snapshot,
  correlation/idempotency reference, reason/reason_code и related disposition;
- новая Alembic revision, preflight/backfill/CHECK и rollback plan;
- тесты authority/scope, visibility-before-lock, concurrent commands и replay.

Точные модели/миграции/endpoint compatibility должны быть определены Task Implementation
Specification; этот список не является разрешением начать bugfix.

## Test strategy приведения к ADR

- APPROVE доступен только effective OTK в GLOBAL/том же PROJECT scope;
- без действующего OTK-route запрещены и APPROVE, и ACTIVATE; ACTIVATE повторно проверяет
  маршрут под root lock;
- COMPANY/SITE/LINE/ENGINEERING_DOCUMENT scope не даёт mutating authority;
- project company `INSPECTION` без effective OTK worker не даёт право APPROVE;
- override action/endpoint/event отсутствуют;
- actor из body отклоняется;
- UPDATE работает только для DRAFT и allow-list, после PREPARE запрещён;
- OGS отменяет только собственный DRAFT; CHIEF — любой open;
- visibility выполняется до lock, а effective role проверяется повторно после lock;
- повтор ключа не создаёт второй переход/event.
- повтор CANCEL следует матрице ADR: тот же запрос replay, другой actor/reason conflict;
- OTK authorization snapshot сохраняет scope момента APPROVE; кадровые изменения не
  переписывают событие.

## Текущее расхождение реализации

Текущий `DISPOSITION_APPROVE_ROLES` включает `CHIEF_WELDER`; отдельного UPDATE DRAFT
event нет; transition блокирует disposition до visibility; CANCEL policy и idempotency не
соответствуют принятому ADR. Эти детали не ратифицируются. Backend, модели, миграции, API и
тесты на текущем документационном этапе не меняются.

## История и происхождение решения

- Первоначальный полный текст появился в `docs/project/DECISIONS.md` в commit `dfaa87b`
  (2026-07-21) вместе с реализацией `feat(quality): add defect disposition workflow`.
- Отдельного файла Implementation Decision в commit `dfaa87b` не существовало; файл
  создан позднее 2026-07-21 при формализации уровня Implementation Decisions.
- Первая версия содержала архитектурные формулировки и ordinary CHIEF approve. Session 009
  и ADR-024 вынесли архитектурную часть на надлежащий уровень; после review override
  исключён из MVP.
- Git-история первоначального решения и реализации не переписывается.

## Где будет реализовываться после отдельного утверждённого bugfix

```text
09_Разработка/backend/app/quality/defect_disposition_workflow.py
09_Разработка/backend/app/quality/defect_disposition_policy.py
09_Разработка/backend/app/quality/defect_disposition_services.py
09_Разработка/backend/app/quality/defect_disposition_schemas.py
09_Разработка/backend/app/quality/defect_disposition_api.py
09_Разработка/backend/app/quality/defect_disposition_models.py
новая Alembic revision (номер назначается только в bugfix)
09_Разработка/backend/tests/test_defect_disposition_workflow.py
09_Разработка/backend/tests/test_defect_disposition_migration.py
```
