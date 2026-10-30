/**
 * The night review on Mon environnement (2026-10-29).
 *
 * What these protect: before the first, said when it comes and how to run
 * it; what LEKA went through, counted; each point in words, the most
 * serious first, with where to see it and, when LEKA can look into it, the
 * question ready to ask; nothing found said as good news; run again on
 * demand, shown at once.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { NightReview } from "@/lib/twin";

const night = vi.hoisted(() => ({ get: vi.fn(), again: vi.fn() }));
vi.mock("@/lib/twin", async (original) => {
  const real = await original<typeof import("@/lib/twin")>();
  return { ...real, monitoring: { ...real.monitoring, night: night.get, nightAgain: night.again } };
});

const { NightReviewCard } = await import("@/components/environment/night-review");

const REVIEW: NightReview = {
  id: "r1",
  at: "2026-10-29T02:30:00Z",
  trigger: "night",
  checked: { things: 42, sources: 3, alerts: 1, findings: 7 },
  points: [
    {
      kind: "alert",
      severity: "high",
      name: "payment-api",
      count: 1,
      href: "/environment",
      ask: true,
      params: { trouble: "unavailable" },
    },
    {
      kind: "source",
      severity: "medium",
      name: "GitHub",
      count: 1,
      href: "/sources/s1",
      ask: false,
      params: { why: "unread" },
    },
    { kind: "decisions", severity: "medium", name: "", count: 2, href: "/approvals", ask: false, params: {} },
  ],
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <NightReviewCard />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  night.get.mockReset();
  night.again.mockReset();
});

describe("the night review", () => {
  it("says what LEKA went through and what to look at, each with where and what to ask", async () => {
    night.get.mockResolvedValue(REVIEW);
    show();
    expect(await screen.findByTestId("night-review-verdict")).toHaveTextContent("3 points à regarder");
    expect(screen.getByTestId("night-review-checked")).toHaveTextContent(
      "LEKA a passé en revue 42 éléments, 3 sources, 1 alerte et 7 constats",
    );
    const points = screen.getAllByTestId("night-review-point");
    expect(points.map((p) => p.getAttribute("data-kind"))).toEqual(["alert", "source", "decisions"]);
    expect(points[0]).toHaveTextContent("payment-api : indisponible");
    expect(within(points[0]).getByRole("link", { name: "Analyser" })).toHaveAttribute(
      "href",
      `/intentions/new?q=${encodeURIComponent("Pourquoi payment-api est indisponible ?")}`,
    );
    expect(points[1]).toHaveTextContent("Source « GitHub » : non lue depuis plus de 24 h");
    expect(within(points[1]).queryByRole("link", { name: "Analyser" })).not.toBeInTheDocument();
    expect(within(points[1]).getByRole("link", { name: "Voir" })).toHaveAttribute("href", "/sources/s1");
    expect(points[2]).toHaveTextContent("2 décisions attendent votre validation");
  });

  it("before the first, says when it comes — and runs it now on demand", async () => {
    const user = userEvent.setup();
    night.get.mockResolvedValue(null);
    night.again.mockResolvedValue({ ...REVIEW, trigger: "asked", points: [] });
    show();
    await waitFor(() =>
      expect(screen.getByTestId("night-review")).toHaveTextContent("chaque nuit à 3 h 30"),
    );
    await user.click(screen.getByTestId("night-review-again"));
    await waitFor(() => expect(screen.getByTestId("night-review-verdict")).toHaveTextContent("Rien à signaler"));
    expect(screen.getByTestId("night-review")).toHaveTextContent("Tout va bien");
    expect(screen.getByTestId("night-review-checked")).toHaveTextContent("Relancée");
  });
});
