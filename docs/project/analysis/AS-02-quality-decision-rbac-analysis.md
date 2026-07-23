# AS-02 — Quality Decision RBAC Analysis

**Дата:** 2026-07-23
**Статус документа:** архитектурный аудит (не принятое решение)
**Автор задачи:** владелец (запрос AS-02); исполнитель — AI-агент, режим read-only
**Область:** RBAC контура Quality Decision и смежных этапов quality-контура

> Это **аудиторский артефакт**, а не канон. Он не заводит запись в `DECISIONS.md`,
> не присваивает номер ADR и не меняет `ARCHITECTURE.md` / `PROJECT_STATUS.yaml`.
> Раздел «Проект ADR» имеет статус `PROPOSED` и приобретает силу только после
> отдельного `ACCEPTED` владельцем (правило фиксации решений `AGENTS.md`).

---

## 1. Executive Summary

Контур `QualityDecision` (Task 10A, ADR-027, **ACCEPTED**) реализован в коде
(на момент аудита — незакоммиченные `quality_decision_*` файлы) и задаёт разделение:
**`OGS_ENGINEER` создаёт/отправляет решение, `OTK_INSPECTOR` возвращает/принимает
(`DECIDE`)**. `CHIEF_WELDER` из контура намеренно исключён, в том числе как fallback.

Главный вывод: **разделение полномочий заложено на уровне ролей, но не на уровне
личности.** Ключевые архитектурные границы (кто устанавливает техническую основу vs
кто принимает решение о качестве) соблюдены. Однако выявлены три сквозных пробела,
требующих консолидирующего ADR:

| # | Пробел | Серьёзность |
|---|---|---|
| R-1 | Нет person-level SoD в `QualityDecision`: `DECIDE`-исполнитель не проверяется на несовпадение с создателем. В `EngineeringEvaluation` такой guard (`EVAL_SAME_ACTOR_REVIEW`) уже есть → внутренняя несогласованность канона. | Высокая |
| R-2 | Audit `QualityDecision` слабее стандарта ADR-024: `quality_audit_events` хранит только `actor_worker_id`, без immutable authorization snapshot (role + scope). ADR-027 §H предлагает класть снимок в `new_values` JSONB — но как рекомендацию, не как норму. | Средняя |
| R-3 | Совмещение несовместимых ролей одним работником (`OGS_ENGINEER` + `OTK_INSPECTOR` в одном scope) нигде не запрещено — делает R-1 практически эксплуатируемым. | Высокая |

**Рекомендация:** сохранить принятую модель ADR-027 (OGS создаёт → OTK решает) и
принять консолидирующий ADR «Quality Decision RBAC Consolidation», закрывающий
R-1/R-2/R-3. Смена авторитета решения не рекомендуется.

---

## 2. Current RBAC Model

### 2.1. Канон ролей (технические `role_code`)

Источник: `09_Разработка/backend/app/quality/inspection_workflow.py`. Новых ролей
проект не вводит.

| `role_code` | Бизнес-имя | Домен |
|---|---|---|
| `OGS_ENGINEER` | **WELDING_ENGINEER** (то же лицо кода) | Инженер ОГС |
| `CHIEF_WELDER` | Главный сварщик | Производственный авторитет |
| `OTK_INSPECTOR` | Инспектор ОТК | Контроль качества / приёмка |
| `NDT_SPECIALIST` | Специалист НК | Неразрушающий контроль |
| `PTO_ENGINEER` | Инженер ПТО | Документация |
| `FOREMAN` / `MASTER` | Прораб / мастер | СМР, производственная готовность |
| `NDT_LAB` (роль **компании** в проекте, не worker-роль) | Лаборатория | Внешняя лаборатория через `project_companies` |

> `WELDING_ENGINEER` — **не отдельная роль**, а бизнес-псевдоним `OGS_ENGINEER`
> (`quality_decision_workflow.py`). Отдельного `INSPECTOR` в каноне нет — есть
> составной `OTK_INSPECTOR`. «NDT» = `NDT_SPECIALIST` (человек) + `NDT_LAB` (компания).

