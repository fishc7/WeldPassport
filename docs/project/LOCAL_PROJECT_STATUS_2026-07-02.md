# Отчёт о состоянии проекта WeldPassport

**Дата:** 2026-07-02  
**Ветка:** `feature/ok-workers-mvp`  
**Режим анализа:** только чтение, без изменений кода и без commit

---

## 1. Git-состояние

| Параметр | Значение |
|---|---|
| Текущая ветка | `feature/ok-workers-mvp` |
| Базовая ветка | `main` (ветка опережает main на 10 коммитов) |
| Стадия | Активная разработка модуля ОК / Работники; HR core закоммичен отдельным commit |

### Последние 5 коммитов

| Hash | Дата | Сообщение |
|---|---|---|
| `d94863e` | 2026-07-02 | docs: add WeldPassport design hubs and cross-links |
| `7e54dda` | 2026-07-02 | docs: add project governance and chat index |
| `e6b42ec` | 2026-07-01 | docs: prioritize workforce admission lifecycle |
| `f35e671` | 2026-07-01 | docs: accept backend architecture baseline |
| `e196773` | 2026-07-01 | gpt_00_2 |

### Незакоммиченные изменения

**Изменённые файлы (9):**

- `09_Разработка/backend/app/main.py` — подключение HR-роутера
- `09_Разработка/backend/app/shared/db.py` — поддержка схемы `hr`
- `09_Разработка/backend/app/workforce/repository.py`
- `09_Разработка/backend/app/workforce/schemas.py`
- `09_Разработка/backend/migrations/env.py` — регистрация HR-моделей
- `09_Разработка/backend/requirements.txt`
- `09_Разработка/desktop_ok/api.py` — доработки моста для десктопа ОК
- `09_Разработка/src/importers/ok1c_importer.py`
- `09_Разработка/src/importers/tabel_importer.py`

**Новые (untracked) файлы:**

- `09_Разработка/backend/app/hr/` — полный HR-модуль (api, models, schemas, repository, services)
- `09_Разработка/backend/migrations/versions/20260702_02_hr_core.py` — миграция схемы `hr`
- `09_Разработка/backend/tests/test_hr_schemas.py`
- `09_Разработка/src/importers/import_report.py`, `welder_roles.py`, `welder_titles.py`
- `10_Проектирование_WeldPassport/03_Работники_и_сварщики/03_HR_модуль_workers_v0.1.md`

**Вывод:** в Git зафиксированы документация и каркас backend (`workforce`), а текущая работа по новому HR-модулю ОК находится только на локальном диске.

---

## 2. Структура локального проекта

### Основные папки (корень `D:\WeldPassport`)

| Папка | Назначение |
|---|---|
| `docs/` | Каноничная документация (архитектура, контекст, governance) |
| `09_Разработка/` | Исполняемый код: `src/`, `backend/`, `frontend/`, `desktop_ok/`, `scripts/` |
| `10_Проектирование_WeldPassport/` | Рабочие материалы проектирования по темам |
| `03_База_данных/` | Реестр сущностей, модель организаций |
| `05_Роли_и_права/` | Роли, ТЗ ОК и ОГС, ролевая цепочка |
| `02_Процессы/` | Процессы сварки, НК |
| `07_Прототипы_экранов/` | Иконки ролей, favicon |
| `08_Справочники/` | Справочники сварки, нормативные документы |
| `00_Паспорт_проекта/` | Паспорт и манифест |
| `Context/` | Профиль владельца, предпочтения |
| `.cursor/`, `.claude/`, `.vscode/` | Настройки IDE и агентов |
| `.obsidian/` | Папка Obsidian (wiki-links в `.md` файлах) |

**Не анализировались:** `_archive/`, `.worktrees/`, `_Входящее/`

### Документация

