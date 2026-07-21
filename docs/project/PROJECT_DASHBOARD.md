# WeldPassport — Project Dashboard

> Человекочитаемая сводка для быстрого возврата в проект. Не источник истины —
> факты берутся из `docs/project/PROJECT_STATUS.yaml`, `docs/project/DECISIONS.md`,
> `docs/project/PROJECT_EXECUTION_MAP.md` и git. При расхождении — верить им, не этому файлу.
> Обновлять вручную после значимых изменений (см. `AGENTS.md`, правило фиксации решений).

Дата обновления: 2026-07-21
Текущая ветка: `feature/engineering-joints-mvp`

---

## Как читать этот документ

Этот файл — краткая панель состояния проекта. Он не заменяет:

- `PROJECT_STATUS.yaml` (машиночитаемый статус);
- `DECISIONS.md` (архитектурные решения);
- `ARCHITECTURE.md` (архитектура).

Он показывает текущую рабочую картину проекта.

---

# 🟢 Текущее состояние

Текущий этап: **Task 9D — Quality / Defect Management**, блок **9D-4 (Finding Disposition and Holds)**, подблок **9D-4A (DefectDisposition workflow)** — реализация в процессе (9D-4A-2/4A-3 done, 9D-4A-4 in progress).

Общий статус: инженерный контур (`Project → Line → EngineeringDocument → Joint → WeldOperation → HeatTreatment → Inspection`) реализован полностью (Tasks 1–8F, 9A–9C). Идёт реализация контроля качества после результата контроля (`QualityFinding → EngineeringEvaluation → Defect → DefectDisposition`). `PROJECT_STATUS.yaml` не обновлялся с 06.07.2026 и не отражает всё, что сделано после этой даты — см. риски ниже.

---

# ✅ Завершено

| Блок | Описание | Последний commit |
|---|---|---|
| **Architecture foundation** | Конституция проекта, домены и владение (ADR-004/005/006), Architecture Governance, Ubiquitous Language | `c899f1f` (2026-07-06) `docs: establish architecture constitution and domain ownership` |
| **Companies / Projects / Lines** | `companies`, `projects`, роли участия организаций (`project_companies`), `lines` | `e0dea82` / `6a7a0fc` (2026-07-10) `feat(projects): add companies projects and participation roles` / `add project lines` |
| **Engineering Documents** | `EngineeringDocument`, `DocumentRevision` | `6d2ea09` (2026-07-10) `feat(engineering): add engineering documents` |
| **Joint lifecycle** | Ядро `Joint`, жизненный цикл и согласования, история ревизий, bulk-импорт (ADR-010/011) | `eecffc2` (2026-07-11) `feat(engineering): implement joint lifecycle and approvals` |
| **WeldOperation** | Производственный факт сварки: core, допуск/WPS, review ОГС, корректировки/supersede, импорт (ADR-012/013) | `b08cd0a` (2026-07-12) `feat(engineering): add weld operation corrections and supersede` |
| **Heat Treatment 8F** | `HeatTreatmentBatch` / `HeatTreatmentOperation`, влияние на готовность Joint (ADR-014) | `992a2f4` (2026-07-13) `feat(engineering): integrate heat treatment workflow` |
| **Inspection 9A** | Ядро `Inspection`: заявка/мероприятие, lifecycle (ADR-015) | `a369a7e` (2026-07-13) `feat(quality): implement inspection core` |
| **Inspection 9B** | Назначение методов контроля (`Method Assignment`) | `160186c` (2026-07-14) `feat(quality): add inspection method assignments` |
| **Inspection 9C** | Выполнение методов, `MethodExecutionResultItem`, `LaboratoryConclusion`, Quality Audit, API (ADR-016) | `7eec0db` (2026-07-15) `feat(quality): implement method execution and results` |

---

# 🔄 Сейчас делаем

**9D — Quality / Defect Management**

| Подблок | Статус | Commit |
|---|---|---|
| 9D-1 QualityFinding core | ✅ done | `57cd921` (2026-07-19) |
| 9D-2A–9D-2E EngineeringEvaluation | ✅ done | `fe42669` … `57cdd3e` (2026-07-19/20) |
| 9D-3 Defect core (ADR-022) | ✅ done | `8e0ae4c` (2026-07-20) |
| **9D-4A-2** DefectDisposition — модель данных (ADR-023) | ✅ done | входит в `dfaa87b` |
| **9D-4A-3** DefectDisposition — роли (`OTK_INSPECTOR` approve, `CHIEF_WELDER` activate) | ✅ done | `dfaa87b` (2026-07-21) `feat(quality): add defect disposition workflow` |
| **9D-4A-4** DefectDisposition — Supersede workflow | 🔄 **в работе, не закоммичено** | — |

> Примечание: в постановке задачи текущей работой назван 9D-4A-3 — по факту репозитория этот подблок уже завершён и закоммичен. Реально незакоммиченная работа сейчас — 9D-4A-4.

### 9D-4A-4 — DefectDisposition Supersede Workflow

