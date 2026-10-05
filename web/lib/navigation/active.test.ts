/**
 * Which URL is which page — what the breadcrumb, the title and the
 * sidebar's mark (lib/navigation/tree.test.ts) all start from.
 *
 * The rules that make "you always know where you are" true, and each of the
 * ways it silently stops being true.
 */

import { describe, expect, it } from "vitest";

import { matchRoute } from "@/lib/navigation/active";

describe("matching a URL to a route", () => {
  it("matches a plain page", () => {
    expect(matchRoute("/sources")?.route.id).toBe("sources");
  });

  it("prefers a literal segment over a parameter", () => {
    // /intentions/new is the composer, not an intention called "new".
    expect(matchRoute("/intentions/new")?.route.id).toBe("intention-new");
    expect(matchRoute("/intentions/42")?.route.id).toBe("intention-detail");
  });

  it("reads the parameters out of the path", () => {
    const match = matchRoute("/environment/services/payment-api");

    expect(match?.route.id).toBe("entity-detail");
    expect(match?.params).toEqual({ entityType: "services", entityId: "payment-api" });
  });

  it("accepts a tab the route declares, and refuses one it does not", () => {
    expect(matchRoute("/intentions/42/evidence")?.tab).toBe("evidence");
    expect(matchRoute("/intentions/42/nonsense")).toBeUndefined();
  });

  it("returns nothing for an address that is not a page", () => {
    expect(matchRoute("/there-is-no-such-page")).toBeUndefined();
    expect(matchRoute("/sources/42/extra/deep")).toBeUndefined();
  });

  it("ignores a query string and a fragment", () => {
    expect(matchRoute("/sources?filter=github#top")?.route.id).toBe("sources");
  });
});
