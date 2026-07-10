# WeldPassport — журнал Architecture Sessions

> **Architecture Session** — процесс принятия фундаментальных архитектурных решений.  
> **ADR** — документированный результат процесса.  
> Это **разные сущности**: сессия фиксируется здесь; решения — в ADR.

Связано: [[docs/project/ARCHITECTURE_GOVERNANCE|AGF]] ·
[[docs/project/CONSTITUTION#6. Архитектурные сессии|Конституция §6]] ·
[[docs/project/CONSTITUTION#2. Архитектурный принцип №0. Сначала архитектурная сессия — потом код|Принцип №0]] ·
[[docs/project/DECISIONS|Журнал ADR]] · [[docs/ARCHITECTURE|ARCHITECTURE]].

---

## Назначение

Этот документ — **официальный журнал архитектурных сессий** проекта WeldPassport.

Каждая запись содержит:

| Поле | Описание |
|------|----------|
| **Номер** | Порядковый номер сессии (`001`, `002`, …) |
| **Дата** | Дата проведения или завершения |
| **Тема** | Предмет обсуждения |
| **Краткое описание** | Контекст и цель сессии |
| **Принятые решения** | Список зафиксированных решений |
| **Связанные ADR** | ADR, созданные или обновлённые по итогам сессии |
| **Статус** | `В работе` · `Завершена` · `Отменена` |

---

## Правило завершения сессии

**Architecture Session не считается завершённой**, пока:

1. решения не зафиксированы в этой записи;
2. ADR не создан или не обновлён;
3. Конституция не обновлена (если затронуты принципы или границы);
4. `ARCHITECTURE.md` и `PROJECT_SUMMARY.md` синхронизированы;
5. связанные документы приведены в соответствие с решениями.

Только после статуса **«Завершена»** допускается реализация в коде.

---

## Формат процесса сессии

1. Вопрос.
2. Анализ.
3. Обсуждение.
4. Архитектурное решение.
5. Фиксация решения (запись в этом журнале).
6. Создание или обновление ADR.
7. Обновление Конституции.
8. Синхронизация `ARCHITECTURE.md` и `PROJECT_SUMMARY.md`.
9. Реализация в коде — **после** завершения сессии.

---

## Architecture Session 001

| | |
|---|---|
| **Номер** | 001 |
| **Дата** | 2026-07-06 |
| **Тема** | Основы инженерной модели Joint и жизненного цикла сварного соединения |
| **Статус** | Завершена |

### Краткое описание

Первая архитектурная сессия WeldPassport. Зафиксированы правила появления,
идентификации, иерархии и жизненного цикла сварного стыка (Joint), а также
разделение инженерной, производственной и документальной моделей.

### Принятые решения

1. Центральная производственная сущность — **Joint**.
2. Joint рождается из **утверждённой РД**.
3. Без РД Joint существовать не может.
4. `joint_id` — неизменяемый системный идентификатор.
5. `project_joint_no` — отдельный бизнес-атрибут (не PK).
6. Каноническая иерархия проекта: Проект → Титул/Установка/Блок → Объект → Линия → Изометрия → Стык.
7. Joint **никогда не удаляется**; при смене РД — `CANCELLED` или `SUPERSEDED`.
8. Существенное изменение в ревизии РД создаёт **новый Joint**.
9. Сварщик **не является свойством** Joint; участник WeldOperation.
10. Разделение инженерной, производственной и документальной моделей; Joint — центральный объект процесса.

### Связанные ADR

- [[docs/project/ADR-007-joint-lifecycle-and-engineering-model|ADR-007 — жизненный цикл стыка и инженерная модель]]

### Синхронизированные документы

- `docs/project/CONSTITUTION.md`
- `docs/ARCHITECTURE.md`
- `docs/project/PROJECT_SUMMARY.md`
- `docs/project/DECISIONS.md`

---

## Architecture Session 002

| | |
|---|---|
| **Номер** | 002 |
| **Дата** | 2026-07-07 |
| **Тема** | Предметная модель WeldPassport на основе реальных документов |
| **Статус** | В работе |

### Краткое описание

Сессия посвящена фиксации архитектурных выводов после анализа реальных
производственных документов: Weld Log, Line List, ISO, LST-NK, журнал НК,
журнал PWHT, НАКС, АЦСТ, WPS/ТКС, допускные листы, приказы по клеймам,
кадровые и квалификационные документы.

Цель сессии — уточнить предметную модель WeldPassport как цифровой модели
жизненного цикла сварного соединения и подготовить пакет решений для отдельных ADR.

### Принятые решения (в рамках сессии)

1. **Главный вывод:** WeldPassport — это цифровая модель жизненного цикла
   сварного соединения, а не просто журнал сварки.
2. **Центральный объект:** Joint (сварочный стык) рождается из инженерной
   документации и проходит жизненный цикл производственных событий.
3. **Инженерный контур:** `Project → Line → Isometric → Joint`.
4. **Кадрово-квалификационный контур:**
   `Person/Worker → Role → Welder → Stamp → NAKS → WelderAdmission`.
5. **Организационно-технологический контур:**
   `Company → ACST → WPS/TKS → область применения технологии`.
6. **Производственный контур:**
   `Joint → WeldOperation → VT/Inspection → NDT → PWHT → Repair → ReInspection → Joint status`.
7. **Важная граница:** исполнительная документация, гидроиспытания и передача
   заказчику относятся к будущему модулю ПТО и пока не входят в ядро ОГС.
8. **Открытые вопросы:**
   - нужен ли отдельный Engineering ADR;
   - нужен ли отдельный Production Events ADR;
   - какие термины переводить из Черновик в Канон в `UBIQUITOUS_LANGUAGE.md`;
   - как связать реальные журналы с сущностями системы.
9. По итогам Session 002 требуется подготовка целевого пакета архитектурных
   решений для последующей фиксации в ADR.

### Подготовка к ADR (ещё не ADR)

- Сформировать draft Engineering ADR по инвариантам контура
  `Project → Line → Isometric → Joint`.
- Сформировать draft Production Events ADR по событиям
  `WeldOperation / Inspection / NDT / PWHT / Repair / ReInspection`.
- Подготовить список терминов `UBIQUITOUS_LANGUAGE.md` для перевода в статус «Канон».
- Подготовить правила трассировки реальных журналов (Weld Log, LST-NK, журнал НК,
  журнал PWHT и др.) к сущностям доменной модели.
- Определить границу MVP-ядра ОГС и будущего ПТО-модуля в терминах данных и событий.

### Связанные ADR

- TBD (решения Session 002 готовятся к вынесению в отдельные ADR)

### Синхронизированные документы

- TBD (после утверждения отдельных ADR)

---

## Architecture Session 003

| | |
|---|---|
| **Номер** | 003 |
| **Дата** | 2026-07-08 — 2026-07-10 |
| **Тема** | Каноническая модель предметной области WeldPassport |
| **Статус** | Завершена |

### Краткое описание

Третья архитектурная сессия. Цель — зафиксировать каноническое ядро
engineering-модели: роли СМР и FOREMAN, инженерную привязку Joint,
универсальный инженерный источник EngineeringDocument, сущность Line,
пакеты документации, правила создания и идентификации стыка, многоуровневую
классификацию типа соединения, геометрию и материалы Joint.

Сессия уточняет и развивает выводы Session 001 (ADR-007) и Session 002
без отмены центральной роли Joint и разделения инженерной / производственной
моделей.

### Принятые решения (блок 003-A — 003-L)

| ID | Тема |
|----|------|
| **003-A** | СМР — производственный контур, не системная роль; факт сварки подтверждает **FOREMAN** |
| **003-B** | Минимальная инженерная привязка Joint: `draft` / `confirmed`; ПТО и/или ОГС подтверждают до закрытия ИД |
| **003-C** | **EngineeringDocument** — минимальный инженерный источник Joint в MVP |
| **003-D** | **Line** — самостоятельная инженерная сущность, не текстовое поле документа |
| **003-E** | **Isometric** — тип EngineeringDocument; связь с Line через **EngineeringDocumentLine** |
| **003-F** | **DocumentationPackage** — учёт передачи документации (частичный / полный комплект) |
| **003-G** | Joint создаётся из любого подходящего EngineeringDocument, не только из изометрии |
| **003-H** | Один основной `source_engineering_document_id` на Joint |
| **003-I** | Уникальность: `(project_id, line_id, source_engineering_document_id, joint_number)` |
| **003-J** | Многоуровневая классификация типа соединения: WeldShapeType, WeldJointDesignType, ProjectJointType, WeldJointTypeAlias |
| **003-K** | Геометрия и материал — атрибуты Joint (могут подтягиваться из источников, но хранятся на стыке) |
| **003-L** | **Material** / **MaterialGroup** / **MaterialAlias**; связь с допуском сварщика |

### Принятые решения (продолжение блока 003-M — 003-Z)

| ID | Тема |
|----|------|
| **003-M** | Один Joint может иметь несколько WeldOperation; Joint и WeldOperation не тождественны |
| **003-N** | Комбинированная сварка RAD + RD хранится как несколько WeldOperation на один Joint |
| **003-O** | WeldOperation допускает первичную фиксацию без подтверждённой WPS; технологическое подтверждение обязательно до закрытия |
| **003-P** | Факт сварки не блокируется из-за непроверенного допуска; для таких операций обязателен статус `requires_ogs_review` |
| **003-Q** | Defect и RepairOperation разделяются: дефект, ремонт и контроль после ремонта — разные сущности |
| **003-R** | RepairOperation и ремонтная WeldOperation (`operation_type = repair`) фиксируются раздельно |
| **003-S** | Inspection и NDTInspection разделяются: общий факт контроля и специализированная НК-детализация |
| **003-T** | HeatTreatmentOperation — отдельное производственно-технологическое событие, не вид Inspection |
| **003-U** | Одна HeatTreatmentOperation может включать несколько Joint через HeatTreatmentOperationJoint |
| **003-V** | Один Joint может иметь несколько HeatTreatmentOperation с явной причиной повтора |
| **003-W** | HardnessInspection — отдельная детализация Inspection для контроля твёрдости |
| **003-X** | Единый файловый механизм: DocumentFile + Attachment вместо `*_file_id` в бизнес-сущностях |
| **003-Y** | Статусы Joint разделяются по контурам (`production_status`, `inspection_status`, `closure_status` и др.) |
| **003-Z** | Финальное закрытие подтверждает роль CLOSURE_RESPONSIBLE после проверки обязательных контуров |

### Обновлённое ядро engineering-модели

```text
Project
 ├── DocumentationPackage
 │    └── EngineeringDocument
 │
 ├── EngineeringDocument
 │    ├── document_type
 │    ├── document_number
 │    ├── revision
 │    └── status
 │
 ├── Line
 │    ├── line_number
 │    ├── material
 │    ├── medium
 │    ├── dn
 │    ├── pressure
 │    ├── temperature
 │    ├── category
 │    └── status
 │
 ├── EngineeringDocumentLine
 │    ├── engineering_document_id
 │    └── line_id
 │
 └── Joint
      ├── project_id
      ├── line_id
      ├── source_engineering_document_id
      ├── joint_number
      ├── weld_shape_type_id
      ├── weld_joint_design_type_id
      ├── project_joint_type_id
      ├── source_joint_type_text
      ├── joint_type_mapping_status
      ├── diameter_dn
      ├── diameter_outer
      ├── thickness
      ├── material_id
      ├── material_text_source
      ├── size_text_source
      ├── engineering_status
      └── status
```

### Обновлённое ядро жизненного цикла Joint (дополнение 003-M — 003-Z)

```text
Project
 └── Line
      └── Joint
           ├── WeldOperation
           ├── Inspection
           │    ├── NDTInspection
           │    └── HardnessInspection
           ├── Defect
           ├── RepairOperation
           │    └── WeldOperation (operation_type = repair)
           ├── HeatTreatmentOperationJoint
           │    └── HeatTreatmentOperation
           ├── DocumentFile / Attachment
           └── closure_status
```

### Цепочка ответственности (уточнение 003-A)

```text
ОК → ОГС → СМР → ПТО → ОТК/НК → Закрытие
```

- ОК создаёт работника.
- ОГС допускает сварщика.
- СМР выполняет производство.
- FOREMAN подтверждает факт сварки от имени СМР.
- ПТО оформляет исполнительную документацию.
- ОТК/НК подтверждают качество.
- Закрытие собирает полную историю стыка.

### Architecture Session 003 — RACI модель Production/Joints MVP

Для Production/Joints MVP зафиксирована RACI-модель ответственности по ключевым
сущностям жизненного цикла стыка. Детали по каждой сущности — решения **003-AB —
003-AL**; сводное архитектурное решение — **003-AM** (ADR-008).

#### Обозначения RACI

| Буква | Роль | Смысл |
|-------|------|-------|
| **R** | Responsible | Выполняет работу, вносит или подтверждает данные |
| **A** | Accountable | Несёт итоговую ответственность за результат |
| **C** | Consulted | Консультируется до или в процессе действия |
| **I** | Informed | Получает информацию о результате |

Участники матрицы: **ОК**, **ОГС**, **СМР**, **FOREMAN**, **ПТО**, **ОТК**, **НК**,
**CLOSURE_RESPONSIBLE**.

#### Таблица ответственности (10 MVP-сущностей)

| ID | Сущность | R | A | C | I |
|----|----------|---|---|---|---|
| **003-AB** | **Project** | ПТО | ПТО / заказчик (по роли в проекте) | ОГС, СМР, генподрядчик | ОТК, НК |
| **003-AC** | **EngineeringDocument** | ПТО | ПТО | ОГС, СМР | ОТК, НК |
| **003-AD** | **Line** | ПТО | ПТО | ОГС, СМР | ОТК, НК |
| **003-AE** | **Joint** | СМР (`draft`); ПТО + ОГС (`confirmed`) | ПТО + ОГС | СМР, ОГС | ОТК, НК, CLOSURE_RESPONSIBLE |
| **003-AF** | **WeldOperation** | СМР | FOREMAN / СМР | ОГС, ПТО | ОТК, НК, ОК |
| **003-AG** | **Inspection** | ОТК (общий контроль); НК (методы НК) | ОТК | НК, ОГС, СМР | ПТО |
| **003-AH** | **Defect** | ОТК | ОТК | НК, ОГС, СМР | ПТО |
| **003-AI** | **RepairOperation** | СМР | ОТК | ОГС, НК | ПТО |
| **003-AJ** | **HeatTreatmentOperation** | СМР | ОГС | ОТК, ПТО | НК |
| **003-AK** | **Attachment / DocumentFile** | владелец связанной сущности (ПТО, НК, СМР, ОГС, ОТК) | владелец связанной сущности | смежные домены | CLOSURE_RESPONSIBLE |

**003-AL** — общие принципы RACI для Production/Joints MVP:

- ПТО и ОГС совместно подотчётны за подтверждение инженерной привязки Joint
  (см. 003-B, 003-AE).
- СМР отвечает за фиксацию производственного факта; FOREMAN подтверждает факт
  сварки (см. 003-A, 003-AF).
- ОТК и НК отвечают за контроль качества; **NDTInspection** и **HardnessInspection**
  — специализированные расширения **Inspection**, а не отдельные пункты базового
  списка из 10 сущностей (см. 003-S, 003-W, 003-AG).
- **DocumentationPackage** — связанный объект документационного контура учёта
  передачи комплектов; не заменяет Project, EngineeringDocument или Line
  (см. 003-F).
- **Joint closure** — процесс финального закрытия стыка; подотчётность несёт
  **CLOSURE_RESPONSIBLE**, не подменяя домены и не заменяя Attachment / DocumentFile
  (см. 003-Z).

### Финальная сводка

**Architecture Session 003 завершена.**

Решения зафиксированы как **003-A — 003-AM** (ADR-008). Результатом сессии является
**каноническая модель Production/Joints MVP**.

**Результаты:**

- определена граница Production/Joints MVP;
- зафиксирована центральная роль Joint;
- определена связь Project → EngineeringDocument / Line → Joint;
- определён жизненный цикл Joint:
  WeldOperation → Inspection / NDTInspection / HardnessInspection → Defect →
  RepairOperation → HeatTreatmentOperation → Closure;
- зафиксирована модель файлов DocumentFile + Attachment;
- зафиксированы раздельные статусы Joint по контурам;
- зафиксирована совместная ответственность СМР, ПТО, ОГС, ОТК/НК и CLOSURE_RESPONSIBLE;
- зафиксирована RACI-модель Production/Joints MVP.

**Следующий этап:** проектирование БД/API Production/Joints MVP.

### Связанные ADR

- [[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)|ADR-008 — каноническая модель предметной области (003-A — 003-AM)]]
- Уточняет [[docs/project/ADR-007-joint-lifecycle-and-engineering-model|ADR-007]] и [[docs/project/ADR-006-domain-ownership-matrix|ADR-006]]

### Синхронизированные документы

- `docs/project/DECISIONS.md` (ADR-008)
- `docs/ARCHITECTURE.md` (краткое описание engineering/joint и lifecycle ядра)
- `docs/project/PROJECT_SUMMARY.md`

---

## Architecture Session 004

| | |
|---|---|
| **Номер** | 004 |
| **Дата** | 2026-07-10 |
| **Тема** | Проектирование БД/API Production/Joints MVP |
| **Статус** | Завершена |

### Краткое описание

Четвёртая архитектурная сессия. Session 003 завершена и зафиксировала минимальное
ядро Production/Joints (ADR-008). На Session 004 проектируются физические границы БД,
связи сущностей, статусы, ограничения и API.

В качестве источников требований проанализированы реальные журналы сварки, ремонта,
контроля, термообработки, справочники типов соединений, данные сварщиков и материалов.

**Код и миграции на этой сессии не создавались.** Session 004 завершена; решения
зафиксированы в ADR-009 и синхронизированы с канонической документацией.

Уточняет: [[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)|ADR-008]] ·
[[docs/project/ADR-007-joint-lifecycle-and-engineering-model|ADR-007]].

### Принятые решения (блок 004-01 — 004-27)

| ID | Тема |
|----|------|
| **004-01** | Двухэтапное создание Joint |
| **004-02** | Два порога готовности Joint |
| **004-03** | Инженерный статус отделён от технической готовности |
| **004-04** | Уникальность номера Joint |
| **004-05** | Поведение Joint при новой ревизии |
| **004-06** | Геометрия соединения и форма шва разделены |
| **004-07** | Материалы — ссылка на каталог плюс исторический снимок |
| **004-08** | Один DN и одна толщина |
| **004-09** | WPS: план и факт разделены |
| **004-10** | Комбинированная сварка через несколько WeldOperation |
| **004-11** | Двойной учёт сварщика |
| **004-12** | Строгая проверка допуска |
| **004-13** | Неизменяемость подтверждённой WeldOperation |
| **004-14** | Единая Inspection |
| **004-15** | FAIL требует Defect |
| **004-16** | Ремонт как отдельный цикл |
| **004-17** | Термообработка как повторяемое событие |
| **004-18** | DocumentFile и универсальные связи |
| **004-19** | Разделение по схемам БД |
| **004-20** | API по предметным контурам |
| **004-21** | Права по владельцам данных |
| **004-22** | Новая роль HEAT_TREATMENT_OPERATOR |
| **004-23** | Производственное состояние Joint вычисляется |
| **004-24** | Условия ACCEPTED |
| **004-25** | Требования контроля наследуются со снимком |
| **004-26** | Импорт Excel — поэтапное решение |
| **004-27** | Сварочные материалы — фактический снимок плюс будущая связь с МТО |

#### 004-01. Двухэтапное создание Joint

- **FOREMAN** / **MASTER** может создать Joint в статусе `DRAFT`.
- Joint должен иметь инженерную привязку.
- **ПТО** проверяет и подтверждает Joint.
- `WeldOperation` разрешено зарегистрировать до подтверждения ПТО, если выполнены
  технические условия.
- Такой Joint попадает в очередь инженерной проверки.

#### 004-02. Два порога готовности Joint

Для создания `DRAFT` обязательны:

- `project`;
- `line`;
- engineering document / isometric;
- `joint_no`.

Перед регистрацией `WeldOperation` дополнительно обязательны:

- `geometry_type`;
- `weld_type`;
- `dn`;
- `thickness`;
- материалы обеих сторон;
- фактический метод сварки.

#### 004-03. Инженерный статус отделён от технической готовности

`engineering_status`:

- `DRAFT`;
- `CONFIRMED`;
- `CANCELLED`;
- `SUPERSEDED`.

`ready_for_welding` является вычисляемым результатом и **отдельно в БД не хранится**.

#### 004-04. Уникальность номера Joint

- Внутренний идентификатор Joint — неизменяемый UUID.
- Номер стыка уникален внутри engineering document / isometric.
- Бизнес-ключ: `project_id` + `engineering_document_id` + `joint_no`.
- Одинаковые `joint_no` разрешены на разных документах / изометриях.
- Это **уточняет** прежнее предварительное решение о проектной уникальности номера
  (см. ADR-008, 003-I).

#### 004-05. Поведение Joint при новой ревизии

- Неизменившийся Joint сохраняет UUID.
- История ревизий не перезаписывается.
- Удалённый Joint получает `CANCELLED`.
- Заменённый Joint получает `SUPERSEDED`.
- Новый или существенно изменённый Joint получает новый UUID.
- Замена связывается через `superseded_by_joint_id`.

#### 004-06. Геометрия соединения и форма шва разделены

- `geometry_type`: `BUTT`, `TEE`, `CORNER`, `LAP`.
- `weld_type`: `BW`, `FW`.
- `standard_joint_code` — необязательное обозначение по ГОСТ, проектному стандарту
  или чертежу.

#### 004-07. Материалы — ссылка на каталог плюс исторический снимок

Для каждой стороны Joint:

- необязательная ссылка на каталог;
- обязательное фактическое обозначение материала.

Изменение каталога не изменяет исторические данные Joint. Сертификаты, плавки и партии
относятся к будущему материальному контуру.

#### 004-08. Один DN и одна толщина

- Joint хранит один `dn` и одну `thickness`.
- Для переходных и разнотолщинных соединений берутся характеристики основной трубы.
- Материалы двух сторон хранятся раздельно.
- `JointComponent` в MVP не создаётся.

#### 004-09. WPS: план и факт разделены

- `Joint.planned_wps_id` — назначение ОГС.
- `WeldOperation.actual_wps_id` — фактически применённая технология.
- Отсутствие или несовпадение WPS устанавливает `requires_ogs_review`.
- Отсутствие WPS само по себе **не блокирует** регистрацию факта, если остальные
  обязательные условия выполнены.

#### 004-10. Комбинированная сварка через несколько WeldOperation

- Один Joint может иметь несколько `WeldOperation`.
- Этапы MVP: `ROOT`, `FILL`, `COVER`, `FILL_COVER`.
- Каждая операция имеет своего сварщика, метод, дату и `actual_wps_id`.
- RAD + RD представляется последовательностью операций.

#### 004-11. Двойной учёт сварщика

- `actual_welder_id` — фактический сварщик, обязателен.
- `documented_welder_id` — сварщик в исполнительной документации, может заполняться
  позднее.
- Несовпадение устанавливает `requires_pto_review`.
- Фактические данные при этом не изменяются.

#### 004-12. Строгая проверка допуска

Перед созданием `WeldOperation` проверяются:

- фактический сварщик;
- активный профиль;
- клеймо;
- метод;
- DN;
- толщина;
- материалы;
- срок действия допуска на дату сварки.

Отсутствие подходящего допуска **блокирует** создание `WeldOperation`. API должен
возвращать конкретные причины отказа. Обход проверки в MVP не предусмотрен.

#### 004-13. Неизменяемость подтверждённой WeldOperation

Статусы:

- `DRAFT` — редактируется;
- `CONFIRMED` — неизменяемый производственный факт;
- `VOIDED` — аннулированная запись, физически не удаляется.

Исправление выполняется новой `WeldOperation` со ссылкой `replaces_operation_id`.

#### 004-14. Единая Inspection

Все виды контроля представлены одной сущностью **Inspection**.

`inspection_type`:

- `VT`;
- `RT`;
- `UT`;
- `PT`;
- `MT`;
- `HARDNESS`;
- `PMI`;
- `FERRITE`.

Общие поля включают Joint, при необходимости WeldOperation, дату, результат, номер
заключения, исполнителя и вложения. Допускается несколько Inspection одного Joint.

#### 004-15. FAIL требует Defect

- Подтверждённая Inspection с результатом `FAIL` должна иметь минимум один Defect.
- Одна Inspection может выявить несколько Defect.
- Defect связан с Joint, Inspection и при необходимости WeldOperation.
- Начальный статус Defect — `OPEN`.
- Закрытие возможно после ремонта и повторного контроля `PASS`.

#### 004-16. Ремонт как отдельный цикл

- `RepairOperation` связывается с одним или несколькими Defect.
- Фактическая ремонтная сварка создаётся как `WeldOperation` с `repair_operation_id`.
- После ремонта создаётся новая Inspection.
- Defect закрывается только после успешного повторного контроля.
- Ремонт **не создаёт** новый Joint.

#### 004-17. Термообработка как повторяемое событие

Каждая `HeatTreatmentOperation` хранит:

- `joint_id`;
- при необходимости `repair_operation_id`;
- порядковый номер;
- вид и способ нагрева;
- дату;
- температуру;
- скорость нагрева;
- выдержку;
- охлаждение;
- оператора-термиста;
- номер диаграммы;
- причину повторной обработки.

Повторные события не перезаписывают предыдущие. Контроль твёрдости оформляется
отдельной Inspection типа `HARDNESS`.

#### 004-18. DocumentFile и универсальные связи

- `DocumentFile` хранит имя, тип, размер, расположение, checksum, автора и дату.
- Связь файлов с предметными объектами реализуется отдельной технической таблицей.
- Один файл может относиться к нескольким объектам.
- Техническая таблица связей **не считается** отдельной предметной сущностью MVP.
- Производственные файлы физически не удаляются.

#### 004-19. Разделение по схемам БД

| Схема | Сущности |
|-------|----------|
| `project` | Project, Line |
| `engineering` | EngineeringDocument, DocumentRevision, Joint |
| `production` | WeldOperation, RepairOperation, HeatTreatmentOperation |
| `quality` | Inspection, Defect |
| `documents` | DocumentFile и технические связи |
| `hr`, `welding` | существующие контуры (без изменений) |

#### 004-20. API по предметным контурам

Группы API:

```text
/api/v1/projects
/api/v1/engineering
/api/v1/production
/api/v1/quality
/api/v1/documents
```

Сущности имеют самостоятельные коллекции. Вложенные GET-маршруты используются для
чтения жизненного цикла конкретного Joint.

#### 004-21. Права по владельцам данных

| Роль | Действия |
|------|----------|
| **FOREMAN** / **MASTER** | создаёт `DRAFT` Joint; регистрирует `WeldOperation` |
| **ПТО** | подтверждает, отменяет и заменяет Joint; уточняет инженерные данные и `documented_welder_id` |
| **ОГС** | назначает WPS; рассматривает технологические отклонения |
| **ОТК** / **INSPECTOR** | регистрирует VT и другие проверки ОТК |
| **НК** | регистрирует НК и Defect |
| **FOREMAN** / **MASTER** | создаёт `RepairOperation` |
| **Оператор-термист** | регистрирует `HeatTreatmentOperation` |

#### 004-22. Новая роль HEAT_TREATMENT_OPERATOR

- Добавляется роль `HEAT_TREATMENT_OPERATOR`.
- Отдельная роль ответственного за ремонт в MVP **не создаётся**.
- **FOREMAN** / **MASTER** отвечает за создание задания и цикла ремонта.
- Результат термообработки подтверждается через контроль ОГС / ОТК.

#### 004-23. Производственное состояние Joint вычисляется

`production_state` **не хранится** как вручную изменяемое поле. Оно рассчитывается из:

- `WeldOperation`;
- `Inspection`;
- открытых Defect;
- `RepairOperation`;
- `HeatTreatmentOperation`.

`engineering_status` и `production_state` являются **разными понятиями**.

#### 004-24. Условия ACCEPTED

Joint считается `ACCEPTED`, когда:

- сварочные операции подтверждены;
- все `required_inspection_types` имеют актуальный `PASS`;
- отсутствуют открытые Defect;
- обязательная термообработка завершена.

#### 004-25. Требования контроля наследуются со снимком

- Line содержит типовой перечень обязательных видов контроля.
- При создании Joint перечень копируется в `required_inspection_types`.
- ПТО / ОТК может уточнить требования конкретного Joint.
- Изменение Line **не переписывает** существующие Joint.
- Новые Joint получают обновлённый перечень.

#### 004-26. Импорт Excel — поэтапное решение

- На начальном этапе MVP используется **ручной / API-контур**.
- Импорт Excel **не отменён**, а **отложен**.
- После стабилизации модели будет выбран **прямой импорт** или **импорт через
  промежуточную проверку**.
- Окончательный вариант импорта пока **не определён**.
- Текущая модель должна учитывать возможность будущего импорта без добавления
  импортных сущностей в MVP.

#### 004-27. Сварочные материалы — фактический снимок плюс будущая связь с МТО

- Фактически использованные сварочные материалы сохраняются как **исторический снимок**.
- Для каждого материала фиксируются тип, марка и при наличии номер партии.
- Используется техническая дочерняя таблица `weld_consumable_usages`.
- Техническая таблица **не считается** отдельной предметной сущностью MVP.
- После появления материального контура допускается необязательная ссылка на
  складскую партию МТО.
- Изменение справочника или складской партии **не изменяет** исторические данные
  `WeldOperation`.

### Подтверждённый раздел 1 — границы БД и связи

```text
Project
 ├── Line
 └── EngineeringDocument
      └── DocumentRevision

Line
 └── Joint ← EngineeringDocument

Joint
 ├── WeldOperation (множество)
 ├── Inspection (множество)
 ├── RepairOperation (множество)
 └── HeatTreatmentOperation (множество)

Inspection → Defect
RepairOperation → устраняет Defect
Ремонтная сварка → WeldOperation (с repair_operation_id)

DocumentFile ↔ предметные объекты (техническая таблица связей)
```

Правила:

- Project содержит Line и EngineeringDocument.
- EngineeringDocument имеет ревизии.
- Joint принадлежит Line и EngineeringDocument.
- Joint сохраняется между ревизиями, если конструкция не изменилась.
- Joint имеет множество WeldOperation, Inspection, RepairOperation и
  HeatTreatmentOperation.
- Defect возникает из Inspection.
- RepairOperation устраняет Defect.
- Ремонтная сварка остаётся WeldOperation.
- DocumentFile связывается с предметными объектами через техническую таблицу.

### Подтверждённый раздел 2 — структура `engineering.joints`

Основные группы полей:

| Группа | Поля |
|--------|------|
| Идентификация | `id`, `project_id`, `line_id`, `engineering_document_id`, `current_revision_id`, `joint_no` |
| Инженерный статус | `engineering_status`, `superseded_by_joint_id` |
| Классификация | `geometry_type`, `weld_type`, `standard_joint_code` |
| Размеры | `dn`, `thickness` |
| Материал 1 | `material_1_catalog_id`, `material_1_name` |
| Материал 2 | `material_2_catalog_id`, `material_2_name` |
| Технология | `planned_wps_id` |
| Контроль | `required_inspection_types`, `heat_treatment_required` |
| Аудит | `created_by`, `created_at`, `updated_at`, `confirmed_by`, `confirmed_at` |

Ограничения:

- уникальность `project_id` + `engineering_document_id` + `joint_no`;
- `DRAFT` требует Project, Line, EngineeringDocument и `joint_no`;
- перед сваркой обязательны типы соединения и шва, DN, толщина и оба материала;
- `CANCELLED` и `SUPERSEDED` запрещают новые производственные события;
- подтверждённый Joint физически не удаляется;
- история связи с ревизиями хранится в технической таблице;
- `ready_for_welding` и `production_state` **вычисляются** API.

### Подтверждённый раздел 3 — структура `production.weld_operations`

Поля:

- `id`, `joint_id`, `repair_operation_id`, `sequence_no`;
- `stage`: `ROOT`, `FILL`, `COVER`, `FILL_COVER`;
- `actual_welder_id`, `documented_welder_id`;
- снимок фактического клейма;
- `welding_method`, `actual_wps_id`, `welding_position`;
- `welded_at`, `passes_count`, `purge_used`;
- `preheat_temperature`, `ambient_temperature`;
- `requires_ogs_review`, `requires_pto_review`;
- `status`: `DRAFT`, `CONFIRMED`, `VOIDED`;
- `replaces_operation_id`, `void_reason`;
- `created_by`, `created_at`, `confirmed_by`, `confirmed_at`.

Правила:

- каждый этап и сварщик оформляются отдельной `WeldOperation`;
- допуск сварщика проверяется перед подтверждением;
- подтверждённая операция неизменяема;
- исправление — `VOIDED` плюс новая операция;
- зарплата и стоимость работ **не входят** в `WeldOperation`;
- сварочные материалы хранятся через `weld_consumable_usages` (см. 004-27).

### Подтверждённый раздел 4 — структура Inspection и Defect

`quality.inspections`:

- `id`, `joint_id`, `weld_operation_id`, `repair_operation_id`;
- `inspection_type`, `inspected_at`, `result`;
- `report_no`, `report_date`;
- `performed_by_worker_id`, `performed_by_company_id`;
- `previous_inspection_id`;
- `status`: `DRAFT`, `CONFIRMED`, `VOIDED`;
- `created_by`, `created_at`, `confirmed_by`, `confirmed_at`.

Результаты: `PASS`, `FAIL`, `CONDITIONAL`.

`quality.defects`:

- `id`, `joint_id`, `inspection_id`, `weld_operation_id`;
- `defect_code`, `description`, `location`;
- `length`, `width`, `depth`;
- `status`: `OPEN`, `IN_REPAIR`, `CLOSED`;
- `closed_by_inspection_id`, `closed_at`;
- `created_by`, `created_at`.

Правила:

- подтверждённый `FAIL` требует минимум один Defect;
- одна Inspection может выявить несколько Defect;
- Defect закрывается только повторной подтверждённой Inspection с `PASS`;
- открытый Defect блокирует `Joint.ACCEPTED`;
- подтверждённые записи физически не удаляются.

### Подтверждённый раздел 5 — RepairOperation и HeatTreatmentOperation

`production.repair_operations`:

- `id`, `joint_id`;
- `repair_no`, `reason`, `started_at`, `completed_at`;
- `excavation_length`, `excavation_width`, `excavation_depth`;
- `preheat_method`, `preheat_temperature`;
- `status`: `PLANNED`, `IN_PROGRESS`, `COMPLETED`, `VOIDED`;
- `created_by`, `created_at`, `completed_by`.

Связь `RepairOperation` с несколькими Defect — техническая таблица `repair_defects`.

Ремонтная сварка — обычная `WeldOperation` с `repair_operation_id`.

`production.heat_treatment_operations`:

- `id`, `joint_id`, `repair_operation_id`;
- `sequence_no`, `treatment_type`, `performed_at`, `repeat_reason`;
- `heating_method`, `temperature_control_method`;
- `target_temperature`, `heating_rate`, `holding_time`, `cooling_method`;
- `operator_worker_id`;
- снимок ФИО / клейма;
- `diagram_no`;
- `status`: `DRAFT`, `CONFIRMED`, `VOIDED`;
- `created_by`, `created_at`, `confirmed_by`, `confirmed_at`.

Правила:

- номер ремонта последователен внутри Joint;
- Defect закрывается **не** ремонтом, а повторной `Inspection.PASS`;
- термообработка повторяема;
- повторная обработка требует причину;
- контроль твёрдости — `Inspection.HARDNESS`;
- история не перезаписывается.

### Подтверждённый раздел 6 — API и переходы состояний

API разделяется по контурам:

```text
/api/v1/projects
/api/v1/engineering
/api/v1/production
/api/v1/quality
/api/v1/documents
```

Joint:

```text
POST   /api/v1/engineering/joints
GET    /api/v1/engineering/joints
GET    /api/v1/engineering/joints/{id}
PATCH  /api/v1/engineering/joints/{id}
POST   /api/v1/engineering/joints/{id}/confirm
POST   /api/v1/engineering/joints/{id}/cancel
POST   /api/v1/engineering/joints/{id}/supersede
GET    /api/v1/engineering/joints/{id}/lifecycle
```

Для `WeldOperation`, `RepairOperation`, `HeatTreatmentOperation` и `Inspection`:

- самостоятельные коллекции;
- отдельные команды `confirm` / `void` и другие допустимые переходы;
- `PATCH` применяется **только** к черновикам.

Ответ Joint API содержит вычисляемые поля:

- `ready_for_welding`;
- `missing_welding_requirements`;
- `production_state`;
- `open_defects_count`;
- `requires_ogs_review`;
- `requires_pto_review`.

Ошибки:

- `404` — не найдено;
- `403` — нет роли / scope;
- `409` — конфликт состояния или уникальности;
- `422` — производственные условия не выполнены, со списком причин.

### Подтверждённый раздел 7 — проверки и тестирование

Уровень БД:

- внешние ключи;
- уникальность Joint в EngineeringDocument;
- CHECK-ограничения статусов и типов;
- положительные значения размеров и режимов;
- уникальная последовательность операций внутри Joint;
- отсутствие физического удаления подтверждённых данных.

Уровень сервисов:

- роли и scope;
- готовность Joint;
- активность сварщика и клеймо;
- допуск по методу, DN, толщине, материалам и дате;
- переходы состояний;
- Defect при `FAIL`;
- повторный `PASS` для закрытия Defect;
- обязательные проверки для `ACCEPTED`.

Обязательные тестовые сценарии:

- минимальный `DRAFT` Joint;
- технически неготовый Joint;
- комбинированная сварка RAD + RD;
- сварщик без подходящего допуска;
- несовпадение actual / documented welder;
- `VOIDED` и замена `WeldOperation`;
- `FAIL` → Defect → Repair → повторный `PASS`;
- повторная термообработка;
- новая ревизия и замена Joint;
- вычисление `ready_for_welding` и `production_state`;
- права ПТО, СМР, ОГС, ОТК и НК.

### Финальная сводка

**Architecture Session 004 завершена.**

- Session 004 завершена.
- Подтверждены решения **004-01 — 004-27**.
- Подтверждены **семь разделов** проекта БД/API.
- Разрешена подготовка **плана реализации**.
- Код, миграции и тесты на архитектурной сессии **не изменялись**.
- Импорт Excel остаётся **отдельным будущим решением**.

### Связанные ADR

- [[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API|ADR-009 — физическая модель БД, события и API (004-01 — 004-27)]]
- Уточняет [[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)|ADR-008]] ·
  [[docs/project/ADR-007-joint-lifecycle-and-engineering-model|ADR-007]] ·
  [[docs/project/ADR-002-double-welder-accounting|ADR-002]]

### Синхронизированные документы

- `docs/project/DECISIONS.md` (ADR-009)
- `docs/ARCHITECTURE.md` (§5.3, активное ядро MVP, API)
- `docs/project/PROJECT_SUMMARY.md`
- `docs/project/UBIQUITOUS_LANGUAGE.md` (уточнение терминов и роли)

---

## Шаблон новой сессии

```markdown
## Architecture Session NNN

| | |
|---|---|
| **Номер** | NNN |
| **Дата** | YYYY-MM-DD |
| **Тема** | … |
| **Статус** | В работе |

### Краткое описание

…

### Принятые решения

1. …

### Связанные ADR

- ADR-…

### Синхронизированные документы

- …
```

---

*Версия журнала: 2026-07-10. Записей: 4 (Session 004 — завершена).*
