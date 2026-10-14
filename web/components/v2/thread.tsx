"use client";

import { ArrowRight, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";

import { cn } from "cn";
import { Mark } from "@/components/brand/logo";
import { IntentionDecision } from "@/components/decisions/intention-decision";
import { AgentsAction, AgentsDecision, PlanChecklist } from "@/components/intentions/agents-decision";
import { AnalysisResults } from "@/components/intentions/analysis-tab";
import { BriefView } from "@/components/intentions/brief";
import { useRights } from "@/components/intentions/journey";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { splitSaid } from "@/components/v2/said";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { useIntentionRuns } from "@/lib/agent-runs-queries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { may } from "@/lib/intentions/journey";
import { useAnalyseAgain, useAnswer, useIntention } from "@/lib/intentions/queries";
import { SPINNING } from "@/lib/motion";
import { notify } from "@/lib/notify";

type State = IntentionDetail["journey"]["state"];

/** What LEKA has to say, by where the request stands (LEKA-443's states). */
const READING: ReadonlySet<State> = new Set(["draft", "ready", "analysing"]);
const ANSWERED: ReadonlySet<State> = new Set([
  "analysis_partial",
  "result_available",
  "decision_required",
]);
const ACTING: ReadonlySet<State> = new Set([
  "approved",
  "action_running",
  "action_failed",
  "to_verify",
  "done",
]);

/**
 * The exchange under the bar (2026-10-14, the product call's Lot 6): what
 * the person said — the request, then each detail — and what LEKA answers,
 * as it stands. Answered, its agents are proposed with Lot 1's logic and
 * bought with Lot 2's; launched, their work and deliverables follow here.
 * Every answer rests on the connected sources: LEKA is not a chat about
 * anything (Lot 0).
 */
export function Thread({ id }: { id: string }) {
  const t = useDictionary();
  const w = t.v2.thread;
  const intention = useIntention(id);
  if (intention.isError) {
    return <ErrorState error={intention.error} onRetry={() => void intention.refetch()} />;
  }
  const data = intention.data;
  if (!data) return <div className="h-32 animate-pulse rounded-2xl bg-white" aria-hidden="true" />;
  return (
    <section aria-label={w.label} className="space-y-4" data-testid="v2-thread" data-state={data.journey.state}>
      {splitSaid(data.text).map((said, index) => (
        <You key={index}>{said}</You>
      ))}
      <Leka>
        <Answer intention={data} />
      </Leka>
      <p className="text-end text-[0.8125rem]">
        <Link
          href={routes.intention(data.id)}
          className="inline-flex items-center gap-1 font-medium text-brand-violet hover:underline"
          data-testid="v2-detail"
        >
          {w.detail}
          <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
        </Link>
      </p>
    </section>
  );
}

function You({ children }: { children: React.ReactNode }) {
  const w = useDictionary().v2.thread;
  return (
    <div className="flex justify-end" data-testid="v2-said">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-violet px-4 py-2.5 text-[0.9375rem] whitespace-pre-line text-white">
        <span className="sr-only">{w.you} : </span>
        <span dir="auto">{children}</span>
      </div>
    </div>
  );
}

function Leka({ children }: { children: React.ReactNode }) {
  const w = useDictionary().v2.thread;
  return (
    <div className="flex items-start gap-3" data-testid="v2-leka">
      <span className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-shell-line">
        <Mark className="h-3.5" title={w.leka} />
      </span>
      <div className="min-w-0 flex-1 space-y-4">{children}</div>
    </div>
  );
}

function Answer({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.v2.thread;
  const state = intention.journey.state;
  const runs = useIntentionRuns(intention.id);

  if (state === "needs_clarification") return <Clarify intention={intention} />;
  if (READING.has(state)) {
    return (
      <Said testId="v2-reading">
        <Loader2 className={cn("size-4 text-brand-violet", SPINNING)} aria-hidden="true" />
        {w.reading}
      </Said>
    );
  }
  if (state === "analysis_failed") return <Failed intention={intention} />;
  if (ANSWERED.has(state)) {
    return (
      <>
        <AnalysisResults intention={intention} />
        <IntentionDecision intentionId={intention.id} />
        {/* Its agents, or by hand — the thread stays where it is; a
            purchase comes back here (Lot 2). */}
        <AgentsDecision intention={intention} onDone={() => undefined} back="home" />
      </>
    );
  }
  if (ACTING.has(state)) {
    const path = intention.journey.path;
    return (
      <>
        <AnalysisResults intention={intention} />
        {path === "self" ? (
          <PlanChecklist intention={intention} />
        ) : path === "agents" || runs.data?.length ? (
          <AgentsAction intention={intention} />
        ) : (
          <Said>{w.working}</Said>
        )}
      </>
    );
  }
  return <Said testId="v2-ended">{w.ended}</Said>;
}

function Said({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return (
    <p
      className="flex items-center gap-2 rounded-2xl rounded-tl-md bg-white px-4 py-3 text-[0.9375rem] text-brand-navy ring-1 ring-shell-line"
      data-testid={testId}
    >
      {children}
    </p>
  );
}

/** What LEKA must know before it answers, asked here and answered here. */
function Clarify({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.v2.thread;
  const answer = useAnswer(intention.id);
  const rights = useRights(intention);
  const answerable = may(intention.journey, "answer", rights);
  return (
    <>
      <Said testId="v2-clarify">{w.clarify}</Said>
      {intention.brief && intention.understanding ? (
        <BriefView
          brief={intention.brief}
          understanding={intention.understanding}
          answers={intention.answers ?? []}
          pending={answer.isPending}
          onAnswer={
            answerable
              ? (given) =>
                  answer.mutate([given], {
                    onSuccess: () => notify.success({ title: w.sent }),
                    onError: (error) =>
                      notify.error({
                        title: error instanceof ApiError ? error.message : String(error),
                      }),
                  })
              : undefined
          }
        />
      ) : null}
    </>
  );
}

function Failed({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.v2.thread;
  const again = useAnalyseAgain(intention.id);
  const rights = useRights(intention);
  return (
    <div className="space-y-2 rounded-2xl rounded-tl-md bg-white px-4 py-3 ring-1 ring-shell-line" data-testid="v2-failed">
      <p className="text-[0.9375rem] text-brand-navy">{w.failed}</p>
      {intention.journey.reason ? (
        <p className="text-[0.8125rem] text-shell-muted">{intention.journey.reason}</p>
      ) : null}
      {may(intention.journey, "analyse_again", rights) ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={again.isPending}
          onClick={() =>
            again.mutate(undefined, {
              onSuccess: () => notify.success({ title: w.retried }),
              onError: (error) =>
                notify.error({ title: error instanceof ApiError ? error.message : String(error) }),
            })
          }
          data-testid="v2-retry"
        >
          <RotateCcw className="size-4" aria-hidden="true" />
          {w.retry}
        </Button>
      ) : null}
    </div>
  );
}
