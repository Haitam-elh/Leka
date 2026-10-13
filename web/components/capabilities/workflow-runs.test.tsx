/**
 * A workflow (LEKA-397) on its capability's sheet.
 *
 * What these protect: its steps in order, each with what it uses, what it
 * runs after, its condition in words, its attempts, whether its failure stops
 * the rest; run for an intention chosen — LEKA's own steps read one — with
 * what it takes; its runs, a failed one said at which step and retried from
 * there; one opened, each step's state and why it was skipped.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CapabilityDetail } from "@/lib/capabilities";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { Workflow, WorkflowRun, WorkflowRunDetail } from "@/lib/workflows";

const api = vi.hoisted(() => ({
  one: vi.fn(),
  runs: vi.fn(),
  run: vi.fn(),
  start: vi.fn(),
  cancel: vi.fn(),
  retry: vi.fn(),
}));
const asked = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/workflows", async (original) => ({
  ...(await original<typeof import("@/lib/workflows")>()),
  workflows: api,
}));
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  intentions: asked,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { WorkflowPanel } = await import("@/components/capabilities/workflow-runs");

const CAPABILITY = {
  key: "incident-review",
  title: "Revue d'incident",
  kind: "workflow",
  available: true,
  inputs: [],
} as unknown as CapabilityDetail;

const REVIEW: Workflow = {
  key: "incident-review",
  title: "Revue d'incident",
  summary: "Use when an incident must be reviewed end to end.",
  category: "operations",
  version: "1.0.0",
  lifecycle: "active",
  inputs: [],
  available: true,
  reasons: [],
  notes: [],
  steps: [
    {
      id: "incidents",
      title: "Ce qui s'est passé",
      uses: "incidents",
      uses_title: "Incidents",
      uses_kind: "rules",
      after: [],
      when: null,
      given: {},
      attempts: 2,
      on_failure: "stop",
    },
    {
      id: "changes",
      title: "Ce qui a changé avant",
      uses: "changes",
      uses_title: "Changes",
      uses_kind: "rules",
      after: ["incidents"],
      when: { any: [{ step: "incidents", found: "incident.no_cause" }, { step: "incidents", status: ["failed"] }] },
      given: {},
      attempts: 1,
      on_failure: "continue",
    },
  ],
};

function run(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: "w1",
    key: "incident-review",
    title: "Revue d'incident",
    version: "1.0.0",
    status: "failed",
    inputs: {},
    requested_by: "me",
    mine: true,
    intention_id: "i1",
    error: "step_failed",
    failed_step: "incidents",
    retries: 0,
    retryable: true,
    queued_at: "2026-10-09T10:00:00Z",
    started_at: "2026-10-09T10:00:01Z",
    finished_at: "2026-10-09T10:01:00Z",
    ...overrides,
  };
}

const DETAIL: WorkflowRunDetail = {
  ...run(),
  steps: [
    {
      step: "incidents",
      position: 0,
      uses: "incidents",
      status: "failed",
      attempts: 2,
      reason: "TimeoutError",
      output: {},
      started_at: null,
      finished_at: null,
    },
    {
      step: "changes",
      position: 1,
      uses: "changes",
      status: "not_reached",
      attempts: 0,
      reason: "stopped",
      output: {},
      started_at: null,
      finished_at: null,
    },
  ],
  events: [],
};

function show(intentionId?: string) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <WorkflowPanel capability={CAPABILITY} intentionId={intentionId} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.one.mockResolvedValue(REVIEW);
  api.runs.mockResolvedValue([run()]);
  api.run.mockResolvedValue(DETAIL);
  api.start.mockResolvedValue(run({ status: "queued" }));
  api.retry.mockResolvedValue(run({ status: "queued", retries: 1 }));
  asked.list.mockResolvedValue({ data: [{ id: "i1", title: "Pourquoi Billing API est lente ?" }], next_cursor: null });
});

describe("a workflow", () => {
  it("says its steps in order, their conditions in words", async () => {
    show();
    const steps = await screen.findByTestId("workflow-steps");
    expect(steps).toHaveTextContent("1. Ce qui s'est passé · Incidents");
    expect(steps).toHaveTextContent("2 essais · son échec arrête le workflow");
    expect(steps).toHaveTextContent(
      "après incidents · si « incidents » a trouvé incident.no_cause ou si « incidents » est en échec · son échec ne l'arrête pas",
    );
  });

  it("runs for an intention chosen", async () => {
    const user = userEvent.setup();
    show();
    const form = await screen.findByTestId("workflow-run-form");
    await waitFor(() => expect(within(form).getAllByRole("option")).toHaveLength(2));
    await user.selectOptions(within(form).getByLabelText("Intention sur laquelle il travaille"), "i1");
    await user.click(within(form).getByRole("button", { name: "Lancer" }));
    await waitFor(() =>
      expect(api.start).toHaveBeenCalledWith({ key: "incident-review", inputs: {}, intention_id: "i1" }),
    );
  });

  it("runs for the intention it is offered on, without asking which", async () => {
    show("i9");
    const form = await screen.findByTestId("workflow-run-form");
    expect(within(form).queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByTestId("workflow-runs")).not.toBeInTheDocument();
  });

  it("says where a run failed, opens it step by step, retries it", async () => {
    const user = userEvent.setup();
    show();
    const [failed] = await screen.findAllByTestId("workflow-run");
    expect(failed).toHaveTextContent("Échoué · à l'étape « incidents »");
    await user.click(within(failed).getByRole("button", { expanded: false }));
    const detail = await screen.findByTestId("workflow-run-detail");
    expect(detail).toHaveTextContent("en échec");
    expect(detail).toHaveTextContent("2 essais");
    expect(detail).toHaveTextContent("non atteinte");
    expect(detail).toHaveTextContent("le workflow s'est arrêté avant");
    await user.click(within(failed).getByRole("button", { name: "Reprendre" }));
    await waitFor(() => expect(api.retry).toHaveBeenCalledWith("w1"));
  });
});
