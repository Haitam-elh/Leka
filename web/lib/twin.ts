/**
 * The Digital Twin (LEKA-442), as every screen reads it: each thing's state
 * in the same six words — never « sain » for what nothing says — with where
 * it comes from, how fresh, and the watch the plan includes.
 *
 *     unavailable   an open severe incident on it; its provider says failed
 *     degraded      an open incident of lower severity; stopped; deduced
 *     stale         what it rests on not read for 3 hours, or failing
 *     unknown       a source could tell, says nothing
 *     not_covered   no connected source could tell
 *     operational   a tool's measure, a provider's word, or deduced — said
 *
 * The API decides (leka/ingestion/enrichment/twin.py); the screens draw:
 * the map, the list, a sheet, the overview — the same state for the same
 * thing everywhere (`twinOf`).
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import type { Environment } from "@/lib/environment";
import type { Architecture } from "@/lib/knowledge-graph";

export type TwinState = components["schemas"]["TwinStateRead"];
export type TwinStateName = TwinState["state"];
export type TwinSource = components["schemas"]["TwinSourceRead"];
export type TwinCoverage = components["schemas"]["TwinCoverageRead"];
export type TwinFreshness = components["schemas"]["TwinFreshnessRead"];
export type Monitoring = components["schemas"]["MonitoringRead"];
export type Alert = components["schemas"]["AlertRead"];
/** What LEKA went through overnight, and what it found (2026-10-29). */
export type NightReview = components["schemas"]["NightReviewRead"];
export type NightPoint = components["schemas"]["NightPointRead"];

/** The worst first: what a list sorts by, what a legend says in order. */
export const TWIN_STATES: readonly TwinStateName[] = [
  "unavailable",
  "degraded",
  "stale",
  "unknown",
  "not_covered",
  "operational",
];

/** What needs someone: the states an overview puts first. */
export const TROUBLE: ReadonlySet<TwinStateName> = new Set(["unavailable", "degraded"]);

/** The environment's health in one word, and the share operational (LEKA-468):
 * the one rule the overview's « Mon environnement » and the page itself both
 * read, counted from the twin's states — services, databases, resources —
 * never from one screen's own figures.
 *
 *     unknown    no source, or nothing with a state yet
 *     stale      the last read is late: what it says is not now
 *     incident   an open incident, or something unavailable or degraded
 *     partial    something stale, unknown or not covered: not « Stable »
 *     stable     everything operational, read on time
 *
 * « Stable » is said only of the last one: an unknown, a thing no source
 * covers or a late read never counts as healthy. */
export type Health = "unknown" | "stale" | "incident" | "partial" | "stable";

export interface Overall {
  health: Health;
  /** Things with a state: the denominator of `share`. */
  total: number;
  operational: number;
  /** Things whose state is known: neither stale, unknown nor not covered. */
  known: number;
  /** Unavailable or degraded. */
  troubled: number;
  /** operational / total; null with nothing to count. */
  share: number | null;
}

export function overallOf(env: {
  states?: Readonly<Partial<Record<string, number>>> | null;
  incidents_open?: number;
  sources?: readonly unknown[] | null;
  freshness?: { late?: boolean } | null;
}): Overall {
  const n = (state: TwinStateName) => env.states?.[state] ?? 0;
  const total = TWIN_STATES.reduce((sum, state) => sum + n(state), 0);
  const operational = n("operational");
  const troubled = n("unavailable") + n("degraded");
  const known = total - n("stale") - n("unknown") - n("not_covered");
  let health: Health = "stable";
  if (!env.sources?.length || total === 0) health = "unknown";
  else if (env.freshness?.late) health = "stale";
  else if ((env.incidents_open ?? 0) > 0 || troubled > 0) health = "incident";
  else if (known < total) health = "partial";
  return { health, total, operational, known, troubled, share: total ? operational / total : null };
}

/** Each thing's state, by its id — the entity ids the company model keeps. */
export function twinOf(environment: Environment | undefined): Map<string, TwinState> {
  const found = new Map<string, TwinState>();
  for (const node of environment?.nodes ?? []) {
    if (node.entity_id && node.twin) found.set(node.entity_id, node.twin);
  }
  return found;
}

/** The architecture, its cards in the twin's states — where the twin knows
 * them — and its health counted from them: one state per thing on every
 * screen. A card the twin does not know keeps what the model said. */
export function withTwin(
  data: Architecture | undefined,
  twin: ReadonlyMap<string, TwinState>,
): Architecture | undefined {
  if (!data || twin.size === 0) return data;
  const cards = data.cards.map((card) => {
    const found = card.entity_id ? twin.get(card.entity_id) : undefined;
    return found
      ? { ...card, status: found.state, deduced: found.basis === "deduced" }
      : card;
  });
  const health: Record<string, number> = {};
  for (const card of cards) {
    if (!card.status || !["services", "data", "cloud"].includes(card.column)) continue;
    health[card.status] = (health[card.status] ?? 0) + 1;
  }
  return { ...data, cards, health: health as Architecture["health"] };
}

/** Rows of things in a twin state, the worst first, then by name. */
export function byState<T extends { name: string; twin?: TwinState | null }>(
  rows: readonly T[],
): T[] {
  const rank = (row: T) =>
    row.twin ? TWIN_STATES.indexOf(row.twin.state) : TWIN_STATES.length;
  return [...rows].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

export const monitoring = {
  get: () => apiFetch<Monitoring>("/monitoring"),
  /** Taken in hand (LEKA-463): by whom, when — the first only. */
  acknowledge: (id: string) =>
    apiFetch<Alert>(`/monitoring/alerts/${encodeURIComponent(id)}/acknowledge`, { method: "POST" }),
  /** The last night review — null before the first. */
  night: () => apiFetch<NightReview | null>("/monitoring/night-review"),
  /** Gone through again now. */
  nightAgain: () => apiFetch<NightReview>("/monitoring/night-review", { method: "POST" }),
};
