/** The home's « Mon environnement » never stays on an empty first look. */

import { describe, expect, it } from "vitest";

import { untilFirstReading } from "@/lib/environment-queries";
import { LIVE_EVERY } from "@/lib/live";

describe("the environment, asked again", () => {
  it("every few seconds until the first reading of its sources lands, then as everything is", () => {
    expect(untilFirstReading({ sources: [{}], freshness: { last_read_at: null } })).toBe(5000);
    expect(untilFirstReading({ sources: [{}], freshness: { last_read_at: "2026-10-16T13:51:39Z" } })).toBe(
      LIVE_EVERY,
    );
    expect(untilFirstReading({ sources: [], freshness: null })).toBe(LIVE_EVERY);
    expect(untilFirstReading(undefined)).toBe(LIVE_EVERY);
  });
});
