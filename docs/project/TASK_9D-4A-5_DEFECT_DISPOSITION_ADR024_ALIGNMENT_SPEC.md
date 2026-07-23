# Task 9D-4A-5 — DefectDisposition ADR-024 Alignment Implementation Specification

## 1. Статус документа

```text
Task: 9D-4A-5 — DefectDisposition ADR-024 Alignment
Status: DRAFT — awaiting independent review
Тип: Implementation Specification
Дата: 2026-07-21
Реализация: NOT STARTED
```

Спецификация описывает обязательное приведение существующей реализации
`DefectDisposition` к принятому ADR-024. Документ не изменяет архитектуру и не подтверждает
соответствие текущего backend целевой модели.

Архитектурное основание:

- [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 — DefectDisposition Lifecycle and Authority Model]] (`ACCEPTED`);
- [[docs/project/implementation-decisions/9D-4A-3-disposition-approve-activate-roles|Implementation Decision 9D-4A-3]];
- [[docs/project/implementation-decisions/9D-4A-4-disposition-supersede-workflow|Implementation Decision 9D-4A-4]];
- [[docs/ARCHITECTURE|Каноническая архитектура WeldPassport]];
- существующая реализация в `09_Разработка/backend/app/quality/` и миграции
  `20260721_22`–`20260721_24` — только источник current-state evidence, не нормативный источник.

## Execution Gate

```text
Task 9D-4A-5A MUST NOT START until all mandatory prerequisites are closed.
```

Обязательные внешние prerequisites не входят в scope Task 9D-4A-5:

| Gate | Условие закрытия | Доказательство |
|---|---|---|
| `MIGRATION_FOUNDATION_READY` | Audit finding B-03 закрыт; `alembic check` выполняется без исключения; `target_metadata`/`include_object` видит `defect_dispositions`, `defect_disposition_events`, будущую idempotency table и связанные quality-таблицы | отдельный принятый diff B-03 + успешный `CMD-PREREQ-ALEMBIC-CHECK` |
| `DATABASE_BASELINE_DECIDED` | Audit finding B-04 закрыт либо принято отдельное архитектурное решение о доказуемом создании clean database; clean upgrade доступен в безопасной test environment | решение/commit B-04 + `CMD-PREREQ-CLEAN-UPGRADE` |
| `TEST-DB-FOUNDATION` (`TEST_DATABASE_ISOLATED`) | существует обязательный `TEST_DATABASE_URL`; нет fallback на application DSN; guard запрещает production/work DB до Alembic, Session и cleanup; foundation реализована отдельным принятым Task/diff | `CMD-PREREQ-TEST-DB-GUARD` |
| `AUTHENTICATION_BOUNDARY_ACCEPTED` | B-01/authentication закрыты и существует принятая authenticated identity boundary; `X-User-Id` является untrusted client input и допускается только как non-production development assumption, которая не закрывает gate | принятое auth-решение и доказательство server-authenticated actor context |

Неизвестные commit/Task IDs для B-03/B-04 не выдумываются. До появления канонических Tasks
они обозначаются как `EXTERNAL PREREQUISITE — audit finding B-03/B-04`. Статус 9D-4A-5
остаётся каноническим `planned`, а execution явно заблокирован prerequisites.

```text
execution_dependencies:
- EXTERNAL PREREQUISITE — audit finding B-03 / migration foundation
- EXTERNAL PREREQUISITE — audit finding B-04 / clean database baseline
- EXTERNAL PREREQUISITE — TEST-DB-FOUNDATION
- EXTERNAL PREREQUISITE — authenticated actor boundary for production
```

Закрытие B-03, B-04, TEST-DB-FOUNDATION и authentication не входит в Task 9D-4A-5 и должно
быть принято отдельными diff/review до начала 5A.

## 2. Цель и обязательность полного объёма

Цель — подготовить один проверяемый контракт реализации, который устраняет все известные
расхождения `DefectDisposition` с ADR-024. Реализация выполняется по одной спецификации,
разбитой на последовательно принимаемые блоки 9D-4A-5A–9D-4A-5E.

Все требования ADR-024 обязательны. Сокращённый вариант, исправляющий только роли APPROVE и
supersede timing, не допускается: он оставил бы нарушения по lifecycle, audit snapshot,
idempotency, блокировкам, ограничениям БД и API.

## 3. Scope

### 3.1. Входит

- additive/transformational Alembic migration после `20260721_24_disp_supersede`;
- модели `DefectDisposition`, `DefectDispositionEvent` и новая quality-таблица idempotency;
- lifecycle, policy, RBAC/scope и проверка действующего OTK-route;
- root-first locking, repository/service transaction boundary и optimistic version;
- CREATE, UPDATE_DRAFT, PREPARE, APPROVE, ACTIVATE, CANCEL;
- activate-time replacement;
- отдельные command endpoints, Pydantic-контракты и error mapping;
- deprecated legacy `/transition` и `/supersede`, возвращающие только `410 Gone`;
- migration/model/service/API/RBAC/audit/idempotency/concurrency/OpenAPI tests;
- синхронизация профильной документации после приёмки реализации.

### 3.2. Не входит

- `APPROVE_OVERRIDE` и `DISPOSITION_APPROVAL_OVERRIDDEN`;
- fallback ADR-019 для `DefectDisposition`;
- ProductionHold, Repair, Reweld, Reinspection, NCR, CAPA и customer approval;
- изменение модели `project_companies` или признание роли `INSPECTION` доказательством OTK-route;
- PROJECT-scoped `CHIEF_WELDER`;
- полный общий idempotency framework для всех модулей;
- автоматический cleanup idempotency-записей;
- удаление legacy `/supersede` в текущем релизе;
- `superseded_by_disposition_id`;
- изменение ADR-024, Tasks B-01…B-04 или иных модулей без отдельного решения.
- исправление общей authentication boundary или доверия к `X-User-Id`;
- создание test DB foundation и исправление Alembic metadata/include-object foundation.

До появления общей retention policy idempotency-записи сохраняются без автоматического
удаления. Удаление deprecated endpoint оформляется отдельным breaking-change Task следующего
релиза.

## 4. Current-state gap analysis

| # | Требование ADR-024 | Текущее состояние | Требуемое изменение | Блок |
|---:|---|---|---|---|
| 1 | APPROVE только OTK | APPROVE допускает CHIEF | исключить CHIEF, разрешить только effective OTK | 5B |
| 2 | Нет APPROVE_OVERRIDE | policy содержит override-ветвь | удалить action/role/reason/event contract | 5B/5D |
| 3 | ACTIVATE только CHIEF | роль в основном совпадает | зафиксировать только effective GLOBAL CHIEF | 5B |
| 4 | OTK GLOBAL/PROJECT | общий helper допускает иерархические scope | отдельная exact-scope policy | 5B |
| 5 | CHIEF GLOBAL-only | общий helper технически шире | fail-closed exact GLOBAL assignment | 5B |
| 6 | OTK-route при APPROVE | отдельной проверки нет | server-side route query и повторная проверка под lock | 5B/5C |
| 7 | текущий OTK-route при ACTIVATE | проверки нет | повторно проверить route, не текущую роль старого approver | 5B/5C |
| 8 | исторический APPROVE snapshot | event хранит только actor/role | типизированный immutable snapshot | 5A/5B |
| 9 | UPDATE_DRAFT | отсутствует | allow-list, version, before/after audit, no-op | 5B–5D |
| 10 | OGS отменяет только свой DRAFT | policy этого не обеспечивает | creator/status/scope check | 5B/5C |
| 11 | CHIEF отменяет open states | APPROVED → CANCEL запрещён | разрешить DRAFT/PREPARED/APPROVED | 5B/5C |
| 12 | activate-time replacement | `/supersede` сразу меняет ACTIVE | replacement DRAFT; swap только ACTIVATE | 5C/5D |
| 13 | old ACTIVE до ACTIVATE | old сразу SUPERSEDED | сохранять ACTIVE до атомарного swap | 5C |
| 14 | 1 ACTIVE + 1 open | ACTIVE ошибочно считается open | разделить active/open queries | 5A/5C |
| 15 | root lock | обычные transitions блокируют disposition | всегда сначала `DefectRoot FOR UPDATE` | 5C |
| 16 | visibility до lock | transition/supersede lock выполняется раньше | двухфазный lookup | 5C |
| 17 | reload/recheck после lock | проверки неполны | повторить ownership, visibility, version, role, route, state | 5C |
| 18 | partial UNIQUE ACTIVE | существует | сохранить и проверить имя/предикат | 5A |
| 19 | partial UNIQUE open | отсутствует | добавить для DRAFT/PREPARED/APPROVED | 5A |
| 20 | idempotency всех mutating commands | отсутствует | reservation-first quality-таблица, required key, буквальный replay/conflict contract ADR-024 | 5A/5C/5D |
| 21 | before/after UPDATE audit | UPDATE отсутствует | JSON change set + version before/after | 5A/5C |
| 22 | related old/new disposition | только metadata/lineage частично | typed `related_disposition_id` в двух событиях | 5A/5C |
| 23 | role/scope snapshot | scope и assignment отсутствуют | typed snapshot columns | 5A/5B |
| 24 | actor только из authenticated auth boundary | текущий `get_current_user_id` только парсит untrusted `X-User-Id`; клиент может подставить worker ID | внутри модуля запретить mass assignment и отдельный actor override; authentication вынести в обязательный external prerequisite | 5D + external gate |
| 25 | append-only audit | события добавляются | запрет UPDATE/DELETE и писать с state в одной транзакции | 5A/5C |
| 26 | one transaction/one commit | repository вызывает commit | commit только service boundary | 5C |
| 27 | нет прямого ACTIVE→SUPERSEDED | есть отдельная команда | удалить семантику; legacy endpoint только 410 | 5B–5D |
| 28 | нет ACTIVE→CANCELLED | policy уже запрещает | сохранить и покрыть regression | 5B/5E |
| 29 | кадровые изменения не отменяют APPROVE | доказательного snapshot нет | ACTIVATE читает immutable APPROVE event | 5A–5C |
| 30 | migration/backfill existing records | отсутствует | preflight, safe backfill, legacy marker, fail-closed | 5A |

