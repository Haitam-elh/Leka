/**
 * The home's blocks (LEKA-456), the question their focus (LEKA-470):
 * « Mon environnement » claims only what is measured — never « Stable » by
 * default — reduced to its state and its last read, the real moment; the
 * way to the analyses asked; the agents on sale, dense, each its state in
 * words, a price and a « + » only where one is to pay; the bundles' cards,
 * no banner; the latest analyses, each to its page.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const env = vi.hoisted(() => ({ data: undefined as unknown }));
const offers = vi.hoisted(() => ({ data: undefined as unknown }));
const list = vi.hoisted(() => ({ value: { isPending: false, data: undefined as unknown } }));
vi.mock("@/lib/environment-queries", () => ({ useEnvironment: () => env }));
const listed = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/sources-queries", () => ({ useSources: () => listed }));
const buy = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
const permissions = vi.hoisted(() => ({ value: [] as string[] }));
vi.mock("@/lib/billing-queries", () => ({ useAddOns: () => offers, useBuy: () => buy }));
const catalogue = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/capabilities-queries", () => ({ useCapabilities: () => catalogue }));
vi.mock("@/components/shell/shell-provider", () => ({ usePermissions: () => permissions.value }));
vi.mock("@/lib/intentions/queries", () => ({ useIntentions: () => list.value }));
vi.mock("@/components/intentions/intentions-list", () => ({
  StatusPill: ({ status }: { status: string }) => <span>{status}</span>,
}));

const home = await import("@/components/overview/home-sections");
const { AgentsSection, EnvironmentCard, HistoryLink, HomeBundles, LatestAnalyses } = home;

const show = (node: React.ReactNode) =>
  render(
    <LocaleProvider>
      <ConfirmProvider>{node}</ConfirmProvider>
    </LocaleProvider>,
  );
const none = { unavailable: 0, degraded: 0, stale: 0, unknown: 0, not_covered: 0, operational: 0 };
const READ_AT = new Date(Date.now() - 7 * 60_000);
const measured = {
  services: 12,
  services_operational: 12,
  services_unknown: 0,
  incidents_open: 0,
  states: { ...none, operational: 15 },
  sources: [{}, {}, {}],
  freshness: { late: false, last_read_at: READ_AT.toISOString(), every_minutes: 60 },
};

describe("Mon environnement", () => {
  it("its state as measured and its last read — the moment and how long ago, nothing else", () => {
    env.data = measured;
    show(<EnvironmentCard />);
    const card = screen.getByTestId("home-environment");
    expect(screen.getByTestId("home-health")).toHaveTextContent("Stable");
    expect(card).toHaveTextContent("100 %");
    const sync = screen.getByTestId("home-last-sync");
    expect(sync).toHaveTextContent("Dernière synchronisation");
    expect(sync).toHaveTextContent("Il y a 7 min");
    // The moment itself, as the API gave it — never made up.
    expect(within(sync).getByText((_, node) => node?.tagName === "TIME")).toHaveAttribute(
      "datetime",
      READ_AT.toISOString(),
    );
    // Reduced (LEKA-470): no counter of sources or services any more.
    expect(card).not.toHaveTextContent(/sources? connectées?/);
    expect(card).not.toHaveTextContent(/services analysés/);
    expect(within(card).getByRole("link", { name: "Mon environnement" })).toHaveAttribute("href", "/environment");
  });

  it("says no source was read rather than a date it does not have", () => {
    env.data = { ...measured, freshness: null };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-last-sync")).toHaveTextContent("Aucune source lue pour l'instant");
    expect(screen.getByTestId("home-last-sync").querySelector("time")).toBeNull();
  });

  it("says what the page says (LEKA-468): its services operational, the rest unknown, never « 100 % Stable »", () => {
    // The ticket's workspace: every service operational, yet the page counts
    // 67 % — databases and resources unknown, one not covered.
    env.data = { ...measured, services: 3, services_operational: 3, states: { ...none, operational: 12, unknown: 5, not_covered: 1 } };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Partiellement vérifié");
    expect(screen.getByTestId("home-environment")).toHaveTextContent("67 %");
    expect(screen.getByTestId("home-environment")).not.toHaveTextContent("Stable");
  });

  it("calls a degraded thing trouble even without an open incident", () => {
    env.data = { ...measured, states: { ...none, operational: 9, degraded: 1 } };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Incident en cours");
  });

  it("never claims a figure it does not have", () => {
    env.data = { ...measured, sources: [], services: 0, services_operational: 0 };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Non vérifié");
    expect(screen.getByTestId("home-environment")).not.toHaveTextContent("%");
  });
});

describe("the analyses already asked", () => {
  it("« Historique des analyses » opens the list of every intention", () => {
    show(<HistoryLink />);
    expect(screen.getByRole("link", { name: "Historique des analyses" })).toHaveAttribute("href", "/intentions");
  });

  it("says a source in error, as Mon environnement does, and leads to Sources", () => {
    env.data = measured;
    listed.data = [{ status: "error" }];
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-sources-failing")).toHaveTextContent("1 source en erreur — voir les sources");
    expect(screen.getByTestId("home-sources-failing")).toHaveAttribute("href", "/sources");
    listed.data = undefined;
  });
});

describe("what is on sale", () => {
  const agent = (key: string, extra: Record<string, unknown> = {}) => ({
    key,
    title: key,
    summary: "s",
    category: "code",
    tier: "standard",
    monthly_price: 900,
    included: false,
    owned: false,
    why: "not_owned",
    ...extra,
  });

  it("one row of six at most — as many as its columns — each its state in words, the way to them all", () => {
    offers.data = {
      available: true,
      every: false,
      minimum_plan: "starter",
      agents: "abcdefghijklm".split("").map((key) => agent(key)),
      bundles: [{}, {}],
    };
    show(<AgentsSection />);
    const cards = screen.getAllByTestId("home-agent");
    expect(cards).toHaveLength(6);
    // One row at every width: two on a phone, three, four, six.
    expect(cards[2]).toHaveClass("max-md:nth-[n+3]:hidden");
    expect(cards[3]).toHaveClass("md:max-lg:nth-[n+4]:hidden");
    expect(cards[4]).toHaveClass("lg:max-xl:nth-[n+5]:hidden");
    expect(screen.getAllByTestId("agent-state")[0]).toHaveTextContent("Option payante");
    expect(screen.getByRole("link", { name: /Voir tous les agents et bundles/ })).toHaveAttribute(
      "href",
      "/capabilities",
    );
    expect(screen.getByTestId("home-agents-grid")).toHaveClass("xl:grid-cols-6", "grid-cols-2");
  });

  it("recommends what works with the connected sources first, saying why (LEKA-488)", () => {
    offers.data = {
      available: true,
      every: false,
      minimum_plan: "starter",
      agents: [agent("jira-reader"), agent("plain", { included: true, owned: true }), agent("github-reader")],
      bundles: [],
    };
    catalogue.data = [
      { key: "jira-reader", sources: [{ any_of: ["jira"], connected: false }] },
      { key: "plain", sources: [] },
      { key: "github-reader", sources: [{ any_of: ["github"], connected: true }] },
    ];
    show(<AgentsSection />);
    const cards = screen.getAllByTestId("home-agent");
    expect(cards.map((c) => c.dataset.key)).toEqual(["github-reader", "plain", "jira-reader"]);
    expect(within(cards[0]).getByTestId("home-agent-fit")).toHaveTextContent(
      "Fonctionne avec vos sources connectées",
    );
    expect(within(cards[1]).queryByTestId("home-agent-fit")).toBeNull();
    expect(within(cards[2]).getByTestId("home-agent-fit")).toHaveTextContent("Une source à connecter");
    catalogue.data = undefined;
  });

  it("each card opens its agent; its action by its state — a purchase confirmed, its price said (LEKA-497)", async () => {
    offers.data = {
      available: true,
      every: false,
      minimum_plan: "starter",
      agents: [
        agent("option", { title: "Revue de code" }),
        agent("included", { included: true, owned: true }),
        agent("upgrade", { why: "plan_required" }),
      ],
      bundles: [],
    };
    const user = userEvent.setup();
    const { unmount } = show(<AgentsSection />);
    const cards = () => Object.fromEntries(screen.getAllByTestId("home-agent").map((c) => [c.dataset.key, c]));
    expect(within(cards().option).getByTestId("home-agent-open")).toHaveAttribute("href", "/capabilities/option");
    expect(within(cards().included).getByTestId("agent-open")).toHaveTextContent("Ouvrir l'agent");
    expect(within(cards().upgrade).getByTestId("agent-upgrade")).toHaveAttribute("href", "/billing/plans");
    // Who may not pay: never a purchase.
    expect(screen.queryByTestId("agent-buy")).toBeNull();
    unmount();

    permissions.value = ["workspace:update"];
    show(<AgentsSection />);
    const buying = screen.getByTestId("agent-buy");
    expect(buying).toHaveAccessibleName("Acheter Revue de code");
    await user.click(buying);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/9\s€ HT par mois/);
    // Backing out buys nothing.
    await user.click(within(dialog).getByRole("button", { name: "Annuler" }));
    expect(buy.mutate).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("agent-buy"));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Continuer vers le paiement" }),
    );
    expect(buy.mutate).toHaveBeenCalledWith({ kind: "agent", key: "option" }, expect.anything());
    permissions.value = [];
  });

  it("a price only where there is one to pay: never on an included or bought agent", () => {
    offers.data = {
      available: true,
      every: false,
      minimum_plan: "growth",
      agents: [
        agent("included", { included: true, owned: true }),
        agent("owned", { owned: true, why: null }),
        agent("upgrade", { why: "plan_required" }),
        agent("option"),
      ],
      bundles: [],
    };
    show(<AgentsSection />);
    const said = Object.fromEntries(
      screen.getAllByTestId("home-agent").map((card) => [
        card.dataset.key,
        [
          within(card).getByTestId("agent-state").textContent,
          within(card).queryByTestId("home-agent-price")?.textContent ?? null,
        ],
      ]),
    );
    expect(said.included).toEqual(["Inclus dans votre plan", null]);
    expect(said.owned).toEqual(["Déjà acheté", null]);
    // Its price for whoever has it to pay — a plan above, here (LEKA-497).
    expect(said.upgrade?.[0]).toBe("Upgrade requis");
    expect(said.upgrade?.[1]).toMatch(/^9\s€ \/ mois HT$/);
    expect(said.option?.[0]).toBe("Option payante");
    expect(said.option?.[1]).toMatch(/^9\s€ \/ mois HT$/);
  });

  it("says nothing while nothing is on sale", () => {
    offers.data = { available: false, every: false, agents: [agent("a")], bundles: [] };
    const { container } = show(<AgentsSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it("no bundle banner any more: the bundles' own cards, lower on the page", () => {
    expect("BundlesBanner" in home).toBe(false);
    offers.data = {
      available: true,
      every: false,
      minimum_plan: "starter",
      runs_agents: true,
      agents: [agent("a")],
      bundles: [
        {
          key: "engineering",
          name: { fr: "Engineering", en: "Engineering" },
          value: null,
          monthly_price: 5900,
          alone_price: null,
          discount_percent: null,
          sellable: false,
          members: [],
        },
      ],
    };
    show(<HomeBundles />);
    expect(screen.getByTestId("home-bundles-cards")).toHaveTextContent("Engineering");
    expect(screen.queryByText("Découvrir les bundles")).toBeNull();
  });
});

describe("Dernières analyses", () => {
  it("lists the four latest, each to its page", () => {
    const row = (id: string) => ({ id, title: `T ${id}`, status: "done", updated_at: new Date().toISOString(), summary: null });
    list.value = { isPending: false, data: { pages: [{ data: ["1", "2", "3", "4", "5"].map(row) }] } };
    show(<LatestAnalyses />);
    const items = screen.getAllByTestId("home-latest-item");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveAttribute("href", "/intentions/1");
    expect(within(items[0]).getByText("T 1")).toBeVisible();
  });
});
