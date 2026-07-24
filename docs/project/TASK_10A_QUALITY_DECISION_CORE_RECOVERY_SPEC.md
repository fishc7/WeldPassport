# Task 10A — QualityDecision Core Governance Recovery Specification

Дата восстановления: 2026-07-24.

Статус: **ACCEPTED FOR RECOVERY IMPLEMENTATION**.

Архитектурное основание:

- [[docs/project/ADR-027-quality-decision-core-canon|ADR-027 — QualityDecision Core Canon]]
  (`ACCEPTED`);
- [[docs/project/ARCHITECTURE_GOVERNANCE|Architecture Governance Framework]];
- согласование владельца от 2026-07-24 на полное исправление проблемных мест Task 10A
  в границах настоящей спецификации.

## 1. История и назначение recovery

ADR-027 был принят до начала Task 10A Implementation Block 1, однако полноценная
Task Implementation Specification до реализации не была создана. В рабочем дереве
присутствуют Models + Migration и Workflow + Repository + Service, а
`TASK_REGISTRY.md`, status-документы и `ARCHITECTURE.md` не отражают фактическое
состояние полностью.

Настоящий документ:

- восстанавливает отсутствующий уровень Task / Implementation Specification;
- не изображается документом, существовавшим до реализации;
- не объявляет существующий код автоматически принятым;
- определяет remediation и завершение API отдельными проверяемыми этапами.

## 2. Цель

Довести `QualityDecision Core` до согласованного MVP-контракта ADR-027:

```text
EngineeringEvaluationRevision
  → QualityDecision DRAFT
  → SUBMIT_FOR_REVIEW
  → UNDER_REVIEW
  → RETURN → DRAFT
  → DECIDE → DECIDED
  → системный supersede предыдущего DECIDED
```

Результат должен иметь доказуемую трассировку ADR → Task → Code → Tests →
Acceptance и командный HTTP API.

## 3. Границы

### 3.1. Входит

- governance recovery и синхронизация канонических/статусных документов;
- модели и новая корректирующая миграция idempotency records;
- workflow/repository/service remediation;
- разрешённое редактирование `DRAFT`;
- snapshot содержания на каждом `SUBMIT_FOR_REVIEW`;
- обязательный `Idempotency-Key` для пяти мутаций;
- Pydantic-схемы и командные FastAPI endpoints;
- профильные model/migration/service/API tests;
- отдельная приёмка каждого технического слоя.

### 3.2. Не входит

- AS-02: person-level SoD, несовместимые роли и расширение authorization snapshot;
- B-04, baseline/stamp/version marker transfer;
- runtime legacy compatibility profile и TEST-DB Foundation;
- создание `Defect` по `DEFECT_CONFIRMED`;
- `DefectDisposition`, Repair, Reinspection;
- импорт, документы, печатные формы, аналитика;
- unrelated refactoring;
- commit и push.

## 4. Восстановленная структура Task 10A

| Подблок | Содержание | Исходное состояние на 2026-07-24 |
|---|---|---|
| 10A-R | Governance recovery | отсутствовал |
| 10A-1 | Models + migration 25 | implementation present, acceptance not verified |
| 10A-1R | Idempotency model + correcting migration | remediation required |
| 10A-2 | Workflow + repository + service | implementation present, acceptance not verified |
| 10A-2R | Submit snapshot + idempotency orchestration | remediation required |
| 10A-3 | Schemas + command API + API tests | not implemented |

Task 10A имеет статус `in_progress`, пока все подблоки не прошли отдельную
приёмку. Наличие файлов или тестовых функций не означает `done`.

## 5. Q-D9 — редактирование DRAFT

Принят вариант Q-D9A:

- любой effective `WELDING_ENGINEER` в scope Joint может менять `summary` и состав
  `DecisionBasis` в `DRAFT`;
- `created_by_worker_id` остаётся автором создания, но не эксклюзивным владельцем
  черновика;
