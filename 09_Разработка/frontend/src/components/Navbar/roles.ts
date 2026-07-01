import hr from "../../assets/icons/hr.png";
import pto from "../../assets/icons/pto.png";
import master from "../../assets/icons/master.png";
import welder from "../../assets/icons/welder.png";
import chief from "../../assets/icons/chief.png";
import qc from "../../assets/icons/qc.png";
import mto from "../../assets/icons/mto.png";

/** Идентификатор раздела (роли-модуля) глобальной навигации. */
export type RoleId =
  | "hr"
  | "pto"
  | "master"
  | "welder"
  | "chief"
  | "qc"
  | "mto";

export interface RoleItem {
  /** Стабильный идентификатор раздела — для роутинга и проверки прав. */
  id: RoleId;
  /** Видимая подпись в навбаре. */
  code: string;
  /** Пояснение (показывается как tooltip). */
  sub: string;
  /** Иконка раздела. */
  icon: string;
}

/**
 * Разделы верхнего уровня системы. Порядок и подписи — из макета Navbar.dc.html.
 * Каждый раздел соответствует роли/рабочему месту в жизненном цикле сварочного
 * производства (см. AGENTS.md §5).
 */
export const ROLES: RoleItem[] = [
  { id: "hr", code: "ОК", sub: "Отдел кадров", icon: hr },
  { id: "pto", code: "ПТО", sub: "Отдел подготовки производства", icon: pto },
  { id: "master", code: "Мастер / прораб", sub: "Производственный персонал", icon: master },
  { id: "welder", code: "Сварщик", sub: "Исполнитель", icon: welder },
  { id: "chief", code: "Главный сварщик", sub: "ОГС", icon: chief },
  { id: "qc", code: "Контроль качества", sub: "ОТК / НК", icon: qc },
  { id: "mto", code: "МТО / кладовщик", sub: "Материалы", icon: mto },
];
