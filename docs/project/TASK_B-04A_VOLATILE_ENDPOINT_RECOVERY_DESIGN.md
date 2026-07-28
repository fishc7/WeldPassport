# B-04A — восстановление volatile Docker endpoint

Дата: 2026-07-28  
Статус: вариант A принят владельцем; готов к реализации по отдельному плану  
Область: только disposable B-04A PostgreSQL и локальный операторский контур

## 1. Контекст и подтверждённая причина

Disposable-контейнер B-04A публикует PostgreSQL на динамический loopback-порт.
Первоначальный защищённый session-файл сохранил endpoint
`127.0.0.1:51999`. После остановки и повторного запуска Docker назначил тому же
проверенному контейнеру endpoint `127.0.0.1:52815`.

Проверки подтвердили:

- ID, имя и ownership label контейнера сохранены;
- PostgreSQL 16 внутри контейнера работает;
- обе disposable-БД остаются пустыми;
- session URL указывает на старый порт и получает `ConnectionRefusedError` /
  `psycopg.errors.ConnectionTimeout`;
- frozen historical offline render отдельно падает на принятом known limitation
  migration 23 и не является причиной online-сбоя.

Корневая проблема: защищённый session-файл трактовал динамический Docker port
mapping как постоянную часть identity.

## 2. Решение

Docker port mapping является volatile runtime-состоянием. Источником истины для
текущего endpoint служит только проверенный owned container.

`StartOwnedContainer` становится идемпотентной операцией восстановления:

1. проверить точный worktree и доступность Docker;
2. загрузить защищённый session без вывода его содержимого;
3. проверить полный container ID, точное имя и ownership label;
4. запустить контейнер по полному ID, если он остановлен;
5. дождаться `pg_isready` по условию, без слепой задержки;
6. получить mapping `5432/tcp` и принять только единственное значение вида
   `127.0.0.1:<port>`;
7. сверить identity обоих URL: driver, host, database, username и ожидаемые
   disposable-имена должны остаться неизменными;
8. при изменении только порта атомарно пересобрать защищённый session-файл;
9. повторно проверить session-контракт, ACL, TCP endpoint и PostgreSQL major 16;
10. только после этого вывести `B04-OWNED-CONTAINER-RUNNING`.

Пароль, ownership token, container ID, имена БД и пользователь БД при
reconciliation не изменяются.

## 3. Fail-closed evidence preflight

`RunEquivalenceEvidence` не исправляет session и не запускает контейнер. Перед
Python runner он обязан:

1. проверить ownership и running-state контейнера;
2. получить актуальный loopback mapping;
3. подтвердить совпадение mapping с обоими session URL;
4. выполнить ограниченный TCP probe;
5. при любой ошибке завершиться до Alembic.

Стабильные публичные коды:

- `B04-OPERATOR-HOST-PORT` — mapping отсутствует, неоднозначен или не loopback;
- `B04-OPERATOR-SESSION-PORT-MISMATCH` — session URL не совпадает с mapping;
- `B04-OPERATOR-ENDPOINT-UNREACHABLE` — endpoint не отвечает за ограниченное
  время;
- существующие ownership, running-state и session-коды сохраняются.

## 4. Таймауты

Все сетевые и дочерние операции должны быть ограничены:

- TCP preflight: короткий фиксированный timeout;
- SQLAlchemy/psycopg connect для historical, baseline и fingerprint:
  `connect_timeout`;
- каждый Alembic subprocess: общий timeout с преобразованием в стабильный
  фазовый `B04-VERIFY-*` код.

Timeout не считается основанием для retry внутри destructive runner. Повтор
разрешён только после read-only диагностики состояния либо перепровижининга.

## 5. Защищённое обновление session

Обновление разрешено только после полной проверки ownership контейнера.

Алгоритм:

- создать временный файл в том же защищённом каталоге;
- применить ACL текущего пользователя к временному файлу до записи секретов;
- сформировать полный session-контент через единый formatter;
- проверить PowerShell parse contract и точный набор переменных;
- атомарно заменить существующий session-файл через
  `File.Replace(..., ignoreMetadataErrors: false)`, чтобы Windows сохранил DACL
  исходного session и не проигнорировал ошибку ACL merge;
- не выполнять отдельный `Set-Acl` после успешного replace;
- при ошибке до/во время replace удалить только временный файл; не выполнять
  второй неатомарный rewrite session;
- никогда не печатать URL, пароль или ownership token.

`Cleanup` и `RecoverOwnedContainer` сохраняют identity-only семантику и должны
работать с остановленным контейнером и устаревшим endpoint.

## 6. Границы

В рамках решения:

- не изменяется migration 23;
- frozen historical chain не объявляется offline-renderable;
- не меняются миграции, canonical baseline и schema fingerprint;
- не создаются новые БД и не затрагиваются внешние PostgreSQL instances;
- не активируется B-04B;
- commit и push выполняются только после отдельной приёмки.

## 7. Проверки и критерии приёмки

До нового operator evidence-run обязательны:

1. RED → GREEN контракты stale-port detection и atomic session refresh;
2. тест, что меняется только порт двух URL;
3. тесты сохранения ownership token, container ID, username, password и имён БД;
4. исполняемые pure-тесты actual PowerShell functions: no-op, port-only
   replacement, сохранение identity/secret values, original-on-pre-replace
   failure и `File.Replace(..., false)`;
5. тесты fail-closed для non-loopback, нескольких mappings, malformed URL,
   недоступного endpoint и отсутствующего ACL/atomic replace;
6. тест, что evidence mode ничего не переписывает;
7. тест, что Cleanup/Recover не требуют running-state или актуального порта;
8. focused helper/runner tests;
9. полный `migration_contract_tests`;
10. `compileall`, PowerShell parser и `git diff --check`;
11. независимый read-only review.

Операторская приёмка:

1. повторный `StartOwnedContainer`;
2. подтверждение нового mapping и TCP-доступности без раскрытия секретов;
3. read-only подтверждение чистых disposable-БД;
4. один equivalence evidence-run;
5. наличие трёх финальных evidence-артефактов и успешная проверка их digest;
6. cleanup только после приёмки Task 7.
