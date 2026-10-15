/**
 * An intention's brief and what it takes, on screen (LEKA-439).
 *
 * What these protect:
 * - each part of what LEKA must know said with its state — a model's
 *   reading said assumed, never a fact; the action asked named;
 * - each question says why it is asked and answers by id, in words, or
 *   « je ne sais pas »; once answered, said and changeable;
 * - what follows is said: analyse, clarify, continue with its limits, block;
 * - what it takes: each capability included or in beta, the credits left
 *   and what it should cost; the least it takes — a source to connect, the
 *   cheapest plan — and changing plan asks first, its price and what
 *   changes said, before the payment page; only who may pay sees it.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type {
  BriefQuestion,
  Feasibility,
  IntentionBrief,
  IntentionDetail,
} from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";

const permissions = vi.hoisted(() => ({ list: ["intention:read", "workspace:update"] }));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentUser: () => ({ id: "u1" }),
  usePermissions: () => permissions.list,
}));
const payment = vi.hoisted(() => ({ checkout: vi.fn(), portal: vi.fn() }));
vi.mock("@/lib/subscription", async (original) => ({
  ...(await original<typeof import("@/lib/subscription")>()),
  subscription: { ...payment, read: vi.fn(), pricing: vi.fn() },
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { BriefView } = await import("@/components/intentions/brief");
const { FeasibilityPanel } = await import("@/components/intentions/feasibility");

type Understanding = NonNullable<IntentionDetail["understanding"]>;

const UNDERSTOOD: Understanding = {
  version: 4,
  text: "Redémarre Billing API en production",
  mode: "request",
  mode_said: "redemarre",
  kind: "general",
  goal: { code: "act", said: ["redemarre"], confidence: 0.9 },
  actions: [
    { code: "restart", said: "redemarre", changes_systems: true, polarity: "affirmed", targets: [] },
  ],
  withheld: [],
  entities: [],
  period: null,
  environment: "production",
  ambiguities: [],
  clear: false,
  off_topic: false,
  scope: null,
};

function question(more: Partial<BriefQuestion> = {}): BriefQuestion {
  return {
    kind: "ambiguous_subject",
    slot: "target",
    blocking: true,
    said: "« billing api » names several things.",
    options: ["Billing API", "Billing API v1"],
    choices: [
      { value: "b1", label: "Billing API", type: "service" },
      { value: "b2", label: "Billing API v1", type: "service" },
    ],
    free: false,
    answer: null,
    ...more,
  };
}

function brief(more: Partial<IntentionBrief> = {}): IntentionBrief {
  return {
    version: 1,
    decision: "clarify",
    restated: null,
    acting: true,
    slots: [
      { slot: "goal", state: "assumed", need: "blocking", value: "act", values: [], origin: "model" },
      { slot: "target", state: "missing", need: "blocking", value: null, values: [], origin: null },
      { slot: "scope", state: "known", need: "blocking", value: "production", values: ["production"], origin: "words" },
      { slot: "expected", state: "known", need: "useful", value: "action", values: [], origin: "words" },
      { slot: "constraints", state: "missing", need: "optional", value: null, values: [], origin: null },
    ],
    questions: [question()],
    limits: [],
    ...more,
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
  permissions.list = ["intention:read", "workspace:update"];
});

describe("an intention's brief", () => {
  it("says each part with its state, a model's reading as assumed, the action named", () => {
    show(<BriefView brief={brief()} understanding={UNDERSTOOD} />);
    const goal = screen.getAllByTestId("brief-slot").find((s) => s.dataset.slot === "goal");
    expect(goal).toHaveAttribute("data-state", "assumed");
    expect(screen.getByText("Supposé par LEKA")).toBeInTheDocument();
    expect(screen.getByText("Une action sur vos systèmes : Redémarrer")).toBeInTheDocument();
    const target = screen.getAllByTestId("brief-slot").find((s) => s.dataset.slot === "target");
    expect(target).toHaveAttribute("data-state", "missing");
    expect(screen.getAllByText("Manquant")).toHaveLength(2);
    expect(screen.getByTestId("brief-decision")).toHaveTextContent(
      "Répondez à la question ci-dessus",
    );
  });

  it("asks why, and answers by id, in words, or « je ne sais pas »", async () => {
    const onAnswer = vi.fn();
    const user = userEvent.setup();
    show(
      <BriefView
        brief={brief({
          questions: [
            question(),
            question({
              kind: "action_without_target",
              choices: [],
              options: ["restart"],
              free: true,
            }),
          ],
        })}
        understanding={UNDERSTOOD}
        onAnswer={onAnswer}
      />,
    );
    const [which, onWhat] = screen.getAllByTestId("brief-question");
    expect(within(which).getByTestId("brief-why")).toHaveTextContent(
      "agir sur le mauvais ne se rattrape pas",
    );
    await user.click(within(which).getByRole("button", { name: "Billing API v1" }));
    expect(onAnswer).toHaveBeenLastCalledWith({
      question: "ambiguous_subject",
      value: "b2",
      unknown: false,
    });
    await user.type(within(onWhat).getByTestId("brief-words"), "Payment API");
    await user.click(within(onWhat).getByTestId("brief-send"));
    expect(onAnswer).toHaveBeenLastCalledWith({
      question: "action_without_target",
      value: "Payment API",
      unknown: false,
    });
    await user.click(within(onWhat).getByTestId("brief-unknown"));
    expect(onAnswer).toHaveBeenLastCalledWith({
      question: "action_without_target",
      value: null,
      unknown: true,
    });
  });

  it("never sends the form it sits in when it is answered in words", async () => {
    // The composer is a form: an answer is not a request launched.
    const sent = vi.fn((event: React.FormEvent) => event.preventDefault());
    const onAnswer = vi.fn();
    const user = userEvent.setup();
    show(
      <form onSubmit={sent}>
        <BriefView
          brief={brief({ questions: [question({ kind: "too_short", choices: [], options: [], free: true })] })}
          understanding={UNDERSTOOD}
          onAnswer={onAnswer}
        />
      </form>,
    );
    await user.type(screen.getByTestId("brief-words"), "Qui en est responsable ?{Enter}");
    expect(onAnswer).toHaveBeenCalledTimes(1);
    await user.type(screen.getByTestId("brief-words"), "encore");
    await user.click(screen.getByTestId("brief-send"));
    expect(onAnswer).toHaveBeenCalledTimes(2);
    expect(sent).not.toHaveBeenCalled();
  });

  it("says what was answered, by its name, and lets it be changed", async () => {
    const user = userEvent.setup();
    show(
      <BriefView
        brief={brief({
          questions: [
            question({ answer: { question: "ambiguous_subject", value: "b1", unknown: false } }),
          ],
        })}
        understanding={UNDERSTOOD}
        onAnswer={vi.fn()}
      />,
    );
    expect(screen.getByTestId("brief-answer")).toHaveTextContent("Votre réponse : Billing API");
    await user.click(screen.getByRole("button", { name: "Modifier" }));
    expect(screen.getByRole("button", { name: "Billing API v1" })).toBeInTheDocument();
  });

  it("says what follows: go on with its limits, or block", () => {
    const { rerender } = show(
      <BriefView
        brief={brief({ decision: "continue", questions: [], limits: ["several_requests"] })}
        understanding={UNDERSTOOD}
      />,
    );
    expect(screen.getByTestId("brief-decision")).toHaveTextContent(
      "LEKA peut avancer, avec ces limites : la première demande d'abord.",
    );
    rerender(
      <QueryClientProvider client={makeQueryClient()}>
        <LocaleProvider>
          <ConfirmProvider>
            <BriefView brief={brief({ decision: "block" })} understanding={UNDERSTOOD} />
          </ConfirmProvider>
        </LocaleProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("brief-decision")).toHaveTextContent(
      "LEKA ne peut pas agir sans savoir sur quoi",
    );
  });
});

function feasibility(more: Partial<Feasibility> = {}): Feasibility {
  return {
    verdict: "ready",
    needed: [
      {
        key: "standing",
        title: "État",
        kind: "rules",
        offer: "included",
        available: true,
        reasons: [],
        delivers: "finding",
        selected: true,
        essential: true,
        credits: null,
        price: null,
      },
      {
        key: "security-review",
        title: "Revue de sécurité",
        kind: "agent",
        offer: "beta",
        available: true,
        reasons: [],
        delivers: "analysis",
        selected: true,
        essential: true,
        credits: 12,
        price: null,
      },
    ],
    credits: {
      plan: "free",
      allowance: 200,
      used: 50,
      remaining: 150,
      state: "ok",
      enforced: true,
      period_end: "2026-11-01T00:00:00Z",
    },
    estimate: 12,
    path: [],
    ...more,
  };
}

describe("what it takes", () => {
  it("says each capability as offered, the credits left and what it should cost", () => {
    show(<FeasibilityPanel feasibility={feasibility()} />);
    expect(screen.getByTestId("feasibility-verdict")).toHaveTextContent("Tout est prêt");
    const [standing, security] = screen.getAllByTestId("feasibility-capability");
    expect(standing).toHaveTextContent("Inclus");
    expect(security).toHaveTextContent("Bêta — inclus pour l'instant, deviendra une option");
    expect(screen.getByTestId("feasibility-credits")).toHaveTextContent(
      "Crédits IA : 150 restants sur 200 (Free)",
    );
    expect(screen.getByTestId("feasibility-credits")).toHaveTextContent(
      "Cette demande : environ 12 crédits",
    );
  });

  it("leads to the source to connect first", () => {
    show(
      <FeasibilityPanel
        feasibility={feasibility({
          verdict: "prerequisites",
          path: [
            {
              kind: "connect_source",
              detail: { capability: "application-architecture", sources: ["confluence", "github"] },
              consent: false,
            },
          ],
        })}
      />,
    );
    const step = screen.getByTestId("feasibility-step");
    expect(step).toHaveTextContent("Connecter une source : Confluence ou GitHub");
    expect(within(step).getByRole("link", { name: /Y aller/ })).toHaveAttribute("href", "/sources");
  });

  it("asks before changing plan — its price, its credits, its launch offer — then pays", async () => {
    payment.checkout.mockResolvedValue({ url: "https://checkout.example/x" });
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const user = userEvent.setup();
    show(
      <FeasibilityPanel
        feasibility={feasibility({
          verdict: "over_quota",
          path: [
            {
              kind: "change_plan",
              detail: {
                plan: "starter",
                monthly_price: 5900,
                credits: 2000,
                launch_percent: 20,
                launch_months: 12,
              },
              consent: true,
            },
          ],
        })}
      />,
    );
    await user.click(screen.getByTestId("feasibility-change-plan"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Passer à Starter ?");
    expect(dialog).toHaveTextContent("59,00");
    expect(dialog).toHaveTextContent("2000 par mois");
    expect(dialog).toHaveTextContent("−20 % les 12 premiers mois");
    // Nothing paid until said yes.
    expect(payment.checkout).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Continuer vers le paiement" }));
    await waitFor(() => expect(payment.checkout).toHaveBeenCalledWith("starter", "month"));
    vi.unstubAllGlobals();
  });

  it("never offers payment to who may not pay for the workspace", () => {
    permissions.list = ["intention:read"];
    show(
      <FeasibilityPanel
        feasibility={feasibility({
          verdict: "over_quota",
          path: [
            {
              kind: "change_plan",
              detail: { plan: "starter", monthly_price: 5900, credits: 2000 },
              consent: true,
            },
          ],
        })}
      />,
    );
    expect(screen.queryByTestId("feasibility-change-plan")).not.toBeInTheDocument();
    expect(screen.getByTestId("feasibility-step")).toHaveTextContent(
      "Demander l'accès à un administrateur",
    );
  });
});
