"use client";

import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Ban,
  CircleCheck,
  CircleDot,
  CircleX,
  Clock,
  type LucideIcon,
  RefreshCw,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import { cn } from "cn";

import type { TileTone } from "@/components/environment/parts";
import { ConfidenceBadge } from "@/components/intelligence/confidence";
import { Pill } from "@/components/intelligence/pill";
import { IntelligenceSection } from "@/components/intelligence/section";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Explanation, SourceState } from "@/lib/intelligence";

/**
 * On what an analysis rests (LEKA-441), drawn apart from what it found:
 * what LEKA understood; each source it read from and in what state —
 * never shown read when it was failing, syncing or out of date; how sure
 * it is, in words, and why — never a bare percentage; what its sources
 * disagree on; what did not answer and what that leaves unknown; what to
 * do next and why; and, when its context moved on since, that it read an
 * older one. Shapes in lib/intelligence.ts (Explanation).
 */

const STATE_LOOK: Record<SourceState, { icon: LucideIcon; tone: TileTone }> = {
  read: { icon: CircleCheck, tone: "success" },
  error: { icon: CircleX, tone: "danger" },
  degraded: { icon: TriangleAlert, tone: "warning" },
  stale: { icon: Clock, tone: "warning" },
  syncing: { icon: RefreshCw, tone: "info" },
  disabled: { icon: Ban, tone: "neutral" },
  gone: { icon: Trash2, tone: "neutral" },
};

const EFFECT_LOOK: Record<
  Explanation["confidence"]["reasons"][number]["effect"],
  { icon: LucideIcon; className: string }
> = {
  base: { icon: CircleDot, className: "text-shell-nav-active" },
  raises: { icon: ArrowUp, className: "text-state-success" },
  lowers: { icon: ArrowDown, className: "text-state-warning" },
  caps: { icon: ArrowDown, className: "text-state-warning" },
};

/** « Ce que LEKA a compris » — one line, above what it found. */
export function UnderstoodLine({ text }: { text: string }) {
  const t = useDictionary();
  return (
    <p
      className="rounded-xl border border-shell-line bg-white px-4 py-3 text-[0.8125rem]"
      data-testid="analysis-understood"
    >
      <span className="font-semibold text-brand-navy">{t.intelligence.explained.understood}</span>{" "}
      <span className="text-shell-muted">{text}</span>
    </p>
  );
}

