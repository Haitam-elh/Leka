/**
 * The plans compared (LEKA-466).
 *
 * What these protect: the five plans side by side, each with the server's
 * price and quotas; the workspace's plan marked, its button idle; the
 * yearly discount and the launch offer as two choices — the launch offer
 * said only while this workspace may take it; a first plan bought through
 * Checkout, a change once subscribed through Stripe's portal; Enterprise a
 * contact; a member reads, never buys; Billing kept as its own page; alert
 * rules and workflows said to come, never announced as working.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const state = vi.hoisted(() => ({
  plan: "starter" as string | null,
  permissions: ["workspace:read", "workspace:update"],
  subscription: {
    status: null as string | null,
    launch_offer_available: true,
    available: true,
    interval: null as string | null,
  },
  checkout: vi.fn(),
  portal: vi.fn(),
}));

const quote = (interval: "month" | "year", list: number, monthly: number, charged: number, discount: "launch" | "annual" | null) => ({
  interval,
  list_monthly: list,
  monthly,
  charged,
  discount,
  for_months: discount === "launch" ? 12 : null,
  then_monthly: discount === "launch" ? list : null,
  trial_days: null,
  first_charge_on: null,
});
const quotas = (users: number | null, sources: number | null, analyses: number | null, alert_rules: number | null, workflows: number | null, contractual = false) => ({
  users,
  sources,
  analyses,
  alert_rules,
  workflows,
  provisional: true,
  contractual,
});
const plan = (key: string, name: string, extra: Record<string, unknown>) => ({
  key,
  name,
  self_service: key !== "enterprise",
  recommended: key === "growth",
  audience: { fr: "", en: "" },
  value: { fr: "", en: "" },
  quotes: [],
  ai_credits_per_month: 200,
  ai_credits_provisional: true,
  ai_credits_contractual: false,
  managed_llm: true,
  own_llm: key === "enterprise",
  trial_days: null,
  ...extra,
});
const PRICING = {
  version: 1,
  currency: "EUR",
  annual_discount_percent: 30,
  launch_offer: { percent: 20, months: 12, open: true, ends_on: null, stacks_with_annual: false },
  add_ons_available: true,
  automatic_overage: false,
  booking: { url: null, contact_url: "https://leka-core.com/demo.html" },
  plans: [
    plan("free", "Free", { quotas: quotas(1, 3, 10, 0, 0) }),
    plan("starter", "Starter", {
      quotes: [quote("month", 5900, 4720, 4720, "launch"), quote("year", 5900, 4130, 49560, "annual")],
      quotas: quotas(1, 5, 100, 5, 0),
    }),
    plan("growth", "Growth", {
      quotes: [quote("month", 17900, 14320, 14320, "launch"), quote("year", 17900, 12530, 150360, "annual")],
      quotas: quotas(5, 15, 500, 20, 10),
    }),
    plan("business", "Business", {
      quotes: [quote("month", 59900, 47920, 47920, "launch"), quote("year", 59900, 41930, 503160, "annual")],
      quotas: quotas(15, 30, 2000, 100, 50),
    }),
    plan("enterprise", "Enterprise", { quotas: quotas(null, null, null, null, null, true), ai_credits_contractual: true }),
  ],
};

vi.mock("@/lib/subscription-queries", () => ({
  usePricing: () => ({ data: PRICING, isError: false }),
  useSubscription: () => ({ data: state.subscription }),
  usePayment: () => ({
    checkout: { mutate: state.checkout, isPending: false },
    portal: { mutate: state.portal, isPending: false },
  }),
}));
vi.mock("@/lib/billing-queries", () => ({ useCredits: () => ({ data: state.plan ? { plan: state.plan } : undefined }) }));
vi.mock("@/components/shell/shell-provider", async (original) => ({
  ...(await original<typeof import("@/components/shell/shell-provider")>()),
  usePermissions: () => state.permissions,
}));

const { PlansPage } = await import("@/components/billing/plans-page");

afterEach(() => {
  state.plan = "starter";
  state.permissions = ["workspace:read", "workspace:update"];
  state.subscription = { status: null, launch_offer_available: true, available: true, interval: null };
  state.checkout.mockReset();
  state.portal.mockReset();
});

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <PlansPage />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

const card = (key: string) =>
  screen.getAllByTestId("plan-card").find((c) => c.getAttribute("data-plan") === key)!;

describe("the plans compared", () => {
  it("lays the five plans side by side, each with the server's price and quotas", () => {
    show();
    expect(screen.getAllByTestId("plan-card").map((c) => c.getAttribute("data-plan"))).toEqual([
      "free",
      "starter",
      "growth",
      "business",
      "enterprise",
    ]);
    expect(within(card("free")).getByTestId("plan-price")).toHaveTextContent("0 €");
    // The launch offer on monthly, then the price it renews at.
    expect(within(card("growth")).getByTestId("plan-price")).toHaveTextContent("143,20 €");
    expect(within(card("growth")).getByTestId("plan-then")).toHaveTextContent("12 premiers mois, puis 179 €");
    expect(card("growth")).toHaveTextContent("5 utilisateurs inclus");
    expect(card("growth")).toHaveTextContent("500 analyses standard équivalentes / mois");
    expect(card("growth")).toHaveTextContent("Recommandé");
    // Not built yet: said to come.
    expect(card("growth")).toHaveTextContent("20 règles d'alerte(bientôt)");
    expect(within(card("enterprise")).getByTestId("plan-price")).toHaveTextContent("Sur devis");
    expect(screen.getByTestId("plans-launch")).toHaveTextContent("Non cumulable avec la remise annuelle");
  });

  it("yearly: the discount, never the launch offer", async () => {
    const user = userEvent.setup();
    show();
    expect(screen.getByTestId("plans-year")).toHaveTextContent("Annuel : économisez 30 %");
    await user.click(screen.getByTestId("plans-year"));
    expect(within(card("growth")).getByTestId("plan-price")).toHaveTextContent("125,30 €");
    expect(within(card("growth")).getByTestId("plan-then")).toHaveTextContent(/1\s503,60 € HT par an/);
    expect(screen.queryByTestId("plans-launch")).not.toBeInTheDocument();
  });

  it("the launch offer already used: the list price, said so nowhere", () => {
    state.subscription = { status: null, launch_offer_available: false, available: true, interval: null };
    show();
    expect(within(card("growth")).getByTestId("plan-price")).toHaveTextContent("179 €");
    expect(screen.queryByTestId("plans-launch")).not.toBeInTheDocument();
  });

  it("marks the workspace's plan; a first plan through Checkout, Enterprise a contact", async () => {
    const user = userEvent.setup();
    show();
    expect(card("starter")).toHaveAttribute("data-current", "true");
    expect(within(card("starter")).getByTestId("plan-current-action")).toBeDisabled();
    expect(card("starter")).toHaveTextContent("Votre formule");
    await user.click(within(card("growth")).getByTestId("plan-choose"));
    expect(state.checkout).toHaveBeenCalledWith({ plan: "growth", interval: "month" }, expect.anything());
    expect(within(card("enterprise")).getByTestId("plan-contact")).toHaveAttribute(
      "href",
      "https://leka-core.com/demo.html",
    );
    expect(screen.getByRole("link", { name: /Facturation, factures/ })).toHaveAttribute("href", "/billing");
  });

  it("subscribed: the exact plan chosen, confirmed in Stripe — Free its end (LEKA-490)", async () => {
    state.subscription = { status: "active", launch_offer_available: false, available: true, interval: "month" };
    const user = userEvent.setup();
    show();
    await user.click(within(card("business")).getByTestId("plan-choose"));
    // The server opens Stripe on the change to that price, never a second subscription.
    expect(state.checkout).toHaveBeenCalledWith({ plan: "business", interval: "month" }, expect.anything());
    expect(state.portal).not.toHaveBeenCalled();
    await user.click(within(card("free")).getByTestId("plan-choose"));
    expect(state.portal).toHaveBeenCalledWith(true, expect.anything());
  });

  it("subscribed monthly, its own plan bought yearly — never a button greyed out (2026-10-24)", async () => {
    state.subscription = { status: "active", launch_offer_available: false, available: true, interval: "month" };
    const user = userEvent.setup();
    show();
    expect(within(card("starter")).getByTestId("plan-current-action")).toBeDisabled();
    await user.click(screen.getByTestId("plans-year"));
    const yearly = within(card("starter")).getByTestId("plan-switch-interval");
    expect(yearly).toHaveTextContent("Passer à l'annuel");
    await user.click(yearly);
    expect(state.checkout).toHaveBeenCalledWith({ plan: "starter", interval: "year" }, expect.anything());
  });

  it("a card is chosen, never stuck on « Votre formule »: its price and how often it is billed said", async () => {
    const user = userEvent.setup();
    show();
    expect(card("starter")).toHaveAttribute("data-selected", "true");
    await user.click(within(card("growth")).getByTestId("plan-select"));
    expect(card("growth")).toHaveAttribute("data-selected", "true");
    expect(card("starter")).toHaveAttribute("data-selected", "false");
    expect(within(card("growth")).getByTestId("plan-recap")).toHaveTextContent(
      "143,20 € HT par mois, facturé chaque mois",
    );
    await user.click(screen.getByTestId("plans-year"));
    expect(within(card("growth")).getByTestId("plan-recap")).toHaveTextContent(
      /125,30 € HT par mois, soit 1\s503,60 € HT facturés chaque année/,
    );
    // The way back home, as on the other pages.
    expect(screen.getByTestId("back-home")).toBeInTheDocument();
  });

  it("a member reads the plans and never buys", () => {
    state.permissions = ["workspace:read"];
    show();
    expect(screen.queryByTestId("plan-choose")).not.toBeInTheDocument();
    expect(screen.getByText("Seul un administrateur peut changer de formule.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Facturation, factures/ })).not.toBeInTheDocument();
  });
});
