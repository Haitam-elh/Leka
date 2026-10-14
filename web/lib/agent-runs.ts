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

/** Still on its way — waiting for approval included (LEKA-406): it may
 * still be cancelled. */
export const ACTIVE: ReadonlySet<string> = new Set(["awaiting_approval", "queued", "running"]);

/** Moving on its own: followed closely. One waiting for approval waits for
 * a person — hours, maybe — and is read again when the page is. */
export const MOVING: ReadonlySet<string> = new Set(["queued", "running"]);

export const agentRuns = {
  list: (key?: string) =>
    apiFetch<AgentRun[]>(`/agent-runs${key ? `?key=${encodeURIComponent(key)}` : ""}`),
  /** The agents at work on an intention — launched for it at its decision. */
  forIntention: (intentionId: string) =>
    apiFetch<AgentRun[]>(`/agent-runs?intention_id=${encodeURIComponent(intentionId)}`),
  one: (id: string) => apiFetch<AgentRunDetail>(`/agent-runs/${encodeURIComponent(id)}`),
  start: (body: AgentRunCreate) =>
    apiFetch<AgentRun>("/agent-runs", { method: "POST", body: JSON.stringify(body) }),
  cancel: (id: string) =>
    apiFetch<AgentRun>(`/agent-runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  /** Waiting for approval (LEKA-406): the runs to decide. */
  awaiting: () => apiFetch<AgentRun[]>("/agent-runs?status=awaiting_approval"),
  decide: (id: string, approve: boolean, note?: string) =>
    apiFetch<AgentRun>(`/agent-runs/${encodeURIComponent(id)}/${approve ? "approve" : "reject"}`, {
      method: "POST",
      body: JSON.stringify(note ? { note } : {}),
    }),
};
