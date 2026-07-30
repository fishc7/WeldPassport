# Prompt for Cursor / Claude Code — Authentication Boundary

## Роль

Ты реализуешь принятый server-authenticated actor boundary WeldPassport строго
по:

- `docs/project/ADR-034-authentication-boundary.md`;
- `docs/superpowers/specs/2026-07-30-authentication-boundary-design.md`;
- `docs/superpowers/plans/2026-07-30-authentication-boundary.md`;
- `docs/ARCHITECTURE.md`;
- `AGENTS.md`.

Рабочий каталог:

```text
D:\WeldPassport\.worktrees\b04b-maintenance-readiness
```

Основной backend:

```text
09_Разработка/backend
```

## Цель

Устранить production-доверие к `X-User-Id` и реализовать локальную
аутентификацию:

```text
local credentials
→ opaque server-side session
→ AuthenticatedActor
→ active hr.worker
→ existing hr.worker_roles/scope
→ business command
```

## Обязательный порядок

Работай по TDD и принимай этапы раздельно:

```text
Domain primitives
→ Domain Model
→ Migration
→ Service
→ API/test adapter
→ Operator CLI
→ Pure closure
→ separately authorized PostgreSQL acceptance
```

Для каждого этапа:

1. напиши точный failing test;
2. запусти его и зафиксируй RED;
3. реализуй минимальный scope;
4. запусти focused GREEN;
5. проверь diff;
6. создай отдельный Conventional Commit.

## Разрешено

- создать `app.identity`;
- добавить `argon2-cffi`;
- добавить три таблицы в схему `identity`;
- создать additive Alembic revision `20260730_28_identity`;
- добавить `AuthenticatedActor`, local password provider и session services;
- изменить `app.shared.auth`, сохранив временную server-derived функцию
  `get_current_user_id`;
- подключить `/api/v1/auth`;
- добавить test-only `X-User-Id` override только в `tests/`;
- добавить safe offline operator CLI;
- обновить canonical metadata/search path/governance;
- добавить pure и integration tests;
- синхронизировать канонические документы.

## Запрещено

- доверять `X-User-Id` в любом файле production package `app/`;
- хранить raw password, session token или CSRF token;
- печатать credentials/tokens в stdout, logs, exceptions или evidence;
- помещать business roles/scope в identity tables;
- объединять `user_account` и `worker`;
- seed’ить production account/password миграцией;
- добавлять JWT browser storage;
- добавлять OIDC, MFA, recovery, self-registration или web admin UI;
- менять Task 9D-4A-5;
- развивать legacy `workforce`;
- менять существующие доменные lifecycle/RBAC правила;
- запускать PostgreSQL, Alembic CLI или `tests/` без отдельного operational
  разрешения;
- создавать, переиспользовать или удалять test DB без отдельного разрешения;
- присваивать `AUTHENTICATION_BOUNDARY_ACCEPTED` по pure результатам.

## Критерии приёмки

- `app/` не содержит production parsing `X-User-Id`;
- пароль хешируется Argon2id;
- raw session/CSRF tokens отсутствуют в DB;
- session expiry, revoke, lockout и CSRF fail closed;
- production insecure-cookie configuration блокируется;
- temporary-password actor не выполняет business commands;
- worker/account разделены, worker binding опционален и уникален;
- HR roles/scope не дублируются;
- migration additive, без credentials seed, с non-empty downgrade guard;
- test header adapter физически расположен только в `tests/`;
- operator CLI не принимает password через argv;
- focused и full pure suites проходят;
- compile и `git diff --check` проходят;
- документация содержит честный статус
  `IMPLEMENTED_UNVERIFIED / PURE VERIFIED`;
- live PostgreSQL gate остаётся отдельным.

## Итоговый отчёт

Предоставь:

- список изменённых файлов по этапам;
- commits;
- RED/GREEN evidence;
- focused/full pure test counts;
- compile/diff/secret-scan results;
- явное перечисление невыполненных operational действий;
- exact следующий PostgreSQL authorization gate.
