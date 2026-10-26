"use client";

import { BookOpen, FlaskConical, GitPullRequestArrow, ListChecks, Loader2, Wrench } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { type NextStep, type NextStepKind, nextStepsOf, WRITER } from "@/lib/agent-products/actions";
import { inLanguage, type Words } from "@/lib/agent-products/types";
import { ApiError } from "@/lib/api";
import type { AgentRunDetail } from "@/lib/agent-runs";
import { useAgentRunChange } from "@/lib/agent-runs-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { SPINNING } from "@/lib/motion";
import { notify } from "@/lib/notify";
import type { PublicationKind } from "@/lib/publications";

/**
 * « Régler maintenant » (Karim, 2026-10-23): at the end of every
 * deliverable, the action that settles what the agent found — never only a
 * report (lib/agent-products/actions.ts says which, agent by agent).
 *
 *     fix, tests   the code-change or test-generation agent asked from the
 *                  deliverable, on its repository — the change shown before
 *                  / after, a pull request only once a person accepts it
 *     issues, pages  the publication form opened: tickets for Jira, pages
 *                  for Confluence, sent once a person chose them
 *     change       the agent's own change, to see and send
 *
 * Nothing leaves LEKA from here without a person's yes.
 */

/** What the writing agent is given of the deliverable, at most: its
 * findings come first. */
export const MOST_DELIVERED = 12_000;

const FIELD = "rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy";

const ICONS: Record<NextStepKind, typeof Wrench> = {
  fix: Wrench,
  tests: FlaskConical,
  issues: ListChecks,
  pages: BookOpen,
  change: GitPullRequestArrow,
};

/** The repository the deliverable read: the one it was asked, else the
 * pull request's. */
export function repositoryOf(run: AgentRunDetail): string {
  const asked = run.inputs.depot;
  return (typeof asked === "string" && asked.trim()) || run.review?.repository || "";
}

export function NextSteps({
  run,
  intentionId,
  onStarted,
  onPublish,
  onShowChange,
  change,
}: {
  run: AgentRunDetail;
  intentionId: string;
  onStarted: (runId: string) => void;
  onPublish: (kind: PublicationKind) => void;
  onShowChange: () => void;
  /** The agent's own change, when it wrote one; else written again on the
   * click — never a button that does nothing (2026-10-24). */
  change?: { available: boolean; rewrite: () => void; pending: boolean };
}) {
  const t = useDictionary();
  const w = t.intentions.deliverable.next;
  const { locale } = useLocale();
  const say = (words: Words) => inLanguage(words, locale);
  const [writing, setWriting] = useState<NextStep | null>(null);
  const steps = nextStepsOf(run.key);

  function act(step: NextStep) {
    if (step.kind === "issues" || step.kind === "pages") onPublish(step.kind);
    else if (step.kind === "change") {
      if (change && !change.available) change.rewrite();
      else onShowChange();
    }
    else setWriting(writing === step ? null : step);
  }

  return (
    <section
      className="flex flex-col gap-3 rounded-xl border-2 border-brand-violet/30 bg-brand-violet-soft/40 px-5 py-4"
      aria-labelledby="next-steps-title"
      data-testid="next-steps"
      data-agent={run.key}
    >
      <div>
        <h2 id="next-steps-title" className="text-[1.0625rem] font-semibold text-brand-navy">
          {w.title}
        </h2>
        <p className="text-[0.8125rem] text-shell-muted">{w.intro}</p>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {steps.map((step, index) => {
          const Icon = ICONS[step.kind];
          return (
            <li
              key={`${step.kind}-${index}`}
              className="flex flex-col gap-2 rounded-lg border border-shell-line bg-white p-3"
              data-testid="next-step"
              data-kind={step.kind}
            >
              <p className="flex items-center gap-2 text-[0.9375rem] font-semibold text-brand-navy">
                <Icon className="size-4 shrink-0 text-brand-violet" aria-hidden="true" />
                {say(step.title)}
              </p>
              <p className="flex-1 text-[0.8125rem] text-shell-muted">{say(step.body)}</p>
              <div>
                <Button
                  type="button"
                  size="sm"
                  variant={index === 0 ? "default" : "outline"}
                  aria-expanded={step.kind === "fix" || step.kind === "tests" ? writing === step : undefined}
                  onClick={() => act(step)}
                  disabled={step.kind === "change" && change?.pending}
                  data-testid={`next-step-${step.kind}`}
                >
                  {step.kind === "change" && change && !change.available ? w.rewrite : say(step.title)}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {writing && (writing.kind === "fix" || writing.kind === "tests") ? (
        <WriteForm
          key={say(writing.title)}
          run={run}
          step={writing}
          writer={WRITER[writing.kind]}
          intentionId={intentionId}
          onStarted={onStarted}
        />
      ) : null}
    </section>
  );
}

function WriteForm({
  run,
  step,
  writer,
  intentionId,
  onStarted,
}: {
  run: AgentRunDetail;
  step: NextStep;
  writer: string;
  intentionId: string;
  onStarted: (runId: string) => void;
}) {
  const t = useDictionary();
  const w = t.intentions.deliverable.next;
  const { format, locale } = useLocale();
  const { start } = useAgentRunChange();
  const title = inLanguage(step.title, locale);
  const [focus, setFocus] = useState(() => (step.focus ? inLanguage(step.focus, locale) : ""));
  const [repository, setRepository] = useState(() => repositoryOf(run));
  const delivered = (run.report ?? run.output ?? "").slice(0, MOST_DELIVERED);
  const ready = Boolean(focus.trim() && delivered);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const intro = fill(w.ask, {
      agent: run.title ?? run.key,
      when: run.finished_at ? exactDate(format, run.finished_at) : "—",
    });
    try {
      const started = await start.mutateAsync({
        key: writer,
        inputs: {
          demande: `${focus.trim()}\n\n${intro}\n\n${delivered}`,
          ...(repository.trim() ? { depot: repository.trim() } : {}),
          // The deliverable it comes from: a design review gives the code
          // change its mock-up, never its words alone (2026-10-24).
          ...(writer === "code-change" ? { livrable: run.id } : {}),
        },
        intention_id: intentionId,
      });
      onStarted(started.id);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-shell-line bg-white p-3"
      onSubmit={(event) => void submit(event)}
      aria-label={title}
      data-testid="next-step-form"
      data-writer={writer}
    >
      <label className="flex flex-col gap-1 text-xs text-shell-muted">
        {w.focus}
        <textarea
          className={cn(FIELD, "min-h-20 py-1.5")}
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
          maxLength={2000}
          required
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-shell-muted">
        {w.depot}
        <input
          className={cn(FIELD, "h-8 w-64 max-w-full font-mono")}
          value={repository}
          onChange={(e) => setRepository(e.target.value)}
          placeholder={w.depotHint}
          maxLength={200}
        />
      </label>
      <p className="text-xs text-shell-muted">{w.hint}</p>
      <div>
        <Button type="submit" size="sm" disabled={!ready || start.isPending} data-testid="next-step-start">
          {start.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
          {w.start}
        </Button>
      </div>
    </form>
  );
}
