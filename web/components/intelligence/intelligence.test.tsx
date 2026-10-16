/**
 * LEKA's intelligence components (LEKA-341), as mockups 03 to 05 and 11
 * draw them.
 *
 * What these protect: what kind of statement a line is, it says — a fact
 * "Constat", a hypothesis "Cause déclarée", "Cause probable" or "À
 * confirmer" with how sure, a proposal a card with its priority and no
 * such tag; confidence is said in words, with its score and what it rests
 * on, and "inconnue" when nothing said; evidence opens from where it is
 * used, on its source, its date, what it holds and a way to see it whole;
 * impact says its level in words and what it is read from, never low for
 * unknown; a recommendation says what it touches, how long, whether it can
 * be undone, how risky and how sure, and opens on what justifies it; an
 * analysis says whether it is running, partial — and what is missing —
 * inconclusive, failed — and offers to retry — or not there yet, before
 * what it found, in its one order; what LEKA does not know is said.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AnalysisState,
  AnalysisView,
  ConfidenceBadge,
  ConfidencePanel,
  ControlNotice,
  EvidenceList,
  EvidenceStrip,
  FindingList,
  ImpactPanel,
  IntelligenceSection,
  ProbableCauseList,
  RecommendationCard,
  RiskBadge,
} from "@/components/intelligence";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import {
  type Analysis,
  causeTag,
  confidenceLevel,
  type EvidenceRef,
  evidenceOf,
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

function piece(id: string): EvidenceRef {
  return { id, label: `Preuve ${id}`, kind: "event", href: `/environment/deployments/${id}` };
}

/** A confidence's pill, and what follows it. */
function confidence(badge: HTMLElement) {
  return [
    badge.getAttribute("data-level"),
    badge.children[0]?.textContent,
    badge.children[1]?.textContent ?? null,
  ];
}

describe("what each statement is", () => {
  it("is a section named by its title, holding what its kind says", () => {
    show(
      <IntelligenceSection kind="fact" title="Constats" count="2 constats" subtitle="Lus">
        <p>x</p>
      </IntelligenceSection>,
    );
    const section = screen.getByRole("region", { name: "Constats" });
    expect(section).toHaveAttribute("data-kind", "fact");
    expect(section).toHaveTextContent("2 constats");
    expect(section).toHaveTextContent("Lus");
  });

  it("tags a fact, a stated, a probable and a doubtful cause apart — and a proposal by its priority", () => {
    show(
      <>
        <FindingList
          findings={[{ id: "f", title: "Durée", statement: "Il a duré 4 h.", evidence: [] }]}
        />
        <ProbableCauseList
          causes={[
            { id: "a", label: "A", confidence: 0.9, basis: "stated", why: "w", evidence: [] },
            { id: "b", label: "B", confidence: 0.7, basis: "inferred", why: "w", evidence: [] },
            { id: "c", label: "C", confidence: 0.3, basis: "inferred", why: "w", evidence: [] },
          ]}
        />
        <RecommendationCard
          recommendation={{
            id: "r",
            title: "Revenir à v2.8.3",
            rationale: "r",
            priority: "high",
            confidence: 0.8,
            evidence: [],
          }}
        />
      </>,
    );
    expect(screen.getAllByTestId("statement-tag").map((tag) => tag.textContent)).toEqual([
      "Constat",
      "Cause déclarée",
      "Cause probable",
      "À confirmer",
    ]);
    const card = screen.getByRole("article", { name: "Revenir à v2.8.3" });
    expect(within(card).queryByTestId("statement-tag")).not.toBeInTheDocument();
    expect(within(card).getByTestId("priority")).toHaveTextContent("Priorité haute");
  });

  it("reads a cause's tag from its basis and its confidence", () => {
    expect(
      [
        { basis: "stated" as const, confidence: 0.2 },
        { basis: "inferred" as const, confidence: 0.85 },
        { basis: "inferred" as const, confidence: 0.6 },
        { basis: "inferred" as const, confidence: 0.59 },
        { basis: "inferred" as const, confidence: null },
      ].map(causeTag),
    ).toEqual(["stated", "probable", "probable", "toConfirm", "toConfirm"]);
  });
});

