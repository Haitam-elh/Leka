/**
 * The detailed map (LEKA-369): the company's graph, explored.
 *
 * What these protect: with nothing chosen, the whole architecture is drawn
 * — every card, every link in words, a database's tables one choice away —
 * and says what to connect when nothing is known; with a thing chosen
 * (?entity=), what surrounds it is walked
 * with the depth, direction and relationships asked, the thing picked on
 * the canvas says what it is and can become the centre, and the shortest
 * way from it to anything searched is written out step by step. Nothing
 * known says so; an address that names no entity asks nothing.
 *
 * jsdom has no layout: React Flow is stubbed as dependency-graph.test.tsx
 * does, and the canvas is read through its words (data-testid graph-text).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DETAILED, NOTHING } from "@/components/environment/architecture.test-data";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { EntityBrief, GraphRead, PathsRead, SearchResults } from "@/lib/knowledge-graph";
import { makeQueryClient } from "@/lib/query";

const graphApi = {
  architecture: vi.fn(),
  view: vi.fn(),
  walk: vi.fn(),
  paths: vi.fn(),
  search: vi.fn(),
};
const replace = vi.fn();
const searchParams = { value: new URLSearchParams() };

vi.mock("@/lib/knowledge-graph", async (original) => ({
  ...(await original<typeof import("@/lib/knowledge-graph")>()),
  knowledgeGraph: graphApi,
}));
vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: { get: vi.fn(), sheet: vi.fn().mockResolvedValue({ events: [] }) },
}));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: { list: vi.fn().mockResolvedValue({ data: [] }) },
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/environment/graph",
  useSearchParams: () => searchParams.value,
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace }),
}));

const { GraphExplorer } = await import("@/components/environment/graph-explorer");

beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  class DOMMatrixStub {
    m22 = 1;
  }
  vi.stubGlobal("DOMMatrixReadOnly", DOMMatrixStub);
});

const BILLING = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CHECKOUT = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PLATFORM = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PAYMENTS = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

const brief = (id: string, type: EntityBrief["type"], name: string): EntityBrief => ({
  id,
  type,
  key: `${type}:${name.toLowerCase().replaceAll(" ", "-")}`,
  name,
  lifecycle: "active",
});
const billing = brief(BILLING, "service", "Billing API");
const checkout = brief(CHECKOUT, "service", "Checkout");
const platform = brief(PLATFORM, "application", "Billing platform");
const payments = brief(PAYMENTS, "team", "Payments");

const link = (id: string, from: string, to: string, type: string, confidence = 0.9) => ({
  id,
  from_entity_id: from,
  to_entity_id: to,
  type: type as GraphRead["relationships"][number]["type"],
  confidence,
  origin: "stated" as const,
  rule: "declared",
  cross_source: false,
  attributes: {},
});

const WALK: GraphRead = {
  roots: [billing],
  depth: 1,
  direction: "both",
  nodes: [
    { entity: billing, depth: 0, sources: ["pagerduty"] },
    { entity: checkout, depth: 1, sources: ["custom_rest"] },
    { entity: platform, depth: 1, sources: [] },
  ],
  relationships: [
    link("r1", CHECKOUT, BILLING, "depends_on"),
    link("r2", BILLING, PLATFORM, "part_of"),
  ],
  truncated: false,
};

const PATHS: PathsRead = {
  start: billing,
  end: payments,
  length: 2,
  paths: [
    {
      entities: [billing, platform, payments],
      relationships: [
        link("r2", BILLING, PLATFORM, "part_of"),
        link("r3", PLATFORM, PAYMENTS, "owned_by"),
      ],
    },
    {
      entities: [billing, checkout, payments],
      relationships: [
        link("r1", CHECKOUT, BILLING, "depends_on"),
        link("r4", CHECKOUT, PAYMENTS, "owned_by"),
      ],
    },
  ],
  truncated: false,
};

const FOUND: SearchResults = {
  query: "pay",
  entities: [{ entity: payments, score: 1.2, holder: null, sources: ["github"] }],
  relationships: [],
};

function mount(entity?: string) {
  searchParams.value = new URLSearchParams(entity ? { entity } : {});
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <GraphExplorer />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

const graphText = async () => within(await screen.findByTestId("graph-text"));

beforeEach(() => {
  vi.clearAllMocks();
  graphApi.architecture.mockResolvedValue(DETAILED);
  graphApi.walk.mockResolvedValue(WALK);
  graphApi.paths.mockResolvedValue(PATHS);
  graphApi.search.mockResolvedValue(FOUND);
});

describe("the whole architecture", () => {
  it("draws the dossier: every card, every link in words, a database's tables one choice away", async () => {
    const user = userEvent.setup();
    mount();

    const words = within(await screen.findByTestId("architecture-text"));
    // The dossier's: every card, its flows, what to confirm, its sources.
    expect(graphApi.architecture).toHaveBeenCalledWith(null, true);
    expect(graphApi.walk).not.toHaveBeenCalled();
    expect(graphApi.view).not.toHaveBeenCalled();
    expect(words.getByText("Leka Web appelle Leka API")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Architecture applicative" })).toBeInTheDocument();
    // The detailed map is the architecture's dossier: no widgets under it.
    expect(screen.queryByTestId("architecture-types")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^PostgreSQL, Base de données/ }));
    expect(screen.getByRole("link", { name: /Voir ses tables/ })).toHaveAttribute(
      "href",
      "/environment/graph?entity=10000000-0000-4000-8000-000000000006",
    );
  });

  it("says what to connect, rather than drawing an empty canvas", async () => {
    graphApi.architecture.mockResolvedValue(NOTHING);
    mount();

    expect(
      await screen.findByText("Votre architecture n'est pas encore connue"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("architecture")).not.toBeInTheDocument();
  });
});

describe("around one thing", () => {
  it("walks one step both ways through every relationship, and names the root", async () => {
    mount(BILLING);

    const words = await graphText();
    expect(graphApi.walk).toHaveBeenCalledWith({
      root: BILLING,
      depth: 1,
      direction: "both",
      relationships: [],
    });
    expect(graphApi.architecture).not.toHaveBeenCalled();
    expect(words.getByText("Checkout dépend de Billing API")).toBeInTheDocument();
    expect(words.getByText("Billing API fait partie de Billing platform")).toBeInTheDocument();
    const trail = screen.getByRole("navigation", { name: "Fil d'Ariane" });
    expect(within(trail).getByRole("link", { name: "Cartographie détaillée" })).toHaveAttribute(
      "href",
      "/environment/graph",
    );
    expect(within(trail).getByText("Billing API")).toHaveAttribute("aria-current", "page");
    // The root, selected: what it is, and the sources that show it.
    const selected = within(screen.getByTestId("explorer-selected"));
    expect(selected.getByText("Point de départ")).toBeInTheDocument();
    expect(selected.getByText("pagerduty")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Centrer ici/ })).not.toBeInTheDocument();
  });

  it("walks again with the depth, direction and relationships asked", async () => {
    const user = userEvent.setup();
    mount(BILLING);
    await graphText();

    await user.click(screen.getByRole("combobox", { name: "Profondeur" }));
    await user.click(await screen.findByRole("option", { name: "3 niveaux" }));
    await user.click(screen.getByRole("combobox", { name: "Sens" }));
    await user.click(await screen.findByRole("option", { name: "Liens sortants" }));
    await user.click(screen.getByRole("combobox", { name: "Relations" }));
    await user.click(await screen.findByRole("option", { name: "Dépendances" }));

    await waitFor(() =>
      expect(graphApi.walk).toHaveBeenLastCalledWith({
        root: BILLING,
        depth: 3,
        direction: "outgoing",
        relationships: ["depends_on", "supported_by", "uses", "reads_from", "references"],
      }),
    );
  });

  it("says what a thing picked on the canvas is, and centres the map on it", async () => {
    const user = userEvent.setup();
    mount(BILLING);
    await graphText();

    // React Flow, unmeasured in jsdom, keeps its nodes from the pointer: a
    // click is fired, as dependency-graph.test.tsx does.
    fireEvent.click(screen.getByRole("button", { name: "Checkout", hidden: true }));

    const selected = within(screen.getByTestId("explorer-selected"));
    expect(selected.getByText("À 1 pas")).toBeInTheDocument();
    expect(selected.getByText("custom_rest")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ouvrir la fiche/ })).toHaveAttribute(
      "href",
      `/environment/services/${CHECKOUT}`,
    );
    await user.click(screen.getByRole("button", { name: /Centrer ici/ }));
    expect(replace).toHaveBeenCalledWith(`/environment/graph?entity=${CHECKOUT}`);
  });

  it("writes out the shortest way to anything searched, step by step", async () => {
    const user = userEvent.setup();
    mount(BILLING);
    await graphText();

    const finder = within(screen.getByTestId("explorer-path"));
    await user.type(finder.getByRole("combobox"), "pay");
    await user.click(await finder.findByRole("option", { name: /Payments/ }));

    const result = within(await screen.findByTestId("explorer-path-result"));
    expect(graphApi.search).toHaveBeenCalledWith("pay", { limit: 8 });
    expect(graphApi.paths).toHaveBeenCalledWith({ from: BILLING, to: PAYMENTS, relationships: [] });
    expect(result.getByText("2 pas")).toBeInTheDocument();
    const steps = result.getAllByRole("listitem");
    expect(steps.map((step) => step.textContent)).toEqual([
      "Billing API · Service",
      "↓ fait partie deBilling platform · Application",
      "↓ appartient àPayments · Équipe",
    ]);
    expect(result.getByRole("link", { name: "Payments" })).toHaveAttribute(
      "href",
      `/environment/teams/${PAYMENTS}`,
    );
    expect(result.getByText("Et 1 autre(s) chemin(s) aussi court(s).")).toBeInTheDocument();
  });

  it("says when no way joins them within four steps", async () => {
    const user = userEvent.setup();
    graphApi.paths.mockResolvedValue({ ...PATHS, length: null, paths: [] });
    mount(BILLING);
    await graphText();

    const finder = within(screen.getByTestId("explorer-path"));
    await user.type(finder.getByRole("combobox"), "pay");
    await user.click(await finder.findByRole("option", { name: /Payments/ }));

    expect(
      await screen.findByText("Aucun chemin en 4 pas au plus entre ces deux éléments."),
    ).toBeInTheDocument();
  });

  it("says when nothing is tied to it", async () => {
    graphApi.walk.mockResolvedValue({
      ...WALK,
      nodes: [WALK.nodes[0]],
      relationships: [],
    });
    mount(BILLING);

    expect(await screen.findByText("Rien n'est relié à cet élément ici")).toBeInTheDocument();
  });

  it("asks nothing for an address that names no entity, and shows the architecture", async () => {
    mount("billing-api");

    await screen.findByTestId("architecture-text");
    expect(graphApi.walk).not.toHaveBeenCalled();
    expect(graphApi.architecture).toHaveBeenCalledWith(null, true);
  });
});
