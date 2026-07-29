import { type FormEvent, useEffect, useMemo, useState } from "react";

import { fetchDashboard, postAssessment } from "./api";

export type ManagementStatus =
  | "READY"
  | "READY_WITH_LIMITATIONS"
  | "DECISION_REQUIRED"
  | "BLOCKED"
  | "NOT_CONFIRMED";

export interface ProjectModule {
  code: string;
  name: string;
  stage: number;
  technical_percent: string;
  metrics_complete: boolean;
  management_status: ManagementStatus;
  next_action: string;
}

export interface Dashboard {
  overall_percent: string;
  generated_at: string;
  data_status: "DEMO" | "LIVE" | "STALE";
  modules: ProjectModule[];
}

export interface AssessmentInput {
  status: ManagementStatus;
  reason: string;
  author: string;
}

interface Props {
  loadDashboard?: () => Promise<Dashboard>;
  saveAssessment?: (moduleCode: string, input: AssessmentInput) => Promise<void>;
}

const statusLabels: Record<ManagementStatus, string> = {
  READY: "Готово",
  READY_WITH_LIMITATIONS: "Готово с ограничениями",
  DECISION_REQUIRED: "Требуется решение",
  BLOCKED: "Заблокировано",
  NOT_CONFIRMED: "Не подтверждено",
};

function tone(module: ProjectModule): string {
  if (module.management_status === "BLOCKED") return "danger";
  if (module.management_status === "DECISION_REQUIRED") return "warning";
  if (Number(module.technical_percent) >= 90) return "success";
  if (Number(module.technical_percent) >= 50) return "active";
  return "planned";
}

