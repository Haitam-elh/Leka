/**
 * The Décision and Action steps carried by LEKA's agents (2026-10-14, the
 * product call).
 *
 * What these protect:
 * - Résultat: the plan, step by step, who does each; the agents it takes,
 *   what each does, why, what it delivers, what a run costs, whether it can
 *   run here — and the way to decide.
 * - Décision: nothing launched without the person. The agents proposed,
 *   ticked; what one lacks completed before it may run; only the files
 *   ticked asked for; « Je le fais moi-même » the other way. A question
 *   only answered says « Aller plus loin » and « Je m'arrête là ».
 * - Action: done by hand, the plan ticked off and downloaded; by its
 *   agents, a failed one launched again.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { AgentProposal, IntentionAnalysisRead, IntentionDetail } from "@/lib/intentions/api";
import { sampleJourney } from "@/lib/intentions/journey-sample";
import { makeQueryClient } from "@/lib/query";

const ID = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => `/intentions/${ID}/decision`,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: ME }),
  usePermissions: () => permissions.value,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const api = vi.hoisted(() => ({
  analysis: vi.fn(),
  launch: vi.fn(),
  byHand: vi.fn(),
  retryAgents: vi.fn(),
}));
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: api,
}));
const runs = vi.hoisted(() => ({ forIntention: vi.fn() }));
const sourcesApi = vi.hoisted(() => ({ list: vi.fn() }));
const sold = vi.hoisted(() => ({ addOns: vi.fn(), entitlements: vi.fn(), buy: vi.fn() }));
vi.mock("@/lib/billing", async (original) => ({
  ...(await original<typeof import("@/lib/billing")>()),
  billing: sold,
}));
const permissions = vi.hoisted(() => ({ value: ["intention:read", "intention:create"] }));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));
vi.mock("@/lib/agent-runs", async (original) => ({
  ...(await original<typeof import("@/lib/agent-runs")>()),
  agentRuns: runs,
}));

const { AgentsAction, AgentsDecision, PlanChecklist, ProposalView } = await import(
  "@/components/intentions/agents-decision"
);

const ARCHITECT = {
  key: "application-architecture",
  title: "Architecte applicatif",
  summary: "Le deck d'architecture d'un parcours.",
  category: "architecture",
  why: "Le deck du parcours, en PDF.",
  deliverables: ["report", "pptx", "pdf"],
  asked: ["pdf"],
  inputs: { parcours: "Paiement CB" },
  missing: ["perimetre"],
  fields: [
    { name: "parcours", type: "text", required: true, description: "Le parcours", choices: [] },
    { name: "perimetre", type: "text", required: true, description: "Le périmètre", choices: [] },
  ],
  credits: 41.2,
  available: true,
  reasons: [],
};
const REVIEW = {
  key: "code-review",
  title: "Revue de code",
  summary: "Relit une pull request.",
  category: "development",
  why: "",
  deliverables: ["report"],
  asked: [],
  inputs: {},
  missing: [],
  fields: [],
  credits: null,
  available: false,
  reasons: ["missing_source"],
};

function proposal(more: Partial<AgentProposal> = {}): AgentProposal {
  return {
    agents: [ARCHITECT, REVIEW],
    steps: [
      { title: "Rassembler la documentation", detail: "Confluence et le code.", agent: null },
      { title: "Dessiner l'architecture", detail: "Le deck.", agent: ARCHITECT.key },
    ],
    informative: false,
    by: "model",
    ...more,
  };
}

function intention(status: IntentionDetail["status"] = "awaiting_decision", more: Partial<IntentionDetail> = {}): IntentionDetail {
  return {
    id: ID,
    title: "L'architecture du parcours Paiement CB",
    text: "Construis l'architecture du parcours Paiement CB, il me faut un PDF",
    kind: "dependency",
    scope: {},
    status,
    phase: "active",
    status_changed_at: new Date().toISOString(),
    summary: "Le parcours est documenté dans Confluence.",
    created_by: ME,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    context_id: "c1",
    archived_at: null,
    moves: [],
    goal: "map_dependencies",
    understanding: null,
    links: [],
    version: 1,
    journey: {
      ...sampleJourney(status),
      by: "asker",
      controls: ["ask_again", "cancel", "launch_agents", "by_hand"],
    },
    ...more,
  };
}

function analysis(said: AgentProposal): IntentionAnalysisRead {
  return {
    id: "a1",
    intention_id: ID,
    number: 1,
    trigger: "created",
    status: "complete",
    requested_by: ME,
    context_id: "c1",
    context_version: 1,
    intention_version: 1,
    current: true,
    readiness: "ready",
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    selection: [],
    steps: [],
    error: null,
    detail: {},
    result: {
      status: "complete",
      summary: [],
      findings: [],
      causes: [],
      impact: [],
      risk: "low",
      risk_basis: null,
      uncertainties: [],
      missing: [],
      confidence: 0.8,
      support: [],
      evidence: [],
      recommendations: [],
      proposal: said,
    },
  } as unknown as IntentionAnalysisRead;
}

function show(node: React.ReactNode) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

describe("the agents it takes, and the decision", () => {
  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    runs.forIntention.mockReset();
    push.mockReset();
    api.analysis.mockResolvedValue(analysis(proposal()));
    sourcesApi.list.mockResolvedValue({
      data: [
        { id: "s-confluence", display_name: "Confluence LEKA", status: "active" },
        { id: "s-github", display_name: "acme/backend", status: "active" },
      ],
    });
  });

  it("shows the plan and the agents it takes, each said, with the way to decide", async () => {
    show(<ProposalView intention={intention()} />);
    const steps = await screen.findAllByTestId("plan-step");
    expect(steps.map((s) => s.textContent)).toEqual([
      expect.stringContaining("Rassembler la documentationConfluence et le code.par vous"),
      expect.stringContaining("par Architecte applicatif"),
    ]);
    const [architect, review] = screen.getAllByTestId("proposed-agent");
    expect(architect).toHaveTextContent("Prêt");
    expect(architect).toHaveTextContent("Le deck du parcours, en PDF.");
    expect(architect).toHaveTextContent("RapportPowerPointPDF");
    expect(architect).toHaveTextContent("≈ 42 crédits par exécution");
    expect(review).toHaveTextContent("Indisponible ici");
    expect(within(review).getByTestId("proposed-agent-why-not")).toHaveTextContent(
      "Il lui faut une source de plus",
    );
    expect(review).toHaveTextContent("Coût estimé après quelques exécutions");
    expect(screen.getByTestId("results-to-decision")).toHaveAttribute(
      "href",
      `/intentions/${ID}/decision`,
    );
  });

  it("launches only what the person ticked, completed, with the files they chose", async () => {
    api.launch.mockResolvedValue(intention("executing"));
    const user = userEvent.setup();
    show(<AgentsDecision intention={intention()} />);
    const architect = await screen.findByText("Architecte applicatif");
    expect(architect).toBeVisible();
    // An agent that cannot run here is not ticked, nor tickable.
    const [mine, review] = screen.getAllByTestId("decide-agent");
    expect(within(review).getByTestId("decide-agent-on")).toHaveAttribute("aria-disabled", "true");
    // What it lacks, completed before it may run.
    const launch = screen.getByTestId("decide-launch");
    expect(launch).toBeDisabled();
    await user.type(within(mine).getByTestId("decide-input-perimetre"), "Digital");
    expect(launch).toBeEnabled();
    // The PDF the request asked for, ticked; the PowerPoint only if asked.
    expect(within(mine).getByTestId("decide-format-pdf")).toHaveAttribute("aria-checked", "true");
    await user.click(within(mine).getByTestId("decide-format-pptx"));
    // Kept to Confluence alone.
    await user.click(within(within(mine).getByTestId("decide-sources")).getByText("Confluence LEKA"));
    await user.click(launch);

    await waitFor(() => expect(api.launch).toHaveBeenCalled());
    expect(api.launch).toHaveBeenCalledWith(ID, [
      {
        key: ARCHITECT.key,
        inputs: { parcours: "Paiement CB", perimetre: "Digital" },
        formats: ["pdf", "pptx"],
        sources: ["s-confluence"],
      },
    ]);
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/intentions/${ID}/actions`));
  });

  it("is done by hand, the plan in hand — a question says it stops there", async () => {
    api.analysis.mockResolvedValue(analysis(proposal({ informative: true })));
    api.byHand.mockResolvedValue(intention("completed"));
    const user = userEvent.setup();
    show(<AgentsDecision intention={intention()} />);
    expect(await screen.findByText("Aller plus loin avec un agent")).toBeVisible();
    await user.click(screen.getByTestId("decide-by-hand"));
    expect(screen.getByTestId("decide-by-hand")).toHaveTextContent("Je m'arrête là");
    await waitFor(() => expect(api.byHand).toHaveBeenCalledWith(ID));
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/intentions/${ID}/actions`));
  });

  it("unlocks an agent not bought, then launches what was chosen once paid", async () => {
    // 2026-10-14: « Débloquer et lancer » — Stripe's page, then back.
    permissions.value = ["intention:read", "intention:create", "workspace:update"];
    const locked = { ...REVIEW, available: false, reasons: ["not_owned"] };
    api.analysis.mockResolvedValue(analysis(proposal({ agents: [ARCHITECT, locked] })));
    sold.addOns.mockResolvedValue({
      available: true,
      provisional: true,
      currency: "EUR",
      minimum_plan: "starter",
      plan: "growth",
      runs_agents: true,
      every: false,
      agents: [
        {
          key: "code-review",
          title: "Revue de code",
          summary: "Relit une pull request.",
          category: "development",
          tier: "standard",
          monthly_price: 900,
          owned: false,
          why: "not_owned",
          bundles: ["engineering"],
        },
      ],
      bundles: [
        {
          key: "engineering",
          name: { fr: "Ingénierie", en: "Engineering" },
          value: null,
          agents: ["code-change", "code-review", "test-analysis", "build-fixer"],
          monthly_price: 4500,
          alone_price: 5800,
          discount_percent: 22,
          owned: false,
        },
      ],
    });
    sold.buy.mockResolvedValue({ url: "https://checkout.stripe.test/cs_1" });
    const user = userEvent.setup();
    show(<AgentsDecision intention={intention()} />);
    const unlock = await screen.findByTestId("decide-unlock");
    expect(unlock).toHaveTextContent("À débloquer : 9 € / mois");
    expect(within(unlock).getByTestId("decide-unlock-bundle")).toHaveTextContent(
      "Dans le bundle Ingénierie : 45 € / mois",
    );
    await user.click(within(unlock).getByTestId("decide-unlock-agent"));
    await waitFor(() => expect(sold.buy).toHaveBeenCalled());
    const [asked] = sold.buy.mock.calls[0];
    expect(asked).toMatchObject({ kind: "agent", key: "code-review", intention_id: ID });
    expect(asked.launch.map((l: { key: string }) => l.key)).toContain("code-review");
    permissions.value = ["intention:read", "intention:create"];
  });

  it("says how it was decided once it was", async () => {
    show(
      <AgentsDecision
        intention={intention("executing", {
          journey: { ...sampleJourney("executing"), controls: [], path: "agents" },
        })}
      />,
    );
    expect(await screen.findByTestId("decided")).toHaveTextContent("Décidé : avec des agents");
  });
});

describe("what is done", () => {
  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    runs.forIntention.mockReset();
    api.analysis.mockResolvedValue(analysis(proposal()));
  });

  it("by hand: the plan to tick off, kept, and to download", async () => {
    const user = userEvent.setup();
    show(<PlanChecklist intention={intention("completed")} />);
    const checks = await screen.findAllByTestId("plan-check");
    expect(checks).toHaveLength(2);
    await user.click(checks[0]);
    expect(checks[0]).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem(`leka.plan.${ID}`)).toBe("[0]");
    expect(screen.getByTestId("plan-download")).toHaveTextContent("Télécharger le plan (.md)");
  });

  it("by its agents: a failed one launched again", async () => {
    runs.forIntention.mockResolvedValue([
      {
        id: "r1",
        key: ARCHITECT.key,
        title: ARCHITECT.title,
        version: "19.1.0",
        status: "failed",
        inputs: {},
        requested_by: ME,
        mine: true,
        intention_id: ID,
        context_id: null,
        context_version: null,
        format: "markdown",
        pending: [],
        deliverables: [],
        expected: ["pdf"],
        error: "timeout",
        reasons: [],
      },
    ]);
    api.retryAgents.mockResolvedValue(intention("executing"));
    const user = userEvent.setup();
    show(
      <AgentsAction
        intention={intention("failed", {
          journey: {
            ...sampleJourney("failed"),
            state: "action_failed",
            reason: "agent_failed",
            by: "asker",
            controls: ["retry_agents", "ask_again", "cancel"],
            path: "agents",
          },
        })}
      />,
    );
    expect(await screen.findByTestId("agent-work-run")).toHaveTextContent("Architecte applicatif");
    await user.click(screen.getByTestId("agents-retry"));
    await waitFor(() => expect(api.retryAgents).toHaveBeenCalledWith(ID));
  });
});
