# Prompt — B-04A Volatile Endpoint Recovery

Работай только в:

```text
D:\WeldPassport\.worktrees\b04-baseline
```

## Цель

Устранить подтверждённый дефект B-04A operator flow: после перезапуска Docker
Desktop динамический mapping PostgreSQL изменился с `127.0.0.1:51999` на
`127.0.0.1:52815`, но защищённый session-файл сохранил старый порт. В результате
historical Alembic получал `ConnectionTimeout`.

Реализуй согласованный вариант A из:

```text
docs/project/TASK_B-04A_VOLATILE_ENDPOINT_RECOVERY_DESIGN.md
docs/project/TASK_B-04A_VOLATILE_ENDPOINT_RECOVERY_IMPLEMENTATION_PLAN.md
```

## Разрешено

- менять только файлы, перечисленные в implementation plan;
- TDD-правки ignored operator helper и его pure tests;
- добавить bounded timeout в B-04 verifier и два изолированных Alembic context;
- атомарно обновлять только порт baseline/historical URL в защищённом session
  после полной проверки owned container;
- обновлять Task 7 report/ledger и закрывающий status только после реального
  успешного evidence-run;
- использовать свежего implementer и отдельного read-only reviewer на каждую
  самостоятельную задачу.

## Запрещено

- изменять migration 23 или любые frozen historical revisions;
- объявлять frozen historical chain offline-renderable;
- менять baseline candidate, fingerprint, seed manifest или source cut;
- наследовать application `.env`, `PATH`, `PYTHONPATH` либо полный process env в
  historical Alembic subprocess;
- выводить URL, пароль, ownership token или session content;
- принимать non-loopback/multiple Docker mappings;
- обновлять session из `RunEquivalenceEvidence`;
- автоматически retry destructive runner;
- затрагивать внешние/боевые БД;
- активировать B-04B;
- stage, commit, push, merge или cleanup без отдельного подтверждения владельца.

## Обязательный процесс

Для каждого Task:

1. прочитать точные требования implementation plan;
2. написать минимальный failing test;
3. показать ожидаемый RED;
4. реализовать минимальный GREEN;
5. запустить focused tests;
6. провести независимый read-only review;
7. исправить Critical/Important findings тем же implementer;
8. только затем переходить к следующему Task.

## Ключевые инварианты

- source of truth endpoint: актуальный mapping проверенного owned container;
- identity: полный ID + точное имя + точный ownership label;
- session refresh меняет только цифровой порт двух URL;
- token, ID, username, password, host и database names неизменны;
- session replacement same-directory, protected и atomic;
- `File.Replace` не игнорирует metadata/ACL errors; исходный DACL сохраняется
  самим Windows, post-replace `Set-Acl` запрещён;
- evidence preflight fail-closed проверяет mapping и TCP, но ничего не
  переписывает;
- Cleanup/Recover работают для остановленного контейнера и stale session;
- connect timeout: 10 секунд;
- Alembic subprocess timeout: 300 секунд;
- все B-04 env variables очищаются в `finally`.

## Проверки

Обязательно выполнить и сообщить точный вывод:

```powershell
& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest .superpowers/sdd/test_task_6_operator_helper.py -q

Set-Location 'D:\WeldPassport\.worktrees\b04-baseline\09_Разработка\backend'

& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest migration_contract_tests/test_b04_verify_runner.py `
  migration_contract_tests/test_b04_historical_context.py `
  migration_contract_tests/test_b04_candidate_context.py -q

& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m pytest migration_contract_tests -q

& 'D:\WeldPassport\.worktrees\project-control-center-mvp\09_Разработка\.venv\Scripts\python.exe' `
  -m compileall -q migrations/b04 migration_contract_tests

git diff --check
```

PowerShell helper также должен пройти parser check и `-ValidateSessionOnly`.

## Operator gate

Не запускай Docker/БД самостоятельно в subagent. После code review передай
владельцу команды:

1. `-StartOwnedContainer`;
2. sanitized mapping/session/TCP verification;
3. read-only DB state;
4. один `-RunEquivalenceEvidence`.

## Критерии приёмки

- stale session port автоматически reconciled в start mode;
- evidence mode отклоняет mismatch до Python/Alembic;
- endpoint failure ограничен timeout и имеет стабильный код;
- session secrets/identity сохранены;
- helper, focused и full contract tests проходят;
- независимый review: PASS;
- equivalence: `B04-EQUIVALENCE-EVIDENCE-OK`;
- опубликованы и проверены три accepted evidence-артефакта;
- нет commit/push/cleanup без отдельного подтверждения.
