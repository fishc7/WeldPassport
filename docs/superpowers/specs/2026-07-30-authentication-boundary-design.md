# Authentication Boundary — архитектурный дизайн

Дата: 2026-07-30
Статус: **ACCEPTED**
Gate: `AUTHENTICATION_BOUNDARY_ACCEPTED`

## 1. Цель

Заменить доверие к клиентскому `X-User-Id` на server-authenticated actor context,
не смешивая аутентификацию, кадровую модель и бизнес-RBAC.

Первый production-провайдер — локальные учётные записи WeldPassport с opaque
server-side sessions. Архитектура допускает последующее подключение OIDC без
изменения бизнес-модулей.

## 2. Архитектурная граница

Создаётся канонический модуль `app.identity` и PostgreSQL-схема `identity`.

```text
Credentials
→ AuthenticationProvider
→ UserAccount
→ ServerSession
→ AuthenticatedActor
→ WorkerActor boundary
→ hr.worker_roles / scope
→ business command
```

Identity отвечает только на вопрос «кто аутентифицирован». HR и существующий
authorization-контур отвечают на вопросы «является ли актор действующим
работником» и «что ему разрешено».

Модули не читают внутренние таблицы друг друга напрямую. Identity получает
сведения о работнике через явный HR port. Бизнес-модули получают actor через
FastAPI dependency и не читают cookies, session storage или credentials.

## 3. Модель данных

### 3.1. `identity.user_accounts`

- `id UUID` — первичный ключ;
- `login` — отображаемый логин;
- `normalized_login` — `trim + casefold`, уникальный;
- `password_hash` — только Argon2id PHC string;
- `status` — `ACTIVE | DISABLED`;
- `worker_id INTEGER NULL UNIQUE` — опциональная связь 0..1 с `hr.workers`;
- `must_change_password BOOLEAN`;
- `failed_login_count INTEGER`;
- `locked_until TIMESTAMPTZ NULL`;
- `password_changed_at TIMESTAMPTZ`;
- `created_at`, `updated_at TIMESTAMPTZ`;
- `record_version INTEGER`.

Пароль, временный пароль и session token никогда не сохраняются в открытом виде.
Физическое удаление аккаунта не входит в MVP. Отключение выполняется статусом
`DISABLED`; временная автоматическая блокировка определяется только
`locked_until`, без отдельного противоречащего статуса.

### 3.2. `identity.sessions`

- `id UUID`;
- `account_id UUID`;
- `token_hash CHAR(64) UNIQUE` — SHA-256 случайного 256-bit token;
- `csrf_token_hash CHAR(64)`;
- `created_at`, `last_seen_at`, `idle_expires_at`, `absolute_expires_at`;
- `revoked_at NULL`;
- `revocation_reason NULL`;
- безопасные метаданные клиента: сокращённый user-agent digest, без raw IP.

Session token возвращается только в cookie `wp_session`. CSRF token возвращается
в отдельной `wp_csrf` cookie и должен совпасть с `X-CSRF-Token` для unsafe HTTP
methods.

### 3.3. `identity.authentication_events`

Append-only журнал:

- `id UUID`;
- `account_id UUID NULL`;
- `event_type`;
- `occurred_at`;
- `session_id UUID NULL`;
- `safe_context JSONB`.

События: `LOGIN_SUCCEEDED`, `LOGIN_FAILED`, `ACCOUNT_LOCKED`,
`PASSWORD_CHANGED`, `LOGOUT`, `SESSION_REVOKED`, `SESSIONS_REVOKED`.
Credentials, raw tokens, cookies и пароли в audit запрещены.

## 4. Authenticated actor

`AuthenticatedActor` — immutable value object:

- `account_id: UUID`;
- `session_id: UUID`;
- `worker_id: int | None`;
- `authenticated_at: datetime`;
- `auth_method: LOCAL_PASSWORD`;
- `must_change_password: bool`.

Основная dependency — `get_authenticated_actor`.

Compatibility dependency `get_current_user_id` перестаёт читать header и
извлекает `worker_id` только из `AuthenticatedActor`. Если worker отсутствует,
неактивен или недоступен, производственная команда получает `403`.
Если account использует временный пароль (`must_change_password=true`),
разрешены только `/auth/me`, `/auth/change-password` и logout; бизнес-команды
получают `403 PASSWORD_CHANGE_REQUIRED`.

Новый код использует `AuthenticatedActor`; старые endpoints могут временно
использовать server-derived `get_current_user_id` до отдельной механической
миграции сигнатур.

## 5. HTTP-контракт

### `POST /api/v1/auth/login`

Принимает `login` и `password`. При успехе:

- создаёт server-side session;
- устанавливает `wp_session` (`HttpOnly`, `Secure`, `SameSite=Lax`);
- устанавливает `wp_csrf` (`Secure`, `SameSite=Lax`);
- возвращает публичный actor/account summary без credential fields.

Ошибки неизвестного логина, неверного пароля, disabled и locked account
возвращают одинаковый `401 AUTHENTICATION_FAILED`.

### `GET /api/v1/auth/me`

Возвращает текущий account, worker binding и безопасный session expiry.

### `POST /api/v1/auth/logout`

Требует CSRF, отзывает текущую session и очищает cookies. Повторный logout
идемпотентен.

### `POST /api/v1/auth/logout-all`

Требует CSRF, отзывает все sessions аккаунта.

### `POST /api/v1/auth/change-password`

