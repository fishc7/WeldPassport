# Engineering Joints MVP — Implementation Plan

> Для исполнителя: реализация выполняется строго по задачам плана. Каждый этап начинается с теста, заканчивается проверкой и отдельным commit. Следующий этап не начинается до архитектурного ревью предыдущего.

**Цель:** реализовать первый вертикальный контур Project → Line → EngineeringDocument → DocumentRevision → Joint без WeldOperation, Inspection, RepairOperation и HeatTreatmentOperation.

**Архитектура:** схемы `project` и `engineering`; UUID для проектных и инженерных сущностей, Integer для Company; FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL + Pydantic v2 + pytest.

**Ветка:** `feature/engineering-joints-mvp` (база `6f1bc85`).

**Канон:** [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 004|Architecture Session 004]] · [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API|ADR-009]].

**Исполнение:**

- **ChatGPT** — архитектурный контроль и review checkpoint;
- **Claude Code** — написание кода по утверждённой задаче;
- **Cursor** — рабочая среда, запуск команд, Git, commit/push.

---

## Решения плана (IP-01 — IP-06)

| ID | Решение |
|----|---------|
| **IP-01** | `project.companies.id` — Integer; `project.projects.id`, `project.lines.id`, `engineering.engineering_documents.id`, `engineering.document_revisions.id`, `engineering.joints.id` — UUID; `project_companies` связывает `project_id` (UUID) и `company_id` (Integer) |
| **IP-02** | Минимальный реестр `project.companies` (id, name, inn, status, created_by, created_at); расширенная карточка отложена; `project_companies` с полноценными FK |
| **IP-03** | `X-User-Id` = `hr.workers.id`; не аутентификация; сервисы проверяют активные `hr.worker_roles`; JWT не входит в план |
| **IP-04** | Добавить `MASTER` в `hr.worker_roles` (CHECK, Pydantic, тесты); `HEAT_TREATMENT_OPERATOR` не добавлять |
| **IP-05** | Scope: `GLOBAL`, `PROJECT`, `LINE`; `scope_id` — UUID проекта/линии в **строковом** виде; `FOREMAN`/`MASTER` создают DRAFT Joint; `PTO` подтверждает, отменяет и заменяет Joint; `PTO` утверждает EngineeringDocument и DocumentRevision; `PTO` привязывает Joint к новой ревизии |
| **IP-06** | Ветка `feature/engineering-joints-mvp`, создана от `6f1bc85` |

---

## Глобальные ограничения

- **`09_Разработка/backend/app/`** — канонический слой реализации.
- **`09_Разработка/src/`** и **`app/workforce/`** — не развивать.
- Не изменять существующую семантику модулей **`hr`** и **`welding`** (кроме явно описанных в Task 1 правок ролей).
- Не реализовывать полноценную аутентификацию (JWT, OAuth, сессии).
- Не реализовывать **WeldOperation**, **Inspection**, **RepairOperation**, **HeatTreatmentOperation**.
- Не реализовывать Excel-импорт.
- Не удалять физически подтверждённые сущности (документы, Joint).
- **`ready_for_welding`** — вычисляемое поле API (не колонка БД).
- **`production_state`** в плане №1 возвращает только допустимое начальное значение (например `NOT_STARTED`); без имитации сварки и контроля.
- Все новые миграции — **одна линейная цепочка** от head `20260703_03_welder_admissions`.
- Существующие тесты `hr` / `ogs` должны оставаться зелёными после каждого Task.
- Не добавлять FK к несуществующим таблицам WPS и МТО.
- Не добавлять FK `hr.workers.company_id` → `project.companies` в этом плане.

---

## Цепочка миграций (линейная)

```text
20260703_03_welder_admissions  (текущий head)
  → 20260710_01_hr_master_role
  → 20260710_02_project_core
  → 20260710_03_project_lines
  → 20260710_04_engineering_documents
  → 20260710_05_engineering_joints
  → 20260710_06_joint_lifecycle
```

---

## Task 1 — MASTER и scoped role check

### Цель

Подготовить минимальную проверку ролей для последующих API: добавить роль `MASTER`, сохранить все существующие `role_code` без изменений, scope `GLOBAL` / `PROJECT` / `LINE`, валидация `scope_id` как UUID-строки. Канонический `role_code` ПТО в плане — `PTO`.

