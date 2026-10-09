/**
 * Where an intention goes (LEKA-398), on its overview.
 *
 * What these protect: the capability LEKA chose is said, each one it
 * considered with its score and the signals behind it in words; one left
 * out is said why — a source to connect, the policy that keeps a question
 * from what proposes actions; a chosen agent is offered to run for the
 * intention; LEKA's own analysis when nothing fits better, said so; an
 * unclear intention says what to ask and what it could mean; routed again
 * on demand.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RoutedCandidate, Routing } from "@/lib/intentions/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({ routing: vi.fn(), route: vi.fn() }));
const catalogue = vi.hoisted(() => ({ one: vi.fn() }));

vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: api,
}));
vi.mock("@/lib/capabilities", async (original) => ({
  ...(await original<typeof import("@/lib/capabilities")>()),
  capabilities: catalogue,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { RoutingPanel } = await import("@/components/intentions/routing");

function candidate(overrides: Partial<RoutedCandidate> = {}): RoutedCandidate {
  return {
    key: "dependencies",
    title: "Dependencies",
    kind: "rules",
    category: "architecture",
    score: 5,
    eligible: true,
    selected: false,
    available: true,
    reasons: [],
    signals: [
      { code: "goal", points: 3, detail: "map_dependencies" },
      { code: "kind", points: 2, detail: "dependency" },
    ],
    needs_inputs: [],
    ...overrides,
  };
}

const ARCHITECT = candidate({
  key: "application-architecture",
  title: "Architecte applicatif",
  kind: "agent",
  score: 8,
  selected: true,
  signals: [
    { code: "goal", points: 3, detail: "map_dependencies" },
    { code: "kind", points: 2, detail: "dependency" },
    { code: "words", points: 2, detail: "architecture, parcours" },
    { code: "context_sources", points: 1, detail: "confluence" },
  ],
  needs_inputs: ["parcours", "perimetre"],
});

function routing(overrides: Partial<Routing> = {}): Routing {
  return {
    id: "r1",
    subject_type: "intention",
    subject_id: "i1",
    version: 1,
    outcome: "routed",
    selected: ["application-architecture"],
    candidates: [ARCHITECT, candidate()],
    excluded: [
      candidate({
        key: "restart-planner",
        title: "Restart planner",
        kind: "agent",
        available: false,
        reasons: [{ code: "policy", rule: "proposes_actions_to_a_question" }],
      }),
    ],
    background: ["synthesis"],
    fallback: null,
    why: null,
    questions: [],
    suggestions: [],
    query: {},
    at: "2026-10-09T10:00:00Z",
    ...overrides,
  };
}

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <RoutingPanel intentionId="i1" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.routing.mockResolvedValue(routing());
  api.route.mockResolvedValue(routing({ id: "r2" }));
  catalogue.one.mockResolvedValue({
    key: "application-architecture",
    title: "Architecte applicatif",
    kind: "agent",
    available: true,
    inputs: [
      { name: "parcours", type: "text", required: true, description: "", choices: [], entity_types: [] },
    ],
  });
});

describe("where an intention goes", () => {
  it("says what was chosen, why each was ranked, why one was left out — and offers the agent", async () => {
    show();
    const panel = await screen.findByTestId("intention-routing");
    expect(panel).toHaveAttribute("data-outcome", "routed");
    expect(panel).toHaveTextContent("LEKA la confie à : Architecte applicatif");
    const ranked = within(panel).getByTestId("routing-candidates");
    expect(ranked).toHaveTextContent(
      "objectif · type de demande · mots : architecture, parcours · sources du contexte : confluence",
    );
    expect(ranked).toHaveTextContent("score 8");
    expect(within(panel).getByTestId("routing-excluded")).toHaveTextContent(
      "Une question n'est jamais confiée à une capacité qui propose des actions",
    );
    // The chosen agent, to run for the intention.
    expect(await screen.findByTestId("agent-run-form")).toBeInTheDocument();
  });

  it("falls back to LEKA's analysis, saying why", async () => {
    api.routing.mockResolvedValue(
      routing({ outcome: "fallback", selected: [], fallback: "analysis", why: "excluded", candidates: [] }),
    );
    show();
    const panel = await screen.findByTestId("intention-routing");
    expect(panel).toHaveTextContent("La capacité la plus adaptée ne peut pas être utilisée ici");
    expect(screen.queryByTestId("agent-run-form")).not.toBeInTheDocument();
  });

  it("says what to ask when it is not clear, and what it could mean", async () => {
    api.routing.mockResolvedValue(
      routing({
        outcome: "clarify",
        why: "unclear",
        selected: [],
        candidates: [candidate({ key: "ownership", title: "Ownership", eligible: false })],
        questions: ["Which payment: payment-api or payment-worker?"],
        suggestions: ["ownership"],
      }),
    );
    show();
    const asked = await screen.findByTestId("routing-clarify");
    expect(asked).toHaveTextContent("Which payment: payment-api or payment-worker?");
    expect(asked).toHaveTextContent("Elle pourrait concerner : Responsabilités");
  });

  it("routes again on demand", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByTestId("intention-routing");
    await user.click(screen.getByRole("button", { name: "Router à nouveau" }));
    await waitFor(() => expect(api.route).toHaveBeenCalledWith("i1"));
  });
});
