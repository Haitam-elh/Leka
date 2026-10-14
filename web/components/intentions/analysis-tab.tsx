"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  ArrowRight,
  ChevronDown,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  History,
  Layers,
  LoaderCircle,
  type LucideIcon,
  RotateCw,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef } from "react";

import { cn } from "cn";

import {
  Card,
  entityHref,
  IconTile,
  type TileTone,
  typeLabel,
} from "@/components/environment/parts";
import { word } from "@/components/insights/leka-insights";
import { ReadinessPanel } from "@/components/intentions/readiness";
import { NextSteps } from "@/components/intentions/decision-step";
import { FeasibilityCard } from "@/components/intentions/feasibility";
import { ReadsCard } from "@/components/intentions/reads-card";
import { ScopeCard } from "@/components/intentions/scope";
import {
  AnalysisState,
  AnalysisView,
  ConfidencePanel,
  EvidenceList,
  FindingList,
  ImpactPanel,
  IntelligenceSection,
  Pill,
} from "@/components/intelligence";
import { useRights } from "@/components/intentions/journey";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { ErrorState } from "@/components/states/error-state";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { may } from "@/lib/intentions/journey";
import {
  analysisEvidence,
  capabilityName,
  type IntentionAnalysis,
  intentionAnalysis,
  type Links,
} from "@/lib/intention-analysis";
import type { Finding } from "@/lib/insights";
import type { Analysis } from "@/lib/intelligence";
import type { IntentionDetail } from "@/lib/intentions/api";
import type { components } from "@/lib/api-types";
import {
  intentionKeys,
  useAnalyseAgain,
  useIntentionAnalyses,
  useIntentionAnalysis,
} from "@/lib/intentions/queries";
import { modelTitle } from "@/lib/models";
import { notify } from "@/lib/notify";

type AnalysisAnswer = components["schemas"]["AnalysisAnswer"];

/**
 * An intention's analysis (LEKA-388), its tabs Analyse and Preuves.
 *
 *     Analyse   how it went — which analysis, why it ran, when, how long,
 *               on which version of its context — its answer and what
 *               LEKA read for it (LEKA-396) — then each capability
 *               LEKA mobilised, why, and how it went: done, failed, timed
 *               out, not run; then what it found, laid out as every
 *               analysis is (mockup 04, LEKA-341) — without proposals,
 *               which LEKA-389 makes and a person decides (LEKA-390).
 *               While one is on its way, mockup 03's "LEKA analyse votre
 *               demande", read again every few seconds; blocked, what its
 *               context lacks; failed, a way to run it again.
 *     Preuves   every piece of evidence it collected, where each came
 *               from — the source, the record, LEKA's rule — and which
 *               capability cites it.
 *
 * Nothing is shown that the API did not say.
 */

type Step = IntentionAnalysis["steps"][number];

function useLinks(): Links {
  const t = useDictionary();
  const { format: locale } = useLocale();
  return useMemo(
    () => ({
      href: entityHref,
      typeName: (type: string) => typeLabel(t, type),
      date: (iso: string) => exactDate(locale, iso),
      // What LEKA concluded, said as Insights says it (LEKA-377 to 383).
      finding: (
        code: string,
        params: Record<string, unknown>,
        statement: string,
      ) => word(t, { code, params, statement } as unknown as Finding),
    }),
    [t, locale],
  );
}

/** Whether one is on its way, as its journey says (LEKA-443): queued, or an
 * analysis of this attempt running — its analysis read again till then. */
function onItsWay(intention: IntentionDetail) {
  const { state, reason } = intention.journey;
  if (intention.archived_at) return false;
  return state === "analysing" || (state === "ready" && reason === "queued");
}

/** Its asker, or who may approve, while its state lets it be analysed
 * again. */
function useMayAnalyse(intention: IntentionDetail): boolean {
  const rights = useRights(intention);
  return may(intention.journey, "analyse_again", rights);
}

/** An analysis that is not its result (LEKA-443): stopped, or of a version
 * of the request asked again since — said so, never drawn as its result. */