### Файлы

**Modify:**

- `09_Разработка/backend/app/hr/models.py`
- `09_Разработка/backend/app/hr/schemas.py`
- `09_Разработка/backend/app/hr/repository.py`
- `09_Разработка/backend/tests/test_hr_worker_roles_schemas.py`
- `09_Разработка/backend/tests/conftest.py` — только при необходимости fixture worker с ролью

**Create:**

- `09_Разработка/backend/app/shared/permissions.py`
- `09_Разработка/backend/migrations/versions/20260710_01_hr_master_role.py`
- `09_Разработка/backend/tests/test_role_permissions.py`

### Interfaces

| Вход | Выход |
|------|-------|
| `hr.workers`, `hr.worker_roles` (существующие) | `permissions.require_role()`, `permissions.has_role()` |
| `X-User-Id` → `worker_id` | Проверка `role_code` + `scope_type` + `scope_id` + `valid_from`/`valid_to` + `is_active` |
| — | Миграция `20260710_01_hr_master_role.py`: пересоздать/расширить CHECK `ck_hr_worker_roles_role_code`, **добавив** `MASTER`; все существующие допустимые `role_code` сохраняются |
| — | Pydantic `WorkerRoleCode`: добавлен `MASTER`; существующие значения, включая `PTO`, без изменений |

**Ключевые имена:**

- `permissions.RoleRequirement` — dataclass: `role_code`, `scope_type`, `scope_id` (optional UUID str)
- `permissions.check_worker_role(db, worker_id, requirement) -> bool`
- `permissions.require_worker_role(db, worker_id, requirement) -> None` — raises 403
- `HrRepo.find_active_roles(worker_id, role_code, scope_type, scope_id) -> list[WorkerRole]`
- `HrRepo.has_active_worker_role_in_scope(...)` — замена/расширение `has_active_worker_role`

### Шаги

- [ ] **1.1** Написать failing test: `WorkerRoleCreate(role_code="MASTER")` и `role_code="PTO"` проходят валидацию
- [ ] **1.2** Написать failing tests в `test_role_permissions.py` (см. ниже)
- [ ] **1.3** Миграция CHECK (только добавление `MASTER`) + синхронизировать model CHECK
- [ ] **1.4** Обновить `WorkerRoleCode` Literal — добавить `MASTER`
- [ ] **1.5** Реализовать `permissions.py` и методы `HrRepo`
- [ ] **1.6** Прогнать тесты, регрессия HR/OGS
- [ ] **1.7** Commit

### Failing tests (порядок)

| # | Тест | Команда | Ожидаемый FAIL |
|---|------|---------|----------------|
| 1 | `test_worker_role_create_accepts_master_and_pto` | `pytest tests/test_hr_worker_roles_schemas.py::test_worker_role_create_accepts_master_and_pto -q` | `ValidationError` или тест отсутствует |
| 2 | `test_has_role_global_foreman` | `pytest tests/test_role_permissions.py::test_has_role_global_foreman -q` | `ModuleNotFoundError: permissions` или assert False |
| 3 | `test_has_role_project_scope_matches_uuid` | `pytest tests/test_role_permissions.py::test_has_role_project_scope_matches_uuid -q` | роль с другим `scope_id` считается подходящей |
| 4 | `test_has_role_line_scope_matches_uuid` | `pytest tests/test_role_permissions.py::test_has_role_line_scope_matches_uuid -q` | то же для LINE |
| 5 | `test_foreign_project_scope_rejected` | `pytest tests/test_role_permissions.py::test_foreign_project_scope_rejected -q` | чужой project UUID проходит |
| 6 | `test_inactive_role_rejected` | `pytest tests/test_role_permissions.py::test_inactive_role_rejected -q` | `is_active=False` проходит |
| 7 | `test_expired_role_rejected` | `pytest tests/test_role_permissions.py::test_expired_role_rejected -q` | `valid_to < today` проходит |

**Минимальная реализация:** миграция пересоздаёт/расширяет CHECK с добавлением `MASTER` (без изменения существующих `role_code` в данных) + Literal + `permissions.py` с проверкой scope (GLOBAL — `scope_id is None`; PROJECT/LINE — `scope_id` равен переданному UUID в строковом виде).

**Проверка PASS:**

