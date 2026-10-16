/**
 * The home's blocks (LEKA-456): « Mon environnement » claims only what is
 * measured — never « Stable » by default; the agents on sale with their
 * price; the bundles; the latest analyses, each to its page.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

const env = vi.hoisted(() => ({ data: undefined as unknown }));
const offers = vi.hoisted(() => ({ data: undefined as unknown }));
const list = vi.hoisted(() => ({ value: { isPending: false, data: undefined as unknown } }));
vi.mock("@/lib/environment-queries", () => ({ useEnvironment: () => env }));
const listed = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/sources-queries", () => ({ useSources: () => listed }));
vi.mock("@/lib/billing-queries", () => ({ useAddOns: () => offers }));
vi.mock("@/lib/intentions/queries", () => ({ useIntentions: () => list.value }));
vi.mock("@/components/capabilities/offers", () => ({
  AgentPrice: ({ agentKey }: { agentKey: string }) => <span data-testid="price">{agentKey}</span>,
}));
vi.mock("@/components/intentions/intentions-list", () => ({
  StatusPill: ({ status }: { status: string }) => <span>{status}</span>,
}));

const { AgentsSection, BundlesBanner, EnvironmentCard, LatestAnalyses } = await import(
  "@/components/overview/home-sections"
);

const show = (node: React.ReactNode) => render(<LocaleProvider>{node}</LocaleProvider>);
const none = { unavailable: 0, degraded: 0, stale: 0, unknown: 0, not_covered: 0, operational: 0 };
const measured = {
  services: 12,
  services_operational: 12,
  services_unknown: 0,
  incidents_open: 0,
  states: { ...none, operational: 15 },
  sources: [{}, {}, {}],
  freshness: { late: false, last_read_at: new Date().toISOString(), every_minutes: 60 },
};

describe("Mon environnement", () => {
  it("shows the measure, the sources, the services", () => {
    env.data = measured;
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Stable");
    expect(screen.getByTestId("home-environment")).toHaveTextContent("100 %");
    expect(screen.getByTestId("home-environment")).toHaveTextContent("3sources connectées");
    expect(screen.getByTestId("home-cadence")).toHaveTextContent("Sources lues toutes les 60 min — pas en temps réel");
  });

  it("says what the page says (LEKA-468): its services operational, the rest unknown, never « 100 % Stable »", () => {
    // The ticket's workspace: every service operational, yet the page counts
    // 67 % — databases and resources unknown, one not covered.
    env.data = { ...measured, services: 3, services_operational: 3, states: { ...none, operational: 12, unknown: 5, not_covered: 1 } };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Partiellement vérifié");
    expect(screen.getByTestId("home-environment")).toHaveTextContent("67 %");
    expect(screen.getByTestId("home-environment")).toHaveTextContent("État connu pour 12 éléments sur 18");
    expect(screen.getByTestId("home-environment")).not.toHaveTextContent("Aucun incident détecté");
  });

  it("calls a degraded thing trouble even without an open incident", () => {
    env.data = { ...measured, states: { ...none, operational: 9, degraded: 1 } };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Incident en cours");
    expect(screen.getByTestId("home-environment")).toHaveTextContent("1 élément dégradé ou indisponible");
  });

  it("never claims a figure it does not have", () => {
    env.data = { ...measured, sources: [], services: 0, services_operational: 0 };
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-health")).toHaveTextContent("Non vérifié");
    expect(screen.getByTestId("home-environment")).not.toHaveTextContent("%");
  });

  it("counts connected sources only, never a draft whose token was refused", () => {
    env.data = measured;
    listed.data = [{ status: "active" }, { status: "draft" }];
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-environment")).toHaveTextContent("1source connectée");
    listed.data = undefined;
  });

  it("says a source in error, as Mon environnement does, and leads to Sources", () => {
    env.data = measured;
    listed.data = [{ status: "error" }];
    show(<EnvironmentCard />);
    expect(screen.getByTestId("home-environment")).toHaveTextContent("1source connectée");
    expect(screen.getByTestId("home-sources-failing")).toHaveTextContent("1 source en erreur — voir les sources");
    expect(screen.getByTestId("home-sources-failing")).toHaveAttribute("href", "/sources");
    listed.data = undefined;
  });
});

describe("what is on sale", () => {
  const agent = (key: string) => ({ key, title: key, summary: "s", category: "code", tier: "standard", monthly_price: 900 });

  it("shows six agents at most, each with its price, and the way to them all", () => {
    offers.data = { available: true, agents: ["a", "b", "c", "d", "e", "f", "g"].map(agent), bundles: [{}, {}] };
    show(<AgentsSection />);
    expect(screen.getAllByTestId("home-agent")).toHaveLength(6);
    expect(screen.getAllByTestId("price")[0]).toHaveTextContent("a");
    expect(screen.getByRole("link", { name: /Voir tous les agents/ })).toHaveAttribute("href", "/capabilities");
  });

  it("says nothing while nothing is on sale", () => {
    offers.data = { available: false, agents: [agent("a")], bundles: [] };
    const { container } = show(
      <>
        <AgentsSection />
        <BundlesBanner />
      </>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("leads to the bundles", () => {
    offers.data = { available: true, agents: [], bundles: [{}, {}, {}] };
    show(<BundlesBanner />);
    expect(screen.getByTestId("home-bundles")).toHaveTextContent("3 ensembles");
    expect(screen.getByRole("link", { name: /Découvrir les bundles/ })).toHaveAttribute("href", "/capabilities#bundles");
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
