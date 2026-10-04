"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Impact, RiskLevel } from "@/lib/intelligence";

/**
 * What a situation reaches, and how bad that is (LEKA-341): area by area —
 * what is touched, what depends on it, the applications holding it, the
 * business relying on it — and the risk in words, with what it is read
 * from. A risk nothing said is "inconnu", never low.
 */

const RISK_TONE: Record<RiskLevel, string> = {
  high: "bg-state-danger-soft text-state-danger",
  medium: "bg-state-warning-soft text-state-warning",
  low: "bg-state-success-soft text-state-success",
  unknown: "bg-shell-canvas text-shell-muted",
};

export function RiskBadge({ level, basis }: { level: RiskLevel; basis?: string | null }) {
  const t = useDictionary();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        RISK_TONE[level],
      )}
      data-level={level}
      data-testid="risk"
      title={basis ?? undefined}
    >
      <ShieldAlert className="size-3.5" aria-hidden="true" />
      {t.intelligence.risk[level]}
    </span>
  );
}

export function ImpactPanel({ impact }: { impact: Impact | null }) {
  const t = useDictionary();
  const w = t.intelligence.impact;
  if (impact === null) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>;
  }
  const areas = impact.areas.filter((area) => area.items.length > 0);
  return (
    <div className="space-y-3 text-[0.8125rem]" data-testid="impact">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge level={impact.risk} basis={impact.riskBasis} />
        <span className="text-xs text-shell-muted">{impact.riskBasis}</span>
      </div>
      {areas.length === 0 ? (
        <p className="text-shell-muted">{w.none}</p>
      ) : (
        <dl className="grid gap-x-3 gap-y-2 sm:grid-cols-[10rem_minmax(0,1fr)]">
          {areas.map((area) => (
            <div key={area.id} className="contents">
              <dt className="text-shell-muted">
                {area.label} ({area.items.length})
              </dt>
              <dd className="flex flex-wrap gap-1.5">
                {area.items.map((item) =>
                  item.href ? (
                    <Link
                      key={item.id}
                      href={item.href}
                      className="rounded-md bg-shell-canvas px-2 py-0.5 text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                    >
                      {item.label}
                    </Link>
                  ) : (
                    <span key={item.id} className="rounded-md bg-shell-canvas px-2 py-0.5">
                      {item.label}
                    </span>
                  ),
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