```powershell
cd 09_Разработка/backend
pytest tests/test_hr_worker_roles_schemas.py tests/test_role_permissions.py -q
```

**Регрессия:**

```powershell
pytest tests/test_hr_schemas.py tests/test_ogs_welders.py tests/test_ogs_welder_admissions.py -q
```

**Commit:** `feat(hr): add master role and scoped permission checks`

**Checkpoint:** архитектурное ревью ChatGPT — scope UUID как строка, отсутствие HEAT_TREATMENT_OPERATOR.

---

## Task 2 — Company, Project и project_companies

### Цель

Схема `project`, реестр компаний, проекты, связь многие-ко-многим через `project_companies`, REST API под `/api/v1/projects`.

### Файлы

**Create:**

- `09_Разработка/backend/app/projects/__init__.py`
- `09_Разработка/backend/app/projects/models.py`
- `09_Разработка/backend/app/projects/schemas.py`
- `09_Разработка/backend/app/projects/repository.py`
- `09_Разработка/backend/app/projects/services.py`
- `09_Разработка/backend/app/projects/api.py`
- `09_Разработка/backend/migrations/versions/20260710_02_project_core.py`
- `09_Разработка/backend/tests/test_projects_api.py`

**Modify:**

- `09_Разработка/backend/app/main.py`
- `09_Разработка/backend/app/shared/db.py` — `search_path` + `project`
- `09_Разработка/backend/migrations/env.py` — import models, `PROJECT_MANAGED_TABLES`
- `09_Разработка/backend/tests/conftest.py` — fixtures `company`, `project`, cleanup

### Interfaces

| Вход | Выход |
|------|-------|
| Task 1 `permissions`, `X-User-Id` | Модуль `app.projects` |
| — | Таблицы: `project.companies`, `project.projects`, `project.project_companies` |
| — | Router `prefix="/projects"` → `/api/v1/projects/*` |

**Модели (`PROJECT_SCHEMA = "project"`):**

| Таблица | Класс | Ключевые поля / ограничения |
|---------|-------|----------------------------|
| `companies` | `Company` | `id` Integer PK; `name`; `inn` nullable; `status` active/inactive; `created_by` int; `created_at`; UNIQUE partial на `inn` WHERE inn IS NOT NULL |
| `projects` | `Project` | `id` UUID PK; `code`; `name`; `status` draft/active/closed; `created_by`; `created_at`; `updated_at`; UNIQUE `code` |
| `project_companies` | `ProjectCompany` | `id` Integer PK; `project_id` UUID FK; `company_id` Integer FK; `role_code`; `valid_from`; `valid_to` nullable; действующая связь: `valid_to IS NULL`; partial UNIQUE `(project_id, company_id, role_code) WHERE valid_to IS NULL`; CHECK `valid_to IS NULL OR valid_to >= valid_from`; исторические закрытые участия сохраняются |

**`role_code` (CHECK):** `CUSTOMER`, `GENERAL_CONTRACTOR`, `WELDING_CONTRACTOR`, `NDT_LAB`, `INSPECTION`, `DESIGNER`.

**Временное правило MVP (Company / Project):**

- `POST /companies` и `POST /projects` требуют только валидный `X-User-Id` существующего **активного** `hr.workers` (`employment_status = active`);
- отсутствие заголовка → `401` (как сейчас); неизвестный `worker_id` → `404` (паттерн `NotFoundError`);
- **не** назначать эти действия ролям `PTO`, `FOREMAN` или `MASTER` на этом этапе;
- role-based управление Company/Project — отдельное будущее архитектурное решение.

**Сервисы / репозиторий:**

- `ProjectRepo` — CRUD companies, projects, project_companies
- `ProjectService.create_company()`, `list_companies()`, `create_project()`, `list_projects(filters)`, `add_project_company()`, `list_project_companies()`

