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
| `accepted_uncommitted` | scoped Diff реализован и принят свежими проверками, но commit ещё отсутствует |
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
| Task 9D-4A-5 | `DefectDisposition` — ADR-024 Alignment | [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model|ADR-024 (ACCEPTED)]] + [[docs/project/TASK_9D-4A-5_DEFECT_DISPOSITION_ADR024_ALIGNMENT_SPEC|Implementation Specification 9D-4A-5]] | `planned` | B-03 и B-04 завершены; spec `DRAFT — awaiting independent review`; execution ожидает TEST-DB-FOUNDATION, Runtime Compatibility Profile и authentication boundary; implementation/commit pending |
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

## QualityDecision Core — Task 10A (ADR-027)

| Task | Название | Архитектурное основание | Статус | Evidence / примечание |
|---|---|---|---|---|
| Task 10A-R | Governance Recovery | [[docs/project/ADR-027-quality-decision-core-canon|ADR-027 + Recovery Addendum]] + [[docs/project/TASK_10A_QUALITY_DECISION_CORE_RECOVERY_SPEC|Recovery Specification]] | `done` | recovery принят и синхронизирован 2026-07-24; `c1b551e` |
| Task 10A-1 | Models + Migration | ADR-027 | `done` | модели и revision 25 приняты свежими contract/metadata/graph проверками; `c1b551e` |
| Task 10A-1R | Idempotency Model + Correcting Migration | ADR-027 Addendum L.2 | `done` | отдельная таблица records и self-contained revision 26; migration 25 не изменена; `c1b551e` |
| Task 10A-2 | Workflow + Repository + Service | ADR-027 | `done` | lifecycle/RBAC/scope/supersede/audit regression suite пройден; `c1b551e` |
| Task 10A-2R | Submit Snapshot + Idempotency Orchestration | ADR-027 Addendum L.1/L.2 | `done` | SUBMIT history, replay/conflict/rollback/concurrency и stable response snapshot проверены; `c1b551e` |
| Task 10A-3 | Schemas + Command API + API Tests | ADR-027 + Recovery Specification | `done` | thin command API и полный API lifecycle/replay/errors пройдены; `c1b551e` |

AS-02 в Task 10A не входит; отдельное архитектурное решение принято в ADR-028.

## QualityDecision RBAC Consolidation — AS-02 (ADR-028)

| Task | Название | Архитектурное основание | Статус | Evidence / примечание |
|---|---|---|---|---|
| AS-02A | Architecture and implementation planning | [[docs/project/ADR-028-quality-decision-rbac-consolidation|ADR-028]] | `done` | person-level SoD, AuthorizationGrant, audit context, dual-role warning, migration/backfill contract и exact implementation prompt приняты 2026-07-24 |
| AS-02B | Domain Model + Correcting Migration | ADR-028 + [[docs/project/TASK_AS_02_QUALITY_DECISION_RBAC_IMPLEMENTATION_PLAN|Implementation Plan]] | `done` | Domain Model и self-contained revision 27 приняты; revisions 25/26 не изменены; migration governance `35 passed` |
| AS-02C | Resolver + Workflow + Service + API | ADR-028 + Implementation Plan | `done` | evidence-bearing resolver, SoD, audit context, dual-role warning и additive API реализованы TDD; focused regression `100 passed` |
| AS-02D | PostgreSQL acceptance + regression + documentation closure | ADR-028 + Implementation Plan | `done` | схема `test` на head 27; rehearsal `27 → 26 → 27`; полный backend regression `1590 passed`; документация синхронизирована 2026-07-24 |

## Infrastructure prerequisites — Migration Governance (ADR-025, Session 010)