- `docs/00_PROJECT_CONTEXT.md` — жизненный цикл, модули
- `docs/ARCHITECTURE.md` — архитектура MVP, модель данных, API
- `docs/project/` — DECISIONS, ROADMAP, PROJECT_SUMMARY, CHAT_INDEX
- `AGENTS.md` — единая инструкция для AI-агентов
- `00_НАВИГАЦИЯ.md` — корневой хаб навигации

### Backend / Frontend

| Компонент | Путь | Статус |
|---|---|---|
| FastAPI backend | `09_Разработка/backend/` | Каркас + модули `workforce` (в Git), `hr` (локально) |
| Legacy ORM | `09_Разработка/src/models/` | Модели на кириллических таблицах (`РАБОТНИКИ`, `СВАРЩИКИ` и др.) |
| React frontend | `09_Разработка/frontend/` | Vite + TS, демо-навбар, встроенный модуль ОК |
| Desktop ОК | `09_Разработка/desktop_ok/` | pywebview + JS UI, мост к `WorkforceService` |
| Скрипты БД | `09_Разработка/scripts/` | create_tables, импорт, проверки схемы (18 файлов) |

### Obsidian

Репозиторий использует wiki-links (`[[...]]`) в markdown-файлах. Папка `.obsidian/` присутствует в корне; отдельного vault вне репозитория в анализе не проверялся.

---

## 3. Что уже сделано

### Документация и governance

- Зафиксирована архитектура модульного монолита (`docs/ARCHITECTURE.md`)
- Принята модель `companies ↔ projects` через `project_companies`
- Описана ролевая цепочка ОК → ОГС → СМР → ПТО → ОТК → Закрытие
- Созданы хабы проектирования (`10_Проектирование_WeldPassport/`)
- ТЗ для ОК и ОГС, план реализации «Работники и сварщики»
- Реестр сущностей БД v0.1, модель организаций

### Код (закоммиченный)

- **Backend FastAPI** с модулем `workforce`:
  - ORM на legacy-таблицах `РАБОТНИКИ`, `СВАРЩИКИ`, документы, аттестации, допуски
  - CRUD API: `/api/v1/workers`, `/api/v1/welders` + read-only вложенные ресурсы сварщика
  - Слои: api → services → repository → SQLAlchemy
  - Заглушка auth: заголовок `X-User-Id`
- **Legacy ORM** в `src/models/`: workers, welders, production, projects, spravochniki
- **Alembic** настроен (`backend/migrations/env.py`), но ревизий в Git нет (только `.gitkeep`)
- **Скрипты**: создание таблиц, импорт сварщиков/табелей, проверка FK, seed должностей
- **Frontend**: React-оболочка с навбаром ролей и встроенным `OkModule`
- **Desktop ОК**: pywebview-приложение с UI и мостом к `WorkforceService`

### Код (локально, не в Git)

- **Новый HR-модуль** `backend/app/hr/` — целевая модель ОК в схеме PostgreSQL `hr`
- **Миграция** `20260702_02_hr_core.py` — `hr.departments`, `hr.positions`, `hr.workers`
- **Тесты** Pydantic-схем HR (без PostgreSQL)
- **Доработки импорта** табелей и 1С
- **Документ** `03_HR_модуль_workers_v0.1.md`

---

## 4. Документация

### Архитектурные документы

| Документ | Статус |
|---|---|
| `docs/ARCHITECTURE.md` | Есть, канон MVP |
| `docs/00_PROJECT_CONTEXT.md` | Есть |
| `docs/project/DECISIONS.md` | Есть (ADR) |
| `docs/project/ROADMAP.md` | Есть |
| `docs/project/PROJECT_SUMMARY.md` | Есть |
| `docs/db-schema.svg` | Есть (схема БД) |
| `10_Проектирование_WeldPassport/00_Навигация_проектирования.md` | Есть |

### По ролям