Дополнительные gaps: отсутствуют `version`, `updated_at`, `DISPOSITION_DRAFT_UPDATED`,
correlation/idempotency reference; event response скрывает часть audit; generic `/transition`
не выражает отдельные command contracts.

## 5. Декомпозиция и границы приёмки

### 5A — Persistence и собственные тесты

Модели, логически разделённая expand/migrate/contract migration, preflight, typed event
snapshot, idempotency persistence, constraints/indexes, clean/current-head upgrade,
downgrade guard и partial UNIQUE tests. Блок не требует готового API, но не начинается до
закрытия Execution Gate и не разворачивается отдельно в runtime.

### 5B — Workflow/Policy и собственные unit tests

Transition table, exact-scope authority, effective assignment resolver, OTK-route,
authorization snapshot builder, UPDATE_DRAFT allow-list, CANCEL, отсутствие override и pure
policy/workflow tests.

### 5C — Repository/Services/Idempotency и integration tests

Одна autobegin transaction, reservation-first idempotency, visibility/root-first locking,
forced reload, one commit, activate-time replacement, audit, concurrency и тест отсутствия
repository commit.

### 5D — API/Schemas и API/OpenAPI tests

Отдельные endpoints/schemas/errors, обязательный `Idempotency-Key`, сохранённый public CREATE,
deprecated `/transition` и `/supersede` с `410`, mass-assignment и OpenAPI tests.

### 5E — Cross-block acceptance

Только full migration verification, full quality/full suite regression, global OpenAPI
duplicate check, `alembic check` и traceability 30/30. 5E не откладывает тесты 5A–5D.

Каждый блок имеет exact files, test IDs, команды, бинарную acceptance и review checkpoint.
Переход к следующему блоку разрешён только после приёмки предыдущего. Объединять 5B/5C без
отдельного решения пользователя запрещено.

## 6. Точная модель данных

### 6.1. `quality.defect_dispositions`

Существующие identity/content/lineage-поля сохраняются: `id`, `defect_root_id`,
`supersedes_disposition_id`, `decision_type`, `status`, `justification`, `comment`,
`created_by_worker_id`, `created_at`, `approved_by_worker_id`, `approved_at`.

Добавить:

| Поле | Тип / nullability | Назначение |
|---|---|---|
| `version` | integer NOT NULL, server default `1` | optimistic content/state version; `ck_defect_dispositions_version_positive: version >= 1` |
| `updated_at` | timestamptz NOT NULL, server default `now()` | при INSERT совпадает с server time; каждое реальное изменение явно устанавливает `now()` в service; ORM `onupdate` не является единственным механизмом |
| `prepared_by_worker_id` / `prepared_at` | integer / timestamptz NULL | быстрое чтение и state invariant PREPARED+ |
| `activated_by_worker_id` / `activated_at` | integer / timestamptz NULL | быстрое чтение и state invariant ACTIVE+ |
| `cancelled_by_worker_id` / `cancelled_at` | integer / timestamptz NULL | state invariant CANCELLED |
| `superseded_by_worker_id` / `superseded_at` | integer / timestamptz NULL | state invariant SUPERSEDED |

`*_by_worker_id` остаются без FK в переходной HR-модели, как существующие audit actor
поля. Каждая actor/time пара либо полностью NULL, либо полностью заполнена.

Полный authorization snapshot и каноническая история причин в disposition не копируются.
Поля actor/time здесь присутствуют только для текущего состояния, быстрого чтения и
DB-инвариантов; доказательная история остаётся в append-only events. Существующее
`supersede_reason` сохраняется как nullable legacy-колонка на безопасный переходный период,
новый workflow её не записывает и API не выдаёт как каноническую причину. Её физическое
удаление возможно только отдельной data-retention migration после проверки истории.

`superseded_by_disposition_id` не добавляется. Обратная связь вычисляется запросом по
`DefectDisposition.supersedes_disposition_id`.

Изменение content/status увеличивает `version` ровно на 1 и обновляет `updated_at`. No-op
UPDATE_DRAFT не меняет ни одно из этих полей. При replacement activation версии old и new
увеличиваются независимо в одной транзакции.

### 6.2. Literal state constraints и indexes

Каждая actor/time-пара защищена отдельным CHECK вида
`(field_at IS NULL) = (field_by_worker_id IS NULL)`:

- `ck_defect_dispositions_prepared_pair`;
- существующий `ck_defect_dispositions_approved_pair`;
- `ck_defect_dispositions_activated_pair`;
- `ck_defect_dispositions_cancelled_pair`;
- `ck_defect_dispositions_superseded_pair`.

`ck_defect_dispositions_state_audit_fields` задаёт буквальную дизъюнкцию:

```sql
(status = 'DRAFT'
 AND prepared_at IS NULL AND approved_at IS NULL AND activated_at IS NULL
 AND cancelled_at IS NULL AND superseded_at IS NULL)
OR
(status = 'PREPARED'
 AND prepared_at IS NOT NULL AND approved_at IS NULL AND activated_at IS NULL
 AND cancelled_at IS NULL AND superseded_at IS NULL)
OR
(status = 'APPROVED'
 AND prepared_at IS NOT NULL AND approved_at IS NOT NULL AND activated_at IS NULL
 AND cancelled_at IS NULL AND superseded_at IS NULL)
OR
(status = 'ACTIVE'
 AND prepared_at IS NOT NULL AND approved_at IS NOT NULL AND activated_at IS NOT NULL
 AND cancelled_at IS NULL AND superseded_at IS NULL)
OR
(status = 'SUPERSEDED'
 AND prepared_at IS NOT NULL AND approved_at IS NOT NULL AND activated_at IS NOT NULL
 AND cancelled_at IS NULL AND superseded_at IS NOT NULL)
OR
(status = 'CANCELLED'
 AND cancelled_at IS NOT NULL AND activated_at IS NULL AND superseded_at IS NULL
 AND (
   (prepared_at IS NULL AND approved_at IS NULL)
   OR (prepared_at IS NOT NULL AND approved_at IS NULL)
   OR (prepared_at IS NOT NULL AND approved_at IS NOT NULL)
 ))
```

Для CANCELLED prepared/approved пары сохраняют фактическую достигнутую стадию. Причины
ACTIVATE/CANCEL являются каноническими event data и проверяются service/event contract; CHECK
между aggregate и event невозможен. Lineage root equality также повторно проверяется сервисом
под root lock. Существующий `ck_defect_dispositions_no_self_supersede` сохраняется.

Partial UNIQUE:

```sql
CREATE UNIQUE INDEX uq_defect_dispositions_one_active_per_root
ON quality.defect_dispositions (defect_root_id)
WHERE status = 'ACTIVE';

CREATE UNIQUE INDEX uq_defect_dispositions_one_open_per_root
ON quality.defect_dispositions (defect_root_id)
WHERE status IN ('DRAFT', 'PREPARED', 'APPROVED');
```

Таким образом допустимы `1 ACTIVE + 1 open`, `0 ACTIVE + 1 open` и `1 ACTIVE + 0 open`.

### 6.3. `quality.defect_disposition_events`

Событие остаётся append-only. Для expand-совместимости существующий `actor_role` не
переименовывается и не удаляется в этом Task: добавить `actor_role_code`, backfill известного
значения, новый код пишет `actor_role_code`, а legacy-колонка становится read-only deprecated.
Её удаление — отдельная cleanup migration. Добавить типизированные колонки:

| Поле | Тип | Правило |
|---|---|---|
| `related_disposition_id` | uuid NULL FK `quality.defect_dispositions(id)` RESTRICT | old/new связь при replacement |
| `reason_code` | varchar(50) NULL | машинная причина, когда применимо |
| `actor_role_code` | varchar(40) NULL | роль actor на момент команды; NOT NULL логически для VERIFIED |
| `actor_scope_type` | varchar(30) NULL | `GLOBAL`/`PROJECT` для VERIFIED |
| `actor_scope_id` | uuid NULL | NULL для GLOBAL; project UUID для PROJECT |
| `actor_role_assignment_id` | integer NULL, **без FK** | исторический scalar фактического `hr.worker_roles.id`; HR assignment mutable/deletable |
| `actor_role_valid_from` / `actor_role_valid_to` | date NULL | фактические nullable `WorkerRole.valid_from/valid_to` |
| `authority_checked_at` | timestamptz NULL | server timestamp policy check |
| `authority_project_id` | uuid NULL FK `project.projects(id)` RESTRICT | проект целевого агрегата |
| `authorization_policy_result` | varchar(30) NULL | для VERIFIED только `AUTHORIZED` |
| `authority_source` | varchar(20) NULL | `GLOBAL` либо `PROJECT` |
| `authorization_snapshot_status` | varchar(50) NOT NULL | VERIFIED или LEGACY marker |
| `correlation_id` | uuid NULL | одна бизнес-команда/транзакция |
| `idempotency_record_id` | uuid NULL FK `quality.defect_disposition_idempotency_records(id)` RESTRICT | обязательна для нового domain event; NULL только legacy |
| `content_version_before` / `content_version_after` | integer NULL | для нового VERIFIED CREATE: `NULL/1`; для UPDATE, transitions и replacement swap: `after = before + 1`; для LEGACY допускается недоказуемая NULL-пара |

Выбран **вариант A — отдельные типизированные колонки**: snapshot имеет фиксированный
нормативный состав, требует SQL constraints и используется при ACTIVATE. JSON-only ослабил
бы валидацию; гибрид дублировал бы те же факты. `metadata JSONB` используется только для
command-specific данных, прежде всего `UPDATE_DRAFT` change set:

```json
{
  "changes": {
    "justification": {"before": "...", "after": "..."},
    "comment": {"before": null, "after": "..."}
  }
}
```

Для новых событий `authorization_snapshot_status = 'VERIFIED_AUTHORIZATION_SNAPSHOT'`.
Migration использует следующие буквальные predicates без вариативной трактовки:

```sql
CONSTRAINT ck_dd_events_snapshot_status CHECK (
  authorization_snapshot_status IN (
    'VERIFIED_AUTHORIZATION_SNAPSHOT',
    'LEGACY_AUTHORIZATION_SNAPSHOT'
  )
),
CONSTRAINT ck_dd_events_verified_snapshot CHECK (
  authorization_snapshot_status <> 'VERIFIED_AUTHORIZATION_SNAPSHOT'
  OR (
    actor_role_code IS NOT NULL
    AND actor_scope_type IN ('GLOBAL', 'PROJECT')
    AND actor_role_assignment_id IS NOT NULL
    AND authority_checked_at IS NOT NULL
    AND authority_project_id IS NOT NULL
    AND authority_source IN ('GLOBAL', 'PROJECT')
    AND authorization_policy_result = 'AUTHORIZED'
    AND correlation_id IS NOT NULL
    AND idempotency_record_id IS NOT NULL
  )
),
CONSTRAINT ck_dd_events_scope_consistency CHECK (
  authorization_snapshot_status <> 'VERIFIED_AUTHORIZATION_SNAPSHOT'
  OR (
    (actor_scope_type = 'GLOBAL'
     AND actor_scope_id IS NULL
     AND authority_source = 'GLOBAL')
    OR
    (actor_scope_type = 'PROJECT'
     AND actor_scope_id = authority_project_id
     AND authority_source = 'PROJECT')
  )
),
CONSTRAINT ck_dd_events_role_interval CHECK (
  actor_role_valid_from IS NULL
  OR actor_role_valid_to IS NULL
  OR actor_role_valid_from <= actor_role_valid_to
),
CONSTRAINT ck_dd_events_legacy_snapshot CHECK (
  authorization_snapshot_status <> 'LEGACY_AUTHORIZATION_SNAPSHOT'
  OR (
    authorization_policy_result IS NULL
    AND idempotency_record_id IS NULL
  )
),
CONSTRAINT ck_dd_events_version_pair CHECK (
  (
    authorization_snapshot_status = 'LEGACY_AUTHORIZATION_SNAPSHOT'
    AND (
      (content_version_before IS NULL AND content_version_after IS NULL)
      OR
      (content_version_before IS NOT NULL AND content_version_after IS NOT NULL
       AND content_version_after >= content_version_before)
    )
  )
  OR
  (
    authorization_snapshot_status = 'VERIFIED_AUTHORIZATION_SNAPSHOT'
    AND (
      (event_type = 'DISPOSITION_CREATED'
       AND content_version_before IS NULL AND content_version_after = 1)
      OR
      (event_type <> 'DISPOSITION_CREATED'
       AND content_version_before IS NOT NULL
       AND content_version_after = content_version_before + 1)
    )
  )
),
CONSTRAINT ck_dd_events_verified_shape CHECK (
  authorization_snapshot_status <> 'VERIFIED_AUTHORIZATION_SNAPSHOT'
  OR (
    (event_type = 'DISPOSITION_CREATED' AND action = 'CREATE'
     AND previous_status IS NULL AND new_status = 'DRAFT')
    OR
    (event_type = 'DISPOSITION_DRAFT_UPDATED' AND action = 'UPDATE_DRAFT'
     AND previous_status = 'DRAFT' AND new_status = 'DRAFT')
    OR
    (event_type = 'DISPOSITION_PREPARED' AND action = 'PREPARE'
     AND previous_status = 'DRAFT' AND new_status = 'PREPARED')
    OR
    (event_type = 'DISPOSITION_APPROVED' AND action = 'APPROVE'
     AND previous_status = 'PREPARED' AND new_status = 'APPROVED')
    OR
    (event_type = 'DISPOSITION_ACTIVATED' AND action = 'ACTIVATE'
     AND previous_status = 'APPROVED' AND new_status = 'ACTIVE')
    OR
    (event_type = 'DISPOSITION_SUPERSEDED' AND action = 'ACTIVATE'
     AND previous_status = 'ACTIVE' AND new_status = 'SUPERSEDED')
    OR
    (event_type = 'DISPOSITION_CANCELLED' AND action = 'CANCEL'
     AND previous_status IN ('DRAFT', 'PREPARED', 'APPROVED')
     AND new_status = 'CANCELLED')
  )
),
CONSTRAINT ck_dd_events_reason_shape CHECK (
  authorization_snapshot_status <> 'VERIFIED_AUTHORIZATION_SNAPSHOT'
  OR event_type NOT IN (
    'DISPOSITION_ACTIVATED', 'DISPOSITION_SUPERSEDED', 'DISPOSITION_CANCELLED'
  )
  OR (reason IS NOT NULL AND length(btrim(reason)) > 0)
);
```

Существующий `ck_defect_disposition_events_type` заменяется тем же именем и literal tuple из
семи event codes ниже. Для LEGACY version-пара либо неизвестна целиком, либо сохраняет только
доказуемые значения; неизвестные role/scope/assignment/validity остаются NULL, а
`authorization_policy_result='AUTHORIZED'` для LEGACY запрещён. Правило `+1` обязательно для
каждого нового VERIFIED event.

`actor_role_assignment_id` намеренно не имеет FK: изменение/удаление HR assignment не может
повредить доказательную историю. `idempotency_record_id` получает FK RESTRICT, потому что
автоматический cleanup в Task отсутствует; будущая retention policy обязана пересмотреть эту
связь отдельным решением.

Полный список event codes:

- `DISPOSITION_CREATED`;
- `DISPOSITION_DRAFT_UPDATED`;
- `DISPOSITION_PREPARED`;
- `DISPOSITION_APPROVED`;
- `DISPOSITION_ACTIVATED`;
- `DISPOSITION_SUPERSEDED`;
- `DISPOSITION_CANCELLED`.

```sql
CONSTRAINT ck_defect_disposition_events_type CHECK (
  event_type IN (
    'DISPOSITION_CREATED',
    'DISPOSITION_DRAFT_UPDATED',
    'DISPOSITION_PREPARED',
    'DISPOSITION_APPROVED',
    'DISPOSITION_ACTIVATED',
    'DISPOSITION_SUPERSEDED',
    'DISPOSITION_CANCELLED'
  )
);
```

Override-event отсутствует. UPDATE/DELETE событий запрещены application/repository contract;
при наличии DB-role separation права runtime-role должны быть INSERT/SELECT без UPDATE/DELETE.

### 6.4. `quality.defect_disposition_idempotency_records`

| Поле | Тип / правило |
|---|---|
| `id` | uuid PK, application default UUID4 |
| `actor_worker_id` | integer NOT NULL |
| `command` | varchar(30) NOT NULL; `ck_dd_idempotency_command` по literal tuple `CREATE/UPDATE_DRAFT/PREPARE/APPROVE/ACTIVATE/CANCEL` |
| `target_aggregate_type` | varchar(30) NOT NULL; `ck_dd_idempotency_aggregate_type` по `DEFECT_ROOT/DEFECT_DISPOSITION` |
| `target_aggregate_id` | uuid NOT NULL |
| `idempotency_key` | varchar(200) NOT NULL, trimmed non-empty |
| `normalized_payload_hash` | char(64) NOT NULL, lowercase SHA-256 hex |
| `result_status` | varchar(20) NOT NULL: `IN_PROGRESS`/`COMPLETED` |
| `response_status_code` | smallint NULL; для COMPLETED обязательно 200–299 |
| `response_body` | JSONB NULL; для COMPLETED обязательно |
| `response_body_size_bytes` | integer NULL; для COMPLETED обязательно, `0..65536` |
| `created_at` | timestamptz NOT NULL DEFAULT now() |
| `completed_at` | timestamptz NULL |

`uq_dd_idempotency_scope_key`:
`(actor_worker_id, command, target_aggregate_type, target_aggregate_id, idempotency_key)`.
`ck_dd_idempotency_result_shape` требует: IN_PROGRESS → response/completed fields NULL;
COMPLETED → response/status/size/completed_at заполнены. `ck_dd_idempotency_key_not_blank`,
`ck_dd_idempotency_payload_hash`, `ck_dd_idempotency_response_size` задаются literal SQL.
Индекс `ix_dd_idempotency_created_at` создаётся для будущей retention policy, но cleanup в
этом Task отсутствует.

Literal predicates migration:

```sql
CONSTRAINT ck_dd_idempotency_command CHECK (
  command IN (
    'CREATE',
    'UPDATE_DRAFT',
    'PREPARE',
    'APPROVE',
    'ACTIVATE',
    'CANCEL'
  )
),
CONSTRAINT ck_dd_idempotency_aggregate_type CHECK (
  target_aggregate_type IN ('DEFECT_ROOT', 'DEFECT_DISPOSITION')
),
CONSTRAINT ck_dd_idempotency_result_shape CHECK (
  (result_status = 'IN_PROGRESS' AND response_status_code IS NULL
   AND response_body IS NULL AND response_body_size_bytes IS NULL AND completed_at IS NULL)
  OR
  (result_status = 'COMPLETED' AND response_status_code BETWEEN 200 AND 299
   AND response_body IS NOT NULL AND response_body_size_bytes IS NOT NULL
   AND completed_at IS NOT NULL)
),
CONSTRAINT ck_dd_idempotency_key_not_blank CHECK (btrim(idempotency_key) <> ''),
CONSTRAINT ck_dd_idempotency_payload_hash CHECK (
  normalized_payload_hash ~ '^[0-9a-f]{64}$'
),
CONSTRAINT ck_dd_idempotency_response_size CHECK (
  response_body_size_bytes IS NULL OR response_body_size_bytes BETWEEN 0 AND 65536
);
```

Migration использует эти буквальные SQL tuples напрямую. Python enum, импорт application-кода
или вычисляемый список значений не являются частью migration contract и не допускаются.

Для CREATE aggregate = `defect_root_id`; для UPDATE/PREPARE/APPROVE/ACTIVATE/CANCEL =
`disposition_id`. Запись успешного результата создаётся в той же транзакции, что state и
events. Failed validation/403/404/409/410 не создают successful idempotency record.

Response snapshot — только безопасный `DefectDispositionRead`, без headers, authorization
snapshot, secrets, SQL или stack trace. Canonical JSON: UTF-8/RFC 8259, sorted keys, compact
separators, lowercase UUID, ISO-8601 UTC timestamps и enum strings. Максимум — 65,536 байт;
превышение вызывает внутренний `DISPOSITION_RESPONSE_SNAPSHOT_TOO_LARGE`, rollback всей
команды и не создаёт COMPLETED record. Request hash использует тот же canonical JSON contract
для нормализованных business fields и optimistic tokens.

