/**
 * The overview: the mockup's layout, the workspace's real figures.
 *
 * What these protect is the decision of 2026-09-25 — real data, or an
 * honest empty state, never the mockup's numbers. The mockup's "98 %",
 * "47 / 48 services" and "3 incidents" must not reach a customer; the
 * sources LEKA actually reads must — the environment's services, its
 * attention points and open incidents, as enrichment made them; this
 * week's events and the open contradictions — and what LEKA proposes,
 * waiting on someone, is listed where the mockup says "À valider" (LEKA-380).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Candidate } from "@/lib/enrichment";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Source, SourceEvent } from "@/lib/sources";

const list = vi.fn();
const events = vi.fn();
const proposed = vi.fn();

vi.mock("@/lib/enrichment", async (original) => ({
  ...(await original<typeof import("@/lib/enrichment")>()),
  enrichment: { candidates: () => proposed() },
}));
vi.mock("@/lib/conflicts", async (original) => ({
  ...(await original<typeof import("@/lib/conflicts")>()),
  conflicts: { list: async () => ({ data: [], next_cursor: null }) },
}));

const environment = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment,
}));
vi.mock("@/lib/activity", async (original) => ({
  ...(await original<typeof import("@/lib/activity")>()),
  activity: { read: async () => ({ stats: { events: { value: 42, previous: 30 } } }) },
}));

vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: { list: () => list(), events: (id: string) => events(id) },
}));

// An account from before registration asked for names, unless a test
// gives it one.
let currentUser: { id: string; email: string; first_name?: string | null } = {
  id: "u1",
  email: "nora@acme.example",
};
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => currentUser,
}));

// The box has its own tests; here it is only a place on the page.
vi.mock("@/components/intentions/compact-composer", () => ({
  CompactIntentionComposer: () => <div data-testid="composer" />,
}));

// The card has its own tests (leka-insights.test.tsx); here it is only a
// place on the page.
vi.mock("@/components/insights/leka-insights", () => ({
  LekaInsights: () => <div data-testid="leka-insights" />,
}));

const { Overview } = await import("@/components/overview/overview");

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function source(overrides: Partial<Source>): Source {
  return {
    id: crypto.randomUUID(),
    type: "github",
    display_name: "acme/backend",
    status: "active",
    config: {},
    capabilities: [],
    source_metadata: {},
    health_status: "healthy",
    last_health_check_at: minutesAgo(4),
    last_error: null,
    sync_status: "idle",
    last_sync_at: minutesAgo(4),
    credentials: null,
    created_by: null,
    created_at: minutesAgo(600),
    updated_at: minutesAgo(4),
    ...overrides,
  } as Source;
}

const BACKEND = source({ display_name: "acme/backend" });
const RUNBOOKS = source({ type: "confluence", display_name: "Runbooks space", status: "error" });
const PLATFORM = source({
  type: "slack",
  display_name: "#platform",
  status: "draft",
  last_sync_at: null,
  last_health_check_at: null,
});

function event(on: Source, type: SourceEvent["type"], minutes: number) {
  return {
    id: crypto.randomUUID(),
    type,
    actor_user_id: null,
    payload: {},
    created_at: minutesAgo(minutes),
    source_id: on.id,
  } as unknown as SourceEvent;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LocaleProvider>
        <Overview />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

function candidate(overrides: Partial<Candidate>): Candidate {
  return {
    id: crypto.randomUUID(),
    analyzer: "enrich_owner",
    family: "organisation",
    code: "enrichment.owner",
    method: "rules",
    kind: "relationship",
    subject: { type: "entity", id: crypto.randomUUID(), name: "postgres-prod", kind: "database" },
    relationship: "owned_by",
    start: null,
    end: null,
    attribute: null,
    value: null,
    current: null,
    overrides: false,
    statement: "Platform likely owns postgres-prod.",
    params: {
      name: "postgres-prod",
      team: "Platform",
      how: "maintainers",
      members: 2,
      maintainers: 2,
    },
    confidence: 0.85,
    status: "proposed",
    decided_via: null,
    decided_at: null,
    first_seen_at: minutesAgo(30),
    last_seen_at: minutesAgo(5),
    occurrences: 1,
    ...overrides,
  };
}

beforeEach(() => {
  environment.get.mockReset().mockResolvedValue({
    services: 4,
    services_operational: 3,
    services_deduced: 2,
    services_external: 1,
    services_unknown: 0,
    incidents_open: 1,
    services_impacted: 1,
    attention: [
      { kind: "open_incident", level: "high", count: 1, entity: null, detail: "Billing API" },
      { kind: "unmonitored_services", level: "info", count: 2, entity: null, detail: null },
    ],
  });
  proposed.mockReset().mockResolvedValue({ data: [], next_cursor: null });
  list.mockReset().mockResolvedValue({ data: [BACKEND, RUNBOOKS, PLATFORM] });
  events.mockReset().mockImplementation(async (id: string) => ({
    data:
      id === BACKEND.id
        ? [event(BACKEND, "activated", 30), event(BACKEND, "test_succeeded", 31)]
        : id === RUNBOOKS.id
          ? [event(RUNBOOKS, "test_failed", 5)]
          : [],
  }));
});

describe("the overview", () => {
  it("greets the person and says what their sources need", async () => {
    mount();

    expect(screen.getByRole("heading", { level: 1, name: "Bonjour Nora," })).toBeVisible();
    expect(await screen.findByText("1 source demande votre attention.")).toBeVisible();
  });

  it("greets by the first name given at registration, not the address", async () => {
    currentUser = { id: "u2", email: "halimi.ha13@acme.example", first_name: "Haitam" };
    try {
      mount();

      expect(screen.getByRole("heading", { level: 1, name: "Bonjour Haitam," })).toBeVisible();
    } finally {
      currentUser = { id: "u1", email: "nora@acme.example" };
    }
    // Let the page's own loading settle before the next test mounts.
    expect(await screen.findByText("1 source demande votre attention.")).toBeVisible();
  });

  it("counts the connected sources, and only them", async () => {
    mount();

    // backend (active) and Runbooks (on, in error) are connected; the draft is not.
    expect(await screen.findByTestId("kpi-sources")).toHaveTextContent("2");
    expect(screen.getByText("2 / 3 sources")).toBeVisible();
  });

  it("lists the real sources, what needs a look first", async () => {
    mount();

    const rows = await screen.findAllByTestId("source-row");
    expect(rows.map((row) => within(row).getByRole("img").getAttribute("aria-label"))).toEqual([
      "Confluence",
      "GitHub",
      "Slack",
    ]);
    expect(within(rows[0]).getByText("Erreur")).toBeVisible();
    expect(within(rows[1]).getByText("Synchronisé")).toBeVisible();
    expect(within(rows[1]).getByText("Il y a 4 min")).toBeVisible();
    expect(within(rows[2]).getByText("À configurer")).toBeVisible();
    expect(within(rows[2]).getByText("Pas encore")).toBeVisible();
  });

  it("tells the sources' recent history, newest first", async () => {
    mount();

    const rows = await screen.findAllByTestId("activity-row");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Échec du test de connexion"),
      expect.stringContaining("Source activée"),
      expect.stringContaining("Connexion vérifiée"),
    ]);
    // The moment itself, machine-readable, as the knowledge timeline gives it.
    const time = rows[0].querySelector("time");
    expect(time).not.toBeNull();
    expect(Date.parse(time?.getAttribute("dateTime") ?? "")).toBeGreaterThan(Date.now() - 6 * 60_000);
    expect(time).toHaveAttribute("title");
  });

  it("never shows the mockup's figures", async () => {
    mount();
    await screen.findAllByTestId("source-row");

    for (const mocked of ["98 %", "47 / 48 services", "Payment API", "Rollback", "Confiance élevée"]) {
      expect(screen.queryByText(new RegExp(mocked))).not.toBeInTheDocument();
    }
    expect(screen.getByText("Rien à valider pour le moment.")).toBeVisible();
  });

  it("says the environment's state as enrichment made it", async () => {
    mount();
    expect(await screen.findByTestId("kpi-services")).toHaveTextContent("3");
    const [services, attention, incidents] = screen.getAllByTestId("kpi-tile");
    // Deduced from what runs them, said so; the external ones apart — as
    // the architecture counts them.
    expect(services).toHaveTextContent(
      "sur 4 services · état déduit de leur hébergement, non mesuré · 1 externe à part",
    );
    // An incident is a point; services nothing measures are worth knowing,
    // not an alarm.
    expect(within(attention).getByTestId("kpi-attention")).toHaveTextContent("1");
    expect(attention).toHaveTextContent("Billing API");
    expect(within(incidents).getByTestId("kpi-incidents")).toHaveTextContent("1");
    expect(incidents).toHaveTextContent("1 service touché");
    // This week's events, and no open contradiction.
    expect(await screen.findByText("42")).toBeVisible();
  });

  it("says what is only worth knowing apart from what needs someone", async () => {
    environment.get.mockResolvedValue({
      services: 6,
      services_operational: 6,
      services_deduced: 6,
      services_external: 1,
      services_unknown: 0,
      incidents_open: 0,
      services_impacted: 0,
      attention: [
        { kind: "unmonitored_services", level: "info", count: 6, entity: null, detail: null },
      ],
    });
    mount();
    const [services, attention] = await screen.findAllByTestId("kpi-tile");
    expect(within(services).getByTestId("kpi-services")).toHaveTextContent("6");
    expect(within(attention).getByTestId("kpi-attention")).toHaveTextContent("0");
    expect(attention).toHaveTextContent("Rien d'urgent · 6 services sans monitoring");
  });

  it("says a state nothing tells as unknown, never as zero", async () => {
    environment.get.mockResolvedValue({
      services: 3,
      services_operational: 0,
      services_deduced: 0,
      services_external: 0,
      services_unknown: 3,
      incidents_open: 0,
      services_impacted: 0,
      attention: [],
    });
    mount();
    const [services] = await screen.findAllByTestId("kpi-tile");
    // Not « — »: that is « not loaded yet ».
    expect(within(services).getByTestId("kpi-services")).toHaveTextContent("?");
    expect(services).toHaveTextContent("sur 3 services · 3 d'état inconnu");
  });

  it("says a workspace with no service, and nothing open", async () => {
    environment.get.mockResolvedValue({
      services: 0,
      services_operational: 0,
      services_deduced: 0,
      services_external: 0,
      services_unknown: 0,
      incidents_open: 0,
      services_impacted: 0,
      attention: [],
    });
    mount();
    const [services, attention, incidents] = await screen.findAllByTestId("kpi-tile");
    expect(services).toHaveTextContent("Aucun service déclaré par vos sources");
    expect(attention).toHaveTextContent("Rien à signaler");
    expect(incidents).toHaveTextContent("Aucun incident ouvert");
  });

  it("says so when the sources cannot be read", async () => {
    list.mockRejectedValue(new Error("down"));
    mount();

    expect(
      await screen.findByText("Impossible de charger vos sources pour le moment."),
    ).toBeVisible();
  });

  it("invites a first source when there is none", async () => {
    list.mockResolvedValue({ data: [] });
    mount();

    expect(await screen.findByText("Connectez une première source pour commencer.")).toBeVisible();
    expect(screen.getByText("Aucune source connectée pour l'instant.")).toBeVisible();
    expect(screen.getByText("Aucune source n'est encore suivie.")).toBeVisible();
  });

  it("lists what LEKA proposes, waiting on someone, each leading to it", async () => {
    const owner = candidate({});
    const code = candidate({
      analyzer: "enrich_code",
      family: "relationship",
      code: "enrichment.code",
      subject: { type: "entity", id: crypto.randomUUID(), name: "user-service", kind: "service" },
      params: { name: "user-service", repository: "acme/user-service", match: "same" },
      confidence: 0.8,
    });
    const more = [1, 2].map((n) => candidate({ params: { name: `db-${n}`, team: "Core" } }));
    proposed.mockResolvedValue({ data: [owner, code, ...more], next_cursor: null });
    mount();

    const lines = within(await screen.findByTestId("approvals-waiting")).getAllByRole("listitem");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveTextContent("Platform est responsable de postgres-prod");
    expect(lines[0]).toHaveTextContent(
      "2 des 2 personnes qui le maintiennent sont membres de Platform · 85 %",
    );
    expect(within(lines[0]).getByRole("link")).toHaveAttribute("href", `/approvals/${owner.id}`);
    expect(lines[1]).toHaveTextContent("acme/user-service est le code de user-service");
    expect(screen.getByText("4 éléments en attente")).toBeVisible();
    expect(screen.queryByText("Rien à valider pour le moment.")).not.toBeInTheDocument();
  });
});
