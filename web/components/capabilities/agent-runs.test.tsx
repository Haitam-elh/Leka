/**
 * An agent, run (LEKA-395), on its capability's sheet.
 *
 * What these protect: the form asks what the agent's contract takes — a
 * text, a yes or no — and sends it as the contract takes it, an empty
 * optional left out; what the API refuses is said by the field it concerns;
 * an agent that cannot run here cannot be started. Its runs are listed,
 * each with where it stands — failed, said why in words — and one opened
 * shows what it delivered, its files still to come, every step in words —
 * a tool read, one not offered and why — and what its model calls took;
 * a run of one's own on its way can be cancelled.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRun, AgentRunDetail } from "@/lib/agent-runs";
import { ApiError } from "@/lib/api";
import type { CapabilityDetail } from "@/lib/capabilities";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({ list: vi.fn(), one: vi.fn(), start: vi.fn(), cancel: vi.fn() }));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/agent-runs", async (original) => ({
  ...(await original<typeof import("@/lib/agent-runs")>()),
  agentRuns: api,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));

const { AgentRuns, RunAgent, inputsOf } = await import("@/components/capabilities/agent-runs");

const ARCHITECT = {
  key: "application-architecture",
  title: "Architecte applicatif",
  kind: "agent",
  available: true,
  inputs: [
    { name: "parcours", type: "text", required: true, description: "Le parcours", choices: [], entity_types: [] },
    { name: "perimetre", type: "text", required: true, description: "Le périmètre", choices: [], entity_types: [] },
    {
      name: "vue_applicative",
      type: "boolean",
      required: false,
      description: "Ajouter la vue applicative",
      choices: [],
      entity_types: [],
    },
  ],
} as unknown as CapabilityDetail;

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    key: ARCHITECT.key,
    title: "Architecte applicatif",
    version: "18.0.0",
    status: "succeeded",
    inputs: { parcours: "Paiement CB", perimetre: "Digital" },
    requested_by: "me",
    mine: true,
    intention_id: null,
    context_id: "c1",
    context_version: 1,
    format: "markdown",
    pending: ["pptx", "pdf"],
    error: null,
    reasons: [],
    provider: "google",
    model: "gemini-3.8-flash",
    model_version: "gemini-3.8-flash-001",
    tool_calls: 2,
    queued_at: "2026-10-09T10:00:00Z",
    started_at: "2026-10-09T10:00:01Z",
    finished_at: "2026-10-09T10:01:00Z",
    ...overrides,
  };
}

const DONE: AgentRunDetail = {
  ...run(),
  output: "# Architecture — Paiement CB",
  usage: { calls: 3, tokens_in: 3000, tokens_out: 900, cost_usd: 0.0056 },
  events: [
    { seq: 1, kind: "queued", at: "2026-10-09T10:00:00Z", detail: {} },
    { seq: 2, kind: "started", at: "2026-10-09T10:00:01Z", detail: {} },
    { seq: 3, kind: "context", at: "2026-10-09T10:00:02Z", detail: { given: 12, out_of_scope: 2, beyond: 0 } },
    { seq: 4, kind: "tool_withheld", at: "2026-10-09T10:00:02Z", detail: { name: "restart_service", why: "acts" } },
    { seq: 5, kind: "tool", at: "2026-10-09T10:00:10Z", detail: { name: "search_entities", outcome: "ok" } },
    { seq: 6, kind: "answered", at: "2026-10-09T10:00:59Z", detail: { model: "gemini-3.8-flash" } },
    { seq: 7, kind: "succeeded", at: "2026-10-09T10:01:00Z", detail: {} },
  ],
};

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.start.mockResolvedValue(run({ status: "queued" }));
  api.list.mockResolvedValue([]);
  api.one.mockResolvedValue(DONE);
  api.cancel.mockResolvedValue(run({ status: "cancelled" }));
});

describe("running an agent", () => {
  it("sends what its contract takes, an empty optional left out", () => {
    expect(inputsOf(ARCHITECT.inputs, { parcours: " Paiement CB ", perimetre: "" })).toEqual({
      parcours: "Paiement CB",
    });
  });

  it("asks what it takes and runs it", async () => {
    const user = userEvent.setup();
    show(<RunAgent capability={ARCHITECT} />);
    await user.type(screen.getByLabelText(/parcours/), "Paiement CB");
    await user.type(screen.getByLabelText(/perimetre/), "Digital");
    await user.click(screen.getByRole("checkbox", { name: "Ajouter la vue applicative" }));
    await user.click(screen.getByRole("button", { name: "Lancer" }));
    await waitFor(() =>
      expect(api.start).toHaveBeenCalledWith({
        key: "application-architecture",
        inputs: { parcours: "Paiement CB", perimetre: "Digital", vue_applicative: true },
      }),
    );
    expect(notices.success).toHaveBeenCalledWith(expect.objectContaining({ title: "Agent lancé" }));
  });

  it("says what was refused, by field", async () => {
    api.start.mockRejectedValue(
      new ApiError(422, "/agent-runs", "Not what it takes.", "validation_failed", {
        "inputs.parcours": "missing",
      }),
    );
    const user = userEvent.setup();
    show(<RunAgent capability={ARCHITECT} />);
    await user.click(screen.getByRole("button", { name: "Lancer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Obligatoire.");
  });

  it("cannot be started when it cannot run here", () => {
    show(<RunAgent capability={{ ...ARCHITECT, available: false }} />);
    expect(screen.getByRole("button", { name: "Lancer" })).toBeDisabled();
    expect(screen.getByText("Il ne peut pas s'exécuter ici pour l'instant.")).toBeInTheDocument();
  });
});

describe("its runs", () => {
  it("lists them, says why one failed, opens one step by step", async () => {
    api.list.mockResolvedValue([
      run({ id: "f", status: "failed", error: "no_model", tool_calls: 0, model: null }),
      run(),
    ]);
    const user = userEvent.setup();
    show(<AgentRuns agentKey={ARCHITECT.key} />);
    const [failed, done] = await screen.findAllByTestId("agent-run");
    expect(failed).toHaveTextContent("Échouée · aucun modèle de langage n'a répondu");
    expect(done).toHaveTextContent("Terminée");
    expect(done).toHaveTextContent("2 appel(s) d'outil");

    await user.click(within(done).getByRole("button", { name: /Paiement CB/ }));
    const detail = await screen.findByTestId("agent-run-detail");
    expect(within(detail).getByTestId("agent-run-output")).toHaveTextContent("# Architecture — Paiement CB");
    expect(detail).toHaveTextContent("PPTX, PDF : pas encore générés");
    const steps = within(detail).getByTestId("agent-run-steps");
    expect(steps).toHaveTextContent("Contexte : 12 élément(s) fournis, 2 écartés");
    expect(steps).toHaveTextContent("Outil non proposé : restart_service (il agirait)");
    expect(steps).toHaveTextContent("Outil search_entities : lu");
    expect(within(detail).getByTestId("agent-run-usage")).toHaveTextContent(
      "3 appel(s) au modèle · 3900 tokens",
    );
  });

  it("cancels a run of one's own on its way", async () => {
    api.list.mockResolvedValue([run({ status: "running" }), run({ id: "x", status: "queued", mine: false })]);
    const user = userEvent.setup();
    show(<AgentRuns agentKey={ARCHITECT.key} />);
    const [mine, theirs] = await screen.findAllByTestId("agent-run");
    expect(within(theirs).queryByRole("button", { name: "Annuler" })).not.toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(api.cancel).toHaveBeenCalledWith(run().id));
  });
});
