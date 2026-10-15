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
  /** How far it is shown (LEKA-441): its source confirms it; LEKA infers it,
   * probable; only time ties it — a correlation, never called a cause. */
  strength?: CauseStrength | null;
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
  /** What must hold first (LEKA-441): met, not met, or still to come. */
  preconditions?: readonly Precondition[];
  /** What it assumes: the causes it rests on that are not confirmed. */
  assumptions?: readonly string[];
  /** Whether it can be carried out as it stands; none when not said. */
  executable?: boolean | null;
}

export interface Precondition {
  id: string;
  label: string;
  met: boolean | null;
  /** Unmet, it cannot be carried out as it stands. */
  blocking: boolean;
}

/** What a confidence rests on, one line each (mockups 03 to 05: "12
 * sources concordantes", "0 contradiction détectée"): established, or
 * still missing. */
export interface Support {
  id: string;
  label: string;
  established: boolean;
  /** What the figure counts — a figure nothing defines is not said (LEKA-441). */
  definition?: string | null;
  /** What it was counted from, each openable when it can be. */
  refs?: readonly { id: string; label: string; href?: string | null }[];
}

export type CauseStrength = "confirmed" | "probable" | "correlated";

/** A source an analysis read from, and in what state it was then (LEKA-441):
 * never shown read when it was failing, syncing or out of date. */
export type SourceState =
  | "read"
  | "error"
  | "degraded"
  | "stale"
  | "syncing"
  | "disabled"
  | "gone";

/** On what an analysis rests (LEKA-441): what LEKA understood, what it read
 * and in what state, what did not answer and what that leaves unknown, how
 * sure it is and why, what disagrees, what is stale, its limits, what next. */
export interface Explanation {
  understood: string;
  consulted: readonly {
    id: string;
    name: string;
    kind: string | null;
    state: SourceState;
    said: string;
    elements: number;
  }[];
  /** The capabilities that did not answer, and what that leaves unknown. */
  silent: readonly { id: string; name: string; leaves: string }[];
  confidence: {
    level: ConfidenceLevel;
    reasons: readonly {
      id: string;
      effect: "base" | "raises" | "lowers" | "caps";
      label: string;
    }[];
  };
  conflicts: readonly {
    id: string;
    label: string;
    values: readonly { value: string; by: readonly string[] }[];
  }[];
  stale: readonly string[];
  limits: readonly string[];
  /** A source that may hold the answer is connected, never read (LEKA-448). */
  unread?: boolean;
  next: { code: string; title: string; why: string };
  /** The context version it read, and the one its intention is at now. */
  freshness?: { read: number | null; now: number | null } | null;
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
  /** On what it rests, said (LEKA-441); none for an analysis made before. */
  explanation?: Explanation | null;
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
export type CauseTag = "stated" | "probable" | "toConfirm" | "correlated";

export function causeTag(
  cause: Pick<ProbableCause, "basis" | "confidence" | "strength">,
): CauseTag {
  // Said by the API (LEKA-441): only time ties it — never called a cause.
  if (cause.strength === "correlated") return "correlated";
  if (cause.strength === "confirmed" || cause.basis === "stated") return "stated";
  if (cause.strength === "probable") return "probable";
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
