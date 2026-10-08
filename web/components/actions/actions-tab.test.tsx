/**
 * An intention's tab Actions (LEKA-391).
 *
 * What these protect: approved, who may approve prepares its plan; ready,
 * each action said with who runs it — an authorized system, or a person —
 * the window it was asked in and when it next opens, run now (asked first,
 * what it runs said) or scheduled; refused, the failing check said; running,
 * a person's step confirmed only with what shows it, the run stopped only
 * saying why; done, its evidence and log in words; failed, what went wrong
 * said and retried; anyone else follows it, and a link that is not http(s)
 * is never one.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { Plan, PlanStep } from "@/lib/actions";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";

const ME = "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ID = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const BILLING = "6c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const permissions = vi.hoisted(() => ({ value: ["intention:read", "intention:approve"] }));
const api = vi.hoisted(() => ({
  of: vi.fn(),
  plan: vi.fn(),
  start: vi.fn(),
  cancel: vi.fn(),
  report: vi.fn(),
}));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/actions", async (original) => ({
  ...(await original<typeof import("@/lib/actions")>()),
  plans: api,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => ({ id: ME }),
}));

const { ActionsTab } = await import("@/components/actions/actions-tab");
const { ApiError } = await import("@/lib/api");

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function intention(overrides: Partial<IntentionDetail> = {}): IntentionDetail {
  return {
    id: ID,
    title: "Redémarre Billing API en production",
    text: "Redémarre Billing API en production",
    kind: "change",
    scope: {},
    status: "approved",
    phase: "active",
    status_changed_at: ago(5),
    summary: null,
    created_by: ME,
    created_at: ago(30),
    updated_at: ago(5),
    context_id: "c1",
    archived_at: null,
    moves: [],
    goal: "act",
    understanding: null,
    links: [],
    ...overrides,
  };
}

function step(overrides: Partial<PlanStep> = {}): PlanStep {
  return {
    id: "s1",
    position: 1,
    proposal_id: "restart",
    action: "restart",
    targets: [{ id: BILLING, name: "Billing API", type: "service" }],
    environment: "production",
    constraints: [],
    executor: "manual",
    endpoint_id: null,
    endpoint_name: null,
    status: "pending",
    started_at: null,
    finished_at: null,
    error: null,
    evidence: {},
    ...overrides,
  };
}

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: "p1",
    intention_id: ID,
    decision_id: "d1",
    number: 1,
    revision: 1,
    status: "planned",
    created_by: ME,
    started_by: null,
    timezone: "UTC",
    scheduled_for: null,
    suggested_for: null,
    started_at: null,
    finished_at: null,
    created_at: ago(2),
    checks: [],
    error: null,
    steps: [step()],
    events: [],
    ...overrides,
  };
}

function show(of: IntentionDetail = intention()) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <ActionsTab intention={of} />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["intention:read", "intention:approve"];
  api.of.mockResolvedValue([]);
  api.plan.mockResolvedValue(plan());
  api.start.mockResolvedValue(plan({ status: "running" }));
  api.cancel.mockResolvedValue(plan({ status: "cancelled" }));
  api.report.mockResolvedValue(plan({ status: "succeeded" }));
});

describe("an intention's actions", () => {
  it("prepares the plan of what was approved", async () => {
    const user = userEvent.setup();
    show();
    const prepare = await screen.findByTestId("plan-prepare");
    expect(prepare).toHaveTextContent("chaque action, et qui l'exécute");
    await user.click(within(prepare).getByTestId("plan-prepare-button"));
    await waitFor(() => expect(api.plan).toHaveBeenCalledWith(ID));
  });

  it("says who runs each action, the window asked, and runs it once asked", async () => {
    const user = userEvent.setup();
    api.of.mockResolvedValue([
      plan({
        suggested_for: "2026-10-08T20:00:00Z",
        steps: [
          step({ constraints: [{ kind: "window", value: "cette nuit" }] }),
          step({
            id: "s2",
            position: 2,
            action: "scale",
            executor: "webhook",
            endpoint_name: "Ops runbooks",
          }),
        ],
      }),
    ]);
    show();
    const [manual, webhook] = await screen.findAllByTestId("plan-step");
    expect(manual).toHaveTextContent("Redémarrer · Billing API · production");
    expect(manual).toHaveTextContent("Par une personne");
    expect(webhook).toHaveTextContent("Par Ops runbooks · système autorisé, appel signé");
    expect(screen.getByTestId("plan-controls")).toHaveTextContent(
      "Demandée « cette nuit » : prochain créneau le",
    );

    await user.click(screen.getByTestId("plan-start"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Redémarrer · Billing API · production");
    await user.click(within(dialog).getByRole("button", { name: "Lancer maintenant" }));
    await waitFor(() =>
      expect(api.start).toHaveBeenCalledWith(ID, { scheduled_for: null, timezone: expect.any(String) }),
    );
  });

  it("says a refused run, and which check failed", async () => {
    const user = userEvent.setup();
    api.of.mockResolvedValue([
      plan({
        checks: [
          { code: "decision_approved", passed: true, detail: {} },
          { code: "endpoint_allows", passed: false, detail: {} },
        ],
      }),
    ]);
    api.start.mockRejectedValue(
      new ApiError(409, "/plan/start", "What must hold does not.", "conflict", {
        refusal: "checks_failed",
      }),
    );
    show();
    const checks = await screen.findByTestId("plan-checks");
    const failing = within(checks).getByText("Le système autorisé accepte toujours cette action");
    expect(failing.closest("li")).toHaveAttribute("data-passed", "false");
    await user.click(screen.getByTestId("plan-start"));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Lancer maintenant",
      }),
    );
    await waitFor(() =>
      expect(notices.error).toHaveBeenCalledWith({
        title: "L'exécution n'a pas été lancée : une vérification ne passe pas.",
      }),
    );
  });

  it("confirms a person's step only with what shows it, and stops only saying why", async () => {
    const user = userEvent.setup();
    api.of.mockResolvedValue([
      plan({ status: "running", started_at: ago(1), steps: [step({ status: "awaiting" })] }),
    ]);
    show(intention({ status: "executing" }));
    const card = await screen.findByTestId("plan-step");
    expect(within(card).getByTestId("step-status")).toHaveTextContent("À confirmer");
    expect(within(card).getByTestId("plan-stages")).toHaveTextContent("Préparation");
    await user.click(within(card).getByTestId("step-done"));
    expect(api.report).not.toHaveBeenCalled();
    expect(notices.error).toHaveBeenCalledWith({ title: "Dites ce qui le montre." });
    await user.type(within(card).getByTestId("step-report-note"), "Redémarré depuis la console.");
    await user.click(within(card).getByTestId("step-done"));
    await waitFor(() =>
      expect(api.report).toHaveBeenCalledWith(ID, "s1", {
        outcome: "succeeded",
        note: "Redémarré depuis la console.",
        link: null,
      }),
    );

    expect(screen.getByTestId("plan-controls")).toHaveTextContent("Vous gardez le contrôle");
    await user.click(screen.getByTestId("plan-cancel"));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Mauvais service.");
    await user.click(within(dialog).getByRole("button", { name: "Interrompre l'exécution" }));
    await waitFor(() => expect(api.cancel).toHaveBeenCalledWith(ID, "Mauvais service."));
  });

  it("says what was done, its evidence and its log", async () => {
    api.of.mockResolvedValue([
      plan({
        status: "succeeded",
        started_at: ago(3),
        steps: [
          step({
            status: "succeeded",
            executor: "webhook",
            endpoint_name: "Ops runbooks",
            evidence: {
              request: { url: "https://ops.acme.example/leka", signed_at: 1_791_435_490 },
              response: { status: 200, duration_ms: 120 },
              outcome: { ref: "run-42" },
            },
          }),
        ],
        events: [
          { id: "e1", step_id: null, kind: "planned", actor: "person", by: ME, at: ago(3), detail: {} },
          { id: "e2", step_id: "s1", kind: "step_succeeded", actor: "system", by: null, at: ago(2), detail: {} },
          { id: "e3", step_id: null, kind: "succeeded", actor: "system", by: null, at: ago(2), detail: {} },
        ],
      }),
    ]);
    show(intention({ status: "verifying" }));
    expect(await screen.findByTestId("plan")).toHaveTextContent(
      "Toutes les actions sont exécutées. LEKA vérifie maintenant le résultat.",
    );
    const evidence = screen.getByTestId("step-evidence");
    expect(evidence).toHaveTextContent("Envoyé à https://ops.acme.example/leka");
    expect(evidence).toHaveTextContent("Réponse 200 en 120 ms");
    expect(evidence).toHaveTextContent("Référence : run-42");
    const journal = screen.getByTestId("plan-journal");
    expect(within(journal).getAllByRole("listitem").map((item) => item.dataset.kind)).toEqual([
      "succeeded",
      "step_succeeded",
      "planned",
    ]);
    expect(journal).toHaveTextContent("Plan préparé");
    expect(journal).toHaveTextContent("par vous");
    expect(journal).toHaveTextContent("par LEKA");
  });

  it("says what failed, and retries what did not succeed", async () => {
    const user = userEvent.setup();
    api.of.mockResolvedValue([
      plan({
        status: "failed",
        error: "http_500",
        steps: [step({ status: "failed", executor: "webhook", error: "http_500" })],
      }),
    ]);
    show(intention({ status: "failed" }));
    expect(await screen.findByTestId("plan-step")).toHaveTextContent("Le système a répondu 500");
    await user.click(screen.getByTestId("plan-retry"));
    await waitFor(() => expect(api.plan).toHaveBeenCalledWith(ID));
  });

  it("lets anyone else follow it — and never runs a link that is not http(s)", async () => {
    permissions.value = ["intention:read"];
    api.of.mockResolvedValue([
      plan({
        status: "running",
        steps: [
          step({
            status: "succeeded",
            evidence: { reported: { note: "Fait.", link: "javascript:alert(1)" } },
          }),
        ],
      }),
    ]);
    show(intention({ status: "executing" }));
    expect(await screen.findByTestId("plan")).toHaveTextContent(
      "Seules les personnes qui peuvent valider lancent ou interrompent l'exécution.",
    );
    expect(screen.queryByTestId("plan-cancel")).not.toBeInTheDocument();
    expect(screen.getByTestId("step-evidence")).toHaveTextContent("Confirmé : « Fait. »");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
