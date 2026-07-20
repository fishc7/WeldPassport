# Task 9D-3C — Defect Schemas, API and RBAC Integration Spec

## 1. Document Status

```
Task 9D-3C — Schemas, API and RBAC Integration
Status: Draft for Review
```

- Автор: AI-агент (по заданию владельца)
- Дата: 2026-07-20
- Тип: Implementation Spec (подготовка к реализации; код не создаётся этим документом)
- Источники истины:
  1. ADR-022 «Defect Technical Model»
  2. ADR-022 Addendum **D-3B-S01** «Defect Supersede Timing Model»
  3. `TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC.md`
  4. Реализованный **Task 9D-3A** (модели/миграция/seed/нумерация)
  5. Реализованный **Task 9D-3B** (`DefectService` / `DefectRepository` / `defect_validation`)

> Spec **не меняет** архитектуру, доменную модель, жизненный цикл, миграции и правила
> supersede. Он только фиксирует HTTP-слой поверх готового `DefectService`.

---

## 2. Purpose

Добавить HTTP-слой для технической модели Defect как тонкую оболочку над готовым
доменным сервисом 9D-3B. Поток запроса:

```
HTTP request
   ↓
Pydantic schemas (валидация входа, extra="forbid")
   ↓
DefectService (RBAC, инварианты, lifecycle, supersede, version — уже реализовано в 9D-3B)
   ↓
DefectRepository (persistence/query)
   ↓
PostgreSQL
```

Никакой доменной логики в API-слое не появляется: 9D-3C только транспортирует
команды/запросы к сервису и сериализует результат.

---

## 3. Scope

В Task 9D-3C входит:

- **Pydantic v2 схемы** Defect (`app/quality/defect_schemas.py`);
- **Defect API router** (`app/quality/defect_api.py`), подключение в `app/main.py`;
- **Reference read API** (read-only справочники типов и расположений дефектов);
- **HTTP error contract** поверх существующего `DomainError`;
- **RBAC integration** — передача `actor_worker_id` сервису (проверка прав — в сервисе);
- **API-тесты** (`tests/test_defect_api.py`, `tests/test_defect_rbac_matrix.py`,
  `tests/test_defect_reference_api.py`).

Для reference-эндпоинтов дополнительно требуются минимальные read-примитивы
(см. §10): методы `list_*` в `DefectRepository` и read-метод(ы) сервиса —
**только чтение активных справочников**, без доменной логики.

---

## 4. Explicit Exclusions

В Task 9D-3C **не входят** (и не вводятся ни схемами, ни маршрутами, ни тестами):

- `Repair` (ремонт);
- `Reweld` (переварка);
- `Reinspection` (повторный контроль);
- `FindingDisposition`;
- `DefectAcceptanceAssessment` (оценка приёмлемости);
- `Files` (файлы/вложения);
- `Reports` (отчёты);
- `Import` (импорт).

Эти сущности отсутствуют в доменной модели Defect (подтверждено `defect_workflow.py`:
ровно шесть типов событий; `FindingDisposition` в 9D-3B не используется). API их не
создаёт и на них не ссылается.

---

## 5. Architecture Boundary

### API-слой ОТВЕЧАЕТ за:

- **routing** — определение маршрутов и HTTP-методов;
- **validation** — Pydantic-валидация входа (`extra="forbid"`, типы, обязательность);
- **serialization** — ORM → response-модель (`from_attributes=True`);
- **dependency injection** — `Depends(get_db)`, сборка `DefectService`;
- **actor extraction** — `actor_worker_id` из заголовка `X-User-Id`.

### API-слой НЕ выполняет:

- CONFIRMED_DEFECT validation (проверка effective `CONFIRMED_DEFECT`-оценки);
- Joint invariant (совпадение Joint оценки и запрошенного `joint_id`);
- lifecycle transitions (DRAFT→ACTIVE→SUPERSEDED/CANCELLED);
- supersede logic (двухшаговый supersede-time);
- version checks (optimistic locking по `expected_version`);
- RBAC decisions (проверка ролей/scope, visibility → 404).