/** How sure, in words, and why: what it starts from, what caps it. */
export function ConfidenceExplained({
  confidence,
  level = 3,
}: {
  confidence: Explanation["confidence"];
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence.explained.confidence;
  return (
    <IntelligenceSection
      kind="confidence"
      title={t.intelligence.confidence.title}
      level={level}
      action={<ConfidenceBadge level={confidence.level} score={null} short detail={false} />}
    >
      <p className="-mt-1.5 mb-2 text-xs text-shell-muted">{w.why}</p>
      <ul className="space-y-1.5 text-[0.8125rem]" data-testid="confidence-reasons">
        {confidence.reasons.map((reason) => {
          const look = EFFECT_LOOK[reason.effect];
          const Icon = look.icon;
          return (
            <li
              key={reason.id}
              className="flex items-start gap-2"
              data-effect={reason.effect}
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", look.className)} aria-hidden="true" />
              <span className="min-w-0 text-brand-navy">
                <span className="sr-only">{w.effects[reason.effect]} : </span>
                {reason.label}
              </span>
            </li>
          );
        })}
      </ul>
    </IntelligenceSection>
  );
}

/** Each source it read from, and in what state when it read. */
export function SourcesConsulted({
  sources,
  level = 3,
}: {
  sources: Explanation["consulted"];
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence.explained.sources;
  return (
    <IntelligenceSection
      kind="context"
      title={w.title}
      count={sources.length ? fill(w.count, { count: sources.length }) : undefined}
      level={level}
    >
      {sources.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      ) : (
        <ul className="space-y-2 text-[0.8125rem]" data-testid="sources-consulted">
          {sources.map((source) => {
            const look = STATE_LOOK[source.state];
            const Icon = look.icon;
            return (
              <li
                key={source.id}
                className="flex items-start gap-2"
                data-state={source.state}
              >
                <Icon
                  className={cn(
                    "mt-0.5 size-4 shrink-0",
                    source.state === "read" ? "text-state-success" : "text-shell-muted",
                  )}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="font-medium text-brand-navy">{source.name}</span>
                    <Pill tone={look.tone}>{w.states[source.state]}</Pill>
                  </div>
                  <p className="text-xs text-shell-muted">
                    {source.said} · {fill(w.elements, { count: source.elements })}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </IntelligenceSection>
  );
}

/** What its sources disagree on about what it asks: every side, who says it. */
export function ConflictList({
  conflicts,
  level = 3,
}: {
  conflicts: Explanation["conflicts"];
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence.explained.conflicts;
  if (conflicts.length === 0) return null;
  return (
    <IntelligenceSection
      kind="missing"
      title={w.title}
      count={fill(w.count, { count: conflicts.length })}
      level={level}
    >
      <ul className="space-y-2 text-[0.8125rem]" data-testid="analysis-conflicts">
        {conflicts.map((conflict) => (
          <li key={conflict.id}>
            <p className="font-medium text-brand-navy">{conflict.label}</p>
            <ul className="mt-1 space-y-0.5 text-shell-muted">
              {conflict.values.map((side) => (
                <li key={`${side.value}:${side.by.join()}`}>
                  <span className="font-medium text-brand-navy">{side.value}</span>{" "}
                  {fill(w.by, { sources: side.by.join(", ") })}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </IntelligenceSection>
  );
}

/** What did not answer and what that leaves unknown; what is failing, out
 * of date or incomplete — said, so a partial result is read as partial. */
export function AnalysisLimits({
  explanation,
  level = 3,
}: {
  explanation: Explanation;
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence.explained.limits;
  const id = useId();
  const silent = explanation.silent;
  const limits = explanation.limits;
  const stale = explanation.stale;
  const none = silent.length === 0 && limits.length === 0 && stale.length === 0;
  return (
    <IntelligenceSection kind="missing" title={w.title} level={level}>
      {none ? (
        <p className="text-[0.8125rem] text-shell-muted" data-testid="analysis-limits-none">
          {w.none}
        </p>
      ) : (
        <div className="space-y-3 text-[0.8125rem]" data-testid="analysis-limits">
          {silent.length ? (
            <ul className="space-y-1.5" aria-labelledby={`${id}-silent`}>
              <li id={`${id}-silent`} className="font-medium text-brand-navy">
                {w.silent}
              </li>
              {silent.map((capability) => (
                <li key={capability.id} className="flex items-start gap-2" data-capability={capability.id}>
                  <CircleX className="mt-0.5 size-4 shrink-0 text-state-danger" aria-hidden="true" />
                  <span className="min-w-0">
                    <span className="font-medium text-brand-navy">{capability.name}</span>
                    {" — "}
                    <span className="text-shell-muted">{capability.leaves}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {limits.length ? (
            <ul className="space-y-1.5 text-shell-muted">
              {limits.map((limit) => (
                <li key={limit} className="flex items-start gap-2">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0 text-state-warning" aria-hidden="true" />
                  {limit}
                </li>
              ))}
              {explanation.unread ? (
                <li className="pl-6">
                  <Link
                    href={routes.sources()}
                    className="font-medium text-brand-violet underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40 focus-visible:outline-none"
                  >
                    {w.seeSources}
                  </Link>
                </li>
              ) : null}
            </ul>
          ) : null}
          {stale.length ? (
            <div>
              <p className="font-medium text-brand-navy">{w.stale}</p>
              <ul className="mt-1 space-y-1.5 text-shell-muted">
                {stale.map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <Clock className="mt-0.5 size-4 shrink-0 text-state-warning" aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </IntelligenceSection>
  );
}

/** What to do next, and why that — under what it proposes. */
export function NextStepPanel({
  next,
  action,
  level = 3,
}: {
  next: Explanation["next"];
  /** The way to do it, when the screen has one. */
  action?: React.ReactNode;
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence.explained.next;
  return (
    <IntelligenceSection kind="proposal" title={w.title} level={level}>
      <div className="space-y-2 text-[0.8125rem]" data-testid="analysis-next" data-code={next.code}>
        <p className="flex items-start gap-2 font-medium text-brand-navy">
          <ArrowRight className="mt-0.5 size-4 shrink-0 text-brand-violet rtl:-scale-x-100" aria-hidden="true" />
          {next.title}
        </p>
        <p className="text-shell-muted">
          <span className="font-medium text-brand-navy">{w.why}</span> {next.why}
        </p>
        {action}
      </div>
    </IntelligenceSection>
  );
}

/** Its context moved on since it read it: said, never silently kept. */
export function FreshnessNotice({
  read,
  now,
  action,
}: {
  read: number | null;
  now: number | null;
  action?: React.ReactNode;
}) {
  const t = useDictionary();
  const w = t.intelligence.explained.freshness;
  if (read === null || now === null || now <= read) return null;
  return (
    <div
      role="status"
      className="flex flex-col gap-3 rounded-xl bg-state-warning-soft px-4 py-3 text-[0.8125rem] sm:flex-row sm:items-center"
      data-testid="analysis-freshness"
    >
      <Clock className="size-4 shrink-0 text-state-warning" aria-hidden="true" />
      <div className="min-w-0 flex-1 text-brand-navy">
        <p className="font-semibold">{w.title}</p>
        <p className="text-shell-muted">{fill(w.body, { read, now })}</p>
      </div>
      {action}
    </div>
  );
}