| Документ | Статус |
|---|---|
| `05_Роли_и_права/00_Ролевая_цепочка_ответственности.md` | Есть |
| `05_Роли_и_права/WeldPassport_Роли_пользователей_v0.1.md` | Есть |
| `05_Роли_и_права/01_ОК_.../WeldPassport_ОК_ТЗ_v0.1.md` | Есть |
| `05_Роли_и_права/05_Главный_сварщик_ОГС/...` | ТЗ, план, парсинг НАКС |

### По БД

| Документ | Статус |
|---|---|
| `03_База_данных/WeldPassport_Реестр_сущностей_БД_v0.1.md` | Есть |
| `03_База_данных/Модель_организаций_и_проектов.md` | Есть |
| `10_Проектирование_WeldPassport/03_.../01_Модель_данных_Работники_и_сварщики_v0.1.md` | Есть |
| `10_Проектирование_WeldPassport/03_.../02_План_реализации_...v0.1.md` | Есть (детальный план, большинство задач не выполнено) |
| `10_Проектирование_WeldPassport/03_.../03_HR_модуль_workers_v0.1.md` | Есть (локально, untracked) |

### По модулям (только проектирование, без кода)

| Тема | Документ | Код / миграции |
|---|---|---|
| ОК / Работники | ТЗ ОК, HR-модуль v0.1, план реализации | HR core в Git; legacy workforce в Git; проверка БД ещё не выполнена |
| Периодика КСС | `10_.../09_Периодика_КСС/00_Периодика_КСС.md` | Нет |
| Нормы времени | `10_.../10_Нормы_времени/00_Нормы_времени.md` | Нет |
| МТО | `10_.../11_МТО_и_материалы/00_МТО_и_материалы.md` | Нет |
| Исполнительная документация | `10_.../05_Исполнительная_документация/00_...md` | Нет |
| Фактическая сварка | `02_Процессы/Сварочные_операции.md` | Частично в `src/models/production.py` |

---

## 5. База данных

### Миграции

| Файл | Статус |
|---|---|
| `backend/migrations/env.py` | В Git, доработан локально под `hr` |
| `backend/migrations/versions/.gitkeep` | В Git (пусто) |
| `backend/migrations/versions/20260702_02_hr_core.py` | **Только локально** — создаёт схему `hr` и 3 таблицы |

Отдельных SQL-файлов (`.sql`) в репозитории **нет**.

### ORM-модели

| Слой | Расположение | Таблицы |
|---|---|---|
| Legacy (src) | `09_Разработка/src/models/` | `РАБОТНИКИ`, `СВАРЩИКИ`, `СПРАВОЧНИК_ДОЛЖНОСТЕЙ`, производство, проекты |
| Backend workforce | `backend/app/workforce/models.py` | Те же legacy-таблицы (дубликат для FastAPI) |
| Backend HR (новый) | `backend/app/hr/models.py` | `hr.departments`, `hr.positions`, `hr.workers` |

### Схемы PostgreSQL

| Схема | В коде / миграциях | Комментарий |
|---|---|---|
| `test` (или из `.env` `POSTGRES_SCHEMA`) | Да — legacy-таблицы | Основная рабочая схема через `create_tables.py` |
| `hr` | Да — миграция `20260702_02_hr_core` (локально) | Новая целевая схема ОК |
| `welding` | Нет | Только в архитектурных планах |
| `norms` | Нет | Описано в документации (`base_norms`, `org_norms`) |
| `periodic_kss` | Нет | Описано в документации (`kss_parties`) |

### Ключевые таблицы

| Таблица | Где | Статус |
|---|---|---|
| `workers` | `hr.workers` (миграция) | Описана, код готов, **не применена в Git** |
| `departments` | `hr.departments` | То же |
| `positions` | `hr.positions` | То же |
| `РАБОТНИКИ` | схема `test` | Создаётся скриптом, используется workforce + desktop_ok |
| `СВАРЩИКИ` | схема `test` | То же |

### Дублирование моделей

Сейчас сосуществуют **две параллельные модели работника**:

