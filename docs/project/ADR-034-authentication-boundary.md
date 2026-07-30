# ADR-034. Server-authenticated actor boundary

Дата: 2026-07-30
Статус: **ACCEPTED**

## Контекст

Текущий backend получает actor как клиентский header `X-User-Id`. Этот механизм
пригоден только как тестовая заглушка: клиент может выбрать любой worker id, а
сервер не доказывает факт аутентификации. Task 9D-4A-5 требует закрытого gate
`AUTHENTICATION_BOUNDARY_ACCEPTED`.

Архитектура проекта требует разделять:

- `user_account` — учётную запись;
- `worker` — физического работника;
- `worker_roles` — бизнес-полномочия и scope.

## Решение

1. Создать канонический модуль `app.identity` и PostgreSQL-схему `identity`.
2. Первый production provider — локальные логин/пароль с Argon2id.
3. Использовать opaque server-side sessions и cookie `HttpOnly + Secure +
   SameSite=Lax`.
4. Unsafe HTTP methods защищать session-bound CSRF token.
5. Ввести immutable `AuthenticatedActor`.
6. Опционально связывать один `user_account` с одним `hr.worker`.
7. Оставить бизнес-RBAC только в `hr.worker_roles`.
8. Удалить production-доверие к `X-User-Id`; header adapter разрешён только как
   dependency override в test tree.
9. Сохранить provider port для будущего OIDC без изменения business API.
10. Account provisioning первого slice выполнять offline operator CLI; web
    administration, MFA и recovery вынести за scope.

Полный контракт:
[[docs/superpowers/specs/2026-07-30-authentication-boundary-design|Authentication Boundary Design]].

## Инварианты

- production actor создаётся только из действующей server session;
- raw password и tokens не сохраняются и не логируются;
- account без активного worker не выполняет производственные команды;
- identity не дублирует HR roles/scope;
- generic authentication failures не раскрывают существование login;
- production не имеет fallback на `X-User-Id`;
- PostgreSQL verification требует отдельного разрешения и новой disposable DB.

## Последствия

Положительные:

- закрывается подмена actor через клиентский header;
- бизнес-модули не зависят от способа входа;
- сохраняется возможность OIDC;
- worker, account и RBAC остаются разными понятиями.

Отрицательные:

- появляются credential/session lifecycle и operator provisioning;
- требуются CSRF, lockout, expiry и security audit;
- существующим API нужен compatibility adapter на server-derived worker id;
- integration acceptance требует отдельного PostgreSQL gate.

## Вне scope

- frontend login UI;
- OIDC/MFA;
- email/SMS recovery;
- self-registration;
- service accounts/API keys;
- изменение бизнес-RBAC;
- Task 9D-4A-5 implementation.