**API endpoints:**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/projects/companies` | `create_company` |
| GET | `/api/v1/projects/companies` | `list_companies` |
| POST | `/api/v1/projects` | `create_project` |
| GET | `/api/v1/projects` | `list_projects` — фильтры `company_id`, `role_code` |
| GET | `/api/v1/projects/{project_id}` | `get_project` |
| POST | `/api/v1/projects/{project_id}/companies` | `add_project_company` |
| GET | `/api/v1/projects/{project_id}/companies` | `list_project_companies` |

### Шаги

- [ ] **2.1** Failing test: POST company → 201 (активный worker)
- [ ] **2.2** Failing test: неизвестный `X-User-Id` → 404
- [ ] **2.3** Failing test: одна company в двух projects
- [ ] **2.4** Failing test: один project — две companies с разными role_code
- [ ] **2.5** Failing test: дубликат активной `(project_id, company_id, role_code)` при `valid_to IS NULL` → 409
- [ ] **2.6** Failing test: закрытое участие (`valid_to` задан) не блокирует новую активную связь с тем же role_code
- [ ] **2.7** Failing test: `valid_to < valid_from` → 422
- [ ] **2.8** Миграция `20260710_02_project_core.py`
- [ ] **2.9** Models, schemas, repo, service, api
- [ ] **2.10** Подключить router в `main.py`; обновить `db.py`, `env.py`
- [ ] **2.11** PASS + регрессия
- [ ] **2.12** Commit

### Failing test (первый)

```powershell
pytest tests/test_projects_api.py::test_create_company_and_project -q
```

**Ожидаемый FAIL:** `404` на POST `/api/v1/projects/companies` (router отсутствует).

**Проверка PASS:**

```powershell
pytest tests/test_projects_api.py -q
```

**Регрессия:**

```powershell
pytest tests/ -q
```

**Commit:** `feat(projects): add companies projects and participation roles`

**Checkpoint:** ChatGPT — FK types UUID/Integer, отсутствие правила «1 company = 1 project».

---

## Task 3 — Line

### Цель

Сущность `project.lines` с привязкой к Project, API, уникальность `line_no` в проекте.

### Файлы

**Modify:**

- `09_Разработка/backend/app/projects/models.py`
- `09_Разработка/backend/app/projects/schemas.py`
- `09_Разработка/backend/app/projects/repository.py`
- `09_Разработка/backend/app/projects/services.py`
- `09_Разработка/backend/app/projects/api.py`
- `09_Разработка/backend/migrations/env.py`
- `09_Разработка/backend/tests/conftest.py`

**Create:**

- `09_Разработка/backend/migrations/versions/20260710_03_project_lines.py`
- `09_Разработка/backend/tests/test_project_lines_api.py`

### Interfaces

| Вход | Выход |
|------|-------|
| `Project` (Task 2) | `Line` model + API |

**Модель `Line`:**

- `id` UUID PK; `project_id` UUID FK → `projects.id`
- `line_no`, `name`, `medium`, `nominal_dn`, `class_code`, `category_code` — nullable где указано
- `status`: draft / active / cancelled
- `required_inspection_types`: PostgreSQL `ARRAY(Text)`; SQLAlchemy `postgresql.ARRAY(String)`; default `'{}'` (пустой массив, **не** NULL)
- `created_by`, `created_at`, `updated_at`
- UNIQUE `(project_id, line_no)`; CHECK `nominal_dn > 0` IF NOT NULL

**API:**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/projects/{project_id}/lines` | `create_line` |
| GET | `/api/v1/projects/{project_id}/lines` | `list_lines` |
| GET | `/api/v1/projects/lines/{line_id}` | `get_line` |
| PATCH | `/api/v1/projects/lines/{line_id}` | `update_line` — только draft/active редактируемые поля |

### Шаги

- [ ] **3.1** Failing test: POST line без project → 404
- [ ] **3.2** Failing test: duplicate line_no в project → 409
- [ ] **3.3** Failing test: nominal_dn <= 0 → 422
- [ ] **3.4** Миграция + реализация
- [ ] **3.5** PASS + регрессия
- [ ] **3.6** Commit

**Первый failing test:**

```powershell
pytest tests/test_project_lines_api.py::test_create_line_for_project -q
```

**Ожидаемый FAIL:** `404` или таблица `project.lines` не существует.

**Commit:** `feat(projects): add project lines`

**Checkpoint:** ChatGPT — `required_inspection_types` как `ARRAY(Text)` снимок для будущих Joint (ADR-009 004-25).

---

## Task 4 — EngineeringDocument и DocumentRevision

### Цель

Схема `engineering`, документы и ревизии, команды approve/cancel/supersede.

### Файлы

**Create:**