### 2.2. Actor / scope / audit-модель

- **Actor:** аутентификация — заголовок `X-User-Id` (`shared/auth.py`); actor = `worker_id`.
- **Scope:** иерархия `GLOBAL → PROJECT → SITE → LINE → ENGINEERING_DOCUMENT` +
  сквозной `COMPANY` (`shared/permissions.py`). Проверка против фактических связей
  Joint (`role_covers_joint`), а не только по равенству `scope_id`. `SITE` физической
  сущности не имеет и против Joint не резолвится.
- **Audit:** полиморфная `quality.quality_audit_events` — хранит `actor_worker_id`,
  **без** `actor_role_code` / `scope_type` / `scope_id` (это R-2).

---

## 3. Current Quality Lifecycle

Полная цепочка и RBAC по этапам (кто создаёт / выполняет / проверяет / утверждает /
может изменить):

| Этап (Task, ADR) | Создаёт | Выполняет | Проверяет / Утверждает | Может изменить |
|---|---|---|---|---|
| **Inspection Request** (9A) | OGS, CHIEF | OGS, CHIEF | override СМР — только CHIEF | OGS, CHIEF (в DRAFT) |
| **Method Assignment** (9B) | OTK, NDT, CHIEF | OTK, NDT, CHIEF | — | те же |
| **Method Execution** (9C, ADR-016) | OTK, NDT, CHIEF | OTK, NDT, CHIEF | `LAB_CONFIRMED` (**не** решение ОТК) | новой редакцией |
| **Laboratory Conclusion** (9C) | OTK, **OGS**, CHIEF | те же | lifecycle `DRAFT→PREPARED→LAB_APPROVED→ISSUED` | новой редакцией |
| **Engineering Evaluation** (9D-2, ADR-021) | **OGS** (prepare) | OGS | **CHIEF** (fix / set-effective / confirm-review); ⚠ `EVAL_SAME_ACTOR_REVIEW` — ревью своей работы запрещено | новой ревизией |
| **Quality Decision** (10A, ADR-027) | **OGS** (CREATE/SUBMIT) | OGS | **OTK** (RETURN/DECIDE); CHIEF **не участвует** | DRAFT — свободно; после SUBMIT неизменяемо |
| **Defect Disposition** (9D-4, ADR-024) | OGS, CHIEF (prepare) | OGS, CHIEF | **OTK** (APPROVE), **CHIEF** (ACTIVATE, override с reason+audit) | supersede: OGS, CHIEF |

Границы, которые **соблюдены**:

- `LAB_CONFIRMED` / `ISSUED` явно **не** является решением ОТК (ADR-016) → лабораторное
  заключение отделено от решения качества.
- `DIRECT_LAB_CONFIRMATION` **не поддержан** (`method_execution_workflow.py`):
  лаборатория не подтверждает сама себя через систему — внутренние роли лишь
  регистрируют внешний документ.

---

## 4. Detected Risks

### Conflict A — один пользователь создаёт + утверждает + принимает решение

**Статус: частично не закрыт (R-1).**

- На уровне **ролей** — предотвращён: CREATE/SUBMIT требуют `OGS_ENGINEER`, DECIDE
  требует `OTK_INSPECTOR` (`quality_decision_workflow.py`).
- На уровне **личности** — **НЕ предотвращён**: метод `decide`
  (`quality_decision_services.py`) не сравнивает `actor_worker_id` с
  `created_by_worker_id`. Работник с обеими ролями в одном scope проходит весь путь
  `CREATE → SUBMIT → DECIDE` сам. Контраст: `EngineeringEvaluation` запрещает ревью
  своей работы (`EVAL_SAME_ACTOR_REVIEW`). → несогласованность канона.

### Conflict B — одна роль имеет EXECUTE и APPROVE одновременно

