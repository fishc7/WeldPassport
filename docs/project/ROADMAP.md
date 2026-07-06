# WeldPassport — дорожная карта

> Связанные документы: [[docs/project/CONSTITUTION|Конституция]] · [[docs/project/DECISIONS|Решения (ADR)]] ·
> [[docs/ARCHITECTURE|Архитектура]] · [[docs/project/PROJECT_EXECUTION_MAP|Карта выполнения]].
> Производственные узлы: [[02_Процессы/Сварочные_операции|Сварочные операции]] · [[02_Процессы/Неразрушающий_контроль|НК]].

## Назначение

План развития WeldPassport. Состояние выполнения — `docs/project/PROJECT_STATUS.yaml`.

## Текущий этап (2026-07-06)

**Стабилизация архитектуры ОК/ОГС завершена.**

Реализовано и задокументировано:

- `hr.workers`, `hr.worker_roles` — ОК (`/api/v1/hr`);
- `welding.welders`, `welding.welder_admissions` — ОГС (`/api/v1/ogs`);
- Конституция, ADR-004, ADR-005;
- deprecated `workforce` (legacy).

## Следующий этап

### 1. Production / joints (СМР)

- спроектировать `production.joints`;
- жизненный цикл стыка;
- назначение и факт сварки;
- реализовать ADR-002 (двойной учёт сварщика) в `weld_operations`.

### 2. ОГС v0.2 (по необходимости)

- `welding.stamps`, `welding.certifications`;
- привязка допуска к `project_id`.

### 3. Вывод legacy

- миграция `desktop_ok` на `hr` + `welding`;
- ETL из `РАБОТНИКИ` / `СВАРЩИКИ`;
- снятие роутера `workforce`.

### 4. ПТО, ОТК, закрытие

- исполнительная документация;
- контроль качества и НК;
- периодика КСС;
- закрытие истории стыка.

## Отложено (backlog)

- нормирование времени (`norms.*`) — [[docs/project/DECISIONS#ADR-003. Исключение модуля нормирования из активного MVP|ADR-003]];
- WPS/PQR как полноценный модуль `engineering` — после стабилизации стыков;
- интеграция с 1С, Active Directory.

## Правило изменения архитектуры

Нельзя менять ключевую архитектуру без записи в `docs/project/DECISIONS.md` и
при необходимости — в [[docs/project/CONSTITUTION|Конституции]].

**Сначала процесс → потом архитектура → потом код.**
