/**
 * An intention's analysis (LEKA-388), read as the screens show an analysis
 * (lib/intelligence.ts, LEKA-341): what LEKA's capabilities found in its
 * assembled context, put in the shapes the intelligence components draw —
 * nothing added that the API did not say.
 *
 *     findings      what each capability states, worded from its code and
 *                   values, titled by the capability that said it
 *     causes        what may explain it — a source's word, or LEKA's
 *                   inference and its rule — the surest first
 *     impact        what it reaches, area by area, and the risk with what
 *                   it is read from
 *     uncertainties what LEKA does not know, said as such
 *     missing       what did not finish: a capability failed, timed out
 *     summary       each capability's one sentence
 *     support       what the confidence rests on: its context's sources,
 *                   their contradictions, its readiness
 *
 *     recommendations what LEKA proposes (LEKA-389) — apart from what it
 *                   found, each worded from its code, why (the finding it
 *                   follows from), how risky, reversible, urgent, sure, and
 *                   the evidence it rests on; one that changes systems
 *                   says it needs approval (LEKA-390)
 *
 * WORDS. The API says each sentence in English, with its code and values;
 * the interface words it in its own language from those, and falls back
 * to the API's sentence for a code it does not know.
 */

import type { components } from "@/lib/api-types";
import { fill } from "@/lib/i18n/dictionaries";
import type { Dictionary } from "@/lib/i18n/dictionaries";
import type {
  Analysis,
  AnalysisStatus,
  CauseStrength,
  ConfidenceLevel,
  EvidenceRef,
  Explanation,
  Finding,
  Impact,
  ProbableCause,
  Recommendation,
  RiskLevel,
  SourceState,
  Support,
} from "@/lib/intelligence";

export type IntentionAnalysis = components["schemas"]["IntentionAnalysisRead"];
export type AnalysisResult = components["schemas"]["IntentionAnalysisResult"];
export type AnalysisEvidence = components["schemas"]["AnalysisEvidence"];
export type AnalysisRecommendation =
  components["schemas"]["AnalysisRecommendation"];
type ApiExplanation = components["schemas"]["AnalysisExplanation"];
type Note = components["schemas"]["AnalysisNote"];
type Params = Record<string, unknown>;

export interface Links {
  /** Where a thing of the company model is seen whole. */
  href: (entity: { id: string; type: string }) => string;
  /** What kind of thing it is, in words. */
  typeName: (type: string) => string;
  /** A moment, in words: "8 oct. 2026, 14:02". */
  date: (iso: string) => string;
  /** What LEKA concluded, in words, as Insights says it — from its code
   * and values, its English statement as a fallback. */
  finding?: (
    code: string,
    params: Record<string, unknown>,
    statement: string,
  ) => { title: string; detail?: string | null };
}

/** What evidence of the company model can be opened in LEKA. */
const OPENABLE = new Set(["entity", "event"]);

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join(", ");
  return String(value);
}

function percent(value: unknown): string {
  return typeof value === "number" ? String(Math.round(value * 100)) : "";
}

/** A capability's name, in words. */
export function capabilityName(t: Dictionary, name: string): string {
  return (
    (t.intentions.analysis.capabilities as Record<string, string>)[name] ?? name
  );
}

/** The values a sentence's template reads: lists joined, codes worded,
 * what is optional said only when there. */
