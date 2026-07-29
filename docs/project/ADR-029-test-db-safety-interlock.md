# ADR-029. Test DB Safety Interlock

Дата: 2026-07-24

Статус: **ACCEPTED**

## Контекст

Интеграционные тесты backend используют тот же `app.shared.db.SessionLocal` и тот же
набор `POSTGRES_*`, что и приложение. Session-scoped autouse fixture запускает
`alembic upgrade head`, а очистка тестовых данных завершает изменения через `commit`.
Отдельный `TEST_DATABASE_URL` пока не реализован.

ADR-025 определяет полный `TEST-DB Foundation` только после B-04 и отдельного runtime
compatibility profile. До выполнения этих prerequisites проекту всё равно нужен
немедленный fail-closed барьер, исключающий случайный запуск текущего набора тестов
против БД из обычного `.env`.

## Решение

До B-04 вводится узкий предварительный gate `TEST-DB-SAFETY-INTERLOCK`.

Перед первым соединением, созданием session и запуском Alembic тестовый bootstrap обязан
проверить одновременно:

1. `WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS` имеет точное значение `YES`;
2. `WELDPASSPORT_TEST_DB_CONFIRM` непустой и точно совпадает с фактическим
   `settings.postgres_db`;
3. имя БД соответствует тестовому шаблону: начинается с `test_`, заканчивается на
   `_test` либо содержит `_test_`;
4. имя БД не входит в denylist системных и рабочих имён:
   `postgres`, `template0`, `template1`, `weldpassport`.

Любое несоответствие завершает pytest до `command.upgrade`, `SessionLocal()` и очистки
данных. Автоматический fallback на обычный `.env` запрещён.

Существующий `_db_available()` и `pytestmark` из `tests/conftest.py` удаляются:
module-level `pytestmark` в `conftest.py` не распространяется на дочерние тестовые
модули и открывает соединение ещё при импорте.

## Границы

Interlock:

- не создаёт тестовую БД;
- не вводит `TEST_DATABASE_URL`;
- не меняет models, migrations, API или доменную логику;
- не переносит `alembic_version`;
- не выполняет B-04;
- не заменяет полный `TEST-DB Foundation` ADR-025;
- не разрешает запуск полного backend regression, пока владелец явно не подготовил
  отдельную PostgreSQL database, потерю которой можно допустить.

Полный `TEST-DB Foundation` после B-04 обязан сравнивать нормализованные test/work DSN,
создавать отдельную ephemeral database для CI и заменить этот временный interlock
целевым механизмом.

## Последствия

Положительное: обычный `pytest` становится fail-closed и не может неявно применить
миграции к БД из `.env`.

Отрицательное: до создания отдельной тестовой БД application tests намеренно
заблокированы. Pure migration contract tests остаются доступными.

## Критерии приёмки

- pure contract tests доказывают отказ без opt-in, без confirmation, при несовпадении,
  при рабочем/системном имени и при нетестовом имени;
- positive contract test допускает только явную безопасную комбинацию;
- guard вызывается до `_apply_migrations`;
- `tests/conftest.py` не подключается к PostgreSQL на import/collection stage;
- изменения ограничены тестовой безопасностью и документацией.