**Статус: в `QualityDecision` закрыт; сквозная концентрация у OTK/CHIEF — под контролем.**

- В `QualityDecision`: OGS = EXECUTE (create/submit), OTK = APPROVE (decide) — разделены.
- OTK совмещает запись Method Execution (технический факт) и финальный DECIDE.
  Смягчено тем, что DECIDE опирается на **независимую** `EngineeringEvaluationRevision`
  (готовит OGS, вводит в действие CHIEF), а не на собственные результаты OTK.
- Наибольшая концентрация EXECUTE+APPROVE — у `CHIEF_WELDER` в disposition. Но в
  `QualityDecision` CHIEF исключён — верное решение.

### Conflict C — лабораторное заключение как финальное решение без независимого Quality Decision

**Статус: закрыт архитектурно.** `QualityDecision` введён как независимый шаг **над**
`EngineeringEvaluation` и **перед** `Defect` (ADR-027 §B). Лабораторное заключение —
технический факт, не приёмка. Самоподтверждение лаборатории невозможно.

### Conflict D — OTK и OGS с пересекающимися полномочиями без явного разделения

**Статус: границы решений чистые; пересечение — только в совместном авторстве.**

- Пересечение: Laboratory Conclusion write (OTK+OGS+CHIEF), регистрация внешнего
  лаб-документа (OTK+OGS+CHIEF).
- Два инварианта **соблюдены**:
  - **OTK не выполняет инженерных функций**: отсутствует в `EVALUATION_PREPARE_ROLES`
    (только OGS) и `EVALUATION_FIX_ROLES` (только CHIEF).
  - **OGS не выполняет инспекционных функций**: отсутствует в
    `ASSIGNMENT_WRITE_ROLES` / `EXECUTION_WRITE_ROLES` (OTK+NDT+CHIEF).
- Остаточный риск: соавторство `LaboratoryConclusion` размывает ответственность, но
  заключение — не решение. → документировать явной матрицей (см. §B.3 проекта ADR).

### Conflict E — override CHIEF_WELDER нарушает аудит/lifecycle

**Статус: в `QualityDecision` override отсутствует; аудит-риск — в другом (R-2).**

- В `QualityDecision` у CHIEF **нет** override (ADR-027 §E). Осознанное следствие: без
  действующего OTK ни одно решение не достигнет `DECIDED` — задокументированный жёсткий
  стоп.
- Где override есть (disposition/inspection) — он требует `reason` + audit (ADR-024).
- Настоящий аудит-риск — **не** override, а R-2: снимок роли/scope для
  `QUALITY_DECISION_DECIDED/_RETURNED` слабее immutable authorization snapshot
  ADR-024 §E.1 (`actor_role_code` + `actor_scope_type` + `actor_scope_id` +
  `valid_from/valid_to`).

---

## 5. Architectural Options

### Variant A — Quality Decision полностью у OTK (OTK и создаёт, и решает)

- **Плюсы:** единый владелец приёмки; простая ответственность.
- **Минусы:** ломает принятый ADR-027; OTK решает на основе им же сформулированного
  основания → возврат Conflict A на уровень роли; OTK не носитель инженерной оценки.
- **Риски:** регресс SoD; переписывание реализованного контура.

### Variant B — Совместное OGS + OTK (текущая модель ADR-027)

- **Плюсы:** OGS формирует техническое основание, OTK независимо принимает — чистый SoD
  на уровне ролей; согласуется с ADR-021/024; уже реализовано.
- **Минусы:** не закрывает person-level SoD (R-1) и audit snapshot (R-2) без доработки;
  жёсткая зависимость от наличия effective OTK.
- **Риски:** при совмещении ролей одним лицом (R-3) — обход SoD.

### Variant C — Авторитет зависит от типа события (техническое→OGS, приёмка→OTK, производственное→CHIEF)