## 7. Migration plan

### 7.1. Preflight — только чтение, fail-closed

До constraints/backfill проверить и вывести идентификаторы конфликтов:

1. более одной ACTIVE или более одной DRAFT/PREPARED/APPROVED на root;
2. self-link, cross-root lineage, cycle и replacement без существующего predecessor;
3. статусы, не входящие в шесть канонических значений;
4. orphan events и несоответствие event root/disposition root;
5. APPROVED/ACTIVE/SUPERSEDED без соответствующего APPROVED event либо с невозможной
   chronology; существующий APPROVED event с недоказуемым historical assignment не является
   migration blocker и обрабатывается как LEGACY по §7.2;
6. несовместимые actor/time пары и chronology (`created ≤ prepared ≤ approved ≤ activated ≤ superseded`);
7. legacy half-replacement: old уже SUPERSEDED, new ещё open и на root нет ACTIVE;
8. дубли будущей idempotency uniqueness (если таблица уже существует после interrupted deploy).

Автоматическое удаление, слияние или выдумывание scope запрещено. Fail-fast применяется к
нескольким ACTIVE/open, невозможным status combinations, orphan/cross-root/cyclic lineage,
неразрешимой replacement lineage и данным, нарушающим будущие core lifecycle constraints.
Обнаруженный legacy half-replacement — **операционный data blocker**: требуется отдельный
утверждённый remediation plan; migration не назначает ACTIVE предположением.

Несколько возможных historical role assignments **не блокируют** migration. Такое событие
получает `LEGACY_AUTHORIZATION_SNAPSHOT`; известный `actor_worker_id` сохраняется,
assignment/scope/validity остаются NULL, а event id попадает в migration report с category
`LEGACY_APPROVED_REQUIRES_MANUAL_RESOLUTION`, если disposition уже `APPROVED`.

### 7.2. Safe backfill

- `version = 1` для существующих rows;
- `updated_at = max(created_at, latest event.created_at)`;
- state actor/time брать только из однозначного соответствующего события; существующие
  approved columns сверять, а не молча перезаписывать;
- `project_id` event выводить через доказуемую цепочку disposition → root → joint → project;
- недоказуемый historical event snapshot маркировать `LEGACY_AUTHORIZATION_SNAPSHOT`; actor/role
  переносить как известные факты, scope/assignment/validity не придумывать;
- `related_disposition_id` backfill только при однозначной lineage/event связи;
- для старых событий correlation/idempotency оставлять NULL;
- idempotency records задним числом не создавать;
- legacy `supersede_reason` и исторические события не удалять.

Legacy APPROVED не блокирует upgrade и остаётся `APPROVED`, но не может быть активирована:
ACTIVATE возвращает `409 DISPOSITION_APPROVAL_SNAPSHOT_UNVERIFIABLE`. Старый event не
переписывается и не повышается до VERIFIED по предположению. Manual resolution выполняется
явно GLOBAL CHIEF: проверить запись из migration report, выполнить canonical CANCEL с
`reason_code='LEGACY_APPROVAL_UNVERIFIABLE'`, затем создать новую DRAFT и провести её через
PREPARE → APPROVE → ACTIVATE с новым VERIFIED snapshot. Автоматические cancel/recreate и
автоматическая реконструкция authority запрещены.

Migration report выводит только безопасные identifiers (`defect_root_id`, `disposition_id`,
`event_id`) и category; content/reasons/ПДн не печатаются. При blocker upgrade aborts до
contract phase; после отдельного remediation оператор повторяет тот же upgrade с начала.

### 7.3. Deploy model: SINGLE MAINTENANCE DEPLOYMENT

5A–5D реализуются и принимаются отдельными review-блоками/commits, но runtime activation
выполняется одним maintenance window только после готовности 5A–5D и прохождения обязательных
5E gate tests. Rolling deployment запрещён: current backend не заполняет новые state/snapshot
поля и не совместим с contract constraints. Old backend не запускается после contract phase.

Логическая migration strategy — expand/migrate/contract, даже если один будущий Alembic
revision технически выполнит все фазы внутри maintenance window.

#### Expand

1. создать idempotency table;
2. добавить новые nullable disposition/event columns;
3. сохранить старый `actor_role` и все старые write columns;
4. не включать несовместимые NOT NULL/state CHECK/open UNIQUE;
5. использовать только локальные literal tuples; imports вида `from app...` в исторической
   migration запрещены.

#### Migrate

1. выполнить preflight и вывести migration report;
2. выполнить доказуемый backfill;
3. маркировать недоказуемые snapshots как LEGACY;
4. повторить preflight;
5. развернуть совместимый backend 5B–5D при остановленных внешних writes.

#### Contract

1. включить NOT NULL/CHECK и `uq_defect_dispositions_one_open_per_root`;
2. переключить новый backend на `actor_role_code`, reservation-first idempotency и новый
   lifecycle;
3. деактивировать старые write paths;
4. `/transition` и `/supersede` перевести на deprecated 410 handlers;
5. выполнить 5E acceptance до снятия maintenance window.

Contract migration нельзя применять отдельно от совместимого кода. Независимая приёмка 5A
означает review/тестирование на isolated test DB, а не самостоятельный production deploy.

### 7.4. Downgrade

Downgrade fail-closed и не удаляет доказательную историю. Перед обратным изменением проверить
наличие DRAFT_UPDATED events, idempotency records, `1 ACTIVE + 1 open`, APPROVED→CANCELLED и
новых version > 1. Если новые semantics использовались, downgrade прекращается с явной
диагностикой; применяется forward-fix.

Только для неиспользованной migration допустимо удалить новые indexes/table/columns в
обратном порядке. `actor_role` в этом Task не переименовывается, поэтому обратного rename нет.
Исторические events или state rows никогда не удаляются ради downgrade. Временный operational
rollback API сохраняет additive schema и блокирует mutating commands, а не возвращает
supersede-time поведение.

## 8. Workflow contract

| From | Command | To | Actor | Обязательные условия | Event |
|---|---|---|---|---|---|
| — | CREATE | DRAFT | OGS/CHIEF | visible confirmed root; нет open; при ACTIVE — expected active и validated lineage | `DISPOSITION_CREATED` |
| DRAFT | UPDATE_DRAFT | DRAFT | OGS/CHIEF | allow-list; expected version; real change либо no-op | `DISPOSITION_DRAFT_UPDATED` только при change |
| DRAFT | PREPARE | PREPARED | OGS/CHIEF | content complete; expected version | `DISPOSITION_PREPARED` |
| PREPARED | APPROVE | APPROVED | OTK | effective GLOBAL/matching PROJECT; OTK-route; expected version | `DISPOSITION_APPROVED` |
| APPROVED | ACTIVATE | ACTIVE | GLOBAL CHIEF | reason; verified historical APPROVE; current OTK-route; expected version/lineage | `DISPOSITION_ACTIVATED` (+ old `DISPOSITION_SUPERSEDED`) |
| DRAFT | CANCEL | CANCELLED | creator OGS или CHIEF | reason; OGS только собственный DRAFT | `DISPOSITION_CANCELLED` |
| PREPARED/APPROVED | CANCEL | CANCELLED | GLOBAL CHIEF | reason; expected version | `DISPOSITION_CANCELLED` |

Прямые ACTIVE→SUPERSEDED и ACTIVE→CANCELLED отсутствуют. SUPERSEDED/CANCELLED терминальны.

### 8.1. CREATE и replacement

После normalize/hash и reservation/replay сервис в той же transaction выполняет root
visibility и базовую role-проверку, затем блокирует root и повторяет ownership/authority.
Под root lock читаются current ACTIVE и open.
Первое создание допустимо только при отсутствии ACTIVE и open: `supersedes_disposition_id` и
`expected_active_version` должны быть NULL. Replacement creation допустимо при наличии ACTIVE
и отсутствии open: оба поля обязательны и должны совпасть с current ACTIVE; сервер валидирует
root/project/lineage/version под root lock. Старая ACTIVE не меняется.

Конфликты разделяются буквально:

- любая существующая open version → `409 DISPOSITION_ALREADY_OPEN`;
- initial intent при существующей ACTIVE без replacement lineage →
  `409 DISPOSITION_ACTIVE_CONFLICT`;
- replacement со stale/wrong ACTIVE id или version → `409 DISPOSITION_LINEAGE_CONFLICT` либо
  `409 DISPOSITION_ACTIVE_CONFLICT` согласно фактической причине;
- корректный replacement intent при `1 ACTIVE + 0 open` → новая DRAFT, не conflict.

### 8.2. UPDATE_DRAFT

Allow-list: `decision_type`, `justification`, `comment`. Поля id/root/project/status/lineage,
actor/time/version из body запрещены. `decision_type` и `justification` при передаче не могут
быть NULL; justification trimmed non-empty; `comment` может очищаться NULL.

Change set строится после нормализации под lock. Реальное изменение повышает version и пишет
ровно один event с before/after. No-op возвращает current representation, не меняет version,
не пишет domain event; idempotency record для replay создаётся.

### 8.3. PREPARE

Проверяет DRAFT, expected version и completeness (`decision_type`, непустой justification и
все будущие явно утверждённые content requirements). Замораживает content, заполняет
prepared pair, повышает version, пишет PREPARED.

### 8.4. APPROVE

Разрешён только actor с effective `OTK_INSPECTOR` assignment в GLOBAL или matching PROJECT.
Отдельно должен существовать хотя бы один effective OTK route проекта. Actor assignment
может одновременно доказывать route. После root lock проверки повторяются. APPROVE snapshot
полностью записывается в event; disposition получает approved pair и новую version.

### 8.5. ACTIVATE

Actor — только effective GLOBAL `CHIEF_WELDER`. Проверяются expected version, APPROVED,
доказуемый VERIFIED APPROVE event и текущий OTK-route; текущая роль прежнего approver не
требуется. Legacy APPROVED без VERIFIED snapshot всегда получает
`409 DISPOSITION_APPROVAL_SNAPSHOT_UNVERIFIABLE` до mutation. Reason trimmed non-empty.

