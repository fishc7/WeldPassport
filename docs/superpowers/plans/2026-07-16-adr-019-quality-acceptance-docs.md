# ADR-019 Quality Acceptance Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Зафиксировать ADR-019 о разделении лабораторного результата, технического решения ОГС и внешней приёмки, затем синхронизировать каноническую документацию до начала Task 9D.

**Architecture:** ADR-019 добавляется как корректирующее решение и явно частично замещает конфликтующие положения ADR-015 и ADR-017, не переписывая их исторический текст. Актуальные документы получают единый канон: лаборатория фиксирует результат, главный сварщик принимает техническое решение, внешний орган приёмки выдаёт официальный итог, а сотрудник ОГС регистрирует его в MVP.

**Tech Stack:** Markdown, Obsidian wiki-links, Git, PowerShell, `rg`.

## Global Constraints

- На этом этапе не изменять код, тесты backend, Alembic-миграции и физическую схему БД.
- Основная БД проекта — только PostgreSQL; SQLite не предлагать.
- Исторические ADR-015 и ADR-017 не переписывать: добавить пометки о частичном замещении и новый ADR-019.
- Не удалять `OTK_INSPECTOR` резко; документировать вывод из активной внутренней цепочки и последующий совместимый перенос прав.
- Не смешивать лабораторное заключение, техническое решение ОГС и внешнее решение `ГОДЕН` / `НЕ ГОДЕН`.
- Не считать дефект или ответственность сварщика автоматически установленными отрицательным результатом лаборатории либо отказом заказчика.
- Историю решений, документов и причинных оценок не перезаписывать.
- Язык документации и коммитов — русский; сообщения коммитов — Conventional Commits.
- Источник требований: `docs/superpowers/specs/2026-07-16-adr-019-external-quality-acceptance-responsibility-design.md`.

---

## File Map

| Файл | Ответственность изменения |
|---|---|
| `docs/project/DECISIONS.md` | Новый ADR-019 и явные связи замещения ADR-015/017 |
| `docs/ARCHITECTURE.md` | Актуальный канон ролей, quality workflow, закрытия Joint и статус реализации |
| `docs/project/PROJECT_SUMMARY.md` | Краткая текущая картина ответственности и следующий этап |
| `docs/project/ROADMAP.md` | Предусловие ADR-019 и обновлённая последовательность post-9C |
| `docs/project/ARCHITECTURE_SESSIONS.md` | Architecture Session 009 как запись пересмотра Session 007/008 |
| `docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md` | Новая разбивка Tasks 9D–9K и отдельный этап внешней приёмки |
| `docs/project/UBIQUITOUS_LANGUAGE.md` | Термины внешнего органа, внешнего решения, Technical Hold, делегирования и ответственности |
| `docs/project/CHAT_INDEX.md` | Источник решения и статус его разбора |
| `00_НАВИГАЦИЯ.md` | Ссылка на ADR-019 только если текущий формат хаба перечисляет отдельные актуальные ADR |

---

### Task 1: Зафиксировать ADR-019

**Files:**
- Modify: `docs/project/DECISIONS.md` — после ADR-017
- Reference: `docs/superpowers/specs/2026-07-16-adr-019-external-quality-acceptance-responsibility-design.md`

**Interfaces:**
- Consumes: согласованные правила спецификации, существующие ADR-015/016/017
- Produces: стабильный якорь `ADR-019. External Quality Acceptance and Welding Responsibility Canon`, на который ссылаются все последующие задачи

- [ ] **Step 1: Перечитать целевые ADR полностью**

Run:

```powershell
$p = 'docs/project/DECISIONS.md'
$lines = Get-Content $p
$lines[1862..($lines.Length - 1)]
```

Expected: видны полные ADR-015, ADR-016 и ADR-017; подтверждено, что Tasks 9D–9K ещё `planned / not implemented`.

- [ ] **Step 2: Добавить пометки о частичном замещении**

В конец ADR-015 и ADR-017 добавить короткие блоки `Актуализация ADR-019`, не меняя исходных решений. Зафиксировать точные замещения:

```text
ADR-019 замещает внутреннюю проверку ОТК, обязательное подтверждение Defect ОТК,
совместное решение ОГС/ОТК и безусловное согласование Repair внутренним ОТК.
Не замещаются: Result ≠ Finding ≠ Defect, версионность, история, отдельный Repair,
Reinspection, документы качества и подтверждаемая причинная связь со сварщиком.
```

