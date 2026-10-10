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
export type CustomRole = components["schemas"]["RoleRead"];
export type RoleUpdate = components["schemas"]["RoleUpdate"];
export type Assignment = components["schemas"]["AssignmentRead"];
export type Policy = components["schemas"]["PolicyRead"];
export type PolicyUpdate = components["schemas"]["PolicyUpdate"];
export type GovernanceEvent = components["schemas"]["GovernanceEventRead"];

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
  roles: () => apiFetch<CustomRole[]>("/governance/roles"),
  saveRole: (key: string, body: RoleUpdate) =>
    apiFetch<CustomRole>(`/governance/roles/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteRole: (key: string) =>
    apiFetch<void>(`/governance/roles/${encodeURIComponent(key)}`, { method: "DELETE" }),
  assignments: () => apiFetch<Assignment[]>("/governance/assignments"),
  assign: (userId: string, role: string | null) =>
    apiFetch<unknown>(`/governance/assignments/${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: JSON.stringify({ role }),
    }),
  policies: () => apiFetch<Policy[]>("/governance/policies"),
  createPolicy: (body: PolicyUpdate) =>
    apiFetch<Policy>("/governance/policies", { method: "POST", body: JSON.stringify(body) }),
  updatePolicy: (id: string, body: PolicyUpdate) =>
    apiFetch<Policy>(`/governance/policies/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deletePolicy: (id: string) =>
    apiFetch<void>(`/governance/policies/${encodeURIComponent(id)}`, { method: "DELETE" }),
  history: () => apiFetch<GovernanceEvent[]>("/governance/history"),
  search: (q: string) =>
    apiFetch<{ entities: EntityHit[] }>(`/knowledge/search?q=${encodeURIComponent(q)}`),
};
