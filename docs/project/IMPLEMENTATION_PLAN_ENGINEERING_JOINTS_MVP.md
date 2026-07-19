# Engineering Joints MVP — Implementation Plan

> Для исполнителя: реализация выполняется строго по задачам плана. Каждый этап начинается с теста, заканчивается проверкой и отдельным commit. Следующий этап не начинается до архитектурного ревью предыдущего.

**Цель:** реализовать первый вертикальный контур Project → Line → EngineeringDocument → DocumentRevision → Joint без WeldOperation, Inspection, RepairOperation и HeatTreatmentOperation.

**Архитектура:** схемы `project` и `engineering`; UUID для проектных и инженерных сущностей, Integer для Company; FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL + Pydantic v2 + pytest.

**Ветка:** `feature/engineering-joints-mvp` (база `6f1bc85`).

**Канон:** [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 004|Architecture Session 004]] · [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API|ADR-009]] · [[docs/project/DECISIONS#ADR-010. Joint MVP — расширенная модель, двойное согласование, история ревизий и bulk-импорт|ADR-010]] (замещает Joint-часть ADR-009).

> **Обновление 2026-07-11 (ADR-010, принят):** модель Joint пересмотрена. Прежние
> Task 5 (Joint DRAFT) и Task 6 (lifecycle + revision history) заменены разбиением
> **Task 5A → 5B → 6 → 7** (см. ниже). Task 4 (EngineeringDocument,
> DocumentRevision) завершён и не затрагивается. ADR-010 — действующий канон
> реализации Joint для Tasks 5A, 5B, 6 и 7.

**Исполнение:**

- **ChatGPT** — архитектурный контроль и review checkpoint;
- **Claude Code** — написание кода по утверждённой задаче;
- **Cursor** — рабочая среда, запуск команд, Git, commit/push.

---

## Решения плана (IP-01 — IP-08)

| ID | Решение |
|----|---------|
| **IP-01** | `project.companies.id` — Integer; `project.projects.id`, `project.lines.id`, `engineering.engineering_documents.id`, `engineering.document_revisions.id`, `engineering.joints.id` — UUID; `project_companies` связывает `project_id` (UUID) и `company_id` (Integer) |
| **IP-02** | Минимальный реестр `project.companies` (id, name, inn, status, created_by, created_at); расширенная карточка отложена; `project_companies` с полноценными FK |
| **IP-03** | `X-User-Id` = `hr.workers.id`; не аутентификация; сервисы проверяют активные `hr.worker_roles`; JWT не входит в план |
| **IP-04** | Добавить `MASTER` в `hr.worker_roles` (CHECK, Pydantic, тесты); `HEAT_TREATMENT_OPERATOR` не добавлять |
| **IP-05** | Scope: `GLOBAL`, `PROJECT`, `LINE`; `scope_id` — UUID проекта/линии в **строковом** виде; `FOREMAN`/`MASTER` создают DRAFT Joint; ПТО (`PTO_ENGINEER`) подтверждает, отменяет и заменяет Joint; ПТО (`PTO_ENGINEER`) утверждает EngineeringDocument и DocumentRevision; ПТО (`PTO_ENGINEER`) привязывает Joint к новой ревизии |
| **IP-06** | Ветка `feature/engineering-joints-mvp`, создана от `6f1bc85` |
| **IP-07** | Предметное название роли — **ПТО**; технический `role_code` существующего backend — `PTO_ENGINEER`; существующий `PTO_ENGINEER` сохраняется; новый `role_code` `PTO` **не** добавляется; миграция данных `PTO_ENGINEER` → `PTO` **не** выполняется |
| **IP-08** | Line создаёт и изменяет техническая роль `PTO_ENGINEER`; при создании Line допускается `GLOBAL` или соответствующий `PROJECT` scope; `LINE` scope **не** используется для создания ещё не существующей линии; `FOREMAN`/`MASTER` **не** создают и **не** изменяют Line; предметное название владельца — **ПТО** |

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
20260703_03_welder_admissions
  → 20260710_01_hr_master_role
  → 20260710_02_project_core
  → 20260710_03_project_lines
  → 20260710_04_engineering_docs        (Task 4, текущий head — commit 6d2ea09)
  → 20260711_05_engineering_joints      (Task 5A)
  → 20260711_06_joint_review            (Task 5B)
  → 20260711_07_joint_doc_revisions     (Task 6)
  → 20260711_08_joint_bulk_requests     (Task 7)
```

> Примечание: фактический id миграции Task 4 — `20260710_04_engineering_docs`
> (сокращён с `…_documents`: полное имя занимало 33 символа и не помещалось в
> `alembic_version.version_num varchar(32)`). Имена этапов 5A–7 подобраны ≤ 32
> символов.

---

## Task 1 — MASTER и scoped role check

### Цель

Подготовить минимальную проверку ролей для последующих API: добавить роль `MASTER`, сохранить все существующие `role_code` без изменений (включая `PTO_ENGINEER` для ПТО — IP-07), scope `GLOBAL` / `PROJECT` / `LINE`, валидация `scope_id` как UUID-строки.

**Ограничения миграции и ролей (IP-07):**

- миграция `20260710_01_hr_master_role` добавляет в CHECK **только** `MASTER`;
- `PTO_ENGINEER` сохраняется без изменений;
- новый `role_code` `PTO` **не** добавляется;
- `UPDATE role_code` в данных `worker_roles` **не** выполняется.

### Файлы

**Modify:**

- `09_Разработка/backend/app/hr/models.py`
- `09_Разработка/backend/app/hr/schemas.py`
- `09_Разработка/backend/app/hr/repository.py`
- `09_Разработка/backend/app/hr/services.py` — `scope_id: str | None`; `PROJECT`/`LINE` — нормализованный строковый UUID; `GLOBAL` — `scope_id` отсутствует; остальные существующие scopes (`COMPANY`, `SITE`) сохраняют прежнюю семантику
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
| — | Миграция `20260710_01_hr_master_role.py`: пересоздать/расширить CHECK `ck_hr_worker_roles_role_code`, **добавив** `MASTER`; все существующие допустимые `role_code` сохраняются; `PTO` не добавляется; UPDATE `role_code` в данных не выполняется |
| — | Pydantic `WorkerRoleCode`: добавлен `MASTER`; существующие значения, включая `PTO_ENGINEER`, без изменений; `PTO` не добавляется |

**Ключевые имена:**

- `permissions.RoleRequirement` — dataclass: `role_code`, `scope_type`, `scope_id` (optional UUID str)
- `permissions.check_worker_role(db, worker_id, requirement) -> bool`
- `permissions.require_worker_role(db, worker_id, requirement) -> None` — raises 403
- `HrRepo.find_active_roles(worker_id, role_code, scope_type, scope_id) -> list[WorkerRole]`
- `HrRepo.has_active_worker_role_in_scope(...)` — замена/расширение `has_active_worker_role`

### Шаги

- [ ] **1.1** Написать failing test: `WorkerRoleCreate(role_code="MASTER")` и `role_code="PTO_ENGINEER"` проходят валидацию
- [ ] **1.2** Написать failing tests в `test_role_permissions.py` (см. ниже)
- [ ] **1.3** Миграция CHECK (только добавление `MASTER`) + синхронизировать model CHECK
- [ ] **1.4** Обновить `WorkerRoleCode` Literal — добавить `MASTER`
- [ ] **1.5** Реализовать `permissions.py` и методы `HrRepo`
- [ ] **1.6** Прогнать тесты, регрессия HR/OGS
- [ ] **1.7** Commit

### Failing tests (порядок)

| # | Тест | Команда | Ожидаемый FAIL |
|---|------|---------|----------------|
| 1 | `test_worker_role_create_accepts_master_and_pto_engineer` | `pytest tests/test_hr_worker_roles_schemas.py::test_worker_role_create_accepts_master_and_pto_engineer -q` | `ValidationError` или тест отсутствует |
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
- **не** назначать эти действия ролям ПТО (`PTO_ENGINEER`), `FOREMAN` или `MASTER` на этом этапе;
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

**Права (IP-08, `role_code` `PTO_ENGINEER`):**

- `POST` Line — ПТО (`PTO_ENGINEER`) с `GLOBAL` или соответствующим `PROJECT` scope; `LINE` scope для создания **не** допускается;
- `PATCH` Line — ПТО (`PTO_ENGINEER`) с `GLOBAL`, соответствующим `PROJECT` либо соответствующим `LINE` scope;
- отсутствие подходящей роли → `403`;
- `GET` (list / get) — существующий authenticated API pattern: валидный `X-User-Id` активного `hr.workers` (`employment_status = active`); отсутствие заголовка → `401`; неизвестный `worker_id` → `404`;
- `FOREMAN` / `MASTER` **не** создают и **не** изменяют Line.

**API:**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/projects/{project_id}/lines` | `create_line` — ПТО (`PTO_ENGINEER`), GLOBAL / PROJECT scope |
| GET | `/api/v1/projects/{project_id}/lines` | `list_lines` |
| GET | `/api/v1/projects/lines/{line_id}` | `get_line` |
| PATCH | `/api/v1/projects/lines/{line_id}` | `update_line` — ПТО (`PTO_ENGINEER`), GLOBAL / PROJECT / LINE scope; только draft/active редактируемые поля |

### Шаги

- [ ] **3.1** Failing test: POST line без project → 404
- [ ] **3.2** Failing test: duplicate line_no в project → 409
- [ ] **3.3** Failing test: nominal_dn <= 0 → 422
- [ ] **3.4** Failing test: GLOBAL `PTO_ENGINEER` создаёт Line
- [ ] **3.5** Failing test: `PTO_ENGINEER` соответствующего `PROJECT` scope создаёт Line
- [ ] **3.6** Failing test: `PTO_ENGINEER` чужого `PROJECT` scope → 403
- [ ] **3.7** Failing test: `FOREMAN` / `MASTER` → 403 на POST и PATCH
- [ ] **3.8** Failing test: `PTO_ENGINEER` соответствующего `LINE` scope изменяет существующую Line
- [ ] **3.9** Failing test: `LINE` scope не может создать новую Line → 403
- [ ] **3.10** Миграция + реализация
- [ ] **3.11** PASS + регрессия
- [ ] **3.12** Commit

**Первый failing test:**

```powershell
pytest tests/test_project_lines_api.py::test_create_line_for_project -q
```

**Ожидаемый FAIL:** `404` или таблица `project.lines` не существует.

**TDD-сценарии прав (IP-08):**

| # | Сценарий | Ожидание |
|---|----------|----------|
| 1 | GLOBAL `PTO_ENGINEER` создаёт Line | `201` |
| 2 | `PTO_ENGINEER` соответствующего `PROJECT` scope создаёт Line | `201` |
| 3 | `PTO_ENGINEER` чужого `PROJECT` scope | `403` |
| 4 | `FOREMAN` / `MASTER` на POST / PATCH | `403` |
| 5 | `PTO_ENGINEER` соответствующего `LINE` scope изменяет существующую Line | `200` |
| 6 | `LINE` scope на POST (создание новой Line) | `403` |

**Самопроверка Task 3:**

- владелец Line — **ПТО** (`PTO_ENGINEER`);
- производственные роли (`FOREMAN`, `MASTER`) Line **не** создают и **не** изменяют;
- `LINE` scope применяется только к уже существующей линии (PATCH), не к POST.

**Commit:** `feat(projects): add project lines`

**Checkpoint:** ChatGPT — `required_inspection_types` как `ARRAY(Text)` снимок для будущих Joint (ADR-009 004-25); владелец Line — ПТО (IP-08).

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

**Права (role_code `PTO_ENGINEER`, scope GLOBAL / PROJECT / LINE):**

- создать `EngineeringDocument` и `DocumentRevision` — активная роль `PTO_ENGINEER` в соответствующем scope;
- `approve` / `cancel` / `supersede` документа и ревизии — `PTO_ENGINEER` в scope проекта (или GLOBAL);
- `X-User-Id` = `hr.workers.id`; отсутствие подходящей роли → `403`.

**Сервисы:**

- `EngineeringService.create_document()`, `approve_document()`, `cancel_document()`, `supersede_document()`
- `EngineeringService.create_revision()`, `approve_revision()`, `cancel_revision()`, `supersede_revision()`

**API (`prefix="/engineering"`):**

| Метод | Путь | Handler |
|-------|------|---------|
| POST | `/api/v1/engineering/documents` | `create_document` — ПТО (`PTO_ENGINEER`) |
| GET | `/api/v1/engineering/documents` | `list_documents` |
| GET | `/api/v1/engineering/documents/{id}` | `get_document` |
| POST | `/api/v1/engineering/documents/{id}/approve` | `approve_document` — ПТО (`PTO_ENGINEER`) |
| POST | `/api/v1/engineering/documents/{id}/cancel` | `cancel_document` — ПТО (`PTO_ENGINEER`) |
| POST | `/api/v1/engineering/documents/{id}/supersede` | `supersede_document` — ПТО (`PTO_ENGINEER`) |
| POST | `/api/v1/engineering/documents/{id}/revisions` | `create_revision` — ПТО (`PTO_ENGINEER`) |
| GET | `/api/v1/engineering/documents/{id}/revisions` | `list_revisions` |
| POST | `/api/v1/engineering/revisions/{id}/approve` | `approve_revision` — ПТО (`PTO_ENGINEER`) |
| POST | `/api/v1/engineering/revisions/{id}/cancel` | `cancel_revision` — ПТО (`PTO_ENGINEER`) |
| POST | `/api/v1/engineering/revisions/{id}/supersede` | `supersede_revision` — ПТО (`PTO_ENGINEER`) |

### Шаги

- [ ] **4.1** Failing test: ПТО (`PTO_ENGINEER`) PROJECT scope создаёт и утверждает document + revision
- [ ] **4.2** Failing test: ПТО (`PTO_ENGINEER`) чужого PROJECT scope → 403
- [ ] **4.3** Failing test: revision без document → 404/422
- [ ] **4.4** Failing test: duplicate document_no в project → 409
- [ ] **4.5** Failing test: approve переводит status, физического DELETE нет
- [ ] **4.6** Миграция + модуль engineering
- [ ] **4.7** PASS + регрессия
- [ ] **4.8** Commit

**Первый failing test:**

```powershell
pytest tests/test_engineering_documents_api.py::test_pto_engineer_creates_and_approves_document -q
```

**Commit:** `feat(engineering): add documents and revisions`

**Checkpoint:** ChatGPT — line_id nullable, согласованность project/line FK.

---

## Task 5A — Joint Core

> Пересматривает прежний Task 5 по ADR-010 (принят). Только ядро Joint без
> lifecycle-переходов согласования, истории снимков и bulk.

### Цель

Таблица `engineering.joints` с обязательной связью с Line, автогенерацией
`system_code`, нормализацией `joint_no`, optimistic locking (`version`) и
вычисляемыми полями `ready_for_welding`, `missing_welding_requirements`,
`production_state`. CRUD + PATCH только допустимых полей. Переходы согласования
(`pto_status` / `ogs_status`, `PENDING_REVIEW` / `ACTIVE`) — в Task 5B.

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

- `09_Разработка/backend/migrations/versions/20260711_05_engineering_joints.py`
- `09_Разработка/backend/tests/test_engineering_joints_api.py`

### Модель `Joint` (ADR-010)

- `id` UUID PK; `project_id` FK → `project.projects` NOT NULL; `line_id` FK →
  `project.lines` **NOT NULL**; `origin_document_revision_id`,
  `current_document_revision_id` FK → `engineering.document_revisions` NOT NULL.
- `system_code` `varchar(64)` NOT NULL, автогенерация `<project_code>-JNT-<sequence>`
  (отдельная на проект, без переиспользования); `UNIQUE(project_id, system_code)`;
  от пользователя не принимается.
- `joint_no` `varchar(100)` NOT NULL (исходное); `joint_no_normalized` `varchar(100)`
  NOT NULL (trim, схлопывание пробелов, типографские дефисы → `-`, сравнение без
  учёта регистра).
- Инженерные поля по сторонам (`dn_1/2`, `thickness_1/2`, `material_id_*`,
  `material_text_*`, `component_type_*`, `component_item_id_*`, `component_text_*`),
  классификация (`geometry_type`, `weld_joint_type`, `connection_code`), проектные
  способы сварки (`required_root/fill/cap_method`), требование термообработки,
  положение на чертеже (координаты необязательны; при `position_x/y` обязателен
  `coordinate_system`).
- Материалы / номенклатура / WPS — nullable UUID **без FK** (Р-4).
- Аудит: `created_by`, `updated_by`, `created_at`, `updated_at`; `version` для
  optimistic locking. Физического удаления нет; DELETE-endpoint не создаётся.

### Согласованность иерархии (Б-3, ADR-010)

- `Joint.line_id` обязателен.
- Если `EngineeringDocument.line_id` заполнен — совпадает с `Joint.line_id`.
- Если `EngineeringDocument.line_id IS NULL` — допустим как основание; линия из
  Joint; документ обязан быть того же `Project`.
- Тип документа-основания не ограничивается `ISOMETRIC`.

### Права

Создавать Joint: `MASTER`, `FOREMAN`, `PTO_ENGINEER`, `OGS_ENGINEER` в допустимом
scope (проверка по документу Joint). Обычный PATCH не меняет `system_code`,
`origin_/current_document_revision_id`, `status`, `pto_status`, `ogs_status`,
`superseded_by_joint_id`.

### Вычисляемые поля (Б-4)

`ready_for_welding`, `missing_welding_requirements`, `production_state`
(`NOT_STARTED`) сохраняются из ADR-009. `requires_review` — отдельный признак
(в 5A может быть выведен, статусы согласования вводятся в 5B).

### API

| Метод | Путь |
|-------|------|
| POST | `/api/v1/engineering/joints` |
| GET | `/api/v1/engineering/joints/{joint_id}` |
| GET | `/api/v1/engineering/joints` (фильтры, сортировка, limit/offset, total) |
| PATCH | `/api/v1/engineering/joints/{joint_id}` |

### Ключевые тесты

Создание всеми разрешёнными ролями; отказ без роли / чужой проект / неверная линия
/ ревизия другого проекта или линии; автогенерация и уникальность `system_code`;
нормализация `joint_no` (регистр, пробелы, дефисы), уникальность в ревизии,
одинаковый номер в другой ревизии допустим, исходный `joint_no` сохраняется;
optimistic locking (успех, конфликт устаревшей version, инкремент);
`ready_for_welding` false/true; запрет изменения защищённых полей через PATCH.

**Commit:** `feat(engineering): add joint core`

**Checkpoint:** ChatGPT — обязательность Line, автогенерация system_code, отсутствие
FK WPS/МТО.

---

## Task 5B — Joint Review Lifecycle

### Цель

Двойное согласование ПТО/ОГС поверх ядра Task 5A: статусы `PENDING_REVIEW` /
`ACTIVE`, `pto_status` / `ogs_status`, команды submit / confirm / reject / cancel /
supersede; аддитивное расширение `scope_type` значением `ENGINEERING_DOCUMENT`.

> **Детальный канон Task 5B — [[docs/project/ADR-011-joint-lifecycle-approvals-blocking-scope|ADR-011]]** (принят 2026-07-11):
> полный жизненный цикл, независимые согласования, блокировки, три версии Joint
> (`record`/`approval`/`workflow`), отмена, замена и переоценка. Расхождения словарей с
> ADR-010 **закрыты** решениями Р-11-1 — Р-11-4 (раздел «Решения по согласованию с
> ADR-010» в ADR-011) и учтены в «Решениях» ниже. Общая линия: словари и физическая
> схема — по ADR-010, полнота жизненного цикла и обязательный объём (§44) — по ADR-011.
> Полные блокировки, переоценка (`ENGINEERING`/`WELDING_TECHNOLOGY`) и проверка
> целостности одного Joint — обязательный объём Task 5B по ADR-011 §44, детализируются
> при разработке этапа.

### Файлы

**Modify:**

- `09_Разработка/backend/app/engineering/models.py`, `schemas.py`, `repository.py`,
  `services.py`, `api.py`
- `09_Разработка/backend/app/hr/models.py`, `schemas.py` — `scope_type`
  `ENGINEERING_DOCUMENT` (аддитивно)
- `09_Разработка/backend/migrations/env.py`
- `09_Разработка/backend/tests/conftest.py`

**Create:**

- `09_Разработка/backend/migrations/versions/20260711_06_joint_review.py`
- `09_Разработка/backend/tests/test_engineering_joint_review.py`

### Решения

- Состояния согласования (Р-11-1): `pto_status`/`ogs_status` ∈
  `NOT_SUBMITTED/PENDING/APPROVED/REJECTED/REVOKED` (положительное решение —
  `APPROVED`, **не** `CONFIRMED`). Дополнительно `pto_pending_reason`/
  `ogs_pending_reason` (`INITIAL_REVIEW/REVIEW_REOPENED/TEMPORARY_SUSPENSION/
  REVALIDATION`), `pto_decision_method`/`ogs_decision_method`
  (`AUTOMATIC/MANUAL/OVERRIDE`), `pto_comment`/`ogs_comment`, `pto_decided_by/at`,
  `ogs_decided_by/at`, `submitted_by/at`. При создании `status=DRAFT`, оба
  `NOT_SUBMITTED`; после submit — оба `PENDING`.
- Версии (Р-11-2): три версии — `record_version` (concurrency, = прежняя `version`
  Task 5A, переименование), `approval_version` (значимые данные; к ней привязаны
  согласования), `workflow_version` (переходы/блокировки/замена); все `>0`. Конфликт →
  `409` с кодами `RECORD_/APPROVAL_/WORKFLOW_/SOURCE_JOINT_/SUCCESSOR_JOINT_VERSION_CONFLICT`,
  без автоповтора.
- Роли (Р-11-3): подтверждают `PTO_ENGINEER` (ПТО) и `OGS_ENGINEER` (ОГС); в CHECK
  `hr.worker_roles.role_code` **аддитивно** добавляются `PTO_MANAGER`, `CHIEF_WELDER`,
  `AUDITOR` (исключительные/совместные решения, диагностика). Права — по действующей
  роли, не по должности.
- `scope_type` (Р-1 / Р-11-4): `ENGINEERING_DOCUMENT` добавляется аддитивно к
  `GLOBAL/COMPANY/PROJECT/SITE/LINE`; `COMPANY`/`SITE` сохраняются; переименования и
  миграции данных нет. Концептуальные уровни ADR-011 отображаются на канон:
  `ISOMETRIC → ENGINEERING_DOCUMENT`, `UNIT → SITE`; литералы `UNIT`/`ISOMETRIC` не
  вводятся. Обновить CHECK БД, Pydantic `ScopeType`, HR-тесты, проверки scope (по
  иерархии, а не только по `scope_id`).
- Разделение полей ПТО/ОГС: изменение полей ПТО → сброс `pto_status`; ОГС →
  `ogs_status`; общих → оба; из `ACTIVE` → `PENDING_REVIEW`. Значимое изменение
  увеличивает `approval_version`, любое изменение — `record_version`, workflow-переход
  — `workflow_version`.
- `ACTIVE` — автоматически и атомарно при обоих `APPROVED` для текущей
  `approval_version`.
- `requires_review = true`, если `pto_status != APPROVED` или `ogs_status !=
  APPROVED`, а также в `DRAFT`/`PENDING_REVIEW`.

### API (переходы)

`POST /joints/{id}/submit-for-review` · `/approve-pto` · `/approve-ogs` ·
`/reject-pto` · `/reject-ogs` · `/revoke-pto` · `/revoke-ogs` · `/cancel` ·
`/supersede`.

Правила: submit — из `DRAFT` или повторно после `REJECTED`, сохраняет
`submitted_by/at`, оба согласования → `PENDING`, → `PENDING_REVIEW`; approve-pto —
только `PTO_ENGINEER`, меняет только `pto_status` → `APPROVED`; approve-ogs — только
`OGS_ENGINEER`; reject — комментарий обязателен, Joint остаётся `PENDING_REVIEW`;
revoke — отзыв действующего `APPROVED` (не восстанавливается, инвариант №20),
основание обязательно; cancel/supersede — причина, подразделение (`PTO`/`OGS`), actor,
ожидаемые версии; supersede дополнительно `superseded_by_joint_id` (запрет
self-supersede; заменяющий того же проекта; допустимый статус). Команды передают
релевантные версии; статусы через обычный PATCH не меняются. Автоматическое
согласование ОГС (`AUTOMATIC`) и `OVERRIDE` (`CHIEF_WELDER`) — предусмотреть способ
решения и аудит (ADR-011 §9), полнота логики поэтапно.

### Ключевые тесты

DRAFT → PENDING_REVIEW; approve ПТО/ОГС; авто-ACTIVE при обоих `APPROVED`; reject
ПТО/ОГС; revoke (не восстанавливается); обязательный комментарий; повторная отправка
после reject; cancel; supersede; запрет self-supersede; выборочный сброс согласований
при изменении полей ПТО/ОГС/общих; возврат ACTIVE → PENDING_REVIEW; три версии
(`record`/`approval`/`workflow`) и коды `409`; `scope_type` `ENGINEERING_DOCUMENT` не
ломает существующие области; проверка scope по иерархии; регрессия HR.

**Commit:** `feat(engineering): add joint review lifecycle`

**Checkpoint:** ChatGPT — двойное согласование (`APPROVED`), три версии Joint,
аддитивный scope_type, роли PTO_ENGINEER/OGS_ENGINEER + PTO_MANAGER/CHIEF_WELDER/AUDITOR.

---

## Task 6 — Joint ↔ DocumentRevision History

### Цель

Таблица `engineering.joint_document_revisions` с неизменяемыми снимками, роли связей,
аннулирование, смена текущей ревизии.

### Файлы

**Modify:** `engineering/models.py`, `schemas.py`, `repository.py`, `services.py`,
`api.py`, `migrations/env.py`.

**Create:**

- `09_Разработка/backend/migrations/versions/20260711_07_joint_doc_revisions.py`
- `09_Разработка/backend/tests/test_engineering_joint_revisions.py`

### Таблица `joint_document_revisions`

- `id` UUID PK; `joint_id` FK NOT NULL; `document_revision_id` FK NOT NULL;
  `revision_role` (`ORIGIN/CONFIRMED/MODIFIED/REMOVED`); `document_role`
  (`PRIMARY/ADDITIONAL/EXECUTIVE/REFERENCE`); `link_status` (`ACTIVE/INVALIDATED`).
- Полный неизменяемый снимок основных параметров Joint (joint_no, нормализация, dn/
  толщины, материалы, компоненты, классификация, способы сварки, термообработка,
  положение) на момент связи. Снимок не редактируется (PATCH snapshot нет).
- Аннулирование: `invalidated_reason/by/at`; `updated_at`/`updated_by` меняются
  только при аннулировании; аннулированная связь остаётся в истории, не может стать
  текущей PRIMARY.
- Partial unique index: `joint_no_normalized` уникален среди активных связей в одной
  `DocumentRevision` (`WHERE link_status='ACTIVE'`); одна активная `PRIMARY`-связь на
  Joint, соответствующая `current_document_revision_id`.

### API

`POST /joints/{id}/document-revisions` (новый снимок, не меняет current
автоматически) · `POST /joints/{id}/document-revisions/{link_id}/invalidate`
(`PTO_ENGINEER`/`OGS_ENGINEER`, причина; текущую PRIMARY нельзя аннулировать без
предварительной смены; повтор → конфликт) · `POST /joints/{id}/set-current-revision`
(expected version; связь принадлежит Joint, ACTIVE, соответствует ревизии;
обновляет `current_document_revision_id`, назначает новую PRIMARY, снимает прежнюю
без изменения снимка, копирует поля Joint из выбранного снимка, проверяет права на
старый и новый документ, сбрасывает нужные подтверждения, инкремент `version`).

### Ключевые тесты

ORIGIN-связь при создании Joint; соответствие снимка Joint; неизменяемость снимка;
новая связь; аннулирование; запрет current для аннулированной; отсутствие
физического удаления; set-current-revision (успех, копирование полей, смена PRIMARY,
права на оба документа, запрет INVALIDATED / чужой связи).

**Commit:** `feat(engineering): add joint document revision history`

**Checkpoint:** ChatGPT — неизменяемые снимки, одна активная PRIMARY, права на оба
документа при смене ревизии.

---

## Task 7 — Bulk Joint Import

### Цель

Массовое атомарное создание Joint из одной `DocumentRevision` с идемпотентностью.

### Файлы

**Modify:** `engineering/schemas.py`, `repository.py`, `services.py`, `api.py`,
`migrations/env.py`.

**Create:**

- `09_Разработка/backend/migrations/versions/20260711_08_joint_bulk_requests.py`
- `09_Разработка/backend/tests/test_engineering_joint_bulk.py`

### Решения

- `POST /api/v1/engineering/joints/bulk` — общие поля (`project_id`, `line_id`,
  `document_revision_id`, `created_by`, `idempotency_key`) + строки (≤ 500) с
  параметрами конкретных Joint. Атомарно: любая невалидная строка → не создаётся ни
  один Joint; ошибки с `row_index`; `system_code` присваивается только после
  успешной валидации всего пакета; commit/rollback целиком. Успех: `row_index`,
  `id`, `system_code`, `joint_no`.
- Таблица `engineering.joint_bulk_requests`: `id`, `project_id`, `idempotency_key`,
  `request_hash`, `status`, `response_payload` JSON, аудит;
  `UNIQUE(project_id, idempotency_key)`. Тот же ключ и hash → сохранённый
  `response_payload`; тот же ключ, другой hash → конфликт; ответ хранится целиком и
  не пересобирается. Hash — из канонизированного тела запроса без нестабильных
  значений.

### Ключевые тесты

Успешный пакет; максимум 500; отказ при 501; атомарный rollback; ошибки с
`row_index`; `system_code` не расходуются при неуспехе; сопоставление `row_index`;
повтор с тем же `idempotency_key`; конфликт при другом содержимом; возврат
сохранённого `response_payload`.

**Commit:** `feat(engineering): add bulk joint import`

**Checkpoint:** ChatGPT — атомарность, идемпотентность, отсутствие расхода
system_code при неуспехе; финальная регрессия Tasks 1–6.

**Статус:** ✅ **закрыт** (инженерный контур `Project → Line → EngineeringDocument → DocumentRevision → Joint` завершён).

---

## Следующий этап — WeldOperation (Session 005)

> **Предусловие:** к Task 8A переходят **только после** принятия
> [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 005|Architecture Session 005]]
> и [[docs/project/DECISIONS#ADR-012. WeldOperation как неизменяемый производственный факт сварки|ADR-012]].
> Детальное ТЗ Task 8A в этом документе **не раскрывается**.

Канон: Session 005 (решения 005-A — 005-CE) · ADR-012.

| Task | Содержание |
|------|-----------|
| **8A — WeldOperation Core** | Базовая сущность, lifecycle, этапы, автор / ответственный, организационный снимок |
| **8B — Qualification & WPS Validation** | Проверка допуска, клейма, WPS; маршрутизация ОГС при нарушениях |
| **8C — OGS Review & Confirmation** | Review ОГС, подтверждение сварщика, раздельные статусы |
| **8D — Corrections & Supersede** | `WeldOperationCorrection`, атомарное применение, `reweld` |
| **8E — Import & Conflict Resolution** | Импорт, идемпотентность, конфликты |
| **8F — Heat Treatment Integration** | Термическая обработка: `HeatTreatmentBatch`/`HeatTreatmentOperation`, карта, документы, отклонения, вычисляемое состояние `Joint`, журнал |

> **Переопределение Task 8F:** ранний план описывал «Integration Boundaries»
> (границы МТО/ОТК/НК, `InspectionApplicabilityDecision`). Фактически Task 8F
> реализован как **Heat Treatment Integration** (ADR-014); прежнее наполнение
> «Integration Boundaries» вынесено в отдельный будущий этап.

**Статус реализации (2026-07-13):** Tasks 8A–8F **реализованы**. Фактические
компоненты Task 8F:

- **модели** — `HeatTreatmentProcedureRevision`, `HeatTreatmentBatch`,
  `HeatTreatmentOperation`, `HeatTreatmentRecord`, `HeatTreatmentDeviation`
  (схема `engineering`, миграция `20260713_14_heat_treatment`);
- **workflow** — цикл `DRAFT → PLANNED → IN_PROGRESS → COMPLETED → REVIEWED → CLOSED`
  (+ `CANCELLED`/`REJECTED`), снимок карты, автоматическая проверка;
- **API** — `heat_treatment_api.py` (циклы, операции, документы, отклонения,
  журнал, состояние `Joint`);
- **документы** — `HeatTreatmentRecord` (температурная диаграмма и др.);
- **отклонения** — `HeatTreatmentDeviation`;
- **вычисляемое состояние `Joint`** — требование ТО и готовность к зависимым этапам;
- **read-only журнал** — представление, одна строка = одна `HeatTreatmentOperation`;
- **тесты** — `tests/test_heat_treatment.py` (40 тестов; регрессия `679 passed`).

**Не входит в Task 8:** локальный ремонт, `RepairOperation`, `Defect`, полный lifecycle
Inspection / NDTInspection, полноценный МТО, учёт бригад (`Crew`). Роль
`HEAT_TREATMENT_OPERATOR` в Task 8F **не добавлена** (MVP-ограничение, ADR-014).

---

## Следующий этап — Контроль качества и НК (Session 007)

> **Предусловие:** к Task 9A переходят **только после** принятия
> [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 007|Architecture Session 007]]
> и [[docs/project/DECISIONS#ADR-015. Inspection and NDT Workflow Canon (Session 007)|ADR-015]].
> На Session 007 **код, миграции и тесты не создавались**; детальное ТЗ Task 9A в
> этом документе **не раскрывается**.

Канон: Session 007 (решения 007-01 — 007-27) · ADR-015. Основной инициатор заявки на
контроль — **ОГС**. Контур:
`Joint → Inspection → назначение методов → выполнение → технические результаты →
проверка ОТК → решение ОГС → состояние Joint → журнал контроля`.

| Task | Содержание |
|------|-----------|
| **9A — Inspection Core — DONE** | `Inspection`, нумерация (`<PROJECT_CODE>-INS-<SEQUENCE>`), связь с `Joint`, lifecycle, готовность `Joint`, permissions/scope, базовый `Joint.inspection_state` |
| **9B — Method Assignment and Laboratory — DONE** | методы (`VT`/`RT`/`UT`/`PT`/`MT`/`LT`), `InspectionMethodAssignment`, лаборатория через `project_companies` (роль `NDT_LAB`), lifecycle назначения `ASSIGNED`/`CANCELLED`/`REPLACED`, проверки лаборатории (реализовано; ТЗ Task 9B сузило исходную формулировку — отдельный `NdtLaboratoryProfile`, сроки, приоритет и стоимость **не входят**) |
| **9C — Method Execution and Results — DONE** | `MethodExecution`, локальные `MethodExecutionResultItem`, редакции выполнения и результатов, `LaboratoryConclusion` и его редакции, внешняя лаборатория/лица, Quality Audit и API; `LAB_CONFIRMED` не является решением ОТК, `VERIFIED` отложен |
| **Task 9D (Session 008 → 008-07)** | Канон качества после результата контроля. Действующая реализационная структура — **9D-1 … 9D-8** (Session 008-07 / ADR-019, решение 008-07-BO); историческая разбивка Session 008 на 9E — 9K — `SUPERSEDED_BY_TASK_9D` (поглощение и остаток — в [таблице соответствия](#соответствие-старых-tasks-9e--9k-блокам-9d-1--9d-8-решение-008-07-bo)). См. [«Следующий этап — Решения по качеству, дефекты, ремонт и документы (Session 008)»](#следующий-этап--решения-по-качеству-дефекты-ремонт-и-документы-session-008) |

**Согласованность:** готовность и актуальность результатов опираются на актуальную
завершённую `WeldOperation` (ADR-012); `reweld` → новый `Inspection`; обязательный
контроль после термообработки — связь `Inspection ↔ HeatTreatmentOperation`
(ADR-014). `Joint.inspection_state` **вычисляется** и не переписывает основной
lifecycle `Joint`.

**Историческая совместимость (ADR-015):**

- результаты `PASS`/`FAIL`/`CONDITIONAL` из ADR-009 — исторический проектный вариант;
  реализованные оценки `MethodExecutionResultItem` —
  `CONFORMING`/`NONCONFORMING`/`INCONCLUSIVE`/`NOT_EVALUATED`;
  `NOT_EVALUATED` означает, что оценка ещё не сформирована, а
  `CONTROL_NOT_PERFORMED` — что контроль не выполнен; это разные понятия;
- прежняя схема `quality.defects` (ADR-009) — предварительный черновик; канон:
  `индикация лаборатории → подтверждение и классификация ОТК → Defect → решение ОГС`;
  полный ремонтный lifecycle — вне **Task 9E**;
- роль: бизнес-наименование `WELDING_ENGINEER`, технический `role_code` —
  `OGS_ENGINEER`; новый `role_code` не вводится.

**Не входит в Session 007 (вне Tasks 9A — 9G):** полный ремонтный lifecycle,
`RepairOperation`, `Reweld`, полная аттестация дефектоскопистов, полный реестр
оборудования НК, полная модель аккредитации лабораторий.

> **Граница с Architecture Session 008.** Импорт результатов контроля (XLSX, CSV, PDF,
> API лаборатории) в Session 007 зафиксирован **только как интеграционное требование
> верхнего уровня**: импорт **не может автоматически принимать результат**. Детальная
> архитектура импорта результатов НК (форматы, разбор протоколов, PDF-извлечение, API
> лабораторий, staging/сопоставление/конфликты/провенанс, ручное подтверждение)
> проектируется в будущей **Architecture Session 008** и в Tasks 9A — 9G **не входит**.

**Статус реализации (2026-07-13):**

- **Task 9A — Inspection Core — реализована и принята.** Миграция
  `20260713_15_inspection_core` (down_revision `20260713_14_heat_treatment`; один
  Alembic head). Отдельный модуль `app/quality`, схема `quality`, сущности
  `Inspection` (`quality.inspections`), `InspectionSequence`
  (`quality.inspection_sequences`), `InspectionEvent` (`quality.inspection_events`).
  Реализованы: lifecycle `DRAFT → REQUESTED`, `DRAFT → CANCELLED`,
  `REQUESTED → CANCELLED`; подтверждение производственной готовности СМР
  (`FOREMAN`/`MASTER`); фиксация готовности ОГС при переходе в `REQUESTED`; override
  главного сварщика (обходит **только** отсутствие подтверждения СМР, не системные
  блокеры); optimistic locking (`version`); идемпотентное создание
  (`Idempotency-Key`); append-only журнал событий; RBAC/scope
  (GLOBAL/PROJECT/LINE/ENGINEERING_DOCUMENT; COMPANY-scope — только чтение, не
  изменяющие действия); проектная нумерация `<PROJECT_CODE>-INS-<SEQUENCE>`;
  readiness `Joint` на реальных статусах моделей (`Joint.status = ACTIVE`,
  актуальная завершённая `WeldOperation`, обязательная принятая
  `HeatTreatmentOperation` по канону Task 8F) и вычисляемое `Joint.inspection_state`
  (без хранимой колонки, батч-расчёт без N+1). Полная регрессия — **791 passed**.
  Согласованное уточнение: actor-поля (`*_by_worker_id`, `actor_worker_id`) —
  `hr.workers.id` типа `Integer` **без FK** на `hr.workers` (переходный период, как
  в Joint/WeldOperation; `X-User-Id` — Integer); FK добавлены на `project.projects` и
  `engineering.joints`.
- **Task 9B — Method Assignment and Laboratory — реализована и принята.** Миграция
  `20260713_16_method_assignments` (down_revision `20260713_15_inspection_core`; один
  Alembic head; идентификатор revision укорочён из-за `alembic_version.version_num
  VARCHAR(32)`, имя файла — полное). В схеме `quality` добавлена одна таблица
  `quality.inspection_method_assignments` (сущность `InspectionMethodAssignment`).
  Реализованы: назначение метода из закрытого набора `VT`/`RT`/`UT`/`PT`/`MT`/`LT`
  (enum `InspectionMethodCode`, отдельный от `projects.InspectionType`); назначение
  лаборатории через существующую `project.companies` (`laboratory_company_id` —
  Integer FK) с проверкой действующей связи `project_companies` роли `NDT_LAB` того
  же проекта, что и `Inspection`; lifecycle назначения `ASSIGNED → CANCELLED` и
  `ASSIGNED → REPLACED` (атомарная замена в одной транзакции, старая запись
  сохраняется и ссылается на новую через `replaced_by_assignment_id`); запрет более
  одного активного назначения метода на `Inspection` (partial unique index
  `WHERE status = 'ASSIGNED'` + сервисная проверка + маппинг `IntegrityError` в
  доменный конфликт); ограниченный `PATCH` только примечаний; optimistic locking
  (`version`); actor-поля канона Task 9A (`assigned_by_worker_id`,
  `cancelled_by_worker_id`, `created_by`/`updated_by_worker_id` — Integer без FK);
  RBAC/scope (write — `OTK_INSPECTOR`/`NDT_SPECIALIST`/`CHIEF_WELDER`, `OGS_ENGINEER`
  общесистемного права не получает; COMPANY-scope — только чтение); вычисляемая
  сводка готовности заявки (`has_method_assignments`, `active_method_assignment_count`,
  `assigned_method_codes`, `all_assignments_have_laboratory`, ограниченный
  `ready_for_execution`) без изменения статуса `Inspection`. Решения ОГС/ОТК,
  дефекты, файлы и журналы (Tasks 9D — 9G) пока не реализованы. Полная регрессия
  блока 9B — **854 passed**.
- **Task 9C — Method Execution and Results — реализована и принята.** Task 9C
  завершает ядро выполнения назначенных методов контроля и регистрации
  лабораторных заключений: lifecycle `MethodExecution`, локальные
  `MethodExecutionResultItem`, редакции выполнений и результатов без перезаписи
  истории, отдельный агрегат `LaboratoryConclusion` и его редакции, модель внешней
  лаборатории и `QualityExternalPerson`, снимок `LaboratoryAccreditation`,
  `quality_audit_events` и API. `LAB_CONFIRMED` подтверждает лабораторный результат
  или регистрацию внешнего документа и не является решением ОТК; `VERIFIED`
  зарезервирован для будущей проверки ОТК.
- **Post-9C (канон качества) — planned / not implemented.** Действующая
  реализационная структура — **9D-1 … 9D-8** (Session 008-07 / ADR-019, решение
  008-07-BO); историческая разбивка Session 008 на 9E — 9K — `SUPERSEDED_BY_TASK_9D`
  (см. следующий раздел). Логика импорта результатов НК **отсутствует** и в объём
  Session 008 не входит.

---

## Следующий этап — Решения по качеству, дефекты, ремонт и документы (Session 008)

> **Предусловие:** к Task 9D переходят **только после** принятия
> [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 008|Architecture Session 008]]
> и [[docs/project/DECISIONS#ADR-017. Quality Decision, Defect, Repair and Quality Documents Canon (Session 008)|ADR-017]].
> На Session 008 **код, миграции и тесты не создавались**; детальные ТЗ Tasks
> 9D — 9K в этом документе **не раскрываются**.

Канон: Session 008 (блоки 008-01 — 008-05) · ADR-017. Контур:
`Inspection Result → Quality Finding → Engineering Evaluation → Defect →
Quality Decision → Repair → Reinspection → Defect Closure`.

> **Пересмотр структуры (2026-07-16, решение 008-07-BO).** Приведённая ниже разбивка
> Session 008 на Tasks **9E — 9K** — **историческая** и **не** является действующей
> реализационной структурой. Официальной реализационной структурой является
> **9D-1 … 9D-8** (Session 008-07 / ADR-019); поглощённые части помечены
> `SUPERSEDED_BY_TASK_9D`, непоглощённый объём сохранён как будущие задачи. Полное
> соответствие — в разделе
> [«Соответствие старых Tasks 9E — 9K блокам 9D-1 … 9D-8»](#соответствие-старых-tasks-9e--9k-блокам-9d-1--9d-8-решение-008-07-bo).

| Task (историческая разбивка Session 008) | Содержание | Статус (008-07-BO) |
|------|-----------|--------------------|
| **9D — Quality Finding and Engineering Evaluation** | `Quality Finding`, инженерная оценка Finding, разделение `Inspection Result ≠ Finding ≠ Defect` | детализирован в **9D-1 … 9D-8** |
| **9E — Quality Decision Workflow** | решения ОГС/ОТК, разрешение разногласий главным сварщиком, override/отмена итога, версии и обоснование | `SUPERSEDED_BY_TASK_9D` → 9D-2 + 9D-4 + 9D-5 |
| **9F — Defect Core** | сущность `Defect`, жизненный цикл, подтверждение ОГС/ОТК, связь `Finding ↔ Defect` (многие-ко-многим) | `SUPERSEDED_BY_TASK_9D` → 9D-3 |
| **9G — Defect Cause, Severity and Localization** | причина и коренная причина, критичность, локализация, корректирующие действия, повторяемость, причинная связь с `WeldOperation` | частично `SUPERSEDED_BY_TASK_9D` → 9D-2 + 9D-3; остаток — будущий контур |
| **9H — Repair Core and Repair Planning** | `Repair`, план ремонта, версии, лимиты и зоны ремонтов | не поглощён; будущая задача (перенумерация после mapping table) |
| **9I — Repair Execution and Verification** | выполнение, остановки/возобновление, отклонения, подтверждения ОГС/ОТК, заключение по ремонту | не поглощён; будущая задача (перенумерация после mapping table) |
| **9J — Reinspection Integration** | повторный контроль, привязка к `Repair`, итог, автоматическое закрытие `Defect` | частично `SUPERSEDED_BY_TASK_9D` → 9D-6; фактическое выполнение — в Inspection Core |
| **9K — Quality Documents and Registry** | `Quality Document`, версии, владение, подписи, комплектность, реестр, экспорт | не поглощён; будущая задача (перенумерация после mapping table) |

**Блок 008-06 «Печатные формы»** завершён (2026-07-16) и зафиксирован в
[[docs/project/DECISIONS#ADR-018. Electronic Documents and Printed Forms Canon (Session 008-06)|ADR-018 — Electronic Documents and Printed Forms Canon]]
(Electronic Documentation Layer: document lifecycle, versioning, snapshots, audit
history, templates, official document issuance). Реализация документного слоя
(генераторы, макеты PDF, ЭП, публичный API проверки подлинности) — отдельными
задачами. **Детальная архитектура импорта результатов НК** остаётся открытой для
отдельной будущей архитектурной сессии.

**Зависимость Task 9D от ADR-018.** Task 9D (Quality Finding and Engineering
Evaluation) зависит от **ADR-018**: инженерная оценка качества должна ссылаться на
конкретные **редакции Official Document** (Document Revision), а не на изменяемые
данные.

**Статус реализации (2026-07-16):** канон качества (Session 008 / ADR-017, Session 008-07
/ ADR-019) — **planned / not implemented**; Session 008 фиксирует архитектурный канон
(ADR-017 — блоки 008-01 — 008-05; ADR-018 — блок 008-06). Действующая реализационная
структура — **9D-1 … 9D-8** (решение 008-07-BO); историческая разбивка 9E — 9K —
`SUPERSEDED_BY_TASK_9D` (см. таблицу соответствия ниже).

### Углублённая архитектура Task 9D (Session 008-07, ADR-019)

> **Статус архитектуры: approved** ([[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 008-07 — Quality Finding and Engineering Evaluation|Session 008-07]] ·
> [[docs/project/DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019]]).
> **Статус реализации: not started.** Модели, миграции, API и тесты **не создавались**.
> Детальные ТЗ подзадач в этом документе не раскрываются.

Session 008-07 углубляет **Task 9D** и разделяет ранее единое `Quality Decision` на три
решения (`EngineeringEvaluation` / `DefectAcceptanceAssessment` / `FindingDisposition`).
Контур:
`QualityFinding → EngineeringEvaluation → Defect / DefectAcceptanceAssessment →
FindingDisposition → ProductionHold → Corrective Action / Reinspection →
CustomerQualityDecision → Closure`. Утверждённая разбивка Task 9D:

| Подзадача | Содержание |
|-----------|-----------|
| **9D-1 — QualityFinding Core** | `QualityFinding`, `FindingLocation`, `FindingEvidence`, `FindingCorrection`, `FindingAssignment`, нумерация `<PROJECT_CODE>-QF-<SEQUENCE>`, register, acknowledge, базовый lifecycle |
| **9D-2 — Engineering Evaluation** | `EngineeringEvaluation`, ревизии, approval, `evaluation_outcome` (что установлено) + `recommended_disposition` (необязывающая рекомендация ОГС), `confirmed_severity`, `impact_scope`, `RequirementReference`, document applicability. Углублённый канон ядра — [[docs/project/DECISIONS#ADR-021. EngineeringEvaluation Core Canon (Task 9D-2)\|ADR-021]] (ревизионность, источники, критерии, `EngineeringException`). Решение **9D-2-C01**: `decision_type` разделён на `evaluation_outcome` + `recommended_disposition`; официальное исполняемое решение по finding — только `FindingDisposition` (9D-4), рекомендация оценки статус finding не меняет |
| **9D-3 — Defect Technical Model** | `Defect`, `DefectType`, `DefectMeasurement`, `DefectAcceptanceAssessment`, вычисляемый lifecycle, разделение `DefectLocation`/`RepairExcavationZone`/`RepairWeldZone` |
| **9D-4 — Finding Disposition and Holds** | `FindingDisposition`, corrective action authorization, `ProductionHold`, `ProductionHoldRelease`, вычисление quality state `Joint` |
| **9D-5 — Customer Quality Decision** | `CustomerQualityDecision`, внешний участник, внутренний регистратор, evidence, version history |
| **9D-6 — Corrective Action and Reinspection Links** | `CorrectiveActionLink`, `ReinspectionRequirement`, интеграция с repair/reweld/inspection, closure readiness |
| **9D-7 — API, permissions and integration** | API, RBAC, cross-module validation, integration tests |
| **9D-8 — Architecture consolidation** | финальная консолидация документации **после** реализации блоков |

**Первый объём Task 9D:** `QualityFinding`, `FindingLocation`, `FindingEvidence`,
`FindingCorrection`, `FindingAssignment`, `EngineeringEvaluation`, `RequirementReference`,
`Defect`, `DefectType`, `DefectMeasurement`, `DefectAcceptanceAssessment`,
`FindingDisposition`, `ProductionHold`, `ProductionHoldRelease`, `CustomerQualityDecision`,
`CorrectiveActionLink`, `ReinspectionRequirement`. **Не входят** (точки расширения без
пустых таблиц): `ResponsibilityAssessment`, `FindingPattern`, `CorrectivePreventiveAction`,
`ComplianceRule` и связанные сущности.

#### Соответствие старых Tasks 9E — 9K блокам 9D-1 … 9D-8 (решение 008-07-BO)

Разбивка **9D-1 … 9D-8** — **официальная реализационная структура**. Историческая
разбивка Session 008 на Tasks **9E — 9K** более **не** действует как параллельная
структура: поглощённые части помечены `SUPERSEDED_BY_TASK_9D`, непоглощённый
функциональный объём сохранён как будущие задачи и подлежит отдельной перенумерации
после утверждения этой таблицы.

| Старый Task (Session 008 / ADR-017) | Поглощён блоком 9D | Остаточный объём | Статус / будущая задача |
|-------------------------------------|--------------------|------------------|-------------------------|
| **9E — Quality Decision Workflow** | 9D-2 + 9D-4 + 9D-5 | — | `SUPERSEDED_BY_TASK_9D` (полностью) |
| **9F — Defect Core** | 9D-3 | — | `SUPERSEDED_BY_TASK_9D` (полностью) |
| **9G — Defect Cause / Severity / Localization** | частично 9D-2 (`confirmed_severity`, applicability) + 9D-3 (localization, measurement) | системный root cause; `ResponsibilityAssessment`; анализ повторяемости (`FindingPattern`) | частично `SUPERSEDED_BY_TASK_9D`; остаток — **будущий контур** Root Cause / Responsibility / Pattern (не входит в первый объём Task 9D) |
| **9H — Repair Core and Repair Planning** | — | полный ремонтный lifecycle, план ремонта, лимиты и зоны | **не поглощён**; будущая задача подлежит отдельной перенумерации после утверждения mapping table |
| **9I — Repair Execution and Verification** | — | выполнение, остановки/возобновление, отклонения, верификация ремонта | **не поглощён**; будущая задача подлежит отдельной перенумерации после утверждения mapping table |
| **9J — Reinspection Integration** | частично 9D-6 (`ReinspectionRequirement`, `CorrectiveActionLink`, closure readiness) | фактическое выполнение повторного контроля | частично `SUPERSEDED_BY_TASK_9D`; фактическое выполнение контроля остаётся в **Inspection Core** (Tasks 9A — 9C) |
| **9K — Quality Documents and Registry** | — | `Quality Document`, версии, владение, подписи, комплектность, реестр, экспорт | **не поглощён**; будущая задача подлежит отдельной перенумерации после утверждения mapping table (учитывать `Official Document` / ADR-018) |

> Непоглощённый функциональный объём (9H, 9I, 9K и остаток 9G) **не удаляется**;
> перенумерация остаточных будущих задач выполняется **отдельно** после утверждения
> этой таблицы. Решение зафиксировано в
> [[docs/project/DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019 (решение 008-07-BO)]].

**Следующий этап:** подготовка отдельного ТЗ на **Task 9D-1 — QualityFinding Core**
(после принятия архитектурной документации Session 008-07 / ADR-019).

---

## Самопроверка плана

| # | Критерий | Статус |
|---|----------|--------|
| 1 | Session 004 первый контур (Project→Line→Doc→Revision→Joint) | Покрыт Tasks 2–4 + 5A/5B/6/7 (Joint по ADR-010) |
| 2 | Нет WeldOperation, Inspection, Repair, HT | Да |
| 3 | Нет полноценной auth/JWT | Да — только X-User-Id + role check |
| 4 | Нет Excel-импорта | Да (bulk Task 7 — JSON, не Excel) |
| 5 | Нет HEAT_TREATMENT_OPERATOR | Да |
| 6 | Нет FK к WPS/МТО | Да — nullable без FK (Р-4) |
| 7 | PK/FK согласованы (IP-01) | Да — таблица в § IP-01 |
| 8 | Миграции линейны от `20260703_03_welder_admissions` | Да — § цепочка |
| 9 | Один Alembic head после Task 7 | Да — `20260711_08_joint_bulk_requests` |
| 10 | Каждый Task — тест + commit | Да — 8 commits (Tasks 1–4, 5A, 5B, 6, 7) |
| 11 | Нет TBD/TODO в плане | Да |
| 12 | ChatGPT — review; Claude Code — код; Cursor — среда/Git | Да — в шапке |
| 13 | Предметный термин ПТО соответствует техническому `role_code` `PTO_ENGINEER` (IP-07) | Да |
| 14 | Новый `role_code` `PTO`/`OGS` отсутствует | Да — используются `PTO_ENGINEER`/`OGS_ENGINEER` (Р-2) |
| 15 | Миграция не переименовывает `role_code` в данных `worker_roles` | Да |
| 16 | Типы массивов `ARRAY(Text)` и UUID определены однозначно | Да |
| 17 | Новая Revision привязывается через `POST .../set-current-revision` | Да — Task 6 (ADR-010) |
| 18 | Права документов и Joint проверяются по scope с `PTO_ENGINEER`/`OGS_ENGINEER` | Да — Tasks 4, 5A, 5B, 6 |
| 19 | Company/Project без выдуманного владельца роли | Да — только active Worker |
| 20 | Владелец Line — ПТО (`PTO_ENGINEER`); `FOREMAN`/`MASTER` не создают Line (IP-08) | Да — Task 3 |
| 21 | `LINE` scope не используется для POST Line (IP-08) | Да — Task 3 |
| 22 | Joint по ADR-010: двойное согласование ПТО/ОГС, `system_code`, снимки, bulk | Да — Tasks 5A/5B/6/7 |
| 23 | `scope_type` `ENGINEERING_DOCUMENT` добавлен аддитивно (COMPANY/SITE сохранены, Р-1) | Да — Task 5B |
| 24 | `ready_for_welding`/`missing_welding_requirements`/`production_state` сохранены (Б-4) | Да — Task 5A |
| 25 | `Joint.line_id` обязателен; согласование с nullable `document.line_id` (Б-3) | Да — Tasks 5A |

---

## Связанные документы

- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 004|Session 004]]
- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 005|Session 005]] (WeldOperation)
- [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API|ADR-009]]
- [[docs/project/DECISIONS#ADR-010. Joint MVP — расширенная модель, двойное согласование, история ревизий и bulk-импорт|ADR-010]] (принят — замещает Joint-часть ADR-009)
- [[docs/project/DECISIONS#ADR-012. WeldOperation как неизменяемый производственный факт сварки|ADR-012]] (принят — канон WeldOperation, Tasks 8A — 8F)
- [[docs/project/DECISIONS#ADR-014. Heat Treatment Integration (Task 8F)|ADR-014]] (принят — термическая обработка, Task 8F)
- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 007|Session 007]] (контроль качества и НК)
- [[docs/project/DECISIONS#ADR-015. Inspection and NDT Workflow Canon (Session 007)|ADR-015]] (принят — канон контроля/НК; Task 9C завершает ядро выполнения методов и лабораторных заключений)
- [[docs/project/DECISIONS#ADR-016. Quality Execution Model (Task 9C)|ADR-016]] (принят — модель выполнения контроля, Task 9C)
- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 008|Session 008]] · [[docs/project/DECISIONS#ADR-017. Quality Decision, Defect, Repair and Quality Documents Canon (Session 008)|ADR-017]] (принят, `PARTIALLY_SUPERSEDED_BY_ADR-019` — канон решений по качеству, дефектов, ремонта и документов; историческая разбивка 9E — 9K → `SUPERSEDED_BY_TASK_9D`)
- [[docs/project/ARCHITECTURE_SESSIONS#Блок 008-06 — Электронные документы и печатные формы (Electronic Documents and Printed Forms)|Session 008-06]] · [[docs/project/DECISIONS#ADR-018. Electronic Documents and Printed Forms Canon (Session 008-06)|ADR-018]] (принят — канон электронных документов и печатных форм; Task 9D ссылается на редакции Official Document)
- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 008-07 — Quality Finding and Engineering Evaluation|Session 008-07]] · [[docs/project/DECISIONS#ADR-019. Quality Finding and Engineering Evaluation Canon (Session 008-07)|ADR-019]] (принят — углублённая архитектура Task 9D; разбивка 9D-1 … 9D-8; реализация не начата)
- [[docs/ARCHITECTURE#5.3. Физическая модель БД и API Production/Joints MVP (Session 004)|ARCHITECTURE §5.3]]

*Версия плана: 2026-07-16 (Tasks 8A–8F и 9A–9C реализованы и приняты; Task 9C
завершает ядро выполнения назначенных методов контроля и регистрации лабораторных
заключений. Session 008 / ADR-017 (`PARTIALLY_SUPERSEDED_BY_ADR-019`) задала канон
post-9C; блок 008-06 «Печатные формы» завершён — ADR-018; Session 008-07 / ADR-019
(решение 008-07-BO) устанавливает действующую реализационную структуру Task 9D —
**9D-1 … 9D-8**, историческая разбивка 9E — 9K — `SUPERSEDED_BY_TASK_9D`, реализация не
начата). Задач: 17 реализованных (1–4, 5A, 5B, 6, 7, 8A–8F, 9A, 9B, 9C) +
Task 9D (блоки 9D-1 … 9D-8, planned / not implemented) + непоглощённый остаток 9H/9I/9K
(будущие задачи, перенумерация после утверждения mapping table).
Ветка: feature/engineering-joints-mvp.*