- `joint_id`, `project_id`, системный номер, status/result/approval/supersede-поля
  через update не меняются;
- требуется `expected_version`; stale version даёт domain conflict;
- минимум одно основание сохраняется;
- основания уникальны, принадлежат тому же Joint и имеют статус `EFFECTIVE`;
- отдельное audit-событие на каждое сохранение черновика не создаётся;
- после `SUBMIT_FOR_REVIEW` содержание неизменяемо до возможного `RETURN`.

Каждый `QUALITY_DECISION_SUBMITTED` фиксирует:

- version, отправленную на review;
- `summary`;
- канонически упорядоченный список `basis_revision_ids`;
- actor worker и actor role.

После `RETURN` следующий `SUBMIT` создаёт новый snapshot и тем самым сохраняет
историю итераций.

## 6. Q-D5 — idempotency

`Idempotency-Key` обязателен для:

- `CREATE`;
- `UPDATE_DRAFT`;
- `SUBMIT_FOR_REVIEW`;
- `RETURN`;
- `DECIDE`.

Область уникальности:

```text
actor_worker_id + command_type + target_type + target_id + idempotency_key
```

Для `CREATE` target — `JOINT`; для остальных команд — `QUALITY_DECISION`.

Тот же key и тот же нормализованный запрос возвращают сохранённый response
snapshot без повторной мутации, version increment, номера, audit или supersede.
Тот же key с другим payload возвращает `409 QD_IDEMPOTENCY_CONFLICT`. Новый key
после достигнутого результата проходит обычные lifecycle/version checks и не
считается replay.

В hash входят command, target, actor, нормализованные бизнес-поля и
`expected_version`, если применимо. Сам key в hash не входит. UUID оснований
сортируются, поскольку порядок не имеет бизнес-смысла.

## 7. Хранилище idempotency

Новая таблица:

`quality.quality_decision_idempotency_records`

Минимальные поля:

- `id UUID PK`;
- `actor_worker_id integer NOT NULL`;
- `command_type varchar(40) NOT NULL`;
- `target_type varchar(30) NOT NULL`;
- `target_id UUID NOT NULL`;
- `idempotency_key varchar(255) NOT NULL`;
- `request_hash varchar(64) NOT NULL`;
- `quality_decision_id UUID NOT NULL`;
- `response_status integer NOT NULL`;
- `response_snapshot jsonb NOT NULL`;
- `created_at timestamptz NOT NULL`.

Обязательны CHECK допустимых command/target, непустого key, response status,
FK на `quality_decisions`, индекс по `quality_decision_id` и UNIQUE области из
§6. Запись создаётся в той же транзакции, что state и audit. Rollback не оставляет
успешную запись. Конкурентный duplicate разрешается UNIQUE и повторным чтением
после `IntegrityError`.

Старая миграция 25 не изменяется. Создаётся следующая self-contained миграция 26.

## 8. Service contract

Service остаётся владельцем:

- lifecycle и role/scope checks;
- optimistic locking;
- validation оснований;
- supersede и basis ownership;
- audit;
- idempotency replay/conflict;
- единой транзакции.

Repository не принимает бизнес-решений. API только валидирует транспорт,
извлекает `X-User-Id`/`Idempotency-Key` и вызывает service.

Для точного replay service-команды возвращают стабильный command response,
построенный из сохранённого snapshot, а не перечитывают изменившийся позднее
агрегат.

## 9. HTTP API

Префикс: `/api/v1/quality/quality-decisions`.

| Method | Path | Назначение |
|---|---|---|
| POST | `/quality/quality-decisions` | CREATE |
| GET | `/quality/quality-decisions/{id}` | чтение |
| GET | `/quality/quality-decisions/{id}/bases` | основания |
| GET | `/quality/quality-decisions/{id}/events` | audit |
| PATCH | `/quality/quality-decisions/{id}/draft` | UPDATE_DRAFT |
| POST | `/quality/quality-decisions/{id}/submit-for-review` | SUBMIT_FOR_REVIEW |
| POST | `/quality/quality-decisions/{id}/return` | RETURN |
| POST | `/quality/quality-decisions/{id}/decide` | DECIDE |

