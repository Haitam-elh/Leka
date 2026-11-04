/**
 * The AI capacity's prompt (LEKA-527).
 *
 * What these protect: nothing under 90 %, nor on the plans page; at 90 %,
 * the usage exact and said in words besides the bar, what 100 % will do,
 * what AI credits are and where they are detailed, the next plan with its
 * credits and price as the server gives them (launch offer, cadence) and
 * what it adds; the plan opened on the plans page, never said bought before
 * the payment; « Plus tard » puts that threshold aside. At 100 %, spent and
 * what that does under the actual policy, the subscription's cadence kept,
 * « Fermer ». Above the plans sold, LEKA's sales; under a contract, the day
 * the credits come back; one who may not pay asks the admins, once.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CreditPlan, CreditPrompt as Prompt } from "@/lib/billing";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({ prompt: vi.fn(), dismiss: vi.fn(), ask: vi.fn(), path: "/overview" }));
vi.mock("@/lib/billing", async (original) => {
  const real = await original<typeof import("@/lib/billing")>();
  return {
    ...real,
    billing: { ...real.billing, creditPrompt: api.prompt, dismissCreditPrompt: api.dismiss, askUpgrade: api.ask },
  };
});
vi.mock("next/navigation", () => ({ usePathname: () => api.path }));

const { CreditPrompt } = await import("@/components/billing/credit-prompt");

const plan = (key: string, name: string, more: Partial<CreditPlan>): CreditPlan => ({
  key,
  name,
  credits: null,
  self_service: true,
  interval: "month",
  monthly: null,
  list_monthly: null,
  charged: null,
  discount: null,
  percent: 0,
  for_months: null,
  ...more,
});

const FREE = plan("free", "Free", { credits: 200, monthly: 0, list_monthly: 0, charged: 0 });
const STARTER = plan("starter", "Starter", {
  credits: 2000,
  monthly: 4720,
  list_monthly: 5900,
  charged: 4720,
  discount: "launch",
  percent: 20,
  for_months: 12,
});

// Noon: the same day wherever the test runs.
const NEAR: Prompt = {
  threshold: 90,
  used: 182.4,
  allowance: 200,
  remaining: 17.6,
  percent: 91.2,
  period_start: "2026-11-01T12:00:00Z",
  period_end: "2026-12-01T12:00:00Z",
  enforced: true,
  current: FREE,
  recommended: STARTER,
  more_credits: 1800,
  more_monthly: 5900,
  currency: "EUR",
  path: "upgrade",
  contact_url: "https://leka-core.com/demo.html",
  can_pay: true,
  asked: false,
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <CreditPrompt />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.prompt.mockReset();
  api.dismiss.mockReset();
  api.ask.mockReset();
  api.path = "/overview";
});

describe("the AI credits' prompt", () => {
  it("says nothing under 90 %, nor on the plans page", async () => {
    api.prompt.mockResolvedValue(null);
    const { unmount } = show();
    await waitFor(() => expect(api.prompt).toHaveBeenCalled());
    expect(screen.queryByTestId("credit-prompt")).not.toBeInTheDocument();
    unmount();

    api.prompt.mockResolvedValue(NEAR);
    api.path = "/billing/plans";
    show();
    await waitFor(() => expect(api.prompt).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("credit-prompt")).not.toBeInTheDocument();
  });

  it("at 90 %: the usage in words and bar, the next plan as the server prices it, and put aside for later", async () => {
    const user = userEvent.setup();
    api.prompt.mockResolvedValueOnce(NEAR).mockResolvedValue(null);
    api.dismiss.mockResolvedValue(undefined);
    show();
    expect(await screen.findByTestId("credit-prompt-title")).toHaveTextContent(
      "Il ne reste que 9 % de vos crédits IA du mois",
    );
    expect(screen.getByTestId("credit-prompt-usage")).toHaveTextContent(
      "182 crédits utilisés sur 200 (91 %) 17 restants jusqu'au 1 décembre 2026.",
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "91");
    expect(bar).toHaveAttribute("aria-valuetext", "91 % des crédits IA du mois utilisés");
    expect(screen.getByTestId("credit-prompt-impact")).toHaveTextContent(
      "À 100 %, l'IA de LEKA sera suspendue jusqu'au 1 décembre 2026.",
    );
    const offer = screen.getByTestId("credit-prompt-offer");
    expect(offer).toHaveTextContent(
      "Starter · 2 000 crédits IA par mois · 47,20 € HT par mois les 12 premiers mois (offre de lancement), puis 59 € HT, facturé chaque mois",
    );
    expect(offer).toHaveTextContent(
      "Par rapport à votre formule Free : 1 800 crédits de plus par mois, 59 € HT de plus par mois.",
    );
    // Opened where it is bought, never said bought before the payment.
    expect(offer).toHaveTextContent("La nouvelle formule et ses crédits s'appliquent une fois le paiement confirmé.");
    expect(screen.getByRole("link", { name: "Voir l'offre Starter" })).toHaveAttribute(
      "href",
      "/billing/plans?plan=starter&interval=month",
    );
    expect(screen.getByRole("link", { name: "Voir la consommation" })).toHaveAttribute("href", "/billing");

    await user.click(screen.getByRole("button", { name: "Plus tard" }));
    expect(api.dismiss).toHaveBeenCalledWith(90);
    await waitFor(() => expect(screen.queryByTestId("credit-prompt")).not.toBeInTheDocument());
  });

  it("at 100 %: spent, what that does, the subscription's cadence kept, closed", async () => {
    const user = userEvent.setup();
    api.dismiss.mockResolvedValue(undefined);
    api.prompt.mockResolvedValue({
      ...NEAR,
      threshold: 100,
      used: 10_000,
      allowance: 10_000,
      remaining: 0,
      percent: 100,
      current: plan("growth", "Growth", {
        credits: 10_000,
        interval: "year",
        monthly: 12_530,
        list_monthly: 17_900,
        charged: 150_360,
        discount: "annual",
        percent: 30,
      }),
      recommended: plan("business", "Business", {
        credits: 40_000,
        interval: "year",
        monthly: 41_930,
        list_monthly: 59_900,
        charged: 503_160,
        discount: "annual",
        percent: 30,
      }),
      more_credits: 30_000,
      more_monthly: 29_400,
    });
    show();
    expect(await screen.findByTestId("credit-prompt-title")).toHaveTextContent("Vos crédits IA du mois sont épuisés");
    expect(screen.getByTestId("credit-prompt")).toHaveAttribute("data-threshold", "100");
    expect(screen.getByTestId("credit-prompt-usage")).toHaveTextContent(
      "10 000 crédits utilisés sur 10 000 (100 %) Ils reviennent le 1 décembre 2026.",
    );
    expect(screen.getByTestId("credit-prompt-impact")).toHaveTextContent(
      "L'IA de LEKA est suspendue jusqu'au 1 décembre 2026 : ce qui en a besoin est refusé d'ici là, sauf avec le modèle propre à votre organisation.",
    );
    expect(screen.getByTestId("credit-prompt-offer")).toHaveTextContent(
      "Business · 40 000 crédits IA par mois · 419,30 € HT par mois, soit 5 031,60 € HT facturés chaque année",
    );
    expect(screen.getByTestId("credit-prompt-offer")).toHaveTextContent(
      "Par rapport à votre formule Growth : 30 000 crédits de plus par mois, 294 € HT de plus par mois.",
    );
    expect(screen.getByRole("link", { name: "Voir l'offre Business" })).toHaveAttribute(
      "href",
      "/billing/plans?plan=business&interval=year",
    );
    await user.click(screen.getByRole("button", { name: "Fermer" }));
    expect(api.dismiss).toHaveBeenCalledWith(100);
  });

  it("above the plans sold, LEKA's sales; spent but not enforced, nothing blocked", async () => {
    api.prompt.mockResolvedValue({
      ...NEAR,
      threshold: 100,
      percent: 104,
      enforced: false,
      current: plan("business", "Business", { credits: 40_000, monthly: 59_900, list_monthly: 59_900, charged: 59_900 }),
      recommended: plan("enterprise", "Enterprise", { self_service: false, interval: null }),
      more_credits: null,
      more_monthly: null,
      path: "sales",
    });
    show();
    expect(await screen.findByTestId("credit-prompt-impact")).toHaveTextContent(
      "Rien n'est bloqué pour l'instant, et aucun dépassement n'est jamais facturé.",
    );
    const offer = screen.getByTestId("credit-prompt-offer");
    expect(offer).toHaveTextContent("Enterprise · crédits IA et prix sur devis");
    expect(offer).not.toHaveTextContent("Par rapport à");
    expect(offer).not.toHaveTextContent("paiement confirmé");
    expect(screen.getByRole("link", { name: "Contacter LEKA" })).toHaveAttribute(
      "href",
      "https://leka-core.com/demo.html",
    );
    expect(screen.queryByRole("link", { name: /Voir l'offre/ })).not.toBeInTheDocument();
  });

  it("under a contract: when the credits come back, and whom to ask", async () => {
    api.prompt.mockResolvedValue({ ...NEAR, recommended: null, more_credits: null, more_monthly: null, path: "contract" });
    show();
    expect(await screen.findByTestId("credit-prompt-offer")).toHaveTextContent(
      "Vos crédits IA sont fixés par votre contrat : ils reviennent le 1 décembre 2026. Pour en avoir plus d'ici là, contactez LEKA.",
    );
    expect(screen.getByRole("link", { name: "Contacter LEKA" })).toBeInTheDocument();
  });

  it("one who may not pay asks the admins, once, and is told it is asked", async () => {
    const user = userEvent.setup();
    api.prompt.mockResolvedValue({ ...NEAR, can_pay: false });
    api.ask.mockResolvedValue({ ...NEAR, can_pay: false, asked: true });
    show();
    expect(await screen.findByTestId("credit-prompt-offer")).toHaveTextContent(
      "Changer de formule est réservé aux administrateurs de l'espace.",
    );
    expect(screen.queryByRole("link", { name: /Voir l'offre/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/paiement confirmé/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Demander à un administrateur" }));
    expect(api.ask).toHaveBeenCalledWith(90);
    expect(await screen.findByTestId("credit-prompt-asked")).toHaveTextContent("Demande envoyée à vos administrateurs.");
    expect(screen.queryByRole("button", { name: "Demander à un administrateur" })).not.toBeInTheDocument();
    // Put aside all the same.
    expect(screen.getByRole("button", { name: "Plus tard" })).toBeInTheDocument();
  });
});