Всё перечисленное уже реализовано в `DefectService` (9D-3B) и повторно в API не
дублируется.

---

## 6. Schema Contract

Файл: `app/quality/defect_schemas.py`. Pydantic **v2**, канон Tasks 9A–9D-2
(`quality_finding_schemas.py`): вход — `ConfigDict(extra="forbid")`; выход —
`ConfigDict(from_attributes=True)`; enum — `Literal`-типы из `defect_workflow`
(`DefectStatus`, `DefectIndicationLocation`); UUID/`datetime`/`Decimal` — нативная
сериализация Pydantic v2; актор — из `X-User-Id`, не из тела.

### 6.1 `DefectFieldsInput` — технические поля ревизии

Общий блок технических характеристик §5 (используется при create и как patch при
update/supersede). Поля соответствуют `dw.DEFECT_TECHNICAL_FIELDS`, все опциональны
(nullable в DRAFT; обязательность на активацию проверяет сервис):

```python
class DefectFieldsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defect_type_id: UUID | None = None
    location_type_id: UUID | None = None
    indication_location: DefectIndicationLocation | None = None
    orientation: str | None = None
    surface: str | None = None
    joint_side: str | None = None
    axial_position_mm: Decimal | None = None
    circumferential_position_deg: Decimal | None = None
    length_mm: Decimal | None = None
    width_mm: Decimal | None = None
    height_mm: Decimal | None = None
    depth_mm: Decimal | None = None
    affected_area_mm2: Decimal | None = None
    quantity: int | None = None
    standard_document: str | None = None
    standard_revision: str | None = None
    standard_clause: str | None = None
    acceptance_level: str | None = None
    normative_category_code: str | None = None
    technical_description: str | None = None
    location_description: str | None = None
    evaluation_note: str | None = None
    technical_note: str | None = None
```

В сервис передаётся `fields = model_dump(exclude_unset=True)` — только реально
переданные ключи (различие «не передано» vs «передано null» сохраняется). Нормализация
значений (trim → NULL, нормализация градусов) выполняется в 9D-3B, а не в схеме.

**Авторитетный набор** совпадает с `dw.DEFECT_TECHNICAL_FIELDS` (9D-3A/9D-3B) и
`TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC.md` §4.6 — 23 поля (перечень задачи 9D-3C
использует «включая» и не перечисляет `acceptance_level`/`normative_category_code`,
которые к техническим полям относятся; они включены). `_apply_fields` в сервисе
фильтрует вход по этому же множеству, поэтому расхождение между схемой и сервисом
невозможно.

**Внутри `fields` НЕ принимаются** (служебные/контекст/аудит) — любое такое поле
отклоняется `extra="forbid"` → 422: `id`, `defect_root_id`, `joint_id`,
`engineering_evaluation_id`, `defect_no`, `revision_no`, `status`, `version`,
`supersedes_defect_id`, actor-поля (`created_by_worker_id`, `updated_by_worker_id`,
`activated_by_worker_id`, `superseded_by_worker_id`, `cancelled_by_worker_id`),
timestamp-поля (`created_at`, `updated_at`, `activated_at`, `superseded_at`,
`cancelled_at`) и `cancellation_reason`. `joint_id` и `engineering_evaluation_id`
задаются только в `DefectCreateRequest` как контекст (§6.2), но не как технические
`fields`.

Правила применения набора:

- **create** принимает полный или неполный набор в зависимости от `activate`
  (`activate=false` — черновик, поля опциональны; `activate=true` — сервис требует
  §8-комплектность);
- **update** и **supersede** используют тот же partial-набор (все поля опциональны —
  patch);
- `extra="forbid"` применяется ко **всем** request-схемам;
- доменная обязательность для ACTIVE остаётся в `DefectService` (схема её не дублирует).

### 6.2 `DefectCreateRequest` — создание

```python
class DefectCreateRequest(DefectFieldsInput):
    model_config = ConfigDict(extra="forbid")

    joint_id: UUID
    engineering_evaluation_id: UUID
    activate: bool = False
```

