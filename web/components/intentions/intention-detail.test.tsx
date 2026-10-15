/**
 * An intention's page (LEKA-458).
 *
 * What these protect:
 * - What LEKA says is what the server's offer says: a plan to take, options
 *   to add, everything covered — or the month's capacity spent.
 * - Each agent never shown included when it is not: its price, or
 *   « Inclus », « Actif », « Indisponible ici ».
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
vi.mock("@/components/intentions/agents-decision", () => ({
  useProposal: () => ({ proposal: PROPOSAL, loading: false }),
  AgentsAction: () => <div data-testid="agents-action" />,
}));
vi.mock("@/components/intentions/analysis-tab", () => ({
  AnalysisResults: () => <div />,
  EvidenceTab: () => <div />,
}));

const checkout = vi.hoisted(() => vi.fn());
vi.mock("@/lib/subscription", () => ({ subscription: { checkout } }));

const { IntentionDetailPage } = await import("@/components/intentions/intention-detail");

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
    expect(screen.getByTestId("detail-plan")).toHaveTextContent("Starter");
    const total = screen.getByTestId("detail-total");
    expect(total).toHaveTextContent("56,20 € / mois");
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
    expect(screen.queryByTestId("detail-activate")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("detail-launch"));
    expect(launch).toHaveBeenCalledWith(
      [{ key: "code-review", inputs: {}, formats: [], sources: [] }],
      expect.anything(),
    );
  });

  it("says the month's capacity is spent, and offers more — never an overage", () => {
    offered.value = offer({ plan_now: "starter", blocked: "credits_exhausted" });
    show();
    expect(screen.getByTestId("detail-leka")).toHaveTextContent("capacité IA de votre formule Starter est épuisée");
    expect(screen.getByTestId("detail-leka")).toHaveTextContent("rien n'est facturé en dépassement");
  });

  it("lays the plan out step by step, LEKA's own steps included", () => {
    show();
    const [step] = screen.getAllByTestId("detail-plan-step");
    expect(step).toHaveTextContent("Analyse du code et des dépendances");
    expect(step).toHaveTextContent("Revue de code");
    expect(step).toHaveTextContent("9 € / mois");
  });
});
