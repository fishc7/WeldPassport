# Prompt — B-04A canonical fingerprint alignment recovery

## Цель

Устранить доказанный drift между исторической схемой PostgreSQL 16 и B-04A
baseline, исправив источник истины — canonical SQLAlchemy metadata — без
ослабления fingerprint и без ручного редактирования generated baseline.

## Доказанное состояние

Read-only runtime diff после остановки на
`B04-VERIFY-FINGERPRINT-MISMATCH` выявил:

- physical column-order drift в четырёх таблицах:
  `engineering.joints`, `quality.laboratory_conclusions`,
  `quality.quality_audit_events`, `quality.quality_decisions`;
- self-FK name drift:
  `fk_engineering_joints_superseded_by_joint` против PostgreSQL auto-name;
- шесть отсутствующих `server_default` в baseline metadata:
  `hr.departments.is_active`, `hr.positions.is_active`,
  `hr.worker_roles.is_active`, `hr.workers.employment_status`,
  `welding.welder_admissions.admission_status`, `welding.welders.status`.

## Архитектурное решение

Сохранить строгий fingerprint-контракт, включая physical ordinal, defaults и
constraint names. Привести canonical metadata к фактическому историческому
каталогу. Generated raw candidate должен быть позднее пересоздан из исправленной
metadata, а затем пройти обязательный deterministic hardening исходного B-04A
Task 6: строгие schema operations, закрытый constructor/name rendering,
governed index, literal seeds и симметричный downgrade. Произвольная ручная
правка запрещена; разрешён только воспроизводимый hardening по уже принятому
AST-контракту.

## Разрешено

- TDD-контракт в `migration_contract_tests/` для metadata alignment;
- минимальные правки только:
  - `app/hr/models.py`;
  - `app/welding/models.py`;
  - `app/engineering/models.py`;
  - `app/quality/execution_models.py`;
  - `app/quality/quality_decision_models.py`;
- перестановка объявлений колонок внутри ORM-класса без изменения API или
  бизнес-логики;
- восстановление historical `server_default` при сохранении существующего
  Python-side `default`;
- явное имя self-FK.

## Запрещено

- менять historical Alembic revisions;
- менять или ослаблять `migrations/b04/fingerprint.py`;
- вносить в `canonical_baseline_v1.py` изменения вне принятого deterministic
  hardening Task 6 и доказанных metadata-alignment дельт;
- запускать Docker, PostgreSQL, Alembic или operator evidence;
- очищать текущие disposable-БД;
- менять сервисы, API, схемы запросов/ответов или бизнес-правила;
- stage, commit, push или cleanup.

## TDD

Сначала executable pure contract должен упасть на текущей metadata и доказать:

1. точный historical column order четырёх таблиц;
2. наличие и точные значения шести `server_default`;
3. точное имя self-FK.

После RED внести минимальные model-only изменения и получить GREEN.

## Критерии приёмки

- focused metadata-alignment contracts проходят;
- весь `migration_contract_tests` проходит;
- `compileall` проходит;
- `git diff --check` проходит;
- independent review не имеет Critical/Important findings;
- generated baseline candidate не изменён;
- Docker, БД, Alembic, Git и cleanup не запускались.