1. **Legacy** — `РАБОТНИКИ` (кириллица, одно поле ФИО, строковая организация)
2. **Целевая HR** — `hr.workers` (раздельные ФИО, `company_id`, статусы `active/dismissed/suspended`)

Связь между ними **не реализована**.

---

## 6. Backend

### FastAPI-приложение

- Точка входа: `09_Разработка/backend/app/main.py`
- В **Git**: подключён только `workforce_router` (`/api/v1`)
- **Локально**: добавлен `hr_router` (`/api/v1/hr`)

### Endpoints

#### Workforce (в Git) — prefix `/api/v1`

| Метод | Путь | Назначение |
|---|---|---|
| GET/POST/PATCH | `/workers`, `/workers/{id}` | CRUD legacy-работников |
| GET/POST/PATCH | `/welders`, `/welders/{id}` | CRUD сварщиков |
| GET | `/welders/{id}/documents` | Документы сварщика |
| GET | `/welders/{id}/certifications` | Аттестации |
| GET | `/welders/{id}/admissions/internal` | Внутренние допуски |
| GET | `/welders/{id}/admissions/site` | Допуски к объекту |

#### HR (локально) — prefix `/api/v1/hr`

| Метод | Путь | Назначение |
|---|---|---|
| GET/POST/PATCH | `/departments`, `/departments/{id}` | Подразделения |
| GET/POST/PATCH | `/positions`, `/positions/{id}` | Должности |
| GET/POST/PATCH | `/workers`, `/workers/{id}` | Работники (целевая модель) |
| POST | `/workers/{id}/dismiss`, `/activate` | Увольнение / активация |

**Конфликт маршрутов:** оба модуля экспонируют `/workers` на разных префиксах (`/api/v1/workers` vs `/api/v1/hr/workers`).

### Pydantic-схемы

- `backend/app/workforce/schemas.py` — Rabotnik, Svarshchik, документы, допуски
- `backend/app/hr/schemas.py` — Department, Position, Worker (полный набор)

### Сервисы и репозитории

| Модуль | Service | Repository | Статус |
|---|---|---|---|
| workforce | `WorkforceService` | `RabotnikRepo`, `SvarshchikRepo` | В Git, рабочий слой |
| hr | `HrService` | `HrRepo` | Локально, полный CRUD + бизнес-правила |

### Тесты

- `backend/tests/test_hr_schemas.py` — 3 unit-теста Pydantic (локально)
- Интеграционных тестов API/БД для HR **нет**
- План в `02_План_реализации_...` предусматривает pytest + Alembic — **не выполнен**

### Auth

Заглушка: `X-User-Id` в заголовке (`app/shared/auth.py`). RBAC не реализован.

---

## 7. Модуль ОК / Работники

### Файлы с упоминаниями worker / hr / ОК

**Backend (целевой HR):**

- `backend/app/hr/` — api, models, schemas, repository, services

**Backend (legacy workforce):**

- `backend/app/workforce/` — api, models, schemas, repository, services

**Legacy ORM и импорт:**

- `src/models/workers.py`, `src/models/welders.py`
- `src/importers/tabel_importer.py`, `ok1c_importer.py`, `welder_roles.py`, `welder_titles.py`
- `scripts/import_welders.py`, `collect_tabeli.py`, `backfill_svarshchiki.py`

**Desktop / Frontend:**

- `desktop_ok/api.py`, `desktop_ok/web/app.js` — UI ОК
- `frontend/src/App.tsx`, `OkModule` — встраивание desktop_ok

**Документация:**

- `05_Роли_и_права/01_ОК_.../WeldPassport_ОК_ТЗ_v0.1.md`
- `10_Проектирование_WeldPassport/03_Работники_и_сварщики/` (3 документа)

### Что уже реализовано (код)

