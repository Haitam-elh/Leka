/**
 * Facturation: no paid plan nor invoice said so; the consumption counted —
 * what the workspace holds, what it did this month against the last.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

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
  },
}));

const { BillingScreen } = await import("@/components/billing/billing-page");

it("says no paid plan, and the consumption counted", async () => {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <BillingScreen />
      </LocaleProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByTestId("billing-plan")).toHaveTextContent("Aucune offre payante active");
  expect(screen.getByTestId("billing-sources")).toHaveTextContent("4");
  expect(screen.getByTestId("billing-sources")).toHaveTextContent("sur 5 déclarée(s)");
  expect(screen.getByTestId("billing-entities")).toHaveTextContent("1 240");
  expect(screen.getByTestId("billing-row-capability_runs")).toHaveTextContent("96");
  expect(screen.getByTestId("billing-row-capability_runs")).toHaveTextContent("60 le mois dernier");
  expect(screen.getByTestId("billing-invoices")).toHaveTextContent("Aucune facture");
});