- `09_Разработка/backend/app/engineering/__init__.py`
- `09_Разработка/backend/app/engineering/models.py`
- `09_Разработка/backend/app/engineering/schemas.py`
- `09_Разработка/backend/app/engineering/repository.py`
- `09_Разработка/backend/app/engineering/services.py`
- `09_Разработка/backend/app/engineering/api.py`
- `09_Разработка/backend/migrations/versions/20260710_04_engineering_documents.py`
- `09_Разработка/backend/tests/test_engineering_documents_api.py`

**Modify:**

- `09_Разработка/backend/app/main.py`
- `09_Разработка/backend/app/shared/db.py` — `search_path` + `engineering`
- `09_Разработка/backend/migrations/env.py`
- `09_Разработка/backend/tests/conftest.py`

### Interfaces

| Вход | Выход |
|------|-------|
| `Project`, `Line` (Task 2–3) | `EngineeringDocument`, `DocumentRevision` |

**Модели (`ENGINEERING_SCHEMA = "engineering"`):**

| Таблица | Класс | Ключевое |
|---------|-------|----------|
| `engineering_documents` | `EngineeringDocument` | UUID PK; `project_id` FK; `line_id` FK nullable; `document_no`; `document_type` ISOMETRIC/DRAWING/WELD_MAP/OTHER; `title`; `status` draft/approved/cancelled/superseded; audit |
| `document_revisions` | `DocumentRevision` | UUID PK; `engineering_document_id` FK; `revision_code`; `issued_at`; `status`; audit |

**Ограничения:** UNIQUE `(project_id, document_no)`; UNIQUE `(engineering_document_id, revision_code)`.

**Права (role_code `PTO`, scope GLOBAL / PROJECT / LINE):**

- создать `EngineeringDocument` и `DocumentRevision` — активная роль `PTO` в соответствующем scope;
- `approve` / `cancel` / `supersede` документа и ревизии — `PTO` в scope проекта (или GLOBAL);
- `X-User-Id` = `hr.workers.id`; отсутствие подходящей роли → `403`.

**Сервисы:**

- `EngineeringService.create_document()`, `approve_document()`, `cancel_document()`, `supersede_document()`
- `EngineeringService.create_revision()`, `approve_revision()`, `cancel_revision()`, `supersede_revision()`

