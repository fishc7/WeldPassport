# WeldPassport — карта выполнения проекта

Источник состояния проекта: `docs/project/PROJECT_STATUS.yaml`

## Верхний уровень

```mermaid
flowchart LR
    A["Конституция + архитектура<br/>100% ✅"] --> B["ОК → Работники<br/>100% ✅"]
    B --> C["ОГС → Профиль + допуски<br/>100% ✅"]
    C --> D["СМР → Факт выполнения<br/>0% ⏳"]
    D --> E["ПТО → Исполнительная<br/>0% ⏳"]
    E --> F["ОТК → Контроль качества<br/>0% ⏳"]
    F --> G["Закрытие истории стыка<br/>0% ⏳"]

    classDef done fill:#d9f99d,stroke:#65a30d,color:#1a2e05;
    classDef planned fill:#e5e7eb,stroke:#6b7280,color:#111827;

    class A,B,C done;
    class D,E,F,G planned;
```

## Завершённый этап: стабилизация ОК/ОГС (2026-07-06)

- [[docs/project/CONSTITUTION|Конституция проекта]]
- [[docs/project/ADR-004-ogs-model-stabilization|ADR-004]] — модель `welders` / `admissions` / `stamp_code`
- [[docs/project/ADR-005-legacy-workforce-deprecation|ADR-005]] — deprecated `workforce`
- Сервисный слой: `WeldingService.create_admission` согласован с архитектурой
- Alembic: `WELDING_MANAGED_TABLES` включает `welder_admissions`

## Следующий этап: СМР → production / joints

```mermaid
flowchart TD
    S1["Модель стыка<br/>⏳"] --> S2["Назначение на работу<br/>⏳"]
    S2 --> S3["Факт сварки + ADR-002<br/>⏳"]
    S3 --> S4["API production<br/>⏳"]

    classDef planned fill:#e5e7eb,stroke:#6b7280,color:#111827;
    class S1,S2,S3,S4 planned;
```

## Где остановились

| Поле | Значение |
|---|---|
| Текущий этап | Стабилизация ОК/ОГС завершена (`ok_ogs_architecture_stabilized`) |
| Ветка | `feature/ogs-welder-admissions-mvp` |
| Фокус | Готовность к этапу production / joints |
| Следующее действие | Спроектировать `production.joints` и жизненный цикл стыка |
| Обновлено | 2026-07-06 |

## Правило ведения проекта

1. Состояние проекта фиксируется в `docs/project/PROJECT_STATUS.yaml`, а не в чате.
2. Архитектурные принципы — в `docs/project/CONSTITUTION.md`.
3. После изменения статуса модуля обновлять YAML и эту карту.
4. Чат — для обсуждения; источник правды — файлы репозитория.
