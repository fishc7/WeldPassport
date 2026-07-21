# Task 9D-4A-4 — DefectDisposition Supersede Implementation Decision

Дата: 2026-07-21

Статус: **ACTIVE — implementation pending alignment with ADR-024; изменение реализации
запрещено до создания и принятия Task Implementation Specification.**

Task: `Task 9D-4A-4` · [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

Архитектурное основание:
[[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 (ACCEPTED) — DefectDisposition Lifecycle and Authority Model]].
Модель хранения: [[docs/project/DECISIONS#ADR-023. DefectDisposition — модель хранения уровня данных (Task 9D-4A-2)|ADR-023]].

Task Implementation Specification: **не создана**. Этот файл не разрешает изменение
backend, моделей, миграций, API или тестов.

Контур: Quality / DefectDisposition version replacement.

Этот ID не устанавливает supersede timing, lifecycle, роли, scope, CANCEL, visibility или
инварианты. Их источник — ADR-024. Здесь описана только ожидаемая техническая реализация
activate-time replacement при будущем приведении к принятому ADR.

## Endpoint/action mapping

| Операция | Ожидаемый HTTP mapping | Service method | Результат |
|---|---|---|---|
| Создать replacement | `POST /quality/defect-dispositions/{active_id}/replacement` | `create_replacement(...)` | Новая `DRAFT`, old остаётся `ACTIVE` |
| Изменить replacement DRAFT | `PATCH /quality/defect-dispositions/{new_id}` | `update_draft(...)` | Allow-list update + полный доказуемый before/after по ADR §D.1 |
| Подготовить/утвердить | существующий transition endpoint | `transition(...)` | Новая версия проходит PREPARE/APPROVE |
| Активировать replacement | transition `action=ACTIVATE` по `new_id` | `activate(...)` | Одна транзакция: old → SUPERSEDED, new → ACTIVE |
| Отменить replacement | transition `action=CANCEL` по `new_id` | `cancel(...)` | New → CANCELLED; old остаётся ACTIVE |

Существующий `/supersede`, который немедленно выключает old ACTIVE, не соответствует
ADR-024 и не должен оставаться вторым каноническим путём. Compatibility/removal определит
будущая Implementation Specification.

## Repository locking и transaction order

Техническая реализация следует ADR-024 §F и не определяет собственный scope:

`create_replacement`:

1. visibility-scoped lookup old ACTIVE без lock; невидимый ресурс → 404;
2. базовая authority check;
3. transaction и lock `DefectRoot`;
4. lock/reload old; повторные ownership/status/effective-role checks;
5. проверить, что old — текущая ACTIVE и другой open нет;
6. проверить reason, payload и idempotency replay;
7. создать DRAFT с `supersedes_disposition_id = old.id`;
8. записать `DISPOSITION_CREATED` с lineage и idempotency reference;
9. один commit.

`activate` replacement:

1. visibility-scoped lookup new и lineage old без lock;
2. базовая authority check;
3. transaction и lock `DefectRoot`;
4. lock old/new в порядке UUID;
5. повторить ownership, visibility, effective-role, действующий OTK-route, reason и
   idempotency checks;
6. проверить old ACTIVE, new APPROVED, один root и прямую lineage;
7. old → SUPERSEDED, new → ACTIVE;
8. записать связанные `DISPOSITION_SUPERSEDED` и `DISPOSITION_ACTIVATED`;
9. один commit.

Единый порядок всех команд: `DefectRoot → current ACTIVE → open/replacement`.

## Lineage и ограничения БД

- `new.supersedes_disposition_id = old.id` — каноническая прямая связь;
- replacement без ссылки на current ACTIVE запрещён;
- обратная связь выводится запросом и в MVP не обязательна;
- `defect_root_id` — владелец цепочки;
- partial UNIQUE по ACTIVE сохраняется;
- добавляется partial UNIQUE по `DRAFT/PREPARED/APPROVED`;
- preflight останавливает migration при дублях; данные автоматически не удаляются;
- причина подготовки replacement и ссылки old/new входят в audit contract.

## Audit sequence

- создание replacement: `DISPOSITION_CREATED` для new с old related id, reason и
  correlation/idempotency reference;
- UPDATE DRAFT: `DISPOSITION_DRAFT_UPDATED` позволяет восстановить каждое изменённое поле
  и before/after по ADR §D.1; no-op доменного события не создаёт;
- activation: `DISPOSITION_SUPERSEDED` old + `DISPOSITION_ACTIVATED` new в одной
  транзакции с взаимными related ids;
- cancellation: только `DISPOSITION_CANCELLED` new; old не меняется;
- повторный CREATED при activation не создаётся;
- actor берётся только из server context; event содержит immutable authorization snapshot
  роли/scope, действовавший на момент команды.

## Idempotency projection

Техническое хранение должно реализовать command-by-command matrix ADR-024 §I: ключ
обязателен для каждой mutating-команды; scope — `actor + command + aggregate + key`;
normalized payload hash, response snapshot, replay исходного результата, conflict при
другом payload, idempotency record в одной транзакции и UNIQUE/`IntegrityError` handling.
Конкретная таблица и retention определяются Implementation Specification/системной
политикой.

Повтор ACTIVATE с тем же ключом после timeout возвращает прежний успех, если new ACTIVE,
old SUPERSEDED и lineage совпадает. Новый ключ или иное состояние → domain conflict.

## API error mapping

| Ситуация | HTTP | Машинный код |
|---|---:|---|
| Old/new отсутствует или невидим | 404 | `DISPOSITION_NOT_FOUND` |
| Недостаточно authority | 403 | `DISPOSITION_PERMISSION_DENIED` |
| Old не current ACTIVE | 409 | `DISPOSITION_REPLACEMENT_REQUIRES_ACTIVE` |
| New не APPROVED | 409 | `DISPOSITION_INVALID_TRANSITION` |
| Уже существует open replacement | 409 | `DISPOSITION_ALREADY_OPEN` |
| Тот же key, другой payload | 409 | `DISPOSITION_IDEMPOTENCY_CONFLICT` |
| Причина отсутствует / payload некорректен | 422 | `DISPOSITION_REASON_REQUIRED` / validation |

## Технические последствия приведения к ADR

- replacement endpoint вместо текущего immediate supersede;
- root-first repository methods и deterministic multi-row lock;
- partial UNIQUE open с migration preflight;
- audit schema migration: related id, immutable actor role/scope/assignment snapshot,
  correlation/idempotency reference;
- idempotency persistence и unique conflict handling;
- compatibility plan для `/supersede`;
- rollback strategy без удаления исторических events;
- concurrency/rollback/replay tests.

Все конкретные schemas, migrations и compatibility details должны сначала появиться в
Task Implementation Specification.

## Test structure приведения к ADR

- replacement сохраняет old ACTIVE и создаёт одну связанную DRAFT;
- `1 ACTIVE + 1 open` разрешено, вторая open запрещена;
- две параллельные create replacement дают одного победителя;
- две параллельные activation дают одного победителя и два события;
- failure/rollback сохраняет old ACTIVE и new APPROVED;
- CANCEL replacement сохраняет old ACTIVE и разрешает последующий новый replacement;
- direct supersede-time path отсутствует;
- partial UNIQUE защищают ACTIVE/open;
- replay не создаёт строку/event повторно;
- чужой project скрывается до lock; authority и действующий OTK-route повторно проверяются
  после lock.

## Текущее расхождение реализации

Текущий `/supersede` немедленно переводит old `ACTIVE → SUPERSEDED` и создаёт DRAFT;
ACTIVE входит в open; create не блокирует root; activation не выполняет атомарную замену;
partial UNIQUE open и command idempotency отсутствуют. Эти детали не ратифицируются.
Backend, модели, миграции, API и тесты на текущем этапе не меняются.

## История и происхождение решения

- Первоначальный supersede-time текст появился в `docs/project/DECISIONS.md` в commit
  `d3a6d87` (2026-07-21) вместе с реализацией
  `feat(quality): add defect disposition supersede workflow`.
- Отдельного ID-файла в commit `d3a6d87` не существовало; файл создан позднее.
- ADR-024 предложил activate-time replacement; первая редакция ADR не прошла review и
  была переработана, не изменяя исторический commit.
- Git-история первоначального решения и реализации не переписывается.

## Где будет реализовываться после отдельного утверждённого bugfix

```text
09_Разработка/backend/app/quality/defect_disposition_workflow.py
09_Разработка/backend/app/quality/defect_disposition_policy.py
09_Разработка/backend/app/quality/defect_disposition_repository.py
09_Разработка/backend/app/quality/defect_disposition_services.py
09_Разработка/backend/app/quality/defect_disposition_schemas.py
09_Разработка/backend/app/quality/defect_disposition_api.py
09_Разработка/backend/app/quality/defect_disposition_models.py
новая Alembic revision (номер назначается только в bugfix)
09_Разработка/backend/tests/test_defect_disposition_workflow.py
09_Разработка/backend/tests/test_defect_disposition_migration.py
```
