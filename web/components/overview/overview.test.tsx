/**
 * The overview: what needs someone first, the workspace's real figures
 * (LEKA-442: a decision, something in trouble, a request under way; then
 * what moved and whether what LEKA sees can be trusted).
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
import { sampleJourney } from "@/lib/intentions/journey-sample";

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
  activity: {
    read: async () => ({
      stats: { events: { value: 42, previous: 30 } },
      // The same events Activité tells (LEKA-438), newest first.
      latest: [
        {
          id: "e1",
          at: new Date(Date.now() - 2 * 60_000).toISOString(),
          category: "information",
          kind: "model_built",
          count: 1,
          subject: null,
          params: {},
          by: null,
          by_name: null,
          via: "source",
        },
      ],
    }),
  },
}));

const monitoring = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/twin", async (original) => ({
  ...(await original<typeof import("@/lib/twin")>()),
  monitoring,
}));
const underWay = vi.hoisted(() => vi.fn());
vi.mock("@/lib/intentions/api", async (original) => {
  const real = await original<typeof import("@/lib/intentions/api")>();
  return { ...real, intentions: { ...real.intentions, list: () => underWay() } };
});

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

// So has the first-steps card (first-steps.test.tsx): here, its place.
vi.mock("@/components/overview/first-steps", () => ({
  FirstStepsCard: () => <div data-testid="first-steps" />,
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

const read = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function twin(state: string, more: Record<string, unknown> = {}) {
  return {
    state,
    basis: "none",
    reason: "no_signal",
    observed_at: read(7),
    signal: [],
    fresh: true,
    was: null,
    certainty: "confirmed",
    incident: null,
    ...more,
  };
}

function node(name: string, state: string, more: Record<string, unknown> = {}) {
  return {
    id: name,
    type: "service",
    layer: "services",
    name,
    status: null,
    entity_id: crypto.randomUUID(),
    key: name,
    detail: null,
    count: 1,
    environment: null,
    team: null,
    twin: twin(state, more),
  };
}

function twinSource(name: string, state: string, category = "code") {
  return {
    id: crypto.randomUUID(),
    kind: "github",
    name,
    category,
    state,
    last_synced_at: state === "never" ? null : read(7),
    error: state === "error" ? "401 Unauthorized" : null,
    webhooks: false,
  };
}

/** A workspace partly connected: GitHub read, Runbooks failing, no
 * monitoring tool — payment-api degraded by an incident, the rest silent. */
function partlyConnected() {
  const github = twinSource("acme/backend", "read");
  const runbooks = twinSource("Runbooks space", "error", "docs");
  return {
    services: 3,
    services_operational: 0,
    services_deduced: 0,
    services_external: 0,
    services_unknown: 2,
    incidents_open: 1,
    services_impacted: 1,
    attention: [],
    events: [],
    nodes: [
      node("auth-service", "not_covered", { reason: "no_monitoring_source" }),
      node("payment-api", "degraded", {
        basis: "measured",
        reason: "incident_open",
        signal: ["OPS board"],
        incident: { id: "i1", key: "OPS-1841", name: "p99 above 2s", severity: "sev2" },
      }),
      node("user-service", "unknown"),
    ],
    states: {
      unavailable: 0,
      degraded: 1,
      stale: 0,
      unknown: 1,
      not_covered: 1,
      operational: 0,
    },
    freshness: { last_read_at: read(7), every_minutes: 60, late: false, webhooks: false },
    coverage: [
      { part: "applications", covered: true, sources: [github.id] },
      { part: "health", covered: false, sources: [] },
    ],
    sources: [github, runbooks],
  };
}

