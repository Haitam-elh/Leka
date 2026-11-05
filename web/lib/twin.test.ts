/**
 * The environment's health (LEKA-468): one rule for the overview and the
 * page, from the twin's states — « Stable » only when everything is
 * operational and read on time. And the score diagnosed (LEKA-532): made
 * of each thing tracked, reproducible, what keeps it from 100 % the most
 * urgent first, its ceiling only when a provider caps it.
 */

import { describe, expect, it } from "vitest";

import { diagnose, fixOf, overallOf, type Tracked, type TwinStateName } from "@/lib/twin";

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

// ── the score diagnosed (LEKA-532) ─────────────────────────────────────────

type Row = Tracked;

function row(name: string, state: TwinStateName, reason: string, more: Partial<Row> = {}): Row {
  return {
    entity: { id: `id-${name}`, type: "infra_resource", key: name, name },
    resource_type: null,
    provider: "aws",
    region: "eu-west-1",
    environment: "production",
    sources: ["aws-1"],
    twin: {
      state,
      basis: "none",
      reason,
      observed_at: null,
      signal: [],
      fresh: true,
      was: null,
      certainty: "confirmed",
      incident: null,
      said: null,
    },
    ...more,
  };
}

describe("the score, diagnosed thing by thing", () => {
  const rows = [
    row("db", "operational", "resource_running"),
    row("cluster", "operational", "resource_running"),
    row("bucket", "unknown", "provider_no_state", { resource_type: "s3:bucket" }),
    row("auth", "unknown", "not_watched"),
    row("api", "not_covered", "no_monitoring_source"),
    row("old", "stale", "sources_stale"),
    row("pay", "unavailable", "incident_open"),
    row("worker", "degraded", "deduced_health"),
  ];

  it("is reproducible from its rows: health, coverage and the ceiling", () => {
    const found = diagnose(rows);
    expect(found).toMatchObject({ total: 8, healthy: 2, known: 4, health: 2 / 8, coverage: 4 / 8 });
    // What its provider gives no readable state for caps it.
    expect(found.reachable).toBe(7 / 8);
    // Each thing weighs the same.
    expect(found.blockers.every((b) => b.points === 100 / 8)).toBe(true);
    expect(found.blockers.reduce((sum, b) => sum + b.points, 0) + found.healthy * (100 / 8)).toBeCloseTo(100);
  });

  it("puts first what to settle, last what nothing can lift", () => {
    expect(diagnose(rows).blockers.map((b) => [b.row.entity.name, b.fix])).toEqual([
      ["pay", "incident"],
      ["worker", "investigate"],
      ["old", "source"],
      ["api", "monitor"],
      ["auth", "watch"],
      ["bucket", "limit"],
    ]);
  });

  it("says each fix from why the thing is in its state", () => {
    const fix = (state: TwinStateName, reason: string) => fixOf(row("x", state, reason).twin);
    expect(fix("not_covered", "no_cloud_source")).toBe("cloud");
    expect(fix("stale", "sources_failing")).toBe("source");
    expect(fix("unknown", "state_unrecognised")).toBe("limit");
    expect(fix("unknown", "no_signal")).toBe("unsure");
  });

  it("promises nothing it cannot count: no ceiling without a cap, nothing without rows", () => {
    expect(diagnose(rows.filter((r) => r.twin.reason !== "provider_no_state")).reachable).toBeNull();
    expect(diagnose([])).toMatchObject({ total: 0, health: null, coverage: null, reachable: null, blockers: [] });
  });
});
