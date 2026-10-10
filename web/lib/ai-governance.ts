/**
 * The workspace's AI, governed (LEKA-406): its controls — which models,
 * how much, what an answer may not carry, which agents wait for approval —
 * and what each did.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type AIControl = components["schemas"]["AIControlRead"];
export type AIControlUpdate = components["schemas"]["AIControlUpdate"];
export type AIControlEvent = components["schemas"]["AIControlEventRead"];
export type AIControlKind = AIControlUpdate["kind"];

export const AI_KINDS: readonly AIControlKind[] = [
  "model_access",
  "usage_limit",
  "output_check",
  "approval",
];

export const aiGovernance = {
  controls: () => apiFetch<AIControl[]>("/governance/ai/controls"),
  create: (body: AIControlUpdate) =>
    apiFetch<AIControl>("/governance/ai/controls", { method: "POST", body: JSON.stringify(body) }),
  update: (id: string, body: AIControlUpdate) =>
    apiFetch<AIControl>(`/governance/ai/controls/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    apiFetch<void>(`/governance/ai/controls/${encodeURIComponent(id)}`, { method: "DELETE" }),
  events: () => apiFetch<AIControlEvent[]>("/governance/ai/events?limit=50"),
};

/** The control as it is, to be sent back changed. */
export function updateOf(c: AIControl): AIControlUpdate {
  return {
    name: c.name,
    description: c.description,
    kind: c.kind,
    purposes: c.purposes,
    roles: c.roles,
    enabled: c.enabled,
    providers: c.providers,
    owners: c.owners,
    block: c.block,
    period: c.period,
    per: c.per,
    max_calls: c.max_calls,
    max_tokens: c.max_tokens,
    max_cost_usd: c.max_cost_usd,
    detect: c.detect,
    on_finding: c.on_finding,
    risk_at_least: c.risk_at_least,
  };
}
