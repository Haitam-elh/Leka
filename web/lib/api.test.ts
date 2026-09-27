/**
 * The CSRF token a mutation carries.
 *
 * The production bug: the page is served from leka-core.com, the API from
 * api.leka-core.com, and the page cannot read the API host's CSRF cookie.
 * Every mutation went without its token and was refused — a sign-out
 * included, so a reload signed people back in. The browser suite could not
 * see it: on localhost the two share their cookies. This can.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, rememberCsrfToken } from "@/lib/api";

const fetchMock = vi.fn();

function sentHeaders(): Record<string, string> {
  return fetchMock.mock.calls[0][1].headers as Record<string, string>;
}

describe("the CSRF token of a mutation", () => {
  beforeEach(() => {
    fetchMock.mockReset().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    rememberCsrfToken(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = "leka_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });

  it("is the one the API handed back, when the page cannot read the cookie", async () => {
    rememberCsrfToken("from-the-body");

    await apiFetch("/auth/logout", { method: "POST" });

    expect(sentHeaders()["X-CSRF-Token"]).toBe("from-the-body");
  });

  it("is the cookie's, when the page can read it", async () => {
    rememberCsrfToken("from-the-body");
    document.cookie = "leka_csrf=from-the-cookie; path=/";

    await apiFetch("/auth/logout", { method: "POST" });

    expect(sentHeaders()["X-CSRF-Token"]).toBe("from-the-cookie");
  });

  it("is not sent on a read", async () => {
    rememberCsrfToken("from-the-body");

    await apiFetch("/auth/me");

    expect(sentHeaders()["X-CSRF-Token"]).toBeUndefined();
  });
});
