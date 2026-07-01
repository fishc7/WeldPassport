import { useState } from "react";
import Navbar from "./components/Navbar/Navbar";
import OkModule from "./components/OkModule/OkModule";
import { ROLES, type RoleId } from "./components/Navbar/roles";

/**
 * Демонстрационная страница: навбар + область контента, реагирующая на выбор
 * раздела. Раздел «ОК» открывает реальный модуль отдела кадров (desktop_ok)
 * внутри страницы; остальные разделы пока — заглушки.
 *
 * activeRole/onRoleSelect вынесены на уровень приложения — это готовит навбар
 * к подключению роутера.
 */
export default function App() {
  const [activeRole, setActiveRole] = useState<RoleId | null>(null);
  const current = ROLES.find((r) => r.id === activeRole) ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <Navbar
        activeRole={activeRole}
        onRoleSelect={setActiveRole}
        onBrandClick={() => setActiveRole(null)}
        onLogin={() => alert("Экран входа — заглушка")}
      />

      <main style={{ flex: 1, minHeight: 0 }}>
        {activeRole === "hr" ? (
          // Реальный модуль ОК (отдел кадров) — встроен из desktop_ok.
          <OkModule />
        ) : current ? (
          <div style={{ padding: "40px 24px", color: "#1f3a5f" }}>
            <h1 style={{ margin: 0, fontSize: 22 }}>{current.code}</h1>
            <p style={{ color: "#6b7280" }}>{current.sub}</p>
            <p>Раздел «{current.code}» — заглушка. Здесь будет рабочее место.</p>
          </div>
        ) : (
          <div style={{ padding: "40px 24px", color: "#6b7280" }}>
            Выберите раздел в панели навигации.
          </div>
        )}
      </main>
    </div>
  );
}
