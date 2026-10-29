/**
 * What LEKA is doing on an intention, now (LEKA-465).
 *
 * What these protect: said at once — the analysis under way, its request
 * recorded and LEKA reading since when; agents at work, each with the steps
 * its run really went through, never a percentage; a failure said, its
 * reason, never a spinner left turning; nothing at a decision; told to
 * whoever does not see it change (a live region); one may leave the page.
 */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";

const state = vi.hoisted(() => ({
  runs: [] as unknown[],
  details: {} as Record<string, unknown>,
  analysis: null as unknown,
}));

vi.mock("@/lib/agent-runs-queries", () => ({
  useIntentionRuns: () => ({ data: state.runs }),
  useAgentRun: (id: string) => ({ data: state.details[id] }),
}));
vi.mock("@/lib/intentions/queries", () => ({
  useIntentionAnalysis: () => ({ data: state.analysis }),
}));

const { Working } = await import("@/components/intentions/working");

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function intention(journey: Partial<IntentionDetail["journey"]>): IntentionDetail {
  return {
    id: "i1",
    created_at: ago(5),
    journey: { state: "analysing", by: "leka", since: ago(3), controls: [], ...journey },
  } as unknown as IntentionDetail;
}

function run(id: string, status: string, error: string | null = null) {
  return { id, key: "application-architecture", title: "Architecte applicatif", status, error, queued_at: ago(4) };
}

function events(...kinds: string[]) {
  return { events: kinds.map((kind, seq) => ({ seq, kind, at: ago(4 - seq * 0.5), detail: {} })) };
}

function show(of: IntentionDetail) {
  return render(
    <LocaleProvider>
      <Working intention={of} />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  state.runs = [];
  state.details = {};
  state.analysis = null;
});

describe("what LEKA is doing, now", () => {
  it("the analysis under way: its request recorded, LEKA reading since when", () => {
    state.analysis = { status: "running", started_at: ago(2) };
    show(intention({ state: "analysing" }));
    const working = screen.getByTestId("working");
    expect(working).toHaveAttribute("aria-live", "polite");
    expect(working).toHaveAttribute("data-phase", "analysis");
    expect(within(working).getByRole("heading")).toHaveTextContent("Analyse en cours");
    const steps = within(working).getAllByTestId("working-step");
    expect(steps[0]).toHaveTextContent("Demande enregistrée");
    expect(steps[0]).toHaveAttribute("data-done", "true");
    expect(steps[1]).toHaveTextContent(/LEKA lit vos sources et analyse\s*· il y a 2 min/);
    expect(working).toHaveTextContent("Vous pouvez quitter cette page");
  });

  it("agents at work: the steps their runs really went through — never a percentage", () => {
    state.runs = [run("r1", "running")];
    state.details = { r1: events("queued", "started", "context", "tool", "tool") };
    show(intention({ state: "action_running" }));
    const working = screen.getByTestId("working");
    expect(within(working).getByRole("heading")).toHaveTextContent("Vos agents travaillent");
    const [agent] = within(working).getAllByTestId("working-run");
    const steps = within(agent).getAllByTestId("working-step").map((s) => s.textContent);
    expect(steps.map((s) => s?.split("·")[0]?.trim())).toEqual([
      "En file d'attente",
      "Démarré",
      "Contexte de votre environnement lu",
      "2 lectures de vos sources",
    ]);
    // The one at work: the last reached, until the run ends.
    expect(within(agent).getAllByTestId("working-step").at(-1)).not.toHaveAttribute("data-done");
    expect(working.textContent).not.toMatch(/%/);
  });

  it("a failure said, its reason — no spinner left turning, the way on below", () => {
    state.runs = [run("r1", "failed", "timeout")];
    state.details = { r1: events("queued", "started", "failed") };
    show(intention({ state: "action_failed", by: "asker" }));
    const working = screen.getByTestId("working");
    expect(working).toHaveAttribute("data-phase", "failed");
    expect(within(working).getByRole("heading")).toHaveTextContent("Le traitement n'a pas abouti");
    expect(working).toHaveTextContent("Échec : trop longue, relancez-la");
    expect(working).not.toHaveTextContent("Vous pouvez quitter cette page");
    expect(working.querySelector(".animate-spin")).toBeNull();
  });

  it("nothing at a decision: the page says what to decide", () => {
    show(intention({ state: "decision_required", by: "asker" }));
    expect(screen.queryByTestId("working")).toBeNull();
  });
});
