# WeldPassport — реестр Tasks (TASK_REGISTRY)

> Связанные документы: [[docs/project/ARCHITECTURE_GOVERNANCE|Architecture Governance (AGF)]] ·
> [[docs/project/DECISIONS|ADR]] · [[docs/project/implementation-decisions/README|Implementation Decisions]] ·
> [[docs/project/PROJECT_STATUS.yaml|PROJECT_STATUS.yaml]] · [[docs/project/PROJECT_SUMMARY|PROJECT_SUMMARY]] ·
> [[docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP|Implementation Plan]].

## Назначение

Единый реестр **Task** — уровня «Task / Implementation Specification» между Architecture
(ADR) и Code (см. [[docs/project/ARCHITECTURE_GOVERNANCE#2. Уровни управления архитектурой|AGF §2]]).

Этот файл — единственный канонический источник **текущего статуса реализации** по Tasks.
Поля «Статус реализации» внутри ADR — точечные снимки на дату принятия ADR и **не
обновляются задним числом** (см. [[docs/project/DECISIONS|DECISIONS.md]], правило
неперезаписи истории); актуальный статус смотреть здесь.

Канон наименований (`Task 9D`, `Task 9D-4A-4`, `Session 008`, `ADR-019`,
`Implementation Decision`, `Commit`) — [[docs/project/ARCHITECTURE_GOVERNANCE#9. Канон наименований|AGF §9]].

## Легенда статусов

| Статус | Значение |
|---|---|
| `done` | код, миграции, тесты реализованы и закоммичены |
| `in_progress` | часть подблоков реализована, часть — в работе |
| `planned` | архитектурный канон принят (ADR), реализация не начата |
| `not_designed` | архитектурное решение ещё не принято |

## Engineering — Tasks 1–7 (Company / Project / Line / EngineeringDocument / Joint)

| Task | Название | Архитектурное основание | Статус | Ключевой commit |
|---|---|---|---|---|
| Task 1 | MASTER и scoped role check | [[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)\|ADR-008]] / [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API\|ADR-009]] — частичное архитектурное основание для роли `MASTER`; scoped role mechanism — **LEGACY, до введения обязательного ADR**, детализирован [[docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP#Task 1 — MASTER и scoped role check\|Implementation Plan, Task 1]] | `done` | `e0dea82`/`6a7a0fc` (2026-07-10) |
| Task 2 | Company, Project, `project_companies` | [[docs/project/DECISIONS#ADR-001. Модель организаций и проектов\|ADR-001]] / [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API\|ADR-009]] | `done` | `e0dea82` (2026-07-10) |
| Task 3 | Line | [[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)\|ADR-008]] / [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API\|ADR-009]] | `done` | `6a7a0fc` (2026-07-10) |
| Task 4 | EngineeringDocument, DocumentRevision | [[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)\|ADR-008]] / [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API\|ADR-009]] | `done` | `6d2ea09` (2026-07-10) |
| Task 5A | Joint Core | ADR-010 | `done` | `eecffc2` (2026-07-11) |
| Task 5B | Joint Review Lifecycle | ADR-010/011 | `done` | `eecffc2` (2026-07-11) |
| Task 6 | Joint ↔ DocumentRevision History | ADR-010/011 | `done` | `eecffc2` (2026-07-11) |
| Task 7 | Bulk Joint Import | ADR-010/011 | `done` | `eecffc2` (2026-07-11) |

Спецификация: [[docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP|IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md]] (Tasks 1–7).

Tasks 1–4 выполнены до введения 2026-07-21 обязательного правила архитектурного основания
в AGF. Фиктивные ADR им не назначаются: в таблице указаны существовавшие к моменту
реализации ADR-001/008/009 и утверждённый Implementation Plan, который декомпозировал их
в Tasks 1–4.

## WeldOperation — Tasks 8A–8F (ADR-012/013/014, Architecture Session 005/006)

| Task | Название | ADR | Статус | Ключевой commit |
|---|---|---|---|---|
| Task 8A | WeldOperation Core | ADR-012 | `done` | `b08cd0a` (2026-07-12) |
| Task 8B | Допуск и WPS | ADR-012 | `done` | `b08cd0a` (2026-07-12) |
| Task 8C | Review ОГС | ADR-012 | `done` | `b08cd0a` (2026-07-12) |
| Task 8D | Корректировки (`WeldOperationCorrection`) | ADR-012 | `done` | `b08cd0a` (2026-07-12) |
| Task 8E | Импорт Excel | ADR-013 | `done` | `b08cd0a` (2026-07-12) |
| Task 8F | Термическая обработка | ADR-014 | `done` | `992a2f4` (2026-07-13) |

## Quality Execution Core — Tasks 9A–9C (ADR-015/016, Architecture Session 007)

| Task | Название | ADR | Статус | Ключевой commit |
|---|---|---|---|---|
| Task 9A | Inspection Core (заявка/мероприятие, lifecycle) | ADR-015 | `done` | `a369a7e` (2026-07-13) |
| Task 9B | Method Assignment (назначение методов) | ADR-015 | `done` | `160186c` (2026-07-14) |
| Task 9C | Method Execution, `LaboratoryConclusion`, Quality Audit, API | ADR-016 | `done` | `7eec0db` (2026-07-15) |

## Task 9D — Quality / Defect Management (ADR-019, Architecture Session 008-07)

Действующая реализационная структура — **9D-1 … 9D-8** (решение 008-07-BO в ADR-019).
Историческая разбивка Session 008 на 9E–9K — `SUPERSEDED_BY_TASK_9D`.

| Task | Название | ADR / Implementation Decision | Статус | Ключевой commit |
|---|---|---|---|---|
| Task 9D-1 | `QualityFinding` Core | ADR-019 | `done` | `57cd921` (2026-07-19) |
| Task 9D-2A | `EngineeringEvaluation` core & migration | ADR-021 | `done` | `fe42669` (2026-07-19) |
| Task 9D-2B | Evaluation sources & criteria | ADR-021 | `done` | `ca04fe4` (2026-07-19) |
| Task 9D-2C | Exceptions & completeness validation | ADR-021 | `done` | `166181e` (2026-07-19) |
| Task 9D-2D | Evaluation lifecycle service & API | ADR-021 | `done` | `7bcb38c` (2026-07-19) |
| Task 9D-2E | Evaluation hardening | ADR-021 | `done` | `57cdd3e` (2026-07-20) |
| Task 9D-3A | Defect Technical Model (модель, миграция) | ADR-022 | `done` | `8e0ae4c` (2026-07-20) |
| Task 9D-3B | Defect supersede workflow/services | ADR-022 + [[docs/project/ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING|ADR-022 Addendum D-3B-S01]] | `done` | `e9c6f7f` (2026-07-20) |
| Task 9D-3C | Defect API и reference-сервисы | ADR-022 | `done` | `18f3899` (2026-07-20), тесты `6ae5abd` |
| Task 9D-4A-2 | `DefectDisposition` — модель хранения (данные) | ADR-023 | `done` | входит в `dfaa87b` (2026-07-21) |
| Task 9D-4A-3 | `DefectDisposition` — approve/activate authority | [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 (ACCEPTED)]] + [[docs/project/implementation-decisions/9D-4A-3-disposition-approve-activate-roles|Implementation Decision 9D-4A-3]] | `in_progress` | исходная реализация `dfaa87b` (2026-07-21); [[docs/project/TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC|alignment spec 9D-4A-5]] — draft; bugfix не начат |
| Task 9D-4A-4 | `DefectDisposition` — activate-time replacement | [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 (ACCEPTED)]] + [[docs/project/implementation-decisions/9D-4A-4-disposition-supersede-workflow|Implementation Decision 9D-4A-4]] | `in_progress` | исходная supersede-time реализация `d3a6d87` (2026-07-21); [[docs/project/TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC|alignment spec 9D-4A-5]] — draft; bugfix не начат |
| Task 9D-4A-5 | `DefectDisposition` — ADR-024 Alignment | [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 (ACCEPTED)]] + [[docs/project/TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC|Implementation Specification 9D-4A-5]] | `planned` | spec `DRAFT — awaiting independent review`; execution blocked by B-03, B-04, TEST-DB-FOUNDATION and authentication boundary; implementation/commit pending |
| Task 9D-4 (остаток) | `ProductionHold` / `ProductionHoldRelease`, вычисляемый quality state Joint | ADR-019 | `planned` | — |
| Task 9D-5 | Customer Quality Decision | ADR-019 | `planned` | — |
| Task 9D-6 | Corrective Action and Reinspection Links | ADR-019 | `planned` | — |
| Task 9D-7 | API, permissions и интеграция контура 9D | ADR-019 | `planned` | — |
| Task 9D-8 | Architecture consolidation Task 9D | ADR-019 | `planned` | — |

