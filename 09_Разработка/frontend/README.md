# WeldPassport · Frontend

Минимальный фронтенд-каркас (React + TypeScript + Vite). Создан под реализацию
панели навигации из макета `Navbar.dc.html` (Claude Design).

## Запуск

```bash
cd 09_Разработка/frontend
npm install
npm run dev      # откроет http://localhost:5173
```

Сборка и проверка типов:

```bash
npm run build      # tsc + vite build
npm run typecheck  # только проверка типов
```

## Быстрое превью без сборки

Открыть `preview.html` двойным кликом в браузере — статичная копия навбара
(виден дизайн и hover-состояния, без интерактива React).

## Структура

```
src/
  main.tsx                     точка входа
  App.tsx                      демо-страница: навбар + контент по выбранному разделу
  index.css                    базовые стили
  assets/icons/                logo + 7 иконок ролей (из handoff-бандла)
  components/Navbar/
    Navbar.tsx                 компонент панели навигации
    Navbar.css                 стили навбара (пиксель-точно по макету)
    roles.ts                   данные разделов (id, подпись, иконка)
```

## Компонент Navbar

Глобальная навигация по разделам-ролям системы. Компонент управляемый —
состояние активного раздела хранит родитель (готов к подключению роутера).

```tsx
import Navbar from "./components/Navbar/Navbar";

<Navbar
  activeRole={activeRole}          // RoleId | null
  onRoleSelect={(id) => ...}        // выбор раздела
  onBrandClick={() => ...}          // клик по логотипу
  onLogin={() => ...}               // кнопка «Войти»
/>
```

Пропсы:

| Проп | Тип | Назначение |
|---|---|---|
| `roles` | `RoleItem[]` | Список разделов (по умолчанию — из `roles.ts`) |
| `activeRole` | `RoleId \| null` | Активный раздел |
| `onRoleSelect` | `(id: RoleId) => void` | Выбор раздела |
| `onBrandClick` | `() => void` | Клик по бренду |
| `onLogin` | `() => void` | Клик по «Войти» |

Разделы (макет): ОК, ПТО, Мастер / прораб, Сварщик, Главный сварщик,
Контроль качества, МТО / кладовщик.

## Раздел «ОК» — модуль отдела кадров

Клик по разделу **ОК** открывает реальный модуль отдела кадров (`desktop_ok/`)
внутри страницы — встроен как iframe ([OkModule.tsx](src/components/OkModule/OkModule.tsx)).
Это тот же интерфейс, что и десктоп-приложение на pywebview, но в браузере.

Данные обслуживает отдельный HTTP-сервер. Запустить из `09_Разработка`:

```powershell
python desktop_ok/server.py     # http://localhost:8077
```

Сервер (`desktop_ok/server.py`, FastAPI) переиспользует тот же класс `Api`, что
и десктоп; `web/app.js` не меняется — мост `window.pywebview.api` подменяет шим
`desktop_ok/web/_webshim.js` на fetch-вызовы. Адрес модуля можно переопределить
переменной окружения `VITE_OK_URL` (по умолчанию `http://localhost:8077`).
Нужен пакет `python-multipart` (загрузка файлов импорта).

Остальные разделы навбара — пока заглушки.

## История изменений

- v1 — первичная реализация навбара по `Navbar.dc.html`.
- v2 — раздел «ОК» открывает модуль `desktop_ok` (iframe + FastAPI-сервер).
