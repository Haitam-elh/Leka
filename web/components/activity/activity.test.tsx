/**
 * Activité (LEKA-383): what happened in the environment and what LEKA did,
 * laid out as mockup 08 — every figure the workspace's own.
 *
 * What these protect: the five figures, each against the period before — a
 * percentage when there was enough before, the difference when there was
 * little, an incident fewer said as good news; the days drawn, stacked by
 * type, and the split; each event worded in French from what it is — a
 * build's changes, a thing gone from the sources, an incident on a
 * service, a finding as Insights words it, a source failing, a decision
 * and who took it — each leading to what it is about; filtered by type
 * and by origin; the services most concerned and who decided most, named
 * as the shell names them; the evolution insights in the banner; only
 * who may approve can ask a rebuild; a period with nothing says so; a
 * failure can be read again.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Activity, ActivityItem } from "@/lib/activity";
import type { Finding } from "@/lib/insights";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({ read: vi.fn(), trends: vi.fn() }));
const operations = vi.hoisted(() => ({ rebuild: vi.fn() }));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:approve"] }));

vi.mock("@/lib/activity", async (original) => ({
  ...(await original<typeof import("@/lib/activity")>()),
  activity: api,
}));
vi.mock("@/lib/evolution", async (original) => ({
  ...(await original<typeof import("@/lib/evolution")>()),
  evolution: operations,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { ActivityScreen } = await import("@/components/activity/activity");
const { delta, personName, wordActivity } = await import("@/components/activity/items");
const { DICTIONARIES } = await import("@/lib/i18n/dictionaries");

const PAYMENT = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const REDIS = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const SOURCE = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const NORA = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const INCIDENT = "4c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const t = DICTIONARIES.fr;

function item(overrides: Partial<ActivityItem>): ActivityItem {
  return {
    id: crypto.randomUUID(),
    at: hoursAgo(1),
    category: "information",
    kind: "model_built",
    count: 1,
    subject: null,
    params: {},
    by: null,
    by_name: null,
    via: "source",
    ...overrides,
  };
}

const service = (id: string, name: string) => ({
  type: "entity" as const,
  id,
  name,
  kind: "service",
});

const LATEST: ActivityItem[] = [
  item({
    kind: "restore",
    category: "action",
    subject: service(PAYMENT, "payment-api"),
    params: { version: 3, status: "applied" },
    by: NORA,
    by_name: "nora@acme.example",
    via: "person",
  }),
  item({
    kind: "finding",
    category: "alert",
    subject: { type: "entity", id: REDIS, name: "redis-sessions", kind: "infra_resource" },
    params: {
      code: "evolution.removed_relied",
      category: "evolution",
      severity: "medium",
      statement: "redis-sessions is no longer shown by any source.",
      params: {
        name: "redis-sessions",
        names: ["auth-service"],
        recommendation: "confirm_removal",
        insight: "risk",
      },
    },
    via: "leka",
  }),
  item({
    kind: "source_event",
    category: "alert",
    subject: { type: "source", id: SOURCE, name: "acme-eu", kind: "datadog" },
    params: { type: "sync_failed", name: "acme-eu" },
  }),
  item({
    kind: "incident",
    category: "incident",
    at: hoursAgo(25),
    subject: service(PAYMENT, "payment-api"),
    params: { name: "payment-api p99 latency above 2s", event_id: INCIDENT, severity: "sev2" },
  }),
  item({
    kind: "model_built",
    at: hoursAgo(30),
    count: 6,
    params: { created: 2, relationships_added: 4, names: ["OPS-1841"] },
  }),
  item({
    kind: "entity_removed",
    at: hoursAgo(144),
    subject: { type: "entity", id: REDIS, name: "redis-sessions", kind: "infra_resource" },
    params: { name: "redis-sessions" },
  }),
];

function bucket(day: string, counts: Partial<Record<string, number>> = {}) {
  return { day, information: 0, action: 0, alert: 0, incident: 0, ...counts };
}

const ACTIVITY: Activity = {
  since: hoursAgo(168),
  until: hoursAgo(0),
  timezone: "Europe/Paris",
  stats: {
    events: { value: 36, previous: 2 },
    actions: { value: 22, previous: 20 },
    incidents: { value: 1, previous: 3 },
    waiting: 4,
    people: { value: 1, previous: 0 },
  },
  buckets: [
    bucket("2026-10-01", { information: 2 }),
    bucket("2026-10-02"),
    bucket("2026-10-03", { information: 1, incident: 1 }),
    bucket("2026-10-04", { action: 3, alert: 17 }),
  ],
  categories: { information: 15, action: 3, alert: 17, incident: 1 },
  latest: LATEST,
  top: [{ subject: service(PAYMENT, "payment-api"), count: 10, previous: 1 }],
  people: [{ user_id: NORA, name: "nora@acme.example", role: "owner", count: 2, previous: 0 }],
};

function evolutionFinding(): Finding {
  return {
    id: crypto.randomUUID(),
    analyzer: "evolution_ownership",
    analyzer_version: 1,
    category: "evolution",
    code: "evolution.owner_changed",
    params: {
      name: "user-service",
      before: ["Nadia Kowalski"],
      after: ["Thomas Berger"],
      recommendation: "confirm_owner",
    },
    statement: "user-service changed owner this month.",
    severity: "low",
    rank: 135,
    confidence: 1,
    subject: { type: "entity", id: PAYMENT, name: "user-service", kind: "service" },
    status: "open",
    first_seen_at: hoursAgo(1),
    last_seen_at: hoursAgo(1),
    resolved_at: null,
    occurrences: 1,
  };
}

function mount() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ActivityScreen />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "intention:approve"];
  api.read.mockResolvedValue(ACTIVITY);
  api.trends.mockResolvedValue({ data: [evolutionFinding()], next_cursor: null });
  operations.rebuild.mockResolvedValue({ id: crypto.randomUUID(), status: "queued" });
});

describe("Activité", () => {
  it("shows the five figures against the period before", async () => {
    mount();
    const stats = await screen.findByTestId("activity-stats");
    expect(within(stats).getByTestId("activity-stat-events")).toHaveTextContent("36");
    // Two before: the difference, not +1700 %.
    expect(within(stats).getByText("+34")).toBeInTheDocument();
    expect(within(stats).getByText("+10 %")).toBeInTheDocument();
    // Fewer incidents is good news.
    expect(within(stats).getByText("−2").closest("span")).toHaveClass("text-state-success");
    expect(within(stats).getByTestId("activity-stat-waiting")).toHaveTextContent("4");
    expect(api.read).toHaveBeenCalledWith(7);
  });

  it("draws the days stacked by type, and the split", async () => {
    mount();
    expect(await screen.findAllByTestId("activity-bar")).toHaveLength(4);
    const split = screen.getByTestId("activity-split");
    expect(within(split).getByText("47 %")).toBeInTheDocument();
    expect(within(split).getByRole("img")).toHaveAccessibleName("36 événements");
  });

  it("words each event and leads to what it is about", async () => {
    mount();
    const latest = await screen.findByTestId("activity-latest");
    expect(
      within(latest).getByRole("link", { name: /Version 3 de payment-api restaurée/ }),
    ).toHaveAttribute("href", `/environment/services/${PAYMENT}/history`);
    expect(within(latest).getByText("par Nora")).toBeInTheDocument();
    expect(
      within(latest).getByText("redis-sessions a disparu de vos sources"),
    ).toBeInTheDocument();
    expect(within(latest).getByRole("link", { name: /Synchronisation en échec/ })).toHaveAttribute(
      "href",
      `/sources/${SOURCE}`,
    );
    expect(
      within(latest).getByRole("link", { name: /Incident détecté sur payment-api/ }),
    ).toHaveAttribute("href", `/environment/incidents/${INCIDENT}`);
    expect(within(latest).getByText("Modèle mis à jour")).toBeInTheDocument();
    expect(
      within(latest).getByText("OPS-1841 · 2 créés, 4 relations ajoutées"),
    ).toBeInTheDocument();
    expect(
      within(latest).getByText("redis-sessions n'apparaît plus dans vos sources"),
    ).toBeInTheDocument();
  });

  it("filters by type and by origin", async () => {
    const user = userEvent.setup();
    mount();
    const latest = await screen.findByTestId("activity-latest");
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(await screen.findByRole("option", { name: "Incidents" }));
    await waitFor(() => expect(within(latest).getAllByRole("listitem")).toHaveLength(1));
    expect(within(latest).getByText("Incident détecté sur payment-api")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(await screen.findByRole("option", { name: "Tous les types" }));
    await user.click(screen.getByRole("combobox", { name: "Origine" }));
    await user.click(await screen.findByRole("option", { name: "Personnes" }));
    await waitFor(() => expect(within(latest).getAllByRole("listitem")).toHaveLength(1));
    expect(within(latest).getByText(/restaurée/)).toBeInTheDocument();
  });

  it("names the services most concerned and who decided most", async () => {
    mount();
    const top = await screen.findByTestId("activity-top");
    expect(within(top).getByRole("link", { name: /payment-api/ })).toHaveAttribute(
      "href",
      `/environment/services/${PAYMENT}`,
    );
    expect(within(top).getByText("+9")).toBeInTheDocument();
    const people = screen.getByTestId("activity-people");
    expect(within(people).getByText("Nora")).toBeInTheDocument();
    expect(within(people).getByText("Propriétaire")).toBeInTheDocument();
  });

  it("says what the model's course shows in the banner", async () => {
    mount();
    const trend = await screen.findByTestId("activity-trend");
    expect(trend).toHaveTextContent("user-service a changé de responsable");
    expect(trend).toHaveTextContent(
      "Nadia Kowalski → Thomas Berger · Confirmer le nouveau responsable",
    );
    expect(screen.getByRole("link", { name: /Créer une intention/ })).toHaveAttribute(
      "href",
      "/intentions/new",
    );
  });

  it("lets who may approve ask a rebuild, and nobody else", async () => {
    const user = userEvent.setup();
    const { unmount } = mount();
    await user.click(await screen.findByRole("button", { name: "Plus d'actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Reconstruire le modèle" }));
    await waitFor(() => expect(operations.rebuild).toHaveBeenCalledWith({ reason: null }));
    unmount();

    permissions.value = ["workspace:read"];
    mount();
    await screen.findByTestId("activity-stats");
    expect(screen.queryByRole("button", { name: "Plus d'actions" })).not.toBeInTheDocument();
  });

  it("says when nothing happened, and when it cannot be read", async () => {
    api.read.mockResolvedValueOnce({
      ...ACTIVITY,
      stats: { ...ACTIVITY.stats, events: { value: 0, previous: 0 } },
      latest: [],
      top: [],
      people: [],
    });
    api.trends.mockResolvedValueOnce({ data: [], next_cursor: null });
    const { unmount } = mount();
    expect(await screen.findAllByText("Rien ne s'est passé sur cette période.")).toHaveLength(2);
    expect(screen.getByText(/Personne n'a encore décidé/)).toBeInTheDocument();
    expect(await screen.findByText(/Aucune tendance notable/)).toBeInTheDocument();
    unmount();

    // Down twice: once, and once more when asked again.
    api.read.mockRejectedValueOnce(new Error("down")).mockRejectedValueOnce(new Error("down"));
    mount();
    const retry = await screen.findByRole("button", { name: "Réessayer" }, { timeout: 4000 });
    await userEvent.setup().click(retry);
    expect(await screen.findByTestId("activity-stats")).toBeInTheDocument();
  });
});

describe("the words", () => {
  it("says a difference when there was little before", () => {
    expect(delta({ value: 0, previous: 0 })).toBeNull();
    expect(delta({ value: 5, previous: 0 })).toEqual({ text: "+5", up: true });
    expect(delta({ value: 1, previous: 3 })).toEqual({ text: "−2", up: false });
    expect(delta({ value: 27, previous: 20 })).toEqual({ text: "+35 %", up: true });
    expect(delta({ value: 20, previous: 20 })).toEqual({ text: "0 %", up: true });
  });

  it("names a person as the shell does", () => {
    expect(personName("nora@acme.example")).toBe("Nora");
    expect(personName("Thomas Berger")).toBe("Thomas Berger");
  });

  it("words a decision, a proposal and a conflict in French", () => {
    const decision = wordActivity(
      t,
      item({
        kind: "decision",
        category: "action",
        subject: service(PAYMENT, "postgres-prod"),
        params: { status: "accepted", family: "organisation", candidate_id: "c-1" },
        via: "policy",
      }),
    );
    expect(decision).toEqual({
      title: "Enrichissement validé",
      detail: "postgres-prod · Organisation",
      href: "/approvals/c-1",
    });
    const conflict = wordActivity(
      t,
      item({
        kind: "conflict",
        category: "alert",
        subject: service(PAYMENT, "payment-api"),
        params: { about: "sla", conflict_id: "k-1" },
      }),
    );
    expect(conflict.href).toBe("/approvals/k-1?kind=conflict");
    expect(conflict.detail).toBe("SLA · payment-api");
  });
});