`activate` управляет выбором конструктора сервиса (см. §8). Технические поля
наследуются от `DefectFieldsInput`; контекст (`joint_id`, `engineering_evaluation_id`)
добавляется явно. `expected_version` при создании отсутствует.

### 6.3 Lifecycle command schemas

```python
class DefectUpdateRequest(DefectFieldsInput):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    reason: str | None = None

class DefectActivateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int

class DefectSupersedeCommand(DefectFieldsInput):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    reason: str | None = None

class DefectCancelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    reason: str
    # field_validator: reason не пустой (сервис дублирует проверку → 422)
```

- `DefectUpdateRequest` — patch технических полей DRAFT + `expected_version` (+ опц. `reason`);
- `DefectSupersedeCommand` — patch поверх снимка предыдущей ACTIVE + `expected_version`;
- `DefectActivateCommand` / `DefectCancelCommand` — только команда, без технических полей.

### 6.4 `DefectRead` — выход

`ConfigDict(from_attributes=True)`; полный набор колонок ревизии `Defect` (§5 модели):

```python
class DefectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    defect_root_id: UUID
    revision_no: int
    supersedes_defect_id: UUID | None
    status: DefectStatus

    # классификация
    defect_type_id: UUID | None
    location_type_id: UUID | None
    indication_location: DefectIndicationLocation | None

    # ориентация / поверхность / сторона
    orientation: str | None
    surface: str | None
    joint_side: str | None

    # положение
    axial_position_mm: Decimal | None
    circumferential_position_deg: Decimal | None

    # измерения
    length_mm: Decimal | None
    width_mm: Decimal | None
    height_mm: Decimal | None
    depth_mm: Decimal | None
    affected_area_mm2: Decimal | None
    quantity: int | None

    # нормативная ссылка
    standard_document: str | None
    standard_revision: str | None
    standard_clause: str | None
    # производное read-поле (parent §10): «{document} {revision}, {clause}» с пропуском
    # пустых частей. НЕ персистится и НЕ входит в fields; вычисляется в схеме
    # (Pydantic @computed_field / model_validator) из трёх раздельных полей.
    standard_reference_display: str | None
    acceptance_level: str | None
    normative_category_code: str | None

    # пояснительный текст
    technical_description: str | None
    location_description: str | None
    evaluation_note: str | None
    technical_note: str | None

    # lifecycle actor/time
    activated_by_worker_id: int | None
    activated_at: datetime | None
    superseded_by_worker_id: int | None
    superseded_at: datetime | None
    cancelled_by_worker_id: int | None
    cancelled_at: datetime | None
    cancellation_reason: str | None

    # аудит и optimistic locking
    created_by_worker_id: int
    created_at: datetime
    updated_by_worker_id: int
    updated_at: datetime
    version: int
```

Поле `defect_no` принадлежит `DefectRoot`, а не ревизии. В `DefectRead` оно не
включается (ревизия его не несёт); при необходимости номер отдаётся отдельной
root-ориентированной схемой в будущих задачах — в 9D-3C не вводится.

### 6.5 `DefectEventRead` — событие истории

```python
class DefectEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    defect_root_id: UUID
    defect_id: UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_worker_id: int
    actor_role: str | None
    reason: str | None
    # колонка модели — event_metadata; в ответе ключ metadata
    metadata: dict | None = Field(default=None, validation_alias="event_metadata")
    correlation_id: UUID | None
    defect_version: int | None
    created_at: datetime
```

### 6.6 Reference schemas (read-only)

```python
class DefectTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    description: str | None
    category: str | None
    is_active: bool
    requires_length: bool
    requires_width: bool
    requires_height: bool
    requires_depth: bool
    requires_area: bool
    requires_quantity: bool

class DefectLocationTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
```

Список отдаётся как `list[DefectTypeRead]` / `list[DefectLocationTypeRead]` (справочники
малы, пагинация не вводится).

---

## 7. API Contract