Initial activation требует отсутствия ACTIVE. Replacement activation требует current ACTIVE,
равной `supersedes_disposition_id` и expected active id/version. В одной транзакции old
ACTIVE→SUPERSEDED и new APPROVED→ACTIVE, обе version увеличиваются, создаются два события с
одинаковыми correlation/idempotency references и взаимным `related_disposition_id`.

### 8.6. CANCEL

OGS может отменить только созданный им DRAFT и только при подходящем GLOBAL/matching PROJECT
assignment. GLOBAL CHIEF может отменить любую DRAFT/PREPARED/APPROVED. Reason обязателен.
Отмена replacement не меняет old ACTIVE. ACTIVE/SUPERSEDED/CANCELLED не отменяются.

## 9. Actor boundary, visibility, authority и OTK-route

Текущий `get_current_user_id` лишь парсит клиентский `X-User-Id`. `X-User-Id` — **untrusted
client input**, а не аутентифицированная server-side identity; клиент может подставить чужой
worker ID. Task 9D-4A-5 не реализует и не доказывает authentication. Внутри quality-модуля actor
берётся только из auth context: body/query/path не могут переопределить actor, role или scope.
Это закрывает mass assignment, но не создаёт внешнюю границу доверия. `X-User-Id` используется
только как non-production development assumption. Эта assumption не закрывает Execution Gate и не
разрешает production acceptance Task 9D-4A-5. Production acceptance и начало
5A заблокированы до принятия `AUTHENTICATION_BOUNDARY_ACCEPTED` с server-authenticated actor context.

```text
MODULE ACTOR MASS ASSIGNMENT CLOSED
SYSTEM AUTHENTICATION TRUST NOT CLOSED
```

Effective assignment означает: active worker; `worker_role.is_active`; текущая дата входит
в `valid_from/valid_to`; точный role code; разрешённый command scope.

| Command | GLOBAL | matching PROJECT | остальные scope |
|---|---|---|---|
| CREATE/UPDATE/PREPARE | OGS, CHIEF | только OGS | запрещены |
| APPROVE | OTK | OTK | запрещены |
| ACTIVATE | только CHIEF | запрещён | запрещены |
| CANCEL DRAFT | CHIEF или creator OGS | creator OGS | запрещены |
| CANCEL PREPARED/APPROVED | только CHIEF | запрещён | запрещены |

`COMPANY`, `SITE`, `LINE`, `ENGINEERING_DOCUMENT` не расширяются иерархическим helper.
`project_companies.INSPECTION` не даёт actor право и не доказывает OTK-route. Route query
ищет хотя бы одного active worker с effective OTK GLOBAL/matching PROJECT и fail-closed при
ошибке/неоднозначности.

Предлагаемые typed interfaces:

```python
@dataclass(frozen=True)
class EffectiveRoleAssignment:
    assignment_id: int
    worker_id: int
    role_code: str
    scope_type: str
    scope_id: UUID | None
    valid_from: date | None
    valid_to: date | None

def resolve_command_assignment(
    *, actor_worker_id: int, project_id: UUID, command: str, on_date: date
) -> EffectiveRoleAssignment

def has_effective_otk_route(*, project_id: UUID, on_date: date) -> bool

def build_authorization_snapshot(
    *, assignment: EffectiveRoleAssignment, project_id: UUID, checked_at: datetime
) -> AuthorizationSnapshot
```

Если несколько assignments дают одно право, resolver выбирает детерминированно: точный
PROJECT предпочтительнее GLOBAL для OGS/OTK, затем минимальный `worker_roles.id`; выбор и
конкретный assignment фиксируются snapshot. Для CHIEF допустим только GLOBAL.

Скрытый объект → 404 до lock. Видимый объект без authority → 403. После root lock все
visibility/ownership/authority/state/version/route checks повторяются по свежим данным.

## 10. Repository contract

Repository не вызывает `commit()` и не скрывает transaction boundary. Допустимы `add`,
`flush`, `refresh`; commit/rollback принадлежат service/API unit of work.

```python
get_root_visible(root_id, actor_worker_id) -> RootContext | None       # no lock
get_disposition_visible(disposition_id, actor_worker_id) -> DispositionContext | None
lock_root(root_id) -> DefectRoot                                      # FOR UPDATE
get_disposition_for_root(disposition_id, root_id) -> DefectDisposition
lock_dispositions_for_root(root_id, ids: Sequence[UUID]) -> list[...] # UUID order
find_active_for_root(root_id) -> DefectDisposition | None
find_open_for_root(root_id) -> DefectDisposition | None
find_verified_approval_event(disposition_id) -> DefectDispositionEvent | None
find_idempotency(scope: IdempotencyScope) -> IdempotencyRecord | None
lock_idempotency(scope: IdempotencyScope) -> IdempotencyRecord | None
try_reserve_idempotency(scope, payload_hash) -> IdempotencyRecord
complete_idempotency(record_id, response_status, response_body) -> None
add_disposition(value) -> None
add_event(value) -> None
add_idempotency(value) -> None
flush() -> None
```

Lock order неизменен:

```text
DefectRoot → current ACTIVE disposition → open/replacement disposition
```

Если нужны две disposition, `SELECT ... FOR UPDATE` использует детерминированный UUID order.
Ни один метод не блокирует disposition до root.

## 11. Service contract и transaction boundary

```python
create(root_id, command, actor_worker_id, idempotency_key) -> CommandResult
update_draft(disposition_id, command, actor_worker_id, idempotency_key) -> CommandResult
prepare(disposition_id, command, actor_worker_id, idempotency_key) -> CommandResult
approve(disposition_id, command, actor_worker_id, idempotency_key) -> CommandResult
activate(disposition_id, command, actor_worker_id, idempotency_key) -> CommandResult
cancel(disposition_id, command, actor_worker_id, idempotency_key) -> CommandResult
```

Actor поступает только из принятого auth context, надёжность которого является external gate.
Одна чистая `Session` и одна обычная autobegin transaction охватывают всю команду. Первый
idempotency SELECT/INSERT открывает transaction; после него нельзя вызывать `session.begin()`
или создавать вложенную outer transaction.
Savepoint разрешён только для idempotency UNIQUE race. Каждый mutating service выполняет:

1. нормализацию полного payload и вычисление SHA-256;
2. в savepoint попытку reservation `IN_PROGRESS` **до любых изменяемых domain checks**;
3. при idempotency UNIQUE violation — rollback только savepoint, lock/read existing row:
   другой hash → 409; `COMPLETED` → сохранённый replay; конкурентный `IN_PROGRESS` ожидается
   до завершения owning transaction и перечитывается; после rollback владельца insert retry;
4. если replay не найден — visibility lookup без row lock: hidden target → 404;
5. базовую authority validation: denied actor → 403;
6. root lock и детерминированные disposition locks;
7. принудительный reload через `populate_existing=True`, `session.refresh()` либо новый
   `SELECT ... FOR UPDATE`; pre-lock ORM objects не используются для mutation;
8. повтор visibility/ownership/authority/state/version/route; перед domain conflict повторно
   lock/read reservation, чтобы concurrent same-key completion вернуть replay;
9. state mutation + append events + safe response snapshot + reservation `COMPLETED`;
10. один service-level commit; при любой ошибке единый rollback state/audit/reservation.

Reservation, domain rows, events и response snapshot находятся в одной transaction и не
видимы как успешный reusable result до commit. Repository commit запрещён.

## 12. API contract

Префикс: `/api/v1/quality`. Read endpoints сохраняются, mutating contract становится:

| Метод | Маршрут | Назначение | Success |
|---|---|---|---:|
| POST | `/defect-dispositions` | сохранённый public initial/replacement CREATE | 201 |
| PATCH | `/defect-dispositions/{id}` | UPDATE_DRAFT | 200 |
| POST | `/defect-dispositions/{id}/prepare` | PREPARE | 200 |
| POST | `/defect-dispositions/{id}/approve` | APPROVE | 200 |
| POST | `/defect-dispositions/{id}/activate` | ACTIVATE/swap | 200 |
| POST | `/defect-dispositions/{id}/cancel` | CANCEL | 200 |
| POST | `/defect-dispositions/{id}/transition` | legacy generic tombstone | всегда 410 |
| POST | `/defect-dispositions/{id}/supersede` | legacy tombstone | всегда 410 |

Полный public path с префиксом: `POST /api/v1/quality/defect-dispositions`; второй root-nested
CREATE в Task не вводится. `Idempotency-Key` — required header для первых шести mutating
routes. Generic `/{id}/transition` остаётся на один переходный релиз в OpenAPI с
`deprecated: true`, всегда возвращает `410 LEGACY_ENDPOINT_GONE`, не создаёт transaction или
побочных эффектов и направляет клиента на отдельные command endpoints.

### 12.1. Legacy `/transition` и `/supersede`

Оба маршрута остаются видимыми один переходный релиз с `deprecated: true` и всегда возвращают:

```json
{
  "detail": {
    "code": "LEGACY_ENDPOINT_GONE",
    "message": "Legacy supersede-time workflow is unavailable; use the activate-time replacement workflow."
  }
}
```

HTTP status — `410 Gone`. Каждый handler не создаёт service/unit-of-work, не читает/меняет aggregate,
не создаёт audit event или idempotency record и не воспроизводит старую семантику. Даже
несуществующий id возвращает тот же 410: endpoint contract важнее resource lookup. Удаление
маршрута — отдельный breaking-change Task следующего релиза.

## 13. Pydantic schemas

Все input schemas: `ConfigDict(extra="forbid")`; actor/role/status/root/lineage/system time
запрещены в body.

- `DefectDispositionCreateRequest`: обязательный `defect_root_id`, `decision_type`,
  `justification`, `comment?`, `supersedes_disposition_id?`, `expected_active_version?`;
  последние два поля либо оба NULL для initial, либо оба заданы для replacement.
- `DefectDispositionUpdateDraftRequest`: `expected_version`, optional allow-list fields;
  должен быть передан хотя бы один content field.
