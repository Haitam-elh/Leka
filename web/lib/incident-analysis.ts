/**
 * An incident, read as an analysis (LEKA-341): what the company model
 * knows of it (lib/incidents.ts, LEKA-367) put in the shapes LEKA's
 * intelligence outputs take (lib/intelligence.ts) — nothing added that the
 * model does not say.
 *
 *     findings      what its sources say: its state and how bad, how long
 *                   it lasted, what it touches — each with its evidence:
 *                   its records, its timeline
 *     causes        what is said or suspected to have caused it, the
 *                   surest first — a source's word, or LEKA's inference
 *                   and its rule — with what changed just before it
 *     impact        what it touches, what depends on that, the
 *                   applications and the business — the risk read from the
 *                   severity its tool gave, or unknown
 *     uncertainties what is only suspected, or not known at all
 *
 * No recommendation: the model proposes none; the analysis engine will
 * (LEKA-384). Complete when it knows a cause and what is touched; partial
 * when one is missing — and says which; inconclusive when it knows neither
 * and nothing changed before it.
 */

import { fill } from "@/lib/i18n/dictionaries";
import type { Dictionary } from "@/lib/i18n/dictionaries";
import type { IncidentDetail } from "@/lib/incidents";
import type { Analysis, EvidenceRef, Finding, ProbableCause } from "@/lib/intelligence";
import { riskOf } from "@/lib/intelligence";

type Brief = IncidentDetail["affects"][number];

export interface Links {
  /** Where an entity is seen whole. */
  href: (entity: Pick<Brief, "id" | "type">) => string;
  /** What kind of thing it is, in words. */
  typeName: (type: string) => string;
  /** A source by its id: its tool and its name — none when it is gone. */
  source?: (id: string) => { kind: string; name: string } | null;
}

export function incidentAnalysis(detail: IncidentDetail, t: Dictionary, links: Links): Analysis {
  const w = t.intelligence.incident;
  const records = sourceEvidence(detail, t, links);
  const timeline = detail.timeline.map(
    (step, index): EvidenceRef => ({
      id: `step-${index}`,
      label: (w.steps as Record<string, string>)[step.step] ?? step.step,
      kind: "event",
      detail: step.state ?? null,
      at: step.at,
      facts: [{ label: w.origin, value: step.origin === "source" ? w.bySource : w.byModel }],
    }),
  );
  const before = detail.changed_before.map(
    (event): EvidenceRef => ({
      id: `before-${event.entity.id}-${event.kind}`,
      label: `${eventName(event.kind, t)} · ${event.entity.name}`,
      kind: "event",
      detail: event.via ? fill(w.on, { name: event.via.name }) : null,
      at: event.at,
      href: links.href(event.entity),
    }),
  );

  const findings: Finding[] = [];
  const how = [
    detail.state ? ((w.states as Record<string, string>)[detail.state] ?? detail.state) : null,
    detail.severity ?? detail.priority ?? null,
  ].filter(Boolean);
  findings.push({
    id: "state",
    statement: how.length
      ? fill(w.findings.state, { name: detail.name, state: how.join(", ") })
      : fill(w.findings.unknownState, { name: detail.name }),
    evidence: records,
  });
  if (detail.duration_minutes !== null && detail.duration_minutes !== undefined) {
    findings.push({
      id: "duration",
      statement: fill(w.findings.duration, { duration: duration(detail.duration_minutes, t) }),
      evidence: timeline,
    });
  } else if (timeline.length > 0) {
    findings.push({ id: "timeline", statement: w.findings.timeline, evidence: timeline });
  }
  if (detail.affected.length > 0) {
    findings.push({
      id: "affects",
      statement: fill(w.findings.affects, {
        names: detail.affected.map((tie) => tie.entity.name).join(", "),
      }),
      evidence: detail.affected.map(
        (tie): EvidenceRef => ({
          id: `affects-${tie.entity.id}`,
          label: tie.entity.name,
          kind: tie.origin === "inferred" ? "inference" : "entity",
          detail: links.typeName(tie.entity.type),
          href: links.href(tie.entity),
          facts: [{ label: w.relation, value: why(tie, t) }],
        }),
      ),
    });
  }

  const causes: ProbableCause[] = [...detail.suspected_causes]
    .sort((a, b) => b.confidence - a.confidence)
    .map((tie) => ({
      id: tie.entity.id,
      label: tie.entity.name,
      kind: links.typeName(tie.entity.type),
      href: links.href(tie.entity),
      confidence: tie.confidence,
      basis: tie.origin === "inferred" ? "inferred" : "stated",
      why: why(tie, t),
      evidence: [
        ...detail.changed_before.flatMap((event, index) =>
          event.entity.id === tie.entity.id ? [before[index]] : [],
        ),
        ...(tie.origin === "inferred" ? [] : records),
      ],
    }));

  const impact = detail.impact;
  const risk =
    riskOf(detail.severity) !== "unknown" ? riskOf(detail.severity) : riskOf(detail.priority);
  const said = detail.severity ?? detail.priority;
  const area = (id: keyof typeof w.areas, items: readonly Brief[]) => ({
    id,
    label: w.areas[id],
    items: items.map((entity) => ({ id: entity.id, label: entity.name, href: links.href(entity) })),
  });

  const uncertainties: string[] = [];
  if (causes.length === 0) {
    uncertainties.push(w.uncertain.noCause);
  } else if (causes.every((cause) => cause.basis === "inferred")) {
    uncertainties.push(w.uncertain.suspected);
  }
  if (detail.affected.length === 0) uncertainties.push(w.uncertain.noAffected);
  if (!said) uncertainties.push(w.uncertain.noSeverity);
  const suspected = new Set(causes.map((cause) => cause.id));
  const unexplained = detail.changed_before.filter((event) => !suspected.has(event.entity.id));
  if (unexplained.length > 0) {
    uncertainties.push(fill(w.uncertain.changedBefore, { count: unexplained.length }));
  }

  const missing = [
    ...(causes.length === 0 ? [w.missing.cause] : []),
    ...(detail.affected.length === 0 ? [w.missing.affected] : []),
  ];
  const status =
    missing.length === 0
      ? "complete"
      : causes.length > 0 || detail.affected.length > 0 || before.length > 0
        ? "partial"
        : "inconclusive";

  return {
    status,
    missing,
    findings,
    causes,
    impact: {
      areas: [
        area("affected", impact.affected),
        area("dependents", impact.dependents),
        area("applications", impact.applications),
        area("capabilities", impact.capabilities.map((tie) => tie.entity)),
        area("processes", impact.processes.map((tie) => tie.entity)),
      ],
      risk,
      riskBasis: said ? fill(w.riskFrom, { said }) : w.riskUnknown,
    },
    recommendations: [],
    uncertainties,
    confidence:
      causes.length > 0 ? Math.max(...causes.map((cause) => cause.confidence ?? 0)) : null,
  };
}

