/**
 * The environment's health (LEKA-468): one rule for the overview and the
 * page, from the twin's states — « Stable » only when everything is
 * operational and read on time.
 */

import { describe, expect, it } from "vitest";

import { overallOf } from "@/lib/twin";

const none = { unavailable: 0, degraded: 0, stale: 0, unknown: 0, not_covered: 0, operational: 0 };
const read = { sources: [{}], freshness: { late: false }, incidents_open: 0 };

describe("the environment's health", () => {
  it("is Stable only when every thing is operational, read on time", () => {
    expect(overallOf({ ...read, states: { ...none, operational: 6 } })).toMatchObject({ health: "stable", share: 1 });
  });

  it("never counts unknown, not covered or stale as healthy", () => {
    for (const state of ["unknown", "not_covered", "stale"]) {
      expect(overallOf({ ...read, states: { ...none, operational: 5, [state]: 1 } })).toMatchObject({
        health: "partial",
        known: 5,
        total: 6,
      });
    }
  });

  it("says trouble for an open incident, or a thing unavailable or degraded", () => {
    expect(overallOf({ ...read, incidents_open: 1, states: { ...none, operational: 3 } }).health).toBe("incident");
    expect(overallOf({ ...read, states: { ...none, operational: 3, unavailable: 1 } })).toMatchObject({ health: "incident", troubled: 1 });
  });

  it("says a late read before anything it read", () => {
    expect(overallOf({ ...read, freshness: { late: true }, states: { ...none, operational: 3 } }).health).toBe("stale");
  });

  it("knows nothing without a source, or with nothing to count", () => {
    expect(overallOf({ ...read, sources: [], states: { ...none, operational: 3 } }).health).toBe("unknown");
    expect(overallOf({ ...read, states: none })).toMatchObject({ health: "unknown", share: null });
  });

  it("counts the share the page shows: operational over every thing with a state", () => {
    expect(overallOf({ ...read, states: { ...none, operational: 12, unknown: 5, not_covered: 1 } }).share).toBeCloseTo(12 / 18);
  });
});
