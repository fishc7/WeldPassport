# WeldPassport — дорожная карта

> Связанные документы: [[docs/project/CONSTITUTION|Конституция]] · [[docs/project/DECISIONS|Решения (ADR)]] ·
> [[docs/ARCHITECTURE|Архитектура]] · [[docs/project/PROJECT_EXECUTION_MAP|Карта выполнения]] ·
> [[docs/project/TASK_REGISTRY|Реестр Tasks]].
> Производственные узлы: [[02_Процессы/Сварочные_операции|Сварочные операции]] · [[02_Процессы/Неразрушающий_контроль|НК]].

## Назначение

План развития WeldPassport. Машиночитаемое состояние выполнения —
`docs/project/PROJECT_STATUS.yaml`; постатейный статус — [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

## Текущий этап (обновлено 2026-07-30)

**Инженерный контур, WeldOperation, термообработка и ядро контроля качества (Tasks 1–7,
8A–8F, 9A–9C) реализованы.** Идёт **Task 9D — Quality / Defect Management**: блоки
9D-1 (`QualityFinding`), 9D-2 (`EngineeringEvaluation`, ADR-021), 9D-3 (`Defect`, ADR-022)
и 9D-4A (`DefectDisposition`, ADR-023) реализованы и закоммичены.

Параллельно завершена приёмка **Task 10A-R — QualityDecision Core Governance Recovery**
(ADR-027): Models/Migration, correcting revision 26, Workflow/Repository/Service,
idempotency remediation и command API приняты в рабочем дереве 2026-07-24. Статус
Task 10A завершён commit `c1b551e` от 2026-07-24.

**AS-02 — QualityDecision RBAC Consolidation** завершён:
[[docs/project/ADR-028-quality-decision-rbac-consolidation|ADR-028]] принят и реализован
2026-07-24. Revision 27, person-level SoD, evidence-bearing grant/snapshot и dual-role
warning прошли PostgreSQL-приёмку и полный backend regression (`1590 passed`).

**B-04 — Canonical Baseline Adoption** завершён и принят 2026-07-30:
active Alembic graph имеет один head `canonical_baseline_v1`, production marker
перенесён в `public`, fingerprint PostgreSQL 18.3 неизменен, owner acceptance
зафиксирован. Migration freeze снят.

Реализовано и задокументировано (полный перечень — [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]]):

- `hr.workers`, `hr.worker_roles` — ОК (`/api/v1/hr`);
- `welding.welders`, `welding.welder_admissions` — ОГС (`/api/v1/ogs`);
- `Company/Project/project_companies/Line/EngineeringDocument/Joint` — инженерный контур
  (`/api/v1/projects`, `/api/v1/engineering`, ADR-010/011);
- `WeldOperation` и термическая обработка — СМР/ОГС (ADR-012/013/014);
- `Inspection`, Method Assignment/Execution, `LaboratoryConclusion` — ОТК/НК (ADR-015/016);
- `QualityFinding`, `EngineeringEvaluation`, `Defect`, `DefectDisposition` — Task 9D-1…9D-4A
  (ADR-019/021/022/023);
- Конституция, AGF, ADR-004/005 и весь журнал ADR;
- deprecated `workforce` (legacy).

## Следующий этап

### 0. TEST-DB Foundation + Runtime Compatibility Profile

- B-04 закрыт со статусом `done / ADOPTION_ACCEPTED`;
- tooling commit:
  `1a84d566311f1cb679a84e851596f95b1053e144`;
- pure verification: `604 passed, 2 skipped`;
- production postflight SHA-256:
  `405e82ae709b2cc051c25ad3bd139614f53996a2bcfcad1d50f6f11560fc2403`;
- owner acceptance SHA-256:
  `c257b1b4736ac53be731d7de8369d45808cd4eeba1af569534272a3a4dca3b56`;
