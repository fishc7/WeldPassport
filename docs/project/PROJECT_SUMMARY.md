# WeldPassport — сводка проекта

> Связанные документы: [[docs/project/CONSTITUTION|Конституция]] · [[docs/ARCHITECTURE|Архитектура]] ·
> [[docs/00_PROJECT_CONTEXT|Контекст проекта]] · [[docs/project/DECISIONS|Решения (ADR)]] ·
> [[docs/project/ARCHITECTURE_GOVERNANCE|Architecture Governance (AGF)]] ·
> [[docs/project/ARCHITECTURE_SESSIONS|Architecture Sessions]] ·
> [[docs/project/UBIQUITOUS_LANGUAGE|Ubiquitous Language]] ·
> [[docs/project/ROADMAP|Дорожная карта]] · [[docs/project/PROJECT_EXECUTION_MAP|Карта выполнения]].

## Назначение

WeldPassport — внутренняя система для отдела главного сварщика и участников сварочного производства.

> **Сначала производство. Потом архитектура. Потом код.**

Управление архитектурой — [[docs/project/ARCHITECTURE_GOVERNANCE|AGF]] ·
[[docs/project/CONSTITUTION#5. Architecture Governance|Конституция §5]] ·
[[docs/project/CONSTITUTION#6. Архитектурные сессии|§6 (Sessions)]] ·
канонический язык — [[docs/project/CONSTITUTION#4. Архитектурный принцип №2. Канонический язык проекта|§4 (принцип №2)]] ·
[[docs/project/UBIQUITOUS_LANGUAGE|Ubiquitous Language]] ·
совместное проектирование — [[docs/project/CONSTITUTION#3. Архитектурный принцип №1. Эксперт предметной области + архитектор|§3 (принцип №1)]].

Цель системы — обеспечить электронный учёт, контроль и прослеживаемость сварочного производства: от организации проекта и персонала до сварных соединений, контроля, исполнительной документации и закрытия работ.

## Основная идея

Система должна объединять:

- проекты и организации;
- персонал и допуски сварщиков;
- сварные соединения;
- изометрии и чертежи;
- журналы сварки;
- контроль качества и НК;
- исполнительную документацию;
- периодику КСС.

Отложенные модули (не входят в активный MVP, см. [[docs/project/DECISIONS#ADR-003. Исключение модуля нормирования из активного MVP|ADR-003]]):

- нормативы времени и калькулятор трудозатрат (`norms.*`).

## Ролевая цепочка

В системе принята производственная цепочка:

```text
ОК → ОГС → СМР → ПТО → ОТК → Закрытие
```

Расшифровка:

- **ОК** — работники, кадры, подразделения, должности, производственные роли (`hr.*`);
- **ОГС** — профиль сварщика, допуски, WPS, PQR, технология сварки (`welding.*`);
- **СМР** — фактическое выполнение и назначения на работу;
- **ПТО** — исполнительная документация (**не** технологические решения по сварке);
- **ОТК** — контроль качества;
- **Закрытие** — полная история стыка.

Границы доменов — [[docs/project/CONSTITUTION|Конституция §8]] · [[docs/project/ADR-006-domain-ownership-matrix|ADR-006: матрица владения]] ·
[[docs/project/ADR-007-joint-lifecycle-and-engineering-model|ADR-007: жизненный цикл стыка]] ·
[[docs/project/DECISIONS#ADR-008. Каноническая модель предметной области WeldPassport (Session 003)|ADR-008: каноническая модель Production/Joints MVP]] ·
[[docs/project/DECISIONS#ADR-009. Production/Joints MVP — физическая модель БД, события и API|ADR-009: физическая модель БД и API Production/Joints MVP]] ·
[[docs/project/DECISIONS#ADR-010. Joint MVP — расширенная модель, двойное согласование, история ревизий и bulk-импорт|ADR-010: расширенная модель Joint, двойное согласование]] ·
[[docs/project/ADR-011-joint-lifecycle-approvals-blocking-scope|ADR-011: жизненный цикл Joint, согласования, блокировки, scope]] ·
[[docs/project/DECISIONS#ADR-012. WeldOperation как неизменяемый производственный факт сварки|ADR-012: WeldOperation — неизменяемый производственный факт]].

## Текущий статус архитектуры (2026-07-12)

- **Architecture Session 003 завершена** — доменная модель Production/Joints MVP
  (ADR-008, решения 003-A — 003-AM).
- **Architecture Session 004 завершена** — физическая модель БД/API (ADR-009,
  решения 004-01 — 004-27); раздел WeldOperation **частично замещён** ADR-012.
- **Architecture Session 005 завершена** — канон производственного факта
  `WeldOperation` (решения 005-A — 005-CE, ADR-012).
- **Инженерный контур реализован** (Tasks 1–7):
  `Project → Line → EngineeringDocument → DocumentRevision → Joint` (ADR-010/011).
- **WeldOperation спроектирован, не реализован** — Tasks **8A — 8F**; к Task 8A
  переходят только после принятия Session 005 и ADR-012.
- **Импорт Excel** — отложенное отдельное решение (не входит в начальный MVP).

План реализации: [[docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP|Engineering Joints MVP — Implementation Plan]].

## Текущее состояние backend (2026-07-06)

| API | Модуль | Статус |
|-----|--------|--------|
| `/api/v1/hr` | `app.hr` | активный |
| `/api/v1/ogs` | `app.welding` | активный |
| `/api/v1` (workers, welders) | `app.workforce` | deprecated |

Схемы БД: `hr` (ОК), `welding` (ОГС). Legacy-таблицы — переходный контур.

## Модель организаций и проектов

В WeldPassport не используется правило «1 фирма = 1 проект».

Принята модель:

```text
companies ↔ projects
```

Связь реализуется через:

```text
project_companies
```

Одна организация может участвовать во многих проектах.

Один проект может включать несколько организаций.

Роль организации в проекте хранится в поле `role`.

Примеры ролей:

```text
customer
general_contractor
welding_contractor
ndt_lab
inspection
designer
```

Каноническое описание находится в:

```text
docs/ARCHITECTURE.md
```

## Базовая иерархия данных

Каноническая иерархия (ADR-007):

```text
Проект
  → Титул / Установка / Блок
    → Объект / Участок
      → Линия
        → Изометрия / чертёж
          → Стык (Joint)
```

Стык создаётся из утверждённой рабочей документации и является **центральным объектом
производственного процесса** (инженерная сущность, ADR-007). Системный идентификатор —
`joint_id` (неизменяемый); проектный номер стыка (`project_joint_no`) — отдельное поле.

События жизненного цикла стыка — WeldOperation, Inspection, NDTInspection,
RepairOperation, ExecutiveDocumentation — привязаны к Joint; модули `production` и
`quality` **работают со стыком**, а не вместо него.

Сварщики — участники операций (`production.weld_operations`), не атрибуты карточки стыка.
Одна `WeldOperation` = один Joint + один фактический сварщик + один этап + один способ
(ADR-012). Подробности — [[docs/project/ADR-007-joint-lifecycle-and-engineering-model|ADR-007]],
[[docs/project/DECISIONS#ADR-012. WeldOperation как неизменяемый производственный факт сварки|ADR-012]].

## WeldOperation — производственный факт (ADR-012)

Канон зафиксирован в
[[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 005|Architecture Session 005]].

| Принцип | Суть |
|---------|------|
| Единица учёта | Один Joint + один сварщик + один этап (`root`/`fill`/`cap`/`back_weld`/`tack`) + один способ |
| Нарушения | Факт сохраняется; несоответствие допуска, WPS или клейма → review ОГС |
| Статусы | Раздельно: lifecycle, подтверждение сварщика, review ОГС |
| Неизменяемость | Завершённая операция не редактируется; исправления — `WeldOperationCorrection` |
| Переварка | Новая операция с признаком `reweld` |
| Вне Task 8 | Локальный ремонт, `RepairOperation`, полный lifecycle Inspection/НК |

Реализация: Tasks **8A** (Core) · **8B** (допуск и WPS) · **8C** (review ОГС) ·
**8D** (корректировки) · **8E** (импорт) · **8F** (границы МТО/ОТК/НК) — см.
[[docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP#Следующий этап — WeldOperation (Session 005)|план]].

> Устаревшие формулировки ADR-009 по WeldOperation (`DRAFT`/`CONFIRMED`/`VOIDED`,
> этапы `ROOT`/`FILL`/`COVER`, блокировка при отсутствии допуска,
> `replaces_operation_id`, ремонт как часть `WeldOperation`) **замещены ADR-012**.

## Ключевые проектные файлы

```text
00_НАВИГАЦИЯ.md
```

Главная навигация по проекту.

```text
AGENTS.md
```

Правила для AI-агентов, Cursor Agent, Claude Code и других помощников.

```text
docs/project/CONSTITUTION.md
```

Главный архитектурный документ проекта.

```text
docs/ARCHITECTURE.md
```

Текущая архитектура системы.

```text
docs/project/DECISIONS.md
```

Журнал архитектурных и проектных решений (ADR).

```text
docs/project/ARCHITECTURE_GOVERNANCE.md
```

Architecture Governance Framework — регламент управления архитектурой (AGF).

```text
docs/project/UBIQUITOUS_LANGUAGE.md
```

Ubiquitous Language — официальный словарь терминов предметной области.

```text
docs/project/ARCHITECTURE_SESSIONS.md
```

Журнал Architecture Sessions — процесс принятия фундаментальных архитектурных решений.

```text
docs/project/ROADMAP.md
```

План развития проекта.

```text
docs/project/PROJECT_SUMMARY.md
```

Краткая сводка проекта.

## Правило работы

Все важные решения должны фиксироваться не только в чате, но и в проектных файлах.

Правило:

```text
Обсудили → приняли решение → зафиксировали в документации → сделали commit
```

Фундаментальные архитектурные решения — **только** по [[docs/project/ARCHITECTURE_GOVERNANCE|AGF]]
([[docs/project/CONSTITUTION#5. Architecture Governance|Конституция §5]] ·
[[docs/project/ARCHITECTURE_SESSIONS|журнал сессий]]).
Новые бизнес-термины — сначала [[docs/project/UBIQUITOUS_LANGUAGE|UBIQUITOUS_LANGUAGE]] (принцип №2, §4).
Код не опережает документацию.

Чат не является единственным источником истины. Источником истины являются файлы проекта.
