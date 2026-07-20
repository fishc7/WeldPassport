# ADR-022 Addendum — D-3B-S01 · Defect Supersede Timing Model

Канон: [[DECISIONS#ADR-022. Defect Technical Model (Task 9D-3)|ADR-022]] ·
Implementation Spec: [[TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC|TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC]] ·
план [[IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP|IMPLEMENTATION_PLAN]] (строка 9D-3).

**Status:** `Accepted`
**Date:** `2026-07-20`
**Addendum ID:** `D-3B-S01`

Этот аддендум **уточняет момент исполнения** (timing) команды `supersede` технической модели `Defect`
и является авторитетным источником по этому вопросу. ADR-022 не переписывается: аддендум фиксирует
принятую **supersede-time** модель, реализованную в Task 9D-3B (`app/quality/defect_services.py`,
`app/quality/defect_workflow.py`). Ранние формулировки, описывавшие «замещение при активации»
(activate-time), заменяются настоящим аддендумом.

---

## Decision

Task 9D-3 использует **supersede-time** модель.

Жизненный цикл ревизии дефекта:

```text
DRAFT
 |
 | activate
 v
ACTIVE
 |
 | supersede
 v
SUPERSEDED

+

DRAFT (new revision)
 |
 | activate
 v
ACTIVE
```

Команда `supersede` в одной атомарной транзакции переводит действующую `ACTIVE`-ревизию в
`SUPERSEDED` **и** создаёт новую ревизию как `DRAFT`. Приёмка новой действующей версии
(`DRAFT → ACTIVE`) выполняется **отдельной** доменной командой `activate`.

---

## Rationale

1. `SUPERSEDED` означает **факт замены технической версии**, а не устранение дефекта.
2. После `supersede` старая версия **больше не является действующей** (`ACTIVE` в цепочке нет).
3. Новая версия создаётся как **`DRAFT`** (может быть неполной; полная проверка — при активации).
4. **Активация новой версии — отдельная доменная операция** (`activate`), не побочный эффект supersede.
5. Модель явно **разделяет**:
   * изменение технических данных (создание новой `DRAFT`-ревизии через supersede);
   * принятие новой действующей версии (`activate`).

---

## Domain rules

### Supersede

Создаёт новую ревизию:

```text
new UUID
same defect_root
revision_no + 1
status = DRAFT
supersedes_defect_id = previous.id
```

Переводит предыдущую ревизию:

```text
ACTIVE → SUPERSEDED
```

Создаёт события:

```text
DEFECT_SUPERSEDED        (предыдущая: from ACTIVE → to SUPERSEDED)
DEFECT_REVISION_CREATED  (новая: from NULL → to DRAFT)
```

Не создаёт:

```text
DEFECT_ACTIVATED
```

### Activate

Отдельная операция:

```text
DRAFT → ACTIVE
```

Создаёт:

```text
DEFECT_ACTIVATED         (новая: from DRAFT → to ACTIVE)
```

---

## Valid intermediate state

После `supersede` и до `activate` допустимо и корректно состояние цепочки:

```text
SUPERSEDED + DRAFT
```

Отсутствие `ACTIVE`-ревизии внутри `defect_root` в этот момент является **корректным** состоянием
(0 `ACTIVE`, ровно 1 открытая `DRAFT`). Инвариант «не более одной `ACTIVE` и не более одной открытой
`DRAFT` в цепочке» (ADR-022 §14 п.7; Spec D04) сохраняется.

---

## Где зафиксировано

```text
docs/project/ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING.md (настоящий аддендум D-3B-S01)
docs/project/DECISIONS.md (ADR-022 §7 — ссылка на аддендум)
docs/project/TASK_9D-3_DEFECT_TECHNICAL_MODEL_SPEC.md (§5, §7.5, §9, D05 — supersede-time)
docs/project/IMPLEMENTATION_PLAN_ENGINEERING_JOINTS_MVP.md (Task 9D-3 — supersede model)
```