Router — `APIRouter(tags=["defects"])` без собственного prefix; монтируется в
`app/main.py` через `app.include_router(defect_router, prefix="/api/v1")` (канон
проекта). Namespace `/quality/defects` пишется в путь. Актор — `Depends(get_current_user_id)`.

| Метод | Путь | Схема входа | Response | Код | Сервис |
|---|---|---|---|---|---|
| POST | `/api/v1/quality/defects` | `DefectCreateRequest` | `DefectRead` | 201 | `create_draft` / `create_active` |
| GET | `/api/v1/quality/defects/{defect_id}` | — | `DefectRead` | 200 | `get` |
| GET | `/api/v1/quality/defects?joint_id={uuid}` | query | `list[DefectRead]` | 200 | `list_by_joint` |
| PATCH | `/api/v1/quality/defects/{defect_id}` | `DefectUpdateRequest` | `DefectRead` | 200 | `update_draft` |
| POST | `/api/v1/quality/defects/{defect_id}/activate` | `DefectActivateCommand` | `DefectRead` | 200 | `activate` |
| POST | `/api/v1/quality/defects/{defect_id}/supersede` | `DefectSupersedeCommand` | `DefectRead` | 200 | `supersede` |
| POST | `/api/v1/quality/defects/{defect_id}/cancel` | `DefectCancelCommand` | `DefectRead` | 200 | `cancel` |
| GET | `/api/v1/quality/defects/{defect_id}/history` | — | `list[DefectEventRead]` | 200 | `history` |

Семантические примечания (соответствуют контракту 9D-3B):

- **`GET /quality/defects` — семантика списка (закреплено):**
  - `joint_id` — **обязательный** query-параметр; при отсутствии → **422** (FastAPI,
    обязательный `Query(...)`);
  - возвращаются **только текущие `ACTIVE`-ревизии** по стыку;
  - response model — **`list[DefectRead]`**;
  - **пагинация отсутствует** (ни `limit`/`offset`, ни курсор);
  - **фильтра статусов нет** (query-параметра `status` не существует);
  - `DRAFT`, `SUPERSEDED`, `CANCELLED` **не возвращаются** ни при каких условиях;
  - используется существующий `DefectService.list_by_joint(joint_id, actor_worker_id)`
    **без расширения его семантики** (метод уже фильтрует `status == ACTIVE` и
    сортирует по `DefectRoot.defect_no`);
  - visibility: скрытый по scope Joint → **404** (сервис, `_require_visible`), список
    не раскрывается.
- `PATCH` правит только DRAFT (сервис запрещает правку ACTIVE → `DEFECT_ACTIVE_IMMUTABLE`).
- `/history` возвращает события **всей цепочки** (по `defect_root_id`), а не одной ревизии.
- Правка/удаление событий истории API не предоставляет (append-only).

---

## 8. Create Semantics

Единый эндпоинт создания:

```
POST /api/v1/quality/defects
```

с флагом в теле:

```json
{ "activate": false }
```

Правило маршрутизации в роутере:

```
activate == false  →  DefectService.create_draft(...)
activate == true   →  DefectService.create_active(...)
```

Оба вызова получают `joint_id`, `engineering_evaluation_id`, `actor_worker_id` и
`fields` (из `model_dump(exclude_unset=True)`). Проверка происхождения
(effective `CONFIRMED_DEFECT`-оценка, совпадение Joint, уникальность цепочки на оценку)
и — при `activate=true` — полная §8-комплектность выполняются сервисом. При успешном
создании возвращается `201` + `DefectRead`.

---

## 9. Supersede Semantics

Используется **supersede-time model** (ADR-022 Addendum D-3B-S01). Команда `supersede`
в одной атомарной транзакции:

```
предыдущая ACTIVE
      ↓  supersede
   SUPERSEDED
      +
   DRAFT (новая ревизия, revision_no + 1)
```

