"use client";

import { Sparkles } from "lucide-react";

import { cn } from "cn";

import { ConfidenceBadge } from "@/components/intelligence/confidence";
import { EvidenceToggle } from "@/components/intelligence/evidence";
import { RiskBadge } from "@/components/intelligence/impact";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Recommendation } from "@/lib/intelligence";

/**
 * What LEKA proposes (LEKA-341): a decision someone takes, drawn so it is
 * never read as a fact — violet, marked "Proposition", with why, what it
 * would change, how risky, whether it can be undone, how sure LEKA is, and
 * the evidence. A screen that lets someone act on it passes the control —
 * a checkbox — and asks before acting (components/interactions/confirm).
 */

export function RecommendationCard({
  recommendation,
  control,
  selected = false,
  level = 4,
}: {
  recommendation: Recommendation;
  /** Its title's level: one below its section's. */
  level?: 3 | 4;
  /** What chooses it, when it can be chosen: a checkbox, labelled by its title. */
  control?: React.ReactNode;
  selected?: boolean;
}) {
  const t = useDictionary();
  const w = t.intelligence.recommendations;
  const Heading = level === 3 ? "h3" : "h4";
  return (
    <article
      aria-label={recommendation.title}
      data-testid="recommendation"
      className={cn(
        "rounded-lg border border-brand-violet/30 bg-white p-3 text-[0.8125rem]",
        selected && "border-brand-violet ring-2 ring-brand-violet/30",
      )}
    >
      <div className="flex items-start gap-3">
        {control ? <span className="pt-0.5">{control}</span> : null}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Sparkles className="size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
            <Heading className="font-semibold text-brand-navy">{recommendation.title}</Heading>
            <span className="flex-1" />
            <ConfidenceBadge score={recommendation.confidence} />
          </div>
          <p className="mt-1 text-shell-muted">{recommendation.rationale}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            {recommendation.effect ? (
              <span className="text-brand-navy">
                <span className="text-shell-muted">{w.effect} : </span>
                {recommendation.effect}
              </span>
            ) : null}
            {recommendation.risk ? <RiskBadge level={recommendation.risk} /> : null}
            {recommendation.reversible === true || recommendation.reversible === false ? (
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 font-medium",
                  recommendation.reversible
                    ? "bg-shell-canvas text-brand-navy"
                    : "bg-state-danger-soft text-state-danger",
                )}
              >
                {recommendation.reversible ? w.reversible : w.irreversible}
              </span>
            ) : null}
          </div>
          <EvidenceToggle items={recommendation.evidence} />
        </div>
      </div>
    </article>
  );
}

export function RecommendationList({
  recommendations,
}: {
  recommendations: readonly Recommendation[];
}) {
  const t = useDictionary();
  if (recommendations.length === 0) {
    return (
      <p className="text-[0.8125rem] text-shell-muted">{t.intelligence.recommendations.none}</p>
    );
  }
  return (
    <div className="space-y-2" data-testid="recommendations">
      {recommendations.map((recommendation) => (
        <RecommendationCard key={recommendation.id} recommendation={recommendation} />
      ))}
    </div>
  );
}
