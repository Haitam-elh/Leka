/**
 * Knowledge quality (LEKA-381): Mon environnement's tab Qualité and the
 * card on a thing's sheet.
 *
 * What these protect: before any measure, the screen says when there will
 * be one — never a made-up score; the workspace's score, its level in
 * words, how it moved in 7 days, the things by level; each dimension, one
 * nothing measured said so; the trend's every point said to a screen
 * reader, and read on hover and by keyboard; the things known least well,
 * each leading to its sheet with what lowers it in words, filtered by
 * level through the API; the areas by column, team, application; on a
 * sheet, a thing not measured yet said so, one measured with its level,
 * since when, what lowers it and why it is held to medium.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { QualityDetail, QualityScore, QualitySummary } from "@/lib/knowledge-quality";

const api = vi.hoisted(() => ({ summary: vi.fn(), weakest: vi.fn(), one: vi.fn() }));

vi.mock("@/lib/knowledge-quality", async (original) => ({
  ...(await original<typeof import("@/lib/knowledge-quality")>()),
  knowledgeQuality: api,
}));

const { EntityQuality, QualityTab, QualityTrend } = await import(
  "@/components/environment/knowledge-quality"
);

const ORPHAN = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const TEAM = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const daysAgo = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString();

function score(overrides: Partial<QualityScore>): QualityScore {
  return {
    key: "workspace",
    scope: "workspace",
    subject: { type: "workspace", id: null, name: "workspace", kind: null },
    column: null,
    score: 0.72,
    level: "medium",
    completeness: 0.6,
    freshness: 0.9,
    consistency: 1,
    confidence: null,
    missing: [],
    areas: [],
    entities: 1,
    capped: null,
    measured_at: daysAgo(0.1),
    since: daysAgo(3),
    ...overrides,
  };
}

const WEAK = score({
  key: `entity:${ORPHAN}`,
  scope: "entity",
  subject: { type: "entity", id: ORPHAN, name: "orphan-worker", kind: "service" },
  column: "services",
  score: 0.41,
  level: "low",
  missing: [
    { code: "unseen", dimension: "freshness", weight: 1, detail: "…" },
    { code: "no_owner", dimension: "completeness", weight: 0.25, detail: "…" },
  ],
});

function point(days: number, value: number): QualitySummary["trend"][number] {
  return {
    measured_at: daysAgo(days),
    score: value,
    level: value >= 0.85 ? "high" : value >= 0.6 ? "medium" : "low",
    completeness: null,
    freshness: null,
    consistency: null,
    confidence: null,
  };
}

function summary(overrides: Partial<QualitySummary> = {}): QualitySummary {
  return {
    measured_at: daysAgo(0.1),
    workspace: score({ entities: 12 }),
    levels: { high: 7, medium: 4, low: 1 },
    columns: [
      score({
        key: "column:services",
        scope: "column",
        subject: { type: "column", id: null, name: "services", kind: "services" },
        score: 0.55,
        level: "low",
        entities: 5,
        missing: [{ code: "no_owner", count: 3 }],
      }),
    ],
    teams: [
      score({
        key: `team:${TEAM}`,
        scope: "team",
        subject: { type: "entity", id: TEAM, name: "Payments", kind: "team" },
        score: 0.9,
        level: "high",
        entities: 4,
      }),
    ],
    applications: [],
    weakest: [WEAK],
    trend: [point(20, 0.6), point(5, 0.67), point(0.1, 0.72)],
    change: 0.05,
    ...overrides,
  };
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.summary.mockResolvedValue(summary());
  api.weakest.mockResolvedValue({ data: [WEAK], next_cursor: null });
});

describe("the tab Qualité", () => {
  it("says when there will be a measure, never a made-up score", async () => {
    api.summary.mockResolvedValue(
      summary({ workspace: null, levels: { high: 0, medium: 0, low: 0 }, trend: [], change: null }),
    );
    mount(<QualityTab />);

    expect(await screen.findByTestId("quality-never")).toHaveTextContent(
      "LEKA n'a pas encore mesuré la qualité de ce qu'il sait",
    );
    expect(screen.queryByTestId("quality-workspace-score")).not.toBeInTheDocument();
  });

  it("says the workspace's score, its level, how it moved and each dimension", async () => {
    mount(<QualityTab />);

    expect(await screen.findByTestId("quality-workspace-score")).toHaveTextContent("72 %");
    expect(screen.getAllByTestId("quality-level")[0]).toHaveTextContent("À consolider");
    expect(screen.getByTestId("quality-change")).toHaveTextContent("+5 pts en 7 jours");
    expect(screen.getByTestId("quality-levels")).toHaveTextContent("1 élément peu fiable");
    expect(screen.getByTestId("quality-levels")).toHaveTextContent("7 éléments fiable");
    expect(screen.getByTestId("quality-dimension-completeness")).toHaveTextContent("60 %");
    // Nothing measured its confidence: said so, not 0.
    expect(screen.getByTestId("quality-dimension-confidence")).toHaveTextContent("Non mesurée");
  });

  it("says every point of the trend, and reads one by keyboard", async () => {
    mount(<QualityTab />);
    const trend = await screen.findByTestId("quality-trend");

    expect(within(trend).getAllByRole("listitem")).toHaveLength(3);
    expect(within(trend).getAllByRole("listitem")[0]).toHaveTextContent("60 %");

    const chart = within(trend).getByRole("img", {
      name: "Score de qualité de votre environnement, sur 30 jours",
    });
    fireEvent.focus(chart);
    expect(screen.getByTestId("quality-trend-tooltip")).toHaveTextContent("72 %");
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(screen.getByTestId("quality-trend-tooltip")).toHaveTextContent("67 %");
  });

  it("lists the things known least well, leading to their sheets, filtered by level", async () => {
    const user = userEvent.setup();
    mount(<QualityTab />);

    const link = await screen.findByRole("link", { name: "orphan-worker" });
    expect(link).toHaveAttribute("href", `/environment/services/${ORPHAN}`);
    const row = link.closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent(
      "plus vu par ses sources depuis des semaines · aucun responsable",
    );
    expect(api.weakest).toHaveBeenLastCalledWith(undefined);

    await user.click(screen.getByTestId("quality-filter-low"));
    expect(api.weakest).toHaveBeenLastCalledWith("low");
    expect(screen.getByTestId("quality-filter-low")).toHaveAttribute("aria-pressed", "true");
  });

  it("gives the areas by column, team and application", async () => {
    const user = userEvent.setup();
    mount(<QualityTab />);

    expect(await screen.findByText("Services")).toBeInTheDocument();
    expect(screen.getByText("aucun responsable (3)")).toBeInTheDocument();

    await user.click(screen.getByTestId("quality-area-teams"));
    expect(screen.getByRole("link", { name: "Payments" })).toBeInTheDocument();

    await user.click(screen.getByTestId("quality-area-applications"));
    expect(screen.getByText("Aucune zone de ce type n'est connue.")).toBeInTheDocument();
  });

  it("says why the trend is not drawn yet", () => {
    mount(<QualityTrend points={summary().trend.slice(-1)} />);
    expect(screen.getByTestId("quality-trend-empty")).toBeInTheDocument();
  });
});

describe("a thing's sheet", () => {
  it("says a lack of one kind once, with how many", async () => {
    api.weakest.mockResolvedValue({
      data: [
        {
          ...WEAK,
          missing: [
            { code: "disputed", dimension: "consistency", weight: 0.35, detail: "sla" },
            { code: "disputed", dimension: "consistency", weight: 0.35, detail: "owner" },
            { code: "stale_documents", dimension: "freshness", weight: 0.2, detail: "…" },
          ],
        },
      ],
      next_cursor: null,
    });
    mount(<QualityTab />);

    const row = (await screen.findByRole("link", { name: "orphan-worker" })).closest("tr");
    expect(row).toHaveTextContent("sources en désaccord (2) · documentation périmée");
  });

  it("says a thing not measured yet", async () => {
    api.one.mockRejectedValue(
      new ApiError(404, "/intelligence/quality/scores/x", "No such quality score."),
    );
    mount(<EntityQuality id={ORPHAN} />);

    expect(await screen.findByTestId("quality-entity-none")).toHaveTextContent(
      "Pas encore mesurée",
    );
    expect(api.one).toHaveBeenCalledWith(`entity:${ORPHAN}`);
  });

  it("says its level, since when, what lowers it, and why it is held", async () => {
    const detail: QualityDetail = {
      ...WEAK,
      level: "medium",
      score: 0.84,
      capped: "contradiction",
      missing: [{ code: "disputed", dimension: "consistency", weight: 0.35, detail: "…" }],
      factors: {},
      provenance: {},
      history: [],
    };
    api.one.mockResolvedValue(detail);
    mount(<EntityQuality id={ORPHAN} />);

    expect(await screen.findByTestId("quality-entity-score")).toHaveTextContent("84 %");
    expect(screen.getByTestId("quality-level")).toHaveTextContent("À consolider");
    expect(screen.getByText(/Niveau « À consolider » atteint ·/)).toBeInTheDocument();
    expect(screen.getByTestId("quality-lacks")).toHaveTextContent("sources en désaccord");
    expect(screen.getByText(/Plafonnée à « À consolider »/)).toBeInTheDocument();
  });
});