- [ ] **Step 3: Добавить ADR-019**

ADR должен содержать следующие разделы без сокращения смысла:

```markdown
## ADR-019. External Quality Acceptance and Welding Responsibility Canon

Статус: **ACCEPTED — принято**

### Контекст
Отдельного ОТК подрядчика нет; технические решения принимает главный сварщик,
официальную приёмку выполняет внешний орган, а ОГС регистрирует решение в MVP.

### Решение
- Laboratory Result / Conclusion не равно внешней приёмке.
- Engineering Evaluation и Chief Welder Decision принадлежат ОГС.
- External Acceptance Decision имеет бинарный итог ГОДЕН / НЕ ГОДЕН.
- Автор внешнего решения, регистратор ОГС и проверяющий разделены.
- Предварительная запись без документа не влияет на Joint.
- Техническая блокировка и внешняя приёмка независимы.
- Новая сварка/ремонт/переварка прекращает актуальность прежней приёмки.
- Требование внешней приёмки задаётся версионируемым правилом проекта.
- OTK_INSPECTOR выводится из активной внутренней цепочки совместимо.
- Defect и ответственность сварщика требуют отдельной технической оценки.

### Последствия
До Task 9D обновляются архитектура, словарь, roadmap и post-9C план.
Код и миграции этим ADR не изменяются.
```

Дополнить ADR таблицами ролей, правил закрытия, версий решения, документов, делегирования и причинной связи из спецификации; сослаться на неё как на согласованный design source.

- [ ] **Step 4: Проверить полноту ADR**

Run:

```powershell
rg -n "ADR-019|External Acceptance|TechnicalHold|OTK_INSPECTOR|DecisionDelegation|ГОДЕН|НЕ ГОДЕН|POSSIBLE|PROBABLE|CONFIRMED" docs/project/DECISIONS.md
```

Expected: ADR-019 найден; присутствуют все ключевые понятия; ADR-015/017 содержат явные пометки о частичном замещении.

- [ ] **Step 5: Проверить формат и закоммитить**

Run:

```powershell
git diff --check -- docs/project/DECISIONS.md
git diff -- docs/project/DECISIONS.md
git add -- docs/project/DECISIONS.md
git commit -m "docs: adopt ADR-019 quality acceptance canon"
```

Expected: `git diff --check` без вывода; коммит затрагивает только `DECISIONS.md`.

---

### Task 2: Синхронизировать каноническую архитектуру

**Files:**
- Modify: `docs/ARCHITECTURE.md:74` — таблица модулей
- Modify: `docs/ARCHITECTURE.md:230` — цепочка ответственности
- Modify: `docs/ARCHITECTURE.md:469` — §5.7
- Modify: `docs/ARCHITECTURE.md:607` — §5.8
- Modify: `docs/ARCHITECTURE.md:1078` — матрица ответственности
- Modify: `docs/ARCHITECTURE.md:1191` — список ADR

**Interfaces:**
- Consumes: якорь ADR-019 из Task 1
- Produces: единственный актуальный архитектурный канон для roadmap, словаря и плана реализации

- [ ] **Step 1: Исправить верхнеуровневое владение quality**

Заменить формулировки «приёмка и дефекты принадлежат внутреннему ОТК» на:

```text
quality: лаборатория НК — выполнение и технический результат;
ОГС/главный сварщик — техническая оценка, дефект и технологическое решение;
внешний орган приёмки — официальный итог;
ОГС в MVP — регистрация внешнего решения.
```

Цепочку ответственности показать как `ОК → ОГС → СМР → ПТО → НК → ОГС → внешняя приёмка → Закрытие`, с примечанием о параллельных техническом и внешнем условиях закрытия.

- [ ] **Step 2: Актуализировать §5.7**

Сохранить описание реализованных Tasks 9A–9C. Исправить только прогнозный слой:

- `LAB_CONFIRMED` остаётся лабораторным подтверждением;
- `VERIFIED` не объявлять будущей внутренней проверкой ОТК — отметить, что окончательный смысл решается при совместимой реализации ADR-019;
- права `OTK_INSPECTOR` описать как реализованный legacy-канон, требующий миграции;
- заменить цепочку `лаборатория → ОТК → ОГС` на `лаборатория → ОГС → внешний орган приёмки`.

