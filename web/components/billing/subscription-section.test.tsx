/**
 * Votre formule (LEKA-431), on Facturation.
 *
 * What these protect: without Stripe, it says payment is not open and links
 * the pricing; with it, each self-service plan at the pricing's price — the
 * launch offer only while the workspace may take it, yearly with its total —
 * and choosing one opens Stripe Checkout; subscribed, the plan, its renewal,
 * a failed payment said, and the portal; back from Stripe, what happened.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { Pricing, Subscription } from "@/lib/subscription";

const api = vi.hoisted(() => ({ read: vi.fn(), pricing: vi.fn(), checkout: vi.fn(), portal: vi.fn() }));
const route = vi.hoisted(() => ({ search: "" }));
vi.mock("@/lib/subscription", async (original) => ({
  ...(await original<typeof import("@/lib/subscription")>()),
  subscription: api,
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(route.search) }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { SubscriptionSection } = await import("@/components/billing/subscription-section");

const quote = (plan: string, interval: "month" | "year", list: number, monthly: number, charged: number, discount: "launch" | "annual" | null) => ({
  plan,
  interval,
  list_monthly: list,
  discount,
  percent: discount === "launch" ? 30 : discount === "annual" ? 20 : 0,
  monthly,
  charged,
  for_months: discount === "launch" ? 12 : null,
  then_monthly: discount === "launch" ? list : null,
});

const words = { fr: "x", en: "x" };
const plan = (key: string, name: string, list: number, credits: number | null, recommended = false) => ({
  key,
  name,
  self_service: key !== "enterprise",
  recommended,
  audience: words,
  value: words,
  quotes:
    key === "enterprise" || key === "free"
      ? key === "free"
        ? [quote(key, "month", 0, 0, 0, null)]
        : []
      : [
          quote(key, "month", list, Math.round(list * 0.7), Math.round(list * 0.7), "launch"),
          quote(key, "year", list, Math.round(list * 0.8), Math.round(list * 0.8) * 12, "annual"),
        ],
  ai_credits_per_month: credits,
  ai_credits_provisional: true,
  ai_credits_contractual: key === "enterprise",
  managed_llm: true,
  own_llm: key === "enterprise",
});

const PRICING = {
  version: "2026-10-10",
  currency: "EUR",
  annual_discount_percent: 20,
  launch_offer: { percent: 30, months: 12, open: true, ends_on: null, stacks_with_annual: false },
  core_agents: [],
  plans: [
    plan("free", "Free", 0, 100),
    plan("starter", "Starter", 5900, 500),
    plan("growth", "Growth", 17900, 2000, true),
    plan("business", "Business", 59900, 8000),
    plan("enterprise", "Enterprise", 0, null),
  ],
  add_ons_available: false,
  capacity_any_time: true,
  automatic_overage: false,
  capacity_packs_available: false,
  booking: { url: null, contact_url: "https://leka-core.com/demo.html?type=enterprise" },
} as unknown as Pricing;

function account(overrides: Partial<Subscription> = {}): Subscription {
  return {
    available: true,
    plan: "free",
    interval: null,
    status: null,
    current_period_end: null,
    cancel_at_period_end: false,
    launch_offer_available: true,
    last_invoice: null,
    has_customer: false,
    ...overrides,
  };
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <SubscriptionSection />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  route.search = "";
  api.pricing.mockResolvedValue(PRICING);
  api.checkout.mockResolvedValue({ url: "https://checkout.stripe.test/cs_1", quote: null });
  api.portal.mockResolvedValue({ url: "https://billing.stripe.test/p_1" });
});

describe("your plan", () => {
  it("says payment is not open without Stripe", async () => {
    api.read.mockResolvedValue(account({ available: false }));
    show();
    expect(await screen.findByTestId("billing-not-available")).toHaveTextContent("pas encore ouvert");
  });

  it("offers each plan at the pricing's price, and opens Stripe Checkout", async () => {
    api.read.mockResolvedValue(account());
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const user = userEvent.setup();
    show();
    const growth = await screen.findByText("Growth").then((el) => el.closest("li") as HTMLElement);
    expect(screen.getAllByTestId("billing-plan").map((li) => li.dataset.plan)).toEqual(["starter", "growth", "business"]);
    expect(growth).toHaveTextContent("125,30");
    expect(growth).toHaveTextContent("pendant 12 mois, puis 179");
    await user.click(screen.getByRole("radio", { name: /Annuelle/ }));
    expect(growth).toHaveTextContent("143,20");
    expect(growth).toHaveTextContent("1 718,40");
    await user.click(within(growth).getByRole("button", { name: "Choisir Growth" }));
    await waitFor(() => expect(api.checkout).toHaveBeenCalledWith("growth", "year"));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.test/cs_1"));
    vi.unstubAllGlobals();
  });

  it("no launch offer once the workspace has had it", async () => {
    api.read.mockResolvedValue(account({ launch_offer_available: false }));
    show();
    const growth = await screen.findByText("Growth").then((el) => el.closest("li") as HTMLElement);
    expect(growth).toHaveTextContent("179");
    expect(growth).not.toHaveTextContent("pendant 12 mois");
  });

  it("subscribed: the plan, a failed payment said, the portal", async () => {
    api.read.mockResolvedValue(
      account({ plan: "growth", interval: "month", status: "past_due", current_period_end: "2026-11-10T00:00:00Z", has_customer: true }),
    );
    const user = userEvent.setup();
    show();
    const subscribed = await screen.findByTestId("billing-subscribed");
    expect(subscribed).toHaveTextContent("Formule Growth, facturation mensuelle.");
    expect(subscribed).toHaveTextContent("Prochain renouvellement le 10 novembre 2026.");
    expect(within(subscribed).getByRole("alert")).toHaveTextContent("Stripe réessaie");
    await user.click(within(subscribed).getByRole("button", { name: "Gérer l'abonnement" }));
    await waitFor(() => expect(api.portal).toHaveBeenCalled());
  });

  it("back from Stripe, says what happened", async () => {
    route.search = "checkout=cancelled";
    api.read.mockResolvedValue(account());
    show();
    expect(await screen.findByTestId("billing-checkout-back")).toHaveTextContent("rien n'a été facturé");
  });
});