- **Плюсы:** гибкость; концептуально красиво.
- **Минусы:** `QualityDecision` по определению — **одно** решение качества (result:
  ACCEPTED / NOT_CONFIRMED / DEFECT_CONFIRMED), а не набор разнотипных; ветвление
  авторитета внутри одной сущности усложнит lifecycle и аудит; CHIEF в контуре QD
  исключён осознанно.
- **Риски:** размытие границы «кто решает качество»; противоречие ADR-027 §E.

---

## 6. Recommendation

**Recommended Architecture: Variant B (сохранить ADR-027) + консолидирующий ADR,
закрывающий R-1/R-2/R-3.**

**Почему:**

- Variant B — единственный, где «носитель технической основы» (OGS/CHIEF через
  EngineeringEvaluation) и «носитель приёмки» (OTK) структурно разделены, и это уже
  принято и реализовано.
- A и C либо возвращают Conflict A на уровень роли, либо противоречат принятому канону
  и природе `QualityDecision` как единого решения.
- Реальные дыры — не в выборе авторитета, а в **person-level SoD**, **консистентности
  аудита** и **несовместимых ролях**. Их закрывает отдельный ADR, не меняя авторитета.

**Какие ADR нужны:**

- Новый: «Quality Decision RBAC Consolidation» (проект — §7). Возможно вынесение нормы
  о несовместимых ролях (R-3) в отдельный сквозной RBAC-ADR, если охват шире quality.

---

## 7. Proposed ADR Draft — Quality Decision RBAC Consolidation

**Статус:** `PROPOSED` · **Контур:** Quality / QualityDecision governance ·
**Task:** AS-02

**Опирается на:** ADR-027 (принятая модель `OGS → OTK`, не отменяется) · ADR-024
(стандарт immutable authorization snapshot §E.1) · ADR-021 (прецедент person-level SoD
`EVAL_SAME_ACTOR_REVIEW`) · ADR-016 (граница «лаб-заключение ≠ решение ОТК») · ADR-006.

**Уточняет (не отменяет):** ADR-027, ADR-019, ADR-021.

### A. Проблема и контекст

`ADR-027` (ACCEPTED) разделил `QualityDecision` на уровне **ролей**: `OGS_ENGINEER`
создаёт/отправляет, `OTK_INSPECTOR` возвращает/принимает, `CHIEF_WELDER` не участвует.
Аудит AS-02 выявил три сквозных пробела, которые ADR-027 не закрывает:

1. **Нет person-level SoD** — `decide` не сравнивает `actor_worker_id` с
   `created_by_worker_id`; носитель обеих ролей проходит `CREATE → SUBMIT → DECIDE`
   сам (Conflict A на уровне личности).
2. **Несогласованность с каноном** — `EngineeringEvaluation` (ADR-021) уже запрещает
   ревью своей работы; `QualityDecision` — решение более высокого уровня — нет.
3. **Аудит слабее ADR-024** — `quality_audit_events` хранит только `actor_worker_id`;
   ADR-027 §H оставляет snapshot рекомендацией, а не нормой.
4. **Совмещение несовместимых ролей** (`OGS_ENGINEER` + `OTK_INSPECTOR` в одном scope)
   нигде не ограничено — делает (1) практически эксплуатируемым.

Не является проблемой (не переоткрывается): отделение лаб-заключения от решения
(ADR-016); INV-1 (OTK не делает инженерную оценку); INV-2 (OGS не делает инспекционное
исполнение); отсутствие override у CHIEF в QD (ADR-027 §E).

### B. Решение

Авторитет решения сохраняется без изменений (`OGS create → OTK decide`). Добавляются
четыре нормы.

**B.1. Person-level Separation of Duties (закрывает R-1, R-2 частично).**
Исполнитель `DECIDE` обязан отличаться от создателя и от отправителя:

```text
DECIDE.actor_worker_id != QualityDecision.created_by_worker_id
DECIDE.actor_worker_id != (worker, выполнивший SUBMIT_FOR_REVIEW)
```