- `DefectDispositionPrepareCommand`: `expected_version`.
- `DefectDispositionApproveCommand`: `expected_version`, optional `comment`.
- `DefectDispositionActivateCommand`: `expected_version`, `reason`, optional pair
  `expected_active_disposition_id/expected_active_version`.
- `DefectDispositionCancelCommand`: `expected_version`, `reason`, optional `reason_code`.
- `DefectDispositionRead`: все content/state/version/lineage и компактные state actor/time;
  без полного authorization snapshot.
- `DefectDispositionEventRead`: typed snapshot, related id, versions, reason/code,
  correlation/idempotency reference и command-specific metadata.
- `DomainErrorRead`: `detail.code`, `detail.message`, optional safe context.

## 14. Error contract

| HTTP | Код | Условие |
|---:|---|---|
| 403 | `DISPOSITION_PERMISSION_DENIED` | visible object, но нет exact effective authority |
| 404 | `DISPOSITION_NOT_FOUND` | disposition не существует или скрыта visibility |
| 404 | `DISPOSITION_ROOT_NOT_FOUND` | root не существует или скрыт |
| 409 | `DISPOSITION_INVALID_TRANSITION` | неверный status/command |
| 409 | `DISPOSITION_VERSION_CONFLICT` | expected version не совпала |
| 409 | `DISPOSITION_ALREADY_OPEN` | уже есть open version |
| 409 | `DISPOSITION_ACTIVE_CONFLICT` | active отсутствует/не совпадает/изменился |
| 409 | `DISPOSITION_LINEAGE_CONFLICT` | replacement lineage не совпадает с current ACTIVE |
| 409 | `DISPOSITION_OTK_ROUTE_UNAVAILABLE` | нет действующего OTK-route |
| 409 | `DISPOSITION_APPROVAL_SNAPSHOT_UNVERIFIABLE` | APPROVE event отсутствует/legacy/неполон |
| 409 | `DISPOSITION_IDEMPOTENCY_CONFLICT` | тот же scope/key, другой normalized payload |
| 410 | `LEGACY_ENDPOINT_GONE` | любой вызов legacy `/transition` или `/supersede` |
| 422 | `DISPOSITION_IDEMPOTENCY_KEY_REQUIRED` | нет/пустой key |
| 422 | `DISPOSITION_REASON_REQUIRED` | обязательная причина пуста |
| 422 | `DISPOSITION_JUSTIFICATION_REQUIRED` | justification пуста |
| 422 | `DISPOSITION_INVALID_PAYLOAD` | schema/content/expected pair invalid |

DB uniqueness/serialization errors преобразуются в стабильный 409 после повторного чтения
актуального состояния; raw `IntegrityError` наружу не выходит.

Migration diagnostics не являются HTTP/API errors. Preflight сообщает безопасные
`defect_root_id`/disposition IDs и вид нарушения без content/ПДн, после чего abort выполняется
до изменения схемы или данных.

## 15. Audit contract

Каждая успешная изменяющая команда пишет ровно одно событие, кроме replacement ACTIVATE,
которая пишет `DISPOSITION_ACTIVATED` для new и `DISPOSITION_SUPERSEDED` для old. Оба события имеют один correlation id,
одну idempotency reference и взаимный related id. CREATE replacement пишет только `DISPOSITION_CREATED`
для new; old ACTIVE не получает события до ACTIVATE.

APPROVE event — каноническое историческое доказательство полномочий. Последующее увольнение,
деактивация или истечение назначения approver не изменяет event и не отменяет approval.
ACTIVATE пишет собственный CHIEF snapshot и ссылается на уже существующий APPROVE факт.

No-op UPDATE и idempotent replay не создают событий. Отклонённые запросы могут попадать в
общий security/request audit, но не в domain event table.

## 16. Idempotency matrix

Матрица является буквальной реализацией ADR-024 §I, строки CREATE–CANCEL. Для каждой команды
ключ обязателен; отсутствие/пустой key → 422. Same key + same normalized payload/hash всегда
возвращает сохранённый response без второй mutation/event; same key + другой payload/hash →
`409 DISPOSITION_IDEMPOTENCY_CONFLICT` (семантика `IDEMPOTENCY_KEY_REUSED`).

| Command | Новый key после уже достигнутого состояния |
|---|---|
| CREATE | существующая open → `DISPOSITION_ALREADY_OPEN`; ACTIVE без replacement intent → `DISPOSITION_ACTIVE_CONFLICT`; корректный новый replacement intent с expected ACTIVE/lineage и без open → новый DRAFT; target aggregate = `defect_root_id` |
| UPDATE_DRAFT | current version + normalized no-op → success без version/event; stale expected version → 409; иначе новый update |
| PREPARE | same actor + same content version + same full normalized payload → success без второго event; иначе 409 |
| APPROVE | same OTK actor + same approved content version + same full normalized payload → success без второго event; иначе 409 |
| ACTIVATE | уже ACTIVE → 409; исключение только replay исходного key, поэтому timeout retry обязан повторять тот же key |
| CANCEL | same actor + same normalized reason/reason_code + same target version → success без второго event; иначе 409 |

Full normalized payload включает expected version, lineage и все command-specific fields.
CREATE target = `defect_root_id`; остальные commands target = `disposition_id`. Hash строится из
canonical UTF-8 JSON: sorted keys, stable scalar/date/UUID encoding, отсутствующие optional
поля нормализуются единообразно. Actor входит в uniqueness и не берётся из payload. Response
snapshot сериализуется до commit и при replay возвращается без пересериализации текущего объекта.

## 17. Concurrency matrix

| A | B | Protection | Lock order | State seen by second tx | Winner | Loser result | Audit count | Idempotency count | Rollback expectation |
|---|---|---|---|---|---|---|---:|---:|---|
| initial CREATE key A | initial CREATE key B | root lock + open UNIQUE | reservation→root | open DRAFT after wait | A: 201 | B: 409 lifecycle | 1 | 1 COMPLETED; B rolled back | no partial row/event |
| replacement CREATE A | replacement CREATE B | root lock + open UNIQUE | reservation→root→ACTIVE | open replacement | A: 201 | B: 409 | 1 | 1 | old ACTIVE unchanged |
| UPDATE_DRAFT | PREPARE | root lock + version | reservation→root→draft | new version/status | first command | second 409 | 1 | 1 | loser fully rolled back |
| APPROVE | CANCEL PREPARED | root lock + version/state | reservation→root→target | winner state | first command | second 409 | 1 | 1 | one terminal outcome |
| APPROVE key A | APPROVE key B | root lock + ADR replay rule | reservation→root→target | APPROVED + actor/version | A | B replay only if exact rule, else 409 | 1 | 1 or 2 COMPLETED success records | no second event |
| ACTIVATE initial | competing CREATE | root lock + ACTIVE/open UNIQUE | reservation→root→rows | ACTIVE/open after winner | first command | domain result after fresh read | 1–2 | only committed commands | invariants preserved |
| replacement ACTIVATE A | replacement ACTIVATE B | root lock + lineage/version | reservation→root→ACTIVE→replacement | swapped lineage | A | B 409 | 2 | 1 | no second swap |
| replacement ACTIVATE | CANCEL replacement | root lock + version/state | reservation→root→ACTIVE→replacement | ACTIVE or CANCELLED winner state | first command | second 409 | 1 or 2 | 1 | no partial swap |
| ACTIVATE expected ACTIVE vN | concurrent change current ACTIVE | expected id/version + root lock | reservation→root→ACTIVE→replacement | changed ACTIVE/version | changer | ACTIVATE 409 | changer only | changer only | new remains APPROVED |
| approver role removal | ACTIVATE | immutable APPROVE event + current route | HR commit before root command | historical VERIFIED approval | HR change | ACTIVATE succeeds iff route exists | ACTIVATE 1–2 | ACTIVATE 1 | approval not rewritten |
| OTK-route removal | ACTIVATE | route recheck under root lock | HR change→reservation→root | no current route | removal | ACTIVATE 409 | 0 disposition | ACTIVATE rolled back | old/new unchanged |
| same key/hash request A | same key/hash request B | idempotency UNIQUE/reservation lock | reservation before root | COMPLETED response after wait | A | B replay | one command's count | 1 COMPLETED | B creates no mutation |
| ACTIVATE, failure after first event | rollback path | one transaction | reservation→root→both rows | no uncommitted state visible | none | error | 0 committed | 0 | rows/events/reservation all revert |

Все тесты гонок используют отдельные DB sessions/transactions и подтверждают итоговое число
rows/events/idempotency records, а не только HTTP-коды.

## 18. Тестовая матрица

### 18.1. Model/migration

- upgrade с пустой и существующей канонической БД;
- preflight каждого вида дубля/lineage/orphan/half-replacement;
- доказуемый backfill actor/time/project/related;
- legacy snapshot без выдуманного scope;
- NOT NULL/CHECK/actor-time pairs/version;
- partial UNIQUE ACTIVE и open, включая разрешённый `1 ACTIVE + 1 open`;
- downgrade без новых данных и fail-closed downgrade с новыми audit/idempotency данными.
- legacy APPROVED попадает в report, upgrade проходит, ACTIVATE блокируется, manual
  CANCEL/recreate проверяется отдельно.

### 18.2. RBAC/scope/route

- OTK GLOBAL и matching PROJECT APPROVE success;
- OTK wrong PROJECT, COMPANY/SITE/LINE/DOCUMENT denied;
- CHIEF не APPROVE; OGS не APPROVE; override отсутствует;
- только GLOBAL CHIEF ACTIVATE;
- inactive/suspended worker, inactive/expired/future role denied;
- project company INSPECTION без worker route не помогает;
- APPROVE/ACTIVATE без OTK-route fail-closed;
- кадровое изменение old approver не переписывает snapshot.

### 18.3. Lifecycle/API

- все строки transition table и все запрещённые переходы;
- creator-only OGS CANCEL DRAFT; CHIEF CANCEL во всех open states;
- UPDATE allow-list, version increment, normalized no-op;
- initial lifecycle до ACTIVE;
- replacement DRAFT сохраняет old ACTIVE; cancel replacement сохраняет old ACTIVE;
- atomic activate-time swap и related events;
- generic transition не выполняет команду;
- actor/system fields/lineage rejected in body.
- initial CREATE, valid replacement CREATE при ACTIVE и раздельные open/lineage/active
  conflicts;

