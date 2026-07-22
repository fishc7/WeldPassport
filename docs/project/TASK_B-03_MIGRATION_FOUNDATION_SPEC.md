# TASK B-03 — Migration Foundation Implementation Specification

## 1. Status

Статус: **ACCEPTED**

Дата подготовки: 2026-07-22.

Task: **B-03 — Migration Foundation**.

Реализация кода по настоящей спецификации не начата. Документ не разрешает B-04,
TEST-DB Foundation, runtime-profile changes или Task 9D-4A-5A.

## 2. Architecture basis

Нормативное основание:

- [[docs/project/ADR-025-migration-governance-and-legacy-schema-boundary|ADR-025 — Migration Governance and Legacy Schema Boundary]] (`ACCEPTED`);
- [[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 010 — Migration Governance and Legacy Boundary|Architecture Session 010]] (`Завершена / Accepted`);
- [[docs/project/DECISIONS#ADR-025. Migration Governance and Legacy Schema Boundary|DECISIONS — ADR-025]];
- [[docs/ARCHITECTURE#Migration governance и Canonical / Legacy boundary|ARCHITECTURE — Migration governance]];
- [[docs/project/ADR-005-legacy-workforce-deprecation|ADR-005 — Legacy Workforce Deprecation]].

Фактическая база аудита:

- ADR-025 фиксирует 69 canonical-таблиц и 7 workforce-таблиц
  (`docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md:28-43`);
- canonical boundary состоит из `hr`, `welding`, `project`, `engineering`, `quality`
  (`docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md:84-107`);
- `target_metadata`, schema filtering и обязательный `alembic check` заданы
  `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md:129-143`;
- B-03/B-04 ownership разделён в
  `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md:419-441`;
- текущий `env.py` импортирует workforce, использует общую `Base.metadata` и ручные
  списки имён таблиц (`09_Разработка/backend/migrations/env.py:12-90`);
- текущий marker задаётся через `settings.postgres_schema`
  (`09_Разработка/backend/migrations/env.py:94-102,125-130`);
- `tests/conftest.py` подключается к обычному `SessionLocal` и автоматически вызывает
  `command.upgrade(cfg, "head")` (`09_Разработка/backend/tests/conftest.py:70-98`),
  поэтому B-03 pure tests не должны находиться под этим каталогом до TEST-DB Foundation.

## 3. Execution gate

B-03 implementation может начаться только после:

1. независимого review настоящей спецификации;
2. перевода спецификации в принятый статус отдельным документным изменением;
3. отдельного явного разрешения пользователя начать **B-03A**.

Блоки принимаются строго последовательно:

```text
B-03A → review → B-03B → review → B-03C → review → B-03D → final acceptance
```

Объединение B-03A/B/C/D, пропуск review checkpoint или перенос работы между блоками
требует отдельного решения пользователя.

B-03 можно реализовать и закрыть до TEST-DB Foundation: для closure используются pure
tests и read-only проверки существующей БД. Clean upgrade, downgrade и любые destructive
database tests принадлежат B-04/TEST-DB Foundation.

## 4. Goal

Сделать Alembic migration environment доказуемым источником истины для текущей canonical
schema без изменения DDL, данных, runtime composition или расположения version marker:

- один тестируемый canonical metadata provider;
- все 69 текущих canonical-таблиц видимы Alembic;
- workforce и схема `test` исключены из autogenerate/drift;
- filtering выполняется по schema boundary, а не по списку имён canonical-таблиц;
- historical graph и current marker продолжают работать до B-04;
- новые `app.*` imports в migrations блокируются;
- `alembic check` возвращает `No new upgrade operations detected.` на текущей БД.

## 5. Scope

В B-03 входят:

- canonical-only metadata provider;
- явная регистрация всех существующих canonical model modules;
- схемы `hr`, `welding`, `project`, `engineering`, `quality`;
- исключение `app.workforce.models` и любых `test.*` tables из target metadata;
- canonical FK closure validation;
- schema-level `include_name`/`include_object` contract;
- отказ от `*_MANAGED_TABLES` для canonical tables;
- служебная обработка version table как Alembic platform object;
- сохранение historical marker mode до B-04;
- metadata, filtering, import-policy, graph и Alembic contract tests;
- read-only `heads`, `history`, `current`, `check`;
- offline-render policy;
- документация реализации и приёмки B-03.

## 6. Out of scope

B-03 не выполняет:

- `canonical_baseline_v1`;
- архивирование или перемещение active historical chain;
- изменение `down_revision`, revision ID или DDL historical migrations;
- перенос, создание или stamp `public.alembic_version`;
- удаление или изменение `test.alembic_version`;
- adoption/fingerprint существующей БД;
- изменение `app/main.py`, workforce router или runtime profiles;
- legacy data/schema repair;
- TEST-DB bootstrap;
- clean upgrade, downgrade или destructive schema tests;
- authentication;
- migration Task 9D-4A-5;
- начало B-04 или 9D-4A-5A.

Если B-03 нельзя завершить без изменения historical migration, работа останавливается.
Предлагаемая правка оформляется как **HISTORICAL MIGRATION EXCEPTION** с доказательством
идентичности generated DDL, отдельным diff и отдельным review. Настоящая спецификация не
содержит и не разрешает такую exception.

## 7. Current gap analysis

| Gap ID | Requirement ADR-025 | Current state / evidence | Gap | B-03 action |
|---|---|---|---|---|
| B03-G01 | Canonical-only metadata | `env.py:12-24` импортирует workforce и использует общую `Base.metadata` | metadata загрязнена legacy | Ввести отдельный provider и импортировать его в `env.py` |
| B03-G02 | 69 canonical tables | Read-only import canonical modules: 69 (`engineering=28`, `hr=4`, `project=4`, `quality=31`, `welding=2`); ADR-025:28-31 | число не проверяется автоматически | Зафиксировать current snapshot test `69` |
| B03-G03 | Workforce excluded | `env.py:22,26-34,89` включает workforce | 7 legacy tables участвуют в Alembic | Удалить workforce import и legacy table list из canonical env |
| B03-G04 | Canonical FK closure | Pure audit canonical metadata: 0 FK за пять схем | инвариант не защищён тестом | Проверять каждый FK target schema/table |
| B03-G05 | Schema-level allowlist | `env.py:26-74` хранит table-name sets | boundary задана таблицами | Ввести `CANONICAL_SCHEMAS` и schema filter |
| B03-G06 | No canonical table whitelist | `env.py:76-90` сверяет каждое имя | новые таблицы невидимы без ручной правки | Любое имя внутри canonical schema включать автоматически |
| B03-G07 | Version table platform treatment | `env.py:101,129` связывает marker с `settings.postgres_schema` | target `public` ещё не принят физически | Сохранить historical marker mode; зарезервировать public target только документально |
| B03-G08 | All canonical tables visible | текущий whitelist содержит 24 canonical из 69 (ADR-025:33-36) | 45 таблиц скрыты | Provider + schema filter должны видеть все 69 |
| B03-G09 | Unknown canonical DB table is drift | unknown name отклоняется whitelist | лишняя таблица скрывается | Reflected table canonical schema всегда включается |
| B03-G10 | Future canonical table auto-visible | требуется правка `*_MANAGED_TABLES` | нет automatic discovery | Synthetic-table contract test без изменения name list |
| B03-G11 | No new `app.*` migration imports | policy отсутствует | mutable runtime dependency разрешена | AST gate для active migrations path |
| B03-G12 | Historical import debt classified | семь файлов содержат восемь AST import statements (`migrations/versions/...:26-36`) | debt не зафиксирован машинно | Exact frozen debt set; новые/изменённые entries запрещены |
| B03-G13 | One root/head | AST и Alembic: root `20260702_02_hr_core`, head `20260721_24_disp_supersede` | проверки фрагментарны | Общий graph contract: root/head/IDs/down_revision |
| B03-G14 | Offline policy | migration 23 делает runtime SELECT (`20260721_23_disp_events.py:41-49`) | full `upgrade head --sql` падает | Known limitation до B-04; новые revisions — offline-safe by default |
| B03-G15 | Metadata coverage test | такого suite нет; migration tests проверяют отдельные доменные таблицы | нет общей coverage | Отдельный pure contract suite |
| B03-G16 | Complete model registration | quality re-export зависит от `quality/models.py:392-448`; import model отдельный | забытый `*_models.py` возможен | Явный module registry + filesystem coverage test |
| B03-G17 | `alembic check` | падает `NoReferencedTableError` на `test.ОБЪЕКТЫ` из `workforce/models.py:201-220` | audit gate не работает | Исключить workforce до metadata sort; требовать no drift |
| B03-G18 | No runtime changes | workforce router подключён `app/main.py:17,25` | runtime-profile работа отдельна | `main.py` и router composition не менять; diff guard |
| B03-G19 | No marker move | current marker `test.alembic_version`; `alembic current` видит head | риск преждевременного switch | Сохранить location и доказать before/after current |
| B03-G20 | B-04 boundary | ADR-025:425-430 назначает baseline/adoption B-04 | риск смешения задач | Запрет baseline/archive/stamp/fingerprint в file scope и tests |

## 8. Decomposition B-03A–B-03D

### B-03A — Canonical Metadata Boundary

**Files:**

- create `09_Разработка/backend/app/shared/canonical_metadata.py`;
- create `09_Разработка/backend/migration_contract_tests/test_canonical_metadata.py`.

**Tests:** `TEST-B03-METADATA-001…004`.

**Command:**

```powershell
python -m pytest migration_contract_tests/test_canonical_metadata.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

**Acceptance:** provider содержит ровно пять текущих schemas и 69 tables; workforce отсутствует;
canonical FK closure полна; filesystem scan не находит незарегистрированный canonical
`*models.py` module.

**Review checkpoint:** принимается только metadata provider и его pure tests. `env.py` ещё
не переключается.

### B-03B — Alembic Environment and Filtering

**Files:**

- create `09_Разработка/backend/migrations/canonical_boundary.py`;
- modify `09_Разработка/backend/migrations/env.py`;
- create `09_Разработка/backend/migration_contract_tests/test_alembic_boundary.py`.

**Tests:** `TEST-B03-METADATA-005`, `TEST-B03-FILTER-001…004`.

**Command:**

```powershell
python -m pytest migration_contract_tests/test_alembic_boundary.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

**Acceptance:** `env.py` использует canonical provider; synthetic canonical table видима
без изменения name list; table-name whitelist отсутствует; historical marker location
сохранена; `main.py`, revisions и legacy models не изменены.

**Review checkpoint:** Git scope review по правилам раздела 16 подтверждает только B-03
environment boundary, без migration DDL/runtime/baseline. Transient state diff не является
постоянным pytest acceptance test.

### B-03C — Migration Contract Policy

**Files:**

- create `09_Разработка/backend/migration_contract_tests/test_migration_import_policy.py`;
- create `09_Разработка/backend/migration_contract_tests/test_migration_graph.py`;
- create `09_Разработка/backend/migration_contract_tests/test_offline_policy.py`;
- create `09_Разработка/backend/migration_contract_tests/__init__.py`.

**Tests:** `TEST-B03-IMPORT-001…003`, `TEST-B03-GRAPH-001…004`,
`TEST-B03-OFFLINE-001…002`.

**Command:**

```powershell
python -m pytest migration_contract_tests/test_migration_import_policy.py migration_contract_tests/test_migration_graph.py migration_contract_tests/test_offline_policy.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

**Acceptance:** новые runtime imports запрещены; historical debt совпадает с exact set;
graph содержит 28 unique revisions, один root/head и разрешённые edges; offline limitation
migration 23 классифицирована, но historical file не изменён.

**Review checkpoint:** policy/tests принимаются отдельно; shared migration utility package
и historical edits отсутствуют.

### B-03D — Verification and closure evidence

**Files:**

- create `09_Разработка/backend/migration_contract_tests/test_alembic_cli_contract.py`;
- modify только B-03-related documentation после успешной приёмки.

**Tests:** `TEST-B03-ALEMBIC-001…005` и полный pure contract suite.

**Review gates:** `B03-SAFETY-001`, `B03-SAFETY-002`, `B03-SCOPE-001`,
`B03-SCOPE-002`.

**Commands:** раздел 17.

**Acceptance:** `heads`, `history`, `current` успешны; `current` показывает historical head;
`check` сообщает отсутствие upgrade operations; working DB не мутируется; Git scope review
подтверждает отсутствие baseline/marker/runtime changes.

**Review checkpoint:** финальная приёмка B-03. B-04 не стартует автоматически.

## 9. Canonical metadata registry

Выбран **вариант A — явный registry module**:

```text
app.shared.canonical_metadata
```

Публичный контракт:

```python
CANONICAL_SCHEMAS: frozenset[str]
CANONICAL_MODEL_MODULES: tuple[str, ...]
canonical_metadata: sqlalchemy.MetaData
validate_canonical_metadata() -> None
```

`CANONICAL_SCHEMAS` содержит только:

```text
hr
welding
project
engineering
quality
```

Единственный владелец `CANONICAL_SCHEMAS`:
`app.shared.canonical_metadata.CANONICAL_SCHEMAS`. Другие модули не создают и не поддерживают
собственный список canonical schemas.

`identity`, `production`, `documents`, `audit` не включаются: эти схемы ещё не введены
отдельными ADR и моделями.

Registry явно импортирует:

```text
app.hr.models
app.welding.models
app.projects.models
app.engineering.models
app.engineering.import_models
app.quality.models
app.quality.execution_models
app.quality.quality_finding_models
app.quality.engineering_evaluation_models
app.quality.defect_models
app.quality.defect_disposition_models
```

`app.workforce.models` и `app.main` не импортируются прямо или транзитивно. После imports
provider экспортирует `Base.metadata` только после fail-fast validation:

- каждая table имеет schema из `CANONICAL_SCHEMAS`;
- фактическое множество schemas равно canonical set;
- каждый FK target разрешается внутри canonical metadata;
- в current snapshot ровно 69 tables.

Filesystem coverage test сканирует model-bearing modules пяти canonical packages и сравнивает
их с registry. Добавление нового `models.py`, `*_models.py` или отдельного model module без
registry update ломает тест. Exact count `69` является versioned current snapshot: будущая
принятая canonical migration обязана обновить snapshot одновременно, но не меняет filter.

Вариант B отклонён: registry внутри `env.py` плохо импортируется pure tests и смешивает
registration с Alembic execution. Вариант C отклонён: проект использует один `Base`
(`app/shared/db.py:23`), нескольких фактических metadata collections нет.

## 10. Alembic environment and schema filtering

`migrations/canonical_boundary.py` является environment policy, но **не** migration utility:
ни одна revision не имеет права импортировать его.

Публичный контракт:

```python
# imported from app.shared.canonical_metadata; optional re-export only
CANONICAL_SCHEMAS: frozenset[str]
PUBLIC_PLATFORM_OBJECTS: frozenset[tuple[str, str]]
include_name(name, type_, parent_names) -> bool
include_object(obj, name, type_, reflected, compare_to) -> bool
```

`migrations.canonical_boundary` обязан импортировать
`app.shared.canonical_metadata.CANONICAL_SCHEMAS`. Он не создаёт собственный список, не
копирует значения и может только re-export существующей константы. Расхождение двух списков
не допускается, потому что второго списка в архитектурном контракте нет.

`env.py` передаёт в оба `context.configure()`:

- `target_metadata=canonical_metadata`;
- `include_schemas=True`;
- `include_name=include_name`;
- `include_object=include_object`;
- неизменённую temporary historical marker location до B-04.

Filtering contract:

| Object | Поведение B-03 |
|---|---|
| Metadata/reflected table в canonical schema | Всегда include независимо от имени |
| Reflected canonical table без metadata peer | Include; `alembic check` показывает drop/drift |
| Metadata canonical table без DB peer | Include; `alembic check` показывает add/drift |
| Table в `test` или иной noncanonical schema | Exclude из autogenerate целиком |
| `public.alembic_version` | Alembic-owned platform object; не canonical table drift |
| `test.alembic_version` до B-04 | Historical version marker; query Alembic разрешён, autogenerate object исключён |
| Другой `public` object | Exclude, если нет отдельного архитектурного решения |
| Column/index/PK/UNIQUE/FK/CHECK | Include только вместе с canonical parent table |
| Temporary object / `pg_temp_*` | Exclude |
| View/materialized view | Не управляется core Alembic autogenerate B-03; exclude |
| Extension-owned object | Exclude; lifecycle extension не входит в B-03 |
| Standalone sequence | Core autogenerate B-03 не заявляет coverage; B-04 fingerprint проверяет отдельно |
| Schema create/drop | Не генерируется автоматически B-03; schema lifecycle остаётся migration-local |

Table-name whitelist для canonical tables запрещён. `PUBLIC_PLATFORM_OBJECTS` не является
доменным whitelist: он содержит только Alembic-owned `("public", "alembic_version")` и
может расширяться исключительно отдельным архитектурным решением.

`include_name` ограничивает reflection до загрузки объектов; `include_object` является
вторым fail-closed guard и проверяет parent schema. Новая canonical table не требует
изменения filter-кода.

## 11. Version table compatibility

Выбран временный **historical marker mode**:

- active chain остаётся в `migrations/versions`;
- current head остаётся `20260721_24_disp_supersede`;
- `version_table_schema` до B-04 продолжает указывать на существующий historical marker
  через текущую migration-конфигурацию (`settings.postgres_schema`, фактически `test`);
- B-03 не создаёт `public.alembic_version`, не выполняет stamp и не удаляет legacy marker;
- schema filter не включает legacy tables, но это не мешает Alembic читать собственный
  marker через `version_table_schema`;
- read-only `alembic current` до и после B-03 обязан выводить historical head.

B-03 не вводит переключатель, способный активировать public marker. B-04 является
единственным владельцем добавления canonical marker mode, физического переноса marker,
stamp `canonical_baseline_v1` и удаления temporary compatibility logic.

Если `current` после B-03 не видит head, B-03B отклоняется; fallback stamp запрещён.

## 12. Migration import policy

Для любой новой revision в active migrations path запрещены AST imports:

```python
from app...
import app...
```

Разрешены:

- Python standard library;
- `alembic`;
- `sqlalchemy` и `sqlalchemy.dialects`;
- migration-local literals;
- migration-local helper functions.

Общий immutable utility package в B-03 не создаётся. Если он понадобится позднее, требуется
отдельное решение о versioning/freeze и migration compatibility.

AST gate сканирует каждый `*.py` в active `migrations/versions`, сообщает `path:line:module`
и сравнивает imports с exact historical debt set. Filename/module wildcard whitelist
запрещён. После B-04 active baseline chain проверяется без historical exceptions, а archive
проверяется checksum manifest, принадлежащим B-04.

## 13. Historical `app.*` imports

Выбран **вариант A — historical migrations не изменять до B-04**.

Аудит обнаружил семь файлов и восемь AST import statements:

| File | Line | Imported module |
|---|---:|---|
| `20260713_14_heat_treatment.py` | 26 | `app.engineering.heat_treatment_workflow` |
| `20260713_15_inspection_core.py` | 28 | `app.quality.inspection_workflow` |
| `20260713_16_method_assignments.py` | 36 | `app.quality.method_assignment_workflow` |
| `20260719_19_quality_finding_core.py` | 30 | `app.quality.quality_finding_workflow` |
| `20260719_20_eng_evaluation_core.py` | 29 | `app.quality.engineering_evaluation_workflow` |
| `20260720_21_defect_model.py` | 27 | `app.quality.defect_seed` |
| `20260720_21_defect_model.py` | 28 | `app.quality.defect_workflow` |
| `20260721_22_defect_dispositions.py` | 29 | `app.quality.defect_disposition_models` |

Exact set фиксируется в policy test как historical debt. Любой девятый statement, восьмой
file, изменение module path или перенос импорта в другой historical file падает. B-03 не
редактирует эти files и не делает semantic/checksum rewrite. Их clean-install dependency
закрывается self-contained baseline B-04.

Вариант B не выбран, потому что текущий `alembic check` блокирует workforce metadata, а не
historical imports; доказанной необходимости менять DDL files нет. Вариант C отклонён как
сохранение зависимости history от runtime code.

## 14. Offline SQL policy

Выбран **вариант B**.

Текущая historical chain имеет известное online-only ограничение:
`20260721_23_disp_events.py:41-49` вызывает `op.get_bind()`, выполняет `SELECT to_regclass`
и вызывает `.scalar()`. В offline mode bind result отсутствует; фактический
`alembic upgrade head --sql` завершается `AttributeError` на строке 46.

Контракт:

- B-03 acceptance не требует успешного full offline render 28 historical revisions;
- migration 23 фиксируется как единственная принятая known limitation текущего manifest;
- B-03 не изменяет migration 23;
- любая revision, созданная после B-03 и до baseline cut, по умолчанию обязана успешно
  рендерить собственный range `down_revision:revision --sql`;
- online-only declaration для новой revision требует отдельного review и явного
  `HISTORICAL MIGRATION EXCEPTION`; молчаливый runtime SELECT запрещён;
- `canonical_baseline_v1` B-04 обязан полностью поддерживать offline render;
- revisions после baseline также offline-safe по умолчанию.

Static test обнаруживает `op.get_bind`, `bind.execute`, connection inspection и другие
runtime DB calls; exact exception разрешена только migration 23 текущего frozen set.

## 15. Tests

Pure contract tests размещаются в `09_Разработка/backend/migration_contract_tests/`, а не
в `tests/`. Это исключает загрузку `tests/conftest.py:91-98`, который автоматически запускает
`alembic upgrade head` на configured database.

### Metadata

| Test ID | Contract |
|---|---|
| TEST-B03-METADATA-001 | Фактические schemas равны пяти canonical schemas |
| TEST-B03-METADATA-002 | Workforce module/tables отсутствуют |
| TEST-B03-METADATA-003 | Current provider содержит ровно 69 tables и полный module registry |
| TEST-B03-METADATA-004 | Каждый canonical FK разрешается внутри canonical metadata |
| TEST-B03-METADATA-005 | Synthetic canonical table принимается filter без правки name list |

### Filtering

| Test ID | Contract |
|---|---|
| TEST-B03-FILTER-001 | Reflected table в canonical schema включается независимо от имени |
| TEST-B03-FILTER-002 | `test.*`, workforce и noncanonical schemas исключаются |
| TEST-B03-FILTER-003 | Unknown canonical DB table не скрывается и становится drift |
| TEST-B03-FILTER-004 | Alembic platform marker не считается canonical table drift |

### Imports

| Test ID | Contract |
|---|---|
| TEST-B03-IMPORT-001 | Новый `app.*` import блокируется AST gate |
| TEST-B03-IMPORT-002 | Failure содержит path, line и imported module |
| TEST-B03-IMPORT-003 | Exact debt равен 7 files / 8 statements |

### Graph

| Test ID | Contract |
|---|---|
| TEST-B03-GRAPH-001 | Ровно один root `20260702_02_hr_core` |
| TEST-B03-GRAPH-002 | Ровно один head `20260721_24_disp_supersede` |
| TEST-B03-GRAPH-003 | Все 28 revision IDs уникальны |
| TEST-B03-GRAPH-004 | Каждый non-root `down_revision` разрешается; cycles/orphans отсутствуют |

### Alembic

| Test ID | Contract |
|---|---|
| TEST-B03-ALEMBIC-001 | `alembic heads` успешен и выводит один head |
| TEST-B03-ALEMBIC-002 | `alembic history` успешен и содержит root→head chain |
| TEST-B03-ALEMBIC-003 | Read-only `alembic current` выводит historical head |
| TEST-B03-ALEMBIC-004 | Read-only `alembic check` возвращает no new operations |
| TEST-B03-ALEMBIC-005 | `check` не падает на workforce metadata/FK |

### Offline

| Test ID | Contract |
|---|---|
| TEST-B03-OFFLINE-001 | Migration 23 — exact current offline exception |
| TEST-B03-OFFLINE-002 | Любая новая revision с runtime DB call без exception блокируется |

### Safety and review gates

| Gate ID | Verification | Expected |
|---|---|---|
| B03-SAFETY-001 | `python -m pytest migration_contract_tests -q` | pytest не загружает `tests/conftest.py` |
| B03-SAFETY-002 | dry-run migration validation command | Состояние рабочей БД до и после проверки идентично |
| B03-SCOPE-001 | `git diff --name-status B03_SOURCE_COMMIT...HEAD` | Diff содержит только разрешённый B-03 scope; migrations/versions, runtime, workforce, baseline/adoption отсутствуют |
| B03-SCOPE-002 | `git diff --check B03_SOURCE_COMMIT...HEAD` | Нет whitespace errors |

`B03-SAFETY-001` и `B03-SAFETY-002` являются acceptance/review gates. Настоящая
спецификация фиксирует только их контракт и не предписывает реализацию дополнительных тестов.
`B03-SCOPE-001` и `B03-SCOPE-002` являются review gates для конкретного Git range, а не
постоянными pytest tests.

## 16. Exact file scope

Стабильная Git-база B-03:

```text
B03_SOURCE_COMMIT: d32eb25b73a2e57968b6165a7c294a56898feb6c
```

Состав изменений B-03 проверяется только относительно этой базы через:

```text
git diff --name-status B03_SOURCE_COMMIT...HEAD
git diff --check B03_SOURCE_COMMIT...HEAD
```

Для исполнения `B03_SOURCE_COMMIT` подставляется указанным полным SHA. Проверка относится к
зафиксированному B-03 Git range. Transient working-tree state не кодируется как постоянный
pytest acceptance test.

Предполагаемый implementation scope:

| Action | Path | Responsibility |
|---|---|---|
| Create | `09_Разработка/backend/app/shared/canonical_metadata.py` | Явная регистрация и canonical metadata provider |
| Create | `09_Разработка/backend/migrations/canonical_boundary.py` | Pure schema/filter policy для Alembic env |
| Modify | `09_Разработка/backend/migrations/env.py` | Подключение provider/filter, сохранение historical marker |
| Create | `09_Разработка/backend/migration_contract_tests/__init__.py` | Изолированный pure test package |
| Create | `09_Разработка/backend/migration_contract_tests/test_canonical_metadata.py` | Metadata/module/FK coverage |
| Create | `09_Разработка/backend/migration_contract_tests/test_alembic_boundary.py` | Schema/object filtering |
| Create | `09_Разработка/backend/migration_contract_tests/test_migration_import_policy.py` | AST import policy/debt |
| Create | `09_Разработка/backend/migration_contract_tests/test_migration_graph.py` | Root/head/edge integrity |
| Create | `09_Разработка/backend/migration_contract_tests/test_offline_policy.py` | Offline-safe policy/exact exception |
| Create | `09_Разработка/backend/migration_contract_tests/test_alembic_cli_contract.py` | Non-DB `heads/history` CLI contract |
| Modify at closure | `docs/project/TASK_REGISTRY.md` | B-03 status/evidence only |
| Modify at closure | `docs/project/TASK_B-03_MIGRATION_FOUNDATION_SPEC.md` | Review/acceptance evidence only |

`alembic.ini` не меняется: аудит не выявил B-03 requirement, требующего его правки.

Запрещённый implementation scope:

- `migrations/versions/*.py`;
- `app/main.py`;
- `app/workforce/**`;
- baseline/archive directories;
- `tests/conftest.py` и существующие integration tests;
- TEST DB scripts/config;
- 9D-4A-5 files.

## 17. PowerShell 5.1 commands

Рабочий каталог:

```powershell
Set-Location D:\WeldPassport\09_Разработка\backend
```

Pure contracts:

```powershell
python -m pytest migration_contract_tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Graph/CLI без подключения к БД:

```powershell
python -m alembic heads
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m alembic history
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Read-only current database verification:

```powershell
python -m alembic current
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m alembic check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Git scope review выполняется из репозитория:

```powershell
git diff --name-status d32eb25b73a2e57968b6165a7c294a56898feb6c...HEAD
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git diff --check d32eb25b73a2e57968b6165a7c294a56898feb6c...HEAD
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Перед `current/check` оператор обязан подтвердить, что configured database — текущая
существующая БД на historical head. Разрешены только эти read-only команды. `upgrade`,
`downgrade`, `revision`, `stamp` и pytest из `tests/` до TEST-DB Foundation запрещены.

Expected outputs:

- `heads`: `20260721_24_disp_supersede (head)`;
- `current`: `20260721_24_disp_supersede (head)`;
- `check`: `No new upgrade operations detected.`;
- pure pytest: 0 failed.

Full historical `python -m alembic upgrade head --sql` не является B-03 acceptance command;
его известный failure классифицирован в разделе 14.

## 18. Binary acceptance criteria

- [ ] Provider содержит только `hr`, `welding`, `project`, `engineering`, `quality`.
- [ ] Current snapshot содержит ровно 69 canonical tables.
- [ ] Workforce tables/module отсутствуют в canonical provider.
- [ ] Все canonical FK разрешаются только в canonical metadata.
- [ ] Новая canonical table не требует изменения table-name list.
- [ ] Reflected unknown canonical table не скрывается.
- [ ] `target_metadata` указывает на canonical provider.
- [ ] `alembic heads` и `history` подтверждают один graph.
- [ ] `alembic current` сохраняет historical head.
- [ ] `alembic check` завершается без drift и без workforce exception.
- [ ] AST gate блокирует любой новый `app.*` import.
- [ ] Historical debt равен exact 7 files / 8 statements.
- [ ] Root/head/IDs/down_revision graph integrity доказана.
- [ ] Historical revisions не изменены.
- [ ] Marker не перенесён, не stamped и не удалён.
- [ ] `public.alembic_version` не создан B-03.
- [ ] Runtime router/main не изменены.
- [ ] Baseline/archive/fingerprint не созданы.
- [ ] Pure tests не загружают `tests/conftest.py`.
- [ ] Рабочая БД не изменяется тестами или командами B-03 acceptance.
- [ ] Existing backend runtime files вне explicit scope не имеют diff.
- [ ] B-04 и TEST-DB Foundation остаются отдельными Tasks.

Любой unchecked criterion блокирует B-03 closure.

## 19. Traceability

| Gap ID | Requirement | Block | Test / Gate ID | Command | Acceptance |
|---|---|---|---|---|---|
| B03-G01 | Canonical-only provider | A | METADATA-001/002 | `python -m pytest migration_contract_tests/test_canonical_metadata.py -q` | только canonical schemas/tables |
| B03-G02 | 69 current tables | A | METADATA-003 | `python -m pytest migration_contract_tests/test_canonical_metadata.py -q` | count = 69 |
| B03-G03 | Workforce excluded | A/B | METADATA-002, ALEMBIC-005 | `python -m alembic check` | no workforce table/error |
| B03-G04 | FK closure | A | METADATA-004 | `python -m pytest migration_contract_tests/test_canonical_metadata.py -q` | 0 external FK |
| B03-G05 | Schema allowlist | B | FILTER-001/002 | `python -m pytest migration_contract_tests/test_alembic_boundary.py -q` | exact five schemas |
| B03-G06 | No table whitelist | B | METADATA-005 | `python -m pytest migration_contract_tests/test_alembic_boundary.py -q` | synthetic name included |
| B03-G07 | Platform/version object | B | FILTER-004, SCOPE-001 | pytest boundary contract + Git scope review | marker treated separately; marker files unchanged |
| B03-G08 | All tables visible | A/B | METADATA-003 | `python -m pytest migration_contract_tests/test_canonical_metadata.py -q` | all 69 visible |
| B03-G09 | Unknown canonical drift | B | FILTER-003 | `python -m pytest migration_contract_tests/test_alembic_boundary.py -q` | object not filtered |
| B03-G10 | Future auto-visibility | B | METADATA-005 | `python -m pytest migration_contract_tests/test_alembic_boundary.py -q` | no name-list edit |
| B03-G11 | Import policy | C | IMPORT-001/002 | `python -m pytest migration_contract_tests/test_migration_import_policy.py -q` | new import fails path:line |
| B03-G12 | Historical debt | C | IMPORT-003 | `python -m pytest migration_contract_tests/test_migration_import_policy.py -q` | exact 7/8 set |
| B03-G13 | One graph | C/D | GRAPH-001…004, ALEMBIC-001/002 | `python -m pytest migration_contract_tests/test_migration_graph.py migration_contract_tests/test_alembic_cli_contract.py -q` | 1 root/head, 28 IDs |
| B03-G14 | Offline contract | C | OFFLINE-001/002 | `python -m pytest migration_contract_tests/test_offline_policy.py -q` | exact exception only |
| B03-G15 | Metadata coverage | A/B | METADATA-001…005 | `python -m pytest migration_contract_tests/test_canonical_metadata.py migration_contract_tests/test_alembic_boundary.py -q` | all tests pass |
| B03-G16 | Model registration | A | METADATA-003 | `python -m pytest migration_contract_tests/test_canonical_metadata.py -q` | filesystem = registry |
| B03-G17 | Alembic check | B/D | ALEMBIC-004/005 | `python -m alembic check` | no operations/error |
| B03-G18 | Runtime unchanged | B/D | SCOPE-001 | `git diff --name-status B03_SOURCE_COMMIT...HEAD` | no runtime diff |
| B03-G19 | Marker unchanged | B/D | SCOPE-001, ALEMBIC-003 | Git scope review + `python -m alembic current` | historical head retained; marker files unchanged |
| B03-G20 | B-04 excluded | B/D | SCOPE-001 | `git diff --name-status B03_SOURCE_COMMIT...HEAD` | no baseline/adoption files |

В таблице test ID используется короткая форма; полный префикс каждого test ID —
`TEST-B03-`. Gate IDs используются в полной форме `B03-SAFETY-*` и `B03-SCOPE-*`.

## 20. Dependencies and acceptance levels

```text
ADR-025 ACCEPTED
      ↓
B-03 spec review/acceptance
      ↓
B-03A → B-03B → B-03C → B-03D
      ↓
B-03 accepted
      ↓
B-04 specification and implementation
      ↓
TEST-DB Foundation
      ↓
9D-4A-5A
```

**Documentation/code review acceptance B-03:** pure contract tests, static scope proof,
read-only `current/check`, no database mutation.

**Clean-install evidence:** не является второй незакрытой частью B-03. Оно принадлежит
B-04 baseline и последующей TEST-DB Foundation. Поэтому dependency graph ADR-025 не
противоречит closure B-03 до появления TEST DB.

## 21. Risks and stop conditions

| Risk | Control | Stop condition |
|---|---|---|
| Registry забывает отдельный model module | filesystem/module coverage | несовпадение registry |
| Global Base загрязнена workforce import | isolated provider import + fail-fast schemas | любая noncanonical table |
| Schema filter скрывает canonical drift | synthetic/unknown reflected tests | table canonical schema filtered out |
| Public/test marker перепутаны | before/after current + scope guard | current head потерян или public marker создан |
| `alembic check` выявляет реальный model/DB drift | fail closed, показать operations | любой non-empty diff |
| Для check потребуется historical edit | HISTORICAL MIGRATION EXCEPTION process | работа останавливается |
| Pure test активирует existing conftest | separate test root | import/fixture из `tests/conftest.py` |
| Offline debt расширяется | AST exact exception | новый runtime DB call |
| B-04 попадает в B-03 diff | forbidden path/content guards | baseline/archive/stamp/adoption change |

## 22. Commit strategy

После отдельных review checkpoint рекомендуются commits:

1. `docs(migrations): add B-03 migration foundation spec`;
2. `refactor(migrations): isolate canonical metadata`;
3. `refactor(migrations): replace table whitelist with schema boundary`;
4. `test(migrations): enforce metadata and migration contracts`;
5. `docs(migrations): close B-03 foundation task`.

Каждый commit выполняется только после отдельного разрешения пользователя. Настоящий этап
не выполняет staging, commit или push.