- TEST-DB-F1 pure core реализован и зафиксирован commit `20c7ea7`;
- Runtime Compatibility Profile реализован как `RUNTIME-COMPAT-1` и имеет статус
  `IMPLEMENTED_UNVERIFIED / PURE VERIFIED / REVIEW APPROVED`; focused
  `60 passed`, полный pure suite `738 passed, 2 skipped`;
- local TEST-DB-F2 architecture принята в
  [[docs/project/ADR-033-test-db-f2-local-rehearsal|ADR-033]];
- TEST-DB-F2 Pure Runner реализован и прошёл pure-приёмку 2026-07-30:
  `52 passed, 1 skipped` focused, `790 passed, 3 skipped` full pure,
  review `APPROVED`; operational PostgreSQL acceptance не выполнялась;
- отдельная TEST-DB-F2 Operator Preflight Specification принята 2026-07-30;
  preflight остаётся полностью offline и предшествует новому разрешению на
  PostgreSQL rehearsal;
- operator-preflight tooling реализован и прошёл pure-приёмку:
  `44 passed, 1 skipped` focused, `819 passed, 3 skipped` full pure,
  review `APPROVED`;
- offline operator preflight выполнен 2026-07-30 и получил
  `TEST_DB_F2_OPERATOR_PREFLIGHT_READY`; evidence id
  `4e434a78-965b-4819-9108-b278298a5b10`, source
  `a2e1f0167054e9d00bd73667f74bd2299ccde88e`, SHA-256
  `ec9ee5244d1d0f6c952429264aacb4120f52695d90baa4baaae2f04c8e31a137`;
  позднее этот checkpoint был потреблён отдельно разрешённым local rehearsal;
- TEST-DB-F2 local rehearsal выполнен 2026-07-30 на PostgreSQL 18.3 и получил
  machine status `TEST_DB_F2_REHEARSAL_VERIFIED`: run
  `9e6c9986-c80d-4fee-81af-13cf9d906194`, source
  `8148794495310ff2f7eed37948da3c64e08d1b23`, manifest SHA-256
  `5da388a47e7bbac7d56a0104d6bf3b6ce61128292976596f667bb4d78d8ea0ed`;
  canonical, legacy-compatible и legacy-negative roles verified, final pure
  suite `825 passed, 3 skipped`;
- owner acceptance `TEST_DB_F2_ACCEPTED` зафиксирована
  `2026-07-30T07:17:11.636887Z`; acceptance SHA-256
  `224974992524dc53cd8bd06b6a602ab83e76e9e6d97fb4f6d54ff687f2cab009`;
  TEST-DB Foundation и Runtime Compatibility Profile закрыты;
- следующий execution order:
  `RUNTIME-COMPAT-1 → TEST-DB-F2-PURE-RUNNER → operator preflight READY →
  local PostgreSQL rehearsal VERIFIED → evidence review → owner acceptance
  ACCEPTED`;
- следующий незакрытый prerequisite — `AUTHENTICATION_BOUNDARY_ACCEPTED`;
  только после него может стартовать Task 9D-4A-5A, затем оставшийся
  Quality-контур.
- архитектура Authentication Boundary принята 2026-07-30:
  [[docs/project/ADR-034-authentication-boundary|ADR-034]] и
  [[docs/superpowers/specs/2026-07-30-authentication-boundary-design|Architecture Design]];
  выбран local account + opaque server session, production `X-User-Id`
  запрещён; следующий шаг — Implementation Plan и Prompt, затем раздельные
  Domain/Migration/Service/API/Tests gates.

### 1. Test DB Safety Interlock — завершён

- ADR-029 вводит fail-closed guard до первого подключения integration pytest и Alembic;
- pure acceptance: focused `10 passed`, migration contracts `45 passed`;
- application regression намеренно не запускался;
- реализация опубликована в commit `2046384`;
- interlock не заменяет полный TEST-DB Foundation и не меняет зависимость ADR-025:
  B-04 принят; Runtime Compatibility Profile остаётся отдельным следующим этапом.

### 2. Task 10A — завершён

