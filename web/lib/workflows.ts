/**
 * Workflows (LEKA-397): several capabilities composed into one controlled
 * run — its steps in order, their conditions; runs followed step by step,
 * retried from where they failed, cancelled.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Workflow = components["schemas"]["WorkflowRead"];
export type WorkflowStep = components["schemas"]["WorkflowStepRead"];
export type WorkflowRun = components["schemas"]["WorkflowRunRead"];
export type WorkflowRunDetail = components["schemas"]["WorkflowRunDetail"];
export type WorkflowRunCreate = components["schemas"]["WorkflowRunCreate"];

/** Still on its way: followed until it ends. */
export const RUNNING: ReadonlySet<string> = new Set(["queued", "running"]);

export const workflows = {
  one: (key: string) => apiFetch<Workflow>(`/workflows/${encodeURIComponent(key)}`),
  runs: (key: string) =>
    apiFetch<WorkflowRun[]>(`/workflow-runs?key=${encodeURIComponent(key)}`),
  run: (id: string) => apiFetch<WorkflowRunDetail>(`/workflow-runs/${encodeURIComponent(id)}`),
  start: (body: WorkflowRunCreate) =>
    apiFetch<WorkflowRun>("/workflow-runs", { method: "POST", body: JSON.stringify(body) }),
  cancel: (id: string) =>
    apiFetch<WorkflowRun>(`/workflow-runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  retry: (id: string) =>
    apiFetch<WorkflowRun>(`/workflow-runs/${encodeURIComponent(id)}/retry`, { method: "POST" }),
};