| Компонент | Реализация | Где используется |
|---|---|---|
| Legacy CRUD работников | Да | workforce API, desktop_ok |
| Legacy CRUD сварщиков | Да (частично read для допусков) | workforce API |
| HR CRUD departments/positions/workers | Да (код) | Только FastAPI, **не desktop_ok** |
| Импорт табелей Excel | Да | desktop_ok, scripts |
| UI рабочего места ОК | Да (базовый) | desktop_ok + frontend |
| Миграция `hr` | Файл есть | Не в Git, применение не подтверждено |

### Что только в документации

- Нормализация ФИО, поиск дублей, merge карточек
- Модель `persons` / `employments` из плана реализации
- Модуль `companies` и FK на `company_id`
- Кадровые документы работника (в ТЗ ОК)
- RBAC для роли ОК
- Связь legacy `РАБОТНИКИ` ↔ `hr.workers`

### Чего не хватает для первого рабочего CRUD (целевая модель `hr`)

1. **Применить миграцию** HR-модуля и проверить CRUD через FastAPI
2. **Применить миграцию** `alembic upgrade head` на PostgreSQL
3. **Переключить desktop_ok** с `WorkforceService` на `HrService` (или прокси-слой)
4. **Интеграционные тесты** с реальной БД
5. **Модуль companies** — сейчас `company_id` без FK
6. **Согласовать** судьбу legacy `РАБОТНИКИ` (миграция данных или параллельная работа)
7. **DELETE** endpoints отсутствуют (только soft через dismiss) — по ТЗ это допустимо
8. **Поиск** по ФИО в HR API есть (`search` query param), но UI desktop_ok пока на legacy

### Завершён ли модуль Работники?

**Нет.** Модуль находится в состоянии **перехода**:

- Legacy-слой (`workforce` + `desktop_ok`) — **работает на старых таблицах**, даёт базовый CRUD
- Целевой HR-слой (`hr`) — **код написан локально**, но не интегрирован, не в Git, миграция не зафиксирована
- Документация и план реализации опережают код (people core, welder qualifications — не сделаны)

---

## 8. Что готово

| Область | Готовность |
|---|---|
| Архитектурная документация | Высокая |
| Governance (ADR, roadmap, agents) | Высокая |
| ТЗ ролей ОК и ОГС | Есть v0.1 |
| Backend-каркас FastAPI | Есть |
| Legacy workforce API + ORM | Рабочий каркас в Git |
| HR API + ORM + миграция | Код готов локально, не завершён цикл |
| Desktop ОК (прототип) | Базовый UI + импорт табелей |
| Frontend React | Оболочка + встраивание ОК |
| Импорт Excel (табели, 1С) | Скрипты и доработки |
| Alembic | Настроен, первая ревизия только локально |
| Производственные модули (стыки, НК, КСС) | Только документация и частичные ORM |

---

## 9. Что не завершено

1. **Два источника истины** по работникам (legacy vs `hr`) без стратегии миграции
2. **HR-модуль уже в Git**, но ещё не прошёл проверку миграции и интеграционное тестирование на БД
3. **Миграции Alembic** — в Git пустая папка versions (кроме локального файла)
4. **Модуль companies** — не реализован
5. **План реализации v0.1** (people core, duplicates, eligibility) — не начат в коде
6. **ОГС / допуски** — API read-only для legacy, нет команд проверки допуска
7. **Identity / RBAC** — заглушка
8. **Frontend** — только ОК, остальные роли — заглушки
9. **Docker, CI/CD, деплой** — не реализованы
10. **Схемы welding, norms, periodic_kss** — только в документации

---

## 10. Риски

