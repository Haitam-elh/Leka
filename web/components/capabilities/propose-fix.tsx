"use client";

import { Loader2, Wrench } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { AgentRunDetail } from "@/lib/agent-runs";
import { useAgentRunChange } from "@/lib/agent-runs-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { SPINNING } from "@/lib/motion";
import { notify } from "@/lib/notify";

/**
 * From a review, its fix (2026-10-18): the code-change agent asked to
 * correct what the review found, with the review itself as its brief. LEKA
 * then shows the change before and after, and opens a pull request only
 * once a person accepts it — nothing reaches GitHub before.
 */

/** The agents whose deliverable is a review of code a fix can follow. */
export const FIXABLE: ReadonlySet<string> = new Set([
  "code-review",
  "ui-quality-review",
  "accessibility-audit",
  "design-review",
  "motion-review",
]);

/** What the fix is given of the review, at most: its findings come first. */
export const MOST_REVIEW = 12_000;

const FIELD = "rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy";

/** The repository the review read: the one it was asked, else the pull
 * request's. */
export function repositoryOf(run: AgentRunDetail): string {
  const asked = run.inputs.depot;
  return (typeof asked === "string" && asked.trim()) || run.review?.repository || "";
}

export function ProposeFix({
  run,
  intentionId,
  onStarted,
}: {
  run: AgentRunDetail;
  intentionId: string;
  onStarted: (runId: string) => void;
}) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intentions.deliverable.fix;
  const { start } = useAgentRunChange();
  const [open, setOpen] = useState(false);
  const [focus, setFocus] = useState<string>(w.focusDefault);
  const [repository, setRepository] = useState(() => repositoryOf(run));
  if (!FIXABLE.has(run.key)) return null;
  const review = (run.report ?? run.output ?? "").slice(0, MOST_REVIEW);
  const ready = Boolean(focus.trim() && repository.trim() && review);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const intro = fill(w.ask, {
      agent: run.title ?? run.key,
      when: run.finished_at ? exactDate(locale, run.finished_at) : "—",
    });
    try {
      const started = await start.mutateAsync({
        key: "code-change",
        inputs: { demande: `${focus.trim()}\n\n${intro}\n\n${review}`, depot: repository.trim() },
        intention_id: intentionId,
      });
      onStarted(started.id);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        data-testid="deliverable-fix-open"
      >
        <Wrench className="size-3.5" aria-hidden="true" />
        {w.open}
      </Button>
      {open ? (
        <form
          className="flex w-full flex-col gap-3 rounded-lg border border-shell-line bg-shell-canvas/50 p-3"
          onSubmit={(event) => void submit(event)}
          aria-label={w.title}
          data-testid="deliverable-fix"
        >
          <p className="text-[0.875rem] font-semibold text-brand-navy">{w.title}</p>
          <label className="flex flex-col gap-1 text-xs text-shell-muted">
            {w.focus}
            <textarea
              className={cn(FIELD, "min-h-16 py-1.5")}
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
              required
            />
          </label>
          <p className="text-xs text-shell-muted">{w.hint}</p>
          <div>
            <Button type="submit" size="sm" disabled={!ready || start.isPending} data-testid="deliverable-fix-start">
              {start.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
              {w.start}
            </Button>
          </div>
        </form>
      ) : null}
    </>
  );
}