Спецификации: [[docs/project/TASK_9D-2_ENGINEERING_EVALUATION_SPEC|TASK_9D-2_ENGINEERING_EVALUATION_SPEC.md]] ·
[[docs/project/TASK_9D-2_CLAUDE_CODE_PROMPT|TASK_9D-2_CLAUDE_CODE_PROMPT.md]] ·
[[docs/project/TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC|TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC.md]] ·
[[docs/project/TASK_9D-3C_DEFECT_API_INTEGRATION_SPEC|TASK_9D-3C_DEFECT_API_INTEGRATION_SPEC.md]] ·
[[docs/project/TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC|TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC.md]].

## Infrastructure prerequisites — Migration Governance (ADR-025, Session 010)

| Task | Название | Архитектурное основание | Статус | Ключевой commit |
|---|---|---|---|---|
| B-03 | Migration Foundation | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] | `not_designed` | ожидает отдельной Implementation Specification; готовит canonical migration environment, не переносит version marker и не меняет runtime; spec/commit отсутствуют |
| B-04 | Canonical Baseline Adoption | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] | `not_designed` | ожидает приёмки B-03 и отдельной Implementation Specification; единственный владелец version marker transfer, baseline stamp и adoption; spec/commit отсутствуют |
| RUNTIME-LEGACY-COMPATIBILITY-PROFILE | Canonical/Legacy Runtime Composition | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] | `not_designed` | ожидает отдельной Implementation Specification; владеет `main.py` composition, config/profile switch, preflight и legacy router loading; spec/commit отсутствуют |
| TEST-DB-FOUNDATION | Isolated PostgreSQL Test Database Foundation | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] | `not_designed` | ожидает приёмки B-04 и отдельной Implementation Specification; application-test acceptance также зависит от runtime profile Task; spec/commit отсутствуют |

