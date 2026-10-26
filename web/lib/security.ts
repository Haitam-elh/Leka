/**
 * What an organisation runs its own (2026-10-25): its people's devices,
 * who may reach its sources, how much its agents ran and who ran which.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type DeviceSession = components["schemas"]["SessionRead"];
export type AgentUsage = components["schemas"]["AgentUsageRead"];
export type AgentJournalEntry = components["schemas"]["AgentJournalRead"];

export const security = {
  /** My signed-in devices. */
  sessions: () => apiFetch<{ data: DeviceSession[] }>("/auth/sessions?limit=100"),
  /** One of them signed out. */
  signOut: (id: string) =>
    apiFetch<void>(`/auth/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** A source's credentials erased: LEKA no longer reaches it, its data kept. */
  revoke: (sourceId: string) =>
    apiFetch<components["schemas"]["SourceRead"]>(`/sources/${encodeURIComponent(sourceId)}/revoke`, {
      method: "POST",
    }),
  /** Each agent's runs over the last `days` — counted, never priced. */
  usage: (days: number) => apiFetch<AgentUsage[]>(`/agent-runs/usage?days=${days}`),
  /** Who ran which agent, the latest first — older than `before` when given. */
  journal: (before?: string) =>
    apiFetch<AgentJournalEntry[]>(
      `/agent-runs/journal?limit=50${before ? `&before=${encodeURIComponent(before)}` : ""}`,
    ),
};