**API (`prefix="/engineering"`):**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/engineering/documents` | `create_document` — PTO |
| GET | `/api/v1/engineering/documents` | `list_documents` |
| GET | `/api/v1/engineering/documents/{id}` | `get_document` |
| POST | `/api/v1/engineering/documents/{id}/approve` | `approve_document` — PTO |
| POST | `/api/v1/engineering/documents/{id}/cancel` | `cancel_document` — PTO |
| POST | `/api/v1/engineering/documents/{id}/supersede` | `supersede_document` — PTO |
| POST | `/api/v1/engineering/documents/{id}/revisions` | `create_revision` — PTO |
| GET | `/api/v1/engineering/documents/{id}/revisions` | `list_revisions` |
| POST | `/api/v1/engineering/revisions/{id}/approve` | `approve_revision` — PTO |
| POST | `/api/v1/engineering/revisions/{id}/cancel` | `cancel_revision` — PTO |
| POST | `/api/v1/engineering/revisions/{id}/supersede` | `supersede_revision` — PTO |

### Шаги

- [ ] **4.1** Failing test: PTO PROJECT scope создаёт и утверждает document + revision
- [ ] **4.2** Failing test: PTO чужого PROJECT scope → 403
- [ ] **4.3** Failing test: revision без document → 404/422
- [ ] **4.4** Failing test: duplicate document_no в project → 409
- [ ] **4.5** Failing test: approve переводит status, физического DELETE нет
- [ ] **4.6** Миграция + модуль engineering
- [ ] **4.7** PASS + регрессия
- [ ] **4.8** Commit

**Первый failing test:**

```powershell
pytest tests/test_engineering_documents_api.py::test_pto_creates_and_approves_document -q
```

**Commit:** `feat(engineering): add documents and revisions`

**Checkpoint:** ChatGPT — line_id nullable, согласованность project/line FK.

---

## Task 5 — Joint DRAFT и вычисление ready_for_welding

### Цель

Таблица `engineering.joints`, создание DRAFT, PATCH только для DRAFT, вычисляемые `ready_for_welding` и `missing_welding_requirements`.

### Файлы

**Modify:**

- `09_Разработка/backend/app/engineering/models.py`
- `09_Разработка/backend/app/engineering/schemas.py`
- `09_Разработка/backend/app/engineering/repository.py`
- `09_Разработка/backend/app/engineering/services.py`
- `09_Разработка/backend/app/engineering/api.py`
- `09_Разработка/backend/migrations/env.py`
- `09_Разработка/backend/tests/conftest.py`

**Create:**

- `09_Разработка/backend/migrations/versions/20260710_05_engineering_joints.py`
- `09_Разработка/backend/tests/test_engineering_joints_api.py`

### Interfaces

| Вход | Выход |
|------|-------|
| Project, Line, EngineeringDocument, DocumentRevision | `Joint` DRAFT |
| Task 1 permissions | 403 без FOREMAN/MASTER в scope |
| Line.required_inspection_types | копия в Joint при создании |

**Модель `Joint`** — поля по Session 004 раздел 2:

`id`, `project_id`, `line_id`, `engineering_document_id`, `current_revision_id`, `joint_no`, `engineering_status`, `superseded_by_joint_id`, `geometry_type`, `weld_type`, `standard_joint_code`, `dn`, `thickness`, `material_1_catalog_id`, `material_1_name`, `material_2_catalog_id`, `material_2_name`, `planned_wps_id`, `required_inspection_types`, `heat_treatment_required`, audit fields.

**Допустимые значения и CHECK:**

| Поле | Значения |
|------|----------|
| `geometry_type` | `BUTT`, `TEE`, `CORNER`, `LAP` |
| `weld_type` | `BW`, `FW` |
| `engineering_status` | `DRAFT`, `CONFIRMED`, `CANCELLED`, `SUPERSEDED` |

**Без FK (nullable UUID, будущие домены МТО/WPS):**

- `material_1_catalog_id` — nullable UUID без FK;
- `material_2_catalog_id` — nullable UUID без FK;
- `planned_wps_id` — nullable UUID без FK.

Причина: будущие сущности МТО и WPS предполагаются самостоятельными доменными объектами с UUID; FK в плане №1 **не создаётся**.

**`required_inspection_types`:** PostgreSQL `ARRAY(Text)`; SQLAlchemy `postgresql.ARRAY(String)`; default `'{}'`; при создании копируется с Line; пустой перечень — пустой массив, не NULL.

**Ограничения:**

- UNIQUE `(project_id, engineering_document_id, joint_no)`;
- CHECK наборов `geometry_type`, `weld_type`, `engineering_status`;
- CHECK `dn > 0` IF `dn IS NOT NULL`;
- CHECK `thickness > 0` IF `thickness IS NOT NULL`;
- CHECK `superseded_by_joint_id IS NULL OR superseded_by_joint_id <> id`;
- все FK в одном project.

**Вычисление (`JointRead` computed):**

- `ready_for_welding`: true если заполнены `geometry_type`, `weld_type`, `dn`, `thickness`, `material_1_name`, `material_2_name`
- `missing_welding_requirements`: список недостающих полей
- `production_state`: константа `NOT_STARTED` для плана №1

**API:**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/engineering/joints` | `create_joint` — FOREMAN/MASTER |
| GET | `/api/v1/engineering/joints` | `list_joints` — фильтры |
| GET | `/api/v1/engineering/joints/{id}` | `get_joint` |
| PATCH | `/api/v1/engineering/joints/{id}` | `update_joint` — только DRAFT |

### Шаги

- [ ] **5.1** Failing test: FOREMAN GLOBAL создаёт DRAFT
- [ ] **5.2** Failing test: без роли → 403
- [ ] **5.3** Failing test: cross-project line → 422
- [ ] **5.4** Failing test: duplicate joint_no → 409
- [ ] **5.5** Failing test: ready_for_welding false/true
- [ ] **5.6** Миграция + сервис `compute_joint_readiness()`
- [ ] **5.7** PASS + регрессия
- [ ] **5.8** Commit

**Первый failing test:**

```powershell
pytest tests/test_engineering_joints_api.py::test_foreman_creates_draft_joint -q
```

**Commit:** `feat(engineering): add draft joints and readiness checks`

**Checkpoint:** ChatGPT — нет FK WPS/МТО, production_state = NOT_STARTED only.

