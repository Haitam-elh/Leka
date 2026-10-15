/**
 * "Mon environnement" and an entity's sheet (LEKA-359, mockups 10 and 11).
 *
 * What these protect: the screen opens on the architecture (LEKA-369,
 * Haitam's mockup) — its figures above every tab, its columns, what moved
 * and what needs a look under it — none invented where the API has nothing; each other
 * tab is a landscape of the company model, its map putting each thing in
 * its layer with its state in words, and the list says the same things as
 * rows; under the map, how well its kinds are known and which sources it
 * comes from; Événements, what moved and what needs attention; an entity's
 * sheet names its owner, its team,
 * its open incident and its dependencies, and leads to its graph; an
 * address that names no entity says so, and keeps the trail.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ARCHITECTURE, NOTHING } from "@/components/environment/architecture.test-data";
import { ApiError } from "@/lib/api";
import type { EntityActivity, EntitySheet, Environment } from "@/lib/environment";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { LandscapeView, ViewName } from "@/lib/knowledge-graph";
import { makeQueryClient } from "@/lib/query";
import type { Source } from "@/lib/sources";

const api = { get: vi.fn(), sheet: vi.fn(), activity: vi.fn() };
const sourcesApi = { list: vi.fn() };
// A thing's course (LEKA-383): what a sheet the sources no longer fill reads.
const courseApi = { history: vi.fn(), at: vi.fn() };
const graphApi = { view: vi.fn(), architecture: vi.fn() };
const pathname = { value: "/environment" };
const params: { value: Record<string, string> } = { value: {} };

vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: api,
}));
vi.mock("@/lib/knowledge-graph", async (original) => ({
  ...(await original<typeof import("@/lib/knowledge-graph")>()),
  knowledgeGraph: graphApi,
}));
// Who reads a thing's course: a member, who may not restore.
vi.mock("@/components/shell/shell-provider", async (original) => ({
  ...(await original<typeof import("@/components/shell/shell-provider")>()),
  usePermissions: () => ["workspace:read"],
  useCurrentUser: () => null,
}));
vi.mock("@/lib/evolution", async (original) => ({
  ...(await original<typeof import("@/lib/evolution")>()),
  evolution: courseApi,
}));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));
// The address's query, as the router keeps it: the screen's tab lives in it
// (LEKA-428), so replacing the address must redraw what reads it.
const query = vi.hoisted(() => {
  let value = "";
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set(next: string) {
      value = next;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
});
const replace = vi.fn((href: string) => query.set(href.split("?")[1] ?? ""));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    usePathname: () => pathname.value,
    useParams: () => params.value,
    useSearchParams: () =>
      new URLSearchParams(useSyncExternalStore(query.subscribe, query.get, query.get)),
    useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace }),
  };
});

// The card has its own tests (leka-insights.test.tsx); here it is only a
// place on the page.
vi.mock("@/components/insights/leka-insights", () => ({
  LekaInsights: () => <div data-testid="leka-insights" />,
}));

const { EnvironmentScreen } = await import("@/components/environment/environment-screen");
const { EntitySheetScreen } = await import("@/components/environment/entity-sheet");

const SERVICE_ID = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const REPO_ID = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const INCIDENT_ID = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const TEAM_ID = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const NOW = new Date().toISOString();

const ref = (id: string, type: string, name: string, key = name) => ({ id, type, key, name });

const ENVIRONMENT: Environment = {
  updated_at: NOW,
  nodes: [
    {
      id: SERVICE_ID,
      type: "service",
      layer: "services",
      name: "Payment API",
      status: "incident",
      entity_id: SERVICE_ID,
      key: "service:payment",
      detail: null,
      count: 1,
      environment: null,
      team: ref(TEAM_ID, "team", "Payments", "team:payments"),
    },
    {
      id: REPO_ID,
      type: "repository",
      layer: "applications",
      name: "acme/payment-api",
      status: null,
      entity_id: REPO_ID,
      key: "github.com/acme/payment-api",
      detail: null,
      count: 1,
      environment: null,
      team: null,
    },
    {
      id: "provider:aws:eu-west-1",
      type: "provider",
      layer: "infrastructure",
      name: "aws",
      status: "operational",
      entity_id: null,
      key: null,
      detail: "eu-west-1",
      count: 4,
      environment: null,
      team: null,
    },
  ],
  edges: [{ from_id: REPO_ID, to_id: SERVICE_ID, type: "part_of", status: "incident" }],
  layers: { applications: 1, services: 1, infrastructure: 4 },
  environments: [],
  services: 5,
  services_operational: 3,
  services_deduced: 0,
  services_external: 0,
  services_unknown: 0,
  incidents_open: 1,
  services_impacted: 1,
  changes_24h: 7,
  attention: [
    {
      kind: "open_incident",
      level: "high",
      count: 1,
      entity: ref(INCIDENT_ID, "incident", "Latence élevée sur Payment API"),
      detail: "Payment API",
    },
    { kind: "unmonitored_services", level: "info", count: 2, entity: null, detail: null },
  ],
  events: [
    {
      entity: ref(INCIDENT_ID, "incident", "Latence élevée sur Payment API"),
      at: NOW,
      kind: "incident",
      where: ref(SERVICE_ID, "service", "Payment API"),
      source_kinds: ["datadog"],
    },
  ],
};

const SOURCES = [
  { id: "s1", type: "github", display_name: "acme/backend", status: "active", capabilities: [] },
  { id: "s2", type: "datadog", display_name: "acme-eu", status: "draft", capabilities: [] },
] as unknown as Source[];

const layer = (name: string, types: string[], total = 0) => ({
  name,
  types: types as LandscapeView["layers"][number]["types"],
  total,
  shown: total,
});

/** The same things as boxes of a view: a team there is an entity's brief. */
const BOXES: LandscapeView["nodes"] = ENVIRONMENT.nodes.map((node) => ({
  ...node,
  team: node.team ? { ...node.team, type: "team", lifecycle: "active" } : null,
  deduced: false,
}));

