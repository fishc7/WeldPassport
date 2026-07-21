# Implementation Decisions — индекс

> Уровень 5 Architecture Governance Framework (AGF) —
> [[docs/project/ARCHITECTURE_GOVERNANCE#Уровень 5 — Task / Implementation Specification|AGF, уровень 5]] ·
> различие ADR / Implementation Decision — [[docs/project/ARCHITECTURE_GOVERNANCE#3. Различие ADR и Implementation Decision|AGF §3]].

## Что это

**Implementation Decision** — техническое решение, принятое **внутри уже утверждённого
Task**, которое не меняет архитектуру (домен, границы модулей, жизненный цикл сущностей,
каноническую иерархию). Отвечает на вопрос «как это устроено технически», а не «что
появляется в домене».

Implementation Decision **не является ADR**: он не проходит через Architecture Session и
не создаёт новую центральную сущность. Каждый новый Implementation Decision обязан
ссылаться на Task и его архитектурное основание — ADR, явно указанное решение Architecture
Session либо канонический раздел архитектуры, допустимый по переходному правилу AGF. Если
есть Task Implementation Spec, ссылка на него также обязательна.

Если в процессе реализации обнаруживается, что решение фактически меняет домен, границы
или жизненный цикл — оформление как Implementation Decision **запрещено**; решение
поднимается на уровень Architecture Session (см. AGF §6 «Критерии фундаментального
решения»).

## Формат файла

Имя файла: `<Task-код>-<короткое-название-в-kebab-case>.md`, например
`9D-4A-4-disposition-supersede-workflow.md`.

Обязательные разделы внутри файла:

1. Заголовок — `# Task <код> — <название> Implementation Decision`.
2. Дата, статус (`ACCEPTED` / `SUPERSEDED` и т.д.).
3. Контур (домен/модуль).
4. Стабильный текстовый Task ID и ссылка на [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]]
   (ссылка на табличный anchor не требуется), архитектурное основание и, при наличии,
   Task / Implementation Specification.
5. Само решение (кратко, по возможности в виде декларативных предложений — по прецеденту
   ниже).
6. Границы / что не входит.
7. Где зафиксировано (файлы кода, миграций, тестов).
8. Для перенесённого исторического решения — раздел `История и происхождение решения` с
   первоначальным местом фиксации, подтверждёнными commit решения и реализации, датой
   переноса и явным указанием, существовал ли отдельный файл в первоначальном commit.

## Реестр

| Task | Файл | Дата | Статус | Детализирует |
|---|---|---|---|---|
| `9D-4A-3` | [[docs/project/implementation-decisions/9D-4A-3-disposition-approve-activate-roles|9D-4A-3-disposition-approve-activate-roles.md]] | 2026-07-21 | ACTIVE — implementation pending alignment with ADR-024 | [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model\|ADR-024 (ACCEPTED)]] |
| `9D-4A-4` | [[docs/project/implementation-decisions/9D-4A-4-disposition-supersede-workflow|9D-4A-4-disposition-supersede-workflow.md]] | 2026-07-21 | ACTIVE — implementation pending alignment with ADR-024 | [[docs/project/ADR-024-defect-disposition-lifecycle-authority-model\|ADR-024 (ACCEPTED)]] |

## Архитектурный прецедент вне каталога

До формализации этого каталога (2026-07-21) supersede timing для `Defect` был оформлен как
отдельный **ADR Addendum**, а не как Implementation Decision:
[[docs/project/ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING|ADR-022-ADDENDUM-DEFECT-SUPERSEDE-TIMING.md]]
(`Task 9D-3B`, timing команды `supersede` для `Defect`). Поскольку timing меняет
версионный lifecycle, файл является архитектурным основанием уровня ADR и сохраняется на
месте. Технические детали его реализации могут оформляться в этом каталоге, но сам
lifecycle — только в Architecture Session/ADR.

## Правило ведения

### Новые решения после введения уровня Implementation Decisions

1. Implementation Decision создаётся **до реализации либо одновременно с первым коммитом
   реализации** соответствующей части Task. Создание задним числом после завершения Task
   не допускается.
2. Решение обязательно содержит стабильный Task ID, ссылку на `TASK_REGISTRY.md`,
   архитектурное основание и, при наличии, Task Implementation Spec. Архитектурным
   основанием может быть ADR, явно указанное решение Architecture Session либо
   канонический раздел архитектуры, допустимый AGF; отдельный ADR не требуется для
   локального технического решения. Для lifecycle, RBAC, separation of duties, override
   и фундаментальных инвариантов отдельный ADR обязателен.
3. `docs/project/DECISIONS.md` не содержит полного текста Implementation Decision — только
   краткую ссылку/редирект на файл в этом каталоге (см. пример в `DECISIONS.md` на местах
   редиректы Task 9D-4A-3/4 в `DECISIONS.md`).
4. Актуальный статус реализации Task — в [[docs/project/TASK_REGISTRY|TASK_REGISTRY.md]],
   а не в тексте Implementation Decision (текст не переписывается задним числом).

### Перенос исторических решений

До введения отдельного каталога техническое решение могло быть зафиксировано полным текстом
в `docs/project/DECISIONS.md` или другом каноническом документе. Такой текст допускается
перенести в отдельный файл **без переписывания Git-истории**, если перенос не изменяет само
решение.

Исторический файл обязан явно указывать:

- первоначальное место фиксации решения;
- commit первоначального появления текста либо `NOT VERIFIED` с объяснением;
- commit реализации либо `NOT VERIFIED` с объяснением;
- дату переноса в каталог;
- что отдельного файла не существовало в первоначальном implementation commit, если это
  подтверждается Git.
