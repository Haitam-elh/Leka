/**
 * « Mon environnement », diagnosed (LEKA-532).
 *
 * What these protect: the score counted again from the rows under it —
 * health apart from coverage, 100 % never a promise, the ceiling said when
 * a provider gives no readable state; every thing « Inconnu » counts, one
 * row each, with its type, source, environment, last observation and why,
 * from what its sources say only; what fixes each, the way there, or that
 * nothing can today; what AWS refused LEKA, with the permissions to grant;
 * the rule and each state's meaning.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { EnvironmentDiagnostic } from "@/components/environment/diagnostic";
import type { Environment } from "@/lib/environment";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { Tracked, TwinSource, TwinStateName } from "@/lib/twin";

const read = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const AWS: TwinSource = {
  id: "aws-1",
  kind: "aws",
  name: "production account",
  category: "cloud",
  state: "read",
  last_synced_at: read(10),
  error: null,
  webhooks: false,
  unread: ["functions", "load_balancers"],
  needs: ["lambda:ListFunctions", "elasticloadbalancing:DescribeLoadBalancers"],
};
const DATADOG: TwinSource = { ...AWS, id: "dd-1", kind: "datadog", name: "acme-eu", category: "observability", unread: [], needs: [] };
const GITHUB: TwinSource = { ...AWS, id: "gh-1", kind: "github", name: "acme/backend", category: "code", state: "stale", unread: [], needs: [] };

function row(
  name: string,
  state: TwinStateName,
  reason: string,
  more: Partial<Tracked> = {},
  twin: Partial<Tracked["twin"]> = {},
): Tracked {
  return {
    entity: { id: `00000000-0000-0000-0000-00000000000${name.length}`, type: "infra_resource", key: name, name },
    resource_type: null,
    provider: "aws",
    region: "eu-west-1",
    environment: "production",
    sources: ["aws-1"],
    twin: {
      state,
      basis: "none",
      reason,
      observed_at: read(10),
      signal: [],
      fresh: true,
      was: null,
      certainty: "confirmed",
      incident: null,
      said: null,
      ...twin,
    },
    ...more,
  };
}

const TRACKED: Tracked[] = [
  row("payment", "unavailable", "incident_open", { entity: { id: "pay", type: "service", key: "s:pay", name: "payment" }, sources: ["dd-1"] }, {
    incident: { id: "inc-1", key: "OPS-9", name: "down", severity: "sev1" },
  }),
  row("backend", "stale", "sources_stale", { entity: { id: "be", type: "service", key: "s:be", name: "backend" }, sources: ["gh-1"], environment: null, region: null }, { was: "operational" }),
  row("auth", "unknown", "not_watched", { entity: { id: "auth", type: "service", key: "s:auth", name: "auth" }, sources: ["gh-1"] }),
  row("invoices", "unknown", "provider_no_state", { resource_type: "s3:bucket" }),
  row("ledger", "unknown", "state_unrecognised", { resource_type: "rds:db" }, { said: "modifying" }),
  row("cluster", "operational", "resource_running", { resource_type: "eks:cluster" }, { said: "running" }),
];

function environment(tracked = TRACKED, sources = [AWS, DATADOG, GITHUB]): Environment {
  return {
    tracked,
    sources,
    states: {},
    freshness: { last_read_at: read(10), every_minutes: 60, late: false, webhooks: false },
  } as unknown as Environment;
}

function Screen({ data, start = null }: { data: Environment; start?: TwinStateName | null }) {
  const [only, setOnly] = useState<TwinStateName | null>(start);
  return <EnvironmentDiagnostic environment={data} filter={only} onFilter={setOnly} />;
}

function show(data = environment(), start: TwinStateName | null = null) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <Screen data={data} start={start} />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

const rows = () => within(screen.getByRole("table")).getAllByRole("row").slice(1);

describe("the diagnosis", () => {
  it("counts the score again from its rows: health apart from coverage, the ceiling said", () => {
    show();
    expect(screen.getByTestId("diagnostic-health")).toHaveTextContent("17 %");
    expect(screen.getByTestId("diagnostic-health")).toHaveTextContent("1 sur 6 en bonne santé");
    // Known: unavailable and healthy; stale and unknown are not.
    expect(screen.getByTestId("diagnostic-coverage")).toHaveTextContent("33 %");
    expect(screen.getByTestId("diagnostic-coverage")).toHaveTextContent("2 sur 6 avec un état connu");
    expect(screen.getByTestId("diagnostic")).toHaveTextContent("100 % ne garantit pas que tout fonctionne");
    // A bucket and a word LEKA cannot read: never healthy, said as the ceiling.
    expect(screen.getByTestId("diagnostic-reachable")).toHaveTextContent(
      "le score ne peut pas dépasser 67 % : 2 éléments n'ont aucun état",
    );
    expect(screen.getByTestId("diagnostic-method")).toHaveTextContent("Ici : 1 ÷ 6 = 17 %.");
    // The counts are the rows': 3 unknown.
    expect(within(screen.getByTestId("twin-counts")).getByText("Inconnu").parentElement).toHaveTextContent("3Inconnu");
  });

  it("lists what keeps it from 100 %, the most urgent first, each with its impact", () => {
    show();
    expect(rows().map((r) => r.querySelector("a")?.textContent)).toEqual([
      "payment",
      "backend",
      "auth",
      "invoices",
      "ledger",
    ]);
    expect(within(rows()[0]).getByTestId("diagnostic-points")).toHaveTextContent("−16,7 pt");
    // Healthy: not a line.
    expect(screen.queryByRole("link", { name: "cluster" })).not.toBeInTheDocument();
  });

  it("opens on « Inconnu »: each thing, its type, source, environment, when, why — only what its sources say", () => {
    show(environment(), "unknown");
    expect(screen.getByTestId("diagnostic-filter")).toHaveTextContent("Seulement « Inconnu » : 3 éléments");
    expect(screen.getByTestId("diagnostic-filter")).toHaveTextContent("Inconnu ne veut dire ni sain, ni en panne.");
    const [auth, invoices, ledger] = rows();
    expect(within(auth).getByTestId("diagnostic-why")).toHaveTextContent(
      "Un outil de supervision est connecté (acme-eu), mais aucun ne suit ce service, ou pas sous ce nom.",
    );
    expect(within(invoices).getByTestId("diagnostic-why")).toHaveTextContent(
      "production account le liste sans donner d'état pour ce type de ressource (s3:bucket).",
    );
    expect(invoices).toHaveTextContent("s3:bucket");
    expect(within(invoices).getByTestId("diagnostic-source")).toHaveTextContent("production account");
    expect(invoices).toHaveTextContent("production · eu-west-1");
    expect(invoices).toHaveTextContent("Il y a 10 min");
    expect(within(ledger).getByTestId("diagnostic-why")).toHaveTextContent("production account le dit « modifying »");
    // Back to all of them.
    expect(rows()).toHaveLength(3);
  });

  it("says what fixes each, the way there — or that nothing can today", async () => {
    const user = userEvent.setup();
    show();
    const fix = (i: number) => within(rows()[i]).getByTestId("diagnostic-fix");
    expect(fix(0)).toHaveAttribute("data-fix", "incident");
    expect(within(fix(0)).getByRole("link")).toHaveAttribute("href", "/environment/incidents/inc-1");
    // Its stale source, by name, to its page.
    expect(within(fix(1)).getByRole("link")).toHaveTextContent("Réparer ou relancer acme/backend");
    expect(within(fix(1)).getByRole("link")).toHaveAttribute("href", "/sources?source=gh-1");
    expect(fix(1).closest("tr")).toHaveTextContent("(était en bonne santé)");
    expect(fix(2)).toHaveAttribute("data-fix", "watch");
    // Nothing to do, said — never a link that leads nowhere.
    expect(fix(3)).toHaveAttribute("data-fix", "limit");
    expect(within(fix(3)).queryByRole("link")).toBeNull();
    expect(fix(3)).toHaveTextContent("Rien à faire aujourd'hui");
    // A count is a filter; « Tout voir » lifts it.
    await user.click(within(screen.getByTestId("twin-counts")).getByRole("button", { name: /Données obsolètes/ }));
    expect(rows()).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Tout voir" }));
    expect(rows()).toHaveLength(5);
  });

  it("says what AWS refused LEKA, and the permissions to grant", () => {
    show();
    const unread = screen.getByTestId("diagnostic-unread");
    expect(unread).toHaveTextContent(
      "production account : au dernier test, AWS a refusé la lecture des fonctions Lambda, load balancers.",
    );
    expect(unread).toHaveTextContent("lambda:ListFunctions, elasticloadbalancing:DescribeLoadBalancers");
    expect(within(unread).getByRole("link", { name: "Ouvrir la source" })).toHaveAttribute("href", "/sources?source=aws-1");
  });

  it("all healthy: nothing in the way, 100 % reachable, no ceiling invented", () => {
    show(environment([row("cluster", "operational", "resource_running")], [AWS]));
    expect(screen.getByTestId("diagnostic-health")).toHaveTextContent("100 %");
    expect(screen.getByTestId("diagnostic-reachable")).toHaveTextContent("100 % est atteignable");
    expect(screen.getByText("Rien : tout ce qui est suivi est en bonne santé.")).toBeInTheDocument();
  });
});
