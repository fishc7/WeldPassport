# Prompt — Task 10A QualityDecision Core Governance Recovery

## Цель

Восстановить governance Task 10A и довести `QualityDecision Core` до
согласованного MVP-контракта ADR-027 с recovery-уточнениями Q-D9/Q-D5:
достоверная документация, idempotency для пяти мутаций, snapshot содержания
при `SUBMIT`, командный API и проверяемая приёмка.

## Архитектурное основание

- `docs/project/ADR-027-quality-decision-core-canon.md`;
- `docs/project/TASK_10A_QUALITY_DECISION_CORE_RECOVERY_SPEC.md`;
- `docs/project/ARCHITECTURE_GOVERNANCE.md`;
- PostgreSQL-only, SQLAlchemy 2, Alembic, FastAPI, Pydantic v2.

## Границы изменений

Только Task 10A:

- governance-документы;
- `quality_decision_*` модели, workflow, repository, service, schemas и API;
- новая корректирующая миграция после revision 25;
- router composition;
- профильные model/migration/service/API tests;
- минимальные реэкспорты/CHECK/cleanup, необходимые новой модели.

## Разрешено

- создать Task Specification и implementation plan;
- добавить датированное recovery-уточнение ADR-027 без переписывания истории;
- синхронизировать architecture/registry/status/roadmap/summary;
- добавить idempotency model и миграцию 26;
- исправить SUBMIT snapshot;
- добавить обязательный key для CREATE/UPDATE_DRAFT/SUBMIT/RETURN/DECIDE;
- создать schemas/API и тесты;
- запускать профильные и регрессионные проверки.

## Запрещено

- AS-02/RBAC hardening;
- B-04, baseline, stamp, version marker transfer;
- runtime profile и TEST-DB Foundation;
- side effect создания Defect;
- DefectDisposition, Repair, Reinspection;
- изменение migration 25;
- SQLite;
- unrelated refactoring;
- commit/push.

## Порядок

1. Governance.
2. Model/Migration.
3. Workflow/Repository/Service.
4. Schemas/API.
5. Tests.
6. Diff.
7. Acceptance.

Для нового поведения соблюдать TDD: тест → ожидаемый RED → минимальная
реализация → GREEN → профильная регрессия.

## Обязательный контракт

- Q-D9A: scope-level WELDING_ENGINEER редактирует только DRAFT;
- каждый SUBMIT сохраняет version/summary/sorted basis ids/actor role;
- key обязателен для пяти мутаций;
- idempotency uniqueness:
  `actor + command + target type + target id + key`;
- same key/same payload возвращает исходный snapshot без side effects;
- same key/different payload → `409 QD_IDEMPOTENCY_CONFLICT`;
- state/audit/idempotency сохраняются в одной транзакции;
- migration 26 создаёт отдельную idempotency table;
- API использует отдельные command endpoints, не generic status update.

## Критерии приёмки

- спецификация и status-трассировка не создают ложной истории;
- model/migration contracts проходят;
- service replay/conflict/rollback/race проходят;
- SUBMIT snapshot доказуем тестом;
- API success/RBAC/scope/lifecycle/idempotency validation проходят;
- применимая регрессия quality-модуля проходит;
- `git diff --check` не сообщает ошибок;
- внерамочных изменений и Git commit/push нет.

