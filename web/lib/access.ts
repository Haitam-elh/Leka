/**
 * Who may do what (LEKA-402): every role's permissions, the entities an
 * admin restricted, and the trail of access decisions.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type AccessModel = components["schemas"]["AccessModelRead"];
export type Restriction = components["schemas"]["RestrictionRead"];
export type AccessDecision = components["schemas"]["AccessDecisionRead"];
export type EntityHit = components["schemas"]["SearchHit"];

export const access = {
  model: () => apiFetch<AccessModel>("/governance/access"),
  restrictions: () => apiFetch<Restriction[]>("/governance/restrictions"),
  restrict: (entityId: string, reason: string) =>
    apiFetch<Restriction>(`/governance/restrictions/${encodeURIComponent(entityId)}`, {
      method: "PUT",
      body: JSON.stringify({ reason }),
    }),
  lift: (entityId: string) =>
    apiFetch<void>(`/governance/restrictions/${encodeURIComponent(entityId)}`, {
      method: "DELETE",
    }),
  decisions: (decision: "allow" | "deny" | null) =>
    apiFetch<AccessDecision[]>(`/governance/decisions${decision ? `?decision=${decision}` : ""}`),
  search: (q: string) =>
    apiFetch<{ entities: EntityHit[] }>(`/knowledge/search?q=${encodeURIComponent(q)}`),
};
