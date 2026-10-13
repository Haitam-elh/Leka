/**
 * Facturation: its plan and its AI credits — used, left, what to do once
 * spent; no invoice said so; the consumption counted — what the workspace
 * holds, what it did this month against the last.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

vi.mock("next/navigation", () => ({
  usePathname: () => "/billing",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/billing", async (original) => ({
  ...(await original<typeof import("@/lib/billing")>()),
  billing: {
    usage: async () => ({
      month_start: "2026-10-01T00:00:00Z",
      members: 3,
      sources: 5,
      sources_connected: 4,
      entities: 1240,
      intentions: 12,
      analyses: 14,
      capability_runs: 96,
      plans: 2,
      previous: { intentions: 8, analyses: 9, capability_runs: 60 },
    }),
    credits: async () => credits,
  },
}));

let credits: Record<string, unknown> = {};

function held(over: Record<string, unknown> = {}) {
  return {
    plan: "growth",
    plan_since: "2026-10-02T09:00:00Z",
    monthly: 10000,
    packs: 0,
    allowance: 10000,
    used: 2400.4,
    remaining: 7599.6,
    percent: 24,
    period_start: "2026-10-01T00:00:00Z",
    period_end: "2026-11-01T00:00:00Z",
    state: "ok",
    warn_at: [80, 100],
    enforced: true,
    credit_usd: 0.01,
    ...over,
  };
}

const { BillingScreen } = await import("@/components/billing/billing-page");

function screenOf() {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <BillingScreen />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

it("says its plan, its credits, and the consumption counted", async () => {
  credits = held();
  screenOf();
  expect(await screen.findByTestId("billing-credits-used")).toHaveTextContent("2 400 utilisés sur 10 000");
  expect(screen.getByTestId("billing-plan")).toHaveTextContent("Growth");
  expect(screen.getByTestId("billing-credits-remaining")).toHaveTextContent("7 599 restants jusqu'au 1 novembre 2026");
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "24");
  expect(screen.queryByTestId("billing-credits-state")).toBeNull();
  expect(screen.getByTestId("billing-sources")).toHaveTextContent("4");
  expect(screen.getByTestId("billing-sources")).toHaveTextContent("sur 5 déclarée(s)");
  expect(screen.getByTestId("billing-entities")).toHaveTextContent("1 240");
  expect(screen.getByTestId("billing-row-capability_runs")).toHaveTextContent("96");
  expect(screen.getByTestId("billing-row-capability_runs")).toHaveTextContent("60 le mois dernier");
  expect(screen.getByTestId("billing-invoices")).toHaveTextContent("Aucune facture");
});

it("near the limit, says so and how to go on", async () => {
  credits = held({ plan: "free", plan_since: null, allowance: 200, monthly: 200, used: 170, remaining: 30, percent: 85, state: "warning" });
  screenOf();
  expect(await screen.findByTestId("billing-credits-state")).toHaveTextContent("Vous approchez de la limite");
  expect(screen.getByTestId("billing-plan")).toHaveTextContent("Offre de départ");
});

it("spent, says LEKA's AI is paused until the month ends — never billed past", async () => {
  credits = held({ packs: 1000, allowance: 11000, used: 11000, remaining: 0, percent: 100, state: "exhausted" });
  screenOf();
  const said = await screen.findByTestId("billing-credits-state");
  expect(said).toHaveTextContent("suspendue jusqu'au 1 novembre 2026");
  expect(said).toHaveTextContent("Aucun dépassement n'est jamais facturé");
  expect(screen.getByTestId("billing-credits-remaining")).toHaveTextContent("dont 1 000 ajoutés ce mois-ci");
});
