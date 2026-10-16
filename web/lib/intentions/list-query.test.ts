/** The history's filters, as the list asks the API (LEKA-457). */

import { describe, expect, it, vi } from "vitest";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch }));

const { intentions } = await import("@/lib/intentions/api");

const asked = () => new URL(String(apiFetch.mock.lastCall?.[0]), "http://x").searchParams;

describe("the history's query", () => {
  it("leaves out what is not chosen: the latest changed first", () => {
    void intentions.list({});
    expect([...asked().keys()]).toEqual(["limit"]);
  });

  it("asks by agent, source, since a number of days, the oldest asked first", () => {
    const before = Date.now();
    void intentions.list({ filters: { agent: "architect", source: "s-1", days: 7, sort: "oldest" } });
    const query = asked();
    expect(query.get("agent")).toBe("architect");
    expect(query.get("source")).toBe("s-1");
    const since = Date.parse(query.get("since") ?? "");
    expect(before - since).toBeGreaterThanOrEqual(7 * 86_400_000 - 1000);
    expect(before - since).toBeLessThanOrEqual(7 * 86_400_000 + 1000);
    expect([query.get("sort"), query.get("order")]).toEqual(["created_at", "asc"]);
  });

  it("the newest asked first", () => {
    void intentions.list({ filters: { sort: "newest" } });
    expect([asked().get("sort"), asked().get("order")]).toEqual(["created_at", "desc"]);
  });

  it("only those whoever reads asked, still active: the header's (LEKA-475)", () => {
    void intentions.list({ phase: "active", filters: { mine: true } });
    expect([asked().get("phase"), asked().get("mine")]).toEqual(["active", "true"]);
  });
});
