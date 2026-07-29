# WeldPassport — Architecture Governance Framework (AGF)

> Единый регламент управления архитектурой проекта WeldPassport.  
> Обязателен для всех участников: экспертов предметной области, архитекторов и AI-инструментов разработки.

Связано: [[docs/project/CONSTITUTION#5. Architecture Governance|Конституция §5]] ·
[[docs/project/CONSTITUTION#4. Архитектурный принцип №2. Канонический язык проекта|§4 (принцип №2)]] ·
[[docs/project/ARCHITECTURE_SESSIONS|Architecture Sessions]] · [[docs/project/DECISIONS|ADR]] ·
[[docs/project/UBIQUITOUS_LANGUAGE|Ubiquitous Language]] · [[docs/ARCHITECTURE|ARCHITECTURE]].

---

## 1. Назначение

**Architecture Governance Framework (AGF)** определяет:

- как принимаются архитектурные решения;
- кто участвует в принятии решений;
- в какой последовательности развивается архитектура;
- кто имеет право изменять фундаментальные принципы проекта.

AGF не заменяет Конституцию — он описывает **процесс** её развития и применения.

---

## 2. Уровни управления архитектурой

Архитектура WeldPassport развивается строго по уровням. Пропуск уровня запрещён.

```text
Уровень 1 — Конституция
        ↓
Уровень 2 — Architecture Sessions
        ↓
Уровень 3 — ADR
        ↓
Уровень 4 — Architecture (документация)
        ↓
Уровень 5 — Task / Implementation Specification
        ↓
Implementation Decision (только техническое «как» внутри уровня 5, при необходимости)
        ↓
Уровень 6 — Реализация (код)
        ↓
Review / приёмка
```

### Уровень 1 — Конституция

- **Документ:** [[docs/project/CONSTITUTION|CONSTITUTION.md]]
- **Роль:** главный документ проекта; фундаментальные принципы и границы.
- **Изменяется:** крайне редко, только по итогам Architecture Session и с фиксацией в ADR.

### Уровень 2 — Architecture Sessions

- **Документ:** [[docs/project/ARCHITECTURE_SESSIONS|ARCHITECTURE_SESSIONS.md]]
- **Роль:** основной механизм принятия **новых** фундаментальных архитектурных решений.
- **Содержание каждой сессии:** номер, тема, вопросы, обсуждение, выводы, итоговые решения.
- **Важно:** Session — **процесс**; ADR — **результат** процесса.

### Уровень 3 — ADR

- **Документ:** [[docs/project/DECISIONS|DECISIONS.md]] и отдельные файлы `ADR-NNN-*.md`
- **Роль:** официальная фиксация каждого принятого **архитектурного** решения (см. §3.1
  различие ADR / Implementation Decision).
- **Правило:** одно существенное решение — один ADR (или явная группа в рамках одной сессии).
  В журнал ADR **не включаются** технические решения уровня Task — для них уровень 5.

### Уровень 4 — Architecture

- **Документы:** [[docs/ARCHITECTURE|ARCHITECTURE.md]] и профильные канонические
  архитектурные материалы.
- **Роль:** синхронизация технической и проектной документации **после** принятия ADR.
- **Обязательно обновляется** после каждой завершённой Architecture Session.

### Уровень 5 — Task / Implementation Specification

- **Документы:**
  - **Task Implementation Spec** — файлы `TASK_<код>_*_SPEC.md` (например
    [[docs/project/TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC|TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC.md]]):
    декомпозиция архитектурного основания в конкретный план реализации одного Task
    (файлы, интерфейсы, шаги, тесты). Не вводит новых архитектурных решений — только
    детализирует уже принятое основание.
  - **Implementation Decision** — файлы каталога
    [[docs/project/implementation-decisions/README|docs/project/implementation-decisions/]]:
    точечное техническое решение **внутри** Task, не меняющее архитектуру (см. §3.1).
  - **Реестр:** [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]] — единый источник
    фактического статуса всех Tasks (см. §3.2).
- **Роль:** мост между утверждённой архитектурой (уровень 4 и архитектурные решения
  уровня 2–3) и кодом
  (уровень 6). Task Implementation Spec и Implementation Decision **обязаны** ссылаться
  на Task и его архитектурное основание. Для новых Tasks после 2026-07-21 основанием
  служит ADR, явно указанное решение Architecture Session либо канонический раздел
  архитектуры, если отдельный ADR для такого решения не требуется. Если основание не
  зафиксировано, фундаментальное решение должно пройти уровни 2–3, а не оформляться как
  Implementation Decision.
- **Порядок:** Implementation Decision следует после архитектурного основания и Task /
  Implementation Specification. Он никогда не стоит выше Architecture Session или ADR и
  не может служить их заменой.
- **Кто ведёт:** Chief AI Architect готовит/утверждает Task Implementation Spec; AI
  Development Team фиксирует Implementation Decision при реализации (§4).

### Уровень 6 — Реализация

- **Исполнители:** AI Development Team (см. §4) — только после уровней 1–5.
- **Допускается:** изменение кода, миграций, API, тестов — в рамках утверждённой архитектуры
  и утверждённого Task Implementation Spec.

---

## 3. Различие ADR и Implementation Decision

Уровень 3 (ADR) и уровень 5 (Task / Implementation Specification) фиксируют решения
**разной природы**. Смешение их в одном журнале запрещено.

### 3.1. Определения

| | **ADR (Architecture Decision Record)** | **Implementation Decision** |
|---|---|---|
| Уровень AGF | 3 | 5 |
| Что фиксирует | **архитектурное** решение: новая/изменённая центральная сущность, границы домена, жизненный цикл данных, RBAC/матрица полномочий и separation of duties, каноническая иерархия, принципы Конституции/AGF (см. §6 «Критерии фундаментального решения») | **техническое** решение внутри уже утверждённого Task: выбор структуры хранения (`CHECK` vs `ENUM`), конкретная ссылка FK, порядок блокировок, имена событий/методов, HTTP mapping и т.п. — не меняющее домен, полномочия, границы или жизненный цикл, заданные ADR |
| Кем принимается | Architecture Session (Chief Domain Expert + Chief AI Architect) | AI Development Team в рамках Task, со ссылкой на ADR/Task Implementation Spec |
| Где фиксируется | [[docs/project/DECISIONS|docs/project/DECISIONS.md]] и/или отдельный файл `ADR-NNN-*.md` | [[docs/project/implementation-decisions/README|docs/project/implementation-decisions/]] |
| Номер/код | `ADR-NNN` | `<Task>-Decision` (например `9D-4A-4 Decision`) — см. §9 «Канон наименований» |
| Обязательная ссылка | на Architecture Session, породившую решение | на Task и его архитектурное основание; при наличии — на Task Implementation Spec |
| Может ли переписывать домен | да (новым ADR, старый не удаляется — только помечается `SUPERSEDED_BY`) | **нет** — если решение меняет домен/границы/жизненный цикл, это не Implementation Decision, а фундаментальное решение и требует полного цикла AGF (Architecture Session → ADR) |

### 3.2. Практическое правило

- Если решение **отвечает на вопрос «что» появляется в домене** (новая сущность, новая
  связь между доменами, новый статус в жизненном цикле) — это ADR.
- Если решение устанавливает lifecycle, право роли выполнить бизнес-команду, разделение
  обязанностей, override или фундаментальный инвариант — требуется отдельный ADR.
- Если решение **отвечает на вопрос «как» это технически устроено** внутри уже принятой
  ADR-модели (тип столбца, состав индекса, endpoint/service mapping для уже определённой
  ADR-команды, порядок блокировок в транзакции) — это Implementation Decision.
- При сомнении — решение считается фундаментальным (ADR), а не Implementation Decision.
- **`DECISIONS.md` содержит только ADR.** Технические решения Task оформляются в
  [[docs/project/implementation-decisions/README|implementation-decisions/]] и попадают в
  `DECISIONS.md` только как краткая ссылка/редирект, не как полноценный раздел.

### 3.3. Единый актуальный статус

ADR и Task Implementation Spec фиксируют статус реализации **на дату принятия** и не
переписываются задним числом (принцип «история вместо перезаписи», Конституция §7.2).
Актуальный статус каждого Task — только в [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

---

## 4. Роли

### Chief Domain Expert

**Отвечает за:**

- реальные производственные процессы;
- нормативные требования;
- технологию сварки;
- экспертную оценку предметной области.

Без участия Chief Domain Expert фундаментальные решения о производственной модели
не считаются принятыми.

### Chief AI Architect

**Отвечает за:**

- архитектуру системы;
- модели данных;
- доменную модель;
- API;
- жизненный цикл данных;
- анализ архитектурных рисков;
- обеспечение масштабируемости.

Chief AI Architect **не подменяет** эксперта предметной области и **не реализует**
код без утверждённой документации.

### AI Development Team

**Выполняет** реализацию утверждённой архитектуры.

**Текущее состояние проекта** (перечень инструментов может меняться без изменения принципов AGF):

| Инструмент | Роль на текущем этапе |
|------------|------------------------|
| **Cursor** | реализация изменений, работа с репозиторием |
| **Claude Code** | разработка и рефакторинг |
| **ChatGPT** | архитектура, ревью, постановка задач и контроль |

---

## 5. Правило для AI

**Ни один AI не имеет права самостоятельно изменять фундаментальную архитектуру проекта.**

Любое изменение:

- доменной модели;
- жизненного цикла сущностей;
- центральных сущностей;
- границ доменов;
- архитектурных принципов;
- **новых бизнес-терминов** (см. [[docs/project/CONSTITUTION#4. Архитектурный принцип №2. Канонический язык проекта|Конституция §4]], [[docs/project/UBIQUITOUS_LANGUAGE|UBIQUITOUS_LANGUAGE]]);

**обязательно** проходит цепочку:

```text
Architecture Session
        ↓
обновление UBIQUITOUS_LANGUAGE.md (при новых терминах)
        ↓
ADR
        ↓
обновление Конституции (при необходимости)
        ↓
синхронизация архитектурной документации
        ↓
только после этого — реализация
```

Реализация «с последующей документацией» запрещена.

---

## 6. Критерии фундаментального решения

Решение считается **фундаментальным** и требует полного цикла AGF, если затрагивает:

- новую центральную сущность или изменение роли существующей;
- границы домена или владельца данных;
- жизненный цикл данных (создание, статусы, удаление, версионирование);
- RBAC/матрицу полномочий, separation of duties, override и ответственность за
  бизнес-переходы;
- каноническую иерархию проекта;
- принципы Конституции или AGF.

Локальные технические решения в рамках утверждённой архитектуры **не требуют**
новой Architecture Session, но должны соответствовать действующим ADR; такие решения
оформляются как **Implementation Decision** (см. §3).

---

## 7. Связь документов

| Документ | Уровень AGF | Назначение |
|----------|------------|------------|
| [[docs/project/CONSTITUTION\|CONSTITUTION.md]] | 1 | Принципы, границы |
| [[docs/project/ARCHITECTURE_GOVERNANCE\|ARCHITECTURE_GOVERNANCE.md]] | — | Регламент процесса (этот документ) |
| [[docs/project/ARCHITECTURE_SESSIONS\|ARCHITECTURE_SESSIONS.md]] | 2 | Журнал сессий |
| [[docs/project/DECISIONS\|DECISIONS.md]] | 3 | Журнал ADR |
| [[docs/ARCHITECTURE\|ARCHITECTURE.md]] | 4 | Техническая архитектура |
| `TASK_<код>_*_SPEC.md` (напр. [[docs/project/TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC\|TASK_9D-3_..._SPEC.md]]) | 5 | Task Implementation Spec |
| [[docs/project/implementation-decisions/README\|implementation-decisions/]] | 5 | Implementation Decision |
| [[docs/project/TASK_REGISTRY\|TASK_REGISTRY.md]] | 5 | Реестр Tasks и актуальный статус реализации |
| [[docs/project/UBIQUITOUS_LANGUAGE\|UBIQUITOUS_LANGUAGE.md]] | — | Канон терминов |
| Код в `09_Разработка/` | 6 | Реализация |

---

## 8. Status/control-документы и приоритет канона

Следующие документы являются **ненормативными представлениями состояния и планов**:

- `docs/project/PROJECT_DASHBOARD.md`;
- `docs/project/PROJECT_STATUS.yaml`;
- `docs/project/PROJECT_EXECUTION_MAP.md`;
- `docs/project/PROJECT_SUMMARY.md`;
- `docs/project/ROADMAP.md`.

Они не принимают и не изменяют архитектуру. При конфликте приоритет имеет нормативный
документ более высокого уровня: Конституция → Architecture Session → ADR → Canonical
Architecture → Task / Implementation Specification → Implementation Decision → Code.
`TASK_REGISTRY.md` является первичным источником **статуса Tasks**, но не архитектурных
решений. Dashboard, Status, Execution Map, Summary и Roadmap — производные представления;
их расхождение с реестром или нормативным каноном не меняет ни статус Task, ни архитектуру.

---

## 9. Канон наименований

Единая грамматика ссылок и идентификаторов проекта. Использовать точно эти формы во всех
документах, коммитах и коде; сокращать или менять регистр — не допускается.

| Форма | Что обозначает | Пример | Где определяется |
|---|---|---|---|
| `Session NNN` или `Session NNN-MM` | Architecture Session — процесс принятия фундаментального решения (уровень 2) | `Session 008`, `Session 008-07` | [[docs/project/ARCHITECTURE_SESSIONS\|ARCHITECTURE_SESSIONS.md]] |
| `ADR-NNN` | Architecture Decision Record — результат Session (уровень 3) | `ADR-019` | [[docs/project/DECISIONS\|DECISIONS.md]] |
| `Task <код>` | Task / Implementation Specification верхнего уровня (уровень 5) | `Task 9D` | [[docs/project/TASK_REGISTRY\|TASK_REGISTRY.md]] |
| `Task <код>-<подблок>[-<подпункт>]` | подблок Task; глубина вложенности не ограничена, каждый уровень — заглавная буква/цифра через дефис | `Task 9D-4A-4` (Task 9D → подблок 4 → под-подблок A → подпункт 4) | [[docs/project/TASK_REGISTRY\|TASK_REGISTRY.md]] |
| `Implementation Decision` (заголовок файла: `Task <код> — <название> Implementation Decision`) | техническое решение внутри Task (уровень 5, см. §3) | `Task 9D-4A-4 — DefectDisposition Supersede Implementation Decision` | [[docs/project/implementation-decisions/README\|implementation-decisions/]] |
| `Commit` | одна атомарная фиксация в git; ссылка — короткий hash в обратных кавычках + дата | `` `d3a6d87` (2026-07-21) `` | `git log`, [[docs/project/TASK_REGISTRY\|TASK_REGISTRY.md]] |

Правила:

- Номер ADR **не переиспользуется** и не меняется задним числом (при коллизии — следующий
  свободный номер с явным примечанием, как это сделано для ADR-019→ADR-021 и ADR-021→ADR-022).
- Для новых Tasks после 2026-07-21 архитектурное основание обязательно. Основанием может
  быть ADR, явно указанное решение Architecture Session либо ссылка на существующий
  канонический раздел архитектуры, если отдельный ADR не требовался.
- Исторические Tasks не получают фиктивные ADR задним числом. В
  [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]] для них указывается подтверждённое
  основание либо одно из значений `LEGACY — до введения обязательного ADR` и
  `NOT VERIFIED`; необъяснённое значение `—` не используется.
- Ссылка на Commit всегда сопровождается датой; ссылка на Session/ADR/Task — соответствующим
  wiki-линком на канонический файл, а не пересказом содержания.
- Implementation Decision указывает стабильный текстовый Task ID и ссылку на
  [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]]. Ссылка на конкретный anchor строки не
  требуется: табличные anchors нестабильны.

---

## 10. Девиз процесса

> **Сначала производство. Потом архитектура. Потом код.**

---

*Версия AGF: 2026-07-21 (уровень 5, граница ADR / Implementation Decision,
status/control-документы, приоритет канона и единый канон наименований).*
