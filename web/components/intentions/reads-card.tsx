"use client";

import {
  Ban,
  BookOpenCheck,
  CircleCheck,
  CircleX,
  Clock,
  type LucideIcon,
} from "lucide-react";
import { useMemo } from "react";

import { cn } from "cn";

import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionAnalysis } from "@/lib/intention-analysis";
import { readAbout, runsBetween, type SkillRun } from "@/lib/skills";
import { useSkillRuns } from "@/lib/skills-queries";

/**
 * What LEKA read to answer (LEKA-396): each read of its analyst, a skill
 * run — checked, with the rights of whoever asked, kept — in the order it
 * read: what it looked for or read, which way, where, over which period,
 * how much it found; a read refused or failed, said why. Nothing when it
 * read nothing: the rules alone answered.
 */

const LOOK: Record<SkillRun["status"], { icon: LucideIcon; tone: TileTone }> = {
  succeeded: { icon: CircleCheck, tone: "success" },
  refused: { icon: Ban, tone: "warning" },
  failed: { icon: CircleX, tone: "danger" },
  timed_out: { icon: Clock, tone: "warning" },
};

/** A moment, short — none when it is not one: a model may have asked with
 * a date LEKA could not read (its read refused). */
function moment(locale: string, iso: string | null): string | null {
  const date = iso ? new Date(iso) : null;
  if (!date || Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function ReadsCard({
  intentionId,
  analysis,
}: {
  intentionId: string;
  analysis: IntentionAnalysis;
}) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.intentions.analysis.reads;
  const runs = useSkillRuns(`intention:${intentionId}`, analysis.status === "running");
  const read = useMemo(
    () => runsBetween(runs.data ?? [], analysis.started_at, analysis.finished_at ?? null),
    [runs.data, analysis.started_at, analysis.finished_at],
  );
  if (!read.length) return null;
  return (
    <Card
      title={w.title}
      icon={<BookOpenCheck className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <p className="text-xs text-shell-muted">{w.body}</p>
      <ol className="divide-y divide-shell-line/60" data-testid="analysis-reads">
        {read.map((run) => {
          const about = readAbout(run);
          const since = moment(locale, about.since);
          const until = moment(locale, about.until);
          const period =
            since && until
              ? fill(w.period, { since, until })
              : since
                ? fill(w.since, { date: since })
                : null;
          const parts = [
            about.subject,
            about.direction ? w[about.direction] : null,
            about.environment,
            period,
          ].filter(Boolean);
          const look = LOOK[run.status];
          const done = run.status === "succeeded";
          const why = (w.reasons as Record<string, string>)[run.reason ?? run.status];
          return (
            <li
              key={run.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[0.8125rem]"
              data-testid="analysis-read"
              data-key={run.key}
              data-status={run.status}
            >
              <look.icon
                className={cn(
                  "size-4 shrink-0",
                  look.tone === "success" && "text-state-success",
                  look.tone === "danger" && "text-state-danger",
                  look.tone === "warning" && "text-state-warning",
                )}
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1">
                <span className="font-medium text-brand-navy">
                  {(w.names as Record<string, string>)[run.key] ?? run.key}
                </span>
                {parts.length ? (
                  <span className="text-shell-muted">
                    {" · "}
                    {parts.join(" · ")}
                  </span>
                ) : null}
                {!done ? (
                  <span className="block text-xs text-shell-muted">{why ?? run.message}</span>
                ) : null}
              </span>
              {done ? (
                run.cited ? (
                  <span className="text-xs text-shell-muted">
                    {fill(w.read, { count: run.cited })}
                  </span>
                ) : null
              ) : (
                <Pill tone={look.tone}>{w.statuses[run.status]}</Pill>
              )}
              <span className="w-16 text-right text-xs tabular-nums text-shell-muted">
                {fill(w.ms, { ms: run.latency_ms })}
              </span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