function NotCurrent({ analysis }: { analysis: IntentionAnalysis }) {
  const t = useDictionary();
  const w = t.intentions.journey;
  const stopped = analysis.status === "stopped";
  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-xl bg-shell-canvas px-4 py-3 text-[0.8125rem]"
      data-testid="analysis-not-current"
      data-why={stopped ? "stopped" : "replaced"}
    >
      <History className="mt-0.5 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
      <div className="min-w-0 text-brand-navy">
        <p className="font-semibold">
          {stopped ? w.states.ready : w.replacedTitle}
        </p>
        <p className="text-shell-muted">
          {stopped
            ? w.stoppedAnalysis
            : fill(w.replaced, { version: analysis.intention_version ?? 1 })}
        </p>
      </div>
    </div>
  );
}

/** Its analysis read, read again while on its way; once one finishes, the
 * intention — which it moved — read again too. */
function useAnalysisOf(intention: IntentionDetail) {
  const client = useQueryClient();
  const analysis = useIntentionAnalysis(intention.id, () => onItsWay(intention));
  const live = onItsWay(intention);
  // Which analysis it is, and whether finished: once read, a change to a
  // finished one is an analysis that just ended.
  const seen = useRef<string | undefined>(undefined);
  const data = analysis.data;
  const finished = data?.finished_at ?? null;
  const state =
    data === undefined
      ? undefined
      : `${data?.id ?? "none"}:${finished ?? "on its way"}`;
  useEffect(() => {
    if (state === undefined) return;
    if (seen.current !== undefined && seen.current !== state && finished) {
      void client.invalidateQueries({
        queryKey: intentionKeys.one(intention.id),
      });
      void client.invalidateQueries({
        queryKey: intentionKeys.history(intention.id),
      });
      void client.invalidateQueries({
        queryKey: intentionKeys.analyses(intention.id),
      });
    }
    seen.current = state;
  }, [state, finished, client, intention.id]);
  return { analysis, live };
}

function AgainButton({
  intention,
  label,
}: {
  intention: IntentionDetail;
  label: string;
}) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  const again = useAnalyseAgain(intention.id);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={again.isPending}
      data-testid="analysis-again"
      onClick={async () => {
        try {
          const { queued } = await again.mutateAsync();
          notify.success({ title: queued ? w.queued : w.already });
        } catch (error) {
          notify.error({
            title: error instanceof ApiError ? error.message : String(error),
          });
        }
      }}
    >
      <RotateCw className="size-4" aria-hidden="true" />
      {label}
    </Button>
  );
}

// ── how it went ──────────────────────────────────────────────────────────

const RESULT_TONES: Record<IntentionAnalysis["status"], TileTone> = {
  running: "violet",
  complete: "success",
  partial: "warning",
  inconclusive: "info",
  failed: "danger",
  blocked: "danger",
  stopped: "neutral",
};

function seconds(analysis: IntentionAnalysis): string | null {
  if (!analysis.finished_at) return null;
  const ms =
    new Date(analysis.finished_at).getTime() -
    new Date(analysis.started_at).getTime();
  return (Math.max(ms, 0) / 1000).toFixed(1);
}

/** "Analyse n° 2 · relancée par une personne · il y a 3 min · en 1.2 s ·
 * contexte v3". */
function MetaLine({ analysis }: { analysis: IntentionAnalysis }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intentions.analysis;
  const took = seconds(analysis);
  const parts = [
    fill(w.number, { number: analysis.number }),
    w.triggers[analysis.trigger],
    timeAgo(t, analysis.started_at),
    took ? fill(w.took, { seconds: took }) : null,
    analysis.context_version
      ? fill(w.context, { version: analysis.context_version })
      : null,
  ].filter(Boolean);
  return (
    <p
      className="text-[0.8125rem] text-shell-muted"
      data-testid="analysis-meta"
    >
      <time
        dateTime={analysis.started_at}
        title={exactDate(locale, analysis.started_at)}
      >
        {parts.join(" · ")}
      </time>
    </p>
  );
}

const STEP_LOOK: Record<Step["status"], { icon: LucideIcon; tone: TileTone }> =
  {
    succeeded: { icon: CircleCheck, tone: "success" },
    failed: { icon: CircleX, tone: "danger" },
    timed_out: { icon: Clock, tone: "warning" },
    skipped: { icon: CircleDashed, tone: "neutral" },
  };

