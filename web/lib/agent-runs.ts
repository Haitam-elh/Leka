/**
 * Agents, run (LEKA-395): one run with what its contract takes, followed —
 * queued, running, done, failed and why, cancelled — what it delivered and
 * every step it took, what its model calls cost.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type AgentRun = components["schemas"]["AgentRunRead"];
export type AgentRunDetail = components["schemas"]["AgentRunDetail"];
export type AgentRunEvent = components["schemas"]["AgentRunEventRead"];
export type AgentRunCreate = components["schemas"]["AgentRunCreate"];
export type RunInputs = AgentRunCreate["inputs"];

/** Still on its way: followed until it ends. */
export const ACTIVE: ReadonlySet<string> = new Set(["queued", "running"]);

export const agentRuns = {
  list: (key?: string) =>
    apiFetch<AgentRun[]>(`/agent-runs${key ? `?key=${encodeURIComponent(key)}` : ""}`),
  one: (id: string) => apiFetch<AgentRunDetail>(`/agent-runs/${encodeURIComponent(id)}`),
  start: (body: AgentRunCreate) =>
    apiFetch<AgentRun>("/agent-runs", { method: "POST", body: JSON.stringify(body) }),
  cancel: (id: string) =>
    apiFetch<AgentRun>(`/agent-runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
};