| Task | Название | Архитектурное основание | Статус | Ключевой commit |
|---|---|---|---|---|
| B-03 | Migration Foundation | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] + [[docs/project/TASK_B-03_MIGRATION_FOUNDATION_SPEC|Implementation Specification B-03]] | `done` | `fc2faad` → `939ab1f` → `893707f` → `f584525` → `5bee400` → `d73bea9` (2026-07-22); реализация, remediation и closure evidence завершены, closure verified 2026-07-22 (см. [[docs/project/TASK_B-03_MIGRATION_FOUNDATION_SPEC#23. Closure Evidence\|Closure Evidence]]); baseline, marker move и runtime changes не выполнялись; B-04 и TEST-DB Foundation не входят |
| TEST-DB-SAFETY-INTERLOCK | Fail-closed защита integration pytest до подключения и Alembic | [[docs/project/ADR-029-test-db-safety-interlock|ADR-029 (ACCEPTED)]] + [[docs/project/TASK_TEST_DB_SAFETY_INTERLOCK_SPEC|Implementation Specification]] | `done` | `2046384` (2026-07-24); focused pure contracts `10 passed`; полный `migration_contract_tests` `45 passed`; PostgreSQL/Alembic/application tests не запускались; не заменяет TEST-DB Foundation |
| B-04 | Canonical Baseline Adoption | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] + [[docs/project/ADR-030-postgresql-18-b04-evidence-versioning|ADR-030 (ACCEPTED)]] + [[docs/project/ADR-031-b04-dual-state-live-restore-evidence|ADR-031 (ACCEPTED)]] + [[docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC|Implementation Specification B-04]] | `done / ADOPTION_ACCEPTED` | B-04A-R18, B-04R, repository cut, isolated rehearsal и production adoption завершены 2026-07-30; postflight `405e82ae709b2cc051c25ad3bd139614f53996a2bcfcad1d50f6f11560fc2403`; owner acceptance `c257b1b4736ac53be731d7de8369d45808cd4eeba1af569534272a3a4dca3b56`; migration freeze released |
| B-04A | Canonical Baseline Build & Verification — PostgreSQL 16 historical evidence | ADR-025 + [[docs/project/TASK_B-04A_BASELINE_BUILD_VERIFICATION_IMPLEMENTATION_PLAN|Implementation Plan B-04A]] | `done / historical_non_authorizing` | implementation `4487127a3042cf6a8ba003b85cffd143dc920f0e`; source `6c56f99edbd4e7346264ee14658d2076b5fd0775`; PostgreSQL 16.14; 73 tables; 15 seeds; fingerprint v1 `ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6`; evidence не разрешает PG18 adoption |
| B-04A-R18 | PostgreSQL 18 Re-verification | [[docs/project/ADR-030-postgresql-18-b04-evidence-versioning|ADR-030 (ACCEPTED)]] + [[docs/project/TASK_B-04A_R18_POSTGRESQL_18_REVERIFICATION_SPEC|Specification (ACCEPTED)]] + [[docs/project/TASK_B-04A_R18_POSTGRESQL_18_REVERIFICATION_IMPLEMENTATION_PLAN|Implementation Plan]] | `done / active_authorizing` | accepted 2026-07-29; implementation `f5245ba80698bdddfc64d2071061c2299a1c20f8`; evidence `b34538f5ddd4ed31d8094bc5d96f42ada7d1f28d`; PostgreSQL 18.3; fingerprint v2 `e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a`; report `B04A_VERIFIED`; `314 passed, 1 skipped`; working DB не подключалась |
| B-04R | PostgreSQL 18 Restore-Roundtrip Evidence | [[docs/project/ADR-031-b04-dual-state-live-restore-evidence|ADR-031 (ACCEPTED)]] + [[docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_SPEC|Specification (ACCEPTED)]] + [[docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_IMPLEMENTATION_PLAN|Implementation Plan (ACCEPTED)]] + [[docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_SPEC|Candidate-State Test Remediation Spec (PROMOTED)]] + [[docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_IMPLEMENTATION_PLAN|Test Remediation Plan (PROMOTED)]] + [[docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_CLAUDE_CODE_PROMPT|Test Remediation Prompt (PROMOTED)]] | `done / active_restore_authorizing` | implementation SHA `1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b` accepted; evidence promoted 2026-07-29T08:55:32Z by `repository_owner`; report SHA `5480a2e4e02a085f8378ee9617da0b9ad4c04aca4a42fd0a52b933b4b75554be`; promotion commit `abaada5aad7e53d94c00395adb1a0ff742c27dd5` accepted; fresh readiness suite `379 passed, 1 skipped` |
| B-04B | Repository Cut, Maintenance and Adoption | ADR-025 + ADR-030 + ADR-031 + [[docs/project/TASK_B-04B_CUT_MAINTENANCE_ADOPTION_IMPLEMENTATION_PLAN|Implementation Plan B-04B]] | `done / ADOPTION_ACCEPTED` | tooling `1a84d566311f1cb679a84e851596f95b1053e144`; `604 passed, 2 skipped`; backup `9c5e72aca5d0d95cf80d8dc4df4d7fe9d3ca458db3056e4e9ce9045a6856288c`; marker `canonical_baseline_v1`; owner acceptance 2026-07-30T03:34:25Z; freeze released |
| RUNTIME-LEGACY-COMPATIBILITY-PROFILE | Canonical/Legacy Runtime Composition | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] + [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032 (ACCEPTED)]] + [[docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_SPEC|Implementation Specification (ACCEPTED)]] + [[docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_IMPLEMENTATION_PLAN|Implementation Plan (ACCEPTED)]] + [[docs/project/TASK_RUNTIME_LEGACY_COMPATIBILITY_PROFILE_CLAUDE_CODE_PROMPT|Cursor / Claude Code Prompt (ACCEPTED)]] | `implemented_unverified / pure verified / review approved` | RUNTIME-COMPAT-1 commits `0b3cbdd`, `d5dce3e`, `5751997`, `8064517`, `f4ba488`, `b0cbe57`, `5df1278`; focused `60 passed`; full pure `738 passed, 2 skipped`; PostgreSQL, Alembic CLI и application suite не запускались; operational acceptance ожидает TEST-DB-F2 / RUNTIME-COMPAT-2 |
| TEST-DB-FOUNDATION | Isolated PostgreSQL Test Database Foundation | [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 (ACCEPTED)]] + [[docs/project/ADR-029-test-db-safety-interlock|ADR-029 (ACCEPTED)]] + [[docs/project/ADR-032-test-db-foundation-and-runtime-bootstrap-boundary|ADR-032 (ACCEPTED)]] + [[docs/project/ADR-033-test-db-f2-local-rehearsal|ADR-033 (ACCEPTED)]] + [[docs/project/TASK_TEST_DB_FOUNDATION_SPEC|Implementation Specification (ACCEPTED)]] + [[docs/project/TASK_TEST_DB_FOUNDATION_IMPLEMENTATION_PLAN|Implementation Plan]] + [[docs/project/TASK_TEST_DB_FOUNDATION_CLAUDE_CODE_PROMPT|Cursor / Claude Code Prompt]] + [[docs/project/TASK_TEST_DB_F2_PURE_RUNNER_SPEC|F2 Pure Runner Specification (ACCEPTED)]] + [[docs/project/TASK_TEST_DB_F2_PURE_RUNNER_IMPLEMENTATION_PLAN|F2 Pure Runner Plan (ACCEPTED)]] + [[docs/project/TASK_TEST_DB_F2_PURE_RUNNER_CLAUDE_CODE_PROMPT|F2 Pure Runner Prompt (ACCEPTED)]] | `implemented_unverified / F2 pure runner planned` | TEST-DB-F1 commit `20c7ea7`; local F2 architecture and pure runner delivery documents accepted 2026-07-30; three preserved owned PostgreSQL 18.3 DB, sequential bind-once workers and append-only evidence; pure runner implementation pending; PostgreSQL/application tests/CI create-drop не запускались |

