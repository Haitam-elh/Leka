"use client";

import { AlertOctagon, CheckCircle2, Database, Info } from "lucide-react";

import { qualityGapSaid } from "@/components/environment/context-quality";
import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import type { QualityGap } from "@/lib/context";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";

/**
 * Whether an intention's context can ground its analysis (LEKA-387): ready,
 * usable with reservations, or blocked — and by what — with what it holds
 * by side and how many sources say it. Every word is the API's readiness
 * (`intention.readiness`), read from the context's own quality, gaps and
 * conflicts (LEKA-372, 375); a gap is said as the context's quality panel
 * says it.
 */

export type Readiness = NonNullable<IntentionDetail["readiness"]>;
type Issue = Readiness["critical"][number];

const TONES: Record<Readiness["status"], TileTone> = {
  ready: "success",
  limited: "warning",
  blocked: "danger",
};
const FACETS = ["technical", "business", "organizational", "temporal"] as const;
const NO_NAMES: ReadonlyMap<string, string> = new Map();

function IssueSaid({ issue }: { issue: Issue }) {
  const t = useDictionary();
  if (issue.origin === "conflict") {
    return (
      <>
        {fill(t.intentions.readiness.conflict, {
          label: issue.label ?? "",
          about: issue.about ?? "",
        })}
      </>
    );
  }
  const gap = {
    kind: issue.kind,
    severity: issue.severity,
    origin: issue.gap_origin ?? "quality",
    said: issue.said,
    refs: issue.refs ?? [],
    detail: issue.detail ?? {},
  } as unknown as QualityGap;
  return <>{qualityGapSaid(t, gap, NO_NAMES)}</>;
}

export function ReadinessPanel({ readiness }: { readiness: Readiness }) {
  const t = useDictionary();
  const w = t.intentions.readiness;
  const Icon = readiness.status === "blocked" ? AlertOctagon : CheckCircle2;
  return (
    <Card title={w.title} icon={<Database className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="space-y-3 text-[0.8125rem]" data-testid="intention-readiness">
        <p className="flex flex-wrap items-center gap-2">
          <Pill tone={TONES[readiness.status]} data-testid="readiness-status" data-status={readiness.status}>
            <Icon className="size-3.5" aria-hidden="true" />
            {w.status[readiness.status]}
          </Pill>
          <span className="text-shell-muted">
            {fill(w.holds, {
              count: readiness.elements,
              sources: readiness.sources,
              version: readiness.version,
            })}
          </span>
        </p>
        <ul className="flex flex-wrap gap-1.5" data-testid="readiness-facets">
          {FACETS.map((facet) => (
            <li key={facet}>
              <Pill tone="neutral">
                {w.facets[facet]} · {readiness.facets[facet] ?? 0}
              </Pill>
            </li>
          ))}
        </ul>
        {readiness.critical.length ? (
          <div>
            <p className="font-semibold text-brand-navy">{w.critical}</p>
            <ul className="mt-1 space-y-1" data-testid="readiness-critical">
              {readiness.critical.map((issue, index) => (
                <li key={`${issue.kind}-${index}`} className="flex items-start gap-2 text-brand-navy">
                  <AlertOctagon className="mt-0.5 size-3.5 shrink-0 text-state-danger" aria-hidden="true" />
                  <span>
                    <IssueSaid issue={issue} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {readiness.warnings.length ? (
          <div>
            <p className="font-medium text-brand-navy">{w.warnings}</p>
            <ul className="mt-1 space-y-1 text-shell-muted" data-testid="readiness-warnings">
              {readiness.warnings.map((issue, index) => (
                <li key={`${issue.kind}-${index}`} className="flex items-start gap-2">
                  <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                  <span>
                    <IssueSaid issue={issue} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
