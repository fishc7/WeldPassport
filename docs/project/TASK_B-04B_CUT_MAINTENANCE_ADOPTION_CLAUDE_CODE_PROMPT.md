# Prompt для Claude Code / Cursor — B-04B Cut & Maintenance Adoption

Начинай только от отдельно принятого B-04A head. Если нет подписанного
`B04A_VERIFIED` evidence, совпадающих artifact digests и отдельной приёмки B-04A,
остановись.

## Цель

Подготовить repository cut, атомарный перенос canonical version marker в
`public.alembic_version`, rehearsal на восстановленной копии backup и отдельный
maintenance adoption существующей PostgreSQL-БД.

## Обязательные источники

- `AGENTS.md`;
- `docs/project/ADR-025-migration-governance-and-legacy-schema-boundary.md`;
- `docs/project/TASK_B-04_CANONICAL_BASELINE_ADOPTION_SPEC.md`;
- `docs/project/TASK_B-04A_BASELINE_BUILD_VERIFICATION_IMPLEMENTATION_PLAN.md`;
- `docs/project/TASK_B-04B_CUT_MAINTENANCE_ADOPTION_IMPLEMENTATION_PLAN.md`;
- все принятые B-04A artifacts и evidence.

## Разрешено до maintenance gate

- создать pure adoption state/preflight/transaction/postflight tests;
- создать B-04B tooling в `migrations/b04/`;
- переместить frozen revisions в archive без изменения байтов;
- активировать byte-identical baseline candidate;
- изменить `alembic.ini` и `migrations/env.py` строго по принятому cut contract;
- выполнить rehearsal только на восстановленной изолированной копии backup;
- подготовить полный diff и evidence.

## Запрещено до отдельного maintenance confirmation

- подключаться к рабочей БД;
- выполнять marker transfer или stamp на рабочей БД;
- удалять `test.alembic_version` на рабочей БД;
- deploy cut release против рабочей БД;
- возобновлять writers;
- снимать migration freeze;
- запускать application tests;
- изменять schema `test` или legacy business tables;
- automatic repair;
- повторять transfer при неоднозначном состоянии;
- staging, commit и push без отдельного разрешения.

## Repository cut contract

После cut:

- archive содержит ровно 31 byte-identical revision;
- каждый SHA-256 совпадает с frozen manifest;
- archive не входит в active Alembic scan;
- active `migrations/versions` содержит только `canonical_baseline_v1.py`;
- active graph имеет один root/head;
- `version_locations` задан явно;
- online/offline `version_table_schema="public"`;
- `version_table_pk=True`;
- новые revisions могут следовать только за baseline.

## Preflight contract

Fail closed проверяет:

- exact target DB identity и PostgreSQL 16.x;
- maintenance approval и остановку writers/migrators;
- custom-format backup, SHA-256 и успешный `pg_restore`;
- accepted source/manifest/fingerprint/seed digests;
- historical marker: ровно одна строка head 27;
- полное отсутствие public marker;
- live fingerprint и 15 exact seeds;
- отсутствие unknown objects, DDL sessions и long transactions.

Успех создаёт immutable `PREPARED` evidence и одноразовый token.

## Transaction contract

Одна caller-owned PostgreSQL transaction:

```text
SERIALIZABLE
→ bounded timeouts
→ search_path=pg_catalog
→ advisory transaction lock
→ identity recheck
→ SHARE locks canonical tables
→ ACCESS EXCLUSIVE historical marker
→ marker/fingerprint recheck
→ create public.alembic_version
→ insert canonical_baseline_v1
→ drop test.alembic_version
→ internal verification
→ COMMIT
```

Public marker shape:

```sql
CREATE TABLE public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
```

Не используй отдельный `alembic stamp` subprocess.

## Rehearsal gate

До рабочей БД обязательно:

- `pg_restore` backup в isolated PostgreSQL 16.x;
- fingerprint restored copy;
- полный preflight;
- marker transaction;
- postflight;
- отдельная recovery rehearsal;
- immutable report `B04B_REHEARSAL_ACCEPTED`.

## Production maintenance gate

Остановись и запроси новое подтверждение, содержащее:

- exact target database;
- maintenance window;
- backup digest;
- rehearsal digest;
- recovery owner;
- external append-only report destination.

Ранее выданное общее разрешение не заменяет этот gate.

## Recovery

- до transaction: stop, БД не менялась;
- внутри transaction: rollback и доказательство исходного marker state;
- ambiguous state: restore проверенного backup;
- commit без acceptance: `COMMITTED_UNVERIFIED`, writers остаются остановлены;
- failed postflight до acceptance: backup restore + previous release/config;
- после `ADOPTION_ACCEPTED`: только отдельно согласованная forward remediation.

## Приёмка кода до production

```powershell
$PythonExe = "D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe"
& $PythonExe -m pytest migration_contract_tests -q
& $PythonExe -m compileall migrations/b04 migrations/versions
& $PythonExe -m alembic heads
& $PythonExe -m alembic history
git diff --check
```

## Формат результата

До maintenance:

1. B-04A evidence reference;
2. список файлов и rename proof;
3. archive checksum proof;
4. полный diff;
5. RED/GREEN evidence;
6. pure test counts;
7. rehearsal evidence and digests;
8. stop conditions;
9. proposed commits;
10. явная остановка перед рабочей БД.

После отдельно подтверждённого maintenance:

1. target identity без credentials;
2. backup/rehearsal/token digests;
3. transaction result;
4. postflight results;
5. immutable report digest;
6. signed status `ADOPTION_ACCEPTED` либо recovery result.
