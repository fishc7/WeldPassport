# Implementation Spec — Task 9D-3 · Defect Technical Model

Канон: [[DECISIONS#ADR-022. Defect Technical Model (Task 9D-3)|ADR-022]] ·
[[ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING|ADR-022 Addendum D-3B-S01]] (supersede-time — авторитет по
моменту исполнения supersede) · опирается на
[[DECISIONS#ADR-021. EngineeringEvaluation Core Canon (Task 9D-2)|ADR-021]]
(`EFFECTIVE` `EngineeringEvaluationRevision` с `classification = CONFIRMED_DEFECT` — единственное
основание) · [[DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019]] ·
план [[IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP|IMPLEMENTATION_PLAN]] (строка 9D-3).

Статус: **NOT IMPLEMENTED.** Реализованы предыдущие блоки Task 9D-1 (`QualityFinding` Core) и
Task 9D-2 (`EngineeringEvaluation`, ADR-021). Task 9D-3 не начата. Этот документ переводит канон
**ADR-022** в реализуемую структуру и **не меняет канон** (как 9D-2 Spec для ADR-021).

> **Главное правило (ADR-022), пронизывает весь spec.**
> `Defect` — самостоятельная **техническая** запись подтверждённого технического дефекта одного
> `Joint`. `Defect` **никогда не**: хранит решение о пригодности/ремонте/disposition; создаёт или
> заменяет `FindingDisposition`; содержит Repair / Reweld / Reinspection / acceptance / вычисляемое
> закрытие. Исправление действующей записи — **только через supersede** (новая ревизия), прямое
> изменение существенных технических полей `ACTIVE` запрещено (ADR-022 §7).

### Ключевые решения 9D-3 (зафиксированы при подготовке Spec)

Согласовано после разрешения архитектурного блокера (вариант 2 — полное соответствие ADR-022;
ADR-022 не изменяется). Последовательно **9D-3-D01 … D12**:

- **D01 — supersede-модель.** Lifecycle `DRAFT → ACTIVE → SUPERSEDED` (+ `CANCELLED`). Существенные
  технические поля `ACTIVE` **immutable**; исправление — новой ревизией через supersede (ADR-022 §6/§7).
- **D02 — корневая идентичность цепочки.** Вводится **`DefectRoot`** — устойчивая идентичность одной
  логической цепочки версий (`defect_root`). `UNIQUE(engineering_evaluation_id)` — на `DefectRoot`
  (D07), не на строке ревизии. `defect_root` реализован как таблица (ADR-022 §7 задаёт его как
  «общий корневой идентификатор», не как обязательную колонку — решение 7 запуска: предпочтительно
  отдельная `DefectRoot`).
- **D03 — ревизия.** `Defect` — версия-ревизия: собственный UUID, `defect_root_id`, `revision_no`
  (≥1, монотонно в цепочке), `supersedes_defect_id` (предыдущая ревизия), `status`.
- **D04 — ровно одна `ACTIVE` в цепочке.** DB-инвариант — частичный `UNIQUE(defect_root_id) WHERE
  status='ACTIVE'`; и не более одной открытой `DRAFT`-ревизии — `UNIQUE(defect_root_id) WHERE
  status='DRAFT'`.
- **D05 — supersede через новую ревизию (supersede-time; аддендум D-3B-S01).** `POST …/{id}/supersede`
  в одной атомарной транзакции переводит предыдущую `ACTIVE` → `SUPERSEDED` **и** создаёт новую
  `DRAFT`-ревизию в той же цепочке (события `DEFECT_SUPERSEDED` предыдущей + `DEFECT_REVISION_CREATED`
  новой). После supersede действующей `ACTIVE` в цепочке нет (0 `ACTIVE`, 1 открытая `DRAFT`). Приёмка
  новой версии — **отдельной** командой `activate` (`DRAFT → ACTIVE`, событие `DEFECT_ACTIVATED`).
  Timing-модель зафиксирована в [[ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING|ADR-022 Addendum D-3B-S01]].
- **D06 — кардинальность.** Одна `EngineeringEvaluation(CONFIRMED_DEFECT)` порождает **≤1 корневую
  цепочку** `Defect` (ADR-022 §3.3). `CANCELLED` **не** освобождает `EngineeringEvaluation` для второй
  независимой цепочки (D08).
- **D07 — уникальность на корне.** `DefectRoot.engineering_evaluation_id` — `UNIQUE`. Строгий
  построчный `UNIQUE(engineering_evaluation_id)` на ревизиях **не используется** (решение 6 запуска).
- **D08 — устойчивость корня.** `DefectRoot` физически не удаляется; при `CANCELLED` всей цепочки
  корень сохраняется, `engineering_evaluation_id` остаётся занятым — повторная регистрация по той же
  оценке невозможна (нужна новая `EngineeringEvaluation`).
- **D09 — actor/optimistic.** Actor-поля `*_by_worker_id` — `Integer` без FK; `version` — отдельный
  optimistic-lock механизм на каждой строке (наряду с revision-цепочкой).
- **D10 — источник = только effective revision.** `CONFIRMED_DEFECT` определяется исключительно через
  `EngineeringEvaluation.effective_revision_id → EngineeringEvaluationRevision(status='EFFECTIVE',
  classification='CONFIRMED_DEFECT')`. Параллельный источник решения не вводится; `FindingDisposition`
  не создаётся.
- **D11 — PATCH только DRAFT.** `PATCH` разрешён только для `DRAFT`-ревизии. `PATCH` технических полей
  `ACTIVE` запрещён (`DEFECT_ACTIVE_IMMUTABLE`). ADR-022 не определяет «несущественные», отдельно
  редактируемые у `ACTIVE` поля — поэтому у `ACTIVE` не редактируется ничего.
- **D12 — справочники read-only.** `DefectType` / `DefectLocationType` — system-managed read-only НСИ:
  модели, миграция, seed, list/detail API, `active_only`, применение в валидации. Без write-API/CRUD.
- **D13 — полное структурное покрытие ADR-022 §5 (ревью-замечание).** Все характеристики §5 —
  **самостоятельные структурированные поля**, а не части свободного текста: `orientation`/`surface`/
  `joint_side` (bounded string, §4.4), `axial_position_mm`/`circumferential_position_deg` (§7.9),
  `height_mm`, раздельные `standard_document`/`standard_revision`/`standard_clause` (§4.5). Независимый
  `standard_reference` **удалён** (правило 7); объединённая ссылка — производное read-поле
  `standard_reference_display` (правило 8). Свободный текст (`technical_description`/
  `location_description`/`evaluation_note`/`technical_note`) — пояснительный, не заменяет структуру
  (правило 1). Новые поля редактируемы в `DRAFT`, валидируются на активацию, immutable в `ACTIVE`,
  копируются при supersede, участвуют в audit metadata ревизии. Полное сопоставление — §4.6.
  `DefectType.requires_height` добавлен для симметрии с прочими `requires_*`.

---

## 1. Границы Task 9D-3

**Входит** (ADR-022 §13): модель `Defect` (supersede-цепочка) и `DefectRoot`; lifecycle
`DRAFT/ACTIVE/SUPERSEDED/CANCELLED`; регистрация на основании `CONFIRMED_DEFECT`; техническая
классификация; локализация; измеримые характеристики; нормативная ссылка; версионность через
supersede (`defect_root`, `revision_no`, `supersedes_defect_id`); отмена; аудит (append-only);
per-joint нумерация; техническая валидация; optimistic concurrency; repository; services; schemas;
API; RBAC; read-only API справочников; seed; миграция; тесты; консолидация документации.

**Не входит** (ADR-022 §8–§10, §13): `FindingDisposition`; `DefectAcceptanceAssessment` и решение о
допустимости; Repair / `RepairAttempt` / `RepairMethod` / `RepairStatus` / Repair-зоны; Reweld и
ремонтный `WeldOperation`; Reinspection и её назначение/результат; вычисляемое и ручное закрытие;
признаки устранения (`is_repaired`/`is_closed`/`closed_at`/`resolved_at`/`eliminated_at`/
`repair_*`/`reweld_operation_id`); M:N-связь оценок; `origin_disposition_id`/`finding_disposition_id`/
`source_result_item_id`; печатные формы, файлы, импорт, массовые операции, аналитические витрины,
автоматическое определение ответственности сварщика.

---

## 2. Соглашения (наследуются от 9A–9D-2)

- Модульный split в `09_Разработка/backend/app/quality/`: `defect_workflow.py` (константы/pure-функции),
  `defect_models.py` (ORM), `defect_schemas.py` (Pydantic v2), `defect_repository.py`,
  `defect_validation.py`, `defect_services.py`, `defect_api.py`.
- Схема БД — `quality`. Перечисления — **CHECK-ограничениями**, без native enum.
- Actor-поля — `*_by_worker_id` типа `Integer` **без FK** (переходный период, как 9A–9D-2).
- Optimistic locking — `version` (≥1) на каждой изменяемой строке. Физического удаления нет
  (`DRAFT`-ревизия удаляется только через `CANCELLED`, не через DELETE — ADR-022 §12).
- Числа — `numeric` (положительные при заполнении), `quantity` — `Integer` (>0). Даты —
  `timestamptz`. Файлов/бинарей нет.
- Роли — существующие `role_code` из `inspection_workflow`, **новых не вводим** (ADR-019). Маппинг:
  `WELDING_ENGINEER ↔ OGS_ENGINEER`, `CHIEF_WELDER ↔ CHIEF_WELDER`, `OTK ↔ OTK_INSPECTOR`,
  `NDT ↔ NDT_SPECIALIST`.
- Бизнес-действия — **команды** (`activate`/`cancel`/`supersede`), не универсальный PATCH статуса.
  `PATCH` — только правка `DRAFT` (D11). Актор из `X-User-Id`; RBAC/scope — на backend в сервисе
  (паттерн `QualityFindingService`).
- Коды ошибок — UPPERCASE, префикс `DEFECT_`. HTTP-семантика: 403 роль/scope; 404 не найдено/скрыто
  scope; 409 конфликт версии/недопустимый переход/нарушение уникальности цепочки; 422 неполнота
  активации/несоответствие ссылок/несовпадение Joint.

---

## 3. Сущности и таблицы (схема `quality`)

| Сущность | Таблица | Назначение |
|---|---|---|
| `DefectRoot` | `defect_roots` | Корневая идентичность цепочки версий (`defect_root`); 1 к 1 с `EngineeringEvaluation(CONFIRMED_DEFECT)` |
| `Defect` | `defects` | Техническая ревизия дефекта (носитель классификации/измерений/статуса) |
| `DefectType` | `defect_types` | Системный read-only справочник типов дефектов |
| `DefectLocationType` | `defect_location_types` | Системный read-only справочник расположений |
| `DefectSequence` | `defect_sequences` | Служебный per-joint счётчик `defect_no` |
| `DefectEvent` | `defect_events` | Неизменяемое событие истории (append-only) |

Обязательные связи ADR-022 §4 (`Joint`, `QualityFinding`, `EngineeringEvaluation`, первичный источник)
**выводятся через цепочку происхождения** от `DefectRoot.engineering_evaluation_id`
(`evaluation → finding → joint_id`; `finding → source refs`), а не дублируются на каждой ревизии
(ADR-022 §4: связи выводятся, не дублируются без доказанной необходимости).

### 3.1. DefectRoot

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | это и есть `defect_root` (общий корневой идентификатор) |
| `joint_id` | uuid FK engineering.joints RESTRICT NOT NULL | денормализация для `UNIQUE(joint_id, defect_no)`, scope/индексов; == evaluation→finding→joint_id (сервис) |
| `engineering_evaluation_id` | uuid FK engineering_evaluations RESTRICT NOT NULL | **UNIQUE** — одна корневая цепочка на оценку (D06/D07/D08) |
| `defect_no` | int ≥1 NOT NULL | per-joint номер; `UNIQUE(joint_id, defect_no)`; неизменяем |
| `current_defect_id` | uuid null | указатель на текущую/последнюю ревизию (плоский UUID без FK — разрыв цикла, как `EngineeringEvaluation.current_revision_id`) |
| `active_defect_id` | uuid null | указатель на действующую (`ACTIVE`) ревизию; `NULL`, если действующей нет (все `CANCELLED` или только `DRAFT`) |
| `created_by_worker_id` / `created_at` / `updated_by_worker_id` / `updated_at` / `version` | audit | канон 9A–9D-2 |

`UNIQUE(engineering_evaluation_id)` физически гарантирует «≤1 корневая цепочка на оценку» и её
устойчивость после `CANCELLED` (D08). `UNIQUE(joint_id, defect_no)` гарантирует per-joint нумерацию.

### 3.2. Defect (ревизия)

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | новый UUID на каждую ревизию (ADR-022 §7) |
| `defect_root_id` | uuid FK defect_roots RESTRICT NOT NULL | принадлежность цепочке |
| `revision_no` | int ≥1 NOT NULL | монотонно в цепочке; `UNIQUE(defect_root_id, revision_no)` |
| `supersedes_defect_id` | uuid null FK defects(self) RESTRICT | предыдущая ревизия (NULL для `revision_no=1`) |
| `status` | text CHECK | lifecycle §5 (`DRAFT`/`ACTIVE`/`SUPERSEDED`/`CANCELLED`) |
| `defect_type_id` | uuid null FK defect_types RESTRICT | обязателен на активацию (§8); nullable в `DRAFT` |
| `location_type_id` | uuid null FK defect_location_types RESTRICT | обязателен на активацию (§8); nullable в `DRAFT` |
| `indication_location` | text null CHECK | §4.2; `UNKNOWN` допустим в `DRAFT`; для `ACTIVE` — по `DefectType.requires_known_indication_location` |
| `orientation` | text null (bounded) | **ориентация** дефекта; контролируемый bounded string, §4.4 |
| `surface` | text null (bounded) | **поверхность**; контролируемый bounded string, §4.4 |
| `joint_side` | text null (bounded) | **сторона соединения**; контролируемый bounded string, §4.4 |
| `axial_position_mm` | numeric null | **положение по длине шва** от датума; ≥ 0; при заполнении обязателен `location_description` (датум/точка отсчёта — текстом), §7.9 |
| `circumferential_position_deg` | numeric null | **положение по окружности шва**, градусы; диапазон `[0, 360)`, нормализация по модулю 360, §7.9 |
| `length_mm` / `width_mm` / `height_mm` / `depth_mm` / `affected_area_mm2` | numeric null | **длина / ширина / высота / глубина / площадь**; при заполнении **строго > 0**; обязательность — по `DefectType.requires_*` (§8) |
| `quantity` | int null | **количество индикаций**; при заполнении **> 0**; обязательность — по `DefectType.requires_quantity` |
| `standard_document` | text null | **нормативный документ** (ГОСТ/ISO/СП/РД…), §4.5 |
| `standard_revision` | text null | **редакция/год** нормативного документа, §4.5 |
| `standard_clause` | text null | **пункт / таблица / раздел** документа, §4.5; при заполнении обязателен `standard_document` |
| `acceptance_level` | text null | уровень/класс приёмки (текст) |
| `normative_category_code` | text null | стабильный код нормативной категории |
| `technical_description` | text null | пояснительный текст; **не заменяет** структурированные характеристики (правило 1); обязателен на активацию при `DefectType.requires_description` |
| `location_description` | text null | пояснительная локализация/датум; обязателен при заполненном `axial_position_mm` (§7.9) |
| `evaluation_note` | text null | пояснительная инженерная заметка оценки |
| `technical_note` | text null | пояснительная техническая заметка |
| `activated_by_worker_id` / `activated_at` | int / timestamptz null | заполняются при активации |
| `superseded_by_worker_id` / `superseded_at` | int / timestamptz null | заполняются при замещении новой ревизией |
| `cancelled_by_worker_id` / `cancelled_at` / `cancellation_reason` | | конечный `CANCELLED` (непустая причина) |
| `created_by_worker_id` / `created_at` / `updated_by_worker_id` / `updated_at` | audit | канон 9A–9D-2 |
| `version` | int ≥1 | optimistic locking строки (D09) |

CHECK-инварианты уровня строки:
- `revision_no >= 1`; `version >= 1`;
- `status IN ('DRAFT','ACTIVE','SUPERSEDED','CANCELLED')`;
- `indication_location IS NULL OR indication_location IN ('SURFACE','INTERNAL','THROUGH_THICKNESS','UNKNOWN')`;
- `length_mm IS NULL OR length_mm > 0` (аналогично `width_mm`, `height_mm`, `depth_mm`, `affected_area_mm2`); `quantity IS NULL OR quantity > 0`;
- `axial_position_mm IS NULL OR axial_position_mm >= 0`;
- `circumferential_position_deg IS NULL OR (circumferential_position_deg >= 0 AND circumferential_position_deg < 360)`;
- `orientation IS NULL OR length(trim(orientation)) > 0` (аналогично `surface`, `joint_side`, `standard_document`, `standard_revision`, `standard_clause`);
- `status <> 'CANCELLED' OR (cancelled_at IS NOT NULL AND cancelled_by_worker_id IS NOT NULL AND length(trim(cancellation_reason)) > 0)`;
- `status <> 'SUPERSEDED' OR (superseded_at IS NOT NULL AND superseded_by_worker_id IS NOT NULL)`;
- `(activated_at IS NULL) = (activated_by_worker_id IS NULL)`;
- частичные UNIQUE (D04): `UNIQUE(defect_root_id) WHERE status='ACTIVE'`; `UNIQUE(defect_root_id) WHERE status='DRAFT'`.

Индексы: `ix_defects_defect_root_id`, `ix_defects_status`, `ix_defects_supersedes_defect_id`,
`ix_defects_defect_type_id`, `ix_defects_created_at`.

> **Полное структурное покрытие ADR-022 §5 (решение 9D-3-D13).** Все характеристики ADR-022 §5
> представлены **самостоятельными структурированными полями** (тип, группа — `DefectType.category`;
> локализация — `location_type_id`/`indication_location`; ориентация — `orientation`; поверхность —
> `surface`; сторона соединения — `joint_side`; положение по длине/окружности — `axial_position_mm`/
> `circumferential_position_deg`; длина/ширина/высота/глубина/площадь; количество индикаций —
> `quantity`; нормативные документ/редакция/пункт — `standard_document`/`standard_revision`/
> `standard_clause`; техническое описание — `technical_description`). Полное сопоставление — §4.6.
> Свободный текст (`technical_description`/`location_description`/`evaluation_note`/`technical_note`) —
> **пояснительный** и **не заменяет** структурированные характеристики (правило 1).
>
> **Полнота структуры сразу / обязательность на активацию.** Скалярные технические поля создаются
> сразу и **nullable в `DRAFT`**; enum-/range-/bounded-CHECK действуют только при `NOT NULL`;
> обязательность (тип, расположение, обязательные измерения, описание) проверяется **на активацию**
> сервисом (§8), а не CHECK-ограничением. Плановых `ALTER TABLE` нет.

### 3.3. DefectType (read-only НСИ)

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `code` | text NOT NULL | стабильный код; `UNIQUE(code)` |
| `name` | text NOT NULL | наименование |
| `description` | text null | |
| `category` | text null | группа дефекта |
| `is_active` | bool NOT NULL default true | деактивация — только миграцией |
| `requires_length` / `requires_width` / `requires_height` / `requires_depth` / `requires_area` / `requires_quantity` / `requires_known_indication_location` / `requires_description` | bool NOT NULL default false | флаги обязательности для активации (§8); `requires_height` добавлен для симметрии с новым `height_mm` (D13) |
| `created_at` / `updated_at` | timestamptz | |

### 3.4. DefectLocationType (read-only НСИ)

| Поле | Тип | Примечание |
|---|---|---|
| `id` | uuid PK | |
| `code` | text NOT NULL | `UNIQUE(code)` |
| `name` | text NOT NULL | |
| `description` | text null | |
| `is_active` | bool NOT NULL default true | |
| `created_at` / `updated_at` | timestamptz | |

### 3.5. DefectSequence

| Поле | Тип | Примечание |
|---|---|---|
| `joint_id` | uuid PK FK engineering.joints CASCADE | отдельная последовательность на `Joint` |
| `last_value` | int ≥0 NOT NULL default 0 | |
| `updated_at` | timestamptz | |

Значение выдаётся атомарно `INSERT … ON CONFLICT (joint_id) DO UPDATE SET last_value = last_value + 1
… RETURNING last_value` в текущей транзакции (как `QualityFindingSequence`) — гонки `MAX()+1` нет.

### 3.6. DefectEvent (append-only)

Поля по канону 9D-1/9D-2 (`QualityFindingEvent`): `id` (uuid PK), `defect_id` (uuid FK defects
RESTRICT), `defect_root_id` (uuid null — для истории цепочки), `event_type` (text CHECK, §9),
`from_status` / `to_status` (text null), `actor_worker_id` (Integer, без FK), `actor_role` (text null),
`reason` (text null), `event_metadata` (JSONB, колонка `metadata`), `correlation_id` (uuid null),
`defect_version` (int — версия ревизии ПОСЛЕ команды), `created_at`. API изменения/удаления событий
нет; событие пишется в одной транзакции с командой.

---

## 4. Перечисления (CHECK-справочники)

### 4.1. status — DefectStatus

```text
DRAFT       — черновая техническая карточка (может быть неполной)
ACTIVE      — действующая подтверждённая техническая запись
SUPERSEDED  — ревизия заменена новой технической версией (supersede)
CANCELLED   — карточка аннулирована как ошибочная/дублирующая
```

Запрещённые статусы (ADR-022 §6, **не вводить** ни в enum, ни в код): `REPAIRED`, `REMOVED`,
`REWELDED`, `ACCEPTED`, `CLOSED`, `PASSED_REINSPECTION`.

### 4.2. indication_location — DefectIndicationLocation

```text
SURFACE · INTERNAL · THROUGH_THICKNESS · UNKNOWN
```

Значение относится к экземпляру ревизии, **не** вычисляется из метода контроля и **не** является
жёстким свойством `DefectType`. `UNKNOWN` допустим в `DRAFT`; для `ACTIVE` допустимость `UNKNOWN`
определяется `DefectType.requires_known_indication_location` (§8). Изменение у `ACTIVE` невозможно
(immutable) — только новой ревизией.

### 4.3. event_type — DefectEventType (ADR-022 §11)

```text
DEFECT_DRAFT_CREATED · DEFECT_UPDATED · DEFECT_ACTIVATED
DEFECT_REVISION_CREATED · DEFECT_SUPERSEDED · DEFECT_CANCELLED
```

### 4.4. orientation / surface / joint_side — контролируемые bounded strings (правило 5)

Ни ADR-022, ни текущий проектный канон **не задают** устойчивого перечня значений для этих
характеристик. Поэтому, по правилу 5, применяется **bounded string / reference strategy без
административного CRUD**, а **не** enum/CHECK-перечень (в отличие от `indication_location`, где
устойчивый перечень зафиксирован §4.2). Поля — `String(30)`/`String(20)`/`String(30)`, CHECK
«непусто при NOT NULL». Значения контролируются на уровне схемы (тип, длина, непустота) и
**рекомендованного словаря** (guidance, не DB-enum). Рекомендованные стартовые словари:

```text
orientation : LONGITUDINAL · TRANSVERSE · ANGULAR · SCATTERED   (по оси шва; расширяемо)
surface     : OUTER · INNER · BOTH                              (поверхность соединения)
joint_side  : SIDE_1 · SIDE_2 · CENTERLINE                      (сторона относительно оси шва)
```

Административного CRUD, company/project-scope и НСИ-версионирования для них **не создаётся**. Если
проект впоследствии утвердит канонический перечень, поля мигрируют в CHECK-enum или read-only
reference-таблицу отдельным решением (вне scope 9D-3). При нестандартном значении используется
`location_description`/`technical_description` как пояснение (правило 1 — текст **дополняет**, а не
заменяет структурированное поле).

### 4.5. Нормативная ссылка — раздельные поля (правила 6–8)

Нормативная ссылка хранится **тремя раздельными структурированными полями**: `standard_document`
(документ), `standard_revision` (редакция/год), `standard_clause` (пункт/таблица/раздел).
Независимый `standard_reference`, способный расходиться с ними, **не хранится** (правило 7 — поле
удалено из модели). Для отображения объединённая ссылка — **производное (computed) поле** уровня
API/read-схемы, напр. `standard_reference_display` (§10), собираемое из трёх полей по шаблону
`«{standard_document} {standard_revision}, {standard_clause}»` (пустые части опускаются). Оно не
персистится и потому не может разойтись со структурированными полями (правило 8). Консистентность:
`standard_clause`/`standard_revision` без `standard_document` недопустимы (`DEFECT_STANDARD_DOCUMENT_REQUIRED`).

### 4.6. Соответствие ADR-022 §5 (полное структурное покрытие, D13)

| ADR-022 §5 характеристика | Поле Spec | Тип / ограничение |
|---|---|---|
| тип дефекта | `defect_type_id` | uuid FK `defect_types` (read-only НСИ) |
| группа дефекта | `DefectType.category` | text (в справочнике типа) |
| локализация | `location_type_id` + `location_description` | uuid FK `defect_location_types` + text |
| ориентация | `orientation` | bounded string `String(30)`, §4.4 |
| поверхность | `surface` | bounded string `String(20)`, §4.4 |
| сторона соединения | `joint_side` | bounded string `String(30)`, §4.4 |
| положение по длине шва | `axial_position_mm` | numeric ≥ 0; при заполнении обязателен `location_description` (§7.9) |
| положение по окружности шва | `circumferential_position_deg` | numeric `[0, 360)`, нормализация mod 360 (§7.9) |
| длина | `length_mm` | numeric > 0 при NOT NULL |
| ширина | `width_mm` | numeric > 0 при NOT NULL |
| высота | `height_mm` | numeric > 0 при NOT NULL |
| глубина | `depth_mm` | numeric > 0 при NOT NULL |
| площадь | `affected_area_mm2` | numeric > 0 при NOT NULL |
| количество индикаций | `quantity` | int > 0 при NOT NULL |
| нормативное обозначение / документ | `standard_document` | text, §4.5 |
| редакция документа | `standard_revision` | text, §4.5 |
| пункт или таблица | `standard_clause` | text, §4.5 (требует `standard_document`) |
| техническое описание | `technical_description` | text (пояснение, **не** заменяет структуру; правило 1) |

Дополнительно (сверх §5, из ранее согласованной модели): `acceptance_level`, `normative_category_code`
(структурированные), `evaluation_note`, `technical_note` (пояснительный текст). Ни одно свободное
текстовое поле не подменяет структурированную характеристику §5 (правило 1).

---

## 5. Lifecycle ревизии

Модель исполнения supersede — **supersede-time** (аддендум
[[ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING|D-3B-S01]]): команда `supersede` в одной транзакции гасит
предыдущую `ACTIVE` и создаёт новую `DRAFT`; приёмка новой версии — отдельной командой `activate`.

```text
ACTIVE revision N
    ↓ supersede
SUPERSEDED revision N
    +
DRAFT revision N+1
    ↓ activate
ACTIVE revision N+1
```

Полная диаграмма статусов одной ревизии:

```text
DRAFT → ACTIVE → SUPERSEDED
          ↓
       CANCELLED
```

| Переход | Команда | Роль | Условия |
|---|---|---|---|
| — → DRAFT (revision_no=1) | `create-defect` (activate=false) | `WELDING_ENGINEER` | создаётся `DefectRoot` (+ `defect_no`, `UNIQUE(engineering_evaluation_id)`) и первая `DRAFT`-ревизия; событие `DEFECT_DRAFT_CREATED` |
| — → ACTIVE (revision_no=1) | `create-defect` (activate=true) | `WELDING_ENGINEER` | то же + полная валидация §8; событие `DEFECT_ACTIVATED` |
| DRAFT → DRAFT | `update-defect` (PATCH) | `WELDING_ENGINEER` | ревизия в `DRAFT`; правка технических полей; событие `DEFECT_UPDATED` |
| DRAFT → ACTIVE | `activate-defect` | `WELDING_ENGINEER` | валидация §8; приёмка `DRAFT`-ревизии как действующей; событие `DEFECT_ACTIVATED`. Замещения предыдущей здесь **нет** — оно уже выполнено при `supersede` (supersede-time) |
| ACTIVE → SUPERSEDED + — → DRAFT (revision_no+1) | `supersede-defect` | `WELDING_ENGINEER` | у цепочки есть `ACTIVE`; нет открытой `DRAFT`; **атомарно**: предыдущая `ACTIVE` → `SUPERSEDED` **и** создаётся новая `DRAFT`-ревизия (`supersedes_defect_id` = замещаемая `ACTIVE`, копия технических полей как старт); события `DEFECT_SUPERSEDED` предыдущей + `DEFECT_REVISION_CREATED` новой. После команды `ACTIVE` в цепочке нет |
| DRAFT → CANCELLED | `cancel-defect` | `WELDING_ENGINEER` / `CHIEF_WELDER` | причина обязательна; событие `DEFECT_CANCELLED` |
| ACTIVE → CANCELLED | `cancel-defect` | `WELDING_ENGINEER` / `CHIEF_WELDER` | причина обязательна; `active_defect_id` цепочки → `NULL`; событие `DEFECT_CANCELLED` |

Запрещённые переходы: `ACTIVE → DRAFT`; `CANCELLED → *` (в т.ч. восстановление); `SUPERSEDED → *`
(конечный, кроме исторического чтения). `SUPERSEDED` и `CANCELLED` **не означают устранение дефекта**
(ADR-022 §6).

Инварианты lifecycle: изменяется только `DRAFT`; после активации существенные технические поля
immutable (§6); в цепочке (`defect_root_id`) — не более одной `ACTIVE` и не более одной открытой
`DRAFT` (D04); `SUPERSEDED` наступает **в момент `supersede`** (supersede-time). Промежуточное
состояние `SUPERSEDED + DRAFT` (0 `ACTIVE` в цепочке) — корректно (аддендум D-3B-S01).

---

## 6. Граница неизменяемости

**Структурно immutable всегда** (нельзя менять ни в одном статусе): `id`, `defect_root_id`,
`revision_no`, `supersedes_defect_id`, `created_by_worker_id`, `created_at`; на уровне корня —
`DefectRoot.id`, `joint_id`, `engineering_evaluation_id`, `defect_no`.

**Immutable после активации** (существенные технические поля, ADR-022 §7): `defect_type_id`,
`location_type_id`, `indication_location`, `orientation`, `surface`, `joint_side`,
`axial_position_mm`, `circumferential_position_deg`, `length_mm`, `width_mm`, `height_mm`, `depth_mm`,
`affected_area_mm2`, `quantity`, `standard_document`, `standard_revision`, `standard_clause`,
`acceptance_level`, `normative_category_code`, `technical_description`, `location_description`,
`evaluation_note`, `technical_note`. Все они **редактируемы в `DRAFT`**, валидируются при активации
(§8), immutable в `ACTIVE`, изменяются только через supersede и **копируются** в новую ревизию (§7.5).

Исправление действующей записи — **только supersede** (новая `DRAFT`-ревизия → активация). `PATCH`
технических полей `ACTIVE` запрещён (`DEFECT_ACTIVE_IMMUTABLE`, D11). ADR-022 не определяет
«несущественные» поля, редактируемые у `ACTIVE`, поэтому у `ACTIVE` не редактируется ничего.

Изменение `QualityFinding`, `EngineeringEvaluation` или её ревизии **не** синхронизирует `Defect`
автоматически: `Defect` — самостоятельный инженерно подтверждённый снимок (ADR-022 §15/§7).

---

## 7. Правила происхождения, цепочки, нумерации

- **7.1. Источник (D10).** `engineering_evaluation_id` (на `DefectRoot`) обязан ссылаться на
  `EngineeringEvaluation`, чья `effective_revision_id` указывает на `EngineeringEvaluationRevision`
  со `status='EFFECTIVE'` и `classification='CONFIRMED_DEFECT'`. Иначе —
  `DEFECT_EVALUATION_NOT_CONFIRMED` / `DEFECT_EVALUATION_NOT_EFFECTIVE`. Прямое создание из результата
  НК запрещено; `FindingDisposition` не создаётся и не требуется.
- **7.2. Joint invariant (ADR-022 §4/§8).** `DefectRoot.joint_id` = `evaluation → finding → joint_id`.
  Несовпадение → `DEFECT_JOINT_MISMATCH`. `joint_id` обязателен и неизменяем; перенос дефекта между
  `Joint` запрещён; `CHIEF_WELDER` инвариант не обходит.
- **7.3. Кардинальность и устойчивость (D06/D07/D08).** `UNIQUE(engineering_evaluation_id)` на
  `DefectRoot` → одна оценка `CONFIRMED_DEFECT` порождает ≤1 корневую цепочку. Попытка создать вторую
  → `DEFECT_ROOT_ALREADY_EXISTS` (409), в т.ч. если единственная ревизия существующей цепочки
  `CANCELLED` (корень сохраняется — D08). Повторная регистрация требует новой `EngineeringEvaluation`.
- **7.4. Нумерация (`defect_no`).** `defect_no` — per-joint, выдаётся один раз при создании
  `DefectRoot` через `DefectSequence` (`ON CONFLICT … RETURNING`); начинается с `1`; неизменяем;
  общий для всех ревизий цепочки; номер `CANCELLED`-цепочки не переиспользуется (корень сохраняется).
  `MAX(defect_no)+1` **запрещён**.
- **7.5. Ревизии и supersede (supersede-time; аддендум D-3B-S01).** `revision_no` монотонно растёт в
  цепочке (1, 2, 3…). `supersede-defect` в одной атомарной транзакции **переводит предыдущую `ACTIVE`
  → `SUPERSEDED`** и создаёт новую `DRAFT`-ревизию (`supersedes_defect_id` = замещаемая `ACTIVE`),
  **копируя все структурированные технические поля** предыдущей `ACTIVE` как стартовые: классификацию
  (`defect_type_id`, `location_type_id`, `indication_location`), геометрию/положение (`orientation`,
  `surface`, `joint_side`, `axial_position_mm`, `circumferential_position_deg`), измерения (`length_mm`,
  `width_mm`, `height_mm`, `depth_mm`, `affected_area_mm2`, `quantity`), нормативные
  (`standard_document`, `standard_revision`, `standard_clause`, `acceptance_level`,
  `normative_category_code`) и пояснительные (`technical_description`, `location_description`,
  `evaluation_note`, `technical_note`). Команда обновляет `DefectRoot.current_defect_id` = новая `DRAFT`
  и `active_defect_id` = `NULL` (после supersede действующей `ACTIVE` нет). События: `DEFECT_SUPERSEDED`
  предыдущей + `DEFECT_REVISION_CREATED` новой; в `event_metadata` `DEFECT_REVISION_CREATED` фиксируется
  перечень скопированных/изменённых полей и `previous_defect_id`/`new_defect_id` (audit metadata
  ревизии). Приёмка новой версии как действующей — **отдельной** командой `activate` (`DRAFT → ACTIVE`,
  `DEFECT_ACTIVATED`, `active_defect_id` = новая ревизия). В цепочке всегда ≤1 `ACTIVE` и ≤1 открытая
  `DRAFT` (D04); допустимо промежуточное состояние `SUPERSEDED + DRAFT` (0 `ACTIVE`).
- **7.6. Валидация справочников при активации.** `defect_type_id`/`location_type_id` обязаны
  ссылаться на **активные** (`is_active=true`) записи справочников при активации/создании-`ACTIVE`
  (`DEFECT_TYPE_INACTIVE` / `DEFECT_LOCATION_TYPE_INACTIVE`). Историческое чтение уже активированной
  ревизии возвращает исходное справочное значение даже после его деактивации (FK сохраняется).
- **7.7. Optimistic concurrency (D09).** Каждая изменяющая команда несёт `expected_version`;
  несовпадение → `DEFECT_VERSION_CONFLICT` (409). `version` инкрементируется при каждой команде,
  меняющей строку (`update`/`activate`/`cancel`/`supersede`-замещение). `version` — механизм
  конкурентного контроля, **отдельный** от `revision_no`.
- **7.8. Нормативная ссылка (правила 6–8).** Только раздельные `standard_document`/`standard_revision`/
  `standard_clause` (§4.5); независимый `standard_reference` не хранится. `standard_clause` или
  `standard_revision` без `standard_document` → `DEFECT_STANDARD_DOCUMENT_REQUIRED`. Объединённое
  представление `standard_reference_display` — производное поле read-схемы (§10), не персистится.
- **7.9. Позиционные характеристики (§5; правила 3–4).**
  - `circumferential_position_deg` — положение по окружности шва в **градусах**, допустимый диапазон
    **`[0, 360)`** (`0` включительно, `360` исключается). Нормализация входного значения — **по модулю
    360** в `[0, 360)` до сохранения (напр. `370 → 10`, `-15 → 345`, `360 → 0`). Конвенция отсчёта:
    `0°` — верх шва (12 часов), рост по часовой стрелке; уточнение при необходимости — в
    `location_description`. Значение вне диапазона после нормализации не сохраняется —
    `DEFECT_CIRC_POSITION_OUT_OF_RANGE`.
  - `axial_position_mm` — положение по длине шва, **`≥ 0`** — расстояние от датума (точки отсчёта). Так
    как единый канонический датум не зафиксирован, при заполненном `axial_position_mm` **обязателен**
    непустой `location_description` с описанием датума/точки отсчёта
    (`DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED`).

---

## 8. Validation matrix (активация)

Единый validation pipeline применяется при: `create-defect(activate=true)`; `activate-defect`
(`DRAFT → ACTIVE`, включая приёмку supersede-ревизии). В supersede-time модели (аддендум D-3B-S01)
сама команда `supersede` создаёт **`DRAFT`** и проходит только структурную проверку (CHECK-уровень),
а полная §8-проверка комплектности выполняется при `activate` этой `DRAFT`. Проверки (агрегированный
результат — все нарушения сразу, как 9D-2-C11):

| Проверка | Условие | Ошибка |
|---|---|---|
| Тип задан | `defect_type_id IS NOT NULL` | `DEFECT_TYPE_REQUIRED` |
| Тип активен | `DefectType.is_active` | `DEFECT_TYPE_INACTIVE` |
| Расположение задано | `location_type_id IS NOT NULL` | `DEFECT_LOCATION_TYPE_REQUIRED` |
| Расположение активно | `DefectLocationType.is_active` | `DEFECT_LOCATION_TYPE_INACTIVE` |
| indication_location задан | `indication_location IS NOT NULL` | `DEFECT_INDICATION_LOCATION_REQUIRED` |
| indication_location известен | если `DefectType.requires_known_indication_location` → `indication_location <> 'UNKNOWN'` | `DEFECT_INDICATION_UNKNOWN_NOT_ALLOWED` |
| Описание | если `requires_description` → `technical_description` непустой | `DEFECT_DESCRIPTION_REQUIRED` |
| Измерения (наличие) | для каждого `requires_length/width/height/depth/area/quantity` → соответствующее поле `NOT NULL` | `DEFECT_MEASUREMENT_REQUIRED` |
| Измерения (положительность) | все заполненные numeric > 0 (`length_mm`, `width_mm`, `height_mm`, `depth_mm`, `affected_area_mm2`); `quantity` > 0 | `DEFECT_MEASUREMENT_NOT_POSITIVE` |
| Положение по окружности | `circumferential_position_deg IS NULL OR [0,360)` (после нормализации, §7.9) | `DEFECT_CIRC_POSITION_OUT_OF_RANGE` |
| Положение по длине | если `axial_position_mm IS NOT NULL` → `location_description` непустой (§7.9) | `DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED` |
| Нормативная ссылка | `standard_clause`/`standard_revision` заданы → `standard_document` непустой (§7.8) | `DEFECT_STANDARD_DOCUMENT_REQUIRED` |
| Основание — CONFIRMED_DEFECT | effective revision `status='EFFECTIVE'` и `classification='CONFIRMED_DEFECT'` | `DEFECT_EVALUATION_NOT_CONFIRMED` / `DEFECT_EVALUATION_NOT_EFFECTIVE` |
| Joint match | `root.joint_id == evaluation→finding→joint_id` | `DEFECT_JOINT_MISMATCH` |
| Уникальность цепочки | нет другой цепочки на этой оценке | `DEFECT_ROOT_ALREADY_EXISTS` |
| Одна ACTIVE в цепочке | при активации — в цепочке нет иной `ACTIVE` (в supersede-time предыдущая уже `SUPERSEDED`, поэтому `ACTIVE` нет) | `DEFECT_INVALID_TRANSITION` |

Для `create-defect(activate=false)` (DRAFT) обязателен только контекст создания цепочки:
`engineering_evaluation_id` (существует, `CONFIRMED_DEFECT`/`EFFECTIVE` — проверяется уже при создании
корня, чтобы не завести черновик без основания), Joint match, уникальность цепочки. Технические поля
`DRAFT` могут быть неполными (ADR-022 §6).

> **Инвариант границы (ADR-022 §8–§10).** Ни одна команда `Defect` **не** меняет `QualityFinding`,
> `EngineeringEvaluation` или её ревизию; **не** создаёт `FindingDisposition`, Repair, Reweld,
> Reinspection, acceptance или закрытие; **не** пишет признаки устранения. В модуле 9D-3 запрещены
> любые вызовы, изменяющие сущности вне контура `Defect*`.

---

## 9. События (append-only)

```text
DEFECT_DRAFT_CREATED   DEFECT_UPDATED   DEFECT_ACTIVATED
DEFECT_REVISION_CREATED   DEFECT_SUPERSEDED   DEFECT_CANCELLED
```

Соответствие командам (supersede-time; аддендум D-3B-S01): `create-defect(DRAFT)` →
`DEFECT_DRAFT_CREATED`; `create-defect(ACTIVE)`/`activate-defect` → `DEFECT_ACTIVATED`;
`update-defect` → `DEFECT_UPDATED`; **`supersede-defect` → `DEFECT_SUPERSEDED` (предыдущей, `ACTIVE →
SUPERSEDED`) + `DEFECT_REVISION_CREATED` (новой, `NULL → DRAFT`)** — оба в одной транзакции; приёмка
новой `DRAFT` командой `activate` → `DEFECT_ACTIVATED` (`DRAFT → ACTIVE`, **без** повторного
`DEFECT_SUPERSEDED`); `cancel-defect` → `DEFECT_CANCELLED`. Команда `supersede` **не** создаёт
`DEFECT_ACTIVATED`. Каждое событие хранит actor, `actor_role`, время, `reason` (обязателен для
`CANCELLED`; для `SUPERSEDED` — причина из команды supersede), `from_status`/`to_status`,
`defect_version` (после команды), `correlation_id` (если используется). События не заменяют
Repair/Reweld/Reinspection/историю ремонта (их нет в 9D-3).

---

## 10. API (команды, префикс `/api/v1`)

| Метод/путь | Команда | Роль |
|---|---|---|
| `POST /quality/defects` | создать `Defect` (DRAFT или ACTIVE); `joint_id`+`engineering_evaluation_id` в body | `WELDING_ENGINEER` |
| `GET /quality/defects?joint_id={id}[&status=&defect_root_id=&engineering_evaluation_id=&limit=&offset=]` | список (фильтры) | READ-роли |
| `GET /quality/defects/{defect_id}` | одна ревизия | READ-роли |
| `PATCH /quality/defects/{defect_id}` | правка `DRAFT` (D11; на `ACTIVE` → `DEFECT_ACTIVE_IMMUTABLE`) | `WELDING_ENGINEER` |
| `POST /quality/defects/{defect_id}/activate` | `DRAFT → ACTIVE` (полная валидация §8; приёмка ревизии как действующей — замещения предыдущей здесь нет, оно выполнено при supersede) | `WELDING_ENGINEER` |
| `POST /quality/defects/{defect_id}/supersede` | supersede-time (D05, аддендум D-3B-S01): атомарно предыдущая `ACTIVE → SUPERSEDED` + новая `DRAFT`-ревизия цепочки | `WELDING_ENGINEER` |
| `POST /quality/defects/{defect_id}/cancel` | `DRAFT/ACTIVE → CANCELLED` (причина обязательна) | `WELDING_ENGINEER` / `CHIEF_WELDER` |
| `GET /quality/defects/{defect_id}/history` | журнал событий **цепочки** (по `defect_root_id`) | READ-роли |
| `GET /quality/defect-types` · `GET /quality/defect-types/{id}` | read-only НСИ; `active_only=true` по умолчанию | READ-роли |
| `GET /quality/defect-location-types` · `…/{id}` | read-only НСИ; `active_only=true` по умолчанию | READ-роли |

Все изменяющие команды несут `expected_version` (optimistic locking) и `actor` из `X-User-Id`.
`joint_id` — в create body (для списков — query). Nested-маршруты `/quality/joints/{joint_id}/defects`
**не используются** (фактическая конвенция проекта). Отдельного link/unlink API для оценки **нет**
(прямой FK, не M:N). Справочники — **без** write-API (`POST/PATCH/PUT/DELETE` → 405/не заводятся).

`POST`/`PATCH` (create/DRAFT-edit) принимают все структурированные поля §5 (§3.2/§4.6). Read-схема
(`GET …/defects/{id}` и список) возвращает раздельные нормативные поля `standard_document`/
`standard_revision`/`standard_clause` **и** производное `standard_reference_display` — вычисляемое
из них представление (§4.5), **не персистится** и потому не расходится со структурированными полями
(правило 8). Отдельного независимого `standard_reference` в модели/схеме нет (правило 7).

---

## 11. Коды ошибок (машинные)

```text
DEFECT_NOT_FOUND · DEFECT_ROLE_DENIED · DEFECT_VERSION_CONFLICT
DEFECT_EVALUATION_NOT_FOUND · DEFECT_EVALUATION_NOT_CONFIRMED · DEFECT_EVALUATION_NOT_EFFECTIVE
DEFECT_JOINT_MISMATCH · DEFECT_ROOT_ALREADY_EXISTS
DEFECT_NOT_DRAFT · DEFECT_INVALID_TRANSITION · DEFECT_ACTIVE_IMMUTABLE · DEFECT_CANCELLED_IMMUTABLE
DEFECT_ACTIVATION_INCOMPLETE · DEFECT_TYPE_REQUIRED · DEFECT_TYPE_INACTIVE
DEFECT_LOCATION_TYPE_REQUIRED · DEFECT_LOCATION_TYPE_INACTIVE
DEFECT_INDICATION_LOCATION_REQUIRED · DEFECT_INDICATION_UNKNOWN_NOT_ALLOWED · DEFECT_DESCRIPTION_REQUIRED
DEFECT_MEASUREMENT_REQUIRED · DEFECT_MEASUREMENT_NOT_POSITIVE
DEFECT_CIRC_POSITION_OUT_OF_RANGE · DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED · DEFECT_STANDARD_DOCUMENT_REQUIRED
DEFECT_SUPERSEDE_REQUIRES_ACTIVE · DEFECT_CHAIN_HAS_OPEN_DRAFT · DEFECT_ALREADY_SUPERSEDED
DEFECT_CANCEL_REASON_REQUIRED · DEFECT_REFERENCE_READ_ONLY
```

HTTP: **403** (`ROLE_DENIED`); **404** (`NOT_FOUND`, `EVALUATION_NOT_FOUND`, скрыто по scope);
**409** (`VERSION_CONFLICT`, `INVALID_TRANSITION`, `ROOT_ALREADY_EXISTS`, `ACTIVE_IMMUTABLE`,
`CANCELLED_IMMUTABLE`, `ALREADY_SUPERSEDED`, `CHAIN_HAS_OPEN_DRAFT`, `SUPERSEDE_REQUIRES_ACTIVE`,
`NOT_DRAFT`); **422** (`ACTIVATION_INCOMPLETE` и агрегированные проверки §8: `*_REQUIRED`,
`*_INACTIVE`, `MEASUREMENT_*`, `INDICATION_*`, `CIRC_POSITION_OUT_OF_RANGE`,
`AXIAL_POSITION_CONTEXT_REQUIRED`, `STANDARD_DOCUMENT_REQUIRED`, `EVALUATION_NOT_CONFIRMED`,
`EVALUATION_NOT_EFFECTIVE`, `JOINT_MISMATCH`, `CANCEL_REASON_REQUIRED`).

---

## 12. Миграция

Одна Alembic-ревизия `defect_technical_model`. `down_revision` — текущий единственный head
`20260719_20_eng_evaluation_core` (проверить `alembic heads`: должен быть ровно один; при нескольких —
сначала свести к одному). Содержимое: **6 таблиц** схемы `quality` (`defect_types`,
`defect_location_types`, `defect_roots`, `defects`, `defect_sequences`, `defect_events`) со всеми
CHECK/UNIQUE/частичными UNIQUE/индексами (§3) и **seed** справочников (§13) в теле `upgrade`.
`defects` содержит **все** структурированные поля §5 (D13): `orientation`/`surface`/`joint_side`
(bounded), `axial_position_mm`/`circumferential_position_deg`, `height_mm`, `standard_document`/
`standard_revision`/`standard_clause` — сразу и nullable, с CHECK положительности/диапазона/непустоты
(§3.2); независимого `standard_reference` **нет**. `defect_types` содержит `requires_height` (D13).
Все поля создаются одной миграцией; плановых `ALTER TABLE` нет.

`downgrade()` — **полноценный** (канон проекта: 9D-2 Spec §12 «drop в обратном порядке с учётом FK»):
`defect_events` → `defects` → `defect_sequences` → `defect_roots` → `defect_location_types` →
`defect_types` (с учётом FK и seed). Существующие таблицы не трогать; данных для бэкофилла нет.
`M:N`-таблицы связи оценок **не создавать** (D07).

---

## 13. Seed (идемпотентный, стабильные коды)

`DefectType.code`: `CRACK`, `LACK_OF_FUSION`, `LACK_OF_PENETRATION`, `POROSITY`, `SLAG_INCLUSION`,
`UNDERCUT`, `BURN_THROUGH`, `OTHER`.
`DefectLocationType.code`: `WELD_METAL`, `FUSION_LINE`, `HEAT_AFFECTED_ZONE`, `BASE_METAL`, `ROOT`,
`FACE`, `OTHER`.

Seed: минимальный; идемпотентный (по `code`, upsert без перезаписи изменённых вручную флагов —
вставка только отсутствующих); пригоден для upgrade на чистой и существующей БД; **не** полный
нормативный классификатор (не заявлять как исчерпывающий ГОСТ/ISO/ASME); значения меняются только
контролируемой миграцией. Для `OTHER` `DefectType.requires_description=true` (техническое описание
обязательно). Стартовые `requires_*` (включая новый `requires_height`) — консервативные значения по
умолчанию (`false`, кроме `OTHER.requires_description=true`), уточняются при реализации и фиксируются
миграцией (не влияет на канон).

---

## 14. Тесты (pytest, как `test_quality_findings_api.py`)

**Models & migration:** таблицы/колонки/типы; CHECK (status, indication_location, положительность
numeric, cancelled/superseded поля); FK; `UNIQUE(engineering_evaluation_id)`,
`UNIQUE(joint_id, defect_no)`, `UNIQUE(defect_root_id, revision_no)`, частичные UNIQUE ACTIVE/DRAFT;
actor-поля `Integer`; индексы; seed; clean upgrade; upgrade с текущего head; ровно один head; downgrade.

**Numbering:** первый `defect_no=1`; последовательные номера; независимые последовательности по
`Joint`; номер `CANCELLED`-цепочки не переиспользуется; конкурентное создание не выдаёт одинаковые
номера; rollback safety.

**Lifecycle & supersede (supersede-time; аддендум D-3B-S01):** create DRAFT; create ACTIVE;
`DRAFT→ACTIVE`; `DRAFT→CANCELLED`; `ACTIVE→CANCELLED`; supersede → предыдущая **`ACTIVE→SUPERSEDED`
атомарно** + новая `DRAFT`-ревизия (`revision_no+1`, `supersedes_defect_id`); после supersede в цепочке
**нет `ACTIVE`** (`active_defect_id = NULL`, `get_current_active_revision → None`, ровно одна открытая
`DRAFT`); события `DEFECT_SUPERSEDED`+`DEFECT_REVISION_CREATED` **без** `DEFECT_ACTIVATED`; отдельная
команда `activate` новой `DRAFT` → `DRAFT→ACTIVE`, `DEFECT_ACTIVATED`, ровно одна `ACTIVE`; полная
§8-валидация выполняется именно при `activate` (неполная `DRAFT` создаётся, но её активация
отклоняется); rollback на структурно недопустимом patch сохраняет предыдущую `ACTIVE`; double supersede
создаёт только одну `DRAFT`; запрет второй открытой `DRAFT` (`DEFECT_CHAIN_HAS_OPEN_DRAFT`); supersede
без `ACTIVE` (`DEFECT_SUPERSEDE_REQUIRES_ACTIVE`); запрет `ACTIVE→DRAFT`, восстановления `CANCELLED`,
изменения `SUPERSEDED`.

**Activation validation:** каждая строка §8 (валид/невалид): нет типа/расположения; тип/расположение
неактивны; отсутствует обязательное измерение; неположительное измерение; `UNKNOWN` при
`requires_known_indication_location`; нет описания при `requires_description`; оценка не
`CONFIRMED_DEFECT`/не `EFFECTIVE`; несовпадение `Joint`; успешная активация; агрегированный список
нарушений.

**Структурные характеристики §5 (D13, правило 10):**
- **высота:** `height_mm > 0` — валидно; `height_mm = 0`/отрицательная → `DEFECT_MEASUREMENT_NOT_POSITIVE`;
  `requires_height=true` без `height_mm` → `DEFECT_MEASUREMENT_REQUIRED`;
- **положение по окружности:** `circumferential_position_deg` в `[0,360)` — валидно; `360`/`-1`/`>360`
  до нормализации → нормализуются (`370→10`, `-15→345`, `360→0`); значение вне диапазона после
  нормализации → `DEFECT_CIRC_POSITION_OUT_OF_RANGE`;
- **положение по длине:** `axial_position_mm` заполнено без `location_description` →
  `DEFECT_AXIAL_POSITION_CONTEXT_REQUIRED`; `axial_position_mm < 0` → CHECK-нарушение;
- **нормативное представление:** раздельные `standard_document`/`standard_revision`/`standard_clause`
  сохраняются структурно; `standard_clause`/`standard_revision` без `standard_document` →
  `DEFECT_STANDARD_DOCUMENT_REQUIRED`; read-схема отдаёт `standard_reference_display`, собранное из
  трёх полей; **отсутствие расхождения** между структурированными полями и производным представлением
  (нет независимого хранимого `standard_reference`);
- **ориентация/поверхность/сторона:** bounded string сохраняется как задано; пустая строка при NOT NULL
  → CHECK-нарушение; рекомендованный словарь — не жёсткий enum (значение вне словаря принимается);
- **supersede копирует все §5-поля:** новая ревизия наследует `orientation`/`surface`/`joint_side`/
  `axial_position_mm`/`circumferential_position_deg`/`height_mm`/`standard_document`/`standard_revision`/
  `standard_clause` (и прочие технические) из предыдущей `ACTIVE`; `event_metadata` содержит перечень
  скопированных полей;
- **immutable §5 в ACTIVE:** `PATCH` любого §5-поля у `ACTIVE` → `DEFECT_ACTIVE_IMMUTABLE`; изменение —
  только через supersede.

**Evaluation link & cardinality:** прямой FK (не M:N); вторая цепочка на той же оценке →
`DEFECT_ROOT_ALREADY_EXISTS`; `CANCELLED` не освобождает оценку (D08); Joint выводится через
`evaluation→finding`; `Defect` не хранит `source_result_item_id`.

**ACTIVE immutability:** `PATCH` на `ACTIVE` → `DEFECT_ACTIVE_IMMUTABLE`; изменение
`QualityFinding`/`EngineeringEvaluation` не синхронизирует `Defect`; неизменяемость
`joint_id`/`engineering_evaluation_id`/`defect_no`/`revision_no`.

**Optimistic concurrency:** `expected_version` конфликт → `DEFECT_VERSION_CONFLICT`; инкремент версии;
параллельные команды.

**Reference data:** seed; уникальные `code`; read-only list/detail; `active_only=true` по умолчанию;
`active_only=false`; историческое чтение неактивного значения активной ревизией; отсутствие
write-endpoints; отсутствие CRUD-RBAC.

**RBAC:** `OGS_ENGINEER`/`CHIEF_WELDER` — запись; непривилегированные роли — только чтение; скрытый по
scope ресурс → 404; мутации не расширяются на COMPANY-scope; override `CHIEF_WELDER` не обходит
`joint_id`/`engineering_evaluation_id`/`defect_no`, не восстанавливает `CANCELLED`, не редактирует НСИ.

**Scope-exclusion (архитектурные assertions):** в моделях/схемах/enum/миграции отсутствуют
`FindingDisposition`, `DefectAcceptanceAssessment`, `RepairZone`/`Repair`/`RepairAttempt`, `Reweld`,
`Reinspection`, `repair_required`/`repair_status`/`is_repaired`/`is_closed`/`closed_at`/`resolved_at`/
`eliminated_at`, `source_result_item_id`, M:N-таблица связи оценок.

---

## 15. Контрактная граница на будущее (не реализуется в 9D-3)

- `FindingDisposition` (что сделать с находкой/дефектом) — Task 9D-4; `Defect` не хранит disposition
  и решение о пригодности.
- Repair / Reweld / Reinspection / закрытие — отдельные будущие контуры; `Defect` сохраняется как
  исторический технический факт и не меняется ремонтом/повторным контролем (ADR-022 §9).
- Новый дефект, выявленный повторным контролем, проходит новый цикл
  `QualityFinding → EngineeringEvaluation → Defect` (новая цепочка/`DefectRoot`).

---

## 16. Definition of Done

Код реализует §3–§11; миграция §12 применяется идемпотентно (clean + с текущего head), `downgrade`
полноценный, ровно один head; seed §13 идемпотентен; тесты §14 зелёные; линтер чист; `compileall`
проходит; канон ADR-022 не изменялся; в модуле 9D-3 нет ни одного пути, меняющего `QualityFinding`/
`EngineeringEvaluation` или создающего `FindingDisposition`/Repair/Reweld/Reinspection/acceptance/
закрытие; scope-exclusion тесты подтверждают отсутствие запрещённых полей и сущностей.
