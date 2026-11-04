/**
 * A bundle's card and its page (LEKA-531).
 *
 * What these protect: every card one way in, to its own bundle's page — no
 * button of its own besides the marketplace's selection box; the page
 * explains it — its promise, for whom, the problem, three reasons, when it
 * helps — and lists every agent with its role, each to its own page; its
 * price and cadence are the API's, the same on the card and the page; a
 * saving is said only where computed from every agent's price, never
 * otherwise; choosing it is said, confirmed, then the purchase every bundle
 * takes; owned, it says so and offers no second purchase; on Free, a plan
 * first; not built, coming soon; who may not pay is told whom to ask; under
 * an Enterprise contract, nothing to buy. An unknown bundle, a failed read:
 * said, with the way back.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import type { AddOns, BundleOffer } from "@/lib/billing";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const route = vi.hoisted(() => ({ key: "engineering" }));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "workspace:update"] }));
const sold = vi.hoisted(() => ({ addOns: vi.fn(), entitlements: vi.fn(), buy: vi.fn() }));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => `/capabilities/bundles/${route.key}`,
  useParams: () => ({ bundleKey: route.key }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentWorkspace: () => ({ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }),
}));
vi.mock("@/lib/billing", async (original) => ({
  ...(await original<typeof import("@/lib/billing")>()),
  billing: sold,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));

const { BundleScreen } = await import("@/components/capabilities/bundle-page");
const { Bundles } = await import("@/components/capabilities/offers");

function agent(key: string, title: string, price: number, market = "development") {
  return {
    key,
    title,
    summary: "",
    category: "development",
    tier: "standard",
    monthly_price: price,
    owned: false,
    why: "not_owned" as string | null,
    bundles: [],
    included: false,
    market,
  };
}

function bundle(key: string, name: string, more: Partial<BundleOffer> = {}): BundleOffer {
  return {
    key,
    name: { fr: name, en: name },
    value: { fr: `${name}, en un mot.`, en: `${name}, in a word.` },
    agents: [],
    monthly_price: 4900,
    alone_price: null,
    discount_percent: null,
    owned: false,
    sellable: true,
    members: [],
    ...more,
  };
}

function offers(more: Partial<AddOns> = {}, bundles?: BundleOffer[]): AddOns {
  return {
    available: true,
    provisional: false,
    currency: "EUR",
    interval: "month",
    minimum_plan: "starter",
    plan: "growth",
    runs_agents: true,
    every: false,
    dedicated: [],
    agents: [
      agent("codebase-explorer", "Exploration du code", 1500),
      agent("code-review", "Revue de code", 2500),
      agent("test-analysis", "Analyse des tests", 2600),
    ],
    bundles: bundles ?? [
      bundle("engineering", "Engineering", {
        agents: ["codebase-explorer", "code-review", "test-analysis"],
        alone_price: 6600,
        discount_percent: 26,
        members: [
          { key: "codebase-explorer", name: "Codebase Explorer", agent: "codebase-explorer", monthly_price: 1500 },
          { key: "code-reviewer", name: "Code Reviewer", agent: "code-review", monthly_price: 2500 },
          { key: "test-strategist", name: "Test Strategist", agent: "test-analysis", monthly_price: 2600 },
        ],
      }),
      bundle("ship-safe", "Ship Safe", {
        monthly_price: 7900,
        members: [
          { key: "code-reviewer", name: "Code Reviewer", agent: "code-review", monthly_price: 2500 },
          { key: "migration-planner", name: "Migration Planner", agent: "migration-planning", monthly_price: null },
        ],
      }),
      bundle("frontend-craft", "Frontend Craft", {
        monthly_price: 2900,
        sellable: false,
        members: [{ key: "motion", name: "Motion Specialist", agent: null, monthly_price: null }],
      }),
    ],
    ...more,
  } as AddOns;
}

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>{node}</ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  route.key = "engineering";
  permissions.value = ["workspace:read", "workspace:update"];
  sold.addOns.mockResolvedValue(offers());
  sold.entitlements.mockResolvedValue([]);
});

describe("a bundle's card", () => {
  it("is one way in, to its own page, the same price as there", async () => {
    show(<Bundles />);
    const cards = await screen.findAllByTestId("bundle");
    expect(cards.map((card) => card.dataset.key)).toEqual(["engineering", "ship-safe", "frontend-craft"]);
    for (const card of cards) {
      const [open, ...more] = within(card).getAllByRole("link");
      expect(more).toEqual([]);
      expect(open).toHaveAttribute("href", `/capabilities/bundles/${card.dataset.key}`);
      expect(within(card).queryAllByRole("button")).toEqual([]);
      expect(card).toHaveClass("cursor-pointer", "has-[a:focus-visible]:ring-3");
    }
    expect(within(cards[0]).getByTestId("bundle-price")).toHaveTextContent(/49\s€/);
    expect(within(cards[2]).getByTestId("bundle-state")).toHaveTextContent("Bientôt disponible");
  });
});

describe("a bundle's page", () => {
  it("explains it: its promise, for whom, the problem, three reasons, when it helps", async () => {
    show(<BundleScreen />);
    expect(await screen.findByRole("heading", { level: 1, name: "Engineering" })).toBeVisible();
    expect(screen.getByTestId("bundle-promise")).toHaveTextContent("Concevez, relisez et testez votre code");
    expect(screen.getByTestId("bundle-audience")).toHaveTextContent("Pour qui : Les équipes de développement");
    expect(screen.getByTestId("bundle-problem")).toHaveTextContent("Une revue faite trop vite");
    expect(screen.getAllByTestId("bundle-benefit")).toHaveLength(3);
    expect(screen.getAllByTestId("bundle-use-case")).toHaveLength(3);
    expect(screen.getByTestId("bundle-back")).toHaveAttribute("href", "/capabilities#bundles");
  });

  it("lists every agent with its role, each to its own page", async () => {
    show(<BundleScreen />);
    const agents = await screen.findAllByTestId("bundle-agent");
    expect(agents.map((a) => a.dataset.key)).toEqual(["codebase-explorer", "code-review", "test-analysis"]);
    expect(within(agents[1]).getByRole("link", { name: "Revue de code" })).toHaveAttribute(
      "href",
      "/capabilities/code-review",
    );
    // Its role, from its own product page — never an empty line.
    for (const each of agents) expect(each.querySelector("p")?.textContent?.length).toBeGreaterThan(20);
    expect(within(agents[0]).getByTestId("bundle-agent-price")).toHaveTextContent(/15\s€ HT par mois/);
  });

  it("says its price and cadence as the API does, a saving only where computed", async () => {
    show(<BundleScreen />);
    const side = await screen.findByTestId("bundle-choose");
    expect(side).toHaveTextContent(/49\s€\s?HT par mois/);
    expect(within(side).getByTestId("bundle-cadence")).toHaveTextContent("Facturé chaque mois");
    expect(side).toHaveTextContent("−26 %");
    expect(screen.getByTestId("bundle-separately")).toHaveTextContent(/66\s€/);
    expect(screen.getByTestId("bundle-saving-said")).toHaveTextContent(
      /Vous économisez 17\s€ HT par mois, soit 26 %\./,
    );
  });

  it("never claims a saving it cannot compute", async () => {
    route.key = "ship-safe";
    show(<BundleScreen />);
    expect(await screen.findByTestId("bundle-saving-said")).toHaveTextContent(
      "L'économie n'est pas affichée",
    );
    expect(screen.queryByTestId("bundle-separately")).toBeNull();
    expect(screen.getByTestId("bundle-choose")).not.toHaveTextContent("%");
  });

  it("is chosen once confirmed, its price and cadence said — the purchase every bundle takes", async () => {
    const user = userEvent.setup();
    sold.buy.mockReturnValue(new Promise(() => {}));
    show(<BundleScreen />);
    const cta = within(await screen.findByTestId("bundle-choose")).getByTestId("bundle-cta");
    expect(cta).toHaveAttribute("data-cta", "buy");
    await user.click(cta);
    let dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Choisir Engineering ?");
    expect(dialog).toHaveTextContent(/49\s€ HT par mois, facturé chaque mois/);
    await user.click(within(dialog).getByRole("button", { name: "Annuler" }));
    expect(sold.buy).not.toHaveBeenCalled();
    await user.click(cta);
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Continuer vers le paiement" }));
    await waitFor(() => expect(sold.buy).toHaveBeenCalledWith({ kind: "bundle", key: "engineering" }));
  });

  it("owned: says it, offers no second purchase, the way to manage it", async () => {
    sold.addOns.mockResolvedValue(
      offers({}, [bundle("engineering", "Engineering", { owned: true, members: [] })]),
    );
    show(<BundleScreen />);
    const cta = within(await screen.findByTestId("bundle-choose")).getByTestId("bundle-cta");
    expect(cta).toHaveAttribute("data-cta", "owned");
    expect(cta).toHaveTextContent("Actif dans votre espace");
    expect(within(cta).getByRole("link", { name: "Gérer vos abonnements" })).toHaveAttribute("href", "/billing");
    expect(screen.queryByRole("button", { name: "Choisir ce bundle" })).toBeNull();
  });

  it("on Free a plan first, not built coming soon, without the right whom to ask", async () => {
    sold.addOns.mockResolvedValue(offers({ plan: "free", runs_agents: false }));
    const { unmount } = show(<BundleScreen />);
    let cta = within(await screen.findByTestId("bundle-choose")).getByTestId("bundle-cta");
    expect(cta).toHaveAttribute("data-cta", "upgrade");
    expect(cta).toHaveAttribute("href", "/billing/plans");
    expect(screen.getByTestId("bundle-choose")).toHaveTextContent("à partir de la formule Starter");
    unmount();

    sold.addOns.mockResolvedValue(offers());
    route.key = "frontend-craft";
    const soon = show(<BundleScreen />);
    cta = within(await screen.findByTestId("bundle-choose")).getByTestId("bundle-cta");
    expect((cta as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("bundle-choose")).toHaveTextContent("encore en préparation");
    soon.unmount();

    route.key = "engineering";
    permissions.value = ["workspace:read"];
    show(<BundleScreen />);
    cta = within(await screen.findByTestId("bundle-choose")).getByTestId("bundle-cta");
    expect((cta as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("bundle-choose")).toHaveTextContent("Seul un administrateur de l'espace peut l'acheter.");
  });

  it("under an Enterprise contract: nothing to buy, no price", async () => {
    sold.addOns.mockResolvedValue(offers({ plan: "enterprise" }));
    show(<BundleScreen />);
    const choose = await screen.findByTestId("bundle-choose");
    expect(within(choose).getByTestId("bundle-cta")).toHaveAttribute("data-cta", "contract");
    expect(choose).not.toHaveTextContent("€");
    expect(screen.queryByTestId("bundle-pricing")).toBeNull();
  });

  it("an unknown bundle, a failed read: said, with the way back", async () => {
    route.key = "nope";
    const { unmount } = show(<BundleScreen />);
    expect(await screen.findByText("Ce bundle n'existe pas, ou n'est plus proposé.")).toBeVisible();
    unmount();

    route.key = "engineering";
    // A refusal, not retried: the page says it at once.
    sold.addOns.mockRejectedValue(new ApiError(403, "/billing/add-ons", "Forbidden"));
    show(<BundleScreen />);
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByTestId("bundle-back")).toBeVisible();
  });
});