/** Where each capability stood in the plan (LEKA-399): planned by the
 * analysis, else read off its step — an analysis kept before has none. */
function levelOf(
  analysis: IntentionAnalysis,
  name: string,
  step: Step | undefined,
): number {
  const planned = (
    analysis.detail?.orchestration as {
      steps?: Record<string, { level?: number }>;
    }
  )?.steps?.[name]?.level;
  return typeof planned === "number" ? planned : (step?.level ?? 0);
}

/** Each capability chosen, why, and how it went — those still to run, on
 * their way — level by level, as LEKA orchestrated them (LEKA-399): what
 * ran together, what each was handed, ran without, stood in for. */
function StepsCard({ analysis }: { analysis: IntentionAnalysis }) {
  const t = useDictionary();
  const w = t.intentions.analysis.steps;
  const ran = new Map(analysis.steps.map((step) => [step.name, step]));
  const chosen = analysis.selection.filter(
    (choice) => choice.chosen || ran.has(choice.name),
  );
  // A fallback ran in another's place: shown beside it.
  const standIns = analysis.steps.filter((step) => step.fallback_of);
  const rows = [
    ...chosen.map((choice) => ({
      name: choice.name,
      reason: choice.reason,
      method: choice.method,
    })),
    ...standIns.map((step) => ({
      name: step.name,
      reason: "fallback",
      method: "rules",
    })),
  ];
  const levels = new Map<number, typeof rows>();
  for (const row of rows) {
    const level = levelOf(analysis, row.name, ran.get(row.name));
    levels.set(level, [...(levels.get(level) ?? []), row]);
  }
  const ordered = [...levels.entries()].sort(([a], [b]) => a - b);
  const last = ordered.length ? ordered[ordered.length - 1][0] : 0;
  const names = (list: readonly string[]) =>
    list.map((n) => capabilityName(t, n)).join(", ");
  // How LEKA worked is there on asking: open by itself when a step did not
  // succeed — the one time it is what to read (LEKA-438).
  const allDone =
    analysis.steps.length > 0 &&
    analysis.steps.every((step) => step.status === "succeeded");
  return (
    <Card
      title={w.title}
      icon={<Layers className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <details
        open={!allDone}
        className="group"
        data-testid="analysis-steps-fold"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded text-[0.8125rem] text-shell-muted outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40">
          <span>
            {allDone ? fill(w.allDone, { count: rows.length }) : w.someNot}
          </span>
          <span className="flex items-center gap-1 font-medium text-shell-nav-active">
            {w.show}
            <ChevronDown
              className="size-3.5 transition-transform group-open:rotate-180"
              aria-hidden="true"
            />
          </span>
        </summary>
        <div className="mt-3 flex flex-col gap-3" data-testid="analysis-steps">
          {ordered.map(([level, members]) => (
            <section
              key={level}
              data-testid="analysis-level"
              data-level={level}
            >
              {ordered.length > 1 ? (
                <p className="text-xs font-semibold tracking-wide text-shell-nav uppercase">
                  {level === last && members.every((m) => m.method === "model")
                    ? w.conclusion
                    : fill(w.level, { n: level + 1 }) +
                      (members.length > 1 ? ` · ${w.together}` : "")}
                </p>
              ) : null}
              <ul className="mt-2 grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
                {members.map((row) => {
                  const step = ran.get(row.name);
                  const look = step ? STEP_LOOK[step.status] : null;
                  const Icon = look?.icon ?? LoaderCircle;
                  const reason = step?.reason ?? row.reason;
                  const notes = [
                    step?.fallback_of
                      ? fill(w.fallbackOf, {
                          name: capabilityName(t, step.fallback_of),
                        })
                      : null,
                    step?.handed?.length
                      ? fill(w.handed, { names: names(step.handed) })
                      : null,
                    step?.degraded?.length
                      ? fill(w.degraded, { names: names(step.degraded) })
                      : null,
                    step?.reason === "upstream" && step.error
                      ? fill(w.waitedOn, {
                          names: names(step.error.split(", ")),
                        })
                      : null,
                  ].filter(Boolean);
                  return (
                    <li
                      key={row.name}
                      className="flex flex-col gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]"
                      data-testid="analysis-step"
                      data-name={row.name}
                      data-status={step?.status ?? "running"}
                    >
                      <span className="flex min-w-0 items-start gap-2">
                        <Icon
                          className={cn(
                            "mt-0.5 size-4 shrink-0",
                            step
                              ? undefined
                              : "text-shell-nav-active motion-safe:animate-spin",
                            look?.tone === "success" && "text-state-success",
                            look?.tone === "danger" && "text-state-danger",
                            look?.tone === "warning" && "text-state-warning",
                            look?.tone === "neutral" && "text-shell-muted",
                          )}
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="font-medium text-brand-navy">
                            {capabilityName(t, row.name)}
                          </span>
                          {reason !== "fallback" ? (
                            <span className="text-shell-muted">
                              {" · "}
                              {(w.reasons as Record<string, string>)[reason] ??
                                reason}
                            </span>
                          ) : null}
                          {notes.length ? (
                            <span
                              className="block text-xs text-shell-muted"
                              data-testid="analysis-step-notes"
                            >
                              {notes.join(" · ")}
                            </span>
                          ) : null}
                          {step?.error && step.reason !== "upstream" ? (
                            <span className="block text-xs text-state-danger">
                              {fill(w.error, { error: step.error })}
                            </span>
                          ) : null}
                        </span>
                      </span>
                      <span className="mt-auto flex items-center justify-between gap-2">
                        <Pill tone={look?.tone ?? "violet"}>
                          {w.statuses[step?.status ?? "running"]}
                        </Pill>
                        {step && step.status !== "skipped" ? (
                          <span className="text-xs tabular-nums text-shell-muted">
                            {step.duration_ms
                              ? fill(w.ms, { ms: step.duration_ms })
                              : w.instant}
                          </span>
                        ) : null}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </details>
    </Card>
  );
}

/** Its analyses, the latest first: number, how each went, when. */
function PreviousCard({ intentionId }: { intentionId: string }) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  const analyses = useIntentionAnalyses(intentionId);
  if (!analyses.data || analyses.data.length < 2) return null;
  return (
    <Card
      title={w.previous}
      icon={
        <ScanSearch className="size-4 text-shell-muted" aria-hidden="true" />
      }
    >
      <ol
        className="space-y-1.5 text-[0.8125rem]"
        data-testid="analysis-previous"
      >
        {analyses.data.map((analysis) => (
          <li key={analysis.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-brand-navy">
              {fill(w.number, { number: analysis.number })}
            </span>
            <Pill tone={RESULT_TONES[analysis.status]}>
              {w.statuses[analysis.status]}
            </Pill>
            {analysis.intention_version ? (
              <span className="text-shell-muted">
                {fill(t.intentions.journey.version, { version: analysis.intention_version })}
              </span>
            ) : null}
            {!analysis.current && analysis.status !== "stopped" ? (
              <Pill tone="neutral" data-testid="analysis-replaced">
                {t.intentions.journey.replacedTitle}
              </Pill>
            ) : null}
            <span className="text-shell-muted">
              {w.triggers[analysis.trigger]} · {timeAgo(t, analysis.started_at)}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Mockup 03's head: LEKA analyses your request, or what it came to. */
function Head({
  intention,
  analysis,
  live,
}: {
  intention: IntentionDetail;
  analysis: IntentionAnalysis | null;
  live: boolean;
}) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  const may = useMayAnalyse(intention);
  const running = live && analysis?.status === "running";
  const waiting = live && !running;
  const title = running ? w.running : waiting ? w.waiting : w.title;
  const tone: TileTone =
    analysis && !live ? RESULT_TONES[analysis.status] : "violet";
  // Its state allows it (LEKA-443): failed, or not run, analysed again;
  // queued, started now rather than waited for.
  const again = !may
    ? null
    : intention.journey.state === "analysis_failed" || analysis?.status === "blocked"
      ? w.again
      : waiting
        ? w.now
        : null;
  return (
    <section
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4 sm:flex-row sm:items-center"
      data-testid="analysis-head"
      data-live={live ? "true" : "false"}
    >
      <IconTile
        icon={running ? LoaderCircle : ShieldCheck}
        tone={tone}
        className="size-11"
      />
      <div className="min-w-0 flex-1">
        <h2 className="text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy">
          {title}
        </h2>
        {running ? (
          <p className="text-[0.8125rem] text-shell-muted">{w.runningBody}</p>
        ) : waiting ? (
          <p className="text-[0.8125rem] text-shell-muted">{w.waitingBody}</p>
        ) : null}
        {analysis ? <MetaLine analysis={analysis} /> : null}
      </div>
      {analysis && !live ? (
        <Pill
          tone={RESULT_TONES[analysis.status]}
          data-testid="analysis-status"
          data-status={analysis.status}
        >
          {w.statuses[analysis.status]}
        </Pill>
      ) : null}
      {again ? <AgainButton intention={intention} label={again} /> : null}
    </section>
  );
}

/** What its analysis came to, in the reader's words — the intention's own
 * summary, as kept, until it is read; none, said so. */
export function SummarySaid({
  intention,
  none,
}: {
  intention: IntentionDetail;
  none: string;
}) {
  const t = useDictionary();
  const links = useLinks();
  const { analysis } = useAnalysisOf(intention);
  const data = analysis.data;
  const said = useMemo(
    () => (data?.result ? intentionAnalysis(t, data, links).summary : null),
    [data, t, links],
  );
  // Written by a model from the analysis (LEKA-394), when one could.
  const summary = data?.result?.answer?.text ?? said ?? intention.summary;
  return (
    <p
      className={
        summary
          ? "text-[0.9375rem] text-brand-navy"
          : "text-[0.875rem] text-shell-muted"
      }
      data-testid="intention-summary"
    >
      {summary ?? none}
    </p>
  );
}

/** The analysis answered in words by a model (LEKA-394), as the
 * synthesis says it (mockup 04): what it comes to, each point and how much
 * it rests on, its caveats, who wrote it. */
function AnswerSaid({ answer }: { answer: AnalysisAnswer }) {
  const t = useDictionary();
  const w = t.intentions.analysis.answer;
  return (
    <div className="mt-1 flex flex-col gap-2" data-testid="analysis-answer">
      <p className="text-[0.9375rem] text-brand-navy" dir="auto">
        {answer.text}
      </p>
      {answer.points.length ? (
        <ul className="flex flex-col gap-1.5 text-[0.8125rem] text-brand-navy">
          {answer.points.map((point) => (
            <li
              key={point.text}
              className="flex flex-wrap items-baseline gap-2"
              data-testid="answer-point"
            >
              <span className="min-w-0 flex-1" dir="auto">
                {point.text}
              </span>
              <Pill tone="neutral">
                {fill(w.rests, { count: String(point.cites.length) })}
              </Pill>
            </li>
          ))}
        </ul>
      ) : null}
      {answer.caveats.length ? (
        <div className="text-[0.8125rem]">
          <p className="font-semibold text-brand-navy">{w.caveats}</p>
          <ul className="list-disc ps-5 text-shell-muted">
            {answer.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-xs text-shell-muted">
        {fill(w.by, { model: modelTitle(answer.model) })}
      </p>
    </div>
  );
}

// ── the tabs ─────────────────────────────────────────────────────────────

function Loading() {
  return (
    <div
      className="h-64 animate-pulse rounded-xl bg-shell-canvas"
      aria-hidden="true"
    />
  );
}

function Nothing({ title, body }: { title: string; body: string }) {
  return (
    <div
      className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem]"
      data-testid="analysis-none"
    >
      <p className="font-semibold text-brand-navy">{title}</p>
      <p className="text-shell-muted">{body}</p>
    </div>
  );
}

/** Step 2, mockup 03: how the analysis goes or went. On the left LEKA at
 * work — each capability it mobilised, a card each, and the first of what
 * it found; on the right what it reads — what it consulted, how far its
 * context can ground it, the scope — and its earlier analyses. Its
 * conclusions are step 3's (AnalysisResults). */
export function AnalysisProgress({
  intention,
}: {
  intention: IntentionDetail;
}) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  const links = useLinks();
  const { analysis, live } = useAnalysisOf(intention);
  const data = analysis.data;
  const shown = useMemo(
    () => (data ? intentionAnalysis(t, data, links) : null),
    [data, t, links],
  );
  if (analysis.isError) {
    return (
      <ErrorState
        error={analysis.error}
        onRetry={() => void analysis.refetch()}
      />
    );
  }
  if (data === undefined) return <Loading />;
  if (data === null && !live)
    return <Nothing title={w.none} body={w.noneBody} />;
  return (
    <div
      className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start"
      data-testid="intention-analysis"
    >
      <div className="min-w-0 space-y-4">
        <Head intention={intention} analysis={data} live={live} />
        {data?.status === "blocked" ? (
          <>
            <div
              role="status"
              className="flex items-start gap-3 rounded-xl bg-state-danger-soft px-4 py-3 text-[0.8125rem]"
              data-testid="analysis-blocked"
            >
              <AlertOctagon
                className="mt-0.5 size-4 shrink-0 text-state-danger"
                aria-hidden="true"
              />
              <div className="min-w-0 text-brand-navy">
                <p className="font-semibold">{w.blocked}</p>
                <p className="text-shell-muted">{w.blockedBody}</p>
              </div>
            </div>
            {intention.readiness ? (
              <ReadinessPanel readiness={intention.readiness} />
            ) : null}
          </>
        ) : data ? (
          <>
            {!data.current && !live ? <NotCurrent analysis={data} /> : null}
            <StepsCard analysis={data} />
            {data.status === "running" ? (
              <AnalysisState status="running" />
            ) : shown?.status === "failed" ? (
              // What stopped it, said where it stopped: there are no results.
              <AnalysisState status="failed" missing={shown.missing} />
            ) : shown && shown.findings.length && data.current ? (
              <FirstFindings
                intentionId={intention.id}
                findings={shown.findings}
              />
            ) : null}
          </>
        ) : null}
      </div>
      <aside className="min-w-0 space-y-4" aria-label={w.title}>
        {data ? <ReadsCard intentionId={intention.id} analysis={data} /> : null}
        {intention.readiness && data?.status !== "blocked" ? (
          <ReadinessPanel readiness={intention.readiness} />
        ) : null}
        <ScopeCard intention={intention} />
        <PreviousCard intentionId={intention.id} />
      </aside>
    </div>
  );
}

/** Mockup 03's "Premiers constats": the first three of what it found, and
 * the way to all of it. */
function FirstFindings({
  intentionId,
  findings,
}: {
  intentionId: string;
  findings: Analysis["findings"];
}) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  return (
    <IntelligenceSection
      kind="fact"
      title={w.firstFindings}
      count={
        findings.length > 3
          ? fill(t.intelligence.findings.count, { count: findings.length })
          : undefined
      }
      level={2}
      action={
        <Link
          href={`${routes.intentions()}/${intentionId}/results`}
          className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-brand-violet hover:underline"
          data-testid="analysis-see-results"
        >
          {w.seeResults}
          <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
        </Link>
      }
    >
      <FindingList findings={findings.slice(0, 3)} />
    </IntelligenceSection>
  );
}

/** Step 3, mockup 04: what the analysis comes to — LEKA's answer, its
 * synthesis and confidence, what it found and on what evidence, what it
 * reaches, what it proposes. */
export function AnalysisResults({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  const links = useLinks();
  const may = useMayAnalyse(intention);
  const { analysis, live } = useAnalysisOf(intention);
  const data = analysis.data;
  const shown = useMemo(
    () => (data ? intentionAnalysis(t, data, links) : null),
    [data, t, links],
  );
  if (analysis.isError) {
    return (
      <ErrorState
        error={analysis.error}
        onRetry={() => void analysis.refetch()}
      />
    );
  }
  if (data === undefined) return <Loading />;
  if (!data || data.status === "running" || live) {
    return <AnalysisState status="running" />;
  }
  // Stopped, or of an earlier version: never its result (LEKA-443).
  if (!data.current) {
    return (
      <div className="space-y-4" data-testid="intention-results">
        <NotCurrent analysis={data} />
      </div>
    );
  }
  return (
    <div className="space-y-4" data-testid="intention-results">
      {shown ? (
        <AnalysisView
          analysis={shown}
          said={
            data.result?.answer ? (
              <AnswerSaid answer={data.result.answer} />
            ) : undefined
          }
          next={<ActOn intention={intention} analysis={shown} />}
          // Its context moved on since it read it: the way to read the
          // latest, said beside it (LEKA-441).
          again={may ? <AgainButton intention={intention} label={w.again} /> : undefined}
          proposals={shown.recommendations.length > 0}
          level={2}
        />
      ) : (
        <Nothing title={w.none} body={w.noneBody} />
      )}
    </div>
  );
}

/** A question answered whose analysis recommends acting: the way to act,
 * as a request of its own — analysed, then decided, as any other. Nothing
 * runs from here (LEKA-438: the results had no way on). */
function ActOn({
  intention,
  analysis,
}: {
  intention: IntentionDetail;
  analysis: Analysis;
}) {
  const w = useDictionary().intentions.analysis;
  const rank = { high: 0, medium: 1, low: 2 } as const;
  const first = [...analysis.recommendations].sort(
    (a, b) => rank[a.priority ?? "low"] - rank[b.priority ?? "low"],
  )[0];
  if (intention.status !== "completed" || !first) return null;
  return (
    <div className="space-y-1.5">
      <Link
        href={`${routes.intentionNew()}?q=${encodeURIComponent(first.title)}`}
        className={buttonVariants({ className: "w-full" })}
        data-testid="results-act"
      >
        {w.act}
      </Link>
      <p className="text-xs text-shell-muted">
        {fill(w.actBody, { title: first.title })}
      </p>
    </div>
  );
}

/** Step 4's side, mockup 05: what the decision rests on — what the
 * analysis says it reaches, how sure it is — and what follows a yes. */
export function DecisionAside({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const links = useLinks();
  const { analysis } = useAnalysisOf(intention);
  const data = analysis.data;
  const shown = useMemo(
    () => (data ? intentionAnalysis(t, data, links) : null),
    [data, t, links],
  );
  const said =
    shown && data?.current && shown.status !== "failed" && shown.status !== "pending";
  return (
    <aside
      className="min-w-0 space-y-4"
      aria-label={t.decision.aside}
      data-testid="decision-aside"
    >
      {said ? (
        <>
          <IntelligenceSection
            kind="impact"
            title={t.intelligence.impact.global}
            level={2}
          >
            <ImpactPanel impact={shown.impact} />
          </IntelligenceSection>
          <ConfidencePanel
            score={shown.confidence}
            support={shown.support}
            level={2}
          />
        </>
      ) : null}
      {/* What it takes to carry it through here (LEKA-439). */}
      <FeasibilityCard intentionId={intention.id} />
      <NextSteps />
    </aside>
  );
}

export function EvidenceTab({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.analysis.evidence;
  const links = useLinks();
  const { analysis } = useAnalysisOf(intention);
  // Its evidence is its current analysis's — never a replaced one's.
  const result = analysis.data?.current ? (analysis.data.result ?? null) : null;
  const items = useMemo(
    () => (result ? analysisEvidence(t, result, links) : []),
    [result, t, links],
  );
  if (analysis.isError) {
    return (
      <ErrorState
        error={analysis.error}
        onRetry={() => void analysis.refetch()}
      />
    );
  }
  if (analysis.data === undefined) return <Loading />;
  return (
    <Card
      title={w.title}
      icon={
        <ShieldCheck className="size-4 text-shell-muted" aria-hidden="true" />
      }
      action={
        items.length ? <Pill tone="neutral">{items.length}</Pill> : undefined
      }
    >
      <div className="space-y-3" data-testid="intention-evidence">
        <p className="text-[0.8125rem] text-shell-muted">
          {result ? w.body : w.noAnalysis}
        </p>
        {result ? <EvidenceList items={items} /> : null}
      </div>
    </Card>
  );
}
