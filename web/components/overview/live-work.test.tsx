/**
 * « LEKA travaille sur… » on the home (2026-10-29).
 *
 * What these protect: each piece of work under way said with its step and
 * the way to follow it; nothing under way, nothing shown.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const now = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/twin", async (original) => {
  const real = await original<typeof import("@/lib/twin")>();
  return { ...real, monitoring: { ...real.monitoring, now: now.get } };
});

const { LiveWork } = await import("@/components/overview/live-work");

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <LiveWork />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => now.get.mockReset());

describe("LEKA is working on", () => {
  it("says each piece of work, its step and where to follow it", async () => {
    now.get.mockResolvedValue([
      { kind: "agent", title: "Revue de design", step: "drawing_design", since: null, href: "/intentions/i1/deliverable" },
      { kind: "intention", title: "Pourquoi le paiement est lent ?", step: "analysing", since: null, href: "/intentions/i2" },
    ]);
    show();
    const items = await screen.findAllByTestId("live-work-item");
    expect(screen.getByTestId("live-work")).toHaveTextContent("LEKA travaille sur…");
    expect(items[0]).toHaveTextContent("Revue de design· dessine les maquettes");
    expect(within(items[0]).getByRole("link", { name: "Revue de design" })).toHaveAttribute(
      "href",
      "/intentions/i1/deliverable",
    );
    expect(items[1]).toHaveTextContent("analyse en cours");
  });

  it("shows nothing when nothing is under way", async () => {
    now.get.mockResolvedValue([]);
    show();
    await waitFor(() => expect(now.get).toHaveBeenCalled());
    expect(screen.queryByTestId("live-work")).not.toBeInTheDocument();
  });
});
