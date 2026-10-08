/**
 * What came of an intention (LEKA-392): what should be true once its plan
 * ran, whether it came — read from the company model and from what the
 * system that acted reported, or said by a person — and its whole story,
 * from its analysis to its outcome.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Expectation = components["schemas"]["ExpectationRead"];
export type Verification = components["schemas"]["IntentionVerificationRead"];
export type ObservedResult = components["schemas"]["ObservedResultRead"];
export type TimelineItem = components["schemas"]["TimelineItem"];
export type TimelineCategory = TimelineItem["category"];

export const TIMELINE_CATEGORIES: readonly TimelineCategory[] = [
  "intention",
  "analysis",
  "decision",
  "action",
  "outcome",
];

export type TimelineFilters = {
  categories?: readonly TimelineCategory[];
  actor?: "person" | "system" | null;
  since?: string | null;
  until?: string | null;
};

function query(filters: TimelineFilters): string {
  const params = new URLSearchParams();
  for (const category of filters.categories ?? []) params.append("category", category);
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  const said = params.toString();
  return said ? `?${said}` : "";
}

export const outcomes = {
  expect: (intentionId: string, expectations: readonly Expectation[]) =>
    apiFetch<Expectation[]>(`/intentions/${intentionId}/plan/expectations`, {
      method: "PUT",
      body: JSON.stringify({ expectations }),
    }),
  verifications: (intentionId: string) =>
    apiFetch<Verification[]>(`/intentions/${intentionId}/verifications`),
  check: (intentionId: string) =>
    apiFetch<Verification>(`/intentions/${intentionId}/verification/check`, { method: "POST" }),
  report: (
    intentionId: string,
    expectationId: string,
    body: { met: boolean; note: string; link?: string | null },
  ) =>
    apiFetch<Verification>(
      `/intentions/${intentionId}/verification/expectations/${encodeURIComponent(expectationId)}/report`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  conclude: (intentionId: string, note: string) =>
    apiFetch<Verification>(`/intentions/${intentionId}/verification/conclude`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  timeline: (intentionId: string, filters: TimelineFilters = {}) =>
    apiFetch<TimelineItem[]>(`/intentions/${intentionId}/timeline${query(filters)}`),
};

/** Still being read: read again now and then. */
export function isVerifying(verification: Verification | undefined): boolean {
  return verification?.status === "verifying";
}

/** A link a person gave, only when a browser opens it as a page. */
export function safeLink(link: unknown): string | null {
  return typeof link === "string" && /^https?:\/\//i.test(link) ? link : null;
}