После `supersede` в цепочке **нет действующей ACTIVE** (0 ACTIVE, 1 открытая DRAFT).
События: `DEFECT_SUPERSEDED` + `DEFECT_REVISION_CREATED`. Новая DRAFT может быть
неполной (проверяются только структурные инварианты).

Активация новой ревизии — **отдельной командой**:

```
POST /api/v1/quality/defects/{new_defect_id}/activate   →  DefectService.activate(...)
```

API эту модель не меняет и не «схлопывает» два шага в один: `/supersede` возвращает
созданную DRAFT-ревизию (`DefectRead` со `status = DRAFT`), `/activate` переводит её в
ACTIVE. Тело `/supersede` может нести patch технических полей поверх снимка предыдущей
ACTIVE (`DefectSupersedeCommand`).

---

## 10. Reference API

Read-only справочники (системные, меняются только миграцией — ADR-022 §5). Приведено к
родительскому `TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC.md`: list **и** detail.

```
GET /api/v1/quality/defect-types                                → list[DefectTypeRead]
GET /api/v1/quality/defect-types/{defect_type_id}               → DefectTypeRead
GET /api/v1/quality/defect-location-types                       → list[DefectLocationTypeRead]
GET /api/v1/quality/defect-location-types/{defect_location_type_id} → DefectLocationTypeRead
```

### 10.1 List endpoints

Query-параметр:

```python
active_only: bool = True
```

Правила:

- по умолчанию (`active_only=true`) список содержит **только `is_active=true`**;
- `active_only=false` возвращает **активные и неактивные** записи;
- сортировка **стабильная по `code`** (`ORDER BY code`);
- **пагинация не добавляется** (справочники малы).

### 10.2 Detail endpoints

- возвращают существующую запись **независимо от `is_active`** (detail не применяет
  фильтр активности — как активную, так и неактивную запись отдаёт по id);
- отсутствующая запись → **404** (`NotFoundError`/`DomainError(404)`).

### 10.3 Запреты

- **CRUD и mutation-эндпоинты запрещены**: `POST`, `PUT`, `PATCH`, `DELETE` на
  reference-путях не объявляются (обращение → 405, маршрут отсутствует).

### 10.4 Минимальное расширение repository/service (net-new, без доменной логики)

Repository (`DefectRepository`) — сейчас есть только `get_defect_type(id)` /
`get_defect_location_type(id)`; добавляются:

```python
list_defect_types(active_only: bool) -> list[DefectType]
get_defect_type_for_read(defect_type_id: UUID) -> DefectType | None

list_defect_location_types(active_only: bool) -> list[DefectLocationType]
get_defect_location_type_for_read(location_type_id: UUID) -> DefectLocationType | None
```

Service — тонкий read-метод (в `DefectService` либо отдельный `DefectReferenceService`),
делегирующий репозиторию и отдающий записи как есть.

> **Важно (граница чтения):** публичный read-метод **не применяет** правило «reference
> must be active», используемое при create/activate Defect (`DEFECT_TYPE_INACTIVE`/
> `DEFECT_LOCATION_TYPE_INACTIVE` в `_resolve_refs`/валидации 9D-3B). Проверка активности
> справочника остаётся только в доменных командах создания/активации; reference-чтение
> её не наследует и может показать неактивные записи (list при `active_only=false`,
> detail — всегда).

---

## 11. RBAC

Используются **существующие** роли (`defect_workflow.py`); новые не создаются.

- **Write** (create/update/activate/supersede/cancel):
  `DEFECT_WRITE_ROLES = { OGS_ENGINEER, CHIEF_WELDER }`.
  Изменяющие действия исключают COMPANY-scope (`include_company=False`).
- **Read** (get/list/history/reference):
  `DEFECT_READ_ROLES = INSPECTION_READ_ROLES`.
- **Override**: `DEFECT_OVERRIDE_ROLES = { CHIEF_WELDER }` (используется сервисом там,
  где это предусмотрено 9D-3B).

Механика (в сервисе, не в API):

- проверка роли+scope через `worker_role_codes_for_joint(...)` по иерархии
  `GLOBAL → PROJECT → SITE → LINE → ENGINEERING_DOCUMENT` + `COMPANY`;
