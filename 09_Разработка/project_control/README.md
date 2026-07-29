# WeldPassport Project Control Center

Отдельная служебная web-панель для владельца проекта и разработчиков. Код расположен
в `09_Разработка/project_control/` и не подключается к производственным таблицам
WeldPassport.

## Возможности текущего рабочего среза

- интерактивная карта семи этапов жизненного цикла;
- прозрачный расчёт технической готовности;
- отдельный управленческий статус владельца;
- создание версий оценки через API и интерфейс;
- сбор состояния локального Git;
- read-only клиент GitHub для ветки, PR и последнего CI;
- модели и Alembic-миграция PostgreSQL в схеме `project_control`;
- сохранение последнего снимка интерфейсом при ошибке обновления.

По умолчанию backend запускается в демонстрационном режиме с данными в памяти.
`SqlAlchemyAssessmentRepository` и миграция предназначены для подключения PostgreSQL;
перед промышленным запуском необходимо передать repository в `DashboardService` и
настроить `PROJECT_CONTROL_DATABASE_URL`.

## Запуск backend

```powershell
cd 09_Разработка\project_control\backend
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010
```

Документация API: `http://127.0.0.1:8010/docs`.

## Запуск frontend

```powershell
cd 09_Разработка\project_control\frontend
npm install
npm run dev
```

Панель: `http://127.0.0.1:5174`.

## Проверки

```powershell
cd backend
..\..\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm test
npm run build
```
