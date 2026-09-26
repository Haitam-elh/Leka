"use client";

import { CircleDashed, Clock, History, type LucideIcon, TriangleAlert } from "lucide-react";

import { cn } from "cn";

import { type Tone, TONES } from "@/components/knowledge/status";
import { exactDate, hoursSince, timeAgo } from "@/components/knowledge/time";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

// ── Quality ─────────────────────────────────────────────────────────────────

export type QualityLevel = "high" | "medium" | "low";

/** Below 50 is poor, from 80 good — the thresholds the ticket sets. */
export function qualityLevel(score: number): QualityLevel {
  if (score >= 80) return "high";
  if (score >= 50) return "medium";
  return "low";
}

const QUALITY_TONE: Record<QualityLevel, Tone> = {
  high: "success",
  medium: "warning",
  low: "danger",
};

export interface QualityIndicatorProps {
  /** 0 to 100. From an entity's confidence: confidenceToScore(). */
  score: number;
  /** What is being scored; "Qualité des données" by default. */
  label?: string;
  showValue?: boolean;
  className?: string;
}

/**
 * A score out of 100, as a bar and a number (LEKA-340).
 *
 * role="meter" with its value, so a screen reader hears "72 sur 100,
 * moyenne" — the bar's colour repeats the level, the number states it.
 */
export function QualityIndicator({
  score,
  label,
  showValue = true,
  className,
}: QualityIndicatorProps) {
  const t = useDictionary();
  const value = Math.round(Math.min(100, Math.max(0, Number.isFinite(score) ? score : 0)));
  const level = qualityLevel(value);
  const name = label ?? t.knowledge.quality.label;

  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-label={fill(t.knowledge.quality.aria, {
        label: name,
        score: value,
        level: t.knowledge.quality[level],
      })}
      data-level={level}
      className={cn("inline-flex items-center gap-2", className)}
    >
      <span aria-hidden="true" className="h-1.5 w-16 overflow-hidden rounded-full bg-shell-canvas">
        <span
          className={cn("block h-full rounded-full", TONES[QUALITY_TONE[level]].dot)}
          style={{ width: `${value}%` }}
        />
      </span>
      {showValue ? (
        <span aria-hidden="true" className="text-xs font-medium text-shell-nav tabular-nums">
          {value}
        </span>
      ) : null}
    </div>
  );
}

// ── Freshness ───────────────────────────────────────────────────────────────

export type Freshness = "fresh" | "aging" | "stale" | "never";

export interface FreshnessThresholds {
  /** Older than this, the data is ageing. 24 h by default. */
  agingAfterHours?: number;
  /** Older than this, it is stale. 7 days by default. */
  staleAfterHours?: number;
}

export const DEFAULT_FRESHNESS: Required<FreshnessThresholds> = {
  agingAfterHours: 24,
  staleAfterHours: 24 * 7,
};

export function freshnessOf(
  lastUpdated: string | Date | null | undefined,
  thresholds: FreshnessThresholds = {},
  now = Date.now(),
): Freshness {
  if (!lastUpdated) return "never";
  const { agingAfterHours, staleAfterHours } = { ...DEFAULT_FRESHNESS, ...thresholds };
  const age = hoursSince(lastUpdated, now);
  if (age >= staleAfterHours) return "stale";
  if (age >= agingAfterHours) return "aging";
  return "fresh";
}

const FRESHNESS_LOOK: Record<Freshness, { tone: Tone; icon: LucideIcon }> = {
  fresh: { tone: "success", icon: Clock },
  aging: { tone: "warning", icon: History },
  stale: { tone: "danger", icon: TriangleAlert },
  never: { tone: "neutral", icon: CircleDashed },
};

export interface FreshnessIndicatorProps {
  lastUpdated: string | Date | null | undefined;
  thresholds?: FreshnessThresholds;
  /** The state's word next to the time. The time alone when false. */
  showLabel?: boolean;
  className?: string;
}

/**
 * How old a piece of knowledge is: "À jour · Il y a 3 h", the exact date
 * in a tooltip (LEKA-340). The thresholds are the caller's to set: a
 * deployment is old after an hour, a runbook after a month.
 */
export function FreshnessIndicator({
  lastUpdated,
  thresholds,
  showLabel = true,
  className,
}: FreshnessIndicatorProps) {
  const t = useDictionary();
  const { locale } = useLocale();
  const state = freshnessOf(lastUpdated, thresholds);
  const { tone, icon: Icon } = FRESHNESS_LOOK[state];
  const ago = lastUpdated ? timeAgo(t, lastUpdated) : t.knowledge.freshness.never;
  const word = t.knowledge.freshness[state];
  const exact = lastUpdated
    ? fill(t.knowledge.freshness.updatedAt, { date: exactDate(locale, lastUpdated) })
    : t.knowledge.freshness.never;

  return (
    <Tooltip>
      {/* "Il y a 3 min" is computed from now: the server's now and the
          browser's can straddle a minute. Only these nodes may differ. */}
      <TooltipTrigger
        suppressHydrationWarning
        data-freshness={state}
        aria-label={`${fill(t.knowledge.freshness.aria, { state: word, ago })}. ${exact}`}
        className={cn(
          "inline-flex w-fit items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
          TONES[tone].badge,
          className,
        )}
      >
        <Icon aria-hidden="true" className="size-3.5 shrink-0" />
        {showLabel && state !== "never" ? <span suppressHydrationWarning>{word} ·</span> : null}
        <span suppressHydrationWarning>{ago}</span>
      </TooltipTrigger>
      <TooltipContent>{exact}</TooltipContent>
    </Tooltip>
  );
}