/** The applications view: mockup 10's rows, the enrichment's things in them. */
const APPLICATIONS: LandscapeView = {
  view: "applications",
  built_at: NOW,
  layers: [
    layer("users", []),
    layer("applications", ["repository"], 1),
    layer("services", ["service"], 1),
    layer("data", ["database"]),
    layer("infrastructure", ["infra_resource"], 4),
  ],
  nodes: BOXES,
  edges: ENVIRONMENT.edges,
  coverage: [
    {
      type: "service",
      total: 1,
      owned: 1,
      documented: 0,
      corroborated: 0,
      connected: 1,
    },
    {
      type: "repository",
      total: 1,
      owned: 0,
      documented: 0,
      corroborated: 0,
      connected: 1,
    },
  ],
  sources: [{ source_id: "s2", kind: "datadog", entities: 1 }],
};

const EMPTY = (view: ViewName, layers: LandscapeView["layers"]): LandscapeView => ({
  view,
  built_at: null,
  layers,
  nodes: [],
  edges: [],
  coverage: [],
  sources: [],
});

const LANDSCAPES: Partial<Record<ViewName, LandscapeView>> = {
  applications: APPLICATIONS,
  infrastructure: {
    ...EMPTY("infrastructure", [
      layer("accounts", ["cloud_account", "resource_group"]),
      layer("resources", ["infra_resource"], 4),
      layer("databases", ["database"]),
    ]),
    nodes: [{ ...BOXES[2], layer: "resources" }],
  },
  domains: EMPTY("domains", [
    layer("capabilities", ["business_capability"]),
    layer("processes", ["business_process"]),
    layer("applications", ["application", "service"]),
    layer("data", ["database", "schema", "data_object"]),
  ]),
};

function sheet(overrides: Partial<EntitySheet> = {}): EntitySheet {
  return {
    entity: {
      id: SERVICE_ID,
      type: "service",
      key: "service:payment",
      name: "Payment API",
      names: ["Payment API"],
      attributes: {},
      conflicts: [],
      confidence: 1,
      quality: null,
      sources: 1,
      resolved_at: NOW,
      enriched: [
        {
          attribute: "lifecycle",
          value: "active",
          confidence: 0.9,
          rule: "activity",
          evidence: "",
          inputs: [],
        },
      ],
      outgoing: [],
      outgoing_total: 0,
      incoming: [],
      incoming_total: 0,
    },
    status: "incident",
    deduced: false,
    environment: "production",
    owner: {
      entity: ref("p1", "person", "Sara Martin"),
      confidence: 0.76,
      evidence: "",
    },
    team: {
      entity: ref(TEAM_ID, "team", "Payments"),
      confidence: 1,
      origin: "stated",
      members: 8,
    },
    incidents: [ENVIRONMENT.events[0]],
    events: [ENVIRONMENT.events[0]],
    dependencies: [
      {
        entity: ref(REPO_ID, "repository", "acme/payment-api"),
        type: "part_of",
        direction: "in",
        status: null,
        origin: "inferred",
        confidence: 0.8,
        cross_source: true,
      },
    ],
    documents: [ref("d1", "document", "Runbook Payment API")],
    attention: [ENVIRONMENT.attention[0]],
    source_kinds: ["datadog"],
    ...overrides,
  };
}

const day = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
function activityOf(days = 30): EntityActivity {
  return {
    days,
    since: `${day(days)}T00:00:00Z`,
    events: [
      {
        entity: ref("r1", "release", "v2.4.0"),
        at: `${day(1)}T09:00:00Z`,
        kind: "change",
        where: ref(REPO_ID, "repository", "acme/payment-api"),
        source_kinds: ["github"],
        state: "published",
        url: "https://github.com/acme/payment-api/releases/v2.4.0",
        version: "v2.4.0",
        environment: null,
      },
      {
        entity: ref("pr1", "pull_request", "Retry on timeout"),
        at: `${day(2)}T10:00:00Z`,
        kind: "change",
        where: ref(REPO_ID, "repository", "acme/payment-api"),
        source_kinds: ["github"],
        state: "merged",
        url: "javascript:alert(1)",
        version: null,
        environment: null,
      },
      {
        entity: ref("i1", "issue", "Payments time out"),
        at: `${day(3)}T10:00:00Z`,
        kind: "information",
        where: null,
        source_kinds: ["jira"],
        state: "open",
        url: null,
        version: null,
        environment: null,
      },
    ],
    by_day: Array.from({ length: days }, (_, n) => ({
      day: day(days - n - 1),
      changes: n === days - 3 ? 1 : 0,
      deployments: n === days - 2 ? 1 : 0,
      incidents: 0,
      work: n === days - 4 ? 1 : 0,
      other: 0,
    })),
    changes: 1,
    deployments: 1,
    incidents: 0,
    incidents_open: 0,
    work: 1,
    work_open: 1,
    last_activity: `${day(1)}T09:00:00Z`,
    previous: { changes: 2, deployments: 0, incidents: 1, work: 0 },
    log_sources: [],
    mentions: [ref("d9", "document", "Architecture des paiements")],
  };
}

function mount(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  pathname.value = "/environment";
  params.value = {};
  query.set("");
  api.get.mockResolvedValue(ENVIRONMENT);
  api.sheet.mockResolvedValue(sheet());
  api.activity.mockImplementation(async (_id: string, days: number) => activityOf(days));
  courseApi.history.mockRejectedValue(new ApiError(404, "/x", "No such entity."));
  sourcesApi.list.mockResolvedValue({ data: SOURCES });
  graphApi.view.mockImplementation(async (name: ViewName) => LANDSCAPES[name]);
  graphApi.architecture.mockResolvedValue(ARCHITECTURE);
});

/** Its views (LEKA-459): the mockup's as tabs, the others in a menu after them. */
const VIEW = DICTIONARIES.fr.environment.tabs;
const MORE = ["infrastructure", "data", "domains", "quality"];
async function pick(user: ReturnType<typeof userEvent.setup>, tab: keyof typeof VIEW) {
  if (MORE.includes(tab)) {
    await user.click(screen.getByTestId("env-more"));
    await user.click(await screen.findByRole("option", { name: VIEW[tab] }));
  } else {
    await user.click(screen.getByRole("tab", { name: VIEW[tab] }));
  }
}
/** The view shown: its tab selected, or the menu naming it. */
function expectView(tab: keyof typeof VIEW) {
  if (MORE.includes(tab)) expect(screen.getByTestId("env-more")).toHaveTextContent(VIEW[tab]);
  else expect(screen.getByRole("tab", { name: VIEW[tab] })).toHaveAttribute("aria-selected", "true");
}

describe("Mon environnement", () => {
  it("opens on the architecture, its figures the API's", async () => {
    mount(<EnvironmentScreen />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Mon environnement");
    expectView("architecture");
    const services = within(screen.getByTestId("arch-figure-services"));
    expect(await services.findByText("4")).toBeInTheDocument();
    expect(await screen.findByTestId("arch-column-services")).toBeInTheDocument();
    // The overview's: a column's first cards, no flows.
    expect(graphApi.architecture).toHaveBeenCalledWith(null, false);
    expect(graphApi.view).not.toHaveBeenCalled();
    // Under it, the mockup's foot (LEKA-459): the overall state, the
    // sources, the alerts, what moved — what needs a look is on Incidents.
    expect(await screen.findAllByText("Latence élevée sur Payment API")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "État global" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Événements récents" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Points d'attention" })).not.toBeInTheDocument();
    expect(screen.queryByText("Top dépendances")).not.toBeInTheDocument();
    // The way back home, and the detailed map, a page of its own.
    expect(screen.getByRole("link", { name: /Retour à l'accueil/ })).toHaveAttribute("href", "/overview");
    expect(screen.getByRole("link", { name: /Voir la cartographie détaillée/ })).toHaveAttribute(
      "href",
      "/environment/graph",
    );
  });

  it("keeps its tab in the address, so the sidebar can open each view", async () => {
    const user = userEvent.setup();
    query.set("tab=infrastructure");
    mount(<EnvironmentScreen />);

    expectView("infrastructure");
    expect(graphApi.view).toHaveBeenCalledWith("infrastructure");

    await pick(user, "domains");
    expect(replace).toHaveBeenLastCalledWith("/environment?tab=domains", { scroll: false });
    expectView("domains");

    // The first tab is the address with no tab at all.
    await pick(user, "architecture");
    expect(replace).toHaveBeenLastCalledWith("/environment", { scroll: false });
  });

  it("holds the sources and what configures them as views of its own (LEKA-459)", async () => {
    const user = userEvent.setup();
    query.set("tab=sources");
    mount(<EnvironmentScreen />);

    expectView("sources");
    // The sources' own page, inside: its figures and its list.
    expect(await screen.findByText("Synchronisations en cours")).toBeInTheDocument();
    await pick(user, "configuration");
    expect(replace).toHaveBeenLastCalledWith("/environment?tab=configuration", { scroll: false });
  });

  it("offers to connect a source only to who may", async () => {
    mount(<EnvironmentScreen />);
    expect(screen.queryByTestId("env-connect")).not.toBeInTheDocument();
  });

  it("opens on the architecture when the address names no tab it has", async () => {
    query.set("tab=nonsense");
    mount(<EnvironmentScreen />);

    expectView("architecture");
  });

  it("puts each thing in its layer on the other tabs, with its state in words", async () => {
    const user = userEvent.setup();
    mount(<EnvironmentScreen />);

    await pick(user, "applications");
    const services = await screen.findByTestId("layer-services");
    expect(graphApi.view).toHaveBeenCalledWith("applications");
    const payment = within(services).getByRole("link", { name: /Payment API/ });
    expect(payment).toHaveAttribute("href", `/environment/services/${SERVICE_ID}`);
    expect(within(payment).getByText("Incident")).toBeInTheDocument();
    // A repository by its own name, its full name in the tooltip.
    const layer = (id: string) => within(screen.getByTestId(`layer-${id}`));
    expect(layer("applications").getByTitle("acme/payment-api")).toHaveTextContent("payment-api");
    expect(layer("infrastructure").getByText("eu-west-1 · 4 ressources")).toBeInTheDocument();
    // No source describes the users: the row says so rather than inventing them.
    expect(layer("users").getByText(/ne décrit encore vos utilisateurs/)).toBeInTheDocument();
    // The architecture's figures stay above every tab.
    expect(screen.getByTestId("arch-figure-services")).toBeInTheDocument();
  });

  it("reads each tab as a landscape of the company model, and lists the same things as rows", async () => {
    const user = userEvent.setup();
    mount(<EnvironmentScreen />);

    await pick(user, "infrastructure");
    const resources = await screen.findByTestId("layer-resources");
    expect(graphApi.view).toHaveBeenCalledWith("infrastructure");
    expect(screen.queryByTestId("layer-services")).not.toBeInTheDocument();
    expect(within(resources).getByText("4 ressources")).toBeInTheDocument();
    expect(within(resources).getByText("eu-west-1 · 4 ressources")).toBeInTheDocument();
    // An empty row names what would fill it.
    expect(
      within(screen.getByTestId("layer-accounts")).getByText(/vos comptes et abonnements/),
    ).toBeInTheDocument();

    // The business domains are rows of the model, empty until declared.
    await pick(user, "domains");
    const capabilities = await screen.findByTestId("layer-capabilities");
    expect(within(capabilities).getByText("0 capacité")).toBeInTheDocument();
    expect(within(capabilities).getByText(/Déclarez vos capacités métier/)).toBeInTheDocument();
    // Its applications are those the business relies on: the row says so,
    // not "connect GitHub" to someone whose GitHub is connected.
    const applications = within(screen.getByTestId("layer-applications"));
    expect(applications.getByText("0 élément")).toBeInTheDocument();
    expect(applications.getByText(/sur lesquels s'appuient vos capacités/)).toBeInTheDocument();
    expect(applications.queryByText(/Connectez GitHub/)).not.toBeInTheDocument();

    await pick(user, "applications");
    await screen.findByTestId("layer-services");
    await user.click(screen.getByRole("button", { name: "Liste" }));
    const table = screen.getByRole("table", { name: "Les éléments de votre environnement" });
    expect(within(table).getByRole("link", { name: "Payment API" })).toBeInTheDocument();
    expect(within(table).getByText("Payments")).toBeInTheDocument();
  });

  it("says under the map how well its kinds are known, and which sources it comes from", async () => {
    const user = userEvent.setup();
    mount(<EnvironmentScreen />);
    await pick(user, "applications");

    const coverage = await screen.findByTestId("coverage");
    // Over every one of its kinds, not only those drawn — and it says so.
    expect(within(coverage).getByText(/pas seulement ceux affichés/)).toBeInTheDocument();
    const service = within(within(coverage).getByTestId("coverage-service"));
    expect(service.getByRole("rowheader")).toHaveTextContent("Service");
    expect(service.getByRole("meter", { name: "Avec propriétaire : 1 sur 1" })).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    expect(service.getByRole("meter", { name: "Documentés : 0 sur 1" })).toHaveAttribute(
      "aria-valuenow",
      "0",
    );
    // The source by its own name, and how much of the view it shows.
    const sources = within(coverage).getByRole("list", { name: "Sources de cette vue" });
    expect(await within(sources).findByText("acme-eu")).toBeInTheDocument();
    expect(within(sources).getByText("1 élément")).toBeInTheDocument();
  });

  it("says on Événements what needs attention and what moved", async () => {
    const user = userEvent.setup();
    mount(<EnvironmentScreen />);
    await pick(user, "events");

    const [incident, unmonitored] = await screen.findAllByTestId("attention-row");
    expect(incident).toHaveTextContent("Latence élevée sur Payment API");
    expect(incident).toHaveTextContent("Impacte Payment API");
    expect(incident).toHaveTextContent("Risque élevé");
    expect(unmonitored).toHaveTextContent("2 services sans monitoring");
    const [event] = screen.getAllByTestId("event-row");
    expect(event).toHaveTextContent("Latence élevée sur Payment API");
    expect(event).toHaveTextContent("Incident");
  });

  it("says what to connect when nothing is known — no number invented", async () => {
    api.get.mockResolvedValue({
      ...ENVIRONMENT,
      updated_at: null,
      nodes: [],
      edges: [],
      layers: {},
      services: 0,
      services_operational: 0,
      services_deduced: 0,
      services_external: 0,
      services_unknown: 0,
      incidents_open: 0,
      services_impacted: 0,
      changes_24h: 0,
      attention: [],
      events: [],
    });
    sourcesApi.list.mockResolvedValue({ data: [] });
    graphApi.architecture.mockResolvedValue(NOTHING);
    mount(<EnvironmentScreen />);

    expect(
      await screen.findByText("Votre architecture n'est pas encore connue"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connecter" })).toHaveAttribute("href", "/sources");
    expect(within(screen.getByTestId("arch-figure-services")).getByText("0")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("arch-figure-health")).getByText("Aucun état connu"),
    ).toBeInTheDocument();
    expect(screen.getByText("Pas encore cartographié")).toBeInTheDocument();
    expect(screen.queryByText("Payment API")).not.toBeInTheDocument();
  });
});

describe("an entity's sheet", () => {
  it("names its owner, its team, its open incident and its dependencies", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    mount(<EntitySheetScreen />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Payment API");
    expect(screen.getByText("Service · production")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sara Martin" })).toBeInTheDocument();
    expect(screen.getByText("Mainteneur · 76 % de confiance")).toBeInTheDocument();
    expect(screen.getByText("8 membres")).toBeInTheDocument();
    const incident = screen.getByTestId("active-incident");
    expect(within(incident).getByText("Incident actif")).toBeInTheDocument();
    expect(within(incident).getByRole("link", { name: /Voir l'incident/ })).toHaveAttribute(
      "href",
      `/environment/incidents/${INCIDENT_ID}`,
    );
    const [dependency] = screen.getAllByTestId("dependency-row");
    expect(dependency).toHaveTextContent("acme/payment-api");
    expect(screen.getByRole("link", { name: "Voir le graphe" })).toHaveAttribute(
      "href",
      `/environment/graph?entity=${SERVICE_ID}`,
    );
    expect(dependency).toHaveTextContent("En fait partie · déduit · 80 % · entre outils");
    // Its activity, as its sources show it — against the period before.
    expect(await screen.findByTestId("activity-changes")).toHaveTextContent("1");
    expect(screen.getByTestId("activity-changes")).toHaveTextContent("-50 %");
    expect(screen.getByTestId("activity-deployments")).toHaveTextContent("+1");
    expect(screen.getByTestId("activity-work")).toHaveTextContent("1 ouvert");
    expect(screen.getByTestId("activity-chart")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Runbook Payment API" })).toBeInTheDocument();
    // The trail names the entity, not its identifier.
    const trail = screen.getByRole("navigation", { name: "Fil d'Ariane" });
    expect(within(trail).getByRole("link", { name: "Mon environnement" })).toBeInTheDocument();
    expect(within(trail).getByText("Payment API")).toBeInTheDocument();
  });

  it("says when nothing is open", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    api.sheet.mockResolvedValue(
      sheet({ incidents: [], attention: [], status: "operational", owner: null, team: null }),
    );
    mount(<EntitySheetScreen />);

    expect(await screen.findByText("Aucun incident actif")).toBeInTheDocument();
    expect(screen.getByText("Rien ne demande votre attention")).toBeInTheDocument();
    expect(screen.getByText("Non identifié")).toBeInTheDocument();
  });

  it("leaves out a figure with nothing to say, says once what is not known, and no promised analysis", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    api.sheet.mockResolvedValue(sheet({ environment: null }));
    api.activity.mockImplementation(async (_id: string, days: number) => {
      const activity = activityOf(days);
      return { ...activity, deployments: 0, previous: { ...activity.previous, deployments: 0 } };
    });
    mount(<EntitySheetScreen />);

    // 0 now and 0 before: no tile (LEKA-438). 0 now but 1 before: said.
    expect(await screen.findByTestId("activity-changes")).toBeInTheDocument();
    expect(screen.queryByTestId("activity-deployments")).not.toBeInTheDocument();
    expect(screen.getByTestId("activity-incidents")).toBeInTheDocument();
    // An unknown is said once, in words — not a row of « Non renseigné ».
    expect(await screen.findByTestId("general-unknown")).toHaveTextContent(/^Pas encore connu : environnement/);
    expect(screen.queryByText("Non renseigné")).not.toBeInTheDocument();
    // « Demander à LEKA » asks; no banner promising an analysis to come.
    expect(screen.queryByRole("link", { name: /Lancer une intention/ })).not.toBeInTheDocument();
  });

  it("says a deduced state as such, and what is only worth knowing apart", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    api.sheet.mockResolvedValue(
      sheet({
        incidents: [],
        status: "operational",
        deduced: true,
        attention: [
          { kind: "unmonitored_services", level: "info", count: 1, entity: null, detail: null },
        ],
      }),
    );
    mount(<EntitySheetScreen />);

    // « En bonne santé », deduced from what runs it — as its card says it.
    expect(await screen.findByTestId("sheet-deduced")).toHaveTextContent("Déduit");
    // Nothing needs anyone: not « 1 point nécessite votre attention ».
    expect(screen.getByText("Rien d'urgent, à savoir")).toBeInTheDocument();
    expect(screen.queryByText(/nécessitent votre attention/)).not.toBeInTheDocument();
  });

  it("reads its figures and its chart over the period chosen, the events too", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    mount(<EntitySheetScreen />);

    await screen.findByTestId("activity-changes");
    expect(api.activity).toHaveBeenLastCalledWith(SERVICE_ID, 30);
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "Période" }));
    await user.click(await screen.findByRole("option", { name: "7 derniers jours" }));
    // The figures follow — not 30 days under « 7 derniers jours ».
    expect(api.activity).toHaveBeenLastCalledWith(SERVICE_ID, 7);
  });

  it("says an address names nothing, and asks the API nothing for it", async () => {
    pathname.value = "/environment/services/payment-api";
    params.value = { entityType: "services", entityId: "payment-api" };
    mount(<EntitySheetScreen />);

    expect(await screen.findByTestId("route-state-not-found")).toBeInTheDocument();
    expect(api.sheet).not.toHaveBeenCalled();
    const trail = screen.getByRole("navigation", { name: "Fil d'Ariane" });
    expect(within(trail).getByText("Payment API")).toBeInTheDocument();
  });

  it("says a thing the model never knew is not found", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    api.sheet.mockRejectedValue(new ApiError(404, "/x", "No such entity."));
    mount(<EntitySheetScreen />);

    expect(await screen.findByTestId("route-state-not-found")).toBeInTheDocument();
  });

  it("shows a thing no source shows any more by its history", async () => {
    pathname.value = `/environment/resources/${SERVICE_ID}`;
    params.value = { entityType: "resources", entityId: SERVICE_ID };
    api.sheet.mockRejectedValue(new ApiError(404, "/x", "No such entity."));
    const redis = {
      id: SERVICE_ID,
      type: "infra_resource",
      key: "arn:redis",
      name: "redis-sessions",
      lifecycle: "removed",
    };
    const version = (number: number, change: string, at: string) => ({
      id: crypto.randomUUID(),
      entity_id: SERVICE_ID,
      entity: redis,
      name: "redis-sessions",
      version: number,
      change,
      fields: change === "removed" ? [{ field: "lifecycle", before: "active", after: "removed" }] : [],
      recorded_at: at,
      run_id: null,
    });
    courseApi.history.mockResolvedValue({
      entity: redis,
      versions: [
        version(2, "removed", "2026-10-01T12:00:00Z"),
        version(1, "created", "2026-09-07T12:00:00Z"),
      ],
      relationships: [],
      operations: [],
      horizon: null,
    });
    mount(<EntitySheetScreen />);

    expect(await screen.findByRole("heading", { level: 1, name: "redis-sessions" })).toBeVisible();
    expect(screen.getByText(/Aucune source ne le montre plus depuis le/)).toBeInTheDocument();
    expect(screen.getByTestId("history-version-2")).toHaveTextContent("Retiré");
    // Gone: nothing of it is restored.
    expect(screen.queryByRole("button", { name: "Restaurer" })).not.toBeInTheDocument();
  });

  it("fills each tab with what its sources show", async () => {
    const user = userEvent.setup();
    const open = (tab: string) => {
      pathname.value = `/environment/services/${SERVICE_ID}/${tab}`;
      params.value = { entityType: "services", entityId: SERVICE_ID, tab };
    };

    open("metrics");
    const { unmount } = mount(<EntitySheetScreen />);
    const metrics = await screen.findByTestId("metrics-tab");
    expect(screen.getByTestId("tab-metrics")).toHaveAttribute("aria-current", "page");
    expect(within(metrics).getByTestId("runtime-note")).toHaveTextContent(
      "Latence, erreurs et disponibilité viennent d'un outil de supervision",
    );
    await user.click(within(metrics).getByRole("button", { name: "90 jours" }));
    expect(api.activity).toHaveBeenLastCalledWith(SERVICE_ID, 90);
    unmount();

    open("deployments");
    const deployments = mount(<EntitySheetScreen />);
    const [release] = await screen.findAllByTestId("activity-event");
    expect(release).toHaveTextContent("v2.4.0");
    expect(within(release).getByRole("link", { name: "Ouvrir" })).toHaveAttribute(
      "href",
      "https://github.com/acme/payment-api/releases/v2.4.0",
    );
    deployments.unmount();

    open("logs");
    const logs = mount(<EntitySheetScreen />);
    expect(await screen.findAllByTestId("activity-event")).toHaveLength(3);
    // A link that is not http(s) is never one.
    expect(screen.queryAllByRole("link", { name: "Ouvrir" })).toHaveLength(1);
    await user.click(screen.getByTestId("logs-filter-work"));
    expect(screen.getAllByTestId("activity-event")).toHaveLength(1);
    expect(screen.getByTestId("logs")).toHaveTextContent("Payments time out");
    logs.unmount();

    open("configuration");
    api.sheet.mockResolvedValue(
      sheet({
        entity: {
          ...sheet().entity,
          attributes: { runtime: "python3.12", replicas: 3, url: "https://x" },
        },
      }),
    );
    const configuration = mount(<EntitySheetScreen />);
    const stated = await screen.findAllByTestId("configuration-stated");
    expect(stated.map((row) => row.textContent)).toEqual(["replicas3", "runtimepython3.12"]);
    expect(screen.getByTestId("configuration-deduced")).toHaveTextContent("lifecycle");
    configuration.unmount();

    open("incidents");
    const incidents = mount(<EntitySheetScreen />);
    expect(await screen.findByTestId("open-work")).toHaveTextContent("Payments time out");
    incidents.unmount();

    open("documentation");
    mount(<EntitySheetScreen />);
    expect(await screen.findByTestId("mentions")).toHaveTextContent("Architecture des paiements");
  });
});