### 18.4. Idempotency

- required key на каждой mutating route;
- same key/hash replay без второй mutation/event;
- same key/different hash 409 для каждой команды;
- new key after reached state согласно матрице;
- CREATE target root, остальные target disposition;
- no-op UPDATE record без domain event;
- rollback не оставляет record; concurrent duplicate даёт один record.
- reservation/replay выполняется до visibility/authority/state checks; same-key completed
  replay не превращается в новый domain conflict после изменения aggregate state.
- `TEST-IDEMPOTENCY-AUTH-SNAPSHOT-REPLAY-001`: выполнить APPROVE и сохранить VERIFIED
  authorization snapshot; затем удалить либо завершить effective OTK assignment; повторить запрос
  тем же actor, `Idempotency-Key` и normalized payload hash; вернуть сохранённый replay без
  пересчёта authority, без нового domain event и без изменения исходного snapshot.

### 18.5. Audit

- полный typed VERIFIED snapshot и точный `worker_roles.id`;
- scope source GLOBAL/PROJECT и project id;
- UPDATE before/after + versions;
- ACTIVATE replacement даёт ровно два связанных события;
- append-only contract; rejected/no-op/replay не создают event;
- disposition read не дублирует полный snapshot.

### 18.6. Legacy/OpenAPI и regression

- `/supersede` всегда 410 с `LEGACY_ENDPOINT_GONE` и новым workflow в message;
- 410 для существующего и случайного UUID одинаков;
- до/после вызова неизменны disposition rows, versions, event count и idempotency count;
- OpenAPI содержит маршрут с `deprecated: true`;
- `TEST-API-OPENAPI-001`: OpenAPI содержит 0 duplicate routes и 0 duplicate `operationId`;
- backend не содержит вызываемого supersede-time service path;
- существующие Defect/Engineering supersede endpoints других агрегатов не изменены;
- read/list/events API и unrelated quality tests проходят.
- существующий `test_defect_disposition_workflow.py` больше не ожидает success от generic
  `/transition` и supersede-time `/supersede`.

### 18.7. Независимая приёмка блоков

| Block | Exact implementation files | Exact test files / IDs | Command | Binary acceptance / review checkpoint |
|---|---|---|---|---|
| 5A | `app/quality/defect_disposition_models.py`; `app/quality/models.py` (re-export/metadata registration); `migrations/versions/20260722_25_disp_adr024_alignment.py`; `tests/conftest.py` (idempotency import и cleanup only; test-DB isolation приходит из prerequisite) | modify `tests/test_defect_disposition_migration.py`; create `tests/test_defect_disposition_adr024_persistence.py`: `test_clean_upgrade`, `test_current_head_upgrade`, `test_constraints_and_partial_unique`, `test_literal_snapshot_checks`, `test_legacy_approved_report`, `test_downgrade_guard`, `test_idempotency_cleanup` | `CMD-5A` | все 5A tests PASS; model/migration diff и cleanup review APPROVED |
| 5B | `app/quality/defect_disposition_policy.py`; `app/quality/defect_disposition_workflow.py` | create `tests/test_defect_disposition_adr024_policy.py`: `test_transition_matrix`, `test_exact_scope_roles`, `test_otk_route`, `test_no_override`, `test_legacy_approved_cannot_activate` | `CMD-5B` | все 5B tests PASS; policy/workflow review APPROVED |
| 5C | `app/quality/defect_disposition_repository.py`; `app/quality/defect_disposition_services.py` | create `tests/test_defect_disposition_adr024_services.py`: `test_reservation_precedes_domain_checks`, `test_reservation_replay`, `test_idempotency_auth_snapshot_replay` (`TEST-IDEMPOTENCY-AUTH-SNAPSHOT-REPLAY-001`), `test_transaction_atomicity`, `test_root_lock_order`, `test_concurrency_matrix`, `test_repository_never_commits`, `test_legacy_approved_manual_resolution` | `CMD-5C` | все 5C tests PASS; auth/scope loss не изменяет completed replay; repository/service integration review APPROVED |
| 5D | `app/quality/defect_disposition_schemas.py`; `app/quality/defect_disposition_api.py` | modify `tests/test_defect_disposition_workflow.py` to remove expectations of working generic transition/immediate supersede and cover command endpoints; create `tests/test_defect_disposition_adr024_api.py`: `test_command_routes`, `test_create_compatibility`, `test_replacement_create_with_active`, `test_legacy_410_zero_side_effects`, `test_openapi_deprecated`, `test_actor_mass_assignment`; create `tests/test_openapi_contracts.py`: `test_no_duplicate_routes_or_operation_ids` (`TEST-API-OPENAPI-001`) | `CMD-5D` + `CMD-API-OPENAPI-001` | все 5D tests PASS; 0 duplicate routes; 0 duplicate `operationId`; old transition/supersede success expectations absent; API review APPROVED |
| 5E | production files не меняются; допускаются только fixes findings в ранее перечисленных files с возвратом на review соответствующего блока | четыре ADR-024 test files, modified existing migration/workflow tests, затем full backend suite и Alembic drift check | `CMD-5E` | все commands exit 0; traceability 30/30; final independent review APPROVED |

Все DB-команды запускаются только после guard: обязательный `TEST_DATABASE_URL`, отсутствие
fallback на application DSN, test-marker/allow-list имени БД, DSN отличается от work DSN,
production deny-list и explicit destructive-test opt-in. Guard выполняется до Alembic,
Session и cleanup; отсутствие/совпадение DSN обязано останавливать pytest fail-fast.

Команды ниже являются буквальными командами Windows PowerShell 5.1. Они выполняются только
после закрытия `TEST-DB-FOUNDATION`; wildcard и оператор `&&` запрещены. Общий preamble каждого
CMD:

```powershell
Set-Location -LiteralPath 'D:\WeldPassport\09_Разработка\backend'
$Python = (Resolve-Path -LiteralPath '..\.venv\Scripts\python.exe').Path
if ([string]::IsNullOrWhiteSpace($env:TEST_DATABASE_URL)) { throw 'TEST_DATABASE_URL is required' }
if ($env:ALLOW_DESTRUCTIVE_TEST_DB -ne '1') { throw 'ALLOW_DESTRUCTIVE_TEST_DB=1 is required' }
```

`CMD-5A`:

```powershell
& $Python -m pytest -q tests/test_defect_disposition_migration.py tests/test_defect_disposition_adr024_persistence.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

`CMD-5B`:

```powershell
& $Python -m pytest -q tests/test_defect_disposition_adr024_policy.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

`CMD-5C`:

```powershell
& $Python -m pytest -q tests/test_defect_disposition_adr024_services.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

`CMD-5D`:

```powershell
& $Python -m pytest -q tests/test_defect_disposition_workflow.py tests/test_defect_disposition_adr024_api.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest tests/test_openapi_contracts.py::test_no_duplicate_routes_or_operation_ids
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

`CMD-API-OPENAPI-001`:

```powershell
& $Python -m pytest tests/test_openapi_contracts.py::test_no_duplicate_routes_or_operation_ids
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Binary acceptance: `0 duplicate routes`; `0 duplicate operationId`.

`CMD-5E`:

```powershell
& $Python -m pytest -q tests/test_defect_disposition_migration.py tests/test_defect_disposition_adr024_persistence.py tests/test_defect_disposition_adr024_policy.py tests/test_defect_disposition_adr024_services.py tests/test_defect_disposition_adr024_api.py tests/test_defect_disposition_workflow.py tests/test_openapi_contracts.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m alembic check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

### 18.8. Gap-to-test traceability

Команды `CMD-5A`…`CMD-5E` означают точные команды соответствующих строк §18.7.

| Gap ID | Requirement | Block | Test ID | Command | Acceptance |
|---:|---|---|---|---|---|
| 1 | APPROVE only OTK | 5B | `test_exact_scope_roles` | CMD-5B | CHIEF/OGS denied |
| 2 | no override | 5B | `test_no_override` | CMD-5B | action/event absent |
| 3 | ACTIVATE GLOBAL CHIEF | 5B | `test_exact_scope_roles` | CMD-5B | only GLOBAL CHIEF passes |
| 4 | OTK GLOBAL/PROJECT | 5B | `test_exact_scope_roles` | CMD-5B | exact scopes pass |
| 5 | CHIEF GLOBAL-only | 5B | `test_exact_scope_roles` | CMD-5B | PROJECT denied |
| 6 | OTK-route APPROVE | 5B | `test_otk_route` | CMD-5B | absent route denied |
| 7 | current route ACTIVATE | 5B | `test_otk_route` | CMD-5B | route rechecked |
| 8 | APPROVE snapshot | 5A | `test_constraints_and_partial_unique` | CMD-5A | VERIFIED checks pass |
| 9 | UPDATE_DRAFT | 5C | `test_transaction_atomicity` | CMD-5C | allow-list/version/audit/no-op pass |
| 10 | creator OGS cancel | 5B | `test_transition_matrix` | CMD-5B | only own DRAFT |
| 11 | CHIEF cancel open | 5B | `test_transition_matrix` | CMD-5B | all open states pass |
| 12 | activate-time replacement | 5C | `test_concurrency_matrix` | CMD-5C | swap only ACTIVATE |
| 13 | old ACTIVE retained | 5C | `test_transaction_atomicity` | CMD-5C | CREATE leaves old unchanged |
| 14 | ACTIVE not open | 5A | `test_constraints_and_partial_unique` | CMD-5A | 1 ACTIVE + 1 open allowed |
| 15 | root-first lock | 5C | `test_root_lock_order` | CMD-5C | SQL order proven |
| 16 | visibility before lock | 5C | `test_root_lock_order` | CMD-5C | hidden gives 404 before lock |
| 17 | forced reload/recheck | 5C | `test_root_lock_order` | CMD-5C | stale object rejected |
| 18 | UNIQUE ACTIVE | 5A | `test_constraints_and_partial_unique` | CMD-5A | second ACTIVE rejected |
| 19 | UNIQUE open | 5A | `test_constraints_and_partial_unique` | CMD-5A | second open rejected |
| 20 | idempotency all commands | 5C | `test_reservation_replay` | CMD-5C | ADR matrix passes |
| 21 | UPDATE before/after | 5C | `test_transaction_atomicity` | CMD-5C | typed versions/diff recorded |
| 22 | related dispositions | 5C | `test_transaction_atomicity` | CMD-5C | two linked swap events |
| 23 | role/scope snapshot | 5A | `test_constraints_and_partial_unique` | CMD-5A | typed DDL enforced |
| 24 | trusted actor boundary | 5D | `test_actor_mass_assignment` | CMD-5D | override rejected; production gate remains |
| 25 | append-only audit | 5C | `test_transaction_atomicity` | CMD-5C | update/delete prohibited |
| 26 | one transaction/commit | 5C | `test_repository_never_commits` | CMD-5C | repository commit count 0 |
| 27 | no direct supersede | 5D | `test_legacy_410_zero_side_effects` | CMD-5D | 410 and zero writes |
| 28 | no ACTIVE cancel | 5B | `test_transition_matrix` | CMD-5B | transition denied |
| 29 | HR change preserves approval | 5C | `test_concurrency_matrix` | CMD-5C | historical event unchanged |
| 30 | safe backfill | 5A | `test_current_head_upgrade` | CMD-5A | report/legacy/fail-closed pass |

