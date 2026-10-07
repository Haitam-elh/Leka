/**
 * Activité (LEKA-383): what happened in the environment and what LEKA did
 * over a period — counted against the period before, day by day, the
 * latest, what concerned most, who decided most. The shapes are the
 * generated ones; api/leka/intelligence/activity.py says what each counts.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import type { Finding } from "@/lib/insights";

export type Activity = components["schemas"]["ActivityRead"];
export type ActivityItem = components["schemas"]["ActivityItem"];
export type ActivityCategory = ActivityItem["category"];
export type ActivityBucket = components["schemas"]["ActivityBucket"];
export type ActivityCount = components["schemas"]["ActivityCount"];

export const CATEGORIES: readonly ActivityCategory[] = ["information", "action", "alert", "incident"];
export const PERIODS = [7, 30, 90] as const;
export type PeriodDays = (typeof PERIODS)[number];

export interface FindingPage {
  data: Finding[];
  next_cursor: string | null;
}

/** The reader's time zone, as the browser knows it: the days are theirs. */
export function readerZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

export const activity = {
  read: (days: PeriodDays, limit = 50) => {
    const query = new URLSearchParams({ days: String(days), limit: String(limit) });
    const zone = readerZone();
    if (zone) query.set("timezone", zone);
    return apiFetch<Activity>(`/intelligence/activity?${query.toString()}`);
  },
  /** What LEKA reads in the model's course (LEKA-383): the open findings
   * of its evolution analyses, the most pressing first. */
  trends: () =>
    apiFetch<FindingPage>("/intelligence/findings?status=open&category=evolution&limit=3"),
};