Safety prerequisite: `ADR-029 → TEST-DB-SAFETY-INTERLOCK` блокирует опасный pytest,
но не меняет основной execution gate.

Основной execution gate: `ADR-025 → ADR-030 → ADR-031 → B-03 → B-04A-R18 → B-04R → B-04B → TEST-DB-F1 pure core → RUNTIME-COMPAT-1 pure implementation → TEST-DB-F2 / RUNTIME-COMPAT-2 isolated PostgreSQL acceptance → Task 9D-4A-5A`.
Текущие статусы: B-03 — `done`, closure
verified 2026-07-22; B-04A PG16 — historical non-authorizing, B-04A-R18 —
`done / active_authorizing`, B-04R — `done / active_restore_authorizing`,
B-04B — `done / ADOPTION_ACCEPTED`; migration freeze released;
TEST-DB Foundation — `implemented_unverified / F2 architecture accepted`;
Runtime profile — `implemented_unverified / pure verified / review approved`;
TEST-DB-F2 pure runner — `planned / implementation not started`.
Следующий gate: `TEST-DB-F2-PURE-RUNNER implementation`; operational
preflight, PostgreSQL rehearsal, commit и push требуют отдельных разрешений.

## Electronic Documentation Layer (ADR-018, Session 008-06)

| Task | Название | ADR | Статус | Ключевой commit |
|---|---|---|---|---|
| — | Document lifecycle, versioning, snapshots, templates | ADR-018 | `planned` | — |

## Project Control Center (служебный контур, не Task WeldPassport)

| Блок | Название | ADR | Статус | Ключевой commit |
|---|---|---|---|---|
| — | Первый рабочий срез (`09_Разработка/project_control/`) | ADR-020 | `in_progress` | `e793104` (мерж `5aceb0d`) |

## Будущее архитектурное направление — AI Data Access & Analytics Layer (ADR-026)

Раздел фиксирует **архитектурный элемент**, а не Task. Implementation Task **не создаётся**
и не планируется до принятия решения.

| Архитектурный элемент | Название | Архитектурное основание | Статус | Ключевой commit |
|---|---|---|---|---|
| ADR-026 | AI Data Access & Analytics Layer | [[docs/project/ADR-026-ai-data-access-analytics-layer\|ADR-026 (`PROPOSED / FUTURE`)]] + [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 011 — AI Data Access & Analytics Layer\|Architecture Session 011 (`IN PROGRESS`)]] | `not_designed` | — (решение не принято; Implementation Task отсутствует; код, миграции, API и схема БД не изменялись) |

Статус `not_designed` означает, что архитектурное решение ещё не принято. Направление не
входит в MVP, не заменяет `reporting` и не является частью Project Control Center. Переход к
проектированию и реализации требует принятого ADR и отдельной Task Implementation
Specification.

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
