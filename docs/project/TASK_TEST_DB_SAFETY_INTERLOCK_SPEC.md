# TEST-DB-SAFETY-INTERLOCK — Implementation Specification

Статус: **ACCEPTED**

Архитектурное основание:
[[docs/project/ADR-029-test-db-safety-interlock|ADR-029]] и
[[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025]].

## Цель

Сделать невозможным неявный запуск текущих PostgreSQL integration tests против БД,
выбранной обычным `.env`, до реализации B-04 и полного TEST-DB Foundation.

## Разрешённые изменения

- `09_Разработка/backend/tests/test_db_safety.py`;
- `09_Разработка/backend/tests/conftest.py`;
- `09_Разработка/backend/migration_contract_tests/test_test_db_safety_interlock.py`;
- документация и project registry/status, относящиеся только к этому gate.

## Запрещённые изменения

- models и migrations;
- backend API и доменная логика;
- B-04, baseline, stamp или перенос `alembic_version`;
- runtime compatibility profile;
- создание или удаление PostgreSQL database;
- чтение/изменение `.env`;
- запуск integration tests до отдельного подтверждённого тестового окружения;
- изменение ограниченной очистки `_purge_test_data`.

## Контракт

```python
def assert_safe_test_database(
    database_name: str,
    *,
    destructive_opt_in: str | None,
    confirmed_database_name: str | None,
) -> None:
    ...
```

Функция ничего не возвращает при безопасной комбинации и поднимает
`pytest.UsageError` с сообщением, не содержащим credentials, при любом нарушении.

## Acceptance

```powershell
Set-Location 09_Разработка/backend
<python> -m pytest migration_contract_tests/test_test_db_safety_interlock.py -q
<python> -m pytest migration_contract_tests -q
<python> -m compileall tests/test_db_safety.py tests/conftest.py
git diff --check
```

Application tests и Alembic commands в этом gate не запускаются.
