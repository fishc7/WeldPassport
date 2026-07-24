# WeldPassport — дорожная карта

> Связанные документы: [[docs/project/CONSTITUTION|Конституция]] · [[docs/project/DECISIONS|Решения (ADR)]] ·
> [[docs/ARCHITECTURE|Архитектура]] · [[docs/project/PROJECT_EXECUTION_MAP|Карта выполнения]] ·
> [[docs/project/TASK_REGISTRY|Реестр Tasks]].
> Производственные узлы: [[02_Процессы/Сварочные_операции|Сварочные операции]] · [[02_Процессы/Неразрушающий_контроль|НК]].

## Назначение

План развития WeldPassport. Машиночитаемое состояние выполнения —
`docs/project/PROJECT_STATUS.yaml`; постатейный статус — [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

## Текущий этап (обновлено 2026-07-24)

**Инженерный контур, WeldOperation, термообработка и ядро контроля качества (Tasks 1–7,
8A–8F, 9A–9C) реализованы.** Идёт **Task 9D — Quality / Defect Management**: блоки
9D-1 (`QualityFinding`), 9D-2 (`EngineeringEvaluation`, ADR-021), 9D-3 (`Defect`, ADR-022)
и 9D-4A (`DefectDisposition`, ADR-023) реализованы и закоммичены.

Параллельно завершена приёмка **Task 10A-R — QualityDecision Core Governance Recovery**
(ADR-027): Models/Migration, correcting revision 26, Workflow/Repository/Service,
idempotency remediation и command API приняты в рабочем дереве 2026-07-24. Статус
`accepted_uncommitted` сохраняется до выполнения commit.

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

### 1. Зафиксировать принятую реализацию Task 10A

- 10A-R/10A-1/10A-1R/10A-2/10A-2R/10A-3 реализованы и приняты;
- следующий gate — локальный commit;
- AS-02 не включён и остаётся самостоятельной архитектурной задачей.

### 2. Завершить Task 9D (Quality / Defect Management)

- остаток блока **9D-4** — `ProductionHold` / `ProductionHoldRelease`, вычисляемый quality
  state `Joint`;
- **9D-5** — Customer Quality Decision;
- **9D-6** — Corrective Action and Reinspection Links;
- **9D-7** — API, permissions и интеграционные тесты контура 9D;
- **9D-8** — Architecture consolidation Task 9D.

### 3. Электронная документация (ADR-018)

- document lifecycle, versioning, snapshots, templates, official document issuance;
- код, миграции и API пока не создавались.

### 4. Вывод legacy

- миграция `desktop_ok` на `hr` + `welding`;
- ETL из `РАБОТНИКИ` / `СВАРЩИКИ`;
- снятие роутера `workforce`.

### 5. Закрытие истории стыка

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