- Проверка — service-level, в `decide` под тем же lock, до мутации статуса.
- Новый код ошибки: `QD_SAME_ACTOR_DECIDE`, HTTP `409`.
- Прецедент: `EVAL_SAME_ACTOR_REVIEW` (ADR-021).
- Для `RETURN` тот же запрет — открытая точка C-2.

**B.2. Обязательный immutable authorization snapshot (закрывает R-2).**
Для событий `QUALITY_DECISION_DECIDED` и `QUALITY_DECISION_RETURNED` snapshot
обязателен и неизменяем, состав — по ADR-024 §E.1:

```text
authorization_snapshot = {
  actor_worker_id, actor_role_code,
  actor_scope_type, actor_scope_id,
  role_valid_from, role_valid_to,
  snapshot_status            # CONFIRMED | LEGACY_AUTHORIZATION_SNAPSHOT
}
```

- Хранение: строго специфицированный ключ `authorization_snapshot` в `new_values` JSONB
  (расширение таблицы колонками — альтернатива, C-1). Это **норма**, а не рекомендация.
- Для `CREATED` / `SUBMITTED` / `SUPERSEDED` снимок роли желателен, не обязателен.

**B.3. Каноническая матрица пересечения OGS/OTK (формализует Conflict D).**

| Инвариант | Механизм в коде |
|---|---|
| **INV-1.** `OTK_INSPECTOR` не выполняет инженерную оценку | OTK нет в `EVALUATION_PREPARE_ROLES` / `EVALUATION_FIX_ROLES` |
| **INV-2.** `OGS_ENGINEER` не выполняет инспекционное исполнение | OGS нет в `ASSIGNMENT_WRITE_ROLES` / `EXECUTION_WRITE_ROLES` |

Пересечение OGS/OTK допускается **только** в соавторстве не-решающих записей
(Laboratory Conclusion, регистрация внешнего лаб-документа).

**B.4. Политика несовместимых ролей (закрывает R-3).**
Одновременное наличие у одного работника действующих ролей `OGS_ENGINEER` и
`OTK_INSPECTOR` в пересекающемся scope — запрещённая комбинация.

- Уровень: RBAC-фреймворк (`hr` / `permissions`), сквозной.
- MVP: минимум детектирующее предупреждение при назначении роли; цель — блокирующая
  проверка.
- Возможен вынос в отдельный RBAC-ADR при более широком охвате.

### C. Открытые точки

| № | Вопрос | Рекомендация |
|---|---|---|
| C-1 | Snapshot в `new_values` JSONB или расширить `quality_audit_events` колонками (как ADR-024)? | JSONB для MVP; колонки — при общей ревизии audit-модели |
| C-2 | Распространять ли person-level запрет на `RETURN`? | Да, для симметрии; не блокер MVP |
| C-3 | B.4 — блокирующая или детектирующая проверка в MVP? | Детектирующая сейчас, блокирующая в целевом RBAC |
| C-4 | Нужно ли поле `submitted_by_worker_id` в модели (для B.1 против submit)? | Да, если submit-actor не восстановим из audit детерминированно |

### D. Границы (что ADR не делает)

- Не меняет авторитет решения (`OGS create → OTK decide`).
- Не вводит новых ролей и статусов.
- Не трогает lifecycle `DRAFT/UNDER_REVIEW/DECIDED/SUPERSEDED` и supersede-механизм
  ADR-027 §G.
- Не переоткрывает исключение `CHIEF_WELDER` (ADR-027 §E).

---

## 8. Implementation Impact (для будущего блока, не сейчас)

| Слой | Изменение |
|---|---|
| models | опц. `submitted_by_worker_id` (C-4); опц. колонки snapshot (C-1) |
| services | проверка same-actor в `decide` (и опц. `return`); формирование snapshot |
| workflow | код `QD_SAME_ACTOR_DECIDE`; pure-функция валидации SoD |
| API | 409 на self-decide; обязательный snapshot в теле события |
| tests | RBAC-матрица; позитив/негатив same-actor; полнота snapshot; сценарий носителя двух ролей |
| audit | приведение `QUALITY_DECISION_*` к стандарту ADR-024 §E.1 |
| RBAC (сквозное) | механизм B.4 в `hr` / `permissions` |

