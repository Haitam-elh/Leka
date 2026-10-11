/**
 * An intention's tabs Analyse and Preuves (LEKA-388).
 *
 * What these protect: how its analysis went — which one, why it ran, each
 * capability mobilised and how it went, a failure or a timeout said — and
 * what it found, in words, without proposals; while one is on its way,
 * LEKA said to be analysing, read again until it is done, the intention
 * then read again; blocked, what its context lacks; failed, run again by
 * its asker — not by someone else; the evidence it collected, where each
 * came from; nothing yet, said so.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionAnalysisRead, IntentionDetail } from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";

const ID = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const BILLING = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PAYMENTS = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const route = vi.hoisted(() => ({ pathname: "/intentions" }));
const me = vi.hoisted(() => ({ id: "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41" }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => route.pathname,
  useParams: () => ({ intentionId: route.pathname.split("/")[2] }),
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => me,
  usePermissions: () => ["intention:read", "intention:create"],
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const api = vi.hoisted(() => ({
  one: vi.fn(),
  history: vi.fn(),
  analysis: vi.fn(),
  analyses: vi.fn(),
  analyse: vi.fn(),
}));
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: api,
}));
const skillApi = vi.hoisted(() => ({ runs: vi.fn() }));
vi.mock("@/lib/skills", async (original) => ({
  ...(await original<typeof import("@/lib/skills")>()),
  skills: skillApi,
}));

const { IntentionScreen } = await import("@/components/intentions/intention-screen");
const { ApiError } = await import("@/lib/api");
const { notify } = await import("@/lib/notify");

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const STEP = {
  version: 1,
  error: null,
  reason: null,
  level: 0,
  started_ms: 0,
  handed: [],
  degraded: [],
  fallback_of: null,
};

function intention(overrides: Partial<IntentionDetail> = {}): IntentionDetail {
  return {
    id: ID,
    title: "Qui est responsable de Billing API ?",
    text: "Qui est responsable de Billing API ?",
    kind: "ownership",
    scope: {},
    status: "completed",
    phase: "finished",
    status_changed_at: ago(2),
    summary: "Billing API is owned by Payments.",
    created_by: ME,
    created_at: ago(3),
    updated_at: ago(2),
    context_id: "c1",
    archived_at: null,
    moves: [],
    goal: "find_owner",
    understanding: null,
    links: [],
    ...overrides,
  };
}

function analysis(overrides: Partial<IntentionAnalysisRead> = {}): IntentionAnalysisRead {
  return {
    id: "a1",
    intention_id: ID,
    number: 2,
    trigger: "requested",
    status: "partial",
    requested_by: ME,
    context_id: "c1",
    context_version: 3,
    readiness: "ready",
    started_at: ago(1),
    finished_at: new Date(new Date(ago(1)).getTime() + 1_200).toISOString(),
    selection: [
      { name: "standing", version: 1, method: "rules", chosen: true, reason: "always" },
      { name: "ownership", version: 1, method: "rules", chosen: true, reason: "goal" },
      { name: "changes", version: 1, method: "rules", chosen: true, reason: "acting" },
    ],
    steps: [
      { ...STEP, name: "standing", status: "succeeded", duration_ms: 8 },
      { ...STEP, name: "ownership", status: "succeeded", duration_ms: 21 },
      { ...STEP, name: "changes", status: "failed", duration_ms: 3, error: "RuntimeError" },
    ],
    result: {
      status: "partial",
      summary: [
        {
          code: "ownership.summary",
          text: "Billing API is owned by Payments.",
          params: { name: "Billing API", owners: ["Payments"] },
        },
      ],
      findings: [
        {
          id: `owner:${BILLING}`,
          capability: "ownership",
          code: "ownership.owner",
          text: "Billing API is owned by Payments.",
          params: { name: "Billing API", owners: ["Payments"], count: 1 },
          evidence: [`tie:${BILLING}:owned_by:${PAYMENTS}`],
        },
      ],
      causes: [],
      impact: [],
      risk: "unknown",
      risk_basis: null,
      uncertainties: [],
      missing: [
        {
          code: "capability.failed",
          text: "changes did not finish: failed.",
          params: { capability: "changes", error: "RuntimeError" },
        },
      ],
      confidence: 0.95,
      support: [
        {
          code: "support.sources",
          text: "1 source(s) behind its context.",
          params: { count: 1, established: true },
        },
      ],
      evidence: [
        {
          id: `tie:${BILLING}:owned_by:${PAYMENTS}`,
          kind: "record",
          label: "Billing API owned by Payments",
          ref_type: "owned_by",
          ref_id: null,
          sources: [{ id: "s1", kind: "backstage", name: "Catalogue" }],
          records: ["component:billing-api"],
          origin: "stated",
          confidence: 1,
          detail: null,
          at: ago(60),
          params: { from: "Billing API", to: "Payments" },
        },
      ],
    },
    error: null,
    detail: {},
    ...overrides,
  };
}

const MISSING = () => new ApiError(404, `/intentions/${ID}/analysis`, "No analysis yet.");

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <IntentionScreen />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  me.id = ME;
  route.pathname = `/intentions/${ID}/analysis`;
  api.one.mockResolvedValue(intention());
  api.history.mockResolvedValue([]);
  api.analysis.mockResolvedValue(analysis());
  api.analyses.mockResolvedValue([
    analysis(),
    analysis({ id: "a0", number: 1, status: "failed" }),
  ]);
  api.analyse.mockResolvedValue({ queued: true });
  skillApi.runs.mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("an intention's analysis", () => {
  it("says how it went, step by step — what it found is its results'", async () => {
    show();

    const head = await screen.findByTestId("analysis-head");
    expect(head).toHaveTextContent("Analyse de LEKA");
    expect(within(head).getByTestId("analysis-status")).toHaveTextContent("Partielle");
    expect(within(head).getByTestId("analysis-meta")).toHaveTextContent(
      /^Analyse n° 2 · relancée par une personne · Il y a 1 min · en 1\.2 s · contexte v3$/,
    );
    const steps = screen.getAllByTestId("analysis-step");
    expect(steps.map((s) => [s.dataset.name, s.dataset.status])).toEqual([
      ["standing", "succeeded"],
      ["ownership", "succeeded"],
      ["changes", "failed"],
    ]);
    expect(steps[1]).toHaveTextContent("Responsabilités · pour son objectif");
    expect(steps[2]).toHaveTextContent("Erreur : RuntimeError");
    expect(steps[2]).toHaveTextContent("En échec");
    // What it comes to is step 3's, not drawn here.
    expect(screen.queryByTestId("analysis")).not.toBeInTheDocument();
    // Completed: nothing to run again.
    expect(screen.queryByTestId("analysis-again")).not.toBeInTheDocument();
    // Its analyses, the latest first.
    const previous = await screen.findByTestId("analysis-previous");
    expect(previous).toHaveTextContent("Analyse n° 2Partielle");
    expect(previous).toHaveTextContent("Analyse n° 1En échec");
  });

  it("says what it found on its results — no proposal", async () => {
    route.pathname = `/intentions/${ID}/results`;
    show();

    const view = await screen.findByTestId("analysis");
    expect(view).toHaveAttribute("data-status", "partial");
    expect(screen.getByTestId("analysis-state")).toHaveTextContent(
      "Changements n'a pas abouti : en échec.",
    );
    expect(screen.getByTestId("analysis-summary")).toHaveTextContent(
      "Billing API appartient à Payments.",
    );
    expect(view).toHaveTextContent("1 source(s) derrière son contexte");
    // Nothing proposed (LEKA-389): no proposals' section, no empty promise.
    expect(screen.queryByText("Recommandations de LEKA")).not.toBeInTheDocument();
  });

  it("lays out, as mockup 03, the first of what it found and the scope beside it", async () => {
    show();
    const first = await screen.findByTestId("analysis-see-results");
    expect(first).toHaveAttribute("href", `/intentions/${ID}/results`);
    expect(screen.getByRole("heading", { name: "Premiers constats" })).toBeInTheDocument();
    const scope = screen.getByTestId("analysis-scope");
    // Nothing chosen: every environment, the default period.
    expect(scope).toHaveTextContent("EnvironnementTous");
    expect(scope).toHaveTextContent("PériodePar défaut pour ce type de demande");
  });

  it("says a question answered needs no decision nor action", async () => {
    show();
    await screen.findByTestId("analysis-head");
    for (const step of ["decision", "action"]) {
      const said = screen.getByTestId(`intention-step-${step}`);
      expect(said).toHaveAttribute("data-state", "skipped");
      expect(said).toHaveTextContent("Non nécessaire");
      expect(within(said).queryByRole("link")).not.toBeInTheDocument();
    }
    expect(screen.getByTestId("intention-step-results")).toHaveAttribute("data-state", "done");
  });

  it("lays its decision beside what it rests on, as mockup 05", async () => {
    route.pathname = `/intentions/${ID}/decision`;
    api.one.mockResolvedValue(intention({ status: "awaiting_decision", phase: "active" }));
    show();
    const aside = await screen.findByTestId("decision-aside");
    expect(await within(aside).findByRole("heading", { name: "Impact global" })).toBeInTheDocument();
    expect(within(aside).getByRole("heading", { name: "Confiance de l'analyse" })).toBeInTheDocument();
    expect(within(aside).getByRole("heading", { name: "Prochaines étapes" })).toBeInTheDocument();
    // What it comes to is step 3's: not drawn again under the decision.
    expect(screen.queryByTestId("intention-results")).not.toBeInTheDocument();
    expect(screen.getByTestId("intention-step-decision")).toHaveAttribute("data-state", "current");
  });

  it("says how LEKA orchestrated it: what ran together, what each was handed (LEKA-399)", async () => {
    api.analysis.mockResolvedValue(
      analysis({
        selection: [
          { name: "standing", version: 1, method: "rules", chosen: true, reason: "always" },
          { name: "ownership", version: 1, method: "rules", chosen: true, reason: "acting" },
          { name: "changes", version: 1, method: "rules", chosen: true, reason: "acting" },
          { name: "incidents", version: 1, method: "rules", chosen: true, reason: "goal" },
          { name: "synthesis", version: 1, method: "model", chosen: true, reason: "always" },
        ],
        steps: [
          { ...STEP, name: "standing", status: "succeeded", duration_ms: 8 },
          { ...STEP, name: "ownership", status: "failed", duration_ms: 3, error: "RuntimeError" },
          { ...STEP, name: "changes", status: "succeeded", duration_ms: 12 },
          {
            ...STEP,
            name: "incidents",
            status: "succeeded",
            duration_ms: 9,
            level: 1,
            handed: ["changes"],
            degraded: ["ownership"],
          },
          {
            ...STEP,
            name: "synthesis",
            status: "succeeded",
            duration_ms: 900,
            level: 2,
            handed: ["standing", "changes", "incidents"],
          },
        ],
        detail: {
          orchestration: {
            levels: [["standing", "ownership", "changes"], ["incidents"], ["synthesis"]],
            steps: {
              standing: { level: 0 },
              ownership: { level: 0 },
              changes: { level: 0 },
              incidents: { level: 1 },
              synthesis: { level: 2 },
            },
          },
        },
      }),
    );
    show();

    const levels = await screen.findAllByTestId("analysis-level");
    expect(levels.map((l) => l.querySelector("p")?.textContent)).toEqual([
      "Étape 1 · en parallèle",
      "Étape 2",
      "Conclusion",
    ]);
    const incidents = within(levels[1]).getByTestId("analysis-step");
    expect(incidents).toHaveTextContent(/reçoit : Changements/);
    // What it reads that failed: run without it, said.
    expect(incidents).toHaveTextContent(/sans : Responsabilités/);
    expect(within(levels[2]).getByTestId("analysis-step")).toHaveTextContent(/reçoit :/);
  });

  it("says LEKA is analysing while one is on its way, and reads it again until done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.one.mockResolvedValue(intention({ status: "analysing", phase: "active", summary: null }));
    api.analysis
      .mockRejectedValueOnce(MISSING())
      .mockResolvedValueOnce(
        analysis({ status: "running", finished_at: null, steps: [], result: null }),
      )
      .mockResolvedValue(analysis());
    show();

    const head = await screen.findByTestId("analysis-head");
    expect(head).toHaveAttribute("data-live", "true");
    expect(head).toHaveTextContent("Analyse en attente");
    // Its asker may start it now rather than wait.
    expect(within(head).getByTestId("analysis-again")).toHaveTextContent("Lancer l'analyse");

    await vi.advanceTimersByTimeAsync(4_000);
    await waitFor(() => expect(head).toHaveTextContent("LEKA analyse votre demande"));
    const steps = screen.getAllByTestId("analysis-step");
    expect(steps.every((s) => s.dataset.status === "running")).toBe(true);
    expect(screen.getByTestId("analysis-state")).toHaveAttribute("data-status", "running");

    api.one.mockResolvedValue(intention());
    await vi.advanceTimersByTimeAsync(4_000);
    await waitFor(() =>
      expect(screen.getAllByTestId("analysis-step").map((s) => s.dataset.status)).toEqual([
        "succeeded",
        "succeeded",
        "failed",
      ]),
    );
    expect(screen.queryByTestId("analysis-state")).not.toBeInTheDocument();
    // Done: the intention it moved, read again.
    await waitFor(() => expect(api.one.mock.calls.length).toBeGreaterThan(1));
    await waitFor(() =>
      expect(screen.getByTestId("analysis-head")).toHaveAttribute("data-live", "false"),
    );
  });

  it("says what its context lacks when it could not be analysed", async () => {
    api.one.mockResolvedValue(
      intention({
        status: "analysing",
        phase: "active",
        summary: null,
        readiness: {
          status: "blocked",
          context_id: "c1",
          version: 3,
          level: "low",
          score: 0.4,
          elements: 4,
          facets: { technical: 3, business: 0, organizational: 1, temporal: 0 },
          sources: 1,
          critical: [
            {
              origin: "gap",
              kind: "no_source_for",
              severity: "critical",
              said: "None of the sources read…",
              refs: [],
              gap_origin: "intent",
              detail: { needs: ["incidents", "deployments"] },
              label: null,
              about: null,
            },
          ],
          warnings: [],
        },
      }),
    );
    api.analysis.mockResolvedValue(
      analysis({
        status: "blocked",
        steps: [],
        selection: [],
        result: null,
        error: "context_blocked",
      }),
    );
    show();

    expect(await screen.findByTestId("analysis-blocked")).toHaveTextContent(
      "Analyse non lancée : le contexte ne peut pas la fonder",
    );
    expect(screen.getByTestId("readiness-critical")).toBeInTheDocument();
    expect(screen.queryByTestId("analysis-steps")).not.toBeInTheDocument();
    expect(screen.getByTestId("analysis-again")).toHaveTextContent("Relancer l'analyse");
  });

  it("runs a failed one again, for its asker", async () => {
    const user = userEvent.setup();
    api.one.mockResolvedValue(intention({ status: "failed", phase: "finished", summary: null }));
    api.analysis.mockResolvedValue(
      analysis({
        status: "failed",
        result: { ...analysis().result!, status: "failed", findings: [], summary: [] },
      }),
    );
    show();

    expect(await screen.findByRole("alert")).toHaveTextContent("Changements n'a pas abouti");
    await user.click(screen.getByTestId("analysis-again"));
    await waitFor(() => expect(api.analyse).toHaveBeenCalledWith(ID));
    expect(notify.success).toHaveBeenCalledWith({ title: "Analyse relancée." });
  });

  it("offers no run again to someone who neither asked nor approves", async () => {
    me.id = "8c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
    api.one.mockResolvedValue(intention({ status: "failed", phase: "finished" }));
    show();
    await screen.findByTestId("analysis-head");
    expect(screen.queryByTestId("analysis-again")).not.toBeInTheDocument();
  });

  it("says when there is none yet", async () => {
    api.one.mockResolvedValue(intention({ status: "needs_clarification", phase: "active" }));
    api.analysis.mockRejectedValue(MISSING());
    show();
    expect(await screen.findByTestId("analysis-none")).toHaveTextContent("Pas encore d'analyse");
  });
});

describe("its overview", () => {
  it("says what its analysis came to, in the reader's words", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    show();
    // Not the API's English sentence kept on the intention.
    expect(await screen.findByText("Billing API appartient à Payments.")).toHaveAttribute(
      "data-testid",
      "intention-summary",
    );
  });
});

describe("its answer, written by a model (LEKA-394)", () => {
  function answered() {
    const base = analysis();
    return analysis({
      result: {
        ...base.result!,
        answer: {
          text: "Payments est responsable de Billing API.",
          points: [
            {
              text: "Le catalogue de services le dit.",
              cites: [`owner:${BILLING}`, `tie:${BILLING}:owned_by:${PAYMENTS}`],
            },
          ],
          caveats: ["Une seule source le dit."],
          provider: "google",
          model: "gemini-3.8-flash",
          version: "gemini-3.8-flash-001",
        },
      },
    });
  }

  it("leads its results, each point saying how much it rests on, and who wrote it", async () => {
    route.pathname = `/intentions/${ID}/results`;
    api.analysis.mockResolvedValue(answered());
    show();
    const answer = await screen.findByTestId("analysis-answer");
    expect(answer).toHaveTextContent("Payments est responsable de Billing API.");
    expect(within(answer).getByTestId("answer-point")).toHaveTextContent(
      "Le catalogue de services le dit.2 élément(s) cité(s)",
    );
    expect(answer).toHaveTextContent("Une seule source le dit.");
    expect(answer).toHaveTextContent(
      "Rédigée par Gemini 3.8 Flash à partir de l'analyse de LEKA",
    );
  });

  it("is what the analysis came to, on its overview", async () => {
    route.pathname = `/intentions/${ID}/overview`;
    api.analysis.mockResolvedValue(answered());
    show();
    expect(await screen.findByText("Payments est responsable de Billing API.")).toHaveAttribute(
      "data-testid",
      "intention-summary",
    );
  });

  it("is not shown when no model wrote one", async () => {
    route.pathname = `/intentions/${ID}/results`;
    show();
    await screen.findByTestId("intention-results");
    expect(screen.queryByTestId("analysis-answer")).not.toBeInTheDocument();
  });
});

describe("what LEKA read to answer (LEKA-396)", () => {
  type SkillRun = import("@/lib/skills").SkillRun;

  function read(key: string, afterMs: number, more: Partial<SkillRun> = {}): SkillRun {
    const started = new Date(analysis().started_at).getTime();
    return {
      id: `${key}-${afterMs}`,
      key,
      version: "1.0.0",
      status: "succeeded",
      reason: null,
      message: null,
      errors: [],
      caller: "analyst",
      ref: `intention:${ID}`,
      run_by: ME,
      mine: true,
      inputs: {},
      output: {},
      cited: 0,
      deprecated: false,
      latency_ms: 12,
      at: new Date(started + afterMs).toISOString(),
      ...more,
    };
  }

  it("says each read in the order it read, what it was about, how much it found", async () => {
    skillApi.runs.mockResolvedValue([
      read("describe", 600, { inputs: { id: `entity:${BILLING}` }, output: { name: "Billing API" }, cited: 3 }),
      read("happened", 400, {
        status: "refused",
        reason: "invalid_input",
        inputs: { since: "yesterday" },
        output: null,
      }),
      read("find", 100, { inputs: { query: "billing" }, output: { found: [] }, cited: 2 }),
      read("dependencies", 300, {
        output: { of: "Billing API", direction: "upstream", environment: "production" },
        cited: 1,
      }),
      // Read for an analysis before this one: not this one's.
      read("overview", -600_000),
    ]);
    show();
    const card = await screen.findByTestId("analysis-reads");
    expect(skillApi.runs).toHaveBeenCalledWith(`intention:${ID}`);
    const reads = within(card).getAllByTestId("analysis-read");
    expect(reads.map((r) => r.dataset.key)).toEqual(["find", "dependencies", "happened", "describe"]);
    expect(reads[0]).toHaveTextContent("Recherche · « billing »2 élément(s) lu(s)12 ms");
    expect(reads[1]).toHaveTextContent("Dépendances · Billing API · ce qui en dépend · production");
    expect(reads[2]).toHaveTextContent("Événements");
    expect(reads[2]).toHaveTextContent("demande mal formée : le modèle l'a reformulée");
    expect(reads[2]).toHaveTextContent("Refusée");
    // A date the model wrote that LEKA could not read: not said, nothing breaks.
    expect(reads[2]).not.toHaveTextContent("depuis");
    expect(reads[3]).toHaveTextContent("Fiche · Billing API3 élément(s) lu(s)");
  });

  it("names a skill of the library as it read (LEKA-401)", async () => {
    skillApi.runs.mockResolvedValue([
      read("delivery-metrics", 200, {
        inputs: { id: `entity:${BILLING}` },
        output: {
          of: "Billing API",
          environment: "production",
          since: "2026-09-10T12:00:00Z",
          change_failure_rate: 1,
        },
        cited: 2,
      }),
    ]);
    show();
    const [delivery] = within(await screen.findByTestId("analysis-reads")).getAllByTestId(
      "analysis-read",
    );
    expect(delivery).toHaveTextContent("Indicateurs de livraison · Billing API · production");
    expect(delivery).toHaveTextContent("depuis le 10 sept.");
    expect(delivery).toHaveTextContent("2 élément(s) lu(s)");
  });

  it("is not shown when LEKA read nothing: the rules alone answered", async () => {
    show();
    await screen.findByTestId("intention-analysis");
    await waitFor(() => expect(skillApi.runs).toHaveBeenCalled());
    expect(screen.queryByTestId("analysis-reads")).not.toBeInTheDocument();
  });
});

describe("its evidence", () => {
  it("lists what it collected, where each came from", async () => {
    const user = userEvent.setup();
    route.pathname = `/intentions/${ID}/evidence`;
    show();

    const tab = await screen.findByTestId("intention-evidence");
    const [item] = await within(tab).findAllByRole("listitem");
    expect(item).toHaveTextContent("Billing API appartient à Payments");
    expect(item).toHaveTextContent("Catalogue");
    await user.click(within(item).getByRole("button"));
    expect(item).toHaveTextContent("component:billing-api");
    expect(item).toHaveTextContent("dit par une source");
  });

  it("says evidence comes once analysed", async () => {
    route.pathname = `/intentions/${ID}/evidence`;
    api.analysis.mockRejectedValue(MISSING());
    show();
    expect(await screen.findByTestId("intention-evidence")).toHaveTextContent(
      "Les preuves apparaissent une fois l'intention analysée.",
    );
  });
});

const ROLLBACK = {
  id: "rollback:d1",
  code: "recommend.rollback",
  text: "Undo payment-api v2.8.4: it is said to have caused p99 above 2s.",
  params: { change: "payment-api v2.8.4", incident: "p99 above 2s" },
  action: "rollback" as const,
  changes_systems: true,
  priority: "high" as const,
  risk: "medium" as const,
  reversible: true,
  confidence: 0.83,
  why: {
    code: "recommend.why.cause",
    text: "Its source says p99 above 2s was caused by it.",
    params: { cause: "payment-api v2.8.4", basis: "stated", incident: "p99 above 2s" },
  },
  basis: ["cause:d1"],
  evidence: [`tie:${BILLING}:owned_by:${PAYMENTS}`],
  target: { ref_type: "deployment", ref_id: "d1", name: "payment-api v2.8.4" },
};
const OWNER = {
  id: "assign_owner:x",
  code: "recommend.assign_owner",
  text: "Name an owner for Billing API: no source names one.",
  params: { name: "Billing API" },
  action: "change" as const,
  changes_systems: false,
  priority: "medium" as const,
  risk: "low" as const,
  reversible: true,
  confidence: null,
  why: {
    code: "recommend.why.uncertain",
    text: "No source names an owner for Billing API.",
    params: { name: "Billing API", of: "ownership.unknown" },
  },
  basis: [],
  evidence: [],
  target: null,
};

describe("what LEKA recommends (LEKA-389)", () => {
  beforeEach(() => {
    route.pathname = `/intentions/${ID}/results`;
  });

  it("proposes apart from what it found, each with why, risk, and its evidence", async () => {
    const found = analysis();
    api.analysis.mockResolvedValue({
      ...found,
      result: { ...found.result!, recommendations: [ROLLBACK, OWNER] },
    });
    const user = userEvent.setup();
    show();

    const proposals = await screen.findByRole("region", { name: "Recommandations de LEKA" });
    const cards = within(proposals).getAllByTestId("recommendation");
    expect(cards).toHaveLength(2);
    // Said as proposals, apart from the facts.
    const facts = screen.getByTestId("analysis-summary");
    expect(facts).not.toHaveTextContent("Revenir sur");
    const [undo, owner] = cards;
    expect(undo).toHaveTextContent("Revenir sur payment-api v2.8.4");
    expect(undo).toHaveTextContent("Cause indiquée par sa source de p99 above 2s.");
    expect(undo).toHaveTextContent("Modifie vos systèmes : soumis à validation");
    expect(undo).toHaveTextContent("Réversible");
    expect(within(undo).getByTestId("priority")).toHaveTextContent("Priorité haute");
    expect(owner).toHaveTextContent("Nommer un responsable pour Billing API");
    // Its why is the uncertainty it follows from, as the analysis says it.
    expect(owner).toHaveTextContent("Aucune source ne nomme de responsable pour Billing API.");
    expect(owner).not.toHaveTextContent("soumis à validation");

    // The evidence it rests on, inspectable from it.
    await user.click(within(undo).getByRole("button", { name: /Voir ce qui justifie/ }));
    expect(undo).toHaveTextContent("Catalogue");
  });

  it("says plainly when it could not conclude, and what to do then", async () => {
    const found = analysis();
    api.analysis.mockResolvedValue({
      ...found,
      status: "inconclusive",
      result: {
        ...found.result!,
        status: "inconclusive",
        findings: [],
        summary: [],
        recommendations: [
          {
            ...OWNER,
            id: "ask_differently",
            code: "recommend.ask_differently",
            text: "Ask differently.",
            params: {},
            priority: "medium",
            why: {
              code: "recommend.why.inconclusive",
              text: "The analysis could not conclude.",
              params: {},
            },
          },
        ],
      },
    });
    show();

    expect(await screen.findByTestId("analysis")).toHaveAttribute("data-status", "inconclusive");
    expect(screen.getByTestId("analysis-state")).toHaveTextContent("Analyse non concluante");
    const [card] = within(
      screen.getByRole("region", { name: "Recommandations de LEKA" }),
    ).getAllByTestId("recommendation");
    expect(card).toHaveTextContent(
      "Reformuler la demande, ou connecter ce qui permettrait de répondre",
    );
    expect(card).toHaveTextContent("L'analyse n'a pas pu conclure.");
  });

  it("says what is missing when the evidence is incomplete", async () => {
    show();
    // A capability failed: the analysis is partial, what is missing said.
    expect(await screen.findByTestId("analysis")).toHaveAttribute("data-status", "partial");
    expect(screen.getByTestId("analysis-state")).toHaveTextContent("Analyse partielle");
    expect(screen.getByTestId("analysis-state")).toHaveTextContent(
      "Changements n'a pas abouti : en échec.",
    );
  });
});
