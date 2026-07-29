# WeldPassport — дорожная карта

> Связанные документы: [[docs/project/CONSTITUTION|Конституция]] · [[docs/project/DECISIONS|Решения (ADR)]] ·
> [[docs/ARCHITECTURE|Архитектура]] · [[docs/project/PROJECT_EXECUTION_MAP|Карта выполнения]] ·
> [[docs/project/TASK_REGISTRY|Реестр Tasks]].
> Производственные узлы: [[02_Процессы/Сварочные_операции|Сварочные операции]] · [[02_Процессы/Неразрушающий_контроль|НК]].

## Назначение

План развития WeldPassport. Машиночитаемое состояние выполнения —
`docs/project/PROJECT_STATUS.yaml`; постатейный статус — [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

## Текущий этап (обновлено 2026-07-29)

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

**B-04A — Canonical Baseline Build & Verification** завершён и зафиксирован
implementation commit `4487127a3042cf6a8ba003b85cffd143dc920f0e`
(`done`). Для source commit
`6c56f99edbd4e7346264ee14658d2076b5fd0775` на PostgreSQL 16.14 доказана
эквивалентность historical, clean baseline и re-upgrade: 73 canonical tables,
15 governed seeds, fingerprint
`ce2cd0613eab20da8d0a93d8caf675aa32fce932d909dfa219533b0c12dfc9f6`;
pure suite — `246 passed, 1 skipped`.

По [[docs/project/ADR-030-postgresql-18-b04-evidence-versioning|ADR-030]] это evidence
сохраняется как `historical_non_authorizing`. Целевая версия проекта — PostgreSQL
18.x. B-04A-R18 с fingerprint v2 уже принят; до B-04B теперь требуется отдельный
B-04R restore-roundtrip evidence по ADR-031.

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

### 0. B-04A-R18 принят; B-04R restore evidence — следующий gate

- B-04A PG16 evidence опубликовано вне активного `migrations/versions` и сохраняется
  неизменяемым как historical non-authorizing;
- implementation commit: `4487127a3042cf6a8ba003b85cffd143dc920f0e`;
- active migration graph, version marker и рабочая БД не изменены;
- migration freeze остаётся активным;
- B-04A-R18 принят 2026-07-29: implementation `f5245ba`, accepted evidence
  `b34538f`, PostgreSQL 18.3, fingerprint v2
  `e9e5affd8544b10353f2139c6526bab819f6da2ed919eb279fc1357803e2649a`;
- PG18 evidence имеет статус `active_authorizing`; verification report —
  `B04A_VERIFIED`; pure verification — `314 passed, 1 skipped`;
- новый READ-ONLY Maintenance Readiness Review выявил стабильное отличие PostgreSQL
  deparser после custom-format restore: live `e9e5affd...`, restore fixed point
  `3a9e682c...`, exact diff 133 CHECK + 2 predicates;
- [[docs/project/ADR-031-b04-dual-state-live-restore-evidence|ADR-031]] принят:
  live и restore states получают отдельные exact authorizing contracts;
- [[docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_SPEC|B-04R Spec]] принята
  2026-07-29;
- [[docs/project/TASK_B-04R_RESTORE_ROUNDTRIP_EVIDENCE_IMPLEMENTATION_PLAN|B-04R
  implementation plan]] принят 2026-07-29;
- documentation commit `08bc6a09974e0272ff27938511af5d4d6ba33403` принят как
  exact implementation base;
- pure TDD implementation принята владельцем и зафиксирована commit
  `2c1a0d9fc66683a1119b496f767f57156e7e3390`;
- первый operator run остановился fail-closed до restore из-за неэкранированного
  `%` в direct psycopg SQL; минимальная remediation `%` → `%%` реализована TDD:
  focused `59 passed`, полный `379 passed, 1 skipped`, real read-only preflight
  `B04R-PREFLIGHT-OK`;
- remediation commit `65f3a28855eb0830077117fa26d9bbf789f50cb5` принят
  владельцем 2026-07-29; повторный operator run завершён
  `B04_RESTORE_ROUNDTRIP_VERIFIED`, candidate evidence опубликован как
  `candidate_pending_acceptance`;
- artifact review и secret scan прошли, но candidate-state focused suite дал
  `44 passed, 15 failed`: тесты предполагают пустой pre-generation index и
  fixture `copytree` наследует опубликованный restore-каталог; evidence
  acceptance/promotion blocked до отдельной test-state remediation;
- remediation option 1 принят 2026-07-29: live-only allowlist fixtures, exact
  empty sandbox index и stage-exact repository assertion; письменная
  [[docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_SPEC|Specification]]
  принята; test-only
  [[docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_IMPLEMENTATION_PLAN|Implementation Plan]]
  и [[docs/project/TASK_B-04R_CANDIDATE_STATE_TEST_REMEDIATION_CLAUDE_CODE_PROMPT|Prompt]]
  приняты 2026-07-29; два test-файла реализованы и дали focused
  `59 passed`; full suite дал `378 passed, 1 skipped, 1 failed` на третьем
  pre-restore directory assertion; scope amendment для
  `test_b04_evidence_versioning.py` и continuation implementation приняты
  2026-07-29; exact `1 passed`, three-file `98 passed`, full
  `379 passed, 1 skipped`; implementation SHA
  `1f4d5f7a265dc7bd86b999adb95ef7070bc2ae7b` принят 2026-07-29;
  evidence promotion отдельно разрешён и выполнен в
  `active_restore_authorizing` с `accepted_at_utc=2026-07-29T08:55:32Z`;
- promotion commit отдельно разрешён; resulting SHA acceptance и новый
  READ-ONLY Maintenance Readiness Review остаются отдельными gates;
- B-04B repository cut, marker transfer и adoption не начинать до принятого B-04R
  evidence и нового Maintenance Readiness verdict `READY`; текущий статус —
  `BLOCKED`.

### 1. Test DB Safety Interlock — завершён

- ADR-029 вводит fail-closed guard до первого подключения integration pytest и Alembic;
- pure acceptance: focused `10 passed`, migration contracts `45 passed`;
- application regression намеренно не запускался;
- реализация опубликована в commit `2046384`;
- interlock не заменяет полный TEST-DB Foundation и не меняет зависимость ADR-025:
  B-04A принят, а B-04B и runtime compatibility profile остаются отдельными этапами.

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