function values(t: Dictionary, code: string, params: Params, links: Links) {
  const w = t.intentions.analysis;
  const words = (map: Record<string, string>, key: unknown) =>
    map[String(key)] ?? text(key);
  const said: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(params)) said[key] = text(value);
  const p = params;
  switch (code) {
    case "standing.state":
      said.type = links.typeName(text(p.type));
      said.lifecycle = words(w.lifecycles, p.lifecycle ?? "known");
      said.status = p.status ? `, ${text(p.status)}` : "";
      said.criticality = p.criticality
        ? fill(w.parts.criticality, { level: text(p.criticality) })
        : "";
      break;
    case "standing.inactive":
      said.lifecycle = words(w.lifecycles, p.lifecycle);
      break;
    case "standing.quality":
      said.level = words(w.levels, p.level);
      said.score = percent(p.score);
      break;
    case "incident.seen":
      said.on = text(p.on) || w.parts.it;
      said.severity = p.severity ? `, ${text(p.severity)}` : "";
      said.state = p.state ? `, ${text(p.state)}` : "";
      break;
    case "recommend.why.cause":
      said.basis = words(w.recommendBasis, p.basis);
      break;
    case "recommend.why.suspected":
      said.confidence = percent(p.confidence);
      break;
    case "recommend.why.impact":
      said.risk = words(w.recommendRisks, p.risk);
      break;
    case "incident.summary":
      said.cause = p.cause
        ? fill(w.parts.likeliest, { cause: text(p.cause) })
        : "";
      break;
    case "change.made":
      said.kind = words(w.changeKinds, p.kind);
      said.at = typeof p.at === "string" ? links.date(p.at) : "";
      said.environment = p.environment
        ? fill(w.parts.inEnvironment, { environment: text(p.environment) })
        : "";
      said.incidents = p.incidents
        ? fill(w.parts.followed, { count: text(p.incidents) })
        : "";
      break;
    case "change.summary":
      said.followed = p.followed
        ? fill(w.parts.followedSome, { count: text(p.followed) })
        : "";
      break;
    case "learned.summary":
      // What moved, counted in the interface's words — never the API's English.
      said.details = Object.entries(w.learned)
        .filter(([change]) => Number(p[change]) > 0)
        .map(([change, words]) => fill(words, { count: text(p[change]) }))
        .join(", ");
      break;
    case "learned.appeared":
    case "learned.changed":
    case "learned.went":
    case "learned.came_back":
      said.type = links.typeName(text(p.type));
      said.at = typeof p.at === "string" ? links.date(p.at) : "";
      said.fields = Array.isArray(p.fields) && p.fields.length
        ? fill(w.learnedFields, { fields: p.fields.map(text).join(", ") })
        : "";
      break;
    case "dependency.risk":
      said.critical = p.critical ? w.parts.someCritical : "";
      said.business = p.business
        ? fill(w.parts.business, { count: text(p.business) })
        : "";
      break;
    case "compliance.check":
      said.check = words(w.checks, p.check);
      said.passed = p.passed ? w.parts.yes : w.parts.no;
      break;
    case "action.asked":
      said.action = words(t.intentions.understanding.actionNames, p.action);
      said.on = text(p.on) || w.parts.something;
      break;
    case "action.summary":
      said.actions = ((p.actions as unknown[]) ?? [])
        .map((a) => words(t.intentions.understanding.actionNames, a))
        .join(", ");
      break;
    case "action.last_deployment":
      said.at = typeof p.at === "string" ? links.date(p.at) : "";
      break;
    case "action.constraint":
      said.kind = words(t.intentions.understanding.scope.kinds, p.kind);
      said.value =
        p.value !== null && p.value !== undefined && p.value !== true
          ? ` (${text(p.value)})`
          : "";
      break;
    case "support.context":
      said.readiness = words(w.readiness, p.readiness);
      said.level = words(w.levels, p.level ?? "unknown");
      break;
    case "capability.failed":
    case "capability.timed_out":
    case "capability.skipped":
      said.capability = capabilityName(t, text(p.capability));
      break;
    case "confidence.capability_failed":
    case "why.partial":
      said.capabilities = ((p.capabilities as unknown[]) ?? [])
        .map((name) => capabilityName(t, text(name)))
        .join(", ");
      break;
  }
  return said;
}

/** A sentence of the analysis, in the interface's words — the API's own
 * for a code it does not know. */
export function noteSaid(
  t: Dictionary,
  note: { code: string; text: string; params?: Params },
  links: Links,
): string {
  const templates = t.intentions.analysis.said as Record<string, string>;
  let code = note.code;
  const params = note.params ?? {};
  // One code, two sentences: where it moves to, said or missing.
  if (code === "migration.summary" && !params.target)
    code = "migration.summary_missing";
  const template = templates[code];
  return template ? fill(template, values(t, code, params, links)) : note.text;
}

