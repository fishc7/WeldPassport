# ADR-024 — DefectDisposition Lifecycle and Authority Model

Дата: 2026-07-21

Статус: **ACCEPTED**

Дата принятия: 2026-07-21.

Принят по результатам
[[docs/project/ARCHITECTURE_SESSIONS#K. Итог финального независимого review|финального независимого архитектурного review этапа 2.2 — APPROVED]]
после устранения findings F-01…F-10 и R-01…R-04. Текущий backend ещё не соответствует
настоящему ADR полностью; перед изменением кода обязательна отдельная Task Implementation
Specification.

Контур: Quality / DefectDisposition governance.

Дополняет: [[docs/project/DECISIONS#ADR-023. DefectDisposition — модель хранения уровня данных (Task 9D-4A-2)|ADR-023]]
(модель хранения). ADR-023 намеренно оставил вне рамок lifecycle, правила утверждения,
RBAC, workflow, API и аудит. Настоящий ADR является принятым целевым каноном, но сам по
себе не разрешает изменять код без отдельной Task Implementation Specification.

Частично заменяет: [[docs/project/DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019]]
только в части исторической модели `FindingDisposition`. Остальные положения ADR-019 о
`QualityFinding`, `EngineeringEvaluation`, `recommended_disposition`, Repair,
ProductionHold, Reinspection и внешнем контуре качества сохраняются.

Опирается на: [[docs/project/DECISIONS#ADR-021. EngineeringEvaluation Core Canon (Task 9D-2)|ADR-021]] ·
[[docs/project/DECISIONS#ADR-022. Defect Technical Model (Task 9D-3)|ADR-022]] ·
[[docs/project/ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING|ADR-022 Addendum D-3B-S01]].

Task: [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]], строки `Task 9D-4A-3` и
`Task 9D-4A-4`.

---

## A. Проблема и ретроспективный контекст

ADR-023 утвердил модель хранения `DefectDisposition`. Последующие документы и код Task
9D-4A-3/4 установили lifecycle, полномочия и supersede timing как Implementation Decisions,
хотя это архитектурные вопросы. Реализация появилась в commits `dfaa87b` и `d3a6d87` до
надлежащей Architecture Session и не является источником архитектурного канона.

Первая редакция ADR-024 также не прошла независимый review:

- F-01: она ошибочно представляла `DefectDisposition` как простое переименование
  `FindingDisposition`, несмотря на изменение владельца, типов и lifecycle;
- F-02/F-03: модель `APPROVE_OVERRIDE` не имела серверно проверяемого условия и позволяла
  одному `CHIEF_WELDER` подготовить, утвердить и активировать решение;
- F-04…F-10: не были полностью определены UPDATE DRAFT, scope, visibility/lock order,
  idempotency, CANCEL и последствия для audit schema.

Настоящая редакция исправляет проект решения. Она не легитимизирует прежнее нарушение AGF
задним числом и не объявляет существующий код соответствующим целевой модели.

## B. Рассмотренные варианты authority

### Вариант A — override с независимым вторым актором

Штатный `APPROVE` выполняет `OTK_INSPECTOR`; при объективном отсутствии OTK-route отдельный
`CHIEF_WELDER` выполняет override, а другой `CHIEF_WELDER` — activation.

Отклонён для MVP: текущая модель данных допускает несколько работников с ролью
`CHIEF_WELDER`, но не гарантирует наличие двух независимых акторов. Декларативный запрет
совпадения actor нельзя считать реализуемым процессом, если второй actor может отсутствовать.

### Вариант B — без override в MVP

`APPROVE` выполняет только effective `OTK_INSPECTOR` в `GLOBAL` или соответствующем
`PROJECT` scope; `ACTIVATE` выполняет только `CHIEF_WELDER`. Если действующего OTK-route
нет, `DefectDisposition` нельзя утвердить и активировать.

**Выбран для предлагаемой модели.** Он проверяется существующей моделью `hr.worker_roles`,
не требует новой сущности и не создаёт скрытого обхода separation of duties.

`APPROVE_OVERRIDE` **не входит в MVP**. Он может быть введён только отдельным ADR после
появления одновременно:

1. серверно проверяемого условия исключения;
2. независимого второго актора;
3. отдельного permission и reason-code policy;
4. обязательной отчётности по исключениям.

Fallback `CHIEF_WELDER`, установленный ADR-019 для исторического контура качества, **не
применяется к `DefectDisposition`**. Это локальное ограничение не отменяет остальные
положения ADR-019. `project_companies.role_code = 'INSPECTION'` описывает участие
организации и само по себе не доказывает наличие конкретного effective
`OTK_INSPECTOR`.

## C. Архитектурная замена FindingDisposition

`DefectDisposition` заменяет ранее проектировавшуюся модель `FindingDisposition` для
подтверждённых `Defect`. Это **не чистое переименование**, а архитектурная замена модели:
изменяются владелец агрегата, входное условие, типы, lifecycle, authority и момент
supersede.

С момента принятия ADR-024:

- `FindingDisposition` получает статус `SUPERSEDED_BY DefectDisposition` и не используется
  для новых Tasks;
- исторические тексты ADR-019 сохраняются как след эволюции, но их disposition-модель не
  служит основанием новой реализации;
- `recommended_disposition` остаётся рекомендацией `EngineeringEvaluation`, не создаёт
  исполняемого решения и не является `FindingDisposition` или `DefectDisposition`;
- официальное исполняемое решение создаётся только как `DefectDisposition`, принадлежит
  `DefectRoot` и возможно только после появления подтверждённого `Defect`;
- связь с `EngineeringEvaluation` проходит через подтверждённый `Defect`; disposition не
  принадлежит evaluation revision;
- `DefectDisposition` не является Repair, Reweld, Reinspection или ProductionHold и не
  фиксирует факт исполнения этих процессов.

### C.1. Mapping моделей

| Историческая модель `FindingDisposition` | Новая модель `DefectDisposition` | Статус |
|---|---|---|
| Владелец `QualityFinding` / действующая evaluation | Владелец `DefectRoot` | Заменено; автоматическая миграция ссылки не допускается |
| Решение по finding после evaluation | Исполняемое решение по подтверждённому `Defect` | Разделено; без `Defect` новая запись невозможна |
| `recommended_disposition` как вход в подготовку | Необязывающая рекомендация остаётся в evaluation | Не переносится как исполняемое решение |
| Старые типы ADR-019 | Четыре типа ADR-023 | Частичное mapping, см. C.2 |
| `DRAFT → PENDING_APPROVAL → APPROVED → IN_EXECUTION → COMPLETED` | `DRAFT → PREPARED → APPROVED → ACTIVE → SUPERSEDED/CANCELLED` | Заменено; прямой migration status запрещён, см. C.3 |
| Историческая матрица ролей | OGS/CHIEF prepare, только OTK approve, только CHIEF activate | Заменено |
| Исторический supersede/исполнение | Activate-time replacement | Заменено |

### C.2. Mapping типов

| Тип `FindingDisposition` ADR-019 | Тип `DefectDisposition` | Mapping |
|---|---|---|
| `NO_ACTION_REQUIRED` | — | `NO DIRECT MAPPING` |
| `ADDITIONAL_INSPECTION` | `REINSPECTION_REQUIRED` | `NO DIRECT MAPPING`: дополнительный и повторный контроль не тождественны |
| `DOCUMENT_CORRECTION` | — | `NO DIRECT MAPPING`; вне MVP DefectDisposition |
| `PROCESS_REVIEW` | — | `NO DIRECT MAPPING`; вне MVP DefectDisposition |
| `ACCEPT_AS_IS` | `ACCEPT_AS_IS` | Семантический кандидат; требует повторного утверждения, не автоматическая миграция |
| `REPAIR` | `REPAIR_REQUIRED` | Семантический кандидат; не означает создание или выполнение Repair |
| `REWELD` | — | `NO DIRECT MAPPING`; не сводится автоматически к Repair |
| `CUT_OUT_AND_REPLACE` | — | `NO DIRECT MAPPING` |
| `REJECT_JOINT` | `REJECT_JOINT` | Семантический кандидат; требует повторного утверждения |
| `RETURN_FOR_ADDITIONAL_EVALUATION` | — | `NO DIRECT MAPPING` |
| — | `REINSPECTION_REQUIRED` | Новый тип; создаётся только явной командой, не автоматическим mapping |

### C.3. Mapping статусов

| Статус `FindingDisposition` | Статус `DefectDisposition` | Mapping |
|---|---|---|
| `DRAFT` | `DRAFT` | Только после проверки владельца и содержимого |
| `PENDING_APPROVAL` | `PREPARED` | `NO DIRECT MAPPING`: PREPARED означает замороженное полное содержимое |
| `APPROVED` | `APPROVED` | `NO DIRECT MAPPING`: новая модель отдельно требует activation |
| `IN_EXECUTION` | `ACTIVE` | `NO DIRECT MAPPING`: ACTIVE — действующее распоряжение, а не факт исполнения |
| `COMPLETED` | — | `NO DIRECT MAPPING`; исполнение/closure вне MVP |
| `RETURNED` | — | `NO DIRECT MAPPING`; правка выполняется через новый DRAFT |
| `SUPERSEDED` | `SUPERSEDED` | Только после проверки lineage и activate-time replacement |
| `CANCELLED` | `CANCELLED` | Только после проверки истории; не автоматическая миграция |

Исторические записи не мигрируют автоматически по таблицам C.2/C.3. Если они существуют в
данных, требуется отдельный preflight, явное решение о каждой записи и migration plan.

## D. Сущность и lifecycle

`DefectDisposition` — дочерний агрегат `DefectRoot` и официальное исполняемое решение о
том, что необходимо сделать с подтверждённым техническим дефектом. Оно имеет собственный
UUID и lifecycle; конкурентные команды сериализуются на `DefectRoot`.

| From | Command | To | Role | Preconditions | Audit |
|---|---|---|---|---|---|
| — | `CREATE` | `DRAFT` | `OGS_ENGINEER`, `CHIEF_WELDER` | Доступный `DefectRoot`; подтверждённый Defect; justification; нет другой open-версии | `DISPOSITION_CREATED` |
| `DRAFT` | `UPDATE_DRAFT` | `DRAFT` | `OGS_ENGINEER`, `CHIEF_WELDER` | Только allow-list полей; status/actor/root/lineage из body запрещены | `DISPOSITION_DRAFT_UPDATED` |
| `DRAFT` | `PREPARE` | `PREPARED` | `OGS_ENGINEER`, `CHIEF_WELDER` | Содержимое комплектно | `DISPOSITION_PREPARED` |
| `PREPARED` | `APPROVE` | `APPROVED` | `OTK_INSPECTOR` | Effective роль в `GLOBAL` либо том же `PROJECT` scope | `DISPOSITION_APPROVED` |
| `APPROVED` | `ACTIVATE` | `ACTIVE` | `CHIEF_WELDER` | Исторический APPROVE имеет доказуемый authorization snapshot; действующий OTK-route подтверждён отдельно; непустая причина; при замене указана текущая ACTIVE через lineage | `DISPOSITION_ACTIVATED`; старой версии также `DISPOSITION_SUPERSEDED` |
| `DRAFT` | `CANCEL` | `CANCELLED` | создавший DRAFT `OGS_ENGINEER` или `CHIEF_WELDER` | Непустая причина | `DISPOSITION_CANCELLED` |
| `PREPARED`, `APPROVED` | `CANCEL` | `CANCELLED` | `CHIEF_WELDER` | Непустая причина | `DISPOSITION_CANCELLED` |

`APPROVE_OVERRIDE` отсутствует. Прямой `ACTIVE → SUPERSEDED` и прямой
`ACTIVE → CANCELLED` отсутствуют.

Смысл статусов:

- `DRAFT` — редактируемый проект решения;
- `PREPARED` — полное и замороженное для проверки решение;
- `APPROVED` — утверждённое ОТК, но ещё не вступившее в действие решение;
- `ACTIVE` — единственное действующее исполняемое решение;
- `SUPERSEDED` — неизменяемая версия, заменённая новой действующей;
- `CANCELLED` — неизменяемая версия, отменённая до вступления в действие.

### D.1. UPDATE_DRAFT

Точные имена колонок определяет будущая Implementation Specification, но архитектурный
allow-list ограничен следующими категориями: disposition type, структурированное содержание
решения, justification/reasoning, поля исполнения, непосредственно относящиеся к проекту
решения, и другие поля только после их явного включения в модель. Неизменяемы через UPDATE:

- `id`, `defect_root_id`, `project_id`, project/root ownership и system identifiers;
- `supersedes_disposition_id` и иная lineage;
- `status`;
- `created_by_worker_id`, actor/time/audit fields.

Каждый успешный изменяющий `UPDATE_DRAFT` создаёт ровно одно
`DISPOSITION_DRAFT_UPDATED`. Событие обязано позволять восстановить полный набор изменённых
allow-list полей, значение каждого поля до и после изменения, authorization snapshot,
логическую disposition version до и после, correlation/idempotency reference и timestamp.
Допустим field-level change set либо полный before/after snapshot; выбор хранения не может
уменьшать доказуемость перечисленных данных.

Если нормализованный payload не меняет ни одного поля, это no-op: состояние и version не
изменяются, доменное `DISPOSITION_DRAFT_UPDATED` не создаётся, возвращается текущее
представление, а idempotency record может быть создан для replay. No-op допускается только в
техническом request-log, но не в доменном audit trail.

После `PREPARE` прямое редактирование запрещено. `UPDATE_DRAFT` выполняется после lock
`DefectRoot` и disposition; под lock повторно проверяются `DRAFT`, ownership, authority и
expected version либо эквивалентный optimistic token. При гонке UPDATE/PREPARE или
UPDATE/CANCEL побеждает одна команда, вторая возвращает доменный `409` без частичного
изменения и без лишнего audit event.

## E. Authority и scope

Effective роль означает: worker активен; `worker_role.is_active = true`; текущая дата
попадает в `valid_from`/`valid_to`; role code соответствует команде; scope разрешает проект
Joint, к которому относится `DefectRoot`.

Действующий OTK-route для проекта существует, если сервер на текущую дату находит хотя бы
одного активного worker с effective ролью `OTK_INSPECTOR` в `GLOBAL` scope либо в
`PROJECT` scope с `scope_id` соответствующего проекта. Наличие только
`project_companies.INSPECTION`, COMPANY/SITE/LINE/ENGINEERING_DOCUMENT role или значение из
request body OTK-route не образует. Проверка выполняется для `APPROVE` и повторно для
`ACTIVATE`. Она fail-closed: ошибка чтения/неоднозначная role не трактуется как разрешение
ни одной из этих команд.

Authorization snapshot события `APPROVE` доказывает полномочие на момент утверждения.
Последующее снятие роли, истечение срока назначения или деактивация прежнего approver не
аннулирует исторически законный APPROVE и не изменяет его событие. При `ACTIVATE` не
требуется текущая роль прежнего approver: отдельно проверяется наличие хотя бы одного
effective OTK-route проекта, и это может быть другой `OTK_INSPECTOR`. Если текущего маршрута
нет, команда блокируется, disposition остаётся `APPROVED`, а approval event не
переписывается.

| Command | GLOBAL | PROJECT | COMPANY | SITE / LINE / ENGINEERING_DOCUMENT |
|---|---:|---:|---:|---:|
| `CREATE` | Да, OGS/CHIEF | Да, OGS того же проекта | Нет | Нет |
| `UPDATE_DRAFT` | Да, OGS/CHIEF | Да, OGS того же проекта | Нет | Нет |
| `PREPARE` | Да, OGS/CHIEF | Да, OGS того же проекта | Нет | Нет |
| `APPROVE` | Да, OTK | Да, OTK того же проекта | Нет | Нет |
| `APPROVE_OVERRIDE` | N/A — вне MVP | N/A | N/A | N/A |
| `ACTIVATE` | Да, только CHIEF | Нет: `CHIEF_WELDER` канонически GLOBAL | Нет | Нет |
| `CANCEL` | Да: CHIEF; OGS только собственный DRAFT | Да: OGS того же проекта только собственный DRAFT | Нет | Нет |

`CHIEF_WELDER` в текущей канонической HR-модели действует только через `GLOBAL` scope.
Будущее введение PROJECT-scoped `CHIEF_WELDER` требует отдельного архитектурного решения
или изменения настоящего ADR; техническая возможность сохранить иной scope не расширяет
полномочия автоматически.

### E.1. Immutable authorization snapshot

Каждое успешное mutating-событие хранит неизменяемый snapshot результата проверки
полномочий на момент команды:

- `actor_worker_id`;
- `actor_role_code`;
- `actor_scope_type`;
- `actor_scope_id`, если scope не `GLOBAL`;
- стабильный идентификатор конкретного role assignment, когда HR-модель позволяет его
  определить;
- `role_valid_from` и `role_valid_to`;
- server timestamp проверки полномочий;
- `project_id` целевого агрегата;
- результат policy-check (`AUTHORIZED` для успешного доменного события);
- источник полномочия: `GLOBAL` или `PROJECT`; иной источник может быть добавлен только
  отдельным архитектурным решением.

Если стабильного assignment ID нет, минимально достаточен доказуемый состав
`worker_id + role_code + scope_type + scope_id + valid_from + valid_to`. Snapshot отражает
факты момента команды и не пересчитывается по текущему состоянию HR. Отклонённые запросы не
создают доменное transition event и могут фиксироваться системным security/request audit.
Качество snapshot обозначается явно: новые доказуемые события имеют подтверждённый статус,
а историческое событие без восстанавливаемого scope получает
`authorization_snapshot_status = LEGACY_AUTHORIZATION_SNAPSHOT`. Этот признак не подменяет
отсутствующие данные и не разрешает выдумывать исторический scope.

`project_companies.INSPECTION` не заменяет проверку effective worker role. Наличие такой
организации может использоваться как управленческая конфигурация проекта, но не даёт
конкретному actor право `APPROVE` и не доказывает существование OTK-route.

Скрытый по visibility scope объект возвращается как `404`. Для видимого объекта отсутствие
необходимой effective role возвращается как `403`. Неверное состояние или конкурентное
изменение возвращает доменный `409`.

## F. Visibility, транзакции и блокировки

### F.1. Двухфазное правило для существующей disposition

1. Получить actor из server authentication context.
2. Выполнить visibility-scoped lookup без блокировки; невидимый объект → `404`.
3. Проверить базовое право команды; недостаток authority → `403`.
4. Начать транзакционную операцию.
5. Заблокировать `DefectRoot` через `SELECT ... FOR UPDATE`.
6. Повторно загрузить disposition под lock.
7. Повторно проверить project/root ownership, visibility, status, effective role и
   preconditions на текущую дату; для `APPROVE` подтвердить authority snapshot, а для
   `ACTIVATE` проверить исторический snapshot APPROVE и отдельно текущий OTK-route.
8. Выполнить изменение и append audit event.
9. Выполнить один commit; любая ошибка откатывает state, audit и idempotency record.

### F.2. CREATE

Visibility-scoped lookup `DefectRoot` → базовый role check → transaction → lock root →
повторная проверка ownership/role → проверка отсутствия второй open-версии → insert →
audit → один commit.

### F.3. Единый lock order

```text
DefectRoot → current ACTIVE disposition → open/replacement disposition
```

Если блокируются две disposition, они загружаются в детерминированном порядке UUID. Ни
одна команда не должна сначала блокировать disposition, а затем соответствующий root.

## G. Инварианты и ограничения БД

1. `DefectDisposition` не существует без `DefectRoot` и подтверждённого Defect.
2. На один `DefectRoot` существует не более одной `ACTIVE` версии.
3. На один `DefectRoot` существует не более одной open-версии
   (`DRAFT`/`PREPARED`/`APPROVED`).
4. Допустимо `1 ACTIVE + 1 open` для будущей замены.
5. `0 ACTIVE + 1 open` допустимо до первой активации.
6. Replacement всегда имеет `supersedes_disposition_id = current_active.id`; replacement
   без прямой ссылки при существующем ACTIVE запрещён.
7. `SUPERSEDED` и `CANCELLED` терминальны и не участвуют в ограничении open.
8. Частичные индексы обязательны:
   - `UNIQUE(defect_root_id) WHERE status = 'ACTIVE'`;
   - `UNIQUE(defect_root_id) WHERE status IN ('DRAFT','PREPARED','APPROVED')`.
9. До добавления индексов migration выполняет preflight существующих данных и fail-closed
   останавливается при дублях; автоматическое удаление/слияние записей запрещено.

## H. Activate-time replacement и CANCEL

Создание replacement создаёт новую `DRAFT` с
`supersedes_disposition_id = old_active.id`, не меняя old ACTIVE. Replacement проходит
`PREPARE → APPROVE`. `ACTIVATE` под root lock проверяет, что old всё ещё единственная
ACTIVE, new всё ещё APPROVED, root и lineage совпадают; затем одной транзакцией переводит
old `ACTIVE → SUPERSEDED`, new `APPROVED → ACTIVE` и пишет два связанных события.

При rollback обе версии и оба события сохраняют прежнее состояние. Самостоятельная команда
`SUPERSEDE`, оставляющая root без ACTIVE, запрещена.

`CANCEL`:

- разрешён только для `DRAFT`, `PREPARED`, `APPROVED`;
- создавший DRAFT `OGS_ENGINEER` может отменить только собственный DRAFT;
- `CHIEF_WELDER` может отменить любую open-версию;
- OGS не отменяет чужой DRAFT, PREPARED или APPROVED;
- reason и `DISPOSITION_CANCELLED` обязательны;
- отмена replacement не меняет old ACTIVE;
- после CANCELLED можно создать новую open-версию;
- ACTIVE, SUPERSEDED и CANCELLED не отменяются.

## I. Idempotency contract

`Idempotency-Key` обязателен для каждой mutating-команды MVP. Один и тот же запрос означает
совпадение actor, command, target aggregate, нормализованных бизнес-полей payload и
expected version/expected active lineage, когда они применимы.
`CREATE` в этой матрице охватывает первичное создание и создание replacement; для
replacement в payload/hash обязательно входит expected current ACTIVE и lineage.

| Command | Key required | Тот же key + тот же запрос / timeout replay | Тот же key + другой payload | Другой key после достигнутого результата | Без key |
|---|---:|---|---|---|---|
| `CREATE` | Да | Вернуть ранее созданную disposition и response snapshot; вторую строку/CREATED не создавать | `409 DISPOSITION_IDEMPOTENCY_CONFLICT` | Повтор того же CREATE intent под новым key при существующей созданной open/ACTIVE версии → `409 DISPOSITION_ALREADY_OPEN`; replacement с явными expected ACTIVE/lineage или новая CREATE после допустимого терминального состояния являются отдельными командами | `422` validation error |
| `UPDATE_DRAFT` | Да | Вернуть прежний response snapshot; второй UPDATE event не создавать | `409 DISPOSITION_IDEMPOTENCY_CONFLICT` | Повторно вычислить изменение под lock: no-op возвращает текущую representation без domain event; реальное изменение требует актуальной expected version | `422` validation error |
| `PREPARE` | Да | Вернуть прежний response snapshot; второй PREPARED не создавать | `409 DISPOSITION_IDEMPOTENCY_CONFLICT` | Idempotent success только если существующий PREPARED event имеет того же actor, ту же content version и тот же нормализованный payload; иначе domain `409` | `422` validation error |
| `APPROVE` | Да | Вернуть прежний response snapshot; второй APPROVED не создавать | `409 DISPOSITION_IDEMPOTENCY_CONFLICT` | Idempotent success только для того же OTK actor, той же content version и того же нормализованного payload; другой actor/payload → domain `409` | `422` validation error |
| `ACTIVATE` | Да | Если disposition уже ACTIVE, а при replacement old уже SUPERSEDED и lineage совпадает, вернуть прежний успех; вторые события не создавать; иное состояние → `409` | `409 DISPOSITION_IDEMPOTENCY_CONFLICT` | Уже достигнутый результат с новым key не является replay и возвращает domain `409` | `422` validation error |
| `CANCEL` | Да | Вернуть прежний response snapshot; второй CANCELLED не создавать | `409 DISPOSITION_IDEMPOTENCY_CONFLICT` | Idempotent success только если существующий CANCELLED event имеет того же actor и ту же нормализованную reason; другой actor/reason → domain `409` | `422` validation error |

Минимальный контракт:

- область уникальности: `actor_worker_id + command + target aggregate + Idempotency-Key`;
- хранится hash нормализованного payload без transport-only полей;
- тот же ключ и payload возвращает сохранённый исходный результат без новой строки/события;
- тот же ключ с другим payload возвращает `409 DISPOSITION_IDEMPOTENCY_CONFLICT`;
- запись idempotency создаётся в той же транзакции, что state и audit;
- concurrent duplicate разрешается UNIQUE-ограничением; `IntegrityError` преобразуется в
  повтор исходного результата либо domain conflict после повторного чтения ключа;
- rollback не оставляет успешную idempotency record;
- replay возвращает сохранённый response snapshot;
- retention задаётся общей системной политикой и не означает бесконечное хранение; cleanup
  не нарушает replay в установленном retention window;
- после удаления idempotency record доменные UNIQUE, version и lifecycle constraints всё
  равно защищают агрегат;
- конкретная таблица/JSON-модель определяется будущей Implementation Specification.

## J. Actor и audit

Actor приходит только из server context; body не принимает actor/author/role/status.
События append-only и записываются в той же транзакции, что доменное изменение.

Минимальные обязательные данные события:

- полный immutable authorization snapshot из §E.1, включая actor role и scope;
- `event_type`, `from_status`, `to_status`;
- `defect_root_id`, `disposition_id`;
- `related_disposition_id`, когда применимо;
- `reason_code`, когда применимо;
- `reason`, когда применимо;
- `correlation_id` или ссылка на idempotency record;
- server timestamp;
- before/after change set или полный before/after snapshot для
  `DISPOSITION_DRAFT_UPDATED` согласно §D.1.

События MVP:

- `DISPOSITION_CREATED`;
- `DISPOSITION_DRAFT_UPDATED`;
- `DISPOSITION_PREPARED`;
- `DISPOSITION_APPROVED`;
- `DISPOSITION_ACTIVATED`;
- `DISPOSITION_SUPERSEDED`;
- `DISPOSITION_CANCELLED`.

`DISPOSITION_APPROVAL_OVERRIDDEN` в MVP отсутствует.

## K. Последствия для будущей реализации

Потребуется отдельный Task Implementation Spec и отдельный bugfix-этап. До него backend,
модели, API, миграции и тесты не меняются.

Будущая реализация потребует:

1. новую Alembic migration;
2. preflight существующих disposition и event данных;
3. preflight и безопасный backfill nullable actor/role/scope-полей authorization snapshot;
   если точный исторический scope доказать нельзя, событие получает
   `authorization_snapshot_status = LEGACY_AUTHORIZATION_SNAPSHOT`, а scope не
   выдумывается;
4. новые/обновлённые CHECK constraints для events и обязательных audit invariants;
5. partial UNIQUE для open-версии;
6. добавление `DISPOSITION_DRAFT_UPDATED` и удаление override-event из MVP contract;
7. authorization snapshot, correlation/idempotency storage и логическую disposition version
   согласно Implementation Specification;
8. migration старого `/supersede` API без параллельного канонического пути;
9. rollback strategy: сначала восстановить старые constraints/API compatibility, не удаляя
   исторические events; необратимый backfill и удаление данных запрещены.

Текущий код соответствует только отдельным локальным механизмам: связь с `DefectRoot`,
server-side actor, наличие append-only events, локальные disposition row locks и partial
UNIQUE для ACTIVE. Он **не соответствует целевой root-level concurrency модели целиком**.

Требуют будущего исправления:

- ordinary APPROVE сейчас разрешает `CHIEF_WELDER`;
- отсутствует целевой OTK-only authority contract;
- supersede выполняется в supersede-time;
- ACTIVE ошибочно входит в open statuses;
- CREATE и ACTIVATE не реализуют целевой root-first lock order;
- отсутствуют UPDATE_DRAFT event, open partial UNIQUE и command idempotency;
- APPROVED → CANCELLED и правило creator-only OGS DRAFT не реализованы;
- audit schema не обеспечивает все обязательные поля настоящего ADR.

## L. MVP / вне рамок

В предлагаемом MVP: lifecycle, UPDATE DRAFT, OTK-only approval, CHIEF activation,
activate-time replacement, CANCEL, scope, two-phase visibility/locking, idempotency contract,
audit contract и ограничения количества версий.

Вне MVP: `APPROVE_OVERRIDE`, ProductionHold, Repair, Reweld, Reinspection, NCR, CAPA,
CustomerQualityDecision, запуск корректирующих действий, печатные формы, файлы,
универсальный approval engine и исправления B-01…B-04.

## Связанные технические решения

- [[docs/project/implementation-decisions/9D-4A-3-disposition-approve-activate-roles|Task 9D-4A-3 — DefectDisposition Approve/Activate Implementation Decision]]
- [[docs/project/implementation-decisions/9D-4A-4-disposition-supersede-workflow|Task 9D-4A-4 — DefectDisposition Supersede Implementation Decision]]
