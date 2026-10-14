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
 *
 * Its outcome (LEKA-392): what is expected said before it runs, changed by
 * who may approve — removed, added, nothing incomplete sent; once it ran,
 * each expectation as it was read — met, not met and why, unknown, awaiting
 * a person — a person's word only with what shows it, read again now,
 * concluded only saying why; achieved, the company's context rebuilt and
 * where to see it, the stages final; not achieved, said; its whole story
 * one click away.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { Plan, PlanStep } from "@/lib/actions";
import type { Verification } from "@/lib/outcomes";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { makeQueryClient } from "@/lib/query";
import { sampleJourney } from "@/lib/intentions/journey-sample";

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
const outcomesApi = vi.hoisted(() => ({
  expect: vi.fn(),
  verifications: vi.fn(),
  check: vi.fn(),
  report: vi.fn(),
  conclude: vi.fn(),
  timeline: vi.fn(),
}));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/actions", async (original) => ({
  ...(await original<typeof import("@/lib/actions")>()),
  plans: api,
}));
vi.mock("@/lib/outcomes", async (original) => ({
  ...(await original<typeof import("@/lib/outcomes")>()),
  outcomes: outcomesApi,
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
  const status = overrides.status ?? "approved";
  return {
    id: ID,
    title: "Redémarre Billing API en production",
    text: "Redémarre Billing API en production",
    kind: "change",
    scope: {},
    status,
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
    version: 1,
    journey: sampleJourney(status),
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

/** What the API allows with a plan in its plainest case (plan_controls). */
function controlsOf(status: Plan["status"], steps: PlanStep[]): Plan["controls"] {
  if (status === "planned") return ["start", "schedule", "cancel"];
  if (status === "scheduled") return ["unschedule"];
  if (status === "running") {
    return steps.some((s) => s.status === "awaiting") ? ["stop", "confirm_step"] : ["stop"];
  }
  return status === "succeeded" ? [] : ["plan"];
}

function plan(overrides: Partial<Plan> = {}): Plan {
  const status = overrides.status ?? "planned";
  return {
    id: "p1",
    intention_id: ID,
    decision_id: "d1",
    number: 1,
    revision: 1,
    status,
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
    expectations: [],
    controls: controlsOf(status, overrides.steps ?? [step()]),
    ...overrides,
  };
}

const HEALTHY = {
  id: `healthy:${BILLING}`,
  kind: "healthy" as const,
  target: { id: BILLING, name: "Billing API", type: "service" },
  name: null,
  comparator: null,
  value: null,
  source: "model" as const,
  said: null,
  incidents: [],
};
const CHECKOUT = {
  ...HEALTHY,
  id: "confirmed:1",
  kind: "confirmed" as const,
  target: null,
  said: "Le paiement passe de bout en bout",
};

function verification(overrides: Partial<Verification> = {}): Verification {
  return {
    id: "v1",
    intention_id: ID,
    plan_id: "p1",
    status: "verifying",
    expectations: [HEALTHY, CHECKOUT],
    results: [],
    observe_after: ago(-5),
    deadline: ago(-24 * 60),
    observed_at: null,
    concluded_at: null,
    concluded_by: null,
    context_update: {},
    detail: {},
    created_at: ago(5),
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
  outcomesApi.verifications.mockResolvedValue([]);
  outcomesApi.expect.mockResolvedValue([]);
  outcomesApi.check.mockResolvedValue(verification());
  outcomesApi.report.mockResolvedValue(verification());
  outcomesApi.conclude.mockResolvedValue(verification({ status: "failed" }));
});

describe("an intention's actions", () => {
  it("says a question calls for no action — not « once the decision is approved »", async () => {
    show(
      intention({
        status: "completed",
        goal: "find_change",
        understanding: {
          goal: { code: "find_change" },
          actions: [],
        } as unknown as IntentionDetail["understanding"],
      }),
    );
    const said = await screen.findByTestId("plan-question");
    expect(said).toHaveTextContent("Une question n'appelle aucune action.");
    expect(said).toHaveTextContent("LEKA propose, une personne décide");
    expect(screen.queryByText(/une fois la décision validée/)).not.toBeInTheDocument();
  });

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

  it("an answer that did not say it was done asks a person to check", async () => {
    api.of.mockResolvedValue([
      plan({
        status: "running",
        started_at: ago(3),
        steps: [
          step({
            status: "awaiting",
            executor: "webhook",
            endpoint_name: "Ops runbooks",
            evidence: {
              request: { url: "https://ops.acme.example/leka", signed_at: 1_791_435_490 },
              response: { status: 200, duration_ms: 90 },
              outcome: { ref: null, reason: "unconfirmed" },
            },
          }),
        ],
      }),
    ]);
    show(intention({ status: "executing" }));
    expect(await screen.findByTestId("step-evidence")).toHaveTextContent(
      "Le système a répondu sans dire si l'action est faite : vérifiez, puis confirmez",
    );
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
    // Run is not done: to be verified, said so (LEKA-443).
    expect(screen.getByTestId("plan-status")).toHaveTextContent("Exécuté · à vérifier");
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

  it("offers only what the API allows with it — never a retry it would refuse", async () => {
    // Failed, but the intention asked again since: no plan to retry here.
    api.of.mockResolvedValue([
      plan({
        status: "failed",
        error: "http_500",
        steps: [step({ status: "failed", executor: "webhook", error: "http_500" })],
        controls: [],
      }),
    ]);
    show(intention({ status: "failed" }));
    expect(await screen.findByTestId("plan-step")).toHaveTextContent("Le système a répondu 500");
    expect(screen.queryByTestId("plan-retry")).not.toBeInTheDocument();
    expect(screen.queryByTestId("plan-controls")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("link", { name: "Voir" })).not.toBeInTheDocument();
  });
});

describe("what came of it", () => {
  it("says what is expected before it runs, and who may approve changes it", async () => {
    const user = userEvent.setup();
    api.of.mockResolvedValue([plan({ expectations: [HEALTHY] })]);
    show();
    const expected = await screen.findByTestId("expectations");
    expect(expected).toHaveTextContent(
      "Billing API en bonne santé : aucun incident ouvert, en service",
    );

    await user.click(screen.getByTestId("expectations-edit"));
    await user.click(within(expected).getByTestId("expectation-remove"));
    expect(expected).toHaveTextContent("Rien d'attendu");
    // Incomplete: nothing added.
    await user.click(screen.getByTestId("expectation-add-button"));
    expect(notices.error).toHaveBeenCalledWith({
      title: "Complétez ce résultat attendu : tout ce qu'il faut pour le vérifier.",
    });
    await user.type(screen.getByTestId("expectation-metric"), "p95_ms");
    await user.type(screen.getByTestId("expectation-value"), "300");
    await user.click(screen.getByTestId("expectation-add-button"));
    expect(expected).toHaveTextContent("p95_ms ≤ 300, selon le système qui a agi");
    await user.selectOptions(screen.getByTestId("expectation-kind"), "confirmed");
    await user.type(screen.getByTestId("expectation-said"), "Le paiement passe");
    await user.click(screen.getByTestId("expectation-add-button"));
    await user.click(screen.getByTestId("expectations-save"));
    await waitFor(() =>
      expect(outcomesApi.expect).toHaveBeenCalledWith(ID, [
        {
          id: "metric:system:p95_ms",
          kind: "metric",
          target: null,
          name: "p95_ms",
          comparator: "lte",
          value: 300,
          source: "system",
          said: null,
          incidents: [],
        },
        {
          id: "confirmed:1",
          kind: "confirmed",
          target: null,
          name: null,
          comparator: null,
          value: null,
          source: "model",
          said: "Le paiement passe",
          incidents: [],
        },
      ]),
    );
  });

  it("is fixed once it runs", async () => {
    api.of.mockResolvedValue([
      plan({ status: "running", expectations: [HEALTHY], steps: [step({ status: "awaiting" })] }),
    ]);
    show(intention({ status: "executing" }));
    expect(await screen.findByTestId("expectations")).toHaveTextContent(
      "Fixé au lancement de l'exécution.",
    );
    expect(screen.queryByTestId("expectations-edit")).not.toBeInTheDocument();
  });

  it("verifies it: each expectation as read, a person's word, read now, concluded", async () => {
    const user = userEvent.setup();
    api.of.mockResolvedValue([
      plan({ status: "succeeded", expectations: [HEALTHY, CHECKOUT], steps: [step({ status: "succeeded" })] }),
    ]);
    outcomesApi.verifications.mockResolvedValue([
      verification({
        observe_after: ago(1),
        observed_at: ago(1),
        results: [
          { expectation_id: HEALTHY.id, seen: "not_met", value: 1, detail: "incidents", reported: null },
          { expectation_id: CHECKOUT.id, seen: "awaiting", value: null, detail: null, reported: null },
        ],
      }),
    ]);
    show(intention({ status: "verifying" }));
    const card = await screen.findByTestId("verification");
    expect(screen.getByTestId("verification-status")).toHaveTextContent("En vérification");
    expect(card).toHaveTextContent("Relu toutes les 5 minutes jusqu'au");
    expect(within(screen.getByTestId("plan-stages")).getByText("En vérification")).toBeInTheDocument();
    const [healthy, checkout] = within(card).getAllByTestId("verification-result");
    expect(healthy).toHaveAttribute("data-seen", "not_met");
    expect(healthy).toHaveTextContent("1 incident ouvert dessus");
    expect(checkout).toHaveTextContent("Une personne confirme : « Le paiement passe de bout en bout »");
    expect(within(checkout).getByTestId("verification-seen")).toHaveTextContent("À confirmer");

    await user.click(within(checkout).getByTestId("expectation-report"));
    await user.click(within(checkout).getByTestId("expectation-met"));
    expect(outcomesApi.report).not.toHaveBeenCalled();
    expect(notices.error).toHaveBeenCalledWith({ title: "Dites ce qui le montre." });
    await user.type(within(checkout).getByTestId("expectation-report-note"), "Commande payée.");
    await user.type(
      within(checkout).getByTestId("expectation-report-link"),
      "https://shop.acme.example/orders/42",
    );
    await user.click(within(checkout).getByTestId("expectation-met"));
    await waitFor(() =>
      expect(outcomesApi.report).toHaveBeenCalledWith(ID, "confirmed:1", {
        met: true,
        note: "Commande payée.",
        link: "https://shop.acme.example/orders/42",
      }),
    );

    await user.click(screen.getByTestId("verification-check"));
    await waitFor(() => expect(outcomesApi.check).toHaveBeenCalledWith(ID));

    await user.click(screen.getByTestId("verification-conclude"));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Conclure" }));
    expect(outcomesApi.conclude).not.toHaveBeenCalled();
    expect(notices.error).toHaveBeenCalledWith({ title: "Dites pourquoi." });
    await user.click(screen.getByTestId("verification-conclude"));
    dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Restauré à la main.");
    await user.click(within(dialog).getByRole("button", { name: "Conclure" }));
    await waitFor(() => expect(outcomesApi.conclude).toHaveBeenCalledWith(ID, "Restauré à la main."));
  });

  it("says what came of it, the context rebuilt, and its whole story one click away", async () => {
    api.of.mockResolvedValue([
      plan({ status: "succeeded", expectations: [HEALTHY], steps: [step({ status: "succeeded" })] }),
    ]);
    outcomesApi.verifications.mockResolvedValue([
      verification({
        status: "succeeded",
        expectations: [HEALTHY],
        concluded_at: ago(1),
        results: [
          { expectation_id: HEALTHY.id, seen: "met", value: "active", detail: "state", reported: null },
        ],
        context_update: { operation_id: "o1", kind: "rebuild", at: ago(1) },
      }),
    ]);
    show(intention({ status: "completed" }));
    const card = await screen.findByTestId("verification");
    expect(card).toHaveTextContent("Ce qui était attendu est là : l'intention est terminée.");
    expect(card).toHaveTextContent("État : active");
    expect(screen.getByTestId("verification-context")).toHaveTextContent(
      "Contexte de l'entreprise mis à jour",
    );
    expect(within(screen.getByTestId("verification-context")).getByRole("link")).toHaveAttribute(
      "href",
      "/activity",
    );
    expect(screen.queryByTestId("verification-controls")).not.toBeInTheDocument();
    const stages = within(screen.getByTestId("plan-stages")).getAllByRole("listitem");
    expect(stages[3]).toHaveTextContent("Finalisation");
    expect(screen.getByTestId("impact-history")).toHaveAttribute("href", `/intentions/${ID}/history`);
  });

  it("says what did not come, and who concluded it, why", async () => {
    api.of.mockResolvedValue([plan({ status: "succeeded", steps: [step({ status: "succeeded" })] })]);
    outcomesApi.verifications.mockResolvedValue([
      verification({
        status: "partial",
        concluded_by: ME,
        detail: { note: "Restauré à la main." },
        results: [
          { expectation_id: HEALTHY.id, seen: "unknown", value: null, detail: "not_seen_since", reported: null },
          {
            expectation_id: CHECKOUT.id,
            seen: "met",
            value: null,
            detail: null,
            reported: { by: ME, note: "Commande payée.", link: "javascript:alert(1)" },
          },
        ],
      }),
    ]);
    show(intention({ status: "failed" }));
    const card = await screen.findByTestId("verification");
    expect(screen.getByTestId("verification-status")).toHaveTextContent("Atteint en partie");
    expect(card).toHaveTextContent("Une partie seulement de ce qui était attendu est là");
    expect(card).toHaveTextContent("Pas encore relu depuis l'exécution");
    expect(screen.getByTestId("verification-reported")).toHaveTextContent(
      "Atteint selon vous : « Commande payée. »",
    );
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByTestId("verification-concluded")).toHaveTextContent(
      "Conclu par vous : « Restauré à la main. »",
    );
    expect(within(screen.getByTestId("plan-stages")).getByText("Atteint en partie")).toHaveClass(
      "text-state-danger",
    );
  });

  it("lets anyone else follow it", async () => {
    permissions.value = ["intention:read"];
    api.of.mockResolvedValue([plan({ status: "succeeded", steps: [step({ status: "succeeded" })] })]);
    outcomesApi.verifications.mockResolvedValue([verification()]);
    show(intention({ status: "verifying" }));
    expect(await screen.findByTestId("verification")).toHaveTextContent(
      "Seules les personnes qui peuvent valider confirment un résultat ou concluent.",
    );
    expect(screen.queryByTestId("expectation-report")).not.toBeInTheDocument();
    expect(screen.queryByTestId("verification-controls")).not.toBeInTheDocument();
  });
});