Универсальный update статуса и generic transition endpoint запрещены.
`actor_worker_id`, status, approval и supersede-поля не принимаются из тела.
Все request-модели используют `extra="forbid"`.

## 10. Ошибки

- `401` — отсутствует/некорректен `X-User-Id`;
- `404` — ресурс отсутствует или скрыт scope;
- `409` — lifecycle/version/basis ownership/idempotency conflict;
- `422` — transport/domain validation, включая отсутствующий или пустой key;
- `403` — только там, где существующий проектный контракт явно раскрывает
  недостаток роли; текущий QD service сохраняет принятый паттерн скрытия scope.

Доменные коды сохраняются стабильными; добавляется
`QD_IDEMPOTENCY_CONFLICT`.

## 11. Зарегистрированные recovery gaps

- `GR-10A-01` — Task отсутствовал в registry;
- `GR-10A-02` — отсутствовала Task Specification;
- `GR-10A-03/04` — architecture/status drift;
- `GR-10A-05` — Q-D9 был реализован до формального разрешения;
- `GR-10A-06` — Q-D5 оставался открытым;
- `GR-10A-07` — acceptance evidence не подтверждён;
- `GR-10A-08` — отсутствовал API spec;
- `GR-10A-09` — AS-02 остаётся отдельным риском;
- `GR-10A-10` — SUBMIT не сохранял content snapshot;
- `GR-10A-11/12/13` — отсутствовали idempotency storage/orchestration/tests;
- `GR-10A-14` — прежнее утверждение о независимости Q-D5 от schema было неверным.

## 12. Этапы и gates

1. Governance documents и recovery provenance.
2. Model + migration 26; отдельно migration-contract review.
3. Workflow/repository/service remediation; отдельно service review.
4. Schemas/API/router; отдельно API review.
5. Профильная и регрессионная проверка.
6. Diff и итоговая приёмка.

Переход к следующему этапу допустим только после успешных проверок предыдущего.

## 13. Acceptance criteria

- Task 10A отражён в registry и производных документах без ложной истории;
- ADR-027 содержит датированное recovery-уточнение Q-D9/Q-D5;
- миграция 25 не изменена, миграция 26 self-contained;
- canonical metadata включает новую таблицу и не включает legacy/test;
- пять команд требуют key и имеют replay/conflict/rollback/race tests;
- replay не создаёт вторичных state/audit/sequence/supersede effects;
- SUBMIT audit содержит final content snapshot;
- lifecycle, роли и scope ADR-027 сохранены;
- API командный и не допускает direct status mutation;
- профильные и применимые regression tests проходят;
- Diff не содержит внерамочных изменений;
- commit/push отсутствуют до отдельного подтверждения.

## 14. Acceptance evidence (2026-07-24)

Статус scoped Diff: `accepted_uncommitted`.

- migration/canonical/graph/offline/pure-policy: `22 passed`;
- QualityDecision service + command API: `55 passed`;
- полный API lifecycle, все пять replay-команд, payload conflict и
  `401/403/404/409/422` проверены;
- два SUBMIT после RETURN сохраняют самостоятельные content snapshots;
- первичный command response и replay используют один стабильный snapshot;
- scoped Python compilation и `PROJECT_STATUS.yaml` parse: успешно;
- `git diff --check`: успешно, только информационные LF/CRLF warnings;
- migration 25 не изменена; revision 26 self-contained;
- AS-02, B-04, baseline/stamp, runtime profile, TEST-DB Foundation и
  Defect/Disposition/Repair/Reinspection side effects не включены;
- staging, commit и push не выполнялись.

Application-тесты запускались с test-only заглушкой legacy `workforce` router,
поскольку штатная композиция `app.main` сейчас блокируется известным, отдельным
runtime-profile/legacy дефектом. Production runtime-код этой заглушкой не изменён.
