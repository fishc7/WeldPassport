# Prompt для Claude Code — TEST-DB-SAFETY-INTERLOCK

Работай только от принятого commit
`24790bc5c3d1b118bf23b76753e4015dc2510541`.

## Цель

Реализовать предварительный fail-closed interlock для PostgreSQL integration tests.
Он должен остановить pytest до первого соединения и до `alembic upgrade head`, если
запуск не подтверждён как разрушительный запуск против отдельной тестовой БД.

## Обязательные источники

- `AGENTS.md`;
- `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md`;
- `docs/project/ADR-029-test-db-safety-interlock.md`;
- `docs/project/TASK_TEST_DB_SAFETY_INTERLOCK_SPEC.md`;
- `09_Разработка/backend/tests/conftest.py`;
- `09_Разработка/backend/app/shared/config.py`.

## Разрешено

- создать `tests/test_db_safety.py`;
- создать pure contract tests в `migration_contract_tests/`;
- изменить `tests/conftest.py` только для вызова guard до Alembic/Session;
- удалить неэффективный `_db_available()` / `pytestmark`;
- обновить относящуюся к gate документацию.

## Запрещено

- подключаться к PostgreSQL;
- запускать application tests;
- запускать Alembic;
- менять `.env`;
- создавать TEST-БД;
- менять models, migrations, API, services или repositories;
- реализовывать B-04 либо полный TEST-DB Foundation;
- ослаблять `_purge_test_data`;
- добавлять fallback на рабочий DSN.

## Требования

Guard допускает запуск только при одновременном выполнении:

1. `WELDPASSPORT_ALLOW_DESTRUCTIVE_TESTS=YES`;
2. `WELDPASSPORT_TEST_DB_CONFIRM` точно совпадает с `settings.postgres_db`;
3. имя имеет явный test-маркер;
4. имя не входит в denylist.

Ошибки не должны выводить DSN, user, password или host.

Работай TDD:

1. сначала failing pure tests;
2. зафиксируй ожидаемый RED;
3. реализуй минимальный guard;
4. подключи его как dependency `_apply_migrations`;
5. выполни только pure contract suite, compileall и diff check.

## Критерии приёмки

- pytest без opt-in останавливается до БД и Alembic;
- positive combination проходит pure unit contract;
- import/collection `conftest.py` больше не открывает соединение через `_db_available`;
- migration contract suite проходит;
- нет изменений вне согласованной области;
- предоставлены список файлов, diff и результаты проверок.
