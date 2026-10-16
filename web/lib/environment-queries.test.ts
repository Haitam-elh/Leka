/** The home's « Mon environnement » never stays on an empty first look. */

import { describe, expect, it } from "vitest";

import { untilFirstReading } from "@/lib/environment-queries";

describe("the environment, asked again", () => {
  it("until the first reading of its sources lands, then never", () => {
    expect(untilFirstReading({ sources: [{}], freshness: { last_read_at: null } })).toBe(5000);
    expect(untilFirstReading({ sources: [{}], freshness: { last_read_at: "2026-10-16T13:51:39Z" } })).toBe(false);
    expect(untilFirstReading({ sources: [], freshness: null })).toBe(false);
    expect(untilFirstReading(undefined)).toBe(false);
  });
});