beforeEach(() => {
  environment.get.mockReset().mockResolvedValue(partlyConnected());
  monitoring.get.mockReset().mockResolvedValue({
    entitlement: {
      plan: "free",
      proactive: false,
      alerts: [],
      contractual: false,
      provisional: true,
      alerts_from: "starter",
      email_from: "growth",
    },
    open: [],
    ended: [],
  });
  underWay.mockReset().mockResolvedValue({ data: [], next_cursor: null });
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
  it("greets the person and says what needs them", async () => {
    mount();

    expect(screen.getByRole("heading", { level: 2, name: "Bonjour Nora," })).toBeVisible();
    // What is in trouble first (LEKA-442), then the sources.
    expect(await screen.findByText("1 élément est en difficulté.")).toBeVisible();
  });

  it("greets by the first name given at registration, not the address", async () => {
    currentUser = { id: "u2", email: "halimi.ha13@acme.example", first_name: "Haitam" };
    try {
      mount();

      expect(screen.getByRole("heading", { level: 2, name: "Bonjour Haitam," })).toBeVisible();
    } finally {
      currentUser = { id: "u1", email: "nora@acme.example" };
    }
    // Let the page's own loading settle before the next test mounts.
    expect(await screen.findByText("1 élément est en difficulté.")).toBeVisible();
  });

  it("puts first what needs someone: a decision, what is wrong, a request under way", async () => {
    mount();
    const now = await screen.findByTestId("overview-now");
    expect(within(now).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "À valider",
      "Ce qui ne va pas",
      "Mes intentions en cours",
    ]);
    const context = screen.getByTestId("overview-context");
    expect(within(context).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Activité récente",
      "Fraîcheur et couverture",
      "Insights LEKA",
    ]);
  });

  it("says what is wrong with how it is known, and what nothing says apart", async () => {
    mount();
    const trouble = await screen.findByTestId("overview-trouble");
    const [row] = within(trouble).getAllByRole("listitem");
    expect(row).toHaveAttribute("data-state", "degraded");
    expect(row).toHaveTextContent("payment-api");
    expect(row).toHaveTextContent("incident « OPS-1841 » ouvert · mesuré · par OPS board");
    expect(within(row).getByRole("link", { name: "Analyser" })).toHaveAttribute(
      "href",
      `/intentions/new?q=${encodeURIComponent("Pourquoi payment-api est dégradé ?")}`,
    );
    // Silence is never health.
    expect(screen.getByTestId("overview-silent")).toHaveTextContent(
      "2 éléments n'ont aucun signal : leur état n'est pas connu — ce n'est pas « sain ».",
    );
    expect(await screen.findByText("1 élément est en difficulté.")).toBeVisible();
  });

  it("on Free, says the alerts are a paid plan's — never one simulated", async () => {
    mount();
    expect(await screen.findByTestId("overview-alerts-limit")).toHaveTextContent(
      "Les alertes proactives sont incluses dès Starter.",
    );
    expect(screen.queryByTestId("overview-alerts")).not.toBeInTheDocument();
  });

  it("on a paid plan, says how many alerts are open", async () => {
    monitoring.get.mockResolvedValue({
      entitlement: {
        plan: "growth",
        proactive: true,
        alerts: ["in_app", "email"],
        contractual: false,
        provisional: true,
        alerts_from: "starter",
        email_from: "growth",
      },
      open: [{ id: "a1" }, { id: "a2" }],
      ended: [],
    });
    mount();
    expect(await screen.findByTestId("overview-alerts")).toHaveTextContent("2 alertes ouvertes.");
  });

  it("says how fresh what LEKA sees is, what fails and what no source covers", async () => {
    mount();
    const card = await screen.findByTestId("overview-freshness");
    expect(card).toHaveTextContent("Lu il y a 7 min");
    expect(card).toHaveTextContent("Sources lues toutes les 60 min — pas en temps réel");
    expect(card).toHaveTextContent("Runbooks space en échec");
    expect(card).toHaveTextContent("Non couvert : État des services.");
  });

  it("an environment read and covered says so, nothing in trouble", async () => {
    const all = partlyConnected();
    environment.get.mockResolvedValue({
      ...all,
      nodes: [node("payment-api", "operational", { basis: "measured", reason: "monitored_quiet" })],
      states: { ...all.states, degraded: 0, unknown: 0, not_covered: 0, operational: 1 },
      coverage: all.coverage.map((c) => ({ ...c, covered: true })),
      sources: [all.sources[0]],
    });
    mount();
    expect(
      await screen.findByText("Rien d'indisponible ni de dégradé selon les sources lues."),
    ).toBeVisible();
    expect(screen.queryByTestId("overview-silent")).not.toBeInTheDocument();
    expect(screen.getByTestId("overview-freshness")).toHaveTextContent(
      "Toutes les sources sont lues et chaque partie de l'environnement est couverte.",
    );
  });

  it("lists the intentions under way, each leading to it, in its journey's words", async () => {
    underWay.mockResolvedValue({
      data: [
        {
          id: "i1",
          title: "Pourquoi payment-api est lente ?",
          status: "awaiting_decision",
          journey: sampleJourney("awaiting_decision"),
        },
      ],
      next_cursor: null,
    });
    mount();
    const list = await screen.findByTestId("overview-intentions");
    const link = within(list).getByRole("link");
    expect(link).toHaveAttribute("href", "/intentions/i1");
    expect(link).toHaveTextContent("Pourquoi payment-api est lente ?");
    // The same state as on the list and its page (LEKA-443).
    expect(within(link).getByTestId("intention-status")).toHaveTextContent("Décision requise");
  });

  it("tells what Activité tells, the same events worded the same way", async () => {
    mount();

    const [row] = await screen.findAllByTestId("activity-row");
    expect(row).toHaveTextContent("Information");
    // The moment itself, machine-readable, as the knowledge timeline gives it.
    const time = row.querySelector("time");
    expect(time).not.toBeNull();
    expect(Date.parse(time?.getAttribute("dateTime") ?? "")).toBeGreaterThan(Date.now() - 6 * 60_000);
    expect(time).toHaveAttribute("title");
  });

  it("never shows the mockup's figures", async () => {
    mount();
    await screen.findByTestId("overview-trouble");

    for (const mocked of ["98 %", "47 / 48 services", "Payment API", "Rollback", "Confiance élevée"]) {
      expect(screen.queryByText(new RegExp(mocked))).not.toBeInTheDocument();
    }
    expect(screen.getByText("Rien à valider pour le moment.")).toBeVisible();
  });

  it("says so when the sources cannot be read", async () => {
    list.mockRejectedValue(new Error("down"));
    mount();

    expect(
      await screen.findByText("Impossible de charger vos sources pour le moment."),
    ).toBeVisible();
  });

  it("invites a first source when there is none: nothing read, nothing in trouble", async () => {
    list.mockResolvedValue({ data: [] });
    environment.get.mockResolvedValue({
      ...partlyConnected(),
      nodes: [],
      states: {},
      coverage: [],
      sources: [],
      freshness: { last_read_at: null, every_minutes: 60, late: false, webhooks: false },
    });
    mount();

    expect(await screen.findByText("Connectez une première source pour commencer.")).toBeVisible();
    expect(screen.getByText("Aucune source connectée pour l'instant.")).toBeVisible();
    // The first steps above the question, where a newcomer looks (LEKA-445).
    const steps = await screen.findByTestId("first-steps");
    expect(steps.compareDocumentPosition(screen.getByTestId("composer")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
