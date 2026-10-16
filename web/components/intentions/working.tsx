"use client";

import { Check, CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";

import { cn } from "cn";

import { timeAgo } from "@/components/knowledge/time";
import { useAgentRun, useIntentionRuns } from "@/lib/agent-runs-queries";
import type { AgentRun } from "@/lib/agent-runs";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { useIntentionAnalysis } from "@/lib/intentions/queries";

/**
 * What LEKA is doing on an intention, now (LEKA-465): said at once, kept
 * through a refresh — everything here is read from the server, never held
 * by the page — and only what really happened.
 *
 *     analysing        its request recorded; LEKA reading its sources and
 *                      analysing, since when
 *     agents at work   each agent, the steps its run really went through
 *                      (queued, started, its context read, its sources
 *                      consulted, its deliverable written, its files
 *                      drawn), each with when
 *     failed           what failed, said; the way on is the journey's
 *                      (JourneyNote): retry, resume
 *
 * No percentage, no progress bar: nothing measures how far a model is.
 * Working, it says one may leave: the work goes on, the result waits here.
 */

type Phase = "analysis" | "agents" | "failed";

const WORKING_STATES = new Set(["analysing", "ready", "draft"]);

export function phaseOf(intention: IntentionDetail, runs: readonly AgentRun[] | undefined): Phase | null {
  const { state, by } = intention.journey;
  if (state === "analysis_failed" || state === "action_failed") return "failed";
  if (state === "action_running" || (runs ?? []).some((r) => r.status === "queued" || r.status === "running")) {
    return "agents";
  }
  if (by === "leka" && WORKING_STATES.has(state)) return "analysis";
  return null;
}

export function Working({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.working;
  const runs = useIntentionRuns(intention.id, intention.journey.by === "leka");
  const phase = phaseOf(intention, runs.data);
  if (!phase) return null;
  const failed = phase === "failed";
  return (
    <section
      // Said as it changes, to whoever does not see it change.
      aria-live="polite"
      aria-labelledby="working-title"
      className={cn(
        "space-y-3 rounded-2xl p-4 ring-1",
        failed ? "bg-state-danger/5 ring-state-danger/30" : "bg-brand-violet-soft/40 ring-brand-violet/25",
      )}
      data-testid="working"
      data-phase={phase}
    >
      <h2 id="working-title" className="flex items-center gap-2.5 text-[1.0625rem] font-semibold text-brand-navy">
        {failed ? (
          <CircleAlert className="size-5 text-state-danger" aria-hidden="true" />
        ) : (
          <LoaderCircle className="size-5 animate-spin text-brand-violet motion-reduce:animate-none" aria-hidden="true" />
        )}
        {phase === "analysis" ? w.analysing : phase === "agents" ? w.agents : w.failed}
      </h2>
      {phase === "analysis" ? <AnalysisSteps intention={intention} /> : null}
      {phase !== "analysis" ? (
        <ul className="space-y-3">
          {(runs.data ?? []).map((run) => (
            <RunSteps key={run.id} run={run} />
          ))}
        </ul>
      ) : null}
      {failed ? null : <p className="text-[0.8125rem] text-shell-muted">{w.leave}</p>}
    </section>
  );
}

const FAILING = new Set(["failed", "render_failed", "cancelled", "rejected"]);

function Step({
  done,
  label,
  at,
  failing = false,
}: {
  done: boolean;
  label: string;
  at?: string | null;
  failing?: boolean;
}) {
  const t = useDictionary();
  return (
    <li className="flex items-start gap-2 text-[0.8125rem]" data-testid="working-step" data-done={done || undefined}>
      {failing ? (
        <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-state-danger" aria-hidden="true" />
      ) : done ? (
        <Check className="mt-0.5 size-3.5 shrink-0 text-[#15803d]" aria-hidden="true" />
      ) : (
        <LoaderCircle className="mt-0.5 size-3.5 shrink-0 animate-spin text-brand-violet motion-reduce:animate-none" aria-hidden="true" />
      )}
      <span className={done ? "text-brand-navy" : "font-medium text-brand-navy"}>{label}</span>
      {at ? <span className="text-shell-muted">· {timeAgo(t, at).toLowerCase()}</span> : null}
    </li>
  );
}

function AnalysisSteps({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.working;
  const analysis = useIntentionAnalysis(intention.id, () => true);
  const running = analysis.data?.status === "running";
  return (
    <ol className="space-y-1.5" data-testid="working-steps">
      <Step done label={w.recorded} at={intention.created_at} />
      {running ? (
        <Step done={false} label={w.reading} at={analysis.data?.started_at} />
      ) : (
        <Step done={false} label={w.queued} at={intention.journey.since} />
      )}
    </ol>
  );
}

/** A run's own events, as they happened: one line each kind reached. */
function RunSteps({ run }: { run: AgentRun }) {
  const t = useDictionary();
  const w = t.intentions.working;
  const detail = useAgentRun(run.id);
  const events = detail.data?.events ?? [];
  const words = w.events as Record<string, string>;
  const seen = new Map<string, { at: string; count: number }>();
  for (const event of events) {
    const kind = event.kind === "tool_withheld" ? "tool" : event.kind;
    if (!(kind in words)) continue;
    const had = seen.get(kind);
    seen.set(kind, { at: event.at, count: (had?.count ?? 0) + 1 });
  }
  const ended = run.status === "succeeded" || run.status === "failed" || run.status === "cancelled";
  const errors = t.agentRuns.errors as Record<string, string>;
  const lines = [...seen.entries()];
  return (
    <li className="space-y-1.5" data-testid="working-run" data-status={run.status}>
      <p className="flex items-center gap-2 text-[0.875rem] font-semibold text-brand-navy">
        {run.status === "succeeded" ? (
          <CircleCheck className="size-4 text-[#15803d]" aria-hidden="true" />
        ) : null}
        {run.title ?? run.key}
      </p>
      <ol className="space-y-1.5" data-testid="working-steps">
        {lines.map(([kind, { at, count }], index) => (
          <Step
            key={kind}
            // The last step reached is the one at work, until the run ends.
            done={ended || index < lines.length - 1}
            failing={FAILING.has(kind)}
            label={
              kind === "tool"
                ? fill(words.tool, { count })
                : kind === "failed"
                  ? fill(words.failed, {
                      why: (run.error && errors[run.error]) || run.error || "—",
                    })
                  : words[kind]
            }
            at={at}
          />
        ))}
        {!lines.length ? <Step done={false} label={words.queued} at={run.queued_at} /> : null}
      </ol>
    </li>
  );
}