describe("confidence", () => {
  it("is said in words, with its score and what it rests on", () => {
    show(
      <>
        <ConfidenceBadge score={0.9} basis="stated" />
        <ConfidenceBadge score={0.7} basis="inferred" />
        <ConfidenceBadge score={0.3} />
        <ConfidenceBadge score={null} />
        <ConfidenceBadge score={0.9} short detail={false} />
      </>,
    );
    expect(screen.getAllByTestId("confidence").map(confidence)).toEqual([
      ["high", "Confiance élevée", "90 % · déclaré par la source"],
      ["medium", "Confiance moyenne", "70 % · déduit par LEKA"],
      ["low", "Confiance faible", "30 %"],
      ["unknown", "Confiance inconnue", null],
      ["high", "Élevée", null],
    ]);
  });

  it("says, under its panel, what it rests on and what is still missing", () => {
    show(
      <ConfidencePanel
        score={0.83}
        support={[
          { id: "s", label: "2 sources lues", established: true },
          { id: "m", label: "Manque : ce qu'il touche", established: false },
        ]}
      />,
    );
    const panel = screen.getByRole("region", { name: "Confiance de l'analyse" });
    expect(within(panel).getByTestId("confidence")).toHaveTextContent("Moyenne");
    expect(within(panel).getByTestId("confidence-score")).toHaveTextContent(
      "Score de confiance : 83 %",
    );
    const lines = within(panel).getAllByRole("listitem");
    expect(lines.map((line) => [line.textContent, line.dataset.established])).toEqual([
      ["2 sources lues", "true"],
      ["Manque : ce qu'il touche", "false"],
    ]);
  });

  it("says when nothing says what it rests on", () => {
    show(<ConfidencePanel score={null} />);
    expect(screen.getByText("Rien ne dit encore sur quoi elle repose.")).toBeInTheDocument();
    expect(screen.getByTestId("confidence")).toHaveTextContent("Inconnue");
    // No score made up.
    expect(screen.queryByTestId("confidence-score")).not.toBeInTheDocument();
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
  it("says what it is, where from and when, and opens on what it holds and where to see it", async () => {
    const user = userEvent.setup();
    show(<EvidenceList items={[RECORD]} />);

    const item = screen.getByTestId("evidence-item");
    expect(item).toHaveTextContent("OPS-1841");
    expect(item).toHaveTextContent("OPS board · l'enregistrement de l'incident");
    // Its tool's own page, outside LEKA: a new tab.
    const see = within(item).getByRole("link", { name: "Voir OPS-1841" });
    expect(see).toHaveAttribute("href", RECORD.href);
    expect(see).toHaveAttribute("target", "_blank");

    expect(screen.queryByTestId("evidence-detail")).not.toBeInTheDocument();
    const details = within(item).getByRole("button", { name: "Détails de la preuve OPS-1841" });
    await user.click(details);
    expect(details).toHaveAttribute("aria-expanded", "true");
    const detail = screen.getByTestId("evidence-detail");
    expect(detail).toHaveTextContent("NatureEnregistrement d'une source");
    expect(detail).toHaveTextContent("SourceOPS board");
    expect(detail).toHaveTextContent("CléOPS-1841");
  });

  it("shows the first few, and all of them on asking", async () => {
    const user = userEvent.setup();
    show(<EvidenceList items={["1", "2", "3", "4", "5", "6"].map(piece)} max={5} />);
    expect(screen.getAllByTestId("evidence-item")).toHaveLength(5);
    await user.click(screen.getByRole("button", { name: "Voir toutes les preuves (6)" }));
    expect(screen.getAllByTestId("evidence-item")).toHaveLength(6);
    // Inside LEKA: the same tab.
    expect(screen.getByRole("link", { name: "Voir Preuve 6" })).not.toHaveAttribute("target");
  });

  it("lines up what justifies a recommendation, then lists them all", async () => {
    const user = userEvent.setup();
    show(<EvidenceStrip title="Éléments" items={["1", "2", "3", "4"].map(piece)} />);
    const strip = screen.getByTestId("evidence-strip");
    expect(strip).toHaveTextContent("Preuve 3");
    expect(strip).not.toHaveTextContent("Preuve 4");
    await user.click(screen.getByRole("button", { name: "Voir toutes les preuves (4)" }));
    expect(screen.getAllByTestId("evidence-item")).toHaveLength(4);
  });

  it("says when there is none", () => {
    show(<EvidenceList items={[]} />);
    expect(screen.getByText("Aucune preuve.")).toBeInTheDocument();
  });

  it("is gathered once each for the whole analysis", () => {
    const analysis: Analysis = {
      status: "complete",
      missing: [],
      findings: [{ id: "f", statement: "s", evidence: [RECORD, piece("1")] }],
      causes: [
        { id: "c", label: "c", confidence: 0.8, basis: "stated", why: "w", evidence: [RECORD] },
      ],
      impact: null,
      recommendations: [],
      uncertainties: [],
      confidence: 0.8,
    };
    expect(evidenceOf(analysis).map((item) => item.id)).toEqual(["r", "1"]);
  });
});

describe("findings and probable causes", () => {
  it("say what they are about, and open on their evidence in place", async () => {
    const user = userEvent.setup();
    show(
      <FindingList
        findings={[{ id: "f", title: "État et gravité", statement: "OPS-1841 : clos.", evidence: [RECORD] }]}
      />,
    );
    const finding = screen.getByTestId("finding");
    expect(finding).toHaveTextContent("État et gravité");
    expect(finding).toHaveTextContent("OPS-1841 : clos.");
    await user.click(within(finding).getByRole("button", { name: /Voir les éléments \(1\)/ }));
    expect(within(finding).getByTestId("evidence")).toHaveTextContent("OPS-1841");
  });

  it("are opened, not scrolled through, when there are many", async () => {
    const user = userEvent.setup();
    const findings = Array.from({ length: 6 }, (_, i) => ({
      id: `f${i}`,
      title: null,
      statement: `Constat ${i + 1}`,
      evidence: [],
    }));
    show(<FindingList findings={findings} max={4} />);
    expect(screen.getAllByTestId("finding")).toHaveLength(4);
    await user.click(screen.getByTestId("findings-all"));
    expect(screen.getByTestId("findings-all")).toHaveTextContent("Voir moins");
    expect(screen.getAllByTestId("finding")).toHaveLength(6);
  });

  it("are ordered, sure to a degree, say why, and open on their evidence", async () => {
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
    expect(screen.getByRole("list").tagName).toBe("OL");
    const [first, second] = screen.getAllByTestId("probable-cause");
    expect(confidence(within(first).getByTestId("confidence"))).toEqual([
      "medium",
      "Confiance moyenne",
      "83 % · déclaré par la source",
    ]);
    expect(first).toHaveTextContent("Déploiement · Pourquoi : Une source le déclare.");
    expect(within(first).getByRole("link", { name: "payment-api v2.8.4" })).toBeInTheDocument();
    expect(second).toHaveTextContent("déduit par LEKA");
    // Nothing to open, no button.
    expect(within(second).queryByRole("button")).not.toBeInTheDocument();
    await user.click(within(first).getByRole("button", { name: /Voir les éléments/ }));
    expect(within(first).getByTestId("evidence")).toHaveTextContent("OPS-1841");
  });
});

describe("impact", () => {
  it("says its level in words, what it is read from, and what it concerns, area by area", () => {
    show(
      <ImpactPanel
        impact={{
          areas: [
            {
              id: "affected",
              label: "Touché",
              items: [
                {
                  id: "p",
                  label: "payment-api",
                  href: "/environment/services/p",
                  type: "service",
                  detail: "Service",
                },
              ],
            },
            { id: "dependents", label: "Qui en dépend", items: [] },
          ],
          risk: "medium",
          riskBasis: "d'après la gravité déclarée (sev2)",
        }}
      />,
    );
    const impact = screen.getByTestId("impact");
    expect(screen.getByTestId("impact-level")).toHaveTextContent("Moyen");
    expect(impact).toHaveTextContent(
      "1 élément concerné · d'après la gravité déclarée (sev2)",
    );
    const touched = screen.getByRole("list", { name: "Touché" });
    expect(within(touched).getByRole("link")).toHaveAttribute("href", "/environment/services/p");
    expect(touched).toHaveTextContent("payment-apiService");
    // An empty area is not drawn.
    expect(impact).not.toHaveTextContent("Qui en dépend");
  });

  it("never says low for unknown", () => {
    show(
      <>
        <ImpactPanel impact={{ areas: [], risk: "unknown", riskBasis: "aucune gravité" }} />
        <RiskBadge level="unknown" />
      </>,
    );
    expect(screen.getByTestId("impact-level")).toHaveTextContent("Inconnu");
    expect(screen.getByTestId("risk")).toHaveTextContent("Risque inconnu");
  });
});

describe("a recommendation", () => {
  it("says what it touches, how long, whether it can be undone, how risky, how sure — and what justifies it", async () => {
    const user = userEvent.setup();
    show(
      <RecommendationCard
        recommendation={{
          id: "r",
          title: "Revenir à v2.8.3",
          rationale: "La latence a commencé avec 2.8.4.",
          effect: "3 services concernés",
          effort: "≈ 15 min",
          action: "rollback",
          priority: "high",
          risk: "medium",
          reversible: false,
          confidence: 0.82,
          evidence: [RECORD],
        }}
      />,
    );
    const card = screen.getByRole("article", { name: "Revenir à v2.8.3" });
    expect(card).toHaveTextContent("La latence a commencé avec 2.8.4.");
    const chips = within(card).getByRole("list", { name: "Ce qu'elle implique" });
    expect(within(chips).getAllByRole("listitem").map((chip) => chip.textContent)).toEqual([
      "Impact : 3 services concernés",
      "≈ 15 min",
      "Irréversible",
      "Risque moyen",
      "Confiance moyenne82 %",
    ]);
    expect(screen.queryByTestId("evidence-strip")).not.toBeInTheDocument();
    await user.click(
      within(card).getByRole("button", { name: "Voir ce qui justifie « Revenir à v2.8.3 »" }),
    );
    expect(screen.getByTestId("evidence-strip")).toHaveTextContent(
      "Éléments qui justifient cette recommandation",
    );
    expect(screen.getByTestId("evidence-strip")).toHaveTextContent("OPS-1841");
  });

  it("says that nothing runs without a yes", () => {
    show(<ControlNotice />);
    expect(screen.getByRole("note")).toHaveTextContent("Vous gardez le contrôle");
    expect(screen.getByRole("note")).toHaveTextContent("sans votre validation explicite");
  });
});

describe("how an analysis went", () => {
  it("says running, partial and what is missing, inconclusive, failed — retried — or none yet", async () => {
    const retry = vi.fn();
    const user = userEvent.setup();
    show(
      <>
        <AnalysisState status="running" />
        <AnalysisState status="partial" missing={["ce qui l'a causé"]} />
        <AnalysisState status="inconclusive" missing={["rien à lire", "rien à lire"]} />
        <AnalysisState status="failed" onRetry={retry} />
        <AnalysisState status="pending" />
        <AnalysisState status="complete" />
      </>,
    );
    const states = screen.getAllByTestId("analysis-state");
    expect(states.map((s) => s.getAttribute("data-status"))).toEqual([
      "running",
      "partial",
      "inconclusive",
      "failed",
      "pending",
    ]);
    expect(states[0]).toHaveTextContent("Analyse en cours…");
    expect(states[1]).toHaveTextContent("Analyse partielle");
    expect(states[1]).toHaveTextContent("ce qui l'a causé");
    expect(states[2]).toHaveTextContent("Analyse non concluante");
    // Two capabilities lacking the same thing: said once.
    expect(within(states[2]).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("L'analyse a échoué");
    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(states[4]).toHaveTextContent("Pas encore d'analyse");
  });

  const PARTIAL: Analysis = {
    status: "partial",
    summary: "OPS-1841 : clos, sev2. Sa cause n'est pas connue.",
    support: [{ id: "s", label: "1 source lue", established: true }],
    missing: ["ce qu'il touche"],
    findings: [{ id: "f", statement: "OPS-1841 : clos, sev2.", evidence: [RECORD] }],
    causes: [],
    impact: null,
    recommendations: [],
    uncertainties: ["Aucune source ne dit ce qui l'a causé."],
    confidence: null,
  };

  const ORDER = /^(analysis-state|analysis-summary|intelligence-\w+|uncertainties)$/;

  it("draws an analysis in its one order: what it comes to first, what it does not know last", () => {
    show(<AnalysisView analysis={PARTIAL} />);

    expect(screen.getAllByTestId(ORDER).map((node) => node.dataset.testid)).toEqual([
      "analysis-state",
      "analysis-summary",
      "intelligence-fact",
      "intelligence-hypothesis",
      "intelligence-evidence",
      "intelligence-impact",
      "intelligence-proposal",
      "uncertainties",
    ]);
    const summary = screen.getByTestId("analysis-summary");
    expect(summary).toHaveTextContent("Synthèse de l'analyse");
    expect(summary).toHaveTextContent("Sa cause n'est pas connue.");
    expect(summary).toHaveTextContent("Confiance inconnue");
    expect(summary).toHaveTextContent("1 source lue");
    expect(screen.getByText("Aucune cause n'est déclarée ni soupçonnée.")).toBeInTheDocument();
    expect(screen.getByTestId("intelligence-evidence")).toHaveTextContent("1 preuve");
    expect(screen.getByTestId("intelligence-proposal")).toHaveTextContent(
      "LEKA ne propose pas encore de recommandation",
    );
    expect(screen.getByTestId("uncertainties")).toHaveTextContent("Ce que LEKA ne sait pas (1)");
  });

  it("puts its confidence at the head of the right side where the screen says what it comes to", () => {
    show(<AnalysisView analysis={PARTIAL} synthesis={false} />);
    expect(screen.queryByTestId("analysis-summary")).not.toBeInTheDocument();
    expect(screen.getAllByTestId(ORDER).map((node) => node.dataset.testid)).toEqual([
      "analysis-state",
      "intelligence-fact",
      "intelligence-hypothesis",
      "intelligence-evidence",
      "intelligence-confidence",
      "intelligence-impact",
      "intelligence-proposal",
      "uncertainties",
    ]);
  });

  it("draws nothing it did not find when it failed", () => {
    show(<AnalysisView analysis={{ ...PARTIAL, status: "failed" }} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("analysis-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("intelligence-fact")).not.toBeInTheDocument();
  });
});