---

## Приложение A — Полная RBAC-матрица quality-контура

Сокращения: **OGS** = `OGS_ENGINEER` (WELDING_ENGINEER) · **CHIEF** = `CHIEF_WELDER` ·
**OTK** = `OTK_INSPECTOR` · **NDT** = `NDT_SPECIALIST` · **PTO** = `PTO_ENGINEER` ·
**FRM** = `FOREMAN` · **MST** = `MASTER` · `NDT_LAB` = роль компании в проекте.

### A.1. Действия (авторитет) по этапам

| Этап (Task / ADR) | Действие | OGS | CHIEF | OTK | NDT | FRM | MST | Источник |
|---|---|:--:|:--:|:--:|:--:|:--:|:--:|---|
| Inspection Request (9A) | CREATE / UPDATE(DRAFT) / REQUEST / CANCEL | + | + | | | | | `INSPECTION_LIFECYCLE_ROLES` |
| | Override отсутствия готовности СМР | | + | | | | | `INSPECTION_OVERRIDE_ROLES` |
| | Подтверждение производственной готовности (СМР) | | | | | + | + | `PRODUCTION_READINESS_ROLES` |
| Method Assignment (9B) | WRITE (назначить метод) | | + | + | + | | | `ASSIGNMENT_WRITE_ROLES` |
| Method Execution (9C / ADR-016) | WRITE (выполнение/результаты) | | + | + | + | | | `EXECUTION_WRITE_ROLES` |
| | Регистрация внешнего лаб-документа | + | + | + | | | | `EXTERNAL_REGISTRATION_ROLES` |
| | `DIRECT_LAB_CONFIRMATION` | — | — | — | — | — | — | **UNSUPPORTED** |
| Laboratory Conclusion (9C) | WRITE (`DRAFT→PREPARED→LAB_APPROVED→ISSUED`) | + | + | + | | | | `CONCLUSION_WRITE_ROLES` |
| Engineering Evaluation (9D-2 / ADR-021) | PREPARE (create / revision / request-review) | + | | | | | | `EVALUATION_PREPARE_ROLES` |
| | FIX / SET-EFFECTIVE / CONFIRM-REVIEW / RETURN | | + | | | | | `EVALUATION_FIX_ROLES` |
| | WITHDRAW | + | + | | | | | `EVALUATION_WITHDRAW_ROLES` |
| | ревью собственной работы | \_ | \_ | \_ | \_ | \_ | \_ | **запрещено** `EVAL_SAME_ACTOR_REVIEW` |
| Quality Decision (10A / ADR-027) | CREATE / UPDATE(DRAFT) / SUBMIT_FOR_REVIEW | + | | | | | | `QD_CREATE/UPDATE/SUBMIT_ROLES` |
| | RETURN | | | + | | | | `QD_RETURN_ROLES` |
| | DECIDE (приёмка/отклонение) | | | + | | | | `QD_DECIDE_ROLES` |
| | person-level SoD на DECIDE | — | — | — | — | — | — | **отсутствует** (R-1) |
| Defect Disposition (9D-4 / ADR-024) | CREATE / PREPARE | + | + | | | | | `DISPOSITION_CREATE/PREPARE_ROLES` |
| | APPROVE | | + | + | | | | `DISPOSITION_APPROVE_ROLES` |
| | ACTIVATE | | + | | | | | `DISPOSITION_ACTIVATE_ROLES` |
| | CANCEL / OVERRIDE (reason+audit) | | + | | | | | `DISPOSITION_CANCEL/OVERRIDE_ROLES` |
| | SUPERSEDE | + | + | | | | | `DISPOSITION_SUPERSEDE_ROLES` |

