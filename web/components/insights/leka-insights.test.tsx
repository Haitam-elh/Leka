/**
 * "Insights LEKA" (LEKA-377): what LEKA's analyses concluded, on the
 * overview and on Mon environnement.
 *
 * What these protect: the most pressing open findings, worded in French
 * from their code and values — never the API's English when the code is
 * known — each leading to the sheet of what it is about, a context to
 * nothing; the rest counted; before any analysis it says so, after one
 * that found nothing that too; when the latest analysis ran; whoever may
 * ask LEKA something can analyse now — the button waits for the run, says
 * when one was already under way — and nobody else sees it; a summary that
 * cannot be read says so and can be read again.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Finding, IntelligenceSummary } from "@/lib/insights";
import { waiting } from "@/lib/insights-queries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const api = vi.hoisted(() => ({ summary: vi.fn(), analyse: vi.fn() }));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:create"] as string[] }));

vi.mock("@/lib/insights", async (original) => ({
  ...(await original<typeof import("@/lib/insights")>()),
  insights: api,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));

const { LekaInsights } = await import("@/components/insights/leka-insights");

const DATABASE = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const SERVICE = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CONTEXT = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: crypto.randomUUID(),
    analyzer: "dependency_concentration",
    analyzer_version: 1,
    category: "architecture",
    code: "dependency.concentration",
    params: {},
    statement: "An English sentence.",
    severity: "medium",
    rank: 250,
    confidence: 1,
    subject: { type: "entity", id: DATABASE, name: "postgresql", kind: "database" },
    status: "open",
    first_seen_at: hoursAgo(5),
    last_seen_at: hoursAgo(1),
    resolved_at: null,
    occurrences: 2,
    ...overrides,
  };
}

const RUN: NonNullable<IntelligenceSummary["latest"]> = {
  id: crypto.randomUUID(),
  status: "succeeded",
  trigger: "model",
  requested_by: null,
  requested: [],
  started_at: hoursAgo(2),
  finished_at: hoursAgo(2),
  model_built_at: hoursAgo(2),
  job_run_id: null,
  counts: {},
  error: null,
};

const CONCENTRATION = finding({
  severity: "high",
  rank: 340,
  params: {
    name: "postgresql",
    kind: "database",
    dependents: 4,
    status: "unknown",
    watched: false,
    deduced: true,
  },
});
const NO_TEAM = finding({
  analyzer: "ownership",
  category: "organisation",
  code: "ownership.no_owner",
  params: { name: "Leka API", kind: "api", dependents: 0, maintainers: ["Haitam"] },
  subject: { type: "entity", id: SERVICE, name: "Leka API", kind: "service" },
});
const BEHIND = finding({
  analyzer: "context_health",
  category: "context",
  code: "context.behind",
  severity: "low",
  rank: 120,
  params: { title: "Payment API", pending: 6, version: 3 },
  subject: { type: "context", id: CONTEXT, name: "Payment API", kind: "context" },
});

function summary(overrides: Partial<IntelligenceSummary> = {}): IntelligenceSummary {
  return {
    open: { high: 1, medium: 3, low: 1 },
    top: [CONCENTRATION, NO_TEAM, BEHIND],
    latest: RUN,
    ...overrides,
  };
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LocaleProvider>
        <LekaInsights />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "intention:create"];
  api.summary.mockResolvedValue(summary());
  api.analyse.mockResolvedValue({ queued: true });
});

describe("Insights LEKA", () => {
  it("words the most pressing findings, each leading to what it is about", async () => {
    mount();

    const lines = within(await screen.findByTestId("insights-findings")).getAllByRole("listitem");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveTextContent("4 éléments dépendent de postgresql");
    expect(lines[0]).toHaveTextContent("Important · Rien ne le surveille — son état est déduit");
    expect(within(lines[0]).getByRole("link")).toHaveAttribute(
      "href",
      `/environment/databases/${DATABASE}`,
    );
    expect(lines[1]).toHaveTextContent("Aucun responsable nommé pour Leka API");
    expect(lines[1]).toHaveTextContent("Maintenu par Haitam");
    expect(within(lines[1]).getByRole("link")).toHaveAttribute(
      "href",
      `/environment/services/${SERVICE}`,
    );
    // A context has no page of its own: a line, not a link.
    expect(lines[2]).toHaveTextContent("Le contexte « Payment API » est en retard sur le modèle");
    expect(lines[2]).toHaveTextContent("6 changement(s) non pris en compte");
    expect(within(lines[2]).queryByRole("link")).not.toBeInTheDocument();
    // Never the API's English when the code is known.
    expect(screen.queryByText(/An English sentence/)).not.toBeInTheDocument();
    // The rest, counted.
    expect(screen.getByText("+ 2 autre(s) point(s) ouvert(s)")).toBeInTheDocument();
    expect(screen.getByText("Dernière analyse · Il y a 2 h")).toBeInTheDocument();
  });

  it("names fewer where it is told to, and counts the rest", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <LocaleProvider>
          <LekaInsights shown={2} />
        </LocaleProvider>
      </QueryClientProvider>,
    );

    const found = await screen.findByTestId("insights-findings");
    expect(within(found).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("+ 3 autre(s) point(s) ouvert(s)")).toBeInTheDocument();
  });

  it("says the English sentence of a code it does not know yet", async () => {
    api.summary.mockResolvedValue(
      summary({ top: [finding({ code: "change.impact", statement: "A change reached 3 things." })] }),
    );
    mount();

    expect(await screen.findByText("A change reached 3 things.")).toBeInTheDocument();
  });

  it("says when LEKA has not analysed yet, and when it found nothing", async () => {
    api.summary.mockResolvedValue(summary({ top: [], open: { high: 0, medium: 0, low: 0 }, latest: null }));
    const { unmount } = mount();
    expect(await screen.findByTestId("insights-empty")).toHaveTextContent(
      "LEKA n'a pas encore analysé votre environnement.",
    );
    unmount();

    api.summary.mockResolvedValue(summary({ top: [], open: { high: 0, medium: 0, low: 0 } }));
    mount();
    expect(await screen.findByTestId("insights-empty")).toHaveTextContent(
      "Rien à signaler : la dernière analyse n'a rien trouvé d'ouvert.",
    );
  });

  it("analyses now for who may ask LEKA something, and waits for the run", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByTestId("insights-analyse"));

    expect(api.analyse).toHaveBeenCalledOnce();
    const button = await screen.findByRole("button", { name: /Analyse en cours/ });
    expect(button).toBeDisabled();
  });

  it("says when an analysis was already under way", async () => {
    const user = userEvent.setup();
    api.analyse.mockResolvedValue({ queued: false });
    mount();

    await user.click(await screen.findByTestId("insights-analyse"));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Une analyse est déjà en cours : elle répondra.",
    );
  });

  it("offers no analysis to who may not ask LEKA something", async () => {
    permissions.value = ["workspace:read"];
    mount();

    await screen.findByTestId("insights-findings");
    expect(screen.queryByTestId("insights-analyse")).not.toBeInTheDocument();
  });

  it("says when the analyses cannot be read, and reads them again", async () => {
    const user = userEvent.setup();
    api.summary.mockRejectedValueOnce(new Error("down"));
    mount();

    const failed = await screen.findByTestId("insights-failed");
    expect(failed).toHaveTextContent("Les analyses de LEKA n'ont pas pu être lues.");
    await user.click(within(failed).getByRole("button", { name: "Réessayer" }));

    expect(await screen.findByTestId("insights-findings")).toBeInTheDocument();
    expect(api.summary).toHaveBeenCalledTimes(2);
  });
});

describe("waiting for a run asked for", () => {
  const asked = Date.parse("2026-10-05T12:00:00Z");
  const run = (started: string, status: (typeof RUN)["status"]) => ({
    ...summary(),
    latest: { ...RUN, started_at: started, status },
  });

  it("waits until a run started after the ask has finished, two minutes at most", () => {
    expect(waiting(run("2026-10-05T11:00:00Z", "succeeded"), asked, asked + 5_000)).toBe(true);
    expect(waiting(run("2026-10-05T12:00:03Z", "running"), asked, asked + 9_000)).toBe(true);
    expect(waiting(run("2026-10-05T12:00:03Z", "succeeded"), asked, asked + 9_000)).toBe(false);
    expect(waiting(run("2026-10-05T11:00:00Z", "succeeded"), asked, asked + 180_000)).toBe(false);
    expect(waiting(summary(), null)).toBe(false);
  });
});
