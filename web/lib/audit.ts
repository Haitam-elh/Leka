/**
 * The audit trail (LEKA-407): one record per event that matters — who did
 * what, to what, with what outcome, from where — searched, read, exported;
 * how long it is kept.
 */

import { apiAddress, apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type AuditEvent = components["schemas"]["AuditEventRead"];
export type AuditEventDetail = components["schemas"]["AuditEventDetail"];
export type AuditPage = components["schemas"]["AuditPageRead"];
export type AuditSettings = components["schemas"]["AuditSettingsRead"];
export type AuditCategory = AuditEvent["category"];
export type AuditOutcome = AuditEvent["outcome"];

export const AUDIT_CATEGORIES: readonly AuditCategory[] = [
  "user",
  "team",
  "workspace",
  "data",
  "access",
  "governance",
  "decision",
  "action",
  "ai",
  "audit",
];

/** How far back, as the filter offers it. */
export const PERIODS = { day: 1, week: 7, month: 30, quarter: 90 } as const;
export type Period = keyof typeof PERIODS | "all";

export type AuditFilters = {
  category?: AuditCategory | "";
  outcome?: AuditOutcome | "";
  actor?: string;
  q?: string;
  period?: Period;
  action?: string;
  target_id?: string;
};

/** The filters as the API reads them — what is empty left out. */
export function auditParams(
  filters: AuditFilters,
  now: Date = new Date(),
): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.outcome) params.set("outcome", filters.outcome);
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.action) params.set("action", filters.action);
  if (filters.target_id) params.set("target_id", filters.target_id);
  if (filters.period && filters.period !== "all") {
    const since = new Date(
      now.getTime() - PERIODS[filters.period] * 86_400_000,
    );
    params.set("since", since.toISOString());
  }
  return params;
}

export const audit = {
  search: (filters: AuditFilters, cursor?: string | null) => {
    const params = auditParams(filters);
    params.set("limit", "50");
    if (cursor) params.set("cursor", cursor);
    return apiFetch<AuditPage>(`/governance/audit?${params.toString()}`);
  },
  event: (id: string) =>
    apiFetch<AuditEventDetail>(`/governance/audit/${encodeURIComponent(id)}`),
  settings: () => apiFetch<AuditSettings>("/governance/audit/settings"),
  keep: (days: number) =>
    apiFetch<AuditSettings>("/governance/audit/settings", {
      method: "PUT",
      body: JSON.stringify({ retention_days: days }),
    }),
  /** Where the CSV is: followed by the browser, the session's cookie with it. */
  exportAddress: (filters: AuditFilters) =>
    apiAddress(`/governance/audit/export?${auditParams(filters).toString()}`),
};