### A.2. Чтение (visibility) по этапам

| Этап | OGS | CHIEF | OTK | NDT | PTO | FRM | MST |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Inspection Request (чтение заявки) | + | + | + | + | + | + | + |
| Inspection readiness (чтение) | + | + | + | | + | + | + |
| Assignment / Execution / Lab Conclusion / Evaluation / Disposition / Quality Decision | + | + | + | + | + | + | + |

Все write-контуры используют единый `INSPECTION_READ_ROLES` (все 7 ролей). NDT не видит
`readiness` заявки до Task 9B.

### A.3. Концентрация полномочий по ролям

| Роль | Что делает в контуре | EXECUTE | APPROVE/DECIDE | Комментарий SoD |
|---|---|:--:|:--:|---|
| OGS | заявка, лаб-заключение (соавтор), инженерная оценка (prepare), создание QD, disposition (create/prepare/supersede) | + | — (в QD не решает) | Носитель технического основания. Не инспектирует (INV-2). |
| OTK | назначение/выполнение (write), лаб-заключение (соавтор), DECIDE QD, disposition APPROVE | + | + | Совмещает запись execution и приёмку → смягчено независимой EE-ревизией. Не делает инженерную оценку (INV-1). |
| CHIEF | почти везде: заявка/override, назначение/выполнение, лаб-заключение, EE set-effective, disposition create+approve+activate+cancel+override | + | + | Максимальная концентрация. В `QualityDecision` исключён осознанно (ADR-027 §E). |
| NDT | назначение/выполнение (write) | + | — | Чисто исполнительная. |
| FRM / MST | подтверждение производственной готовности (СМР) | + | — | Вне контроля качества. |
| PTO | только чтение | — | — | Наблюдатель. |
| NDT_LAB | внешняя лаборатория через `project_companies`; сама себя не подтверждает | — | — | Самоподтверждение заблокировано. |

### A.4. Итоговые наблюдения из матрицы

1. **QualityDecision — единственная точка приёмки без person-level SoD.**
2. Инварианты INV-1 / INV-2 соблюдены матрицей.
3. Пересечение OGS/OTK — только в не-решающем соавторстве.
4. CHIEF — узел концентрации; его исключение из QD — единственный барьер против
   «главный сварщик решает качество сам».

> Не аудировано отдельно: `QualityFinding` (9D-1) — вне прямой цепочки авторитета
> «решение качества»; роли не выгружались.

---

## Источники (сверено с кодом на 2026-07-23, read-only)

- `09_Разработка/backend/app/quality/inspection_workflow.py` — канон ролей, READ_ROLES.
- `09_Разработка/backend/app/quality/method_assignment_workflow.py` — ASSIGNMENT_*_ROLES, `NDT_LAB`.
- `09_Разработка/backend/app/quality/method_execution_workflow.py` — EXECUTION_*_ROLES, EXTERNAL_REGISTRATION, DIRECT_LAB_CONFIRMATION unsupported.
- `09_Разработка/backend/app/quality/laboratory_conclusion_workflow.py` — CONCLUSION_*_ROLES.
- `09_Разработка/backend/app/quality/engineering_evaluation_workflow.py` — EVALUATION_*_ROLES, `EVAL_SAME_ACTOR_REVIEW`.
- `09_Разработка/backend/app/quality/defect_disposition_workflow.py` + `defect_disposition_policy.py` — DISPOSITION_*_ROLES.
- `09_Разработка/backend/app/quality/quality_decision_workflow.py` + `quality_decision_services.py` — QD_*_ROLES, метод `decide` (отсутствие same-actor guard).
- `09_Разработка/backend/app/shared/permissions.py`, `auth.py` — scope-модель, actor.
- `docs/project/ADR-027-quality-decision-core-canon.md`, `ADR-024-...md`; `docs/project/DECISIONS.md` (ADR-016, ADR-019, ADR-021).
