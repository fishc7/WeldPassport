# Полный аудит WeldPassport — 2026-07-24

## Итог

Аудит выполнен после реализации AS-02. Проверены исполняемые backend/frontend-контуры,
миграционная цепочка, PostgreSQL-схема `test`, зависимости, сборки, каноническая
документация и Git-гигиена.

Статус: **пройден с исправлением подтверждённых дефектов**.

## Проверенные контуры

| Контур | Проверка | Результат |
|---|---|---|
| Основной backend | полный `pytest tests` | `1590 passed` |
| Migration governance | полный `pytest migration_contract_tests` | `35 passed` |
| AS-02 focused regression | permissions/domain/service/API/import | `100 passed` |
| PostgreSQL | head, колонки, CHECK, rehearsal `27 → 26 → 27` | успешно |
| Project Control backend | полный pytest | `12 passed` |
| Project Control frontend | typecheck, `4` tests, production build | успешно |
| Основной frontend | typecheck, production build | успешно |
| Node dependencies | `npm audit` обоих frontend | `0 vulnerabilities` |
| Python dependencies | `pip check` | конфликтов нет |
| Python source | `compileall` основного backend и Project Control | успешно |
| Документация | `92` Markdown-файла текущего worktree, локальные ссылки | проверено |
| Git/security hygiene | diff check, tracked artifacts/secrets scan | нарушений нет |

## Исправленные проблемы

### 1. Legacy workforce import

`app.workforce.repository` не импортировался: метод класса `list` затенял builtin
`list` во время вычисления аннотации `list[DokumentSvarshchika]`.

Исправление: включены отложенные аннотации через
`from __future__ import annotations`; добавлен regression test импорта.

### 2. Основной frontend typecheck

Штатная команда использовала несовместимое сочетание TypeScript build-mode и
`--noEmit` при project reference и завершалась `TS6310`.

Исправление: typecheck переведён на
`tsc --noEmit -p tsconfig.json`; production build сохранён отдельно.

### 3. Уязвимые frontend dev dependencies

Основной frontend использовал Vite 5, для которого audit показывал уязвимости, включая
Windows path-deny bypass. Vite и React plugin обновлены до уже применяемой в
Project Control совместимой линии Vite 8 / plugin-react 6.

После обновления typecheck/build успешны, `npm audit` сообщает `0 vulnerabilities`.

### 4. Локальный npm cache

Среда не имела доступа к пользовательскому npm-cache. Cache был направлен внутрь
frontend-каталогов, а `**/.npm-cache/` добавлен в `.gitignore`.

## AS-02 acceptance

- Revision: `20260724_27_qd_rbac_sod`.
- Revisions 25/26 не изменены.
- Реализованы current-cycle submitter, `409 QD_SAME_ACTOR_REVIEW`,
  evidence-bearing `AuthorizationGrant`, immutable `authorization_context`,
  deterministic scope selection и `QD_DUAL_ROLE_ASSIGNMENT`.
- Публичные command URL и request body не изменены; read API расширен двумя nullable-полями.
- На пустой тестовой схеме downgrade удалил только две AS-02-колонки/ограничения,
  последующий upgrade восстановил их и head 27.

## Оставшиеся границы и известные риски

- Тестовая схема не содержала исторических `QualityDecision`, поэтому backfill реальных
  legacy-строк не репетировался на копии owner/production data. Его SQL/AST-контракт
  проверен, а миграция намеренно останавливается, если submitter недоказуем.
- `X-User-Id` остаётся временной authentication boundary; AS-02 усиливает authorization,
  но не заменяет Identity/Auth.
- Task 9D-4A-5 и остаток 9D остаются в статусах реестра; аудит не подменяет их отдельные
  архитектурные и implementation gate.
- Интерактивный browser/E2E smoke UI не выполнялся; оба frontend прошли typecheck,
  unit tests там, где они определены, и production build.
- Штатное PostgreSQL-подключение и авто-снимки Project Control остаются следующим
  рубежом этого служебного контура.

## Вывод

Репозиторий готов к фиксации и публикации текущего набора: AS-02 реализован и принят,
полный автоматизированный regression зелёный, обнаруженные воспроизводимые дефекты
устранены, границы непроверенного явно зафиксированы.