---

## Task 6 — Joint lifecycle и история ревизий

### Цель

Команды confirm/cancel/supersede/link, техническая таблица `joint_revision_links`, GET lifecycle.

### Файлы

**Create:**

- `09_Разработка/backend/migrations/versions/20260710_06_joint_lifecycle.py`
- `09_Разработка/backend/tests/test_engineering_joint_lifecycle.py`

**Modify:**

- `09_Разработка/backend/app/engineering/models.py` — `JointRevisionLink`
- `09_Разработка/backend/app/engineering/schemas.py` — `JointLifecycleOut`
- `09_Разработка/backend/app/engineering/repository.py`
- `09_Разработка/backend/app/engineering/services.py` — `confirm_joint()`, `cancel_joint()`, `supersede_joint()`, `link_joint_revision()`
- `09_Разработка/backend/app/engineering/api.py`
- `09_Разработка/backend/migrations/env.py`

### Interfaces

| Вход | Выход |
|------|-------|
| Joint DRAFT (Task 5) | CONFIRMED / CANCELLED / SUPERSEDED |
| `PTO` + scope GLOBAL / PROJECT / LINE | confirm, cancel, supersede, link_joint_revision |
| approved Document/Revision | precondition для confirm |

**Таблица `engineering.joint_revision_links`:**

- `joint_id` UUID FK; `document_revision_id` UUID FK; `linked_at`; `linked_by`
- UNIQUE `(joint_id, document_revision_id)`

