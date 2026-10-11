"use client";

import {
  ChartColumn,
  ChevronRight,
  type LucideIcon,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useId, useState } from "react";

import { cn } from "cn";

import { IconTile, type TileTone } from "@/components/environment/parts";
import { ConfidenceBadge } from "@/components/intelligence/confidence";
import { EvidenceStrip } from "@/components/intelligence/evidence";
import { RiskBadge } from "@/components/intelligence/impact";
import { Pill } from "@/components/intelligence/pill";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Priority, Recommendation, RecommendationAction } from "@/lib/intelligence";

/**
 * What LEKA proposes (LEKA-341): a decision someone takes, as mockups 04
 * and 05 draw it — never as a fact. A card each: its icon, what to do, why,
 * its priority, and in chips what it touches, how long it takes, whether
 * it can be undone, how risky it is and how sure LEKA is; the chevron
 * opens "Éléments qui justifient cette recommandation". A screen that lets
 * someone act on it passes the control — a checkbox — and asks before
 * acting (components/interactions/confirm). `ControlNotice` says so.
 */

const ACTION_ICONS: Record<RecommendationAction, LucideIcon> = {
  rollback: RotateCcw,
  change: Settings2,
  monitor: ChartColumn,
  other: Sparkles,
};

const PRIORITY_TONES: Record<Priority, TileTone> = {
  high: "danger",
  medium: "warning",
  low: "violet",
};

const SELECTED: Record<Priority | "none", string> = {
  high: "border-state-danger/50 bg-state-danger-soft/30",
  medium: "border-state-warning/50 bg-state-warning-soft/30",
  low: "border-brand-violet/50 bg-brand-violet-soft/30",
  none: "border-brand-violet/50 bg-brand-violet-soft/30",
};

export function RecommendationCard({
  recommendation,
  control,
  selected = false,
  compact = false,
  level = 4,
}: {
  recommendation: Recommendation;
  /** Its title's level: one below its section's. */
  level?: 3 | 4;
  /** What chooses it, when it can be chosen: a checkbox, labelled by its title. */
  control?: React.ReactNode;
  selected?: boolean;
  /** Mockup 04's line, in a side column: tighter. */
  compact?: boolean;
}) {
  const t = useDictionary();
  const w = t.intelligence.recommendations;
  const [open, setOpen] = useState(false);
  const more = useId();
  const Heading = level === 3 ? "h3" : "h4";
  const priority = recommendation.priority ?? null;
  const tone: TileTone = priority ? PRIORITY_TONES[priority] : "violet";
  const icon = ACTION_ICONS[recommendation.action ?? "other"];
  const chips = (
    <ul className="mt-2 flex flex-wrap items-center gap-2" aria-label={w.chips}>
      {recommendation.effect ? (
        <li>
          <Pill tone={priority ? tone : "neutral"}>
            {fill(w.effectChip, { effect: recommendation.effect })}
          </Pill>
        </li>
      ) : null}
      {recommendation.effort ? (
        <li>
          <Pill tone="neutral">{recommendation.effort}</Pill>
        </li>
      ) : null}
      {recommendation.reversible === true || recommendation.reversible === false ? (
        <li>
          <Pill tone={recommendation.reversible ? "success" : "danger"}>
            {recommendation.reversible ? w.reversible : w.irreversible}
          </Pill>
        </li>
      ) : null}
      {recommendation.risk ? (
        <li>
          <RiskBadge level={recommendation.risk} />
        </li>
      ) : null}
      <li>
        <ConfidenceBadge score={recommendation.confidence} />
      </li>
    </ul>
  );
  return (
    <article
      aria-label={recommendation.title}
      data-testid="recommendation"
      data-priority={priority ?? undefined}
      className={cn(
        "rounded-xl border bg-white text-[0.8125rem]",
        compact ? "p-3" : "p-4",
        selected ? SELECTED[priority ?? "none"] : "border-shell-line",
      )}
    >
      <div className="flex items-start gap-3">
        {control ? <span className="pt-3">{control}</span> : null}
        <IconTile icon={icon} tone={tone} className={compact ? "size-9" : "size-12"} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
            <Heading className="min-w-0 flex-1 text-[0.9375rem] font-semibold text-brand-navy">
              {recommendation.title}
            </Heading>
            {priority ? (
              <Pill tone={tone} data-testid="priority">
                {w.priority[priority]}
              </Pill>
            ) : null}
          </div>
          <p className="mt-0.5 text-shell-muted">{recommendation.rationale}</p>
          {chips}
          {open ? (
            <div id={more} className="mt-3">
              <EvidenceStrip items={recommendation.evidence} title={w.justified} />
            </div>
          ) : null}
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={open ? more : undefined}
          aria-label={fill(w.why, { title: recommendation.title })}
          onClick={() => setOpen(!open)}
          className="shrink-0 rounded p-1 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <ChevronRight className={cn("size-5 transition-transform", open ? "rotate-90" : "rtl:-scale-x-100")} />
        </button>
      </div>
    </article>
  );
}

export function RecommendationList({
  recommendations,
  compact = false,
  level = 4,
}: {
  recommendations: readonly Recommendation[];
  compact?: boolean;
  level?: 3 | 4;
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
        <RecommendationCard
          key={recommendation.id}
          recommendation={recommendation}
          compact={compact}
          level={level}
        />
      ))}
    </div>
  );
}

/** Mockups 02, 05 and 06's "Vous gardez le contrôle": nothing runs without
 * someone's explicit yes. */
export function ControlNotice() {
  const t = useDictionary();
  const w = t.intelligence.control;
  return (
    <div
      role="note"
      className="flex items-start gap-4 rounded-xl bg-shell-highlight px-5 py-4"
      data-testid="control-notice"
    >
      <IconTile icon={ShieldCheck} tone="violet" className="size-11" />
      <div className="min-w-0 text-[0.8125rem]">
        <p className="text-[0.9375rem] font-semibold text-brand-navy">{w.title}</p>
        <p className="text-shell-muted">{w.body}</p>
      </div>
    </div>
  );
}