/** Why LEKA recommends it, in words: the finding or the uncertainty it
 * follows from, said as the analysis says it — or its own why. */
function recommendationWhy(
  t: Dictionary,
  item: AnalysisRecommendation,
  links: Links,
): string {
  const params = (item.why.params ?? {}) as Params;
  const of = typeof params.of === "string" ? params.of : null;
  const templates = t.intentions.analysis.said as Record<string, string>;
  if (of && templates[of])
    return noteSaid(t, { code: of, text: item.why.text, params }, links);
  return noteSaid(t, item.why, links);
}

/** Why a cause is one, in words: its source said so, or LEKA's rule. */
function causeWhy(
  t: Dictionary,
  cause: AnalysisResult["causes"][number],
  links: Links,
): string {
  return noteSaid(
    t,
    { code: cause.code, text: cause.why, params: cause.params },
    links,
  );
}

/** A piece of evidence, as the evidence components draw it. */
export function evidenceRef(
  t: Dictionary,
  item: AnalysisEvidence,
  links: Links,
  citedBy: readonly string[] = [],
): EvidenceRef {
  const w = t.intentions.analysis.evidence;
  const params = (item.params ?? {}) as Record<string, unknown>;
  const verb = item.ref_type
    ? ((t.knowledge.relationships as Record<string, string>)[item.ref_type] ??
      item.ref_type.replace(/_/g, " "))
    : "";
  const tie = item.id.startsWith("tie:") && params.from && params.to;
  const concluded =
    item.ref_type === "finding" &&
    links.finding &&
    typeof params.code === "string"
      ? links.finding(
          params.code,
          (params.params ?? {}) as Record<string, unknown>,
          item.label,
        )
      : null;
  const label = tie
    ? `${text(params.from)} ${verb} ${text(params.to)}`
    : (concluded?.title ?? item.label);
  const [first, ...others] = item.sources;
  const facts: { label: string; value: string }[] = [];
  if (item.origin) {
    facts.push({
      label: w.origin,
      value: (w.origins as Record<string, string>)[item.origin] ?? item.origin,
    });
  }
  if (item.confidence !== null && item.confidence !== undefined) {
    facts.push({ label: w.confidence, value: `${percent(item.confidence)} %` });
  }
  if (item.records.length)
    facts.push({ label: w.records, value: item.records.join(", ") });
  if (others.length) {
    facts.push({
      label: w.alsoFrom,
      value: others.map((s) => s.name ?? w.gone).join(", "),
    });
  }
  if (first && first.name === null)
    facts.push({ label: w.source, value: w.gone });
  if (citedBy.length) {
    facts.push({
      label: w.citedBy,
      value: citedBy.map((c) => capabilityName(t, c)).join(", "),
    });
  }
  const typed = item.ref_type && !tie ? links.typeName(item.ref_type) : null;
  const happened = item.detail
    ? ((w.details as Record<string, string>)[item.detail] ?? item.detail)
    : null;
  const detail =
    item.kind === "entity"
      ? typed
      : item.kind === "event"
        ? [typed, happened].filter(Boolean).join(" · ")
        : item.ref_type === "finding"
          ? (concluded?.detail ?? null)
          : null;
  return {
    id: item.id,
    label,
    kind: item.kind,
    source: first ? { kind: first.kind, name: first.name } : null,
    detail: detail || null,
    at: item.at ?? null,
    href:
      OPENABLE.has(item.kind) && item.ref_id && item.ref_type
        ? links.href({ id: item.ref_id, type: item.ref_type })
        : null,
    facts,
  };
}

/** Which capabilities cite each piece of evidence. */
function citations(result: AnalysisResult): Map<string, string[]> {
  const cited = new Map<string, string[]>();
  for (const statement of [...result.findings, ...result.causes]) {
    for (const id of statement.evidence) {
      const by = cited.get(id) ?? [];
      if (!by.includes(statement.capability)) by.push(statement.capability);
      cited.set(id, by);
    }
  }
  return cited;
}