**API:**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/engineering/joints/{id}/confirm` | `confirm_joint` — PTO |
| POST | `/api/v1/engineering/joints/{id}/cancel` | `cancel_joint` — PTO + reason |
| POST | `/api/v1/engineering/joints/{id}/supersede` | `supersede_joint` — PTO + new joint payload + reason |
| POST | `/api/v1/engineering/joints/{joint_id}/revisions/{revision_id}/link` | `link_joint_revision` — PTO |
| GET | `/api/v1/engineering/joints/{id}/lifecycle` | `get_joint_lifecycle` |

**Правила `link_joint_revision`:**

- выполняет только `PTO` в GLOBAL / PROJECT / LINE scope;
- Revision принадлежит тому же `EngineeringDocument` и `Project`, что и Joint;
- Joint **сохраняет** прежний UUID;
- создаётся запись `joint_revision_links`;
- `current_revision_id` обновляется на новую Revision;
- повторная идентичная связь → `409`;
- Revision другого документа или проекта → `422`;
- `CANCELLED` или `SUPERSEDED` Joint нельзя переносить на новую Revision.

**Правила confirm / cancel / supersede:**

- confirm: `engineering_status` → CONFIRMED; требует `PTO` и approved doc/revision
- cancel: → CANCELLED; требует `PTO` и reason; CANCELLED/SUPERSEDED не редактируются
- supersede: требует `PTO`; старый → SUPERSEDED + `superseded_by_joint_id`; новый Joint с новым UUID
- запрет циклической цепочки supersede
- неизменившийся Joint сохраняет UUID при новой Revision через `POST .../link` и `joint_revision_links`

### Шаги

- [ ] **6.1** Failing test: PTO confirm DRAFT → CONFIRMED
- [ ] **6.2** Failing test: confirm без approved revision → 422
- [ ] **6.3** Failing test: supersede создаёт новый UUID, старый SUPERSEDED
- [ ] **6.4** Failing test: циклический supersede → 409
- [ ] **6.5** Failing test: неизменившийся Joint связывается с новой Revision через `link_joint_revision`, UUID сохранён
- [ ] **6.6** Failing test: Revision другого EngineeringDocument → 422
- [ ] **6.7** Failing test: повторная связь joint+revision → 409
- [ ] **6.8** Failing test: lifecycle возвращает revision links
- [ ] **6.9** Миграция + реализация
- [ ] **6.10** PASS + регрессия
- [ ] **6.11** Commit

**Первый failing test:**

```powershell
pytest tests/test_engineering_joint_lifecycle.py::test_pto_confirms_joint -q
```

**Commit:** `feat(engineering): add joint lifecycle and revision history`

**Checkpoint:** ChatGPT — соответствие ADR-009 004-05, отсутствие физического DELETE.

---

## Task 7 — интеграция и регрессия

### Цель

E2E вертикальный срез и финальная проверка цепочки миграций и тестов.

### Файлы

**Create:**

- `09_Разработка/backend/tests/test_engineering_joints_e2e.py`

**Modify (только при подтверждённой необходимости):**

- `09_Разработка/backend/app/main.py`
- `09_Разработка/backend/migrations/env.py`
- `09_Разработка/backend/app/shared/db.py`
- `09_Разработка/backend/tests/conftest.py`

### Interfaces

| Вход | Выход |
|------|-------|
| Tasks 1–6 | E2E сценарий без WeldOperation |

**E2E сценарий (`test_full_engineering_vertical_slice`):**

1. Create Company
2. Create Project
3. Add project_companies (WELDING_CONTRACTOR)
4. Create Line с `required_inspection_types`
5. Create EngineeringDocument + DocumentRevision
6. Approve document и revision (`PTO`)
7. FOREMAN/MASTER создаёт DRAFT Joint (копия `required_inspection_types` с Line)
8. PATCH полей → `ready_for_welding=true`
9. PTO confirm → CONFIRMED
10. Новая DocumentRevision на тот же document (approve `PTO`)
11. `POST /joints/{id}/revisions/{revision_id}/link` (`PTO`) — UUID Joint сохранён, `current_revision_id` обновлён
12. Альтернативная ветка: supersede (`PTO`) → новый Joint UUID

### Шаги

- [ ] **7.1** Написать E2E test (failing до полной сборки)
- [ ] **7.2** `alembic heads` — один head `20260710_06_joint_lifecycle`
- [ ] **7.3** `alembic upgrade head`
- [ ] **7.4** `python -m compileall app`
- [ ] **7.5** `pytest tests/test_engineering_joints_e2e.py -q`
- [ ] **7.6** `pytest tests/ -q` — полный набор
- [ ] **7.7** Проверить список маршрутов (OpenAPI `/docs` или `app.routes`)
- [ ] **7.8** Убедиться: нет импортов `src.models`, нет правок `app/workforce`
- [ ] **7.9** Commit

**Команды проверки:**

```powershell
cd 09_Разработка/backend
alembic heads
alembic upgrade head
python -m compileall app
pytest tests/test_engineering_joints_e2e.py -q
pytest tests/ -q
```

**Commit:** `test(engineering): verify engineering joints vertical slice`

**Checkpoint:** ChatGPT — готовность к implementation plan №2 (WeldOperation).

---

## Самопроверка плана

| # | Критерий | Статус |
|---|----------|--------|
| 1 | Session 004 первый контур (Project→Line→Doc→Revision→Joint) | Покрыт Tasks 2–6 |
| 2 | Нет WeldOperation, Inspection, Repair, HT | Да |
| 3 | Нет полноценной auth/JWT | Да — только X-User-Id + role check |
| 4 | Нет Excel-импорта | Да |
| 5 | Нет HEAT_TREATMENT_OPERATOR | Да |
| 6 | Нет FK к WPS/МТО | Да — nullable без FK |
| 7 | PK/FK согласованы (IP-01) | Да — таблица в § IP-01 |
| 8 | Миграции линейны от `20260703_03_welder_admissions` | Да — § цепочка |
| 9 | Один Alembic head после Task 6 | Да |
| 10 | Каждый Task — тест + commit | Да — 7 commits |
| 11 | Нет TBD/TODO в плане | Да |
| 12 | ChatGPT — review; Claude Code — код; Cursor — среда/Git | Да — в шапке |
| 13 | В API плана используется канонический role_code `PTO` | Да |
| 14 | Типы массивов `ARRAY(Text)` и UUID определены однозначно | Да |
| 15 | Новая Revision привязывается через `POST .../link` | Да — Task 6 |
| 16 | Права документов и Joint проверяются по scope | Да — Tasks 4–6 |
| 17 | Company/Project без выдуманного владельца роли | Да — только active Worker |

---

## Связанные документы

- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 004|Session 004]]
- [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API|ADR-009]]
- [[docs/ARCHITECTURE#5.3. Физическая модель БД и API Production/Joints MVP (Session 004)|ARCHITECTURE §5.3]]

*Версия плана: 2026-07-10. Задач: 7. Ветка: feature/engineering-joints-mvp.*
