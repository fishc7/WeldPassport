# ADR-025 — Migration Governance and Legacy Schema Boundary

Дата принятия: 2026-07-22

Статус: **ACCEPTED**

Подготовлен по результатам
[[docs/project/ARCHITECTURE_SESSIONS#Architecture Session 010 — Migration Governance and Legacy Boundary|Architecture Session 010]].
Первый независимый review пакета завершён с вердиктом `CHANGES REQUIRED`; findings
R-025-01…R-025-07 устранены в настоящей редакции. Повторный
[[docs/project/ARCHITECTURE_SESSIONS#I. Финальный независимый review|финальный независимый review]]
от 2026-07-22 завершён с вердиктом `APPROVED`; после закрытия R-025-01…R-025-07
решение принято.

Контур: Database / Migration Governance / Legacy Boundary.

Связано: [[docs/project/ADR-005-legacy-workforce-deprecation|ADR-005 — вывод legacy-модуля workforce из эксплуатации]] ·
[[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]].

Настоящий ADR определяет целевую границу управления схемой. Он не реализует B-03,
B-04 или TEST-DB Foundation, не изменяет существующую БД и сам по себе не разрешает
изменять код, модели или миграции без отдельных Task Implementation Specification.

---

## A. Контекст и проблема

До принятия ADR-025 одновременно существовали три несовместимых представления схемы:

1. Общая SQLAlchemy `Base.metadata` после импорта всех модулей содержит **76 таблиц**:
   **69 canonical** в схемах `hr`, `welding`, `project`, `engineering`, `quality` и
   **7 legacy workforce** в схеме `test`.
2. Табличный `include_object` в Alembic допускает только **31 таблицу metadata**:
   24 canonical и 7 workforce. Он скрывает 45 canonical-таблиц, в том числе часть
   `engineering`, большинство `quality` и будущие таблицы, не добавленные вручную в whitelist.
3. Активная историческая цепочка содержит **28 revisions**: root
   `20260702_02_hr_core`, head `20260721_24_disp_supersede`. Она создаёт 69
   canonical-таблиц, тогда как legacy-схема дополнительно поддерживается отдельным
   `scripts/create_tables.py` через `create_all`.

Из-за смешения canonical и workforce metadata `alembic check` не может построить граф:
legacy FK `test.ДОПУСКИ_К_ОБЪЕКТУ.ID_Объекта` ссылается на отсутствующую в backend metadata
таблицу `test.ОБЪЕКТЫ`. При этом table-name whitelist скрывает canonical drift вместо его
обнаружения.

Дополнительные нарушения migration governance:

- семь исторических revisions импортируют изменяемые константы или workflow из `app.*`;
- `alembic_version` привязан к настраиваемой legacy-схеме `POSTGRES_SCHEMA` (`test` по умолчанию);
- пустая PostgreSQL database не может доказуемо пройти `alembic upgrade head` до рабочей
  canonical-схемы;
- offline upgrade текущей цепочки из 28 revisions не является самодостаточным;
- новая canonical-таблица, включая будущую quality idempotency table Task 9D-4A-5,
  остаётся невидимой, пока её имя вручную не внесено в whitelist.

Следовательно, Alembic фактически не был единым источником истины для canonical schema.

## B. Рассмотренные варианты

### Вариант A — Full Alembic ownership

Передать Alembic все canonical и legacy-таблицы, включая workforce и схему `test`.

Отклонён: закрепляет deprecated-контур как часть целевой схемы, требует достраивать
неполную legacy metadata и противоречит направлению ADR-005.

### Вариант B — Canonical / Legacy Separation

Alembic управляет только canonical-схемами. Workforce и схема `test` остаются временным
legacy-контуром с отдельным compatibility profile.

**Выбран для целевой модели.** Вариант восстанавливает drift detection, позволяет создать
чистый baseline и TEST DB, не превращая deprecated workforce в постоянную часть продукта.
Нормативное принятие ожидает финального независимого review настоящей редакции.

### Вариант C — Two Alembic contexts

Создать независимые Alembic contexts и истории revisions для canonical и legacy.

Отклонён для текущего этапа: создаёт второй долгоживущий migration lifecycle для контура,
который подлежит выводу. Может рассматриваться только новым ADR, если legacy получит
самостоятельный срок жизни и владельца.

## C. Решение: canonical schema boundary

### C.1. Схемы под управлением canonical Alembic

Canonical Alembic управляет целиком следующими схемами:

- `hr`;
- `welding`;
- `project`;
- `engineering`;
- `quality`.

После появления соответствующих доменов в ту же boundary входят схемы:

- `identity`;
- `production`;
- `documents`;
- `audit`.

Включение будущей схемы фиксируется её архитектурным основанием и отдельной Task, но внутри
принятой canonical-схемы все таблицы автоматически участвуют в migration governance.

Служебный `project_control` остаётся отдельным приложением и отдельным migration lifecycle;
он не входит в canonical Alembic backend WeldPassport.

### C.2. Legacy boundary

Legacy-контур включает:

- модуль `app.workforce`;
- схему `test`;
- кириллические legacy-таблицы;
- переходные скрипты `09_Разработка/src/` и `scripts/create_tables.py` в их текущей границе.

Legacy-контур:

- не входит в canonical `target_metadata`;
- не управляется canonical Alembic;
- не может получать новые функции, таблицы или бизнес-правила;
- не может становиться источником новых междоменных FK;
- удаляется, переносится или получает отдельный migration lifecycle только по новому ADR.

`scripts/create_tables.py` признаётся временным legacy bootstrap-механизмом. Его использование
запрещено в canonical deployment и canonical CI.

## D. Alembic governance

1. `target_metadata` содержит только модели canonical-схем.
2. `app.workforce.models` не импортируется в canonical Alembic environment.
3. `include_object` использует schema-level allowlist canonical-схем.
4. Table-name whitelist для canonical-таблиц запрещён.
5. Любая новая таблица в canonical-схеме автоматически видна autogenerate и drift detection.
6. Неизвестная таблица внутри canonical-схемы считается drift, а не молча игнорируется.
7. Таблицы и схемы вне canonical boundary не включаются в autogenerate diff.
8. `alembic check` является обязательной проверкой B-03, CI и последующих migration Tasks.
9. Расположение canonical `alembic_version` не зависит от legacy `POSTGRES_SCHEMA`;
   единственная целевая служебная схема настоящего решения — `public`.
10. Отдельные проверки обязаны доказывать полное соответствие canonical metadata,
    schema-level filter и migration coverage.

Таким образом, будущая quality idempotency table Task 9D-4A-5 попадёт под Alembic
автоматически, без ручного добавления её имени в `env.py`.

## E. Historical migrations policy

На дату подготовки ADR активная historical chain содержит **28 revisions**:

```text
root: 20260702_02_hr_core
head: 20260721_24_disp_supersede
revision count: 28
```

Обозначение `01–24` в исторических именах является частью revision IDs и не означает
количество файлов. Scope архива определяется не диапазоном номеров, а полным frozen
revision manifest на canonical baseline cut.

Frozen manifest для каждого revision обязательно фиксирует:

- revision ID;
- `down_revision`;
- filename;
- криптографический checksum содержимого.

Все revisions frozen manifest являются историческими артефактами и сохраняются неизменными:

- не редактируются;
- не удаляются;
- не переименовываются задним числом;
- после принятия `canonical_baseline_v1` переводятся в immutable historical archive.

Архив хранится в отдельном архивном каталоге backend migrations, который **не входит** в
активные Alembic `version_locations`, не расположен внутри автоматически сканируемого
`versions` path и не загружается Alembic. Конкретное имя каталога фиксируется B-04
Implementation Specification; его отделённость от любого active scan является нормативным
инвариантом. Рядом хранится checksum manifest. Существующие revision IDs и документные
ссылки сохраняются для аудита и расследования истории.

После переключения на baseline в active `version_locations` остаётся ровно один root и один
head; historical archive не может создавать второй root/head.

Новые migrations должны быть self-contained. В них запрещены:

```text
from app.*
import app.*
```

Разрешены:

- Python standard library;
- Alembic;
- SQLAlchemy;
- PostgreSQL dialect SQLAlchemy;
- буквальные migration-local constants и seed data.

Изменение application enum, workflow или модели не должно менять поведение уже принятой
migration.

## F. Canonical baseline v1

`canonical_baseline_v1` создаётся отдельной Task **B-04 — Canonical Baseline Adoption**
после принятия B-03.

Baseline является self-contained root revision и создаёт на пустой PostgreSQL database:

- canonical-схемы;
- все canonical-таблицы;
- PK, FK, UNIQUE и CHECK constraints;
- индексы;
- обязательные canonical seeds.

Baseline не использует `Base.metadata.create_all`, не импортирует `app.*` и не включает
legacy workforce или схему `test`.

### F.1. Canonical baseline cut

Baseline cut выполняется только после:

1. нормативного принятия ADR-025;
2. завершения и приёмки B-03;
3. фиксации canonical metadata boundary;
4. определения source commit, который становится единственным источником baseline.

Cut фиксирует единый доказательный комплект:

```text
source commit
  + frozen revision manifest
  + canonical schema fingerprint
```

На короткое maintenance-окно cut вводится **migration freeze**: создание, изменение и merge
новых active migrations запрещены. После cut любые новые schema changes создаются только
как revisions поверх `canonical_baseline_v1`; параллельные ветки обязаны rebase на новый
baseline. Task 9D-4A-5 и её будущие migrations в baseline **не входят** и остаются после
B-03, B-04 и TEST-DB Foundation.

### F.2. Canonical schema fingerprint

Fingerprint описывает только canonical boundary и включает:

- **schemas:** имена canonical-схем;
- **tables:** полные schema-qualified имена таблиц;
- **columns:** имена, типы, nullable и `normalized defaults` для server-side значений;
- **constraints:** PK, UNIQUE, FK и нормализованные CHECK expressions;
- **indexes:** обычные индексы, уникальность и partial predicates;
- **sequences:** identity/sequence definitions;
- **seeds:** обязательные canonical reference data и их ожидаемые ключи/значения.

Любой лишний объект внутри canonical-схем запрещён, кроме объекта, явно включённого в
утверждённый platform allowlist B-04. Legacy-схемы и legacy-объекты в fingerprint не входят.
Любое отсутствие, отличие или неразрешённый extra canonical object означает drift и
останавливает процесс fail closed. Automatic repair и предположительная нормализация БД
перед stamp запрещены.

### F.3. Adoption существующей БД

Существующая БД принимается только отдельным maintenance-процессом B-04:

```text
backup
  ↓
canonical schema fingerprint
  ↓
validate historical marker
  ↓
maintenance transaction
  ↓
public.alembic_version stamp
  ↓
alembic current/check + smoke verification
  ↓
adoption report
```

До adoption обязательно проверяется, что `test.alembic_version` существует и содержит head
frozen historical manifest. До maintenance transaction отсутствие или несовпадение marker
останавливает процесс.

B-04 в одном maintenance-процессе переключает canonical Alembic на
`public.alembic_version` и выполняет stamp `canonical_baseline_v1` без повторного создания
таблиц. После успешной проверки:

- `public.alembic_version = canonical_baseline_v1` является единственным active marker;
- исходное значение `test.alembic_version`, fingerprint, source commit, manifest checksums
  и результаты verification сохраняются в immutable adoption report;
- legacy `test.alembic_version` удаляется как active version table и не используется
  canonical Alembic.

Повторный adoption запрещён, если `public.alembic_version` уже содержит
`canonical_baseline_v1` или более новый canonical revision. Несовпадение fingerprint,
historical marker или verification останавливает adoption. Rollback adoption не выполняется
через Alembic downgrade: до финальной приёмки восстанавливается проверенный backup, после
приёмки применяется отдельная повторная remediation procedure.

### F.4. Downgrade governance

Архивирование frozen historical manifest не удаляет доказательную историю downgrade-функций.
Новые revisions после baseline обязаны иметь проверяемый downgrade в своей локальной
границе, если отдельная Task явно не обоснует forward-only migration.

Production downgrade через `canonical_baseline_v1`, уничтожающий canonical schema, не
является штатным откатом. Production recovery выполняется из проверенного backup и/или
forward remediation. Destructive baseline downgrade допускается только на защищённой
одноразовой тестовой БД.

## G. Runtime profiles

### G.1. Canonical profile

Canonical profile является default:

- workforce router не подключается;
- legacy metadata не загружается;
- наличие схемы `test` не требуется;
- canonical API запускается после проверки canonical database revision.

### G.2. Legacy compatibility profile

Compatibility profile включается только явно и временно:

- выполняет preflight наличия и совместимости legacy schema;
- подключает workforce router только после успешного preflight;
- не создаёт legacy-таблицы автоматически;
- используется для контролируемого backup/import и поддержки существующих потребителей;
- имеет отдельные compatibility tests и не входит в canonical clean-install acceptance.

Включение профиля не возвращает workforce в canonical Alembic и не отменяет deprecated
статус.

Runtime composition не входит в B-03 и B-04. Отдельная Task
**RUNTIME-LEGACY-COMPATIBILITY-PROFILE** отвечает за `app/main.py` composition,
конфигурацию profile switch, условную загрузку workforce router и preflight legacy schema.
Точное имя config/env-параметра определяется её Implementation Specification. Task должна
быть принята до canonical clean-install application acceptance и application-test стадии
TEST-DB Foundation.

## H. TEST-DB Foundation

TEST-DB Foundation является отдельной prerequisite после B-04:

- обязательный `TEST_DATABASE_URL` указывает на отдельную PostgreSQL database, а не на
  отдельную schema рабочей БД;
- fallback на рабочий DSN запрещён;
- normalized test/work DSN сравниваются до создания engine, Session или запуска Alembic;
- обязательны test marker, production denylist и явный opt-in для destructive operations;
- любой неопределённый или небезопасный DSN завершает процесс fail-fast;
- canonical CI создаёт ephemeral database, выполняет `alembic upgrade head`, проверяет
  `current/head` и `alembic check`, запускает migration/model/application tests и удаляет
  только созданную test database.

Legacy compatibility tests выполняются отдельно и не используют рабочую БД.

## I. Отношение к ADR-005

ADR-025 **не отменяет ADR-005** и не переписывает его историю.

Сохраняются положения ADR-005:

- workforce имеет статус deprecated;
- новые функции, таблицы и бизнес-правила в workforce запрещены;
- новые интеграции используют `hr` и `welding`;
- legacy-потребители поддерживаются только до миграции;
- миграция данных и окончательное удаление выполняются отдельными этапами;
- удаление legacy требует отдельного ADR и backup.

ADR-025 заменяет только технические последствия ADR-005 в части:

1. участия workforce models в canonical `target_metadata`;
2. безусловного участия workforce в canonical Alembic и runtime composition.

Историческая запись ADR-005 о `WORKFORCE_MANAGED_TABLES` сохраняется как состояние на дату
принятия ADR-005; с принятием ADR-025 она получает статус `SUPERSEDED_BY ADR-025` только в
указанной технической границе.

## J. Последствия

### Положительные

- Alembic становится источником истины для canonical schema;
- новые canonical-таблицы автоматически участвуют в drift detection;
- clean install становится воспроизводимым;
- появляется безопасная основа TEST DB и CI;
- legacy не закрепляется как часть целевого продукта;
- разблокируется последовательная подготовка Task 9D-4A-5.

### Отрицательные и стоимость

- требуется отдельная реализация B-03;
- требуется полный self-contained baseline B-04;
- adoption существующей БД требует maintenance window, backup и fingerprint;
- до вывода legacy нужен явный compatibility profile и отдельные tests;
- frozen historical chain больше не используется для clean install.

## K. Границы реализации и зависимости

```text
ADR-025
   ↓
B-03 — Migration Foundation
   ↓
B-04 — Canonical Baseline Adoption
   ↓
TEST-DB Foundation
   ↓
Task 9D-4A-5A

ADR-025
   ↓
RUNTIME-LEGACY-COMPATIBILITY-PROFILE
   ↓
canonical application acceptance / TEST-DB application tests
```

### B-03 — Migration Foundation

Включает canonical metadata boundary, `env.py`, schema-level filtering, migration import
policy, coverage checks и восстановление `alembic check`. Не создаёт baseline, не переносит
существующий version marker и не изменяет runtime composition.

### B-04 — Canonical Baseline Adoption

Включает clean PostgreSQL baseline, архивирование активной цепочки, adoption существующей
БД и legacy coexistence boundary. B-04 является **единственным владельцем** физического
переноса version marker, переключения на `public.alembic_version`, stamp baseline и adoption
существующей БД. Не исправляет доменную реализацию 9D-4A-5.

### RUNTIME-LEGACY-COMPATIBILITY-PROFILE

Отдельная Task изменяет только runtime composition/configuration и legacy router loading.
Она не меняет canonical metadata, Alembic history, baseline или legacy business rules.

### Execution gate

Начало B-03 code fix требует отдельной принятой Task Implementation Specification.
B-04 не начинается до приёмки B-03. Task 9D-4A-5A не начинается до приёмки B-03, B-04,
TEST-DB Foundation и остальных prerequisites своей спецификации.

## L. Статус реализации на дату принятия

- Session 010 завершена; финальный независимый review — `APPROVED`;
- ADR-025 — `ACCEPTED` 2026-07-22 после закрытия R-025-01…R-025-07;
- B-03 — `not_designed`, реализация не начата;
- B-04 — `not_designed`, реализация не начата;
- TEST-DB Foundation — `not_designed`, реализация не начата;
- RUNTIME-LEGACY-COMPATIBILITY-PROFILE — `not_designed`, реализация не начата;
- backend, models, migrations, API и tests настоящим ADR не изменены.
