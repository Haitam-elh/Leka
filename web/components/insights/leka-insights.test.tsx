/**
 * "Insights LEKA" (LEKA-377): what LEKA's analyses concluded, on the
 * overview and on Mon environnement.
 *
 * What these protect: the most pressing open findings, worded in French
 * from their code and values — never the API's English when the code is
 * known — each leading to the sheet of what it is about, a context to
 * nothing, a stale source to its page, a family of sources not connected
 * to the sources; every gap told apart by its words; the rest counted;
 * before any analysis it says so, after one
 * that found nothing that too; when the latest analysis ran; whoever may
 * ask LEKA something can analyse now — the button waits for the run, says
 * when one was already under way — and nobody else sees it; a summary that
 * cannot be read says so and can be read again.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Finding, IntelligenceSummary } from "@/lib/insights";
import { waiting } from "@/lib/insights-queries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const api = vi.hoisted(() => ({ summary: vi.fn(), analyse: vi.fn() }));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:create"] as string[] }));

vi.mock("@/lib/insights", async (original) => ({
  ...(await original<typeof import("@/lib/insights")>()),
  insights: api,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));

const { LekaInsights, duration, word } = await import("@/components/insights/leka-insights");
const { DICTIONARIES } = await import("@/lib/i18n/dictionaries");

const DATABASE = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const SERVICE = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CONTEXT = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const SOURCE = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: crypto.randomUUID(),
    analyzer: "dependency_concentration",
    analyzer_version: 1,
    category: "architecture",
    code: "dependency.concentration",
    params: {},
    statement: "An English sentence.",
    severity: "medium",
    rank: 250,
    confidence: 1,
    subject: { type: "entity", id: DATABASE, name: "postgresql", kind: "database" },
    status: "open",
    first_seen_at: hoursAgo(5),
    last_seen_at: hoursAgo(1),
    resolved_at: null,
    occurrences: 2,
    ...overrides,
  };
}

const RUN: NonNullable<IntelligenceSummary["latest"]> = {
  id: crypto.randomUUID(),
  status: "succeeded",
  trigger: "model",
  requested_by: null,
  requested: [],
  started_at: hoursAgo(2),
  finished_at: hoursAgo(2),
  model_built_at: hoursAgo(2),
  job_run_id: null,
  counts: {},
  error: null,
};

const CONCENTRATION = finding({
  severity: "high",
  rank: 340,
  params: {
    name: "postgresql",
    kind: "database",
    dependents: 4,
    status: "unknown",
    watched: false,
    deduced: true,
  },
});
const NO_TEAM = finding({
  analyzer: "ownership",
  category: "organisation",
  code: "ownership.no_owner",
  params: { name: "Leka API", kind: "api", dependents: 0, maintainers: ["Haitam"] },
  subject: { type: "entity", id: SERVICE, name: "Leka API", kind: "service" },
});
const BEHIND = finding({
  analyzer: "context_health",
  category: "context",
  code: "context.behind",
  severity: "low",
  rank: 120,
  params: { title: "Payment API", pending: 6, version: 3 },
  subject: { type: "context", id: CONTEXT, name: "Payment API", kind: "context" },
});

function summary(overrides: Partial<IntelligenceSummary> = {}): IntelligenceSummary {
  return {
    open: { high: 1, medium: 3, low: 1 },
    top: [CONCENTRATION, NO_TEAM, BEHIND],
    latest: RUN,
    ...overrides,
  };
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LocaleProvider>
        <LekaInsights />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "intention:create"];
  api.summary.mockResolvedValue(summary());
  api.analyse.mockResolvedValue({ queued: true });
});

describe("Insights LEKA", () => {
  it("words the most pressing findings, each leading to what it is about", async () => {
    mount();

    const lines = within(await screen.findByTestId("insights-findings")).getAllByRole("listitem");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveTextContent("4 éléments dépendent de postgresql");
    expect(lines[0]).toHaveTextContent("Important · Rien ne le surveille — son état est déduit");
    expect(within(lines[0]).getByRole("link")).toHaveAttribute(
      "href",
      `/environment/databases/${DATABASE}`,
    );
    expect(lines[1]).toHaveTextContent("Aucun responsable nommé pour Leka API");
    expect(lines[1]).toHaveTextContent("Maintenu par Haitam");
    expect(within(lines[1]).getByRole("link")).toHaveAttribute(
      "href",
      `/environment/services/${SERVICE}`,
    );
    // A context has no page of its own: a line, not a link.
    expect(lines[2]).toHaveTextContent("Le contexte « Payment API » est en retard sur le modèle");
    expect(lines[2]).toHaveTextContent("6 changements non pris en compte");
    expect(within(lines[2]).queryByRole("link")).not.toBeInTheDocument();
    // Never the API's English when the code is known.
    expect(screen.queryByText(/An English sentence/)).not.toBeInTheDocument();
    // The rest, counted.
    expect(screen.getByText("+ 2 autres points ouverts")).toBeInTheDocument();
    expect(screen.getByText("Dernière analyse · Il y a 2 h")).toBeInTheDocument();
  });

  it("names fewer where it is told to, and counts the rest", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <LocaleProvider>
          <LekaInsights shown={2} />
        </LocaleProvider>
      </QueryClientProvider>,
    );

    const found = await screen.findByTestId("insights-findings");
    expect(within(found).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("+ 3 autres points ouverts")).toBeInTheDocument();
  });

  it("words a change and what followed it, leading to the service it was made to", async () => {
    api.summary.mockResolvedValue(
      summary({
        top: [
          finding({
            analyzer: "change_impact",
            category: "change",
            code: "change.impact",
            severity: "high",
            params: {
              change: "payment-api v2.8.4",
              kind: "deployment",
              hours: 26,
              environment: "production",
              reached: 3,
              incidents: 1,
            },
            subject: { type: "entity", id: SERVICE, name: "payment-api", kind: "service" },
          }),
          finding({
            analyzer: "change_impact",
            category: "change",
            code: "change.impact",
            params: { change: "CHG-12", kind: "change", hours: 5, reached: 2, incidents: 0 },
            subject: { type: "entity", id: SERVICE, name: "user-service", kind: "service" },
          }),
        ],
      }),
    );
    mount();

    const lines = within(await screen.findByTestId("insights-findings")).getAllByRole("listitem");
    expect(lines[0]).toHaveTextContent("Déploiement « payment-api v2.8.4 » : 1 incident ensuite");
    expect(lines[0]).toHaveTextContent("Important · Il y a 26 h · production");
    expect(within(lines[0]).getByRole("link")).toHaveAttribute(
      "href",
      `/environment/services/${SERVICE}`,
    );
    expect(lines[1]).toHaveTextContent("Changement « CHG-12 » : 2 éléments concernés");
  });

  it("words the gaps, leading to the thing, the source, or the sources to connect", async () => {
    const gap = (overrides: Partial<Finding>) =>
      finding({ analyzer: "gaps_documentation", category: "gaps", ...overrides });
    api.summary.mockResolvedValue(
      summary({
        top: [
          gap({
            code: "gap.stale_documentation",
            severity: "high",
            params: {
              gap: "documentation",
              name: "payment-api",
              kind: "service",
              dependents: 1,
              documents: 1,
              last_documented_at: hoursAgo(24 * 243),
            },
            subject: { type: "entity", id: SERVICE, name: "payment-api", kind: "service" },
          }),
          gap({
            analyzer: "gaps_staleness",
            code: "gap.stale_source",
            params: {
              gap: "staleness",
              name: "Runbooks",
              kind: "confluence",
              status: "active",
              since: hoursAgo(24 * 5 + 2),
              entities: 0,
            },
            subject: { type: "source", id: SOURCE, name: "Runbooks", kind: "confluence" },
          }),
          gap({
            analyzer: "gaps_coverage",
            code: "gap.coverage.monitoring",
            params: { gap: "coverage", family: "monitoring", count: 4 },
            subject: { type: "coverage", id: null, name: "monitoring", kind: "monitoring" },
          }),
        ],
      }),
    );
    mount();

    const lines = within(await screen.findByTestId("insights-findings")).getAllByRole("listitem");
    expect(lines[0]).toHaveTextContent("La documentation de payment-api n'est plus à jour");
    expect(lines[0]).toHaveTextContent("Important · Modifiée il y a 243 j");
    expect(within(lines[0]).getByRole("link")).toHaveAttribute(
      "href",
      `/environment/services/${SERVICE}`,
    );
    expect(lines[1]).toHaveTextContent("La source Runbooks n'a pas été lue depuis 5 j");
    expect(lines[1]).toHaveTextContent("Ce qu'elle montre a pu changer");
    expect(within(lines[1]).getByRole("link")).toHaveAttribute("href", `/sources/${SOURCE}`);
    expect(lines[2]).toHaveTextContent("Aucune supervision connectée");
    expect(lines[2]).toHaveTextContent("4 services non surveillés");
    expect(within(lines[2]).getByRole("link")).toHaveAttribute("href", "/sources");
  });

  it("tells every gap apart, never in the API's English", () => {
    const t = DICTIONARIES.fr;
    const thing = { name: "user-service", kind: "service", dependents: 2 };
    const said = (code: string, params: Record<string, unknown>) =>
      word(t, finding({ code, category: "gaps", params }));

    expect(said("gap.missing_entity.runtime", thing)).toEqual({
      title: "On ne sait pas où tourne user-service",
      detail: "Service · 2 éléments en dépendent",
    });
    expect(said("gap.missing_entity.code", thing).title).toBe("Le code de user-service est inconnu");
    expect(said("gap.missing_entity.data_model", { name: "postgres-prod" }).title).toBe(
      "Les tables de postgres-prod sont inconnues",
    );
    expect(said("gap.missing_relationship.isolated", { name: "orphan", kind: "worker" })).toEqual({
      title: "orphan n'est relié à rien",
      detail: "Tâches de fond",
    });
    expect(said("gap.missing_relationship.business", thing).title).toBe(
      "Aucune application ni capacité métier ne porte user-service",
    );
    expect(said("gap.missing_documentation", thing).title).toBe(
      "Aucun document ne décrit user-service",
    );
    expect(said("gap.stale_knowledge.dormant", { ...thing, name: "ledger" })).toEqual({
      title: "ledger est inactif depuis des mois",
      detail: "Service · 2 éléments en dépendent",
    });
    expect(said("gap.stale_source", { name: "OPS", status: "error", since: hoursAgo(30) })).toEqual({
      title: "La source OPS est en erreur",
      detail: "Dernière lecture il y a 1 j",
    });
    expect(said("gap.stale_source", { name: "Wiki", status: "active", since: null })).toEqual({
      title: "La source Wiki n'a jamais été lue",
      detail: null,
    });
    expect(said("gap.coverage.organisation", { family: "organisation", count: 6 })).toEqual({
      title: "Aucun responsable connu",
      detail: "Personne n'est nommé pour 6 éléments",
    });
    // A family the interface does not know yet: its English sentence.
    expect(said("gap.coverage.telepathy", { family: "telepathy", count: 1 }).title).toBe(
      "An English sentence.",
    );
  });

  it("words weak knowledge, a thing's and an area's, in French and in English", () => {
    const weak = finding({
      analyzer: "quality",
      category: "quality",
      code: "quality.low",
      params: { name: "orphan-worker", score: 0.414, missing: ["unseen", "weak_records"] },
    });
    const area = (scope: string) =>
      finding({
        analyzer: "quality",
        category: "quality",
        code: "quality.low_area",
        params: { name: "Legacy", scope, entities: 3, score: 0.5 },
      });

    expect(word(DICTIONARIES.fr, weak)).toEqual({
      title: "Ce que LEKA sait de orphan-worker est peu fiable",
      detail: "Qualité 41 % · plus vu par ses sources depuis des semaines",
    });
    expect(word(DICTIONARIES.en, weak)).toEqual({
      title: "What LEKA knows of orphan-worker is weak",
      detail: "Quality 41% · not shown by its sources for weeks",
    });
    expect(word(DICTIONARIES.fr, area("team"))).toEqual({
      title: "Connaissance peu fiable : Legacy",
      detail: "Équipe · 3 éléments · qualité 50 %",
    });
    expect(word(DICTIONARIES.fr, area("workspace")).title).toBe(
      "Ce que LEKA sait de votre environnement est peu fiable",
    );
    // A lack the interface does not know yet: the score alone.
    expect(word(DICTIONARIES.fr, { ...weak, params: { ...weak.params, missing: ["telepathy"] } }).detail).toBe(
      "Qualité 41 %",
    );
  });

  it("words what the model's course says, and what to do, in French and in English", () => {
    const fr = DICTIONARIES.fr;
    const evolution = (code: string, params: Record<string, unknown>) =>
      finding({ category: "evolution", code, params });
    const said = [
      evolution("evolution.dependencies_grew", {
        name: "payment-api",
        added: 3,
        names: ["fx-rates", "ledger-api", "tax-service"],
        recommendation: "review_dependencies",
      }),
      evolution("evolution.owner_lost", {
        name: "billing-queue",
        before: ["Platform"],
        at: hoursAgo(24 * 9),
        recommendation: "name_owner",
      }),
      evolution("evolution.owner_changed", {
        name: "user-service",
        before: ["Nadia Kowalski"],
        after: ["Thomas Berger"],
        recommendation: "confirm_owner",
      }),
      evolution("evolution.removed_relied", {
        name: "redis-sessions",
        names: ["auth-service"],
        recommendation: "confirm_removal",
      }),
      evolution("evolution.architecture_moved", {
        created: 3,
        removed: 1,
        recommendation: "review_architecture",
      }),
      evolution("evolution.incidents_rising", {
        name: "checkout",
        recent: 4,
        before: 1,
        recommendation: "investigate_incidents",
      }),
      evolution("evolution.volatile", {
        name: "feature-flags",
        changes: 5,
        recommendation: "watch_changes",
      }),
      evolution("evolution.quality_fell", {
        name: "workspace",
        scope: "workspace",
        before: 0.72,
        after: 0.58,
        recommendation: "review_quality",
      }),
      evolution("evolution.quality_fell", {
        name: "services",
        scope: "column",
        column: "services",
        before: 0.9,
        after: 0.75,
        recommendation: "review_quality",
      }),
    ].map((f) => word(fr, f));

    expect(said).toEqual([
      {
        title: "payment-api dépend de 3 éléments de plus qu'il y a un mois",
        detail: "Nouveaux : fx-rates, ledger-api, tax-service · Revoir ses dépendances",
      },
      {
        title: "billing-queue n'a plus de responsable",
        detail: "Platform n'est plus nommé depuis 9 j · Nommer un responsable",
      },
      {
        title: "user-service a changé de responsable",
        detail: "Nadia Kowalski → Thomas Berger · Confirmer le nouveau responsable",
      },
      {
        title: "redis-sessions a disparu de vos sources",
        detail: "auth-service en dépendait encore · Confirmer la suppression",
      },
      {
        title: "Votre architecture a bougé ce mois-ci",
        detail: "3 apparus, 1 disparu · Revoir l'architecture",
      },
      {
        title: "Les incidents augmentent sur checkout",
        detail: "4 ce mois-ci, 1 le mois précédent · Analyser les incidents",
      },
      {
        title: "feature-flags change souvent",
        detail: "5 changements ce mois-ci · Surveiller ses changements",
      },
      {
        title: "La qualité de ce que LEKA sait de votre entreprise baisse",
        detail: "72 % il y a un mois, 58 % aujourd'hui · Voir ce qui la fait baisser",
      },
      {
        title: "La qualité de ce que LEKA sait de Services baisse",
        detail: "90 % il y a un mois, 75 % aujourd'hui · Voir ce qui la fait baisser",
      },
    ]);
    const english = finding({ code: "evolution.volatile", params: { name: "x", changes: 4 } });
    expect(word(DICTIONARIES.en, english)).toEqual({
      title: "x changes often",
      detail: "4 changes this month",
    });
  });

  it("says the English sentence of a code it does not know yet", async () => {
    api.summary.mockResolvedValue(
      summary({ top: [finding({ code: "gap.undocumented", statement: "A change reached 3 things." })] }),
    );
    mount();

    expect(await screen.findByText("A change reached 3 things.")).toBeInTheDocument();
  });

  it("says when LEKA has not analysed yet, and when it found nothing", async () => {
    api.summary.mockResolvedValue(summary({ top: [], open: { high: 0, medium: 0, low: 0 }, latest: null }));
    const { unmount } = mount();
    expect(await screen.findByTestId("insights-empty")).toHaveTextContent(
      "LEKA n'a pas encore analysé votre environnement.",
    );
    unmount();

    api.summary.mockResolvedValue(summary({ top: [], open: { high: 0, medium: 0, low: 0 } }));
    mount();
    expect(await screen.findByTestId("insights-empty")).toHaveTextContent(
      "Rien à signaler : la dernière analyse n'a rien trouvé d'ouvert.",
    );
  });

  it("analyses now for who may ask LEKA something, and waits for the run", async () => {
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByTestId("insights-analyse"));

    expect(api.analyse).toHaveBeenCalledOnce();
    const button = await screen.findByRole("button", { name: /Analyse en cours/ });
    expect(button).toBeDisabled();
  });

  it("says when an analysis was already under way", async () => {
    const user = userEvent.setup();
    api.analyse.mockResolvedValue({ queued: false });
    mount();

    await user.click(await screen.findByTestId("insights-analyse"));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Une analyse est déjà en cours : elle répondra.",
    );
  });

  it("offers no analysis to who may not ask LEKA something", async () => {
    permissions.value = ["workspace:read"];
    mount();

    await screen.findByTestId("insights-findings");
    expect(screen.queryByTestId("insights-analyse")).not.toBeInTheDocument();
  });

  it("says when the analyses cannot be read, and reads them again", async () => {
    const user = userEvent.setup();
    api.summary.mockRejectedValueOnce(new Error("down"));
    mount();

    const failed = await screen.findByTestId("insights-failed");
    expect(failed).toHaveTextContent("Les analyses de LEKA n'ont pas pu être lues.");
    await user.click(within(failed).getByRole("button", { name: "Réessayer" }));

    expect(await screen.findByTestId("insights-findings")).toBeInTheDocument();
    expect(api.summary).toHaveBeenCalledTimes(2);
  });
});

describe("waiting for a run asked for", () => {
  const asked = Date.parse("2026-10-05T12:00:00Z");
  const run = (started: string, status: (typeof RUN)["status"]) => ({
    ...summary(),
    latest: { ...RUN, started_at: started, status },
  });

  it("waits until a run started after the ask has finished, fifteen minutes at most", () => {
    expect(waiting(run("2026-10-05T11:00:00Z", "succeeded"), asked, asked + 5_000)).toBe(true);
    expect(waiting(run("2026-10-05T12:00:03Z", "running"), asked, asked + 9_000)).toBe(true);
    expect(waiting(run("2026-10-05T12:00:03Z", "succeeded"), asked, asked + 9_000)).toBe(false);
    // Past two minutes, still followed: an analysis can take longer.
    expect(waiting(run("2026-10-05T12:00:03Z", "running"), asked, asked + 180_000)).toBe(true);
    expect(waiting(run("2026-10-05T11:00:00Z", "succeeded"), asked, asked + 16 * 60_000)).toBe(
      false,
    );
    expect(waiting(summary(), null)).toBe(false);
  });

  it("follows a run under way, asked by someone else, until it ends", () => {
    const now = Date.parse("2026-10-05T12:01:00Z");
    expect(waiting(run("2026-10-05T12:00:00Z", "running"), null, now)).toBe(true);
    // One left running an hour ago is not waited for.
    expect(waiting(run("2026-10-05T11:00:00Z", "running"), null, now)).toBe(false);
  });

  it("says how long, short", () => {
    expect(duration(45_000)).toBe("45 s");
    expect(duration(125_000)).toBe("2 min 05 s");
  });
});
