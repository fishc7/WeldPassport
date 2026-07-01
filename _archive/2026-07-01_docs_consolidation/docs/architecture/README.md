# WeldPassport — Architecture Documentation

Этот раздел содержит архитектурную документацию проекта WeldPassport.

## Назначение

Архитектурная документация описывает:

* устройство системы;
* ключевые бизнес-процессы;
* предметную модель;
* структуру Backend и Frontend;
* базу данных;
* API;
* безопасность;
* интеграции;
* архитектурные решения.

## Главный принцип

WeldPassport строится вокруг центральной бизнес-сущности:

**Сварной стык**

Все модули системы связаны с жизненным циклом сварного стыка:

```text
ОК → ОГС → СМР → ПТО → ОТК → Закрытие
```

## Структура раздела

```text
docs/architecture/
├── README.md
├── 00_System_Overview.md
├── 01_Business_Architecture.md
├── 02_Domain_Model.md
├── 03_Context_Diagram.md
├── 04_Container_Architecture.md
├── 05_Component_Architecture.md
├── 06_Database_Architecture.md
├── 07_API_Architecture.md
├── 08_Security_Architecture.md
├── 09_Deployment_Architecture.md
├── 10_Integration_Architecture.md
├── 11_Decision_Log.md
└── adr/
```

## Рекомендуемый порядок чтения

1. `00_System_Overview.md`
2. `01_Business_Architecture.md`
3. `02_Domain_Model.md`
4. `04_Container_Architecture.md`
5. `06_Database_Architecture.md`
6. `07_API_Architecture.md`
7. `08_Security_Architecture.md`

## Правила ведения документации

* Документация обновляется вместе с кодом.
* Архитектурные решения фиксируются в Decision Log или ADR.
* Запрещается создавать дублирующие архитектурные документы в других папках.
* Если архитектура меняется, этот раздел обновляется первым.

## Связанные документы

* `PROJECT_RULES.md`
* `DOMAIN_MODEL.md`
* `ARCHITECTURE_DECISIONS.md`
* `PRODUCT_BACKLOG.md`
* `SPRINT_01.md`
