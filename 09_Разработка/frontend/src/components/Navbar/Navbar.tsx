import logo from "../../assets/icons/logo.png";
import { ROLES, type RoleId, type RoleItem } from "./roles";
import "./Navbar.css";

export interface NavbarProps {
  /** Список разделов. По умолчанию — роли из макета (см. roles.ts). */
  roles?: RoleItem[];
  /** Активный раздел. `null` — ничего не выбрано (стартовый экран). */
  activeRole?: RoleId | null;
  /** Выбор раздела (глобальная навигация по модулям). */
  onRoleSelect?: (id: RoleId) => void;
  /** Клик по бренду — переход на главную. */
  onBrandClick?: () => void;
  /** Клик по кнопке «Войти». */
  onLogin?: () => void;
}

/**
 * Глобальная панель навигации WeldPassport.
 * Воспроизводит макет Navbar.dc.html: бренд слева, полоса разделов-ролей по
 * центру, кнопка «Войти» справа. Компонент управляемый — состояние активного
 * раздела хранит родитель (роутер), что готовит навбар к реальной навигации.
 */
export default function Navbar({
  roles = ROLES,
  activeRole = null,
  onRoleSelect,
  onBrandClick,
  onLogin,
}: NavbarProps) {
  return (
    <header className="wp-navbar">
      <button
        type="button"
        className="wp-brand"
        onClick={onBrandClick}
        aria-label="WeldPassport — на главную"
      >
        <img className="wp-brand__logo" src={logo} alt="WeldPassport" />
        <span className="wp-brand__title">WeldPassport</span>
      </button>

      <nav className="wp-roles-wrap" aria-label="Разделы системы">
        <div className="wp-roles">
          {roles.map((role) => {
            const active = role.id === activeRole;
            return (
              <button
                key={role.id}
                type="button"
                className={active ? "wp-role wp-role--active" : "wp-role"}
                title={role.sub}
                aria-pressed={active}
                onClick={() => onRoleSelect?.(role.id)}
              >
                <span className="wp-role__icon">
                  <img src={role.icon} alt={role.code} />
                </span>
                <span className="wp-role__code">{role.code}</span>
              </button>
            );
          })}
        </div>
      </nav>

      <button type="button" className="wp-login" onClick={onLogin}>
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path>
          <polyline points="10 17 15 12 10 7"></polyline>
          <line x1="15" y1="12" x2="3" y2="12"></line>
        </svg>
        <span>Войти</span>
      </button>
    </header>
  );
}
