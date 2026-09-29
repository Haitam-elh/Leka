/**
 * Which field a custom connector's form shows, for which choice (LEKA-426).
 *
 * What these protect: a field is hidden only where the choice above it
 * makes it pointless — and what a hidden field holds is never sent, so an
 * API that refuses a header name without a header never sees one.
 */

import { describe, expect, it } from "vitest";

import { CUSTOM_KINDS, isCustom, shownFor, shownOnly, TEMPLATES } from "@/lib/custom-connectors";

describe("the fields a choice makes useful", () => {
  it.each([
    ["none", { auth_name: false, username: false, secret: false }],
    ["bearer", { auth_name: false, username: false, secret: true }],
    ["header", { auth_name: true, username: false, secret: true }],
    ["query", { auth_name: true, username: false, secret: true }],
    ["basic", { auth_name: false, username: true, secret: true }],
  ])("for an API reached with %s", (auth, expected) => {
    for (const kind of ["custom_rest", "custom_graphql"]) {
      for (const [field, shown] of Object.entries(expected)) {
        expect(shownFor(kind, field, { auth }), `${kind}.${field}`).toBe(shown);
      }
      expect(shownFor(kind, "definition", { auth })).toBe(true);
    }
  });

  it("names no header for Standard Webhooks, which names its own", () => {
    expect(shownFor("custom_webhook", "signature_header", { signature: "hmac_sha256" })).toBe(true);
    expect(shownFor("custom_webhook", "signature_header", { signature: "token" })).toBe(true);
    expect(
      shownFor("custom_webhook", "signature_header", { signature: "standard_webhooks" }),
    ).toBe(false);
    expect(shownFor("custom_webhook", "secret", { signature: "standard_webhooks" })).toBe(true);
  });

  it("leaves every other connector's form as its schema says", () => {
    expect(shownFor("postgresql", "username", { auth: "none" })).toBe(true);
    expect(shownFor("github", "token", {})).toBe(true);
  });

  it("sends nothing a choice made pointless", () => {
    const typed = { auth: "bearer", auth_name: "X-API-Key", definition: "{}" };

    expect(shownOnly("custom_rest", typed, typed)).toEqual({ auth: "bearer", definition: "{}" });
  });
});

describe("the custom kinds", () => {
  it("are the custom category, each with an example definition", () => {
    for (const kind of CUSTOM_KINDS) {
      expect(isCustom(kind)).toBe(true);
      expect(JSON.parse(TEMPLATES[kind]).resources.length).toBeGreaterThan(0);
    }
    expect(isCustom("github")).toBe(false);
  });
});