/** Every piece of evidence the analysis collected, as the Preuves tab
 * lists them: in the order it was collected, each with who cites it. */
export function analysisEvidence(
  t: Dictionary,
  result: AnalysisResult,
  links: Links,
): EvidenceRef[] {
  const cited = citations(result);
  return result.evidence.map((item) =>
    evidenceRef(t, item, links, cited.get(item.id) ?? []),
  );
}

const STATUSES: Record<IntentionAnalysis["status"], AnalysisStatus> = {
  running: "running",
  complete: "complete",
  partial: "partial",
  inconclusive: "inconclusive",
  failed: "failed",
  // Not run: the tab says why, from its context's readiness.
  blocked: "pending",
  // Stopped by a person (LEKA-443): what it found, short of the whole.
  stopped: "partial",
};

/** A precondition, in words: met or not, as the analysis says it. */
function preconditionSaid(
  t: Dictionary,
  item: NonNullable<AnalysisRecommendation["preconditions"]>[number],
): string {
  const words = (
    t.intentions.analysis.explanation.preconditions as Record<
      string,
      { met: string; unmet: string }
    >
  )[item.code];
  if (!words) return item.text;
  return fill(item.met === true ? words.met : words.unmet, {
    version: text(item.params?.version),
    environment: text(item.params?.environment),
  });
}

/** On what it rests (LEKA-441), in the interface's words: what LEKA
 * understood, each source it read and in what state, what did not answer,
 * how sure and why, what disagrees, what is stale, what next and why. */
