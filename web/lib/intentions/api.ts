import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { BUDGET, type IntentAsk } from "@/lib/context";
import type { IntentionRequest } from "@/lib/validation/intentions";

/**
 * Submitting an intention (LEKA-384): it is kept — what was asked, by whom,
 * where it stands — and the context it asks for assembled with it (LEKA-373):
 * what LEKA reads of its words and its scope, what it is about, when,
 * where, what is missing. Step 2 shows that context; the intention is in
 * Mes intentions from then on, with its history.
 *
 * WHAT THE FORM SAYS, AND WHAT IT LEAVES TO THE WORDS. The scope it shows
 * is sent as asked: an environment other than "every one", the services
 * chosen, the sources when not all of them are ticked. The period is sent
 * only when someone chose it: its default is no choice, and « depuis
 * hier » in the question says more than a preset nobody touched.
 *
 * TODO: attachments are names here. Uploading them is a separate call to
 * object storage, and the request should carry the ids it returns.
 */

const HOUR = 3_600_000;
const PRESETS: Record<string, number> = { "24h": 24 * HOUR, "7d": 7 * 24 * HOUR, "30d": 30 * 24 * HOUR };

/** The intention as the API reads it. */
export function intentAsk(
  request: IntentionRequest,
  {
    everySource,
    periodChosen,
    now = new Date(),
  }: { everySource: boolean; periodChosen: boolean; now?: Date },
): IntentAsk {
  const ask: IntentAsk = {
    text: request.text.trim(),
    services: request.services,
    sources: everySource ? [] : request.sources,
    limit: BUDGET,
  };
  if (request.environment && request.environment !== "all") ask.environment = request.environment;
  if (periodChosen) Object.assign(ask, periodOf(request.period, now));
  return ask;
}

/** A period as the form holds it — a preset, or two days — as instants. */
export function periodOf(
  period: IntentionRequest["period"],
  now: Date,
): { since: string; until: string } | Record<string, never> {
  const span = PRESETS[period.preset];
  if (span) return { since: new Date(now.getTime() - span).toISOString(), until: now.toISOString() };
  const { from, to } = period.range;
  if (!from) return {};
  // Two calendar days, the second whole: « du 1er au 3 » reads the 3rd.
  const until = to ? new Date(`${to}T00:00:00Z`).getTime() + 24 * HOUR : now.getTime();
  return {
    since: new Date(`${from}T00:00:00Z`).toISOString(),
    until: new Date(Math.min(until, now.getTime())).toISOString(),
  };
}

export type Intention = components["schemas"]["IntentionRead"];
export type IntentionDetail = components["schemas"]["IntentionDetail"];
export type IntentionCreated = components["schemas"]["IntentionCreated"];
export type IntentionEvent = components["schemas"]["IntentionEventRead"];
export type IntentionLink = components["schemas"]["IntentionLinkRead"];
export type IntentionCounts = components["schemas"]["IntentionCounts"];
export type IntentionAnalysisRead = components["schemas"]["IntentionAnalysisRead"];
export type IntentionStatus = Intention["status"];
export type Routing = components["schemas"]["RoutingRead"];
export type RoutedCandidate = components["schemas"]["RoutedCandidateRead"];
export type IntentionPhase = "active" | "scheduled" | "finished" | "archived";

export interface IntentionPage {
  data: Intention[];
  next_cursor: string | null;
}

const BASE = "/intentions";

export const intentions = {
  /** Asked: kept, its context assembled — 422 when nothing can start it. */
  create: (ask: IntentAsk) =>
    apiFetch<IntentionCreated>(BASE, { method: "POST", body: JSON.stringify(ask) }),
  /** Asked again: its context made again, a new version (LEKA-374). */
  ask: (id: string, ask: IntentAsk) =>
    apiFetch<IntentionCreated>(`${BASE}/${id}/ask`, {
      method: "POST",
      body: JSON.stringify(ask),
    }),
  /** A page of them, the latest changed first — not archived unless asked. */
  list: ({
    phase,
    q,
    cursor,
    limit = 20,
  }: {
    phase?: IntentionPhase | null;
    q?: string;
    cursor?: string | null;
    limit?: number;
  }) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (phase) query.set("phase", phase);
    if (q) query.set("q", q);
    if (cursor) query.set("cursor", cursor);
    return apiFetch<IntentionPage>(`${BASE}?${query.toString()}`);
  },
  counts: () => apiFetch<IntentionCounts>(`${BASE}/counts`),
  one: (id: string) => apiFetch<IntentionDetail>(`${BASE}/${id}`),
  history: (id: string) => apiFetch<IntentionEvent[]>(`${BASE}/${id}/history`),
  cancel: (id: string, reason?: string) =>
    apiFetch<IntentionDetail>(`${BASE}/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || null }),
    }),
  archive: (id: string) => apiFetch<IntentionDetail>(`${BASE}/${id}/archive`, { method: "POST" }),
  restore: (id: string) => apiFetch<IntentionDetail>(`${BASE}/${id}/restore`, { method: "POST" }),
  /** Its latest analysis (LEKA-388) — 404 while there is none. */
  analysis: (id: string) => apiFetch<IntentionAnalysisRead>(`${BASE}/${id}/analysis`),
  /** Every analysis of it, the latest first. */
  analyses: (id: string) => apiFetch<IntentionAnalysisRead[]>(`${BASE}/${id}/analyses`),
  /** Where it was routed, and why (LEKA-398) — routed on first read. */
  routing: (id: string) => apiFetch<Routing>(`${BASE}/${id}/routing`),
  /** Routed again, as it and the catalogue now stand. */
  route: (id: string) => apiFetch<Routing>(`${BASE}/${id}/routing`, { method: "POST" }),
  /** Analysed again: queued — false when one is already on its way. */
  analyse: (id: string) =>
    apiFetch<{ queued: boolean }>(`${BASE}/${id}/analyse`, { method: "POST" }),
};

export function submitIntention(ask: IntentAsk): Promise<IntentionCreated> {
  return intentions.create(ask);
}

/** The intention asked again, as it now stands: the same context made
 * again — a new version that says what LEKA reads differently (LEKA-374). */
export function reaskIntention(intentionId: string, ask: IntentAsk): Promise<IntentionCreated> {
  return intentions.ask(intentionId, ask);
}