/** A deployment, a change… in words. */
function eventName(kind: string, t: Dictionary): string {
  return (t.intelligence.incident.events as Record<string, string>)[kind] ?? kind;
}

/** Why a tie holds: a source said so, or a rule of LEKA's inferred it. */
function why(tie: IncidentDetail["affected"][number], t: Dictionary): string {
  const w = t.intelligence.incident;
  if (tie.origin !== "inferred") return w.stated;
  return (w.rules as Record<string, string>)[tie.rule] ?? fill(w.inferred, { rule: tie.rule });
}

/** The records the incident was read from: each source and its key there. */
function sourceEvidence(detail: IncidentDetail, t: Dictionary, links: Links): EvidenceRef[] {
  const sources = (detail.provenance as { sources?: unknown }).sources;
  if (!Array.isArray(sources)) return [];
  return sources.flatMap((said, index): EvidenceRef[] => {
    if (typeof said !== "object" || said === null) return [];
    // A provenance's kind is its key's — key, alias, derived — not its
    // tool's: the tool is the source's, named by its id.
    const { source_id: id, key } = said as { source_id?: unknown; key?: unknown };
    const known = typeof id === "string" ? (links.source?.(id) ?? null) : null;
    return [
      {
        id: `record-${index}`,
        label: typeof key === "string" ? key : detail.name,
        kind: "record",
        source: known ?? { kind: null, name: t.intelligence.evidence.unknownSource },
        detail: t.intelligence.incident.record,
        href: detail.url ?? null,
        facts: typeof key === "string" ? [{ label: t.intelligence.incident.key, value: key }] : [],
      },
    ];
  });
}

/** 95 → "1 h 35", 20 → "20 min", 3000 → "2 j 2 h". */
function duration(minutes: number, t: Dictionary): string {
  const w = t.intelligence.incident.units;
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  if (days > 0) return `${days} ${w.days}${hours ? ` ${hours} ${w.hours}` : ""}`;
  if (hours > 0) return `${hours} ${w.hours}${rest ? ` ${rest}` : ""}`;
  return `${rest} ${w.minutes}`;
}