- 10A-R/10A-1/10A-1R/10A-2/10A-2R/10A-3 реализованы, приняты и зафиксированы (`c1b551e`);
- AS-02 не включён в Task 10A; архитектура AS-02 принята отдельно в ADR-028.

### 3. AS-02 — завершён

- person-level SoD для `SUBMIT → RETURN/DECIDE`;
- evidence-bearing `AuthorizationGrant` и immutable `authorization_context`;
- dual-role governance warning без HR blocking;
- все раздельные gate из
  [[docs/project/TASK_AS_02_QUALITY_DECISION_RBAC_IMPLEMENTATION_PLAN|Implementation Plan]]
  завершены; PostgreSQL rehearsal `27 → 26 → 27` и полный regression успешны.

### 4. Завершить Task 9D (Quality / Defect Management)

- остаток блока **9D-4** — `ProductionHold` / `ProductionHoldRelease`, вычисляемый quality
  state `Joint`;
- **9D-5** — Customer Quality Decision;
- **9D-6** — Corrective Action and Reinspection Links;
- **9D-7** — API, permissions и интеграционные тесты контура 9D;
- **9D-8** — Architecture consolidation Task 9D.

### 5. Электронная документация (ADR-018)

- document lifecycle, versioning, snapshots, templates, official document issuance;
- код, миграции и API пока не создавались.

### 6. Вывод legacy

- миграция `desktop_ok` на `hr` + `welding`;
- ETL из `РАБОТНИКИ` / `СВАРЩИКИ`;
- снятие роутера `workforce`.

### 7. Закрытие истории стыка

- периодика КСС;
- сведение производственной, контрольной и документальной истории стыка в единую
  итоговую запись (финальная цель системы).

## Отложено (backlog)

- нормирование времени (`norms.*`) — [[docs/project/DECISIONS#ADR-003. Исключение модуля нормирования из активного MVP|ADR-003]];
- WPS/PQR как полноценный модуль `engineering` — после стабилизации стыков;
- интеграция с 1С, Active Directory.

### AI Data Access & Analytics Layer (ADR-026, PROPOSED / FUTURE)

Отложенное направление: **будущий слой** управляемого доступа к данным WeldPassport для
аналитических и AI-потребителей. Решение **не принято** —
[[docs/project/ADR-026-ai-data-access-analytics-layer|ADR-026]] имеет статус
`PROPOSED / FUTURE`, прорабатывается в
[[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 011 — AI Data Access & Analytics Layer|Architecture Session 011]]
(`IN PROGRESS`). Реализация **требует отдельного архитектурного решения**; Implementation
Task не создаётся.

Направление рассматривается **только после стабилизации** контуров:

- HR;
- Admissions (допуски);
- Joint lifecycle;
- WeldOperation;
- Heat Treatment;
- Inspection;
- Defect / Disposition / Repair;
- RBAC.

Направление не входит в текущий MVP, не заменяет `reporting` и не является частью
Project Control Center.

## Правило изменения архитектуры

Нельзя менять ключевую архитектуру без записи в `docs/project/DECISIONS.md` и
при необходимости — в [[docs/project/CONSTITUTION|Конституции]].

**Сначала процесс → потом архитектура → потом код.**

## Служебный контур управления реализацией

Утверждён дизайн отдельного **Project Control Center** для владельца и разработчиков.
Он должен объединить карту жизненного цикла, Git/GitHub, CI, тесты, миграции,
документацию, задачи, риски и управленческие подтверждения. Контур не является
производственным модулем WeldPassport и не меняет приоритет предметной разработки.

Статус: первый рабочий срез реализован в `09_Разработка/project_control/`.
Интерактивная карта, API, форма оценки, Git/GitHub-источники, PostgreSQL-модели и
миграция готовы. Следующий рубеж — штатное подключение PostgreSQL, автоматические
снимки и реальные метрики модулей.

См. [[docs/superpowers/specs/2026-07-19-project-control-center-design|проектное предложение]]
и [[docs/project/DECISIONS#ADR-020. Отдельный Project Control Center для контроля реализации|ADR-020]].
