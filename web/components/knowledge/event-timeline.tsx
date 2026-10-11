"use client";

import {
  BookOpen,
  Gavel,
  GitCommitHorizontal,
  HeartPulse,
  type LucideIcon,
  OctagonAlert,
  Rocket,
  Sparkles,
} from "lucide-react";
import { useId, useMemo, useState } from "react";

import { cn } from "cn";

import { type Tone, TONES } from "@/components/knowledge/status";
import { exactDate, shortWhen } from "@/components/knowledge/time";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

export const EVENT_TYPES = [
  "deployment",
  "incident",
  "change",
  "decision",
  "documentation",
  "leka_analysis",
  "health_change",
] as const;
export type TimelineEventType = (typeof EVENT_TYPES)[number];

export interface TimelineEvent {
  id: string;
  type: TimelineEventType;
  title: string;
  /** ISO 8601. */
  at: string;
  /** Where it came from, as mockup 11 writes it: "GitHub · Commit a1b3c4d". */
  subtitle?: string;
}

const LOOK: Record<TimelineEventType, { tone: Tone; icon: LucideIcon }> = {
  deployment: { tone: "accent", icon: Rocket },
  incident: { tone: "danger", icon: OctagonAlert },
  change: { tone: "info", icon: GitCommitHorizontal },
  decision: { tone: "accent", icon: Gavel },
  documentation: { tone: "info", icon: BookOpen },
  leka_analysis: { tone: "accent", icon: Sparkles },
  health_change: { tone: "warning", icon: HeartPulse },
};

export interface EventTimelineProps {
  events: readonly TimelineEvent[];
  /** Time and title only. */
  compact?: boolean;
  /** How many before "Voir tout". Everything when absent. */
  maxVisible?: number;
  onSelect?: (id: string) => void;
  className?: string;
}

/**
 * What happened, newest first, on one vertical line (LEKA-340) — the
 * "Derniers événements" of mockup 11. An ordered list with real <time>
 * elements: the order means something, and so does the moment.
 */
export function EventTimeline({
  events,
  compact = false,
  maxVisible,
  onSelect,
  className,
}: EventTimelineProps) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const [expanded, setExpanded] = useState(false);
  const listId = useId();

  const sorted = useMemo(
    () => [...events].sort((a, b) => Date.parse(b.at) - Date.parse(a.at)),
    [events],
  );

  if (sorted.length === 0) {
    return (
      <p className={cn("py-3 text-[0.8125rem] text-shell-muted", className)}>
        {t.knowledge.timeline.empty}
      </p>
    );
  }

  const limited = maxVisible !== undefined && sorted.length > maxVisible && !expanded;
  const shown = limited ? sorted.slice(0, Math.max(1, maxVisible)) : sorted;

  return (
    <div className={className}>
      <ol id={listId} className="relative">
        {shown.map((event, index) => {
          const { tone, icon: Icon } = LOOK[event.type];
          const kind = t.knowledge.events[event.type];
          const last = index === shown.length - 1;
          return (
            <li
              key={event.id}
              data-event-type={event.type}
              className={cn("relative flex gap-3", compact ? "pb-2" : "pb-3", last && "pb-0")}
            >
              {/* The line joining the icons: decoration, the order is in the <ol>. */}
              {!last ? (
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute w-px bg-shell-line",
                    compact ? "top-5 bottom-0 start-[9px]" : "top-8 bottom-0 start-[15px]",
                  )}
                />
              ) : null}
              <span
                aria-hidden="true"
                className={cn(
                  "relative flex shrink-0 items-center justify-center rounded-lg",
                  compact ? "size-[19px] rounded-md" : "size-8",
                  TONES[tone].badge,
                )}
              >
                <Icon className={compact ? "size-3" : "size-4"} />
              </span>
              <div className="relative min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <time
                    suppressHydrationWarning
                    dateTime={event.at}
                    title={exactDate(locale, event.at)}
                    className="shrink-0 text-xs text-shell-muted tabular-nums"
                  >
                    {shortWhen(locale, event.at)}
                  </time>
                  {onSelect ? (
                    <button
                      type="button"
                      onClick={() => onSelect(event.id)}
                      className="min-w-0 truncate text-start text-[0.8125rem] font-medium text-brand-navy outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-md focus-visible:after:ring-3 focus-visible:after:ring-brand-violet/40"
                    >
                      {event.title}
                    </button>
                  ) : (
                    <span className="min-w-0 truncate text-[0.8125rem] font-medium text-brand-navy">
                      {event.title}
                    </span>
                  )}
                  {compact ? <span className="sr-only">{`, ${kind}`}</span> : null}
                </div>
                {!compact ? (
                  <div className="mt-0.5 flex items-center gap-2">
                    {event.subtitle ? (
                      <span className="min-w-0 truncate text-xs text-shell-accent-muted">
                        {event.subtitle}
                      </span>
                    ) : null}
                    <span
                      className={cn(
                        "ms-auto shrink-0 rounded-md px-1.5 py-0.5 text-[0.6875rem] font-medium",
                        TONES[tone].badge,
                      )}
                    >
                      {kind}
                    </span>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {maxVisible !== undefined && sorted.length > maxVisible ? (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => setExpanded((open) => !open)}
          className="mt-2 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          {expanded
            ? t.knowledge.timeline.showLess
            : fill(t.knowledge.timeline.showAll, { count: sorted.length })}
        </button>
      ) : null}
    </div>
  );
}
