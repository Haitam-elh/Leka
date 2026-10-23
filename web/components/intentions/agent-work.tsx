"use client";

import { Bot, FileText, LoaderCircle, Wrench } from "lucide-react";
import Link from "next/link";

import { Deliverables } from "@/components/capabilities/agent-runs";
import { deliverableHref } from "@/components/intentions/deliverable";
import { IconTile } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { buttonVariants } from "@/components/ui/button";
import { agentTitle } from "@/lib/agent-title";
import type { AgentRun } from "@/lib/agent-runs";
import { useIntentionRuns } from "@/lib/agent-runs-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The agents at work on an intention (docs/intentions.md § 15 bis): LEKA
 * handed it to the one that does what it asks — the architect for a deck —
 * and here is what it is doing, on what, and its files as soon as they are
 * drawn: the PDF first, then the PowerPoint. The first thing a person who
 * asked for a deliverable looks for, so it comes first on the page.
 */

const TONES = {
  held: "warning",
  queued: "neutral",
  running: "violet",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
} as const;

function inputsSaid(run: AgentRun): string {
  return Object.values(run.inputs)
    .filter((value): value is string => typeof value === "string" && value.trim() !== "")
    .join(" · ");
}

export function AgentWork({ intentionId, live = false }: { intentionId: string; live?: boolean }) {
  const t = useDictionary();
  const w = t.intentions.agentWork;
  const statuses = t.agentRuns.statuses as Record<string, string>;
  const errors = t.agentRuns.errors as Record<string, string>;
  const { data } = useIntentionRuns(intentionId, live);
  if (!data?.length) return null;
  return (
    <section
      className="rounded-xl border border-brand-violet/30 bg-white p-4 shadow-[0_1px_0_rgba(78,10,244,0.06)]"
      aria-labelledby="agent-work-title"
      data-testid="agent-work"
    >
      {/* Who works on it, said apart from the skills its analysis used
          (2026-10-14: « on ne comprend pas quel agent a travaillé »). */}
      <h2
        id="agent-work-title"
        className="mb-3 text-xs font-semibold uppercase tracking-[0.06em] text-shell-muted"
      >
        {w.title}
      </h2>
      <ul className="flex flex-col gap-4">
        {data.map((run) => {
          const moving = run.status === "queued" || run.status === "running";
          const agent = agentTitle(t, run.key, run.title ?? run.key);
          const said = moving
            ? fill(w.working, { agent })
            : run.status === "succeeded"
              ? fill(run.deliverables.length ? w.delivered : w.done, { agent })
              : run.status === "awaiting_approval"
                ? fill(w.agent, { agent })
                : fill(w.stopped, { agent });
          // The files it was asked for, never ones it will not draw
          // (2026-10-14: « PDF et PowerPoint » said of every agent).
          const formats = (run.expected ?? [])
            .map((f) => (t.intentions.agents.deliverables as Record<string, string>)[f] ?? f)
            .join(", ");
          return (
            <li key={run.id} className="flex flex-col gap-3 sm:flex-row sm:items-center" data-testid="agent-work-run">
              <IconTile
                icon={moving ? LoaderCircle : Bot}
                tone={moving ? "violet" : "success"}
                className="size-11"
                spin={moving}
              />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="text-[1rem] font-semibold text-brand-navy">{said}</span>
                  <Pill tone={TONES[run.status as keyof typeof TONES] ?? "neutral"}>
                    {statuses[run.status] ?? run.status}
                  </Pill>
                </p>
                <p className="text-[0.8125rem] text-shell-muted" dir="auto">
                  {inputsSaid(run)}
                </p>
                {run.status === "failed" && run.error ? (
                  <p className="text-[0.8125rem] text-state-danger">{errors[run.error] ?? run.error}</p>
                ) : run.status === "awaiting_approval" ? (
                  <p className="text-[0.8125rem] text-shell-muted">{w.held}</p>
                ) : moving ? (
                  <p className="text-[0.8125rem] text-shell-muted">
                    {formats ? fill(w.filesSoon, { formats }) : w.reportSoon}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Deliverables run={run} />
                {/* What it delivered, read here — every agent's report, the
                    code review's comments on the diff (2026-10-14). */}
                {run.status === "succeeded" ? (
                  <Link
                    href={deliverableHref(intentionId, run.id)}
                    className={buttonVariants({ size: "sm", variant: "outline" })}
                    data-testid="agent-work-open"
                  >
                    <FileText className="size-3.5" aria-hidden="true" />
                    {run.key === "code-review" ? t.intentions.deliverable.openReview : t.intentions.deliverable.open}
                  </Link>
                ) : null}
                {/* Right after the intention, the action that settles it
                    (2026-10-23): its fix, its tests, its tickets, its pages. */}
                {run.status === "succeeded" ? (
                  <Link
                    href={`${deliverableHref(intentionId, run.id)}#next-steps`}
                    className={buttonVariants({ size: "sm" })}
                    data-testid="agent-work-settle"
                  >
                    <Wrench className="size-3.5" aria-hidden="true" />
                    {t.intentions.deliverable.next.open}
                  </Link>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
