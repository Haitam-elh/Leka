/**
 * The workspace's AI, governed (LEKA-406).
 *
 * What these protect: a control is said in words — which models, how much,
 * what an answer may not carry, which agents wait — created with its kind's
 * own fields only, turned off; a run waiting for approval is approved or
 * rejected by someone who may, never offered to who asked it; what the
 * controls did is said, with whom it was for.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { AgentRun } from "@/lib/agent-runs";
import type { AIControl } from "@/lib/ai-governance";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const ai = vi.hoisted(() => ({
  controls: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  events: vi.fn(),
}));
const runs = vi.hoisted(() => ({ awaiting: vi.fn(), decide: vi.fn() }));
const people = vi.hoisted(() => ({ members: vi.fn() }));
const models = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/ai-governance", async (original) => ({
  ...(await original<typeof import("@/lib/ai-governance")>()),
  aiGovernance: ai,
}));
vi.mock("@/lib/agent-runs", async (original) => ({
  ...(await original<typeof import("@/lib/agent-runs")>()),
  agentRuns: runs,
}));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: people,
}));
vi.mock("@/lib/models", async (original) => ({
  ...(await original<typeof import("@/lib/models")>()),
  models,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { AIAuditCard, AIControlsCard, ApprovalsCard, controlSaid } = await import(
  "@/components/governance/ai-controls"
);
const fr = DICTIONARIES.fr;

const BASE: Omit<AIControl, "id" | "name" | "kind"> = {
  updated_at: "2026-10-10T09:00:00Z",
  description: null,
  purposes: [],
  roles: [],
  enabled: true,
  providers: [],
  owners: [],
  block: false,
  period: "day",
  per: "workspace",
  max_calls: null,
  max_tokens: null,
  max_cost_usd: null,
  detect: [],
  on_finding: "redact",
  risk_at_least: "high",
};
const SECRETS: AIControl = {
  ...BASE,
  id: "c1",
  name: "Aucun secret",
  kind: "output_check",
  detect: ["secrets"],
  on_finding: "block",
};
const LIMIT: AIControl = {
  ...BASE,
  id: "c2",
  name: "Budget agents",
  kind: "usage_limit",
  purposes: ["agent:*"],
  per: "person",
  max_calls: 20,
};

function run(over: Partial<AgentRun>): AgentRun {
  return {
    id: "r1",
    key: "security-review",
    title: "Revue de sécurité",
    version: "1.0.0",
    status: "awaiting_approval",
    inputs: {},
    requested_by: "u-ana",
    mine: false,
    intention_id: null,
    context_id: null,
    context_version: null,
    format: "markdown",
    pending: [],
    error: null,
    reasons: [],
    provider: null,
    model: null,
    model_version: null,
    tool_calls: 0,
    queued_at: "2026-10-10T09:00:00Z",
    started_at: null,
    finished_at: null,
    ...over,
  } as AgentRun;
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
  ai.controls.mockResolvedValue([SECRETS, LIMIT]);
  ai.events.mockResolvedValue([]);
  people.members.mockResolvedValue([
    { user_id: "u-ana", email: "ana@acme.fr", first_name: "Ana", last_name: null, role: "member" },
  ]);
  models.get.mockResolvedValue({ providers: [{ name: "mistral", title: "Mistral" }] });
});

describe("controlSaid", () => {
  it("says what each kind does, over which work, for whom", () => {
    expect(controlSaid(fr, SECRETS)).toBe("Secrets : Bloquer la réponse · tout");
    expect(controlSaid(fr, LIMIT)).toBe("20 appels par jour, par personne · agent:*");
    expect(
      controlSaid(fr, { ...BASE, id: "c3", name: "x", kind: "model_access", providers: ["mistral"], roles: ["member"] }),
    ).toContain("seulement mistral");
    expect(controlSaid(fr, { ...BASE, id: "c4", name: "x", kind: "approval", risk_at_least: "medium" })).toContain(
      "agents de risque moyen ou plus",
    );
  });
});

describe("AIControlsCard", () => {
  it("lists the controls and creates one with its kind's fields", async () => {
    ai.create.mockResolvedValue({ ...LIMIT, id: "c9" });
    show(<AIControlsCard canManage roles={[]} />);
    const list = await screen.findByTestId("ai-controls");
    expect(within(list).getByText("Aucun secret")).toBeInTheDocument();
    expect(within(list).getByText("Contrôle des réponses")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Nouveau contrôle"), "Limite du mois");
    await user.selectOptions(screen.getByLabelText("Type"), "usage_limit");
    await user.selectOptions(screen.getByLabelText("Période"), "month");
    await user.type(screen.getByLabelText("Tokens max."), "500000");
    await user.type(screen.getByLabelText("Travaux concernés"), "agent:*, intention.*");
    await user.click(screen.getByRole("button", { name: "Créer le contrôle" }));

    await waitFor(() => expect(ai.create).toHaveBeenCalled());
    expect(ai.create.mock.calls[0][0]).toMatchObject({
      name: "Limite du mois",
      kind: "usage_limit",
      period: "month",
      max_tokens: 500000,
      max_calls: null,
      purposes: ["agent:*", "intention.*"],
    });
  });

  it("turns one off, keeping what it is", async () => {
    ai.update.mockResolvedValue({ ...SECRETS, enabled: false });
    show(<AIControlsCard canManage roles={[]} />);
    const list = await screen.findByTestId("ai-controls");
    const user = userEvent.setup();
    await user.click(within(list).getAllByRole("button", { name: "Désactiver" })[0]);
    await waitFor(() => expect(ai.update).toHaveBeenCalled());
    expect(ai.update.mock.calls[0]).toEqual([
      "c1",
      expect.objectContaining({ name: "Aucun secret", detect: ["secrets"], on_finding: "block", enabled: false }),
    ]);
  });

  it("offers no change to who may not manage", async () => {
    show(<AIControlsCard canManage={false} roles={[]} />);
    await screen.findByTestId("ai-controls");
    expect(screen.queryByTestId("ai-control-form")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supprimer" })).not.toBeInTheDocument();
  });
});

describe("ApprovalsCard", () => {
  it("approves or rejects another's run — never one's own", async () => {
    runs.awaiting.mockResolvedValue([run({}), run({ id: "r2", mine: true })]);
    runs.decide.mockResolvedValue(run({ status: "queued" }));
    show(<ApprovalsCard canApprove />);
    const list = await screen.findByTestId("ai-approvals");
    const [theirs, mine] = within(list).getAllByRole("listitem");
    expect(within(theirs).getByText(/Ana/)).toBeInTheDocument();
    expect(within(mine).getByText(/votre demande/)).toBeInTheDocument();
    expect(within(mine).queryByRole("button", { name: "Approuver" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(theirs).getByRole("button", { name: "Approuver" }));
    await waitFor(() => expect(runs.decide).toHaveBeenCalledWith("r1", true));
    await user.click(within(theirs).getByRole("button", { name: "Refuser" }));
    await waitFor(() => expect(runs.decide).toHaveBeenCalledWith("r1", false));
  });

  it("offers no decision to who may not approve", async () => {
    runs.awaiting.mockResolvedValue([run({})]);
    show(<ApprovalsCard canApprove={false} />);
    await screen.findByTestId("ai-approvals");
    expect(screen.queryByRole("button", { name: "Approuver" })).not.toBeInTheDocument();
  });
});

describe("AIAuditCard", () => {
  it("says what each control did, to what, for whom", async () => {
    ai.events.mockResolvedValue([
      {
        id: "e1",
        control_id: "c1",
        control_name: "Aucun secret",
        kind: "output_check",
        outcome: "blocked",
        purpose: "agent:security-review",
        ref: null,
        run_id: null,
        user_id: "u-ana",
        provider: "google",
        model: "gemini-3.8-flash",
        at: "2026-10-10T09:00:00Z",
        detail: { found: ["aws_key"] },
      },
    ]);
    show(<AIAuditCard />);
    const audit = await screen.findByTestId("ai-audit");
    expect(within(audit).getByText("Réponse bloquée")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(audit).getByText(
          "Aucun secret · agent:security-review · google gemini-3.8-flash · aws_key · Ana",
        ),
      ).toBeInTheDocument(),
    );
  });
});