- [ ] **Step 3: Актуализировать §5.8 новым §5.9 или вложенным блоком ADR-019**

Не удалять канон ADR-017. Добавить сразу после него раздел:

```text
ADR-019 частично замещает ролевые положения ADR-017.
Result ≠ Finding ≠ Defect сохраняется.
Defect подтверждает ОГС после Engineering Evaluation.
Chief Welder Decision и External Acceptance Decision раздельны.
Repair согласуется внешним органом только когда этого требует правило проекта.
Reinspection не закрывает Defect без внутреннего решения и, когда требуется,
актуальной внешней приёмки.
```

Добавить таблицу «условия закрытия Joint»: внешний итог обязателен по правилу проекта; `TechnicalHold` всегда блокирует; `ГОДЕН` не снимает hold; `НЕ ГОДЕН` всегда блокирует.

- [ ] **Step 4: Обновить ссылки и статус этапа**

В списке ADR добавить ADR-019. Следующий этап сформулировать как «документационная фиксация ADR-019, затем перепланированный Task 9D», не утверждая, что код ADR-019 реализован.

- [ ] **Step 5: Проверить отсутствие активного старого канона**

Run:

```powershell
rg -n "ОТК.*подтвержд|совместн.*ОГС.*ОТК|OTK_INSPECTOR|VERIFIED|ADR-019|внешн.*приём" docs/ARCHITECTURE.md
```

Expected: исторические формулировки помечены как замещённые; актуальные разделы ссылаются на ADR-019; реализованное состояние Tasks 9A–9C не искажено.

- [ ] **Step 6: Проверить и закоммитить**

Run:

```powershell
git diff --check -- docs/ARCHITECTURE.md
git add -- docs/ARCHITECTURE.md
git commit -m "docs: align architecture with external acceptance"
```

Expected: один документационный коммит; код не затронут.

---

### Task 3: Обновить сводку и roadmap

**Files:**
- Modify: `docs/project/PROJECT_SUMMARY.md`
- Modify: `docs/project/ROADMAP.md`

**Interfaces:**
- Consumes: актуальный канон `docs/ARCHITECTURE.md` из Task 2
- Produces: краткая управленческая картина и корректное предусловие следующего этапа

- [ ] **Step 1: Обновить PROJECT_SUMMARY**

Добавить краткий блок:

```text
Лаборатория фиксирует результат; ОГС принимает техническое решение;
внешний орган приёмки выдаёт официальный итог. В MVP решение регистрирует ОГС.
Закрытие требует отсутствия TechnicalHold и, когда установлено проектом,
актуального внешнего итога ГОДЕН.
```

Убрать из актуальных сводок утверждение, что внутренний ОТК владеет Defect или приёмкой. Исторические ссылки оставить с пометкой ADR-019.

- [ ] **Step 2: Обновить ROADMAP**

До Task 9D вставить документационный checkpoint:

```text
ADR-019 Documentation Alignment — ADR, Architecture, Sessions, Ubiquitous
Language, post-9C tasks. Code/migrations: none.
```

Отметить отдельный будущий вертикальный этап External Acceptance после базовой технической оценки, но до финального закрытия Joint. Не назначать ему номер, конфликтующий с Tasks 9D–9K, пока разбивка не обновлена в Task 5 этого плана.

- [ ] **Step 3: Проверить статусы**

Run:

```powershell
rg -n "ADR-019|внешн.*приём|TechnicalHold|Task 9D|9K|ОТК" docs/project/PROJECT_SUMMARY.md docs/project/ROADMAP.md
```

Expected: ADR-019 принят как архитектурный канон, но реализация явно `planned / not implemented`.

- [ ] **Step 4: Проверить и закоммитить**

Run:

```powershell
git diff --check -- docs/project/PROJECT_SUMMARY.md docs/project/ROADMAP.md
git add -- docs/project/PROJECT_SUMMARY.md docs/project/ROADMAP.md
git commit -m "docs: update quality acceptance roadmap"
```

Expected: коммит содержит только два заявленных файла.

---

### Task 4: Записать Architecture Session 009

**Files:**
- Modify: `docs/project/ARCHITECTURE_SESSIONS.md` — перед шаблоном новой сессии

**Interfaces:**
- Consumes: ADR-019 и обновлённый roadmap
- Produces: историческая запись интервью и карта решений 009-01…009-08

