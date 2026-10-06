/**
 * What the company model's sources disagree on (LEKA-382): each side, who
 * says it, how much each is believed, what LEKA recommends — settled in À
 * valider by someone who may approve. The shapes are the generated ones;
 * api/leka/api/intelligence.py says what each route answers,
 * docs/intelligence.md § 14 how a conflict is judged and settled.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Conflict = components["schemas"]["ConflictRead"];
export type ConflictDetail = components["schemas"]["ConflictDetail"];
export type ConflictSide = components["schemas"]["ConflictSideRead"];
export type ConflictSummary = components["schemas"]["ConflictSummary"];
export type ConflictStatus = Conflict["status"];
export type AuthorityRule = components["schemas"]["AuthorityRuleRead"];

export interface ConflictPage {
  data: Conflict[];
  next_cursor: string | null;
}

const BASE = "/intelligence/conflicts";

export const conflicts = {
  /** The conflicts in a state, the latest seen first — 100 at most. */
  list: (status: ConflictStatus) => apiFetch<ConflictPage>(`${BASE}?status=${status}&limit=100`),
  one: (id: string) => apiFetch<ConflictDetail>(`${BASE}/${id}`),
  summary: () => apiFetch<ConflictSummary>(`${BASE}/summary`),
  resolve: (id: string, body: { side: number; reason?: string | null; remember?: boolean }) =>
    apiFetch<ConflictDetail>(`${BASE}/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  dismiss: (id: string, body: { reason?: string | null }) =>
    apiFetch<ConflictDetail>(`${BASE}/${id}/dismiss`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reopen: (id: string) => apiFetch<ConflictDetail>(`${BASE}/${id}/reopen`, { method: "POST" }),
};
