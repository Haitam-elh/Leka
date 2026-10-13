/**
 * An intention's journey on every screen (LEKA-443).
 *
 * What these protect:
 * - The same state wherever the same intention is shown: its row, the
 *   panel beside the list, its page — the API's state, never one the
 *   screen made up.
 * - What happened, since when, what comes next and who, said on its page.
 *   An error says why and the next step, its technical code folded away.
 *   Late is said.
 * - « Arrêter l'analyse »:
 *   - asks first, saying partial results are kept;
 *   - stopped, the next step is to resume it.
 * - No control its state does not allow: « Modifier la décision » only
 *   while a decision is open, to who may approve; nothing to stop or
 *   cancel while its actions run.
 * - An analysis stopped, or of a version asked again since, is never shown
 *   as its result, nor its evidence.
 * - Its history says its versions apart, the earlier said replaced.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionAnalysisRead, IntentionDetail } from "@/lib/intentions/api";
import { QUEUED, sampleJourney } from "@/lib/intentions/journey-sample";
import type { TimelineItem } from "@/lib/outcomes";
import { makeQueryClient } from "@/lib/query";

const ID = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const route = vi.hoisted(() => ({ pathname: "/intentions" }));
const permissions = vi.hoisted(() => ({ value: ["intention:read", "intention:create"] }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => route.pathname,
  useParams: () => ({ intentionId: route.pathname.split("/")[2] }),
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: ME }),
  usePermissions: () => permissions.value,
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  counts: vi.fn(),
  one: vi.fn(),
  history: vi.fn(),
  cancel: vi.fn(),
  stop: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
  analysis: vi.fn(),
  analyses: vi.fn(),
  analyse: vi.fn(),
  answer: vi.fn(),
  feasibility: vi.fn(),
}));
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: api,
}));
const told = vi.hoisted(() => ({ timeline: vi.fn() }));
vi.mock("@/lib/outcomes", async (original) => ({
  ...(await original<typeof import("@/lib/outcomes")>()),
  outcomes: told,
}));

const { IntentionsList } = await import("@/components/intentions/intentions-list");
const { IntentionScreen } = await import("@/components/intentions/intention-screen");
const { ApiError } = await import("@/lib/api");

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function intention(overrides: Partial<IntentionDetail> = {}): IntentionDetail {
  const status = overrides.status ?? "analysing";
  return {
    id: ID,
    title: "Pourquoi Billing API est lente depuis hier ?",
    text: "Pourquoi Billing API est lente depuis hier ?",
    kind: "diagnose",
    scope: {},
    status,
    phase: "active",
    status_changed_at: ago(3),
    summary: null,
    created_by: ME,
    created_at: ago(10),
    updated_at: ago(3),
    context_id: "c1",
    archived_at: null,
    moves: [],
    goal: "explain_cause",
    understanding: null,
    links: [],
    version: 1,
    journey: sampleJourney(status, {}, ago(3)),
    ...overrides,
  };
}

function analysis(overrides: Partial<IntentionAnalysisRead> = {}): IntentionAnalysisRead {
  return {
    id: "a1",
    intention_id: ID,
    number: 1,
    trigger: "created",
    status: "complete",
    requested_by: null,
    context_id: "c1",
    context_version: 1,
    intention_version: 1,
    current: true,
    readiness: "ready",
    started_at: ago(5),
    finished_at: ago(4),
    selection: [],
    steps: [],
    result: null,
    error: null,
    detail: {},
    ...overrides,
  };
}

function item(overrides: Partial<TimelineItem>): TimelineItem {
  return {
    id: `event:${crypto.randomUUID()}`,
    intention_id: ID,
    title: null,
    category: "intention",
    kind: "created",
    at: ago(9),
    actor: "person",
    by: ME,
    by_name: "Nora Diallo",
    reason: null,
    detail: { event: "created" },
    version: 1,
    ...overrides,
  };
}

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>{node}</ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  route.pathname = `/intentions/${ID}/overview`;
  permissions.value = ["intention:read", "intention:create"];
  api.counts.mockResolvedValue({ all: 1, active: 1, scheduled: 0, finished: 0, archived: 0 });
  api.history.mockResolvedValue([]);
  api.analyses.mockResolvedValue([]);
  api.analysis.mockRejectedValue(new ApiError(404, `/intentions/${ID}/analysis`, "No analysis yet."));
  api.feasibility.mockRejectedValue(new ApiError(404, "/x", "No."));
  told.timeline.mockResolvedValue([]);
});

describe("an intention's journey", () => {
  it("is the same state on its row, beside the list and on its page", async () => {
    const failed = intention({
      status: "failed",
      journey: sampleJourney("failed", { reason: "interrupted", technical: "interrupted" }),
    });
    api.list.mockResolvedValue({ data: [failed], next_cursor: null });
    api.one.mockResolvedValue(failed);
    route.pathname = "/intentions";
    const { unmount } = show(<IntentionsList />);

    const [row] = await screen.findAllByTestId("intention-row");
    expect(within(row).getByTestId("intention-status")).toHaveAttribute(
      "data-state",
      "analysis_failed",
    );
    expect(within(row).getByTestId("intention-status")).toHaveTextContent("Analyse échouée");
    // Beside the list: the same, and why — an error stays in sight.
    const preview = await screen.findByTestId("intention-preview");
    expect(within(preview).getByTestId("intention-status")).toHaveTextContent("Analyse échouée");
    expect(within(preview).getByTestId("preview-why")).toHaveTextContent(
      "L'analyse s'est interrompue : le moteur d'analyse ne répondait plus.",
    );
    unmount();

    route.pathname = `/intentions/${ID}/overview`;
    show(<IntentionScreen />);
    expect(await screen.findByTestId("intention-status")).toHaveTextContent("Analyse échouée");
    const note = screen.getByTestId("journey-note");
    expect(note).toHaveAttribute("data-reason", "interrupted");
    expect(within(note).getByTestId("journey-why")).toHaveTextContent(
      "L'analyse s'est interrompue",
    );
    expect(within(note).getByTestId("journey-next-said")).toHaveTextContent(
      "À vous · Relancez l'analyse.",
    );
    // The code for whoever diagnoses it — folded, never the first words.
    expect(within(note).getByTestId("journey-technical")).toHaveTextContent(
      "Pour le diagnostic : code interrupted · version 1",
    );
    // Its asker runs it again from here.
    const user = userEvent.setup();
    api.analyse.mockResolvedValue({ queued: true });
    await user.click(within(note).getByTestId("journey-analyse_again"));
    await waitFor(() => expect(api.analyse).toHaveBeenCalledWith(ID));
  });

  it("asks before stopping its analysis, keeps what it found, and resumes it", async () => {
    const user = userEvent.setup();
    api.one.mockResolvedValue(intention({ journey: sampleJourney("analysing", {}, ago(1)) }));
    const stopped = intention({ status: "submitted", journey: sampleJourney("submitted") });
    api.stop.mockResolvedValue(stopped);
    show(<IntentionScreen />);

    await user.click(await screen.findByTestId("intention-stop"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Les résultats partiels seront conservés dans l'historique.");
    api.one.mockResolvedValue(stopped);
    await user.click(within(dialog).getByRole("button", { name: "Arrêter" }));
    await waitFor(() => expect(api.stop).toHaveBeenCalledWith(ID));

    const note = await screen.findByTestId("journey-note");
    await waitFor(() => expect(note).toHaveAttribute("data-reason", "stopped"));
    expect(screen.getByTestId("intention-status")).toHaveTextContent("Prête à analyser");
    expect(within(note).getByTestId("journey-why")).toHaveTextContent(
      "Analyse arrêtée. Rien n'est perdu",
    );
    expect(screen.queryByTestId("intention-stop")).not.toBeInTheDocument();
    api.analyse.mockResolvedValue({ queued: true });
    await user.click(within(note).getByTestId("journey-resume"));
    await waitFor(() => expect(api.analyse).toHaveBeenCalledWith(ID));
  });

  it("says when LEKA takes longer than it should", async () => {
    api.one.mockResolvedValue(
      intention({ journey: sampleJourney("analysing", { ...QUEUED, late: true }, ago(8)) }),
    );
    show(<IntentionScreen />);
    expect(await screen.findByTestId("journey-late")).toHaveTextContent(
      "En attente depuis plus de 5 min",
    );
    expect(screen.getByTestId("journey-analyse_again")).toBeInTheDocument();
  });

  it("offers no control its state does not allow", async () => {
    // Running actions: nothing to stop, cancel nor decide from here.
    api.one.mockResolvedValue(intention({ status: "executing" }));
    const { unmount } = show(<IntentionScreen />);
    expect(await screen.findByTestId("intention-status")).toHaveTextContent("Action en cours");
    expect(screen.queryByTestId("intention-stop")).not.toBeInTheDocument();
    expect(screen.queryByTestId("intention-cancel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("intention-modify-decision")).not.toBeInTheDocument();
    unmount();

    // A decision open: changed only by who may approve.
    api.one.mockResolvedValue(intention({ status: "awaiting_decision" }));
    const member = show(<IntentionScreen />);
    expect(await screen.findByTestId("intention-status")).toHaveTextContent("Décision requise");
    expect(screen.queryByTestId("intention-modify-decision")).not.toBeInTheDocument();
    member.unmount();
    permissions.value = ["intention:read", "intention:create", "intention:approve"];
    show(<IntentionScreen />);
    expect(await screen.findByTestId("intention-modify-decision")).toHaveAttribute(
      "href",
      `/intentions/${ID}/decision`,
    );
  });

  it("never shows a stopped analysis, nor one of an earlier version, as its result", async () => {
    route.pathname = `/intentions/${ID}/results`;
    api.one.mockResolvedValue(
      intention({ status: "submitted", journey: sampleJourney("submitted") }),
    );
    api.analysis.mockResolvedValue(analysis({ status: "stopped", current: false }));
    const { unmount } = show(<IntentionScreen />);
    const stopped = await screen.findByTestId("analysis-not-current");
    expect(stopped).toHaveAttribute("data-why", "stopped");
    expect(screen.queryByTestId("intelligence-findings")).not.toBeInTheDocument();
    unmount();

    // Asked again, still to be made clear: version 1's analysis, replaced.
    api.one.mockResolvedValue(
      intention({ status: "needs_clarification", version: 2 }),
    );
    api.analysis.mockResolvedValue(analysis({ current: false, intention_version: 1 }));
    show(<IntentionScreen />);
    const replaced = await screen.findByTestId("analysis-not-current");
    expect(replaced).toHaveAttribute("data-why", "replaced");
    expect(replaced).toHaveTextContent(
      "Cette analyse portait sur la version 1 de la demande, remplacée depuis.",
    );
    expect(screen.getByTestId("intention-version")).toHaveTextContent("Version 2");
  });

  it("tells its versions apart in its history, the earlier said replaced", async () => {
    route.pathname = `/intentions/${ID}/history`;
    api.one.mockResolvedValue(intention({ version: 2 }));
    told.timeline.mockResolvedValue([
      item({
        kind: "asked_again",
        at: ago(2),
        version: 2,
        detail: { event: "moved", from_status: "completed", to_status: "analysing" },
      }),
      item({
        id: "analysis:a1:finished",
        category: "analysis",
        kind: "analysis_complete",
        at: ago(6),
        actor: "system",
        by: null,
        by_name: null,
        detail: { number: 1 },
      }),
      item({}),
    ]);
    show(<IntentionScreen />);

    const versions = await screen.findAllByTestId("timeline-version");
    expect(versions.map((v) => v.textContent)).toEqual([
      "Version 1 · remplacée par une version plus récente",
      "Version 2 · en cours",
    ]);
    const events = screen.getAllByTestId("intention-event");
    expect(events.map((e) => e.dataset.version)).toEqual(["1", "1", "2"]);
  });
});