- [ ] **Step 1: Добавить Session 009**

Использовать существующий формат сессий и зафиксировать минимум следующие блоки:

```text
009-01 — фактическая организационная модель: внутреннего ОТК нет.
009-02 — два варианта лабораторного заключения; ни один не равен приёмке.
009-03 — Chief Welder Decision и External Acceptance Decision независимы.
009-04 — регистрация ОГС, внешний автор, внутренний проверяющий и документ.
009-05 — решения по методу и стыку; бинарный итог; версии и актуальность.
009-06 — TechnicalHold, ремонт, повторный контроль и правила закрытия.
009-07 — Defect, многофакторные причины и ответственность сварщика.
009-08 — RBAC, делегирование и вывод OTK_INSPECTOR из активной цепочки.
```

В каждой записи указать выбранный вариант и последствие. Сослаться на ADR-019 и спецификацию.

- [ ] **Step 2: Обновить итоговый счётчик и следующий этап**

В нижнем статусном абзаце увеличить число сессий до 9, отметить Session 009 завершённой и назвать следующим этапом обновление post-9C задач без кода.

- [ ] **Step 3: Проверить структуру**

Run:

```powershell
rg -n "Architecture Session 009|009-0[1-8]|ADR-019|Сессий: 9|Записей: 9" docs/project/ARCHITECTURE_SESSIONS.md
```

Expected: найдены заголовок, восемь решений, ссылка на ADR-019 и обновлённый счётчик в формате, который уже используется файлом.

- [ ] **Step 4: Проверить и закоммитить**

Run:

```powershell
git diff --check -- docs/project/ARCHITECTURE_SESSIONS.md
git add -- docs/project/ARCHITECTURE_SESSIONS.md
git commit -m "docs: record quality responsibility session 009"
```

Expected: один файл в коммите.

---

### Task 5: Перепланировать Tasks 9D–9K

**Files:**
- Modify: `docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md:932`

**Interfaces:**
- Consumes: архитектурные границы ADR-019 и Session 009
- Produces: последовательность независимо проверяемых вертикальных этапов для будущих implementation plans

- [ ] **Step 1: Сохранить реализованный baseline**

Не менять статусы Tasks 9A–9C и физические факты их реализации. В блоке исторической совместимости отметить, что права `OTK_INSPECTOR` и резерв `VERIFIED` требуют совместимой корректировки отдельной задачей.

- [ ] **Step 2: Заменить прогнозную разбивку post-9C**

Использовать следующую последовательность:

| Task | Результат |
|---|---|
| 9D — Quality Finding and Engineering Evaluation | Finding, оценка ОГС, Result ≠ Finding ≠ Defect |
| 9E — Chief Welder Decision and Technical Hold | решения ОГС, блокировки, версии, делегирование |
| 9F — Defect Core | Defect после оценки ОГС, lifecycle, Finding ↔ Defect |
| 9G — Cause, Severity and Responsibility | причины, коренная причина, локализация, ответственность |
| 9H — Repair Planning and External Coordination | план, версии, лимиты, проектное требование согласования |
| 9I — Repair Execution | выполнение, отклонения и техническая проверка ОГС |
| 9J — Reinspection Integration | повторный контроль, актуальность, закрытие Defect по внутренним условиям |
| 9K — Quality Documents and Registry | документы, версии, подписи, архивные реквизиты |
| 9L — External Acceptance | внешний орган, инспектор snapshot, решения по методу/стыку, регистрация и проверка |
| 9M — Joint Quality Closure Integration | правила обязательности, readiness, взаимодействие TechnicalHold и внешнего итога |

Явно указать, что добавление 9L/9M — изменение roadmap, а не реализация. Печатные формы остаются отдельным открытым блоком, если их объём не покрыт 9K.

- [ ] **Step 3: Добавить аудит совместимости 9A–9C**

Перед 9D добавить небольшую задачу `Post-9C compatibility audit` без изменения схемы в рамках документационного этапа. Её будущий implementation scope:

- карта всех прав `OTK_INSPECTOR`;
- целевой перенос на проектно уполномоченный ОГС;
- решение о судьбе `VERIFIED`;
- миграция ролей без потери существующих назначений и аудита.

- [ ] **Step 4: Проверить последовательность**

Run:

