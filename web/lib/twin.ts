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
};
