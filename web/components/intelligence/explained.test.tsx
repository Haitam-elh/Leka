/**
 * On what an analysis rests (LEKA-441), as the screens draw it — the
 * ticket's scenarios.
 *
 * What these protect: what LEKA understood heads it; how sure is said in
 * words with why — never a bare percentage once the analysis says why; each
 * figure opens on what it counts and what it was counted from; each source
 * read is shown in its state — a failing one never as read; what did not
 * answer is said with what that leaves unknown; what the sources disagree
 * on is said, every side and who says it; a correlation is tagged apart,
 * never as a cause, without a percentage; a recommendation that cannot be
 * carried out as it stands says so, and what to settle first; an analysis
 * that failed still says what to do next and why; a context that moved on
 * since is said, with the way to analyse again; an analysis made before
 * draws as it did.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AnalysisView, ProbableCauseList, RecommendationCard } from "@/components/intelligence";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import type { Analysis, Explanation } from "@/lib/intelligence";

function show(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const EXPLANATION: Explanation = {
  understood: "Expliquer une cause · sur payment-api · depuis le 11 oct.",
  consulted: [
    {
      id: "s1",
      name: "acme/backend",
      kind: "github",
      state: "read",
      said: "Synchronisée le 13 oct.",
      elements: 13,
    },
    {
      id: "s2",
      name: "Runbooks space",
      kind: "confluence",
      state: "error",
      said: "En échec : ce qu'elle disait date de sa dernière synchro.",
      elements: 2,
    },
  ],
  silent: [],
  confidence: {
    level: "medium",
    reasons: [
      { id: "confidence.cause_confirmed", effect: "base", label: "Sa cause la plus probable est déclarée par une source." },
      { id: "confidence.sources_unsure", effect: "caps", label: "Runbooks space : en échec, en cours de synchro ou pas à jour." },
    ],
  },
  conflicts: [],
  stale: [],
  limits: ["Runbooks space est en échec : ce qu'elle disait date de sa dernière synchro."],
  next: {
    code: "prepare",
    title: "Préparer « Revenir sur payment-api v2.8.4 » avant d'en décider.",
    why: "Version à restaurer inconnue : aucune source ne dit laquelle tournait avant.",
  },
  freshness: { read: 3, now: 3 },
};

function analysis(more: Partial<Analysis> = {}, explanation: Partial<Explanation> = {}): Analysis {
  return {
    status: "partial",
    summary: "1 changement sur payment-api, suivi d'un incident.",
    missing: ["Toutes les sources n'ont pas répondu : Runbooks space."],
    findings: [{ id: "f", statement: "payment-api p99 au-dessus de 2 s, sev2.", evidence: [] }],
    causes: [
      {
        id: "c",
        label: "payment-api v2.8.4",
        confidence: 0.9,
        basis: "stated",
        strength: "confirmed",
        why: "Sa source dit qu'il l'a causé.",
        evidence: [],
      },
    ],
    impact: null,
    recommendations: [],
    uncertainties: [],
    confidence: 0.84,
    support: [
      {
        id: "sources",
        label: "2 sources à l'appui des constats",
        established: true,
        definition: "Les sources distinctes d'où viennent les preuves de ses constats et de ses causes.",
        refs: [
          { id: "s1", label: "acme/backend" },
          { id: "s3", label: "OPS board" },
        ],
      },
    ],
    explanation: { ...EXPLANATION, ...explanation },
    ...more,
  };
}

describe("an analysis, explained (LEKA-441)", () => {
  it("heads it with what LEKA understood, and says how sure in words, with why", () => {
    show(<AnalysisView analysis={analysis()} />);
    expect(screen.getByTestId("analysis-understood")).toHaveTextContent(
      "Expliquer une cause · sur payment-api",
    );
    const reasons = screen.getByTestId("confidence-reasons");
    expect(within(reasons).getAllByRole("listitem")).toHaveLength(2);
    expect(reasons).toHaveTextContent("déclarée par une source");
    // A level in words — never « 84 % » beside it once the analysis says why.
    const summary = screen.getByTestId("analysis-summary");
    expect(within(summary).getByTestId("confidence")).toHaveAttribute("data-level", "medium");
    expect(screen.getByTestId("analysis-summary")).not.toHaveTextContent("84 %");
  });

  it("opens a figure on what it counts and what it was counted from", async () => {
    show(<AnalysisView analysis={analysis()} />);
    const line = screen.getByText("2 sources à l'appui des constats");
    await userEvent.click(line);
    const claim = line.closest("li") as HTMLElement;
    expect(claim).toHaveTextContent("Les sources distinctes d'où viennent les preuves");
    expect(within(claim).getByText("OPS board")).toBeInTheDocument();
  });

  it("shows each source in its state — a failing one never as read", () => {
    show(<AnalysisView analysis={analysis()} />);
    const sources = screen.getByTestId("sources-consulted");
    const items = within(sources).getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("data-state"))).toEqual(["read", "error"]);
    expect(items[1]).toHaveTextContent("En échec");
    expect(items[1]).not.toHaveTextContent("Lue");
    // Partial, said so, with what is missing.
    expect(screen.getByTestId("analysis")).toHaveAttribute("data-status", "partial");
    expect(screen.getByTestId("analysis-limits")).toHaveTextContent("Runbooks space est en échec");
  });

  it("offers the sources when one that may hold the answer was never read (LEKA-448)", () => {
    const { unmount } = show(<AnalysisView analysis={analysis()} />);
    expect(screen.queryByRole("link", { name: "Voir les sources" })).toBeNull();
    unmount();
    show(
      <AnalysisView
        analysis={analysis(
          {},
          {
            limits: ["Acme GitHub est connectée mais pas encore lue : la réponse peut être incomplète."],
            unread: true,
          },
        )}
      />,
    );
    const limits = screen.getByTestId("analysis-limits");
    expect(within(limits).getByRole("link", { name: "Voir les sources" })).toHaveAttribute(
      "href",
      "/sources",
    );
  });

  it("says what did not answer and what that leaves unknown", () => {
    show(
      <AnalysisView
        analysis={analysis(
          {},
          {
            silent: [
              {
                id: "changes",
                name: "Changements",
                leaves: "Ce qui a changé sur la période n'est pas connu : une cause peut manquer.",
              },
            ],
          },
        )}
      />,
    );
    const silent = screen.getByTestId("analysis-limits");
    expect(within(silent).getByText("Changements")).toBeInTheDocument();
    expect(silent).toHaveTextContent("une cause peut manquer");
  });

  it("says what the sources disagree on, every side and who says it", () => {
    show(
      <AnalysisView
        analysis={analysis(
          {},
          {
            conflicts: [
              {
                id: "k",
                label: "payment-api · sla",
                values: [
                  { value: "99.95", by: ["acme/backend"] },
                  { value: "99.9", by: ["acme-eu"] },
                ],
              },
            ],
          },
        )}
      />,
    );
    const conflicts = screen.getByTestId("analysis-conflicts");
    expect(conflicts).toHaveTextContent("payment-api · sla");
    expect(conflicts).toHaveTextContent("99.95 selon acme/backend");
    expect(conflicts).toHaveTextContent("99.9 selon acme-eu");
  });

  it("tags a correlation apart — never a cause, never a percentage", () => {
    show(
      <ProbableCauseList
        causes={[
          {
            id: "c",
            label: "payment-api v2.8.4",
            confidence: 0.55,
            basis: "inferred",
            strength: "correlated",
            why: "Il a changé 26 heures avant l'incident.",
            evidence: [],
          },
        ]}
      />,
    );
    const cause = screen.getByTestId("probable-cause");
    expect(cause).toHaveTextContent("Corrélation, pas une cause");
    expect(cause).not.toHaveTextContent("Cause probable");
    expect(cause).not.toHaveTextContent("55 %");
  });

  it("says a recommendation cannot be carried out as it stands, and what to settle first", async () => {
    show(
      <RecommendationCard
        recommendation={{
          id: "rollback",
          title: "Revenir sur payment-api v2.8.4",
          rationale: "Sa source dit qu'il a causé l'incident.",
          confidence: 0.9,
          evidence: [],
          executable: false,
          preconditions: [
            {
              id: "precondition.version_to_restore",
              label: "Version à restaurer inconnue : aucune source ne dit laquelle tournait avant.",
              met: false,
              blocking: true,
            },
            { id: "precondition.environment", label: "En production.", met: true, blocking: true },
            {
              id: "precondition.approved",
              label: "Une personne l'approuve avant toute exécution.",
              met: null,
              blocking: false,
            },
          ],
          assumptions: [],
        }}
      />,
    );
    expect(screen.getByTestId("not-executable")).toHaveTextContent("Pas exécutable en l'état");
    expect(screen.getByTestId("unmet")).toHaveTextContent("Version à restaurer inconnue");
    // No version invented: none is named.
    expect(screen.getByRole("article")).not.toHaveTextContent("v2.7");
    await userEvent.click(screen.getByRole("button", { name: /ce qui justifie/i }));
    const pre = screen.getByTestId("preconditions");
    expect(within(pre).getAllByRole("listitem").map((i) => i.getAttribute("data-met"))).toEqual([
      "false",
      "true",
      "null",
    ]);
  });

  it("still says what to do next, and why, when it could not run", () => {
    show(
      <AnalysisView
        analysis={analysis(
          { status: "failed", findings: [], causes: [], missing: ["Changements n'a pas abouti."] },
          {
            confidence: { level: "unknown", reasons: [] },
            next: { code: "rerun", title: "Relancer l'analyse.", why: "Aucune compétence n'a répondu." },
          },
        )}
      />,
    );
    const next = screen.getByTestId("analysis-next");
    expect(next).toHaveAttribute("data-code", "rerun");
    expect(next).toHaveTextContent("Aucune compétence n'a répondu.");
    expect(screen.queryByTestId("analysis-summary")).not.toBeInTheDocument();
  });

  it("says its context moved on since, with the way to read the latest", () => {
    show(
      <AnalysisView
        analysis={analysis({}, { freshness: { read: 2, now: 4 } })}
        again={<button type="button">Relancer</button>}
      />,
    );
    const notice = screen.getByTestId("analysis-freshness");
    expect(notice).toHaveTextContent("version 2 du contexte");
    expect(notice).toHaveTextContent("version 4");
    expect(within(notice).getByRole("button", { name: "Relancer" })).toBeInTheDocument();
  });

  it("draws an analysis made before as it did", () => {
    show(<AnalysisView analysis={analysis({ explanation: null, support: [] })} />);
    expect(screen.queryByTestId("analysis-understood")).not.toBeInTheDocument();
    expect(screen.queryByTestId("analysis-next")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sources-consulted")).not.toBeInTheDocument();
  });
});