| Риск | Описание | Критичность |
|---|---|---|
| Дублирование модели работника | `РАБОТНИКИ` и `hr.workers` без связи | Высокая |
| Незакоммиченный код | Потеря при сбое, нет истории решений | Средняя |
| desktop_ok на legacy | UI не использует целевой HR API | Высокая |
| `company_id` без FK | Нет валидации организации на уровне БД | Средняя |
| Два `/workers` endpoint | Путаница для клиентов API | Средняя |
| План реализации vs факт | План описывает `people.py`, миграции 20260624 — не созданы | Средняя |
| Auth-заглушка | Нет реальной безопасности | Низкая для dev, высокая для prod |
| Кириллические имена таблиц | Технический долг, усложняет миграцию | Средняя |

---

## 11. Рекомендуемый следующий этап

### Приоритет: завершить ОК → Работники, затем ОГС → допуски

По ролевой цепочке и ТЗ:

- **ОК** создаёт и ведёт карточку работника
- **ОГС** выдаёт сварочные допуски, аттестации, клейма

Переход к полноценным допускам ОГС **до стабилизации HR-модуля ОК** создаст зависимость сварщика от нестабильной базовой сущности.

### Конкретные шаги (1–2 спринта)

1. **Зафиксировать решение** legacy vs `hr` в `docs/project/DECISIONS.md` (миграция или bridge-таблица)
2. **HR core уже закоммичен**; следующий шаг — применить миграцию и проверить API
3. **Применить миграцию** и проверить CRUD через Swagger (`/docs`)
4. **Перевести desktop_ok** на `HrService` для списка/карточки/приёма/увольнения
5. **Добавить интеграционные тесты** HR API
6. **Минимальный модуль companies** (таблица + FK) или явный seed `company_id=1`
7. **После стабильного CRUD работников** — слой ОГС: связь `hr.workers` → `welder_profile`, команды допуска

### Можно ли переходить к ОГС → сварочные допуски?

**Частично.** Read-only API по legacy-сварщикам уже есть, но для production-ready допусков нужно:

- стабильный `worker_id` из `hr.workers`;
- разделение «работник ОК» и «профиль сварщика ОГС»;
- команды проверки допуска (не просто CRUD).

**Рекомендация:** сначала закрыть MVP CRUD ОК на схеме `hr`, затем строить ОГС поверх `hr.workers`.

---

## Приложение: просмотренные ключевые файлы

### Git и навигация

- `AGENTS.md`, `00_НАВИГАЦИЯ.md`
- `docs/ARCHITECTURE.md`, `docs/00_PROJECT_CONTEXT.md`
- `docs/project/ROADMAP.md`, `PROJECT_SUMMARY.md`, `DECISIONS.md`

### База данных

- `03_База_данных/WeldPassport_Реестр_сущностей_БД_v0.1.md`
- `09_Разработка/backend/migrations/versions/20260702_02_hr_core.py`
- `09_Разработка/backend/migrations/env.py`
- `09_Разработка/src/models/workers.py`

### Backend

- `09_Разработка/backend/app/main.py`
- `09_Разработка/backend/app/hr/` (api, models, schemas, services, repository)
- `09_Разработка/backend/app/workforce/` (api, models, schemas, services, repository)
- `09_Разработка/backend/app/shared/auth.py`, `db.py`
- `09_Разработка/backend/tests/test_hr_schemas.py`

### ОК / Desktop / Frontend

- `09_Разработка/desktop_ok/api.py`
- `05_Роли_и_права/01_ОК_Отдел_кадров/ТЗ/WeldPassport_ОК_ТЗ_v0.1.md`
- `10_Проектирование_WeldPassport/03_Работники_и_сварщики/` (01, 02, 03)
- `09_Разработка/frontend/src/App.tsx`

### Проектирование смежных модулей

- `10_Проектирование_WeldPassport/09_Периодика_КСС/00_Периодика_КСС.md`
- `10_Проектирование_WeldPassport/10_Нормы_времени/00_Нормы_времени.md`
- `10_Проектирование_WeldPassport/11_МТО_и_материалы/00_МТО_и_материалы.md`
- `10_Проектирование_WeldPassport/05_Исполнительная_документация/00_Исполнительная_документация.md`






