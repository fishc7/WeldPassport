# WeldPassport — карта выполнения проекта

Источник состояния проекта: `docs/project/PROJECT_STATUS.yaml`

## Верхний уровень

```mermaid
flowchart LR
    A["Архитектура<br/>90% ✅"] --> B["ОК → Работники<br/>100% ✅"]
    B --> C["ОГС → Допуски сварщика<br/>15% 🔄"]
    C --> D["СМР → Факт выполнения<br/>0% ⏳"]
    D --> E["ПТО → Исполнительная<br/>0% ⏳"]
    E --> F["ОТК → Контроль качества<br/>0% ⏳"]
    F --> G["Закрытие истории стыка<br/>0% ⏳"]

    classDef done fill:#d9f99d,stroke:#65a30d,color:#1a2e05;
    classDef progress fill:#fde68a,stroke:#d97706,color:#451a03;
    classDef planned fill:#e5e7eb,stroke:#6b7280,color:#111827;

    class A,B done;
    class C progress;
    class D,E,F,G planned;