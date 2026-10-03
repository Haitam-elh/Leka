/**
 * "Mon environnement" and an entity's sheet (LEKA-359, mockups 10 and 11).
 *
 * What these protect: every figure on the screen is the API's — the
 * services up, the incidents and the services they hit, the changes, the
 * points of attention — and none is invented where the API has nothing;
 * the map puts each thing in its layer, with its state in words; each tab
 * is a landscape of the company model (LEKA-369), and the list says the
 * same things as rows; under the map, how well its kinds are known and
 * which sources it comes from; an entity's sheet names its owner, its team,
 * its open incident and its dependencies, and leads to its graph; an
 * address that names no entity says so, and keeps the trail.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { EntitySheet, Environment } from "@/lib/environment";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { LandscapeView, ViewName } from "@/lib/knowledge-graph";
import { makeQueryClient } from "@/lib/query";
import type { Source } from "@/lib/sources";

const api = { get: vi.fn(), sheet: vi.fn() };
const sourcesApi = { list: vi.fn() };
const graphApi = { view: vi.fn() };
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
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
  useParams: () => params.value,
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
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
  { id: "s1", type: "github", display_name: "acme/backend", status: "active" },
  { id: "s2", type: "datadog", display_name: "acme-eu", status: "draft" },
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
}));

/** The company view: mockup 10's rows, the enrichment's things in them. */
const COMPANY: LandscapeView = {
  view: "company",
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
  company: COMPANY,
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
  api.get.mockResolvedValue(ENVIRONMENT);
  api.sheet.mockResolvedValue(sheet());
  sourcesApi.list.mockResolvedValue({ data: SOURCES });
  graphApi.view.mockImplementation(async (name: ViewName) => LANDSCAPES[name]);
});

describe("Mon environnement", () => {
  it("shows the API's figures, and only them", async () => {
    mount(<EnvironmentScreen />);

    const services = screen.getByTestId("env-kpi-services");
    expect(await within(services).findByText("3")).toBeInTheDocument();
    expect(within(services).getByText("sur 5 services")).toBeInTheDocument();
    const tile = (id: string) => within(screen.getByTestId(`env-kpi-${id}`));
    expect(tile("incidents").getByText("impacte 1 service(s)")).toBeInTheDocument();
    expect(tile("changes").getByText("7")).toBeInTheDocument();
    expect(tile("attention").getByText("2")).toBeInTheDocument();
    expect(await tile("sources").findByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Votre environnement technologique",
    );
  });

  it("puts each thing in its layer, with its state in words", async () => {
    mount(<EnvironmentScreen />);

    const services = await screen.findByTestId("layer-services");
    const payment = within(services).getByRole("link", { name: /Payment API/ });
    expect(payment).toHaveAttribute("href", `/environment/services/${SERVICE_ID}`);
    expect(within(payment).getByText("Incident")).toBeInTheDocument();
    // A repository by its own name, its full name in the tooltip.
    const layer = (id: string) => within(screen.getByTestId(`layer-${id}`));
    expect(layer("applications").getByTitle("acme/payment-api")).toHaveTextContent("payment-api");
    expect(layer("infrastructure").getByText("eu-west-1 · 4 ressource(s)")).toBeInTheDocument();
    // No source describes the users: the row says so rather than inventing them.
    expect(layer("users").getByText(/ne décrit encore vos utilisateurs/)).toBeInTheDocument();
  });

  it("reads each tab as a landscape of the company model, and lists the same things as rows", async () => {
    const user = userEvent.setup();
    mount(<EnvironmentScreen />);
    await screen.findByTestId("layer-services");
    expect(graphApi.view).toHaveBeenCalledWith("company");

    await user.click(screen.getByTestId("env-tab-infrastructure"));
    const resources = await screen.findByTestId("layer-resources");
    expect(graphApi.view).toHaveBeenCalledWith("infrastructure");
    expect(screen.queryByTestId("layer-services")).not.toBeInTheDocument();
    expect(within(resources).getByText("4 ressource(s)")).toBeInTheDocument();
    expect(within(resources).getByText("eu-west-1 · 4 ressource(s)")).toBeInTheDocument();
    // An empty row names what would fill it.
    expect(
      within(screen.getByTestId("layer-accounts")).getByText(/vos comptes et abonnements/),
    ).toBeInTheDocument();

    // The business domains are rows of the model now, empty until declared.
    await user.click(screen.getByTestId("env-tab-domains"));
    const capabilities = await screen.findByTestId("layer-capabilities");
    expect(within(capabilities).getByText("0 capacité(s)")).toBeInTheDocument();
    expect(within(capabilities).getByText(/Déclarez vos capacités métier/)).toBeInTheDocument();
    // Its applications are those the business relies on: the row says so,
    // not "connect GitHub" to someone whose GitHub is connected.
    const applications = within(screen.getByTestId("layer-applications"));
    expect(applications.getByText("0 élément(s)")).toBeInTheDocument();
    expect(applications.getByText(/sur lesquels s'appuient vos capacités/)).toBeInTheDocument();
    expect(applications.queryByText(/Connectez GitHub/)).not.toBeInTheDocument();

    // The applications tab's own row holds what a catalogue declares, not
    // the repositories: it says so, rather than "connect GitHub".
    graphApi.view.mockResolvedValueOnce(
      EMPTY("applications", [
        layer("applications", ["application"]),
        layer("services", ["service"]),
        layer("code", ["repository"]),
      ]),
    );
    await user.click(screen.getByTestId("env-tab-applications"));
    const declared = within(await screen.findByTestId("layer-code"));
    expect(declared.getByText(/reliés à une application ou à un service/)).toBeInTheDocument();
    expect(
      within(screen.getByTestId("layer-applications")).getByText(/que déclare un catalogue/),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("env-tab-company"));
    await user.click(screen.getByRole("button", { name: "Liste" }));
    const table = screen.getByRole("table", { name: "Les éléments de votre environnement" });
    expect(within(table).getByRole("link", { name: "Payment API" })).toBeInTheDocument();
    expect(within(table).getByText("Payments")).toBeInTheDocument();
  });

  it("says under the map how well its kinds are known, and which sources it comes from", async () => {
    mount(<EnvironmentScreen />);

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
    expect(within(sources).getByText("1 élément(s)")).toBeInTheDocument();
    // The detailed map is a page of its own.
    expect(screen.getByRole("link", { name: /Voir la cartographie détaillée/ })).toHaveAttribute(
      "href",
      "/environment/graph",
    );
  });

  it("says what needs attention and what moved", async () => {
    mount(<EnvironmentScreen />);

    const [incident, unmonitored] = await screen.findAllByTestId("attention-row");
    expect(incident).toHaveTextContent("Latence élevée sur Payment API");
    expect(incident).toHaveTextContent("Impacte Payment API");
    expect(incident).toHaveTextContent("Risque élevé");
    expect(unmonitored).toHaveTextContent("2 service(s) sans monitoring");
    const [event] = screen.getAllByTestId("event-row");
    expect(event).toHaveTextContent("Payment API");
    expect(event).toHaveTextContent("Incident");
  });

  it("keeps the map's structure when nothing is mapped, and says what to connect — no number invented", async () => {
    api.get.mockResolvedValue({
      ...ENVIRONMENT,
      updated_at: null,
      nodes: [],
      edges: [],
      layers: {},
      services: 0,
      services_operational: 0,
      incidents_open: 0,
      services_impacted: 0,
      changes_24h: 0,
      attention: [],
      events: [],
    });
    sourcesApi.list.mockResolvedValue({ data: [] });
    graphApi.view.mockResolvedValue(
      EMPTY("company", [
        layer("users", []),
        layer("applications", ["repository"]),
        layer("services", ["service"]),
        layer("data", ["database"]),
        layer("infrastructure", ["infra_resource"]),
      ]),
    );
    mount(<EnvironmentScreen />);

    const services = await screen.findByTestId("layer-services");
    expect(within(services).getByText("0 service(s)")).toBeInTheDocument();
    expect(within(services).getByText(/Connectez PagerDuty, Datadog ou Grafana/)).toBeInTheDocument();
    expect(within(services).getByRole("link", { name: "Connecter" })).toHaveAttribute(
      "href",
      "/sources",
    );
    expect(
      within(screen.getByTestId("layer-applications")).getByText(/Connectez GitHub/),
    ).toBeInTheDocument();
    const tile = (id: string) => within(screen.getByTestId(`env-kpi-${id}`));
    expect(tile("services").getByText("sur 0 services")).toBeInTheDocument();
    expect(tile("sources").getByText("0 / 0")).toBeInTheDocument();
    expect(screen.getByText("Pas encore cartographié")).toBeInTheDocument();
    expect(screen.getByText("Rien ne demande votre attention.")).toBeInTheDocument();
    expect(screen.queryByText("Payment API")).not.toBeInTheDocument();
    expect(screen.getByText("Rien à mesurer dans cette vue pour l'instant.")).toBeInTheDocument();
    expect(screen.getByText("Aucune source ne nourrit encore cette vue.")).toBeInTheDocument();
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
    expect(screen.getByText("8 membre(s)")).toBeInTheDocument();
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
    // No metrics source: the four tiles say so, with no number.
    const latency = within(screen.getByTestId("metric-latency"));
    expect(latency.getByText("Aucune source de métriques")).toBeInTheDocument();
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

  it("says an address names nothing, and asks the API nothing for it", async () => {
    pathname.value = "/environment/services/payment-api";
    params.value = { entityType: "services", entityId: "payment-api" };
    mount(<EntitySheetScreen />);

    expect(await screen.findByTestId("route-state-not-found")).toBeInTheDocument();
    expect(api.sheet).not.toHaveBeenCalled();
    const trail = screen.getByRole("navigation", { name: "Fil d'Ariane" });
    expect(within(trail).getByText("Payment API")).toBeInTheDocument();
  });

  it("says an entity gone from the sources is not found", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}`;
    params.value = { entityType: "services", entityId: SERVICE_ID };
    api.sheet.mockRejectedValue(new ApiError(404, "/x", "No such entity."));
    mount(<EntitySheetScreen />);

    expect(await screen.findByTestId("route-state-not-found")).toBeInTheDocument();
  });

  it("shows a tab the sources cannot fill as what it waits for", async () => {
    pathname.value = `/environment/services/${SERVICE_ID}/metrics`;
    params.value = { entityType: "services", entityId: SERVICE_ID, tab: "metrics" };
    mount(<EntitySheetScreen />);

    expect(
      await screen.findByText(/latence, erreurs et disponibilité apparaîtront ici/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("tab-metrics")).toHaveAttribute("aria-current", "page");
  });
});
