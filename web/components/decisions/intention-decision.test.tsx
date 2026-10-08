/**
 * An intention's decision on its page (LEKA-390).
 *
 * What these protect: decided, it says so — by whom, why, at which
 * revision, what the modification changed — and offers nothing more to
 * vote; nothing at all when the intention asks to change nothing.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const INTENTION = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const BILLING = "6c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const choices = vi.hoisted(() => ({ of: vi.fn() }));

vi.mock("@/lib/decisions", async (original) => ({
  ...(await original<typeof import("@/lib/decisions")>()),
  decisions: choices,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => ["intention:read", "intention:approve"],
  useCurrentUser: () => ({ id: ME }),
}));

const { IntentionDecision } = await import("@/components/decisions/intention-decision");

const proposal = (environment: string) => ({
  id: "restart",
  action: "restart",
  targets: [{ id: BILLING, name: "Billing API", type: "service" }],
  environment,
  constraints: [],
  reversible: true,
});

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

beforeEach(() => vi.clearAllMocks());

describe("an intention's decision", () => {
  it("says what was decided, by whom, why — and nothing more to vote", async () => {
    choices.of.mockResolvedValue([
      {
        id: "d1",
        intention_id: INTENTION,
        number: 1,
        status: "approved",
        open: false,
        risk: "low",
        analysis_risk: "low",
        revision: 2,
        required_approvals: 1,
        separate_asker: false,
        approvers: [ME],
        proposals: [proposal("staging")],
        analysis_id: null,
        context_version: 1,
        asked_by: "someone",
        created_at: new Date().toISOString(),
        decided_at: new Date().toISOString(),
        votes: [
          {
            id: "v1",
            revision: 1,
            verdict: "modify",
            by: ME,
            at: new Date().toISOString(),
            reason: "D'abord en staging.",
            changes: {
              from: { proposals: [proposal("production")] },
              to: { proposals: [proposal("staging")] },
            },
            context: {},
          },
        ],
      },
    ]);
    show();
    const decision = await screen.findByTestId("decision");
    expect(decision).toHaveTextContent("Décision n° 1");
    expect(screen.getByTestId("decision-status")).toHaveTextContent("Validée");
    expect(screen.getByTestId("decision-risk")).toHaveTextContent("Risque faible");
    const [vote] = screen.getAllByTestId("decision-vote");
    expect(vote).toHaveTextContent("Modifiée et validée par vous");
    expect(vote).toHaveTextContent(
      "Redémarrer · Billing API · production → Redémarrer · Billing API · staging",
    );
    expect(vote).toHaveTextContent("« D'abord en staging. »");
    expect(screen.queryByTestId("decision-actions")).not.toBeInTheDocument();
  });

  it("shows nothing when nothing is to decide", async () => {
    choices.of.mockResolvedValue([]);
    const { container } = show();
    await vi.waitFor(() => expect(choices.of).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