function explanationOf(
  t: Dictionary,
  analysis: IntentionAnalysis,
  explained: ApiExplanation,
  recommendations: readonly Recommendation[],
  apiRecommendations: readonly AnalysisRecommendation[],
  links: Links,
): Explanation {
  const w = t.intentions.analysis.explanation;
  const say = (note: Note) => noteSaid(t, note, links);
  const p = (explained.understood.params ?? {}) as Params;
  const list = (value: unknown) => (Array.isArray(value) ? value.map(text) : []);
  const goals = t.intentions.understanding.goals as Record<string, string>;
  const understood = [
    goals[text(p.goal)] ?? text(p.goal),
    list(p.names).length ? fill(w.understood.about, { names: list(p.names).join(", ") }) : null,
    list(p.unknown).length && !list(p.names).length
      ? fill(w.understood.unknown, { names: list(p.unknown).join(", ") })
      : null,
    p.environment ? fill(w.understood.environment, { environment: text(p.environment) }) : null,
    list(p.excluded).length
      ? fill(w.understood.except, { names: list(p.excluded).join(", ") })
      : null,
    p.period_said && typeof p.since === "string"
      ? fill(w.understood.since, { since: links.date(p.since) })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const consulted = explained.consulted.map((source) => {
    const at = source.last_synced_at ? links.date(source.last_synced_at) : null;
    const states = w.states as Record<string, string>;
    return {
      id: source.source_id,
      name: source.name ?? source.kind ?? t.intelligence.context.deletedSource,
      kind: source.kind,
      state: source.state as SourceState,
      said: fill(states[source.state] ?? source.said, {
        at:
          source.state === "read" || source.state === "stale"
            ? (at ?? w.states.never)
            : at
              ? fill(w.states.lastAt, { at })
              : "",
      }),
      elements: source.elements,
    };
  });
  const silent = explained.capabilities
    .filter((c) => c.status !== "succeeded" && c.leaves)
    .map((c) => ({
      id: c.name,
      name: capabilityName(t, c.name),
      leaves: say(c.leaves as Note),
    }));
  const conflicts = explained.conflicts.map((conflict) => ({
    id: conflict.id,
    label: `${conflict.label} · ${conflict.about}`,
    values: conflict.values.map((side) => ({
      value: text(side.value),
      by: list(side.by),
    })),
  }));
  const conflictSaid = (id: unknown) => {
    const found = conflicts.find((c) => c.id === text(id));
    return found
      ? `${found.label} — ${found.values.map((v) => `${v.value} (${v.by.join(", ")})`).join(" ≠ ")}`
      : "";
  };
  const next = explained.next;
  const np = (next.params ?? {}) as Params;
  const index = apiRecommendations.findIndex((r) => r.id === text(np.recommendation));
  const title = index >= 0 ? recommendations[index].title : "";
  const nexts = w.next as Record<string, string>;
  const nextTitle =
    next.code === "rerun" && list(np.sources).length
      ? fill(w.next.rerunSources, { sources: list(np.sources).join(", ") })
      : fill(nexts[next.code] ?? next.text, {
          title,
          conflict: conflictSaid(np.conflict),
          sources: list(np.sources).join(", "),
        });
  const why = (() => {
    const wp = (next.why.params ?? {}) as Params;
    if (next.why.code === "why.recommendation" && index >= 0)
      return recommendations[index].rationale;
    if (next.why.code === "why.preconditions" && index >= 0)
      return (apiRecommendations[index].preconditions ?? [])
        .filter((pre) => pre.blocking && pre.met === false)
        .map((pre) => preconditionSaid(t, pre))
        .join(" ");
    if (next.why.code === "why.conflict" || next.why.code === "why.conflict_asked")
      return conflictSaid(wp.conflict) || next.why.text;
    return say(next.why);
  })();
  return {
    understood: understood || say(explained.understood),
    consulted,
    silent,
    confidence: {
      level: explained.confidence.level as ConfidenceLevel,
      reasons: explained.confidence.reasons.map((reason) => ({
        id: reason.code,
        effect: reason.effect,
        label: say(reason),
      })),
    },
    conflicts,
    stale: explained.stale.map(say),
    limits: explained.limits.filter((n) => !n.code.startsWith("limit.capability.")).map(say),
    unread: explained.limits.some((n) => n.code === "limit.source_unread"),
    next: { code: next.code, title: nextTitle, why },
    freshness: { read: analysis.context_version, now: analysis.context_now ?? null },
  };
}

/** The figures it may say, in words — each with what it counts and what it
 * was counted from (LEKA-441). */
function claimsOf(
  t: Dictionary,
  explained: ApiExplanation,
  result: AnalysisResult,
  evidence: Map<string, EvidenceRef>,
): Support[] {
  const w = t.intentions.analysis.explanation;
  const sources = new Map(explained.consulted.map((s) => [s.source_id, s.name ?? s.kind ?? ""]));
  const causes = new Map(result.causes.map((c) => [c.ref_id ?? c.id, c.label]));
  const conflicts = new Map(explained.conflicts.map((c) => [c.id, `${c.label} · ${c.about}`]));
  return explained.claims.map((claim) => {
    const label =
      claim.code === "contradictions" && claim.count === 0
        ? w.claims.noContradiction
        : fill((w.claims as Record<string, string>)[claim.code], { count: claim.count });
    const refs = claim.refs.map((id) => ({
      id,
      label:
        sources.get(id) ??
        causes.get(id) ??
        conflicts.get(id) ??
        evidence.get(id)?.label ??
        id,
      href: evidence.get(id)?.href ?? null,
    }));
    return {
      id: claim.code,
      label,
      established: claim.holds,
      definition: (w.definitions as Record<string, string>)[claim.code] ?? claim.definition,
      refs,
    };
  });
}

export function intentionAnalysis(
  t: Dictionary,
  analysis: IntentionAnalysis,
  links: Links,
): Analysis {
  const result = analysis.result;
  const status = STATUSES[analysis.status];
  if (!result) {
    return {
      status,
      missing: [],
      findings: [],
      causes: [],
      impact: null,
      recommendations: [],
      uncertainties: [],
      confidence: null,
    };
  }
  const say = (note: Note) => noteSaid(t, note, links);
  const cited = citations(result);
  const evidence = new Map(
    result.evidence.map((item) => [
      item.id,
      evidenceRef(t, item, links, cited.get(item.id) ?? []),
    ]),
  );
  const refs = (ids: readonly string[]) =>
    ids
      .map((id) => evidence.get(id))
      .filter((item): item is EvidenceRef => Boolean(item));
  const findings = result.findings.map((statement): Finding => ({
    id: statement.id,
    title: capabilityName(t, statement.capability),
    statement: noteSaid(t, statement, links),
    evidence: refs(statement.evidence),
  }));
  // Two capabilities can reach the same cause — "changes" and "incidents"
  // both read a deployment its incident names: one cause, the surest
  // reading of it, its evidence put together.
  const sameCause = new Map<string, AnalysisResult["causes"][number]>();
  for (const cause of result.causes) {
    const seen = sameCause.get(cause.id);
    if (!seen) {
      sameCause.set(cause.id, cause);
      continue;
    }
    const surest =
      (cause.confidence ?? 0) > (seen.confidence ?? 0) ? cause : seen;
    sameCause.set(cause.id, {
      ...surest,
      evidence: [...new Set([...seen.evidence, ...cause.evidence])],
    });
  }
  const causes = [...sameCause.values()].map((cause): ProbableCause => ({
    id: cause.id,
    label: cause.label,
    kind: cause.ref_type ? links.typeName(cause.ref_type) : null,
    href:
      cause.ref_id && cause.ref_type
        ? links.href({ id: cause.ref_id, type: cause.ref_type })
        : null,
    confidence: cause.confidence,
    basis: cause.basis,
    strength: (cause.strength ?? null) as CauseStrength | null,
    why: causeWhy(t, cause, links),
    evidence: refs(cause.evidence),
  }));
  const areas = t.intentions.analysis.areas;
  const impact: Impact | null =
    result.impact.length || result.risk !== "unknown"
      ? {
          areas: result.impact.map((area) => ({
            id: area.code,
            label: areas[area.code],
            items: area.items.map((item) => ({
              id: item.ref_id,
              label: item.name,
              href: links.href({ id: item.ref_id, type: item.ref_type }),
              type: item.ref_type,
              detail: links.typeName(item.ref_type),
            })),
          })),
          risk: result.risk as RiskLevel,
          riskBasis: result.risk_basis ? say(result.risk_basis) : "",
        }
      : null;
  const recommendations = (result.recommendations ?? []).map(
    (item): Recommendation => ({
      id: item.id,
      title: noteSaid(t, item, links),
      rationale: recommendationWhy(t, item, links),
      effect: item.changes_systems ? t.intentions.analysis.systems : null,
      risk: item.risk as RiskLevel,
      reversible: item.reversible,
      priority: item.priority,
      action: item.action,
      confidence: item.confidence,
      evidence: refs(item.evidence),
      preconditions: (item.preconditions ?? []).map((pre) => ({
        id: pre.code,
        label: preconditionSaid(t, pre),
        met: pre.met,
        blocking: pre.blocking,
      })),
      assumptions: (item.assumptions ?? []).map(
        (id) => result.causes.find((c) => c.id === id)?.label ?? id,
      ),
      executable: item.executable ?? null,
    }),
  );
  const explained = result.explanation ?? null;
  return {
    status: STATUSES[result.status],
    summary: result.summary.length ? result.summary.map(say).join(" ") : null,
    missing: result.missing.map(say),
    findings,
    causes,
    impact,
    recommendations,
    uncertainties: result.uncertainties.map(say),
    confidence: result.confidence,
    // What the figures count, when the analysis says it (LEKA-441); the
    // older three lines otherwise.
    support: explained
      ? claimsOf(t, explained, result, evidence)
      : result.support.map((note) => ({
          id: note.code,
          label: say(note),
          established: note.params?.established === true,
        })),
    explanation: explained
      ? explanationOf(
          t,
          analysis,
          explained,
          recommendations,
          result.recommendations ?? [],
          links,
        )
      : null,
  };
}
