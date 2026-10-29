/**
 * A decision's governance, on its card (LEKA-404).
 *
 * What these protect: why it is at its risk, in words — the analysis's,
 * each rule that raised it; the role one approver must hold; a freeze that
 * covered it, said with its reason; escalated, said; a member an approver
 * lent their authority to votes in that approver's name — and the API is
 * told whose; without one, a member does not vote; a vote cast for someone
 * says for whom, as which role.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { Decision, Delegation } from "@/lib/decisions";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ADA = "8c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ASKER = "7c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const INTENTION = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const BILLING = "6c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const choices = vi.hoisted(() => ({ of: vi.fn(), delegations: vi.fn(), vote: vi.fn() }));
const people = vi.hoisted(() => ({ members: vi.fn() }));

vi.mock("@/lib/decisions", async (original) => ({
  ...(await original<typeof import("@/lib/decisions")>()),
  decisions: choices,
}));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: people,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => ["intention:read", "intention:create"],
  useCurrentUser: () => ({ id: ME }),
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { IntentionDecision } = await import("@/components/decisions/intention-decision");

const NOW = Date.now();
const iso = (hours: number) => new Date(NOW + hours * 3_600_000).toISOString();

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    id: "d1",
    intention_id: INTENTION,
    number: 1,
    status: "proposed",
    open: true,
    risk: "critical",
    analysis_risk: "low",
    revision: 1,
    required_approvals: 2,
    separate_asker: true,
    approvers: [],
    proposals: [
      {
        id: "migrate",
        action: "migrate",
        targets: [{ id: BILLING, name: "Billing API", type: "service" }],
        environment: "production",
        constraints: [],
        reversible: false,
      },
    ],
    analysis_id: null,
    context_version: 1,
    asked_by: ASKER,
    created_at: iso(-6),
    decided_at: null,
    votes: [],
    governance: {
      reasons: [
        { code: "analysis", params: { risk: "low" } },
        { code: "rule", params: { rule: "irreversible", action: "migrate", at_least: "high" } },
        {
          code: "rule",
          params: { rule: "irreversible_in_production", action: "migrate", at_least: "critical" },
        },
      ],
      required_role: "owner",
      valid_hours: 24,
      escalate_at: iso(-2),
      escalated_at: iso(-2),
      valid_until: null,
      frozen: false,
      waived: false,
      exceptions: [],
    },
    ...overrides,
  } as Decision;
}

const lent: Delegation = {
  id: "g1",
  delegated_by: ADA,
  delegated_to: ME,
  max_risk: "critical",
  starts_at: iso(-24),
  ends_at: iso(24 * 6),
  reason: "Congés d'Ada",
  revoked_at: null,
  revoked_by: null,
  active: true,
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <IntentionDecision intentionId={INTENTION} />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  people.members.mockResolvedValue([
    {
      id: "m1",
      user_id: ADA,
      role: "admin",
      email: "ada@acme.io",
      first_name: "Ada",
      last_name: "Admin",
      joined_at: iso(-1000),
    },
  ]);
  choices.delegations.mockResolvedValue([]);
});

describe("a decision's governance", () => {
  it("says why its risk, the role it needs, that it was escalated", async () => {
    choices.of.mockResolvedValue([decision()]);
    show();
    const card = await screen.findByTestId("decision");
    expect(screen.getByTestId("decision-risk")).toHaveTextContent("Risque critique");
    expect(screen.getByTestId("decision-requirement")).toHaveTextContent(
      "2 validations requises par une autre personne que le demandeur, dont un propriétaire",
    );
    const reasons = within(card).getByTestId("decision-reasons");
    expect(reasons).toHaveTextContent("L'analyse l'estime faible");
    expect(reasons).toHaveTextContent("Irréversible : au moins élevé");
    expect(reasons).toHaveTextContent("Irréversible en production : au moins critique");
    expect(screen.getByTestId("decision-escalated-pill")).toHaveTextContent("Escaladée");
    expect(screen.getByTestId("decision-escalated")).toHaveTextContent(
      "Escaladée aux propriétaires",
    );
  });

  it("says plainly what each action does, and what approving or refusing changes", async () => {
    // 2026-10-29: « on comprend pas vraiment pourquoi on cliquerait sur valider ».
    choices.of.mockResolvedValue([decision()]);
    show();
    expect(await screen.findByTestId("decision-effect")).toHaveTextContent(
      "Si vous validez, LEKA pourra migrer Billing API vers sa nouvelle cible en production.",
    );
    const choice = screen.getByTestId("decision-choice");
    expect(choice).toHaveTextContent("Valider : ces actions pourront être lancées à l'étape Action");
    expect(choice).toHaveTextContent("Refuser : rien n'est fait");
  });

  it("says the freeze that covered it", async () => {
    choices.of.mockResolvedValue([
      decision({
        governance: {
          ...decision().governance!,
          escalated_at: null,
          frozen: true,
          exceptions: [
            { id: "x1", kind: "freeze", reason: "Clôture comptable", ends_at: iso(30) },
          ],
        },
      }),
    ]);
    show();
    expect(await screen.findByTestId("decision-frozen")).toHaveTextContent(
      "Gelée à son ouverture : « Clôture comptable »",
    );
    expect(screen.getByTestId("decision-escalates")).toHaveTextContent(
      "Escaladée aux propriétaires le",
    );
  });

  it("says what a risky action lacks, and that it cannot be approved", async () => {
    choices.of.mockResolvedValue([
      decision({
        governance: {
          ...decision().governance!,
          escalated_at: null,
          grounding: { gate: "blocked", missing: ["changes", "ownership"], stale: ["model_stale"] },
        },
      }),
    ]);
    show();
    const note = await screen.findByTestId("decision-grounding");
    expect(note).toHaveTextContent("Action risquée sans les preuves nécessaires");
    expect(note).toHaveTextContent("le dernier changement, son responsable, un contexte à jour");
    expect(note).toHaveTextContent("analysée à nouveau");
  });

  it("a member does not vote — unless an approver lent them their authority", async () => {
    choices.of.mockResolvedValue([decision()]);
    const { unmount } = show();
    expect(await screen.findByText("Seules les personnes qui peuvent valider décident.")).toBeVisible();
    unmount();

    choices.delegations.mockResolvedValue([lent]);
    choices.vote.mockResolvedValue(decision());
    show();
    const authority = await screen.findByTestId("decision-authority");
    await waitFor(() => expect(authority).toHaveTextContent("Au nom de Ada Admin"));
    expect(screen.getByText("Vous votez avec l'autorité qui vous a été déléguée.")).toBeVisible();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("decision-approve"));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Valider" }));
    await waitFor(() =>
      expect(choices.vote).toHaveBeenCalledWith(INTENTION, "approve", { on_behalf_of: ADA }),
    );
  });

  it("a delegation that does not reach its risk gives no vote", async () => {
    choices.of.mockResolvedValue([decision()]);
    choices.delegations.mockResolvedValue([{ ...lent, max_risk: "high" }]);
    show();
    expect(await screen.findByText("Seules les personnes qui peuvent valider décident.")).toBeVisible();
    expect(screen.queryByTestId("decision-authority")).not.toBeInTheDocument();
  });

  it("a vote cast for someone says for whom, as which role", async () => {
    choices.of.mockResolvedValue([
      decision({
        status: "approved",
        open: false,
        risk: "medium",
        approvers: [ADA],
        decided_at: iso(-1),
        votes: [
          {
            id: "v1",
            revision: 1,
            verdict: "approve",
            by: ME,
            on_behalf_of: ADA,
            role: "admin",
            at: iso(-1),
            reason: null,
            changes: {},
            context: {},
          },
        ],
        governance: { ...decision().governance!, escalated_at: null, valid_until: iso(23) },
      }),
    ]);
    show();
    const vote = await screen.findByTestId("decision-vote");
    await waitFor(() => expect(vote).toHaveTextContent("Validée par vous au nom de Ada Admin (administrateur)"));
    expect(screen.getByTestId("decision-valid")).toHaveTextContent("Validation valable jusqu'au");
  });
});
