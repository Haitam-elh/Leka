/**
 * The Digital Twin, drawn (LEKA-442) — the ticket's scenarios.
 *
 * What these protect: the six states each defined in the legend; how fresh,
 * never « temps réel », a late read said; a normal thing operational with
 * what measured it; a confirmed incident, a suspected anomaly, an unknown
 * thing, a stale source, a failing one — each in its words and how it is
 * known, the worst first, each the way to an intention about it; each
 * source in its state, each part covered or not; on Free the limit and the
 * plan that lifts it, never an alert; on a paid plan the alerts open, how
 * sure, since when, the way to analyse each, those ended with what verified
 * them; e-mail not included, said.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AlertsCard,
  FreshnessLine,
  SourcesCoverage,
  TwinCounts,
  TwinLegend,
  TwinList,
} from "@/components/environment/twin";
import type { EnvironmentNode } from "@/lib/environment";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Credits } from "@/lib/billing";
import { makeQueryClient } from "@/lib/query";
import type { Monitoring, TwinSource, TwinState } from "@/lib/twin";

// The month's credits (LEKA-463), as GET /billing/credits says them.
const credits = vi.hoisted(() => ({ value: undefined as Credits | undefined }));
vi.mock("@/lib/billing-queries", () => ({ useCredits: () => ({ data: credits.value }) }));
// Who reads: an admin, who may take an alert in hand.
const people = vi.hoisted(() => ({ permissions: ["source:read", "source:manage"] }));
vi.mock("@/components/shell/shell-provider", async (original) => ({
  ...(await original<typeof import("@/components/shell/shell-provider")>()),
  usePermissions: () => people.permissions,
  useCurrentUser: () => ({ id: "me" }),
}));
const acknowledge = vi.hoisted(() => vi.fn());
vi.mock("@/lib/twin", async (original) => {
  const real = await original<typeof import("@/lib/twin")>();
  return { ...real, monitoring: { ...real.monitoring, acknowledge } };
});

afterEach(() => {
  credits.value = undefined;
  people.permissions = ["source:read", "source:manage"];
  acknowledge.mockReset();
});

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

const read = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function twin(more: Partial<TwinState>): TwinState {
  return {
    state: "unknown",
    basis: "none",
    reason: "no_signal",
    observed_at: read(7),
    signal: [],
    fresh: true,
    was: null,
    certainty: "confirmed",
    incident: null,
    ...more,
  };
}

function node(name: string, state: Partial<TwinState>): EnvironmentNode {
  return {
    id: name,
    type: "service",
    layer: "services",
    name,
    status: null,
    entity_id: `00000000-0000-0000-0000-${String(name.length).padStart(12, "0")}`,
    key: name,
    detail: null,
    count: 1,
    environment: null,
    team: null,
    twin: twin(state),
  };
}

const NODES = [
  node("normal", { state: "operational", basis: "measured", reason: "monitored_quiet", signal: ["acme-eu"] }),
  node("confirmed", {
    state: "unavailable",
    basis: "measured",
    reason: "incident_open",
    incident: { id: "i", key: "OPS-9", name: "down", severity: "sev1" },
  }),
  node("suspected", { state: "degraded", basis: "deduced", reason: "deduced_health", certainty: "suspected" }),
  node("silent", { state: "unknown" }),
  node("old", {
    state: "stale",
    basis: "measured",
    reason: "sources_stale",
    fresh: false,
    was: "operational",
    certainty: "unverified",
  }),
];

function source(name: string, state: TwinSource["state"], category = "code"): TwinSource {
  return {
    id: name,
    kind: "github",
    name,
    category,
    state,
    last_synced_at: state === "never" ? null : read(30),
    error: state === "error" ? "401 Unauthorized" : null,
    webhooks: false,
  };
}

function watch(plan: string, alerts: Monitoring["entitlement"]["alerts"], open: Monitoring["open"] = []): Monitoring {
  return {
    entitlement: {
      plan,
      proactive: alerts.length > 0,
      alerts,
      contractual: false,
      provisional: true,
      alerts_from: "starter",
      email_from: "growth",
    },
    open,
    ended: [],
  };
}

function alert(more: Partial<Monitoring["open"][number]>): Monitoring["open"][number] {
  return {
    id: crypto.randomUUID(),
    subject_type: "entity",
    subject_id: "s",
    subject_name: "payment-api",
    kind: "degraded",
    severity: "medium",
    certainty: "confirmed",
    status: "open",
    opened_at: read(60),
    last_seen_at: read(5),
    resolved_at: null,
    detail: { incident: { key: "OPS-1841" } },
    resolution: null,
    notified: {},
    ...more,
  };
}

describe("the Digital Twin", () => {
  it("defines its six states, never « sain » for what nothing says", () => {
    show(<TwinLegend />);
    const legend = screen.getByTestId("twin-legend");
    expect(within(legend).getAllByRole("listitem")).toHaveLength(6);
    expect(legend).toHaveTextContent("Inconnu : Une source pourrait le dire et ne dit rien : inconnu ne veut pas dire sain.");
    expect(legend).toHaveTextContent("Non couvert");
    expect(legend).toHaveTextContent("Données obsolètes");
  });

  it("says how fresh it is — never in real time — and a late read", () => {
    show(<FreshnessLine freshness={{ last_read_at: read(7), every_minutes: 60, late: false, webhooks: false }} />);
    expect(screen.getByTestId("twin-freshness")).toHaveTextContent(
      "Lu il y a 7 minSources lues toutes les 60 min — pas en temps réel",
    );
    show(<FreshnessLine freshness={{ last_read_at: read(200), every_minutes: 60, late: true, webhooks: false }} />);
    expect(screen.getByTestId("twin-late")).toHaveTextContent("En retard : aucune lecture depuis plus de 2 h");
  });

  it("lists every thing the worst first, each state with how it is known", () => {
    show(<TwinList nodes={NODES} />);
    const rows = within(screen.getByTestId("twin-list")).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.querySelector("a")?.textContent)).toEqual([
      "confirmed",
      "suspected",
      "old",
      "silent",
      "normal",
    ]);
    expect(rows[0]).toHaveTextContent("Indisponible");
    expect(rows[0]).toHaveTextContent("incident OPS-9 ouvert · mesuré");
    expect(rows[1]).toHaveTextContent("Dégradé");
    expect(rows[1]).toHaveTextContent("état déduit · déduit de ce qui le fait tourner · soupçonné");
    expect(rows[2]).toHaveTextContent("Données obsolètes");
    expect(rows[2]).toHaveTextContent("non vérifié · était opérationnel");
    expect(rows[3]).toHaveTextContent("Inconnu");
    expect(rows[4]).toHaveTextContent("surveillé, rien à signaler · mesuré · par acme-eu");
    // Each the way to an intention about it.
    expect(within(rows[0]).getByRole("link", { name: /Demander à LEKA/ })).toHaveAttribute(
      "href",
      `/intentions/new?q=${encodeURIComponent("Pourquoi confirmed est indisponible ?")}`,
    );
  });

  it("filters to one state, counted, the way to the list", () => {
    show(<TwinList nodes={NODES} filter="degraded" />);
    expect(within(screen.getByTestId("twin-list")).getAllByRole("row")).toHaveLength(2);
    show(<TwinCounts states={{ unavailable: 1, degraded: 1, stale: 1, unknown: 1, not_covered: 0, operational: 1 }} />);
    const counts = screen.getByTestId("twin-counts");
    expect(within(counts).getAllByRole("listitem")).toHaveLength(6);
    expect(counts).toHaveTextContent("0Non couvert");
  });

  it("says each source in its state and what covers each part", () => {
    show(
      <SourcesCoverage
        coverage={[
          { part: "applications", covered: true, sources: ["acme/backend"] },
          { part: "health", covered: false, sources: [] },
        ]}
        sources={[source("acme/backend", "read"), source("Runbooks", "error", "docs"), source("#platform", "never")]}
      />,
    );
    const parts = within(screen.getByTestId("twin-coverage")).getAllByRole("listitem");
    expect(parts[0]).toHaveTextContent("Applications couvert par acme/backend");
    expect(parts[1]).toHaveTextContent("État des services non couvert : aucune source connectée ne le décrit");
    const sources = within(screen.getByTestId("twin-sources")).getAllByRole("listitem");
    expect(sources.map((row) => row.getAttribute("data-state"))).toEqual(["read", "error", "never"]);
    expect(sources[1]).toHaveTextContent("En échec");
    expect(sources[1]).toHaveTextContent("401 Unauthorized");
    expect(sources[2]).toHaveTextContent("jamais lue");
  });

  it("on Free, says the limit and the plan that lifts it — never an alert", () => {
    show(<AlertsCard monitoring={watch("free", [])} />);
    expect(screen.getByTestId("alerts-limit")).toHaveTextContent(
      "Votre plan Free montre les états, leur fraîcheur et leur couverture. Les alertes proactives sont incluses dès Starter, par e-mail dès Growth.",
    );
    expect(screen.getByRole("link", { name: /Voir les plans/ })).toHaveAttribute("href", "/billing");
    expect(screen.queryByTestId("alert")).not.toBeInTheDocument();
  });

  it("on a paid plan, lists the alerts open, how sure, since when, the way to analyse", () => {
    show(
      <AlertsCard
        monitoring={{
          ...watch("growth", ["in_app", "email"], [
            alert({}),
            alert({ subject_name: "Runbooks", kind: "source_failing", subject_type: "source", detail: {} }),
          ]),
          ended: [
            alert({
              id: "ended",
              status: "resolved",
              resolved_at: read(2),
              resolution: { signal: ["acme-eu"] },
            }),
          ],
        }}
      />,
    );
    const [open] = within(screen.getByTestId("alerts")).getAllByTestId("alert");
    expect(open).toHaveTextContent("payment-api — Dégradé (OPS-1841)");
    expect(open).toHaveTextContent("confirmé · ouverte il y a 1 h");
    expect(within(open).getByRole("link", { name: /Analyser avec LEKA/ })).toHaveAttribute(
      "href",
      `/intentions/new?q=${encodeURIComponent("Pourquoi payment-api est dégradé ?")}`,
    );
    expect(screen.getByText("dans LEKA et par e-mail")).toBeVisible();
    // Ended: resolved by what verified it.
    expect(screen.getByText(/résolue, vérifiée par acme-eu/)).toBeInTheDocument();
  });

  it("an alert taken in hand by who manages: by whom and since when; a member only reads", async () => {
    acknowledge.mockResolvedValue({});
    const user = userEvent.setup();
    const { unmount } = show(<AlertsCard monitoring={watch("starter", ["in_app"], [alert({ id: "a1" })])} />);
    await user.click(screen.getByTestId("alert-take"));
    expect(acknowledge).toHaveBeenCalledWith("a1", expect.anything());
    unmount();
    show(
      <AlertsCard
        monitoring={watch("starter", ["in_app"], [alert({ acknowledged_at: read(5), acknowledged_by: "me" })])}
      />,
    );
    expect(screen.getByTestId("alert")).toHaveTextContent("prise en charge par vous il y a 5 min");
    expect(screen.queryByTestId("alert-take")).not.toBeInTheDocument();
  });

  it("a member reads the alerts and may not take one in hand", () => {
    people.permissions = ["source:read"];
    show(<AlertsCard monitoring={watch("starter", ["in_app"], [alert({})])} />);
    expect(screen.getByTestId("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("alert-take")).not.toBeInTheDocument();
  });

  it("the month's AI capacity on every plan: each threshold passed and when; spent, why and the way to more", () => {
    credits.value = {
      plan: "free",
      percent: 100,
      state: "exhausted",
      enforced: true,
      period_end: "2026-11-01T00:00:00Z",
      warned: [
        { threshold: 80, at: read(120), used: 160 },
        { threshold: 100, at: read(10), used: 200 },
      ],
    } as unknown as Credits;
    show(<AlertsCard monitoring={watch("free", [])} />);
    const capacity = screen.getByTestId("alerts-capacity");
    expect(capacity).toHaveTextContent("100 % des crédits IA du mois utilisés (mesuré)");
    const passed = screen.getAllByTestId("alerts-capacity-passed");
    expect(passed[0]).toHaveTextContent("Seuil de 80 % franchi il y a 2 h.");
    expect(passed[1]).toHaveTextContent("Seuil de 100 % franchi il y a 10 min.");
    expect(capacity).toHaveTextContent("les analyses de LEKA sont suspendues");
    expect(capacity).toHaveTextContent("Aucun dépassement n'est facturé");
    expect(
      screen.getByRole("link", { name: /Passer à un plan offrant plus de capacité/ }),
    ).toHaveAttribute("href", "/billing");
  });

  it("e-mail not included is said: in LEKA only", () => {
    show(<AlertsCard monitoring={watch("starter", ["in_app"])} />);
    expect(screen.getByText("dans LEKA")).toBeVisible();
    expect(screen.getByText("Aucune alerte ouverte.")).toBeVisible();
  });
});