Дополнительные обязательные review tests не изменяют нумерацию ADR gap matrix `30/30`:

| Test ID | Requirement | Block | Pytest node | Command | Acceptance |
|---|---|---|---|---|---|
| `TEST-IDEMPOTENCY-AUTH-SNAPSHOT-REPLAY-001` | completed APPROVE replay не зависит от последующей утраты/истечения OTK role/scope | 5C | `tests/test_defect_disposition_adr024_services.py::test_idempotency_auth_snapshot_replay` | CMD-5C | сохранённый response replay; authority не пересчитывается; snapshot неизменен; новых event/mutation нет |
| `TEST-API-OPENAPI-001` | глобальная уникальность OpenAPI routes и operationId | 5D/5E | `tests/test_openapi_contracts.py::test_no_duplicate_routes_or_operation_ids` | CMD-API-OPENAPI-001 и CMD-5E | 0 duplicate routes; 0 duplicate `operationId` |

Дополнительная traceability: ADR command idempotency → `test_reservation_replay`/CMD-5C;
authorization audit → `test_constraints_and_partial_unique`/CMD-5A; оба deprecated endpoint
→ `test_legacy_410_zero_side_effects` и `test_openapi_deprecated`/CMD-5D; prerequisites →
`CMD-PREREQ-ALEMBIC-CHECK`, `CMD-PREREQ-CLEAN-UPGRADE`, `CMD-PREREQ-TEST-DB-GUARD` и
принятое auth-решение. Результат считается бинарным только при `30/30` PASS.

## 19. Безопасный порядок реализации

1. tests для migration preflight;
2. 5A migration/model changes;
3. typed audit snapshot и legacy backfill;
4. idempotency persistence;
5. repository root-first locks и removal repository commit;
6. 5B workflow/policy;
7. 5C services и transaction tests;
8. 5D schemas/separate API commands;
9. заменить legacy supersede на deprecated 410;
10. migration/model tests;
11. RBAC/idempotency/concurrency/audit tests;
12. полный regression suite;
13. docs sync и независимая приёмка 5E.

До каждого изменения репозитория формируется отдельный точный implementation prompt с целью,
границами, разрешениями, запретами и критериями приёмки. После каждого блока предъявляются
изменённые файлы, diff и результаты проверок.

## 20. Commit strategy будущей реализации

Рекомендуемые атомарные commits после отдельного разрешения владельца:

1. `docs(quality): add ADR-024 alignment implementation spec`
2. `feat(quality): extend defect disposition persistence`
3. `feat(quality): align defect disposition workflow`
4. `feat(quality): align defect disposition API`
5. `test(quality): cover ADR-024 concurrency and idempotency`
6. `docs(quality): close defect disposition alignment task`

Spec commit не смешивается с backend. 5A, 5B, 5C, 5D и 5E остаются отдельно reviewable и
принимаются последовательно; объединение 5B/5C не допускается без нового отдельного решения
владельца. Commit/push выполняются только по отдельному подтверждению.

## 21. Acceptance criteria

- все 30 gaps из §4 закрыты кодом и тестами;
- APPROVE доступен только effective OTK GLOBAL/matching PROJECT;
- ACTIVATE доступен только GLOBAL CHIEF и требует verified APPROVE + current OTK-route;
- override/fallback отсутствуют;
- ACTIVE не входит в open, DB допускает ровно `1 ACTIVE + 1 open`;
- оба partial UNIQUE действуют;
- replacement не меняет old ACTIVE до atomic ACTIVATE;
- UPDATE_DRAFT имеет allow-list/version/before-after audit/no-op semantics;
- authorization snapshot типизирован, assignment = `hr.worker_roles.id`, legacy не выдуман;
- idempotency обязательна, replay/conflict/concurrent duplicate соответствуют матрице;
- state/audit/idempotency атомарны и repository не commit;
- visibility-before-lock и root-first order подтверждены SQL/concurrency tests;
- отдельные command endpoints стали каноническими; generic transition оставлен только как deprecated 410 tombstone;
- legacy transition/supersede видимы deprecated, всегда 410 и side-effect free;
- migration preflight/backfill/downgrade fail-closed и не удаляют историю;
- полный targeted и regression test suite зелёный;
- независимый review одобрил каждый блок и финальный diff.

## 22. Open blockers и решения, требующие нового ADR

### 22.1. Mandatory execution blockers

- audit finding B-03 / migration foundation;
- audit finding B-04 / database baseline;
- isolated test DB foundation;
- authenticated actor boundary для production acceptance.

Пока любой пункт открыт, 5A остаётся `planned` с execution blocked и не начинается.

### 22.2. Migration data blockers

- несколько ACTIVE или несколько open на одном root;
- неразрешимая replacement lineage;
- невозможные status combinations и нарушения будущих core lifecycle constraints.

При обнаружении migration abort публикует безопасный preflight report; автоматическое
исправление или удаление истории запрещено.

### 22.3. Non-blocking legacy conditions

- неоднозначные historical assignments → `LEGACY_AUTHORIZATION_SNAPSHOT`;
- недоказуемые historical scope/assignment fields остаются NULL;
- прежние omissions в event metadata отражаются в migration report;
- legacy APPROVED не блокирует migration, но ACTIVATE запрещён до manual CANCEL/recreate по
  контракту §7.2; автоматическая реконструкция snapshot запрещена.

### 22.4. Out-of-scope future decisions

Следующие изменения запрещено решать внутри реализации; при необходимости они получают
маркер **ARCHITECTURE BLOCKER** и отдельный ADR/Task:

- введение APPROVE_OVERRIDE или второго исключительного актора;
- PROJECT-scoped CHIEF_WELDER;
- признание company participation достаточным OTK-route;
- изменение перечня mutable disposition content за пределами текущего allow-list;
- автоматическая retention/cleanup policy, если она допускает потерю replay evidence;
- автоматическая неоднозначная коррекция legacy half-replacement;
- удаление deprecated endpoint раньше согласованного breaking-change релиза.

### 22.5. Closure map финального review

| Finding | Нормативное закрытие |
|---|---|
| R-01 | Closed — §8.1 и §16 разделяют initial CREATE, valid replacement CREATE, open/active/lineage conflicts; `TEST-IDEMPOTENCY-AUTH-SNAPSHOT-REPLAY-001` доказывает replay после утраты текущей OTK authority |
| R-02 | §11 фиксирует `normalize → hash → reservation/replay → visibility → authority → lock → mutation` |
| R-03 | §7.3 фиксирует SINGLE MAINTENANCE DEPLOYMENT; rolling запрещён; production только после 5E |
| R-04 | Execution Gate и §18.7 требуют внешний `TEST-DB-FOUNDATION` и fail-fast `TEST_DATABASE_URL` |
| R-05 | Execution Gate фиксирует B-03/B-04 как отдельные execution dependencies вне 9D-4A-5 |
| R-06 | Closed — §9 признаёт `X-User-Id` untrusted non-production development assumption; исключений из gate нет; production acceptance и 5A блокируются authenticated identity boundary |
| R-07 | Closed — §10–§11 фиксируют одну Session/autobegin transaction, repository без commit и единый service-level commit/rollback |
| R-08 | §6.3 содержит literal VERIFIED/LEGACY/scope/version/event-shape CHECK predicates |
| R-09 | Closed — §12 сохраняет один current CREATE contract и переводит legacy `/transition`/`/supersede` в deprecated side-effect-free 410 |
| R-10 | Closed — §18.7 перечисляет existing/new production/test files и PowerShell 5.1 commands для 5A–5E; `TEST-API-OPENAPI-001` проверяет глобальные duplicates |
| R-11 | §7.2 задаёт non-blocking migration и manual CANCEL/recreate для legacy APPROVED |
| R-12 | Closed — §17 содержит 13-сценарную concurrency matrix с winner/loser, event/idempotency counts и rollback outcome |
| R-13 | Closed — §6.2–§6.4 фиксируют version `+1`, state/event predicates, event codes и буквальные SQL CHECK для idempotency command/aggregate type без Python imports/enums |
| R-14 | Closed — §18.8 содержит ADR gap matrix `30/30`, дополнительные review test IDs, точные commands и binary acceptance |

## 23. Definition of Ready для реализации

- спецификация прошла независимый архитектурный и code-oriented review;
- все findings закрыты либо явно приняты владельцем;
- закрыты `MIGRATION_FOUNDATION_READY`, `DATABASE_BASELINE_DECIDED`,
  `TEST-DB-FOUNDATION`, `AUTHENTICATION_BOUNDARY_ACCEPTED`;
- 9D-4A-3/4 остаются `in_progress` до фактического исправления;
- подготовлен implementation prompt только для 5A;
- рабочее дерево проверено, scope 5A изолирован;
- commit/push отдельно разрешены владельцем.