export default function App({
  loadDashboard = fetchDashboard,
  saveAssessment = postAssessment,
}: Props) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [assessmentOpen, setAssessmentOpen] = useState(false);
  const [assessmentError, setAssessmentError] = useState(false);
  const [assessment, setAssessment] = useState<AssessmentInput>({
    status: "NOT_CONFIRMED",
    reason: "",
    author: "",
  });

  useEffect(() => {
    let cancelled = false;
    setError(false);
    loadDashboard()
      .then((data) => {
        if (cancelled) return;
        setDashboard(data);
        setSelectedCode((current) => current ?? data.modules[0]?.code ?? null);
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [loadDashboard, refreshKey]);

  const selected = useMemo(
    () => dashboard?.modules.find((module) => module.code === selectedCode) ?? null,
    [dashboard, selectedCode],
  );

  if (error && !dashboard) {
    return (
      <main className="state-page">
        <div className="state-card">
          <div className="state-icon">!</div>
          <h1>Не удалось получить свежие данные</h1>
          <p>Backend недоступен. Последние данные не были заменены нулевыми значениями.</p>
          <button onClick={() => setRefreshKey((value) => value + 1)}>Повторить</button>
        </div>
      </main>
    );
  }

  if (!dashboard || !selected) {
    return <main className="state-page"><div className="loader" aria-label="Загрузка" /></main>;
  }

  const updated = new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "short",
  }).format(new Date(dashboard.generated_at));
  const selectedModuleCode = selected.code;

  async function submitAssessment(event: FormEvent) {
    event.preventDefault();
    setAssessmentError(false);
    try {
      await saveAssessment(selectedModuleCode, assessment);
      setDashboard((current) => current && ({
        ...current,
        modules: current.modules.map((module) =>
          module.code === selectedModuleCode
            ? { ...module, management_status: assessment.status }
            : module,
        ),
      }));
      setAssessmentOpen(false);
    } catch {
      setAssessmentError(true);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><span>W</span></div>
        <div className="brand-copy">
          <strong>WeldPassport</strong>
          <small>Project Control Center</small>
        </div>
        <nav>
          <button className="nav-active">Карта системы</button>
          <button>Задачи</button>
          <button>Риски</button>
          <button>История</button>
        </nav>
        <button
          type="button"
          className="sync-pill"
          aria-label="Обновить данные"
          onClick={() => setRefreshKey((value) => value + 1)}
        ><i /> Рассчитано: {updated}</button>
        <div className="avatar">А</div>
      </header>

      <main className="workspace">
        {dashboard.data_status === "DEMO" && (
          <div className="data-banner demo">Демонстрационные данные</div>
        )}
        {(error || dashboard.data_status === "STALE") && (
          <div className="data-banner stale">Не удалось обновить данные — показан предыдущий расчёт</div>
        )}
        <section className="hero-row">
          <div>
            <p className="eyebrow">ЦЕНТР УПРАВЛЕНИЯ РЕАЛИЗАЦИЕЙ</p>
            <h1>Карта готовности WeldPassport</h1>
            <p className="hero-subtitle">От приёма сварщика до закрытия истории стыка</p>
          </div>
          <div className="overall-card">
            <div className="ring" style={{ "--progress": `${dashboard.overall_percent}%` } as React.CSSProperties}>
              <span>{Math.round(Number(dashboard.overall_percent))}%</span>
            </div>
            <div><small>Общая техническая готовность</small><strong>Расчёт по доступным метрикам</strong></div>
          </div>
        </section>

        <section className="lifecycle-card">
          <div className="section-heading">
            <div><span>ЖИЗНЕННЫЙ ЦИКЛ</span><h2>Состояние ключевых контуров</h2></div>
            <p>Выберите этап для подробностей</p>
          </div>
          <div className="lifecycle-track">
            {dashboard.modules.map((module, index) => (
              <div className="stage-wrap" key={module.code}>
                <button
                  className={`stage-card ${tone(module)} ${selected.code === module.code ? "selected" : ""}`}
                  aria-label={`${module.name}, ${module.technical_percent}%`}
                  onClick={() => setSelectedCode(module.code)}
                >
                  <span className="stage-number">{String(module.stage).padStart(2, "0")}</span>
                  <strong>{module.name}</strong>
                  <div className="stage-percent">{Math.round(Number(module.technical_percent))}<small>%</small></div>
                  <div className="mini-progress"><i style={{ width: `${module.technical_percent}%` }} /></div>
                  <span className="stage-status">{statusLabels[module.management_status]}</span>
                </button>
                {index < dashboard.modules.length - 1 && <span className="connector">›</span>}
              </div>
            ))}
          </div>
        </section>

        <section className="content-grid">
          <article className="detail-card">
            <div className="detail-header">
              <div>
                <span className="module-code">МОДУЛЬ {String(selected.stage).padStart(2, "0")}</span>
                <h2>{selected.name}</h2>
              </div>
              <div className="detail-actions">
                <span className={`status-badge ${tone(selected)}`}>{statusLabels[selected.management_status]}</span>
                <button
                  className="assessment-button"
                  onClick={() => {
                    setAssessment({ status: selected.management_status, reason: "", author: "" });
                    setAssessmentError(false);
                    setAssessmentOpen(true);
                  }}
                >Обновить оценку</button>
              </div>
            </div>

            <div className="metric-grid">
              <Metric label="Техническая готовность" value={`${Math.round(Number(selected.technical_percent))}%`} accent="blue" />
              <Metric label="Источник" value="Демо-каталог" accent="green" />
              <Metric label="Детализация" value="Не подключена" accent="violet" />
              <Metric label="Тип расчёта" value="По запросу" accent="amber" />
            </div>

            <div className="detail-columns">
              <div>
                <h3>Следующее действие</h3>
                <div className="action-item"><span className="action-dot" /><div><strong>{selected.next_action}</strong><small>Приоритетный шаг выбран для текущего модуля</small></div></div>
              </div>
              <div>
                <h3>Состояние данных</h3>
                <div className="data-quality"><span>Набор метрик</span><strong>{selected.metrics_complete ? "Заполнен" : "Есть пропуски"}</strong></div>
                <div className="data-quality"><span>Оценка владельца</span><strong>{statusLabels[selected.management_status]}</strong></div>
              </div>
            </div>
          </article>

          <aside className="sidebar">
            <div className="focus-card">
              <span>СЛЕДУЮЩИЙ ПРАКТИЧЕСКИЙ ШАГ</span>
              <h3>{selected.next_action}</h3>
              <p>Модуль: {selected.name}</p>
              <button>Открыть карточку <b>→</b></button>
            </div>
            <div className="signal-card">
              <div className="signal-heading"><h3>Риски и задачи</h3></div>
              <p className="empty-signal">Источники рисков и задач ещё не подключены.</p>
            </div>
          </aside>
        </section>
      </main>
      {assessmentOpen && (
        <div className="modal-backdrop" role="presentation">
          <form className="assessment-modal" onSubmit={submitAssessment}>
            <div className="modal-heading">
              <div><span>УПРАВЛЕНЧЕСКАЯ ОЦЕНКА</span><h2>{selected.name}</h2></div>
              <button type="button" aria-label="Закрыть" onClick={() => setAssessmentOpen(false)}>×</button>
            </div>
            <label>Статус
              <select
                value={assessment.status}
                onChange={(event) => setAssessment({ ...assessment, status: event.target.value as ManagementStatus })}
              >
                {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>Обоснование
              <textarea
                required
                minLength={3}
                value={assessment.reason}
                onChange={(event) => setAssessment({ ...assessment, reason: event.target.value })}
              />
            </label>
            <label>Автор
              <input
                required
                minLength={2}
                value={assessment.author}
                onChange={(event) => setAssessment({ ...assessment, author: event.target.value })}
              />
            </label>
            {assessmentError && <p className="form-error">Не удалось сохранить оценку. Проверьте доступность backend и повторите попытку.</p>}
            <div className="modal-actions">
              <button type="button" onClick={() => setAssessmentOpen(false)}>Отмена</button>
              <button type="submit">Сохранить оценку</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent: string }) {
  return <div className={`metric ${accent}`}><span>{label}</span><strong>{value}</strong></div>;
}