- **Цель.** Дать возможность пересмотреть уже активное официальное решение по дефекту (`DefectDisposition`) без потери истории: старая версия помечается `SUPERSEDED`, атомарно создаётся новая версия `DRAFT`, связанная через `supersedes_disposition_id`.
- **Текущий статус.** Архитектурное решение принято и записано в `docs/project/DECISIONS.md` (раздел «9D-4A-4 Decision», 2026-07-21, статус ACCEPTED) — **но эта запись сама ещё не закоммичена**. Код изменён, но не закоммичен.
- **Что уже сделано.** Изменены `defect_disposition_workflow.py`, `defect_disposition_policy.py`, `defect_disposition_repository.py`, `defect_disposition_services.py`, `defect_disposition_schemas.py`, `defect_disposition_api.py`, тесты `test_defect_disposition_workflow.py`; добавлена миграция `20260721_24_disp_supersede.py` (новый event type `DISPOSITION_SUPERSEDED`, root-level lock).
- **Что осталось.** Прогнать тесты, зафиксировать (`git add` + commit) код и решение в `DECISIONS.md`; после этого — обновить `PROJECT_STATUS.yaml` и `PROJECT_EXECUTION_MAP.md` по правилу проекта.

---

# ⏭ Следующие шаги

1. Закоммитить 9D-4A-4 (Supersede workflow) — тесты и решение уже готовы, требуется зафиксировать.
2. Закрыть оставшуюся часть блока **9D-4** — `ProductionHold` / `ProductionHoldRelease` и вычисляемый quality state `Joint` (пока нет отдельной реализации, только упоминания в workflow).
3. **9D-5 — Customer Quality Decision** (внешний участник, внутренний регистратор, evidence, история версий).
4. **9D-6 — Corrective Action and Reinspection Links** (интеграция с Repair/Reweld/Inspection, closure readiness).
5. **9D-7 — API, permissions and integration** (RBAC, cross-module валидация, интеграционные тесты всего контура 9D).
6. **9D-8 — Architecture consolidation** Task 9D.
7. Актуализировать `docs/project/PROJECT_STATUS.yaml` и `PROJECT_EXECUTION_MAP.md` (не обновлялись с 06.07.2026).

---

# 🧾 Последние commit

| Commit | Дата | Описание |
|---|---|---|
| `dfaa87b` | 2026-07-21 | feat(quality): add defect disposition workflow (9D-4A-2/4A-3) |
| `18f3899` | 2026-07-21 | feat(quality): implement defect API and reference services |
| `8e0ae4c` | 2026-07-20 | feat(quality): add defect technical model (Task 9D-3) |
| `3d08244` | 2026-07-20 | docs(quality): accept ADR-022 defect technical model |
| `57cdd3e` | 2026-07-20 | feat(quality): implement evaluation hardening (Task 9D-2E) |
| `57cd921` | 2026-07-19 | feat(quality): implement QualityFinding core (Task 9D-1) |
| `80da0fe` | 2026-07-19 | docs(architecture): adopt ADR-021 engineering evaluation core canon |
| `c106bcd` | 2026-07-16 | docs(architecture): adopt ADR-019 quality finding canon |
| `7eec0db` | 2026-07-15 | feat(quality): implement method execution and results (Inspection 9C) |
| `992a2f4` | 2026-07-13 | feat(engineering): integrate heat treatment workflow (Task 8F) |
| `eecffc2` | 2026-07-11 | feat(engineering): implement joint lifecycle and approvals |
| `c899f1f` | 2026-07-06 | docs: establish architecture constitution and domain ownership |

*(мелкие технические коммиты — точечные фиксы, тесты без нового поведения, форматирование — не включены)*

---

# ⚠️ Текущие риски

- **Смешение Defect / Disposition / Repair.** Границы уже разведены в ADR-019/ADR-022/9D-4A, но контур `Repair`/`Reinspection`/`NCR` сознательно вынесен за рамки 9D-4A-4 — при спешке легко случайно затянуть его в текущий блок.
- **Потеря архитектурного контроля.** Task 9D разбит на 8 подблоков (9D-1…9D-8) с несколькими под-решениями внутри (9D-4A-2/3/4…) — без дисциплины ADR/DECISIONS легко потерять, какой подблок реально закрыт.
- **Риск соблюдения процесса «решение → реализация → тесты → commit».** Правило проекта («Код не опережает документацию») требует, чтобы расширение модели `quality` сначала фиксировалось в `DECISIONS.md`, а код и тесты — сразу следом, одним блоком, без разрыва последовательности.
- **Отсутствие актуального статуса.** `PROJECT_STATUS.yaml` (главный источник состояния по правилу проекта) не обновлялся с 06.07.2026 — не отражает ни `production/joints`, ни `engineering`, ни `quality`/Task 9D. Риск принятия решений на основе устаревшей картины.

---

# 🗺 Карта проекта

```text
Joint
  ↓
WeldOperation
  ↓
Heat Treatment
  ↓
Inspection
  ↓
Defect
  ↓
Repair
  ↓
Final Passport
```
