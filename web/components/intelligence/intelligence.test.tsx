/**
 * LEKA's intelligence components (LEKA-341).
 *
 * What these protect: a fact, a hypothesis and a proposal are named and
 * drawn apart; confidence is said in words, with what it rests on, and
 * "inconnue" when nothing said; evidence opens from where it is used, on
 * its source, its date, what it holds and a way to see it whole; a cause
 * is ranked, sure to a degree, and says why; impact says the risk in words
 * and what it is read from, never low for unknown; a recommendation says
 * what it would change and whether it can be undone; an analysis says
 * whether it is partial — and what is missing — inconclusive, failed — and
 * offers to retry — or not there yet, before what it found; what LEKA
 * does not know is said.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AnalysisState,
  AnalysisView,
  ConfidenceBadge,
  EvidenceList,
  ImpactPanel,
  IntelligenceSection,
  ProbableCauseList,
  RecommendationCard,
} from "@/components/intelligence";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import {
  type Analysis,
  confidenceLevel,
  type EvidenceRef,
  riskOf,
} from "@/lib/intelligence";

const NOW = new Date().toISOString();

function show(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

const RECORD: EvidenceRef = {
  id: "r",
  label: "OPS-1841",
  kind: "record",
  source: { kind: "jira", name: "OPS board" },
  detail: "l'enregistrement de l'incident",
  at: NOW,
  href: "https://acme.atlassian.net/browse/OPS-1841",
  facts: [{ label: "Clé", value: "OPS-1841" }],
};

describe("what each statement is", () => {
  it("names and draws a fact, a hypothesis and a proposal apart", () => {
    show(
      <>
        <IntelligenceSection kind="fact" title="Ce que disent les sources">
          <p>x</p>
        </IntelligenceSection>
        <IntelligenceSection kind="hypothesis" title="Causes probables">
          <p>y</p>
        </IntelligenceSection>
        <IntelligenceSection kind="proposal" title="Recommandations">
          <p>z</p>
        </IntelligenceSection>
      </>,
    );
    const fact = screen.getByRole("region", { name: "Ce que disent les sources" });
    const hypothesis = screen.getByRole("region", { name: "Causes probables" });
    const proposal = screen.getByRole("region", { name: "Recommandations" });
    expect(fact).toHaveTextContent("Constat");
    expect(hypothesis).toHaveTextContent("Hypothèse");
    expect(proposal).toHaveTextContent("Proposition de LEKA");
    expect(proposal.className).toContain("border-dashed");
    expect(fact.className).not.toBe(hypothesis.className);
  });
});

describe("confidence", () => {
  it("is said in words, with what it rests on", () => {
    show(
      <>
        <ConfidenceBadge score={0.9} basis="stated" />
        <ConfidenceBadge score={0.7} basis="inferred" />
        <ConfidenceBadge score={0.3} />
        <ConfidenceBadge score={null} />
      </>,
    );
    const said = screen.getAllByTestId("confidence").map((badge) => [
      badge.getAttribute("data-level"),
      badge.textContent,
    ]);
    expect(said).toEqual([
      ["high", "Confiance élevée · 90 % · déclaré par la source"],
      ["medium", "Confiance moyenne · 70 % · déduit par LEKA"],
      ["low", "Confiance faible · 30 %"],
      ["unknown", "Confiance inconnue"],
    ]);
  });

  it("reads a score and a severity in words", () => {
    expect([0.95, 0.85, 0.6, 0.59, 0, null, undefined].map(confidenceLevel)).toEqual([
      "high",
      "high",
      "medium",
      "low",
      "low",
      "unknown",
      "unknown",
    ]);
    const said = ["sev1", "P1", "critical", "sev2", "High", "sev4", "minor", "", null, "weird"];
    expect(said.map(riskOf)).toEqual([
      "high",
      "high",
      "high",
      "medium",
      "medium",
      "low",
      "low",
      "unknown",
      "unknown",
      "unknown",
    ]);
  });
});

describe("evidence", () => {
  it("opens, from where it is used, on what it holds and where to see it", async () => {
    const user = userEvent.setup();
    show(<EvidenceList items={[RECORD]} />);

    const item = screen.getByTestId("evidence-item");
    expect(item).toHaveTextContent("OPS-1841");
    expect(screen.queryByTestId("evidence-detail")).not.toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: "Voir la preuve OPS-1841" }));
    const detail = screen.getByTestId("evidence-detail");
    expect(detail).toHaveTextContent("NatureEnregistrement d'une source");
    expect(detail).toHaveTextContent("SourceOPS board");
    expect(detail).toHaveTextContent("CléOPS-1841");
    expect(within(detail).getByRole("link", { name: "Ouvrir" })).toHaveAttribute(
      "href",
      RECORD.href,
    );
  });

  it("says when there is none", () => {
    show(<EvidenceList items={[]} />);
    expect(screen.getByText("Aucune preuve.")).toBeInTheDocument();
  });
});

describe("probable causes", () => {
  it("are ranked, sure to a degree, say why, and open on their evidence", async () => {
    const user = userEvent.setup();
    show(
      <ProbableCauseList
        causes={[
          {
            id: "a",
            label: "payment-api v2.8.4",
            kind: "Déploiement",
            href: "/environment/deployments/a",
            confidence: 0.83,
            basis: "stated",
            why: "Une source le déclare.",
            evidence: [RECORD],
          },
          {
            id: "b",
            label: "Feature flag flipped",
            confidence: 0.6,
            basis: "inferred",
            why: "Il a eu lieu juste avant l'incident.",
            evidence: [],
          },
        ]}
      />,
    );
    const [first, second] = screen.getAllByTestId("probable-cause");
    expect(first).toHaveTextContent("Hypothèse 1");
    expect(first).toHaveTextContent("Confiance moyenne · 83 % · déclaré par la source");
    expect(first).toHaveTextContent("Pourquoi : Une source le déclare.");
    expect(within(first).getByRole("link", { name: "payment-api v2.8.4" })).toBeInTheDocument();
    expect(second).toHaveTextContent("Hypothèse 2");
    expect(second).toHaveTextContent("déduit par LEKA");
    await user.click(within(first).getByRole("button", { name: /1 preuve/ }));
    expect(within(first).getByTestId("evidence")).toHaveTextContent("OPS-1841");
  });
});

describe("impact", () => {
  it("says the risk in words and what it is read from, area by area", () => {
    show(
      <ImpactPanel
        impact={{
          areas: [
            { id: "affected", label: "Touché", items: [{ id: "p", label: "payment-api" }] },
            { id: "dependents", label: "Qui en dépend", items: [] },
          ],
          risk: "medium",
          riskBasis: "d'après la gravité déclarée (sev2)",
        }}
      />,
    );
    const impact = screen.getByTestId("impact");
    expect(impact).toHaveTextContent("Risque moyen");
    expect(impact).toHaveTextContent("d'après la gravité déclarée (sev2)");
    expect(impact).toHaveTextContent("Touché (1)payment-api");
    // An empty area is not drawn.
    expect(impact).not.toHaveTextContent("Qui en dépend");
  });

  it("never says low for unknown", () => {
    show(<ImpactPanel impact={{ areas: [], risk: "unknown", riskBasis: "aucune gravité" }} />);
    expect(screen.getByTestId("risk")).toHaveTextContent("Risque inconnu");
  });
});

describe("a recommendation", () => {
  it("is a proposal: why, what it changes, how risky, whether it can be undone", () => {
    show(
      <RecommendationCard
        recommendation={{
          id: "r",
          title: "Revenir à v2.8.3",
          rationale: "La latence a commencé avec 2.8.4.",
          effect: "3 services concernés",
          risk: "medium",
          reversible: false,
          confidence: 0.82,
          evidence: [],
        }}
      />,
    );
    const card = screen.getByRole("article", { name: "Revenir à v2.8.3" });
    expect(card).toHaveTextContent("La latence a commencé avec 2.8.4.");
    expect(card).toHaveTextContent("Effet : 3 services concernés");
    expect(card).toHaveTextContent("Risque moyen");
    expect(card).toHaveTextContent("Irréversible");
    expect(card).toHaveTextContent("Confiance moyenne · 82 %");
  });
});

describe("how an analysis went", () => {
  it("says partial and what is missing, inconclusive, failed — retried — or none yet", async () => {
    const retry = vi.fn();
    const user = userEvent.setup();
    show(
      <>
        <AnalysisState status="partial" missing={["ce qui l'a causé"]} />
        <AnalysisState status="inconclusive" />
        <AnalysisState status="failed" onRetry={retry} />
        <AnalysisState status="pending" />
        <AnalysisState status="complete" />
      </>,
    );
    const states = screen.getAllByTestId("analysis-state");
    expect(states.map((s) => s.getAttribute("data-status"))).toEqual([
      "partial",
      "inconclusive",
      "failed",
      "pending",
    ]);
    expect(states[0]).toHaveTextContent("Analyse partielle");
    expect(states[0]).toHaveTextContent("ce qui l'a causé");
    expect(states[1]).toHaveTextContent("Analyse non concluante");
    expect(screen.getByRole("alert")).toHaveTextContent("L'analyse a échoué");
    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(states[3]).toHaveTextContent("Pas encore d'analyse");
  });

  it("draws an analysis in its one order, what it does not know last", () => {
    const analysis: Analysis = {
      status: "partial",
      missing: ["ce qu'il touche"],
      findings: [{ id: "f", statement: "OPS-1841 : clos, sev2.", evidence: [RECORD] }],
      causes: [],
      impact: null,
      recommendations: [],
      uncertainties: ["Aucune source ne dit ce qui l'a causé."],
      confidence: null,
    };
    show(<AnalysisView analysis={analysis} />);

    const order = screen
      .getAllByTestId(/^(analysis-state|intelligence-\w+|uncertainties)$/)
      .map((node) => node.getAttribute("data-testid"));
    expect(order).toEqual([
      "analysis-state",
      "intelligence-fact",
      "intelligence-hypothesis",
      "intelligence-fact",
      "intelligence-proposal",
      "uncertainties",
    ]);
    expect(screen.getByText("Aucune cause n'est déclarée ni soupçonnée.")).toBeInTheDocument();
    expect(screen.getByTestId("intelligence-proposal")).toHaveTextContent(
      "LEKA ne propose pas encore de recommandation",
    );
    expect(screen.getByTestId("uncertainties")).toHaveTextContent("Ce que LEKA ne sait pas (1)");
    expect(screen.getByText(/Confiance de l'analyse/)).toHaveTextContent("Confiance inconnue");
  });

  it("draws nothing it did not find when it failed", () => {
    show(
      <AnalysisView
        analysis={{
          status: "failed",
          missing: [],
          findings: [],
          causes: [],
          impact: null,
          recommendations: [],
          uncertainties: [],
          confidence: null,
        }}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("intelligence-fact")).not.toBeInTheDocument();
  });
});
