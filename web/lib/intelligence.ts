/**
 * What LEKA's reasoning produces, as the screens show it (LEKA-341): an
 * analysis — its findings, its probable causes, the evidence behind them,
 * what it reaches, what LEKA proposes, how sure it is and what it does not
 * know — whatever produced it. The components of components/intelligence/
 * draw these shapes; each screen maps what its API says onto them
 * (lib/incident-analysis.ts for an incident, the context tab for a
 * context). docs/frontend/intelligence-components.md says when to use each.
 *
 * FACTS, HYPOTHESES, PROPOSALS. A finding is what a source says or LEKA
 * observed; a probable cause is what LEKA thinks, and says how sure; a
 * recommendation is what LEKA proposes, and someone decides. The three are
 * kept apart in the types so that no screen can draw one as another.
 */

/** How an analysis went. */
export type AnalysisStatus =
  /** Everything it looked for, found. */
  | "complete"
  /** Still reading: what it found so far, and more to come (mockup 03). */
  | "running"
  /** Some of it: what is missing is said. */
  | "partial"
  /** It looked, and could not conclude. */
  | "inconclusive"
  /** It could not run. */
  | "failed"
  /** None yet. */
  | "pending";

export type ConfidenceLevel = "high" | "medium" | "low" | "unknown";
export type RiskLevel = "high" | "medium" | "low" | "unknown";
/** How soon a recommendation should be acted on: mockup 05's "Priorité haute". */
export type Priority = "high" | "medium" | "low";
/** What a recommendation does, for its icon: undo, change, watch, other. */
export type RecommendationAction = "rollback" | "change" | "monitor" | "other";

/** Where a piece of evidence comes from, and how it can be inspected. */
export interface EvidenceRef {
  id: string;
  /** What it is: "Déploiement payment-api v2.8.4", "Incident ouvert". */
  label: string;
  kind: "record" | "entity" | "event" | "inference";
  /** The tool it was read from — its kind for the logo, its name. */
  source?: { kind: string | null; name: string | null } | null;
  /** What it says, in a line. */
  detail?: string | null;
  /** When it happened, or was seen. */
  at?: string | null;
  /** Where it can be seen whole. */
  href?: string | null;
  /** What opening it shows: its key, its record, the rule. */
  facts?: readonly { label: string; value: string }[];
}

/** What a source says, or LEKA observed: a fact. */
export interface Finding {
  id: string;
  /** What it is about, in a few words: "Durée", "Ce qu'il touche". */
  title?: string | null;
  statement: string;
  evidence: readonly EvidenceRef[];
}

/** What LEKA thinks caused it: a hypothesis, and how sure. */
export interface ProbableCause {
  id: string;
  label: string;
  /** What kind of thing: "Déploiement", "Changement". */
  kind?: string | null;
  href?: string | null;
  confidence: number | null;
  /** A source said so, or LEKA inferred it. */
  basis: "stated" | "inferred";
  /** Why it is a cause: who said so, or the rule. */
  why: string;
  evidence: readonly EvidenceRef[];
}

/** What it reaches, area by area, and how bad that is. */
export interface Impact {
  areas: readonly {
    id: string;
    label: string;
    items: readonly {
      id: string;
      label: string;
      href?: string | null;
      /** Its type, for its icon: service, application… */
      type?: string | null;
      /** What it is, in words: "Service". */
      detail?: string | null;
    }[];
  }[];
  risk: RiskLevel;
  /** What the risk is read from: "d'après la gravité déclarée (sev2)". */
  riskBasis: string;
}

/** What LEKA proposes: a decision someone takes, never a fact. */
export interface Recommendation {
  id: string;
  title: string;
  rationale: string;
  /** What it would change, out loud before anyone approves it. */
  effect?: string | null;
  risk?: RiskLevel;
  reversible?: boolean | null;
  priority?: Priority | null;
  /** How long it takes, as said: "≈ 15 min". */
  effort?: string | null;
  action?: RecommendationAction | null;
  confidence: number | null;
  evidence: readonly EvidenceRef[];
}

/** What a confidence rests on, one line each (mockups 03 to 05: "12
 * sources concordantes", "0 contradiction détectée"): established, or
 * still missing. */
export interface Support {
  id: string;
  label: string;
  established: boolean;
}

/** An analysis, whole. */
export interface Analysis {
  status: AnalysisStatus;
  /** What it comes to, in a few sentences: mockup 04's "Synthèse". */
  summary?: string | null;
  /** What is missing, when partial or inconclusive; why, when failed. */
  missing: readonly string[];
  findings: readonly Finding[];
  causes: readonly ProbableCause[];
  impact: Impact | null;
  recommendations: readonly Recommendation[];
  /** What LEKA does not know, said as such. */
  uncertainties: readonly string[];
  /** How sure the analysis is as a whole; none when it cannot say. */
  confidence: number | null;
  /** What that confidence rests on. */
  support?: readonly Support[];
}

/** A confidence in words: high from 85 %, medium from 60 %, low below —
 * unknown when none was given. The thresholds are the enrichment's own: a
 * rule's evidence makes 0.6 to 0.8, a source's word 0.9 to 1. */
export function confidenceLevel(score: number | null | undefined): ConfidenceLevel {
  if (score === null || score === undefined || Number.isNaN(score)) return "unknown";
  if (score >= 0.85) return "high";
  if (score >= 0.6) return "medium";
  return "low";
}

/** A severity or priority, as a tool says it, read as a risk: sev1, P1,
 * critical, highest → high; sev2, P2, high, major → medium; sev3 to 5, P3
 * to P5, medium, low, minor → low; anything else, unknown. */
export function riskOf(said: string | null | undefined): RiskLevel {
  if (!said) return "unknown";
  const word = said.toLowerCase().replace(/[\s_-]/g, "");
  if (/^(sev0|sev1|p0|p1|critical|highest|urgent|blocker)$/.test(word)) return "high";
  if (/^(sev2|p2|high|major)$/.test(word)) return "medium";
  if (/^(sev[345]|p[345]|medium|low|lowest|minor|trivial)$/.test(word)) return "low";
  return "unknown";
}

/** How a probable cause is tagged (mockup 03: "Probable cause", "À
 * confirmer"): a source said it; LEKA thinks it, fairly sure; LEKA only
 * suspects it, and someone should check. */
export type CauseTag = "stated" | "probable" | "toConfirm";

export function causeTag(cause: Pick<ProbableCause, "basis" | "confidence">): CauseTag {
  if (cause.basis === "stated") return "stated";
  const level = confidenceLevel(cause.confidence);
  return level === "high" || level === "medium" ? "probable" : "toConfirm";
}

/** Every piece of evidence an analysis rests on, once each, in the order
 * its statements cite them: mockup 04's "Preuves et sources clés". */
export function evidenceOf(analysis: Analysis): EvidenceRef[] {
  const seen = new Map<string, EvidenceRef>();
  const cited = [
    ...analysis.findings.flatMap((finding) => finding.evidence),
    ...analysis.causes.flatMap((cause) => cause.evidence),
    ...analysis.recommendations.flatMap((recommendation) => recommendation.evidence),
  ];
  for (const item of cited) if (!seen.has(item.id)) seen.set(item.id, item);
  return [...seen.values()];
}
