/**
 * What LEKA concluded from what it knows (LEKA-377): the open findings of
 * its intelligence engine, the most pressing first, and its latest run —
 * and the way to ask for one now. The shapes are the generated ones;
 * api/leka/api/intelligence.py says what each route answers, and
 * docs/intelligence.md what each finding means.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type Finding = components["schemas"]["FindingRead"];
export type IntelligenceSummary = components["schemas"]["IntelligenceSummary"];
export type IntelligenceRun = components["schemas"]["RunRead"];
export type AnalysisRequested = components["schemas"]["AnalysisRequested"];

export const insights = {
  /** What is open, how bad, the most pressing, the latest run. */
  summary: () => apiFetch<IntelligenceSummary>("/intelligence/summary"),
  /** Analyse now, every analysis. `queued` is false when one is on its way. */
  analyse: () =>
    apiFetch<AnalysisRequested>("/intelligence/runs", {
      method: "POST",
      body: JSON.stringify({}),
    }),
};
