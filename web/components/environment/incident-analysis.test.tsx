/**
 * An incident's "Analyse de LEKA" (LEKA-341): the incident as the company
 * model knows it, drawn with the intelligence components.
 *
 * What these protect: the probable cause, how sure and why, its evidence
 * one click away; what the sources say; what it reaches and the risk read
 * from its severity; no recommendation made up — the slot says why it is
 * empty; a failed read says so, shows nothing else, and retries.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { IncidentDetail } from "@/lib/incidents";
import { makeQueryClient } from "@/lib/query";

const api = { detail: vi.fn() };
vi.mock("@/lib/incidents", async (original) => ({
  ...(await original<typeof import("@/lib/incidents")>()),
  incidents: api,
}));

// The workspace's sources, which name the incident's records.
const sourcesApi = { list: vi.fn() };
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  sources: sourcesApi,
}));

const { IncidentAnalysis } = await import("@/components/environment/incident-analysis");

const SERVICE = {
  id: "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41",
  type: "service" as const,
  key: "service:payment-api",
  name: "payment-api",
  lifecycle: "active" as const,
};
const DEPLOY = {
  id: "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41",
  type: "deployment" as const,
  key: "deploy-1",
  name: "payment-api v2.8.4",
  lifecycle: "active" as const,
};

const DETAIL: IncidentDetail = {
  id: "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41",
  key: "OPS-1841",
  name: "payment-api p99 latency above 2s",
  lifecycle: "active",
  url: null,
  tools: ["jira"],
  state: "closed",
  priority: null,
  severity: "sev2",
  urgency: null,
  opened_at: "2026-10-03T10:00:00Z",
  acknowledged_at: null,
  resolved_at: "2026-10-03T14:00:00Z",
  time_to_acknowledge_minutes: null,
  duration_minutes: 240,
  affects: [SERVICE],
  commander: null,
  assignees: [],
  causes: [DEPLOY],
  attributes: {},
  provenance: { sources: [{ source_id: "s1", key: "OPS-1841", kind: "key" }] },
  timeline: [{ at: "2026-10-03T10:00:00Z", step: "opened", state: null, origin: "source" }],
  affected: [{ entity: SERVICE, origin: "stated", rule: "stated", confidence: 1 }],
  people: [],
  suspected_causes: [{ entity: DEPLOY, origin: "stated", rule: "stated", confidence: 0.83 }],
  changed_before: [
    {
      entity: DEPLOY,
      kind: "deployment",
      at: "2026-10-03T09:00:00Z",
      state: "succeeded",
      environment: "production",
      via: SERVICE,
    },
  ],
  impact: {
    affected: [SERVICE],
    dependents: [],
    applications: [],
    capabilities: [],
    processes: [],
  },
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <IncidentAnalysis id={DETAIL.id} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  sourcesApi.list.mockResolvedValue({
    data: [{ id: "s1", type: "jira", display_name: "OPS board" }],
    next_cursor: null,
  });
});

describe("an incident's analysis", () => {
  it("says the probable cause, how sure and why, what is known, what it reaches", async () => {
    api.detail.mockResolvedValue(DETAIL);
    const user = userEvent.setup();
    show();

    const cause = await screen.findByTestId("probable-cause");
    expect(cause).toHaveTextContent("Hypothèse 1");
    expect(cause).toHaveTextContent("payment-api v2.8.4");
    expect(cause).toHaveTextContent("Confiance moyenne · 83 % · déclaré par la source");
    await user.click(within(cause).getByRole("button", { name: /2 preuve/ }));
    expect(within(cause).getByTestId("evidence")).toHaveTextContent(
      "Déploiement · payment-api v2.8.4",
    );

    expect(screen.getByTestId("findings")).toHaveTextContent(
      "payment-api p99 latency above 2s : clos, sev2.",
    );
    expect(screen.getByTestId("impact")).toHaveTextContent("Risque moyen");
    expect(screen.getByTestId("intelligence-proposal")).toHaveTextContent(
      "LEKA ne propose pas encore de recommandation",
    );
    expect(screen.queryByTestId("analysis-state")).not.toBeInTheDocument();
    expect(api.detail).toHaveBeenCalledWith(DETAIL.id);
  });

  it("says when it could not read, shows nothing else, and retries", async () => {
    // Not retried by the query: the alert shows at once.
    api.detail.mockRejectedValueOnce(new ApiError(404, "/knowledge/incidents/x", "Not built."));
    api.detail.mockResolvedValue(DETAIL);
    const user = userEvent.setup();
    show();

    const failed = await screen.findByRole("alert");
    expect(failed).toHaveTextContent("L'analyse a échoué");
    expect(screen.queryByTestId("probable-cause")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByTestId("probable-cause")).toBeInTheDocument();
  });
});
