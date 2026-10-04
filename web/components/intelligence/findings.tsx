"use client";

import Link from "next/link";

import { ConfidenceBadge } from "@/components/intelligence/confidence";
import { EvidenceToggle } from "@/components/intelligence/evidence";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Finding, ProbableCause } from "@/lib/intelligence";

/**
 * What is known, and what is thought (LEKA-341). A finding is a fact — a
 * source said it, LEKA observed it — with its evidence. A probable cause is
 * a hypothesis, ranked, with how sure LEKA is, what it rests on (a
 * source's word, or LEKA's inference) and why. They are drawn apart: a
 * hypothesis is never written as a fact.
 */

export function FindingList({ findings }: { findings: readonly Finding[] }) {
  const t = useDictionary();
  if (findings.length === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{t.intelligence.findings.none}</p>;
  }
  return (
    <ul className="space-y-3" data-testid="findings">
      {findings.map((finding) => (
        <li key={finding.id} className="text-[0.8125rem] text-brand-navy">
          <p>{finding.statement}</p>
          <EvidenceToggle items={finding.evidence} />
        </li>
      ))}
    </ul>
  );
}

export function ProbableCauseList({ causes }: { causes: readonly ProbableCause[] }) {
  const t = useDictionary();
  const w = t.intelligence.causes;
  if (causes.length === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>;
  }
  return (
    <ol className="space-y-3" data-testid="probable-causes">
      {causes.map((cause, index) => (
        <li
          key={cause.id}
          className="rounded-lg border border-state-warning/30 bg-state-warning-soft/30 p-3 text-[0.8125rem]"
          data-testid="probable-cause"
        >
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-xs font-medium text-state-warning">
              {fill(w.rank, { rank: index + 1 })}
            </span>
            {cause.href ? (
              <Link
                href={cause.href}
                className="font-semibold text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {cause.label}
              </Link>
            ) : (
              <span className="font-semibold text-brand-navy">{cause.label}</span>
            )}
            {cause.kind ? <span className="text-xs text-shell-muted">{cause.kind}</span> : null}
            <span className="flex-1" />
            <ConfidenceBadge score={cause.confidence} basis={cause.basis} />
          </div>
          <p className="mt-1 text-shell-muted">
            <span className="font-medium text-brand-navy">{w.why} </span>
            {cause.why}
          </p>
          <EvidenceToggle items={cause.evidence} />
        </li>
      ))}
    </ol>
  );
}
