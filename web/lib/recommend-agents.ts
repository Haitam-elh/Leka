/**
 * The agents the home recommends (LEKA-488), in one row: explainable, never
 * arbitrary. The unavailable last; before them, first those that work with
 * the sources this workspace connected, then those needing no source, then
 * those waiting on one; at each, what the plan includes or was bought before
 * what may be bought; then the catalogue's own order — so the same data gives
 * the same row, and no catalogue still gives one.
 */

import type { AgentState } from "@/components/capabilities/offers";
import type { Capability } from "@/lib/capabilities";

export type Fit = "connected" | "none_needed" | "to_connect";

export interface Recommended<T> {
  agent: T;
  fit: Fit | null;
}

const FITS: readonly Fit[] = ["connected", "none_needed", "to_connect"];
const STATES: readonly AgentState[] = ["included", "owned", "option", "upgrade", "unavailable"];

export function fitOf(capability: Capability | undefined): Fit | null {
  if (!capability) return null;
  if (capability.sources.length === 0) return "none_needed";
  return capability.sources.every((need) => need.connected) ? "connected" : "to_connect";
}

export function recommend<T extends { key: string }>(
  agents: readonly T[],
  stateOf: (key: string) => AgentState | null,
  catalogue: readonly Capability[] | undefined,
  count: number,
): Recommended<T>[] {
  const known = new Map((catalogue ?? []).map((c) => [c.key, c]));
  const rank = (agent: T, at: number) => {
    const fit = fitOf(known.get(agent.key));
    const state = stateOf(agent.key) ?? "unavailable";
    const out = state === "unavailable" ? 1 : 0;
    return [out, fit === null ? FITS.length : FITS.indexOf(fit), STATES.indexOf(state), at] as const;
  };
  return agents
    .map((agent, at) => ({ agent, at, by: rank(agent, at) }))
    .sort((a, b) => a.by.reduce((said, x, i) => said || x - b.by[i], 0))
    .slice(0, count)
    .map(({ agent }) => ({ agent, fit: fitOf(known.get(agent.key)) }));
}
