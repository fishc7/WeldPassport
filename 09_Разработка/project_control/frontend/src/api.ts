import type { AssessmentInput, Dashboard } from "./App";

export async function fetchDashboard(): Promise<Dashboard> {
  const response = await fetch("/api/v1/dashboard");
  if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
  return response.json() as Promise<Dashboard>;
}

export async function postAssessment(
  moduleCode: string,
  assessment: AssessmentInput,
): Promise<void> {
  const response = await fetch(`/api/v1/modules/${moduleCode}/assessments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(assessment),
  });
  if (!response.ok) throw new Error(`Assessment request failed: ${response.status}`);
}