```powershell
rg -n "9D|9E|9F|9G|9H|9I|9J|9K|9L|9M|ADR-019|OTK_INSPECTOR|VERIFIED" docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md
```

Expected: Tasks 9A–9C остаются DONE; 9D–9M имеют однозначный scope; старые совместные решения ОГС/ОТК помечены как замещённые.

- [ ] **Step 5: Проверить и закоммитить**

Run:

```powershell
git diff --check -- docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md
git add -- docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md
git commit -m "docs: replan post-9C quality tasks"
```

Expected: один файл в коммите; никаких исходников или миграций.

---

### Task 6: Синхронизировать ubiquitous language

**Files:**
- Modify: `docs/project/UBIQUITOUS_LANGUAGE.md:1377` — прежнее решение ОТК
- Modify: `docs/project/UBIQUITOUS_LANGUAGE.md:1398` — Defect
- Modify: `docs/project/UBIQUITOUS_LANGUAGE.md:1455` — Repair
- Modify: `docs/project/UBIQUITOUS_LANGUAGE.md:1499` — Reinspection
- Modify: `docs/project/UBIQUITOUS_LANGUAGE.md` — новые термины ADR-019

**Interfaces:**
- Consumes: сущности и границы из спецификации и ADR-019
- Produces: единые термины для будущих схем, API и UI

- [ ] **Step 1: Добавить новые термины**

Создать определения:

```text
External Acceptance Authority — уполномоченная внешняя организация проекта.
External Acceptance Decision — версионный официальный итог по методу или Joint.
External Inspector Snapshot — неизменяемые данные фактического автора решения.
External Acceptance Document — документ-основание для одного или многих решений.
Technical Hold — техническая блокировка, независимая от внешней приёмки.
Chief Welder Decision — утверждённое техническое решение ОГС.
Decision Delegation — ограниченное полномочие принять решение вместо главного сварщика.
Responsibility Assessment — отдельная оценка причинной связи, а не свойство Defect.
```

Для каждого термина указать владельца, что с ним не следует путать, связанные сущности и ссылку на ADR-019.

- [ ] **Step 2: Актуализировать существующие определения**

- `Defect`: подтверждается ОГС после инженерной оценки; внешний отказ не создаёт Defect автоматически.
- `Repair`: утверждает главный сварщик; внешнее согласование зависит от правила проекта.
- `Reinspection`: технический результат не равен внешней повторной приёмке.
- прежнее «решение ОТК»: переименовать в исторический или замещённый термин и направить на `External Acceptance Decision`.
- ответственность сварщика: только `CONFIRMED` влияет на показатели и допуски.

- [ ] **Step 3: Проверить термины и ссылки**

Run:

```powershell
rg -n "External Acceptance|Technical Hold|Chief Welder Decision|Decision Delegation|Responsibility Assessment|ADR-019|ОТК" docs/project/UBIQUITOUS_LANGUAGE.md
```

Expected: все восемь терминов определены; активные определения не требуют внутреннего ОТК.

- [ ] **Step 4: Проверить и закоммитить**

Run:

```powershell
git diff --check -- docs/project/UBIQUITOUS_LANGUAGE.md
git add -- docs/project/UBIQUITOUS_LANGUAGE.md
git commit -m "docs: define external quality acceptance language"
```

Expected: один файл в коммите.

---

### Task 7: Обновить индекс чатов и навигацию

**Files:**
- Modify: `docs/project/CHAT_INDEX.md:198`
- Modify if required by existing hub pattern: `00_НАВИГАЦИЯ.md`

**Interfaces:**
- Consumes: принятый ADR-019, Session 009 и обновлённые документы
- Produces: трассируемость от рабочего обсуждения к каноническому решению

- [ ] **Step 1: Обновить раздел «НК, ОТК и качество»**

Добавить запись обсуждения «ОТК и ответственность сварщика» со статусом `processed`. Указать:

- исходный ChatGPT conversation id `6a585886-7cf8-83eb-a774-40a677e3d546` как рабочий источник, не канон;
- результат: спецификация, ADR-019 и Session 009;
- ключевое изменение: внутреннего ОТК нет, внешний итог регистрирует ОГС;
- ссылки на обновлённые канонические файлы.

- [ ] **Step 2: Проверить необходимость корневой навигации**

Run:

```powershell
rg -n "ADR-015|ADR-016|ADR-017|DECISIONS|Архитектур" 00_НАВИГАЦИЯ.md
```

Expected: если хаб перечисляет отдельные ADR, добавить ADR-019 рядом; если он ссылается только на `DECISIONS.md`, файл не менять.

- [ ] **Step 3: Проверить ссылки и закоммитить**

Run:

```powershell
git diff --check -- docs/project/CHAT_INDEX.md 00_НАВИГАЦИЯ.md
git add -- docs/project/CHAT_INDEX.md
git diff --quiet -- 00_НАВИГАЦИЯ.md; if ($LASTEXITCODE -ne 0) { git add -- 00_НАВИГАЦИЯ.md }
git commit -m "docs: index quality responsibility decision"
```

Expected: `CHAT_INDEX.md` изменён; `00_НАВИГАЦИЯ.md` включён только при необходимости.

---

### Task 8: Выполнить сквозную проверку документации

**Files:**
- Verify: все файлы Tasks 1–7
- Modify only if verification finds a contradiction: `docs/project/DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/project/PROJECT_SUMMARY.md`, `docs/project/ROADMAP.md`, `docs/project/ARCHITECTURE_SESSIONS.md`, `docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md`, `docs/project/UBIQUITOUS_LANGUAGE.md`, `docs/project/CHAT_INDEX.md`

**Interfaces:**
- Consumes: весь синхронизированный комплект
- Produces: непротиворечивый канон, готовый для отдельного implementation plan Task 9D

- [ ] **Step 1: Проверить запрещённые активные формулировки**

Run:

```powershell
rg -n "ОТК.*подтверждает.*Defect|совместн.*решени.*ОГС.*ОТК|ОТК.*владел.*Defect|лаборатор.*автомат.*НЕ ГОДЕН" docs/ARCHITECTURE.md docs/project/DECISIONS.md docs/project/PROJECT_SUMMARY.md docs/project/ROADMAP.md docs/project/ARCHITECTURE_SESSIONS.md docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md docs/project/UBIQUITOUS_LANGUAGE.md
```

Expected: совпадения допустимы только внутри явно помеченного исторического/замещённого текста; каждый такой фрагмент рядом ссылается на ADR-019.

- [ ] **Step 2: Проверить обязательный новый канон**

Run:

```powershell
rg -l "ADR-019" docs/ARCHITECTURE.md docs/project/DECISIONS.md docs/project/PROJECT_SUMMARY.md docs/project/ROADMAP.md docs/project/ARCHITECTURE_SESSIONS.md docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md docs/project/UBIQUITOUS_LANGUAGE.md docs/project/CHAT_INDEX.md
```

Expected: команда выводит все восемь файлов.

- [ ] **Step 3: Проверить placeholders и формат**

Run:

```powershell
rg -n "T[B]D|T[O]DO|implement lat[e]r|заполнить позж[e]" docs/ARCHITECTURE.md docs/project/DECISIONS.md docs/project/PROJECT_SUMMARY.md docs/project/ROADMAP.md docs/project/ARCHITECTURE_SESSIONS.md docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md docs/project/UBIQUITOUS_LANGUAGE.md docs/project/CHAT_INDEX.md
git diff --check 3e43dde..HEAD
```

Expected: новые разделы не содержат незаполненных маркеров; `git diff --check` без вывода. Существующие исторические маркеры, если найдены вне изменённых разделов, перечислить в отчёте и не расширять scope.

- [ ] **Step 4: Проверить, что код не изменён**

Run:

```powershell
git diff --name-only 3e43dde..HEAD | rg "^(09_Разработка|.*\.py$|.*\.ts$|.*\.tsx$)"
```

Expected: нет вывода.

- [ ] **Step 5: Проверить чистоту целевых файлов**

Run:

```powershell
git status --short
git log -8 --oneline
```

Expected: целевые изменения закоммичены отдельными Conventional Commits; любые чужие изменения в рабочем дереве не затронуты.

- [ ] **Step 6: Создать корректирующий коммит только при необходимости**

Если сквозная проверка потребовала правок, добавить только исправленные документы и выполнить:

```powershell
git diff --check
git commit -m "docs: reconcile ADR-019 references"
```

Expected: коммит создаётся только при фактических исправлениях; иначе шаг отмечается как `not needed` в отчёте выполнения.
