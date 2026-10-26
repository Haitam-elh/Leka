/**
 * An agent's product page (LEKA-471).
 *
 * What these protect: the page says what the agent brings, from its product
 * — never the registry's jargon first — and every fact that changes is the
 * server's: its price, the plans that include it, its state and the action
 * that state allows. Included: use it. Bought: use it, manage it. An option:
 * buy it, for whoever may. On Free: a plan first. Not on sale: never offered,
 * no price. The examples are said to be examples; the registry's details
 * stay below, folded.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CapabilityDetail } from "@/lib/capabilities";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:create"] }));
const sold = vi.hoisted(() => ({ addOns: vi.fn(), entitlements: vi.fn(), buy: vi.fn() }));
const connected = vi.hoisted(() => ({ value: [] as unknown[] }));

vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => ({ id: "me" }),
  useCurrentWorkspace: () => ({ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }),
}));
vi.mock("@/lib/billing", async (original) => ({
  ...(await original<typeof import("@/lib/billing")>()),
  billing: sold,
}));
vi.mock("@/lib/sources-queries", () => ({ useSources: () => ({ data: connected.value }) }));
vi.mock("@/components/demo/demo", () => ({
  ExploreDemoButton: () => <button type="button">Explorer la démonstration</button>,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { AgentProductPage } = await import("@/components/capabilities/agent-product");

const REVIEW = {
  key: "code-review",
  title: "Revue de code",
  summary: "Use when someone asks for a review of a pull request.",
  category: "development",
  kind: "agent",
  version: "1.3.0",
  lifecycle: "active",
  origin: "internal",
  mode: "read_only",
  risk: "low",
  permission: "intention:create",
  inputs: [],
  output: "analysis",
  formats: ["markdown"],
  sources: [{ any_of: ["github", "gitlab", "bitbucket"], connected: true }],
  model: true,
  model_needs: null,
  answering: null,
  goals: [],
  kinds: [],
  entity_types: [],
  examples: ["Fais la revue de la dernière PR de payment-api"],
  available: true,
  reasons: [],
  usage: { runs: 0, previous: 0, failures: 0, average_ms: null },
  history: [],
  events: [],
  days: [],
} as unknown as CapabilityDetail;

type Standing = { included?: boolean; owned?: boolean; why?: string | null; plan?: string; from?: string | null };

function offers({ included = false, owned = false, why = "not_owned", plan = "starter", from = "starter" }: Standing) {
  const agent = (key: string, title: string, market: string, tier: string, price: number) => ({
    key,
    title,
    summary: `${title}.`,
    category: "development",
    tier,
    monthly_price: price,
    owned: false,
    why: "not_owned",
    bundles: [],
    reference: null,
    included: false,
    market,
    included_from: "growth",
  });
  return {
    available: true,
    provisional: true,
    currency: "EUR",
    minimum_plan: "starter",
    plan,
    runs_agents: plan !== "free",
    every: false,
    agents: [
      {
        ...agent("code-review", "Revue de code", "architecture", "standard", 900),
        owned,
        included,
        why,
        included_from: from,
      },
      agent("codebase-explorer", "Exploration du code", "architecture", "standard", 900),
      agent("test-analysis", "Analyse des tests", "testing", "standard", 900),
      agent("security-review", "Revue de sécurité", "security", "expert", 2500),
      agent("application-architecture", "Architecte applicatif", "architecture", "expert", 2500),
      agent("data-analysis", "Analyse des données", "performance", "specialized", 1500),
    ],
    bundles: [],
  };
}

function show(capability: CapabilityDetail = REVIEW) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <AgentProductPage
          capability={capability}
          use={<div data-testid="run-form" />}
          technical={<div data-testid="capability-inputs">parcours</div>}
        />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

const cta = () => within(screen.getByTestId("agent-choose")).getByTestId("agent-cta");

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "intention:create"];
  connected.value = [{ type: "github", status: "active", sync_status: "succeeded", last_sync_at: "2026-10-16T08:00:00Z" }];
  sold.entitlements.mockResolvedValue([]);
});

describe("an agent's product page", () => {
  it("says what it brings — its promise, its benefits, what it does, how, its limits — never its registry first", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "business" }));
    show();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Revue de code");
    expect(screen.getByTestId("agent-promise")).toHaveTextContent(
      "Une revue de chaque pull request : ce qu'elle touche, ce qu'elle risque et qui devrait la relire",
    );
    expect(screen.getAllByTestId("agent-benefit")).toHaveLength(3);
    expect(within(screen.getByTestId("agent-feature-list")).getAllByRole("listitem").length).toBeGreaterThanOrEqual(5);
    const how = within(screen.getByTestId("agent-how")).getAllByRole("listitem");
    expect(how).toHaveLength(3);
    expect(how[1]).toHaveTextContent("GitHub, GitLab, Bitbucket");
    expect(screen.getByTestId("agent-limits")).toHaveTextContent("Lecture seule : il ne modifie rien dans vos outils.");
    // The registry's details: below, folded.
    const technical = screen.getByTestId("agent-technical");
    expect(technical.tagName).toBe("DETAILS");
    expect(technical).not.toHaveAttribute("open");
    expect(within(technical).getByTestId("capability-inputs")).toBeInTheDocument();
  });

  it("its sections by their address, in the order of the tabs", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "business" }));
    show();
    const tabs = within(screen.getByRole("navigation", { name: "Sections de la page" })).getAllByRole("link");
    expect(tabs.map((tab) => tab.getAttribute("href"))).toEqual([
      "#overview",
      "#features",
      "#use-cases",
      "#integrations",
      "#results",
      "#pricing",
      "#faq",
    ]);
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Vue d'ensemble",
      "Fonctionnalités",
      "Cas d'usage",
      "Intégrations",
      "Exemples de résultats",
      "Tarifs",
      "FAQ",
    ]);
    for (const tab of tabs) expect(document.getElementById(tab.getAttribute("href")!.slice(1))).not.toBeNull();
    // The one being read, and only it.
    expect(tabs.filter((tab) => tab.getAttribute("aria-current") === "location")).toHaveLength(1);
  });

  it("included: its price and plans as the server says them, « Utiliser l'agent » to its run form", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "business" }));
    show();
    expect(await screen.findByTestId("agent-hero-price")).toHaveTextContent("9 € / mois HT");
    const hero = screen.getByTestId("agent-hero");
    expect(hero).toHaveTextContent("Inclus dès Starter");
    expect(within(hero).getByTestId("agent-state")).toHaveTextContent("Inclus dans votre plan");
    expect(cta()).toHaveAttribute("data-cta", "use");
    expect(cta()).toHaveAttribute("href", "#use");
    expect(within(screen.getByTestId("agent-use")).getByTestId("run-form")).toBeInTheDocument();
    // Included from Starter: every plan from it, the workspace's said.
    const plans = within(screen.getByTestId("agent-plans")).getAllByRole("link");
    expect(plans.map((p) => p.getAttribute("data-plan"))).toEqual(["starter", "growth", "business", "enterprise"]);
    expect(plans[2]).toHaveTextContent("Votre formule");
    const rows = within(screen.getByTestId("agent-plans-table")).getAllByRole("row");
    expect(rows.map((row) => row.textContent)).toEqual([
      "FreeAucun agent",
      "StarterInclus",
      "GrowthInclus",
      "BusinessVotre formuleInclus",
      "EnterpriseInclus",
    ]);
  });

  it("bought: use it, and manage its subscription", async () => {
    sold.addOns.mockResolvedValue(offers({ owned: true, why: null, from: "business" }));
    show();
    await screen.findByTestId("agent-hero-price");
    expect(within(screen.getByTestId("agent-choose")).getByTestId("agent-manage")).toHaveAttribute("href", "/billing");
    expect(cta()).toHaveAttribute("data-cta", "use");
    expect(within(screen.getByTestId("agent-hero")).getByTestId("agent-state")).toHaveTextContent("Déjà acheté");
  });

  it("an option: « Acheter » opens Stripe's page — for whoever may change the workspace", async () => {
    const user = userEvent.setup();
    sold.addOns.mockResolvedValue(offers({ from: "business" }));
    sold.buy.mockResolvedValue({ url: "https://checkout.stripe.test/c" });
    permissions.value = ["workspace:read", "workspace:update", "intention:create"];
    show();
    await screen.findByTestId("agent-hero-price");
    expect(cta()).toHaveAttribute("data-cta", "buy");
    expect(cta()).toHaveTextContent("Acheter");
    // Not runnable before it is bought: no run form.
    expect(screen.queryByTestId("agent-use")).toBeNull();
    const rows = within(screen.getByTestId("agent-plans-table")).getAllByRole("row");
    expect(rows[1]).toHaveTextContent(/^StarterVotre formuleEn option · 9\s€ HT \/ mois$/);
    expect(rows[3]).toHaveTextContent("BusinessInclus");
    await user.click(cta());
    expect(sold.buy).toHaveBeenCalledWith({ kind: "agent", key: "code-review" });
  });

  it("an option, for a member: said who may buy it, nothing bought", async () => {
    sold.addOns.mockResolvedValue(offers({ from: "business" }));
    show();
    await screen.findByTestId("agent-hero-price");
    expect(cta()).toBeDisabled();
    expect(screen.getByTestId("agent-choose")).toHaveTextContent(
      "Seul un propriétaire ou un administrateur de l'espace peut l'acheter.",
    );
  });

  it("on Free: a plan first — « Voir les formules », never « Acheter »", async () => {
    sold.addOns.mockResolvedValue(offers({ why: "plan_required", plan: "free" }));
    show();
    await screen.findByTestId("agent-hero-price");
    expect(cta()).toHaveAttribute("data-cta", "upgrade");
    expect(cta()).toHaveAttribute("href", "/billing/plans");
    expect(screen.getByTestId("agent-choose")).toHaveTextContent(
      "Les agents sont disponibles à partir de la formule Starter.",
    );
    expect(screen.queryByText("Acheter")).toBeNull();
  });

  it("not on sale: never offered — no price, no plan, « Indisponible »", async () => {
    sold.addOns.mockResolvedValue(offers({}));
    show({
      ...REVIEW,
      key: "map-service-ownership",
      title: "Map service ownership",
      summary: "Use when a service has no clear owner.",
      lifecycle: "draft",
      examples: ["Qui possède vraiment payment-api ?"],
    } as CapabilityDetail);
    await screen.findByTestId("agent-similar");
    expect(screen.queryByTestId("agent-hero-price")).toBeNull();
    expect(cta()).toHaveAttribute("data-cta", "unavailable");
    expect(cta()).toBeDisabled();
    expect(screen.queryByTestId("agent-plans")).toBeNull();
    expect(screen.getByTestId("agent-pricing")).toHaveTextContent("Il n'est pas commercialisé pour l'instant.");
    // Its summary, as the catalogue says it — no product written for it.
    expect(screen.getByTestId("agent-promise")).toHaveTextContent(
      (DICTIONARIES.fr.catalogue.summaries as Record<string, string>)["map-service-ownership"],
    );
    expect(screen.getByTestId("agent-ask")).toHaveAttribute(
      "href",
      `/intentions/new?q=${encodeURIComponent("Qui possède vraiment payment-api ?")}`,
    );
  });

  it("dedicated to this organisation: said so, never priced, no plan — « Utiliser l'agent » (2026-10-25)", async () => {
    const offer = offers({});
    sold.addOns.mockResolvedValue({
      ...offer,
      agents: offer.agents.filter((a) => a.key !== "application-architecture"),
      dedicated: ["application-architecture"],
    });
    show({ ...REVIEW, key: "application-architecture", title: "Architecte applicatif", category: "architecture", dedicated: true } as CapabilityDetail);
    expect(await screen.findByTestId("agent-dedicated")).toHaveTextContent("Conçu pour Acme Corp");
    expect(within(screen.getByTestId("agent-hero")).getByTestId("agent-state")).toHaveTextContent("Dédié à votre organisation");
    expect(screen.queryByTestId("agent-hero-price")).toBeNull();
    expect(screen.queryByTestId("agent-plans")).toBeNull();
    expect(screen.getByTestId("agent-contract")).toHaveTextContent(
      "Conçu pour Acme Corp et inclus dans votre contrat : il n'est pas vendu.",
    );
    expect(cta()).toHaveAttribute("data-cta", "use");
    expect(screen.getByTestId("agent-use")).toBeInTheDocument();
    expect(screen.getByTestId("agent-facts")).not.toHaveTextContent(DICTIONARIES.fr.catalogue.product.fact.buy);
  });

  it("under an Enterprise contract: included, never a price (2026-10-25)", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "enterprise" }));
    show();
    expect(await screen.findByTestId("agent-contract")).toHaveTextContent("Inclus dans votre contrat Entreprise.");
    expect(screen.queryByTestId("agent-hero-price")).toBeNull();
    expect(screen.queryByTestId("agent-plans")).toBeNull();
    expect(screen.getByTestId("capability")).not.toHaveTextContent("€");
    expect(cta()).toHaveAttribute("data-cta", "use");
  });

  it("each use case, a request to give it; its sources, those connected said", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "business" }));
    show();
    const cases = screen.getAllByTestId("agent-use-case");
    expect(cases).toHaveLength(4);
    expect(within(cases[0]).getByTestId("agent-ask")).toHaveAttribute(
      "href",
      `/intentions/new?q=${encodeURIComponent("Fais la revue de la dernière PR de payment-api")}`,
    );
    const sources = screen.getAllByTestId("agent-source");
    expect(sources.map((s) => s.getAttribute("data-kind"))).toEqual(["github", "gitlab", "bitbucket"]);
    expect(sources[0]).toHaveAttribute("data-connected", "true");
    expect(sources[1]).not.toHaveAttribute("data-connected");
  });

  it("the examples are said to be examples; the deliverable as it is", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "business" }));
    show();
    const examples = screen.getAllByTestId("agent-example");
    expect(examples).toHaveLength(2);
    for (const example of examples) expect(example).toHaveTextContent("Exemple illustratif");
    expect(screen.getByTestId("agent-results")).toHaveTextContent(
      "Données d'exemple : vos résultats viennent de vos propres sources.",
    );
    const deliverable = screen.getByTestId("agent-deliverable");
    expect(deliverable).toHaveTextContent("Rapport");
    expect(within(deliverable).getAllByRole("listitem")[0]).toHaveTextContent("Ce que fait le changement");
  });

  it("a short FAQ from the facts; similar agents, its own category first", async () => {
    sold.addOns.mockResolvedValue(offers({ included: true, owned: true, why: null, plan: "business" }));
    show();
    await screen.findByTestId("agent-hero-price");
    const faq = screen.getByTestId("agent-faq-list");
    expect(within(faq).getAllByRole("listitem")).toHaveLength(6);
    expect(faq).toHaveTextContent("Non. Il travaille en lecture seule et ne déclenche rien.");
    expect(faq).toHaveTextContent(/9\s€ HT par mois en option, à partir de la formule Starter\. Il est inclus, sans option, dans la formule Starter et au-delà\./);
    expect(faq).toHaveTextContent("Le lancer : tout membre de l'espace.");
    const similar = await screen.findAllByTestId("agent-similar-card");
    expect(similar.map((card) => card.getAttribute("data-key"))).toEqual([
      "codebase-explorer",
      "application-architecture",
      "test-analysis",
      "security-review",
    ]);
    expect(within(similar[0]).getByRole("link", { name: "Exploration du code" })).toHaveAttribute(
      "href",
      "/capabilities/codebase-explorer",
    );
  });
});