- скрытый по scope ресурс → **404** (`DEFECT_NOT_FOUND`), не 403;
- запрещённая мутация → **403** (`RoleDeniedError(DEFECT_PERMISSION_DENIED)`).

Ответственность API: извлечь `actor_worker_id` из `X-User-Id` и передать его в
сервис. Никаких решений по правам в API-слое.

### 11.1 Два класса ресурсов

| Класс ресурса | Модель доступа |
|---|---|
| **Defect resources** (`/quality/defects*`) | **scoped read/write через `DefectService`** — роль + Joint-scope, visibility → 404 |
| **Reference resources** (`/quality/defect-types*`, `/quality/defect-location-types*`) | **authenticated read-only** — любой аутентифицированный `X-User-Id`, без Joint-scope |

### 11.2 Reference RBAC (закреплено)

Справочники не связаны с конкретным Joint, поэтому:

- `X-User-Id` **обязателен** (нет заголовка → 401, `get_current_user_id`);
- reference-эндпоинты доступны **любому аутентифицированному** пользователю;
- **Joint-scoped RBAC к ним не применяется** (нет `joint_id`, нет `worker_role_codes_for_joint`);
- данные — **глобальные system-managed read-only**;
- **доступ к справочникам не даёт доступа к скрытым Defect** — это разные ресурсы;
  чтение `defect-types` не раскрывает ни один `Defect`;
- **новые роли не создаются**.

---

## 12. Error Contract

Используется существующий `DomainError` и подклассы (`app/shared/errors.py`). Они —
наследники `HTTPException` и несут `status_code` + `detail = {code, message, ...}`.
В `app/main.py` exception_handler'ов нет, поэтому **API-слой ошибки не мапит**:
сервис бросает типизированную ошибку — FastAPI сериализует её автоматически. Pydantic-
ошибки входа дают `422` штатно.

| Случай | Пример кода домена | HTTP |
|---|---|---|
| not found / скрыт по scope | `DEFECT_NOT_FOUND`, `DEFECT_ROOT_NOT_FOUND` | **404** |
| permission denied | `DEFECT_PERMISSION_DENIED` (`RoleDeniedError`) | **403** |
| validation | `DEFECT_*_REQUIRED`, `DEFECT_EVALUATION_NOT_CONFIRMED`, Pydantic | **422** |
| version conflict | `DEFECT_VERSION_CONFLICT` (`VersionConflictError`) | **409** |
| invalid state / transition | `DEFECT_INVALID_TRANSITION`, `DEFECT_SUPERSEDE_REQUIRES_ACTIVE`, `DEFECT_CHAIN_HAS_OPEN_DRAFT`, `DEFECT_ACTIVE_IMMUTABLE` | **409** |
| duplicate / conflict | `DEFECT_ALREADY_EXISTS_FOR_EVALUATION` | **409** |

> Проект использует **422** для валидации (и Pydantic, и доменной) — не 400. API-слой
> следует этому канону.

Формат тела ошибки: `{ "detail": { "code": "<UPPERCASE>", "message": "<text>", ... } }`
(для version conflict дополнительно `expected_version`/`current_version`).

---

## 13. Tests Plan

Файлы: `tests/test_defect_api.py`, `tests/test_defect_rbac_matrix.py`,
`tests/test_defect_reference_api.py`. Переиспользовать фикстуры `tests/_defect_support.py`.
Транспорт через FastAPI `TestClient`, актор — заголовком `X-User-Id`.

### API (`test_defect_api.py`)

- **create**: `activate=false` → 201 + `status=DRAFT`; `activate=true` → 201 +
  `status=ACTIVE`; `extra="forbid"` (лишнее поле → 422); отсутствие `X-User-Id` → 401;
  дубль цепочки на одну оценку → 409; оценка не `CONFIRMED_DEFECT`/не effective → 422;
  Joint mismatch → 422.
- **read**: существующий → 200 + корректная сериализация (UUID/Decimal/datetime);
  несуществующий → 404.