Основной execution gate: `ADR-025 → B-03 → B-04 → TEST-DB-FOUNDATION → Task 9D-4A-5A`.
Параллельная ветвь: `ADR-025 → RUNTIME-LEGACY-COMPATIBILITY-PROFILE → canonical application
acceptance / TEST-DB application tests`. После принятия ADR все четыре Tasks остаются
`not_designed`; code fix запрещён без отдельной Implementation Specification и приёмки
предыдущих зависимостей.

## Electronic Documentation Layer (ADR-018, Session 008-06)

| Task | Название | ADR | Статус | Ключевой commit |
|---|---|---|---|---|
| — | Document lifecycle, versioning, snapshots, templates | ADR-018 | `planned` | — |

## Project Control Center (служебный контур, не Task WeldPassport)

| Блок | Название | ADR | Статус | Ключевой commit |
|---|---|---|---|---|
| — | Первый рабочий срез (`09_Разработка/project_control/`) | ADR-020 | `in_progress` | `e793104` (мерж `5aceb0d`) |

## Правило ведения реестра

1. Новая строка добавляется **в тот же коммит**, где Task переходит в `done` (правило
   «решение → реализация → тесты → commit», [[docs/project/PROJECT_DASHBOARD|PROJECT_DASHBOARD]]).
2. Статус `done` в этом файле требует наличия кода/миграции/тестов; наличия только ADR —
   недостаточно (тогда статус — `planned`).
3. Этот файл не переписывает ADR и не заменяет [[docs/project/DECISIONS|DECISIONS.md]] —
   он агрегирует ссылки на них.
4. **Bootstrap-исключение (2026-07-21).** Первоначальное заполнение реестра выполняется
   ретроспективно: исторические строки могут ссылаться на уже существующие commits.
   Требование добавлять/обновлять строку в implementation commit применяется только к
   новым Tasks после вступления `TASK_REGISTRY.md` в силу 2026-07-21.
