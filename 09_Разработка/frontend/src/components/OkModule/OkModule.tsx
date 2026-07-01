/**
 * Раздел «ОК» в веб-фронтенде. Встраивает существующий модуль отдела кадров
 * (desktop_ok/web) как iframe — тот же интерфейс, что и десктоп-приложение на
 * pywebview, но открытый внутри страницы вместо отдельного окна.
 *
 * Данные обслуживает отдельный HTTP-сервер desktop_ok/server.py (по умолчанию
 * http://localhost:8077). Адрес можно переопределить через VITE_OK_URL.
 * Сервер должен быть запущен: `python desktop_ok/server.py` из 09_Разработка.
 */
const OK_MODULE_URL =
  (import.meta.env.VITE_OK_URL as string | undefined) ?? "http://localhost:8077/";

export default function OkModule() {
  return (
    <iframe
      title="ОК · Персонал"
      src={OK_MODULE_URL}
      style={{ width: "100%", height: "100%", border: 0, display: "block" }}
    />
  );
}