- **list** (`GET /quality/defects?joint_id=`):
  - без `joint_id` → **422** (обязательный query);
  - возвращается **ACTIVE**-ревизия по стыку;
  - **DRAFT не возвращается** (создан черновик — в списке его нет);
  - **SUPERSEDED не возвращается** (после supersede предыдущая ревизия скрыта из списка);
  - **CANCELLED не возвращается**;
  - **скрытый Joint не раскрывается** — актор без read-доступа к стыку → 404, а не
    пустой список и не 200;
  - пустой список для стыка без ACTIVE-дефектов;
  - response — `list[DefectRead]` (не объект с `items/total`).
- **update (PATCH)**: правка DRAFT → 200 + version+1; правка ACTIVE → 409
  (`DEFECT_ACTIVE_IMMUTABLE`); неверный `expected_version` → 409; лишнее поле → 422.
- **activate**: DRAFT → ACTIVE (200); неполная DRAFT → 422 (`DEFECT_ACTIVATION_*`);
  повторная активация/наличие ACTIVE → 409; version mismatch → 409.
- **supersede**: ACTIVE → возвращается новая DRAFT (`status=DRAFT`), предыдущая
  SUPERSEDED; нет ACTIVE → 409 (`DEFECT_SUPERSEDE_REQUIRES_ACTIVE`); уже есть открытая
  DRAFT → 409 (`DEFECT_CHAIN_HAS_OPEN_DRAFT`); version mismatch → 409; два события в истории.
- **cancel**: DRAFT/ACTIVE → CANCELLED (200); пустой `reason` → 422; из терминального
  статуса → 409; version mismatch → 409.
- **history**: события всей цепочки в порядке `created_at`/`defect_version`; ключ
  ответа `metadata` (alias); read-доступ достаточен.

### RBAC (`test_defect_rbac_matrix.py`)

Матрица по образцу `test_quality_execution_rbac_matrix.py`:

- **allowed**: `OGS_ENGINEER`/`CHIEF_WELDER` в подходящем scope выполняют write-команды;
  `INSPECTION_READ_ROLES` выполняют read.
- **denied**: read-роль на write-команду → 403 (`DEFECT_PERMISSION_DENIED`);
  COMPANY-scope на write → 403 (исключён для мутаций).
- **hidden resource**: актор без read-доступа к стыку → **404** (не 403) на
  get/list/history существующего дефекта.

### Reference (`test_defect_reference_api.py`)

- **auth — без `X-User-Id`** → **401** (list и detail);
- **auth — валидный actor** → **200** (любая аутентифицированная роль, без Joint-scope);
- **active records / active_only=true (default)**: list возвращает только `is_active=true`,
  стабильно отсортировано по `code`;
- **inactive скрыт при `active_only=true`**: неактивная запись отсутствует в списке
  по умолчанию;
- **inactive виден при `active_only=false`**: list возвращает активные и неактивные;
- **inactive доступен по detail**: `GET …/{id}` неактивной записи → 200 (detail
  игнорирует `is_active`);
- **detail 404**: несуществующий id → 404;
- **no mutation**: `POST`/`PUT`/`PATCH`/`DELETE` на reference-путях отсутствуют → 405;
- **изоляция**: чтение справочника не раскрывает ни один скрытый `Defect`
  (reference-доступ ≠ Defect-доступ).

Для обоих справочников (`defect-types`, `defect-location-types`) — одинаковый набор.

---

## 14. Definition of Done

- [ ] `app/quality/defect_schemas.py` — все схемы §6 готовы (Pydantic v2, `extra="forbid"`);
- [ ] `app/quality/defect_api.py` — все эндпоинты §7 работают через `DefectService`;
- [ ] `app/main.py` — `defect_router` подключён под `/api/v1`;
- [ ] reference API (§10) работает read-only (list + detail для обоих справочников);
      добавлены `list_*(active_only)` и `get_*_for_read(id)` в репозитории; публичное
      чтение не применяет правило «reference must be active»;
