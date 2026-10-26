/**
 * An intention's page (LEKA-458).
 *
 * What these protect:
 * - What LEKA says is what the server's offer says: a plan to take, options
 *   to add, everything covered — or the month's capacity spent.
 * - Each agent never shown included when it is not: its price, or
 *   « Inclus » — « Inclus avec Starter » when the plan to take includes it —
 *   « Actif », « Indisponible ici ».
 * - The total now and after the launch offer, renewed until cancelled.
 * - Nothing bought without a confirmation that says it all; covered, it is
 *   launched as it is.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail, IntentionOffer } from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/intentions/i1",
}));

vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: "u1", email: "karim@acme.example", first_name: "Karim", last_name: "D." }),
  useCurrentWorkspace: () => ({ id: "w1", name: "Acme", slug: "acme", role: "owner" }),
  usePermissions: () => ["workspace:update", "intention:approve"],
}));

const offered = vi.hoisted(() => ({ value: undefined as unknown }));
const launch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/intentions/queries", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/queries")>()),
  useIntentionOffer: () => ({ data: offered.value }),
  useIntentionAnalysis: () => ({ data: null }),
  useDecide: () => ({ launch: { mutate: launch, isPending: false } }),
}));

vi.mock("@/lib/agent-runs-queries", () => ({ useIntentionRuns: () => ({ data: [] }) }));
vi.mock("@/lib/sources-queries", () => ({
  useSources: () => ({
    data: [{ id: "s1", type: "github", display_name: "acme/front", status: "active" }],
  }),
}));

const PROPOSAL = {
  agents: [
    {
      key: "code-review",
      title: "Revue de code",
      summary: "",
      category: "development",
      why: "Les changements sont relus.",
      deliverables: ["report"],
      asked: [],
      inputs: {},
      missing: [],
      fields: [],
      credits: null,
      available: true,
      reasons: [],
    },
  ],
  steps: [{ title: "Analyse du code et des dépendances", detail: "Scan du code.", agent: "code-review" }],
  informative: false,
  by: "model",
};
const proposed = vi.hoisted(() => ({ value: undefined as unknown }));
vi.mock("@/components/intentions/agents-decision", () => ({
  useProposal: () => ({ proposal: proposed.value ?? PROPOSAL, loading: false }),
  AgentsAction: () => <div data-testid="agents-action" />,
}));
vi.mock("@/components/intentions/analysis-tab", () => ({
  AnalysisResults: () => <div />,
  EvidenceTab: () => <div />,
}));

const checkout = vi.hoisted(() => vi.fn());
vi.mock("@/lib/subscription", () => ({ subscription: { checkout } }));
const activateDemo = vi.hoisted(() => vi.fn());
vi.mock("@/lib/workspace", () => ({ workspace: { activateDemo } }));

const { IntentionDetailPage } = await import("@/components/intentions/intention-detail");
const { InDemoContext } = await import("@/components/demo/in-demo");

function intention(): IntentionDetail {
  return {
    id: "i1",
    text: "Analyse les risques de passer notre application de React 17 à React 18",
    title: "Migration React 18",
    status: "awaiting_decision",
    created_at: "2026-10-15T12:28:00Z",
    updated_at: "2026-10-15T12:28:00Z",
    scope: {},
    understanding: { restated: "Analyser les risques d'une migration vers React 18." },
    journey: { state: "decision_required", path: null, by: "asker", controls: ["launch_agents"] },
  } as unknown as IntentionDetail;
}

function offer(over: Partial<IntentionOffer> = {}): IntentionOffer {
  return {
    plan_now: "free",
    plan: {
      key: "starter",
      name: "Starter",
      monthly_price: 5900,
      launch_monthly: 4720,
      launch_months: 12,
      trial_days: null,
      credits: 2000,
      users: 1,
      sources: 5,
      analyses: 100,
      runs_agents: true,
      contractual: false,
    },
    change_plan: true,
    agents: [
      {
        key: "code-review",
        title: "Revue de code",
        category: "development",
        tier: "standard",
        monthly_price: 900,
        status: "to_buy",
        reasons: [],
        credits: null,
        chosen: true,
      },
    ],
    lines: [
      { kind: "plan", key: "starter", label: "Starter", monthly_price: 4720, then_monthly: 5900, for_months: 12, agents: [] },
      { kind: "agent", key: "code-review", label: "Revue de code", monthly_price: 900, then_monthly: null, for_months: null, agents: ["code-review"] },
    ],
    total_monthly: 5620,
    then_monthly: 6800,
    used: 12,
    allowance: 200,
    estimate: null,
    estimate_complete: false,
    blocked: null,
    ready: false,
    provisional: true,
    ...over,
  } as IntentionOffer;
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <IntentionDetailPage intention={intention()} />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  checkout.mockReset();
  launch.mockReset();
  offered.value = offer();
  proposed.value = undefined;
});

describe("an intention's page", () => {
  it("says the plan to take and the agents to add, each priced — the total now and after", async () => {
    const user = userEvent.setup();
    checkout.mockReturnValue(new Promise(() => {}));
    show();

    expect(screen.getByTestId("detail-leka")).toHaveTextContent("pas inclus dans la formule Free");
    expect(screen.getByTestId("detail-understanding")).toHaveTextContent(
      "Analyser les risques d'une migration vers React 18.",
    );
    expect(screen.getByTestId("detail-sources")).toHaveTextContent("acme/front");
    const [agent] = screen.getAllByTestId("detail-agent");
    expect(agent).toHaveTextContent("9 € / mois");
    expect(agent).not.toHaveTextContent("Inclus");
    // Each paid line, which right it brings (LEKA-464).
    const [planWhy, agentWhy] = screen.getAllByTestId("detail-line-why");
    expect(planWhy).toHaveTextContent("Votre formule Free n'exécute pas d'agents spécialisés.");
    expect(agentWhy).toHaveTextContent("Option mensuelle : non incluse dans la formule Starter.");
    expect(screen.getByTestId("detail-plan")).toHaveTextContent("Starter");
    const total = screen.getByTestId("detail-total");
    expect(total).toHaveTextContent("56,20 € / mois");
    expect(total).toHaveTextContent("Abonnement + 1 agent");
    expect(screen.getByTestId("detail-then")).toHaveTextContent("puis 68 € / mois après 12 mois");
    expect(total).toHaveTextContent("renouvelé automatiquement jusqu'à résiliation");
    // No estimate before an agent ran here: said, never invented.
    expect(screen.getByTestId("detail-capacity")).toHaveTextContent("Pas encore d'estimation");

    // Nothing bought without the confirmation saying it all.
    await user.click(screen.getByTestId("detail-activate"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Étape 1 : l'abonnement Starter");
    expect(dialog).toHaveTextContent("Étape 2 : 1 agent");
    expect(checkout).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Payer et activer" }));
    await waitFor(() => expect(checkout).toHaveBeenCalledWith("starter", "month", "i1"));
  });

  it("in a demonstration: its payment simulated, said so — never Stripe (LEKA-498)", async () => {
    const user = userEvent.setup();
    activateDemo.mockResolvedValue({ activated: true });
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <LocaleProvider>
          <ConfirmProvider>
            <InDemoContext.Provider value>
              <IntentionDetailPage intention={intention()} />
            </InDemoContext.Provider>
          </ConfirmProvider>
        </LocaleProvider>
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId("detail-activate")).not.toBeInTheDocument();
    expect(screen.getByTestId("detail-simulate-note")).toHaveTextContent("aucun paiement réel");
    await user.click(screen.getByTestId("detail-simulate"));
    await waitFor(() => expect(activateDemo).toHaveBeenCalled());
    expect(checkout).not.toHaveBeenCalled();
  });

  it("an agent the plan to take includes: said included with it, never sold", () => {
    offered.value = offer({
      agents: [{ ...offer().agents[0], status: "included" }],
      lines: [offer().lines[0]],
      total_monthly: 4720,
      then_monthly: 5900,
    });
    show();
    const [agent] = screen.getAllByTestId("detail-agent");
    expect(agent).toHaveTextContent("Inclus avec Starter");
    expect(agent).not.toHaveTextContent("/ mois");
    expect(screen.getByTestId("detail-total")).toHaveTextContent("47,20 € / mois");
    // The total pays for the plan alone: no agent counted in it.
    expect(screen.getByTestId("detail-total")).not.toHaveTextContent("agent");
  });

  it("covered by the plan and its agents: launched as it is, nothing to pay", async () => {
    const user = userEvent.setup();
    offered.value = offer({
      plan_now: "growth",
      change_plan: false,
      lines: [],
      total_monthly: 0,
      then_monthly: null,
      ready: true,
      agents: [{ ...offer().agents[0], status: "owned" }],
    });
    show();
    expect(screen.getByTestId("detail-leka")).toHaveTextContent("couvrent cette demande");
    expect(screen.getByTestId("detail-agent")).toHaveTextContent("Actif");
    // LEKA-464: no price, no total, no checkout — said covered, launched.
    const covered = screen.getByTestId("detail-covered");
    expect(covered).toHaveTextContent("Votre formule Growth et vos agents couvrent cette demande");
    expect(covered).toHaveTextContent(/Revue de code\s*· votre option active/);
    expect(screen.queryByTestId("detail-offer")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-total")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-activate")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("0 € / mois");
    expect(document.body).not.toHaveTextContent("Stripe");
    await user.click(screen.getByTestId("detail-launch"));
    expect(launch).toHaveBeenCalledWith(
      [{ key: "code-review", inputs: {}, formats: [], sources: [] }],
      expect.anything(),
    );
  });

  it("an agent its plan includes: never offered for sale (LEKA-464)", () => {
    offered.value = offer({
      plan_now: "growth",
      change_plan: false,
      lines: [],
      total_monthly: 0,
      then_monthly: null,
      ready: true,
      agents: [{ ...offer().agents[0], status: "included" }],
    });
    show();
    expect(screen.getByTestId("detail-covered")).toHaveTextContent(/Revue de code\s*· inclus dans votre formule/);
    expect(screen.queryByTestId("detail-line")).not.toBeInTheDocument();
  });

  it("a specialised agent missing: its real price and why, before any consent (LEKA-464)", () => {
    offered.value = offer({
      plan_now: "growth",
      change_plan: false,
      plan: { ...offer().plan, key: "growth", name: "Growth" },
      lines: [offer().lines[1]],
      total_monthly: 900,
      then_monthly: null,
      ready: false,
    });
    show();
    const [line] = screen.getAllByTestId("detail-line");
    expect(line).toHaveTextContent("Revue de code");
    expect(line).toHaveTextContent("9 € / mois");
    expect(line).toHaveTextContent("Option mensuelle : non incluse dans la formule Growth.");
    expect(screen.getByTestId("detail-total")).toHaveTextContent("Total mensuel (HT)");
    expect(screen.queryByTestId("detail-covered")).not.toBeInTheDocument();
  });

  it("an agent still waiting on its information: completed first, never paid for to be refused", () => {
    PROPOSAL.agents[0].missing = ["parcours"] as never[];
    try {
      show();
      expect(screen.getByTestId("detail-complete")).toHaveTextContent("Compléter les informations");
      expect(screen.queryByTestId("detail-activate")).not.toBeInTheDocument();
    } finally {
      PROPOSAL.agents[0].missing = [];
    }
  });

  it("asks the architect for its PDF and PowerPoint unless unticked (2026-10-16)", async () => {
    const user = userEvent.setup();
    const architect = {
      ...PROPOSAL.agents[0],
      key: "application-architecture",
      title: "Architecte applicatif",
      deliverables: ["report", "pptx", "pdf"],
    };
    proposed.value = { ...PROPOSAL, agents: [architect] };
    offered.value = offer({
      plan_now: "growth",
      change_plan: false,
      lines: [],
      total_monthly: 0,
      then_monthly: null,
      ready: true,
      agents: [{ ...offer().agents[0], key: "application-architecture", status: "included" }],
    });
    show();
    const files = screen.getByTestId("detail-agent-files");
    expect(within(files).getByTestId("detail-agent-file-pdf")).toBeChecked();
    expect(within(files).getByTestId("detail-agent-file-pptx")).toBeChecked();
    await user.click(within(files).getByTestId("detail-agent-file-pdf"));
    await user.click(screen.getByTestId("detail-launch"));
    expect(launch).toHaveBeenCalledWith(
      [{ key: "application-architecture", inputs: {}, formats: ["pptx"], sources: [] }],
      expect.anything(),
    );
  });

  it("says the month's capacity is spent, and offers more — never an overage", () => {
    offered.value = offer({ plan_now: "starter", blocked: "credits_exhausted" });
    show();
    expect(screen.getByTestId("detail-leka")).toHaveTextContent("capacité IA de votre formule Starter est épuisée");
    expect(screen.getByTestId("detail-leka")).toHaveTextContent("rien n'est facturé en dépassement");
    // The plan above, said why: never a launch nor an overage.
    expect(screen.queryByTestId("detail-launch")).not.toBeInTheDocument();
    const [plan] = screen.getAllByTestId("detail-line-why");
    expect(plan).toHaveTextContent("La capacité IA de votre formule Starter est épuisée ce mois-ci.");
  });

  it("lays the plan out step by step, LEKA's own steps included", () => {
    show();
    const [step] = screen.getAllByTestId("detail-plan-step");
    expect(step).toHaveTextContent("Analyse du code et des dépendances");
    expect(step).toHaveTextContent("Revue de code");
    expect(step).toHaveTextContent("9 € / mois");
  });
});
