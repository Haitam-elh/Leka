/**
 * The overview: the mockup's layout, the workspace's real figures.
 *
 * What these protect is the decision of 2026-09-25 — real data, or an
 * honest empty state, never the mockup's numbers. The mockup's "98 %",
 * "47 / 48 services" and "3 incidents" must not reach a customer; the
 * sources LEKA actually reads must.
 */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Source, SourceEvent } from "@/lib/sources";

const list = vi.fn();
const events = vi.fn();

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
  render(
    <LocaleProvider>
      <Overview />
    </LocaleProvider>,
  );
}

beforeEach(() => {
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
    expect(await screen.findByText("1 source(s) demandent votre attention.")).toBeVisible();
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
    expect(await screen.findByText("1 source(s) demandent votre attention.")).toBeVisible();
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
    // Service health and incidents are not measured: said, not invented.
    expect(screen.getAllByText("Aucune supervision connectée")).toHaveLength(3);
    expect(screen.getByText("Rien à valider pour le moment.")).toBeVisible();
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
});