Требует текущий пароль, новый пароль и CSRF. После изменения отзывает все
sessions, включая текущую; требуется новый login.

Account provisioning, disable/unlock и forced password reset выполняются
отдельным offline operator CLI. Web admin API не входит в первый slice.

## 6. Security policy

- password hashing: Argon2id через поддерживаемую библиотеку;
- минимальная длина нового пароля — 12 символов;
- максимум 5 последовательных неуспешных попыток;
- блокировка на 15 минут; успешный login обнуляет счётчик;
- session token — 256 random bits;
- idle timeout — 30 минут;
- absolute timeout — 12 часов;
- `last_seen_at` обновляется не чаще одного раза в 5 минут;
- logout/password change/disable немедленно отзывают sessions;
- production startup запрещён, если cookies не `Secure`;
- raw `X-User-Id` не является production authentication input;
- authentication errors не раскрывают наличие аккаунта;
- credentials и tokens запрещены в argv, exception details, logs и evidence.

Настройки timeout и cookie domain/path конфигурируются, но production defaults
остаются fail-closed.

## 7. Test-only boundary

Существующие application tests используют `X-User-Id`. Для их постепенной
миграции header parsing переносится из production-кода в test-only dependency
override внутри `tests/conftest.py`.

Production package:

- не содержит profile, разрешающего доверять `X-User-Id`;
- не читает `X-User-Id`;
- не имеет fallback на header при ошибке session;
- не включает test adapter по environment variable.

Pure governance tests запрещают `Header(... alias="X-User-Id")` и прямое чтение
этого header внутри `app/`.

## 8. Provider abstraction

`AuthenticationProvider` предоставляет один use case:

```text
authenticate(credentials) → AuthenticatedPrincipal
```

Первый adapter — `LocalPasswordAuthenticationProvider`.
Будущий `OidcAuthenticationProvider` сможет создавать тот же
`AuthenticatedActor`; cookies, business dependencies и RBAC не меняются.

OIDC, MFA, service accounts, API keys и machine-to-machine authentication
находятся вне scope первого slice.

## 9. Error handling

Стабильные публичные коды:

- `AUTHENTICATION_REQUIRED` — нет действующей session, HTTP 401;
- `AUTHENTICATION_FAILED` — login не выполнен, HTTP 401;
- `SESSION_EXPIRED` — session истекла, HTTP 401;
- `CSRF_VALIDATION_FAILED` — unsafe request не подтверждён, HTTP 403;
- `ACTOR_WORKER_REQUIRED` — команда требует worker binding, HTTP 403;
- `ACTOR_WORKER_INACTIVE` — worker неактивен, HTTP 403;
- `PASSWORD_CHANGE_REQUIRED` — временный пароль должен быть заменён, HTTP 403;
- `PASSWORD_POLICY_FAILED` — новый пароль не соответствует policy, HTTP 422;
- `IDENTITY_CONFLICT` — optimistic/version conflict, HTTP 409.

Internal exception text не возвращается клиенту.

## 10. Operator lifecycle

Offline CLI поддерживает:

- `create-account`;
- `bind-worker`;
- `disable-account`;
- `unlock-account`;
- `set-temporary-password`;
- `revoke-sessions`.

CLI требует explicit action, скрытый ввод пароля и не печатает credentials.
Первый account создаётся оператором после migration. Автоматический seed
production-пароля запрещён.

## 11. Migration boundary

Identity schema добавляется новой Alembic revision после
`canonical_baseline_v1`. Миграция:

- только additive;
- не создаёт аккаунты и пароли;
- не изменяет `hr.worker_roles`;
- не переносит `X-User-Id` в данные;
- добавляет canonical metadata для трёх identity tables;
- поддерживает clean upgrade PostgreSQL 18.3;
- downgrade не удаляет непустые identity tables без fail-closed проверки.

Domain Model, Migration, Service/API и Tests принимаются отдельными commits.

## 12. Verification

### Pure

- password hashing/verification и redaction;
- session token hashing, expiry, revocation и CSRF;
- actor construction и worker-required policy;
- generic authentication failures;
- отсутствие production `X-User-Id`;
- provider-port contract;
- CLI argument/output safety;
- migration AST/governance contracts.

### Isolated PostgreSQL

- clean migration upgrade;
- unique normalized login и worker binding;
- login/session/logout/change-password integration;
- lockout concurrency;
- revoked/expired session rejection;
- inactive worker rejection;
- application regression suite.

PostgreSQL verification выполняется только на новой отдельно разрешённой owned
disposable test DB. Pure implementation не получает такое разрешение
автоматически.

## 13. Acceptance criteria

- клиентский `X-User-Id` не влияет на production actor;
- каждый production actor доказуемо связан с действующей server session;
- пароль и raw tokens отсутствуют в БД, logs и API responses;
- worker/account разделены и имеют опциональную one-to-one binding;
- бизнес-RBAC остаётся в `hr.worker_roles`;
- production startup/cookies fail closed;
- test adapter физически находится вне production package;
- migration, pure tests и отдельно разрешённый PostgreSQL gate проходят;
- канонические документы и TASK_REGISTRY синхронизированы;
- только после evidence review и отдельной owner acceptance присваивается
  `AUTHENTICATION_BOUNDARY_ACCEPTED`.

## 14. Вне scope

- frontend login UI;
- OIDC provider;
- MFA;
- email/SMS password recovery;
- self-registration;
- web account administration;
- service accounts и API keys;
- переработка бизнес-RBAC;
- реализация Task 9D-4A-5.
