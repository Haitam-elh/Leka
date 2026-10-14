/**
 * The agents at work on an intention (2026-10-14: « ça charge, ça ne tourne
 * pas ; il faut rafraîchir pour voir qu'il a fini »).
 *
 * What these protect: while LEKA works on the intention, its agents are read
 * again — even when none had started at first read — and one that finishes
 * is seen finished without a reload; one at work says so with a spinner that
 * turns.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRun } from "@/lib/agent-runs";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const runs = vi.hoisted(() => ({ forIntention: vi.fn() }));
vi.mock("@/lib/agent-runs", async (original) => ({
  ...(await original<typeof import("@/lib/agent-runs")>()),
  agentRuns: runs,
}));

const { AgentWork } = await import("@/components/intentions/agent-work");

function run(status: AgentRun["status"]): AgentRun {
  return {
    id: "r1",
    key: "code-review",
    title: "Revue de code",
    version: "1.2.0",
    status,
    inputs: { changement: "la dernière PR de acme/leka" },
    requested_by: null,
    mine: true,
    intention_id: "i1",
    context_id: null,
    context_version: null,
    format: "markdown",
    pending: [],
    deliverables: [],
    error: null,
    reasons: [],
    provider: null,
    model: null,
    model_version: null,
    tool_calls: 0,
    queued_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
  };
}

function show(live: boolean) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <AgentWork intentionId="i1" live={live} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("the agents at work on an intention", () => {
  it("is read again while LEKA works, and seen finished without a reload", async () => {
    runs.forIntention
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([run("running")])
      .mockResolvedValue([run("succeeded")]);
    show(true);

    // Not started yet at first read: read again, it appears, at work.
    await vi.advanceTimersByTimeAsync(3_000);
    const working = await screen.findByTestId("agent-work-run");
    expect(working).toHaveTextContent("Revue de code");
    // Its spinner turns.
    expect(working.querySelector("svg")?.getAttribute("class")).toContain("animate-spin");

    await vi.advanceTimersByTimeAsync(3_000);
    expect(await screen.findByText(/a terminé/)).toBeInTheDocument();
    expect(screen.getByTestId("agent-work-run").querySelector("svg")?.getAttribute("class")).not.toContain(
      "animate-spin",
    );
  });

  it("is not read again when nothing works on it", async () => {
    runs.forIntention.mockResolvedValue([]);
    show(false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(runs.forIntention).toHaveBeenCalledTimes(1);
  });
});
