import { describe, expect, it } from "vitest";

import type { Capability } from "@/lib/capabilities";
import { recommend } from "@/lib/recommend-agents";

const cap = (key: string, sources: { any_of: string[]; connected: boolean }[]) =>
  ({ key, sources }) as unknown as Capability;

const AGENTS = ["a", "b", "c", "d", "e"].map((key) => ({ key }));
const STATES: Record<string, "included" | "owned" | "option" | "upgrade" | "unavailable"> = {
  a: "option",
  b: "unavailable",
  c: "included",
  d: "option",
  e: "owned",
};

describe("the agents the home recommends (LEKA-488)", () => {
  it("those working with the connected sources first, then by what the plan gives — the unavailable last", () => {
    const catalogue = [
      cap("a", [{ any_of: ["github"], connected: true }]),
      cap("b", [{ any_of: ["github"], connected: true }]),
      cap("c", []),
      cap("d", [{ any_of: ["jira"], connected: false }]),
      cap("e", []),
    ];
    const row = recommend(AGENTS, (k) => STATES[k], catalogue, 4);
    expect(row.map((r) => [r.agent.key, r.fit])).toEqual([
      ["a", "connected"],
      ["c", "none_needed"],
      ["e", "none_needed"],
      ["d", "to_connect"],
    ]);
  });

  it("no catalogue yet: by state, then its order — the same row every time", () => {
    const row = recommend(AGENTS, (k) => STATES[k], undefined, 5);
    expect(row.map((r) => r.agent.key)).toEqual(["c", "e", "a", "d", "b"]);
    expect(recommend(AGENTS, (k) => STATES[k], undefined, 5)).toEqual(row);
  });
});
