/**
 * An intention, as the API reads it (LEKA-373): lib/intentions/api.ts.
 *
 * What these protect: the form's scope sent as asked — an environment
 * other than every one, the services chosen, the sources when not all are
 * ticked; the period sent only when someone chose it, as instants — a
 * preset back from now, two calendar days with the second whole, never
 * past now; the words trimmed.
 */

import { describe, expect, it } from "vitest";

import { intentAsk, periodOf } from "@/lib/intentions/api";
import type { IntentionRequest } from "@/lib/validation/intentions";

const NOW = new Date("2026-10-07T15:30:00Z");

const REQUEST: IntentionRequest = {
  text: "  Pourquoi payment-api est lent depuis hier ?  ",
  sources: ["s1", "s2"],
  environment: "production",
  period: { preset: "7d", range: { from: "", to: "" } },
  services: ["e1"],
  attachments: [],
};

describe("an intention, as the API reads it", () => {
  it("sends the scope asked, and leaves the period to the words when nobody chose one", () => {
    expect(intentAsk(REQUEST, { everySource: true, periodChosen: false, now: NOW })).toEqual({
      text: "Pourquoi payment-api est lent depuis hier ?",
      services: ["e1"],
      sources: [],
      limit: 100,
      environment: "production",
    });
    const narrowed = intentAsk(
      { ...REQUEST, environment: "all" },
      { everySource: false, periodChosen: true, now: NOW },
    );
    expect(narrowed.sources).toEqual(["s1", "s2"]);
    expect(narrowed.environment).toBeUndefined();
    expect(narrowed.since).toBe("2026-09-30T15:30:00.000Z");
    expect(narrowed.until).toBe("2026-10-07T15:30:00.000Z");
  });

  it("reads a period as instants: a preset back from now, two days the second whole", () => {
    expect(periodOf({ preset: "24h", range: { from: "", to: "" } }, NOW)).toEqual({
      since: "2026-10-06T15:30:00.000Z",
      until: "2026-10-07T15:30:00.000Z",
    });
    expect(
      periodOf({ preset: "custom", range: { from: "2026-10-01", to: "2026-10-03" } }, NOW),
    ).toEqual({ since: "2026-10-01T00:00:00.000Z", until: "2026-10-04T00:00:00.000Z" });
    // Never past now; no start, no period.
    expect(
      periodOf({ preset: "custom", range: { from: "2026-10-06", to: "2026-10-07" } }, NOW).until,
    ).toBe("2026-10-07T15:30:00.000Z");
    expect(periodOf({ preset: "custom", range: { from: "", to: "" } }, NOW)).toEqual({});
  });
});
