import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import App, { type Dashboard } from "./App";

const dashboard: Dashboard = {
  overall_percent: "58.00",
  generated_at: "2026-07-19T08:00:00Z",
  data_status: "DEMO",
  modules: [
    {
      code: "hr",
      name: "Приём и допуск",
      stage: 1,
      technical_percent: "100.00",
      metrics_complete: true,
      management_status: "READY",
      next_action: "Поддерживать данные",
    },
    {
      code: "engineering",
      name: "Engineering",
      stage: 3,
      technical_percent: "74.00",
      metrics_complete: true,
      management_status: "DECISION_REQUIRED",
      next_action: "Завершить Engineering Evaluation",
    },
  ],
};

test("shows lifecycle modules and opens selected module details", async () => {
  render(<App loadDashboard={async () => dashboard} />);

  expect(
    await screen.findByRole("button", { name: /Приём и допуск/ }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Engineering/ }));

  expect(screen.getAllByText("Завершить Engineering Evaluation")).toHaveLength(2);
  expect(screen.getAllByText("Требуется решение").length).toBeGreaterThan(0);
  expect(screen.getByText("Демонстрационные данные")).toBeInTheDocument();
  expect(screen.queryByText("12 / 16")).not.toBeInTheDocument();
});

test("keeps the dashboard usable when backend is unavailable", async () => {
  render(<App loadDashboard={async () => Promise.reject(new Error("offline"))} />);

  expect(await screen.findByText(/Не удалось получить свежие данные/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Повторить/ })).toBeInTheDocument();
});

test("keeps the previous calculation and marks it stale after refresh failure", async () => {
  const loadDashboard = vi
    .fn()
    .mockResolvedValueOnce(dashboard)
    .mockRejectedValueOnce(new Error("offline"));
  render(<App loadDashboard={loadDashboard} />);

  await screen.findByText("Демонстрационные данные");
  fireEvent.click(screen.getByRole("button", { name: "Обновить данные" }));

  expect(
    await screen.findByText("Не удалось обновить данные — показан предыдущий расчёт"),
  ).toBeInTheDocument();
  expect(screen.getByText("Карта готовности WeldPassport")).toBeInTheDocument();
});

test("owner records a new management assessment from module card", async () => {
  const saveAssessment = vi.fn().mockResolvedValue(undefined);
  render(
    <App
      loadDashboard={async () => dashboard}
      saveAssessment={saveAssessment}
    />,
  );

  await screen.findByRole("button", { name: /Приём и допуск/ });
  fireEvent.click(screen.getByRole("button", { name: "Обновить оценку" }));
  fireEvent.change(screen.getByLabelText("Статус"), {
    target: { value: "READY_WITH_LIMITATIONS" },
  });
  fireEvent.change(screen.getByLabelText("Обоснование"), {
    target: { value: "Нужна итоговая проверка документов" },
  });
  fireEvent.change(screen.getByLabelText("Автор"), {
    target: { value: "Андрей" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить оценку" }));

  await waitFor(() =>
    expect(saveAssessment).toHaveBeenCalledWith("hr", {
      status: "READY_WITH_LIMITATIONS",
      reason: "Нужна итоговая проверка документов",
      author: "Андрей",
    }),
  );
  expect(screen.getAllByText("Готово с ограничениями").length).toBeGreaterThan(0);
});