- [ ] RBAC-регрессия зелёная (allowed/denied/hidden, §13); прав в API-слое не решается;
- [ ] `pytest` зелёный (новые + существующие quality-тесты);
- [ ] **один Alembic head** (`20260720_21_defect_model`) — миграции не добавляются;
- [ ] нет дублирующего кода/документов; линтер чист.

---

## 15. Consistency Check

Сверка с источниками истины; противоречий не выявлено.

| Аспект | Источник | Статус |
|---|---|---|
| supersede-time (2 шага, отдельный `activate`) | ADR-022 Addendum **D-3B-S01**; `defect_services.supersede` | ✅ §9 совпадает |
| list semantics (только ACTIVE, обяз. `joint_id`, без пагинации/фильтра) | `DefectService.list_by_joint` (фильтр `status==ACTIVE`) | ✅ §7 без расширения сервиса |
| reference list/detail, `active_only` | parent `TASK_9D-3…SPEC` §10 | ✅ §10, detail игнорирует `is_active` |
| публичное reference-чтение ≠ доменная проверка активности | 9D-3B `_resolve_refs` (`DEFECT_*_INACTIVE`) | ✅ §10.4 явно разделено |
| validation HTTP **422** (Pydantic + доменная) | `app/shared/errors.py`; канон 9A–9D-2 | ✅ §12 (не 400) |
| RBAC роли (`OGS_ENGINEER`/`CHIEF_WELDER`/`INSPECTION_READ_ROLES`), новых нет | `defect_workflow.py` | ✅ §11; reference — authenticated-only |
| поля Defect = `dw.DEFECT_TECHNICAL_FIELDS` (23) | 9D-3A модель; parent §4.6 | ✅ §6.1 (вкл. `acceptance_level`/`normative_category_code`) |
| производное `standard_reference_display` в read-схеме | parent §10 | ✅ добавлено в `DefectRead` (§6.4) |
| один Alembic head, миграций не добавляется | 9D-3A `20260720_21_defect_model` | ✅ §14 |

Замечание (не конфликт): `standard_reference_display` — вычисляемое поле read-схемы,
которого нет как атрибута ORM-модели `Defect`; реализуется в Pydantic-схеме
(`@computed_field`/`model_validator`) из трёх раздельных `standard_*`. Это read-only
транспортная сборка, доменную модель не меняет (правило 8 parent-spec).

---

## Appendix A — Соответствие эндпоинтов сервису 9D-3B (карта)

| Endpoint | `DefectService` метод | kwargs |
|---|---|---|
| `POST /defects` (`activate=false`) | `create_draft` | `joint_id, engineering_evaluation_id, actor_worker_id, fields` |
| `POST /defects` (`activate=true`) | `create_active` | `joint_id, engineering_evaluation_id, actor_worker_id, fields` |
| `GET /defects/{id}` | `get` | `defect_id, actor_worker_id` |
| `GET /defects?joint_id=` | `list_by_joint` | `joint_id, actor_worker_id` |
| `PATCH /defects/{id}` | `update_draft` | `defect_id, expected_version, actor_worker_id, fields, reason` |
| `POST /defects/{id}/activate` | `activate` | `defect_id, expected_version, actor_worker_id` |
| `POST /defects/{id}/supersede` | `supersede` | `defect_id, expected_version, actor_worker_id, fields, reason` |
| `POST /defects/{id}/cancel` | `cancel` | `defect_id, expected_version, actor_worker_id, reason` |
| `GET /defects/{id}/history` | `history` | `defect_id, actor_worker_id` |
| `GET /defect-types` | `list_defect_types` (net-new read) | `active_only=True` |
| `GET /defect-types/{id}` | `get_defect_type_for_read` (net-new read) | по id, `is_active` игнор. |
| `GET /defect-location-types` | `list_defect_location_types` (net-new read) | `active_only=True` |
| `GET /defect-location-types/{id}` | `get_defect_location_type_for_read` (net-new read) | по id, `is_active` игнор. |
