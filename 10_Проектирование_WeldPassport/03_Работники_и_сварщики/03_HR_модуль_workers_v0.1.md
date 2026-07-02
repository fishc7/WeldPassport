# HR-модуль ОК — workers v0.1

> Связанные документы: [[05_Роли_и_права/01_ОК_Отдел_кадров/ТЗ/WeldPassport_ОК_ТЗ_v0.1|ТЗ ОК]] ·
> [[docs/ARCHITECTURE#Модель организаций и проектов|Модель организаций]] ·
> [[10_Проектирование_WeldPassport/03_Работники_и_сварщики/01_Модель_данных_Работники_и_сварщики_v0.1|Legacy: работники и сварщики]].

## Назначение

PostgreSQL-схема `hr` — базовая карточка **Работника** для зоны ОК.

Сварщик = Работник + сварочные допуски ОГС (клейма, аттестации) — **не** в `hr.workers`.

## Таблицы

| Таблица | Назначение |
|---|---|
| `hr.departments` | Подразделения организации (`company_id`) |
| `hr.positions` | Справочник должностей (глобальный) |
| `hr.workers` | Кадровая карточка работника |

`company_id` — integer без FK до появления модуля `companies` (ADR-001).

## API

Базовый префикс: `/api/v1/hr`

- `GET/POST/PATCH /departments`
- `GET/POST/PATCH /positions`
- `GET/POST/PATCH /workers`, `POST /workers/{id}/dismiss`, `POST /workers/{id}/activate`

Код: `09_Разработка/backend/app/hr/`

Миграция: `backend/migrations/versions/20260702_02_hr_core.py`

## Следующий этап

- Модуль `companies` и FK с `hr.workers.company_id`
- Связь legacy `РАБОТНИКИ` ↔ `hr.workers` или миграция данных
- Зона ОГС: `worker_stamps`, `worker_certifications`, project access
