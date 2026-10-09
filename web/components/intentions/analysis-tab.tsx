"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Layers,
  LoaderCircle,
  type LucideIcon,
  RotateCw,
  ScanSearch,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
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
import { ReadsCard } from "@/components/intentions/reads-card";
import { AnalysisState, AnalysisView, EvidenceList, Pill } from "@/components/intelligence";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  analysisEvidence,
  capabilityName,
  type IntentionAnalysis,
  intentionAnalysis,
  type Links,
} from "@/lib/intention-analysis";
import type { Finding } from "@/lib/insights";
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
  const { locale } = useLocale();
  return useMemo(
    () => ({
      href: entityHref,
      typeName: (type: string) => typeLabel(t, type),
      date: (iso: string) => exactDate(locale, iso),
      // What LEKA concluded, said as Insights says it (LEKA-377 to 383).
      finding: (code: string, params: Record<string, unknown>, statement: string) =>
        word(t, { code, params, statement } as unknown as Finding),
    }),
    [t, locale],
  );
}

/** Whether one is on its way: the intention analysing, and no analysis
 * finished on its current context yet. */
function onItsWay(intention: IntentionDetail, analysis: IntentionAnalysis | null | undefined) {
  if (intention.status !== "analysing" || intention.archived_at) return false;
  if (!analysis) return true;
  return analysis.status === "running" || analysis.context_id !== intention.context_id;
}

/** Its asker, or who may approve, while it can be analysed again. */
function useMayAnalyse(intention: IntentionDetail): boolean {
  const me = useCurrentUser();
  const steward = usePermissions()?.includes("intention:approve") ?? false;
  const yours = Boolean(me?.id) && intention.created_by === me?.id;
  return (
    (yours || steward) &&
    !intention.archived_at &&
    (intention.status === "failed" || intention.status === "analysing")
  );
}

/** Its analysis read, read again while on its way; once one finishes, the
 * intention — which it moved — read again too. */
function useAnalysisOf(intention: IntentionDetail) {
  const client = useQueryClient();
  const analysis = useIntentionAnalysis(intention.id, (data) => onItsWay(intention, data));
  const live = onItsWay(intention, analysis.data);
  // Which analysis it is, and whether finished: once read, a change to a
  // finished one is an analysis that just ended.
  const seen = useRef<string | undefined>(undefined);
  const data = analysis.data;
  const finished = data?.finished_at ?? null;
  const state = data === undefined ? undefined : `${data?.id ?? "none"}:${finished ?? "on its way"}`;
  useEffect(() => {
    if (state === undefined) return;
    if (seen.current !== undefined && seen.current !== state && finished) {
      void client.invalidateQueries({ queryKey: intentionKeys.one(intention.id) });
      void client.invalidateQueries({ queryKey: intentionKeys.history(intention.id) });
      void client.invalidateQueries({ queryKey: intentionKeys.analyses(intention.id) });
    }
    seen.current = state;
  }, [state, finished, client, intention.id]);
  return { analysis, live };
}

function AgainButton({ intention, label }: { intention: IntentionDetail; label: string }) {
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
          notify.error({ title: error instanceof ApiError ? error.message : String(error) });
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
};

function seconds(analysis: IntentionAnalysis): string | null {
  if (!analysis.finished_at) return null;
  const ms = new Date(analysis.finished_at).getTime() - new Date(analysis.started_at).getTime();
  return (Math.max(ms, 0) / 1000).toFixed(1);
}

/** "Analyse n° 2 · relancée par une personne · il y a 3 min · en 1.2 s ·
 * contexte v3". */
function MetaLine({ analysis }: { analysis: IntentionAnalysis }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.intentions.analysis;
  const took = seconds(analysis);
  const parts = [
    fill(w.number, { number: analysis.number }),
    w.triggers[analysis.trigger],
    timeAgo(t, analysis.started_at),
    took ? fill(w.took, { seconds: took }) : null,
    analysis.context_version ? fill(w.context, { version: analysis.context_version }) : null,
  ].filter(Boolean);
  return (
    <p className="text-[0.8125rem] text-shell-muted" data-testid="analysis-meta">
      <time dateTime={analysis.started_at} title={exactDate(locale, analysis.started_at)}>
        {parts.join(" · ")}
      </time>
    </p>
  );
}

const STEP_LOOK: Record<Step["status"], { icon: LucideIcon; tone: TileTone }> = {
  succeeded: { icon: CircleCheck, tone: "success" },
  failed: { icon: CircleX, tone: "danger" },
  timed_out: { icon: Clock, tone: "warning" },
  skipped: { icon: CircleDashed, tone: "neutral" },
};

/** Where each capability stood in the plan (LEKA-399): planned by the
 * analysis, else read off its step — an analysis kept before has none. */
function levelOf(analysis: IntentionAnalysis, name: string, step: Step | undefined): number {
  const planned = (analysis.detail?.orchestration as { steps?: Record<string, { level?: number }> })
    ?.steps?.[name]?.level;
  return typeof planned === "number" ? planned : (step?.level ?? 0);
}

/** Each capability chosen, why, and how it went — those still to run, on
 * their way — level by level, as LEKA orchestrated them (LEKA-399): what
 * ran together, what each was handed, ran without, stood in for. */
function StepsCard({ analysis }: { analysis: IntentionAnalysis }) {
  const t = useDictionary();
  const w = t.intentions.analysis.steps;
  const ran = new Map(analysis.steps.map((step) => [step.name, step]));
  const chosen = analysis.selection.filter((choice) => choice.chosen || ran.has(choice.name));
  // A fallback ran in another's place: shown beside it.
  const standIns = analysis.steps.filter((step) => step.fallback_of);
  const rows = [
    ...chosen.map((choice) => ({ name: choice.name, reason: choice.reason, method: choice.method })),
    ...standIns.map((step) => ({ name: step.name, reason: "fallback", method: "rules" })),
  ];
  const levels = new Map<number, typeof rows>();
  for (const row of rows) {
    const level = levelOf(analysis, row.name, ran.get(row.name));
    levels.set(level, [...(levels.get(level) ?? []), row]);
  }
  const ordered = [...levels.entries()].sort(([a], [b]) => a - b);
  const last = ordered.length ? ordered[ordered.length - 1][0] : 0;
  const names = (list: readonly string[]) => list.map((n) => capabilityName(t, n)).join(", ");
  return (
    <Card title={w.title} icon={<Layers className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="flex flex-col gap-3" data-testid="analysis-steps">
        {ordered.map(([level, members]) => (
          <section key={level} data-testid="analysis-level" data-level={level}>
            {ordered.length > 1 ? (
              <p className="text-xs font-semibold tracking-wide text-shell-nav uppercase">
                {level === last && members.every((m) => m.method === "model")
                  ? w.conclusion
                  : fill(w.level, { n: level + 1 }) + (members.length > 1 ? ` · ${w.together}` : "")}
              </p>
            ) : null}
            <ul className="divide-y divide-shell-line/60">
              {members.map((row) => {
                const step = ran.get(row.name);
                const look = step ? STEP_LOOK[step.status] : null;
                const Icon = look?.icon ?? LoaderCircle;
                const reason = step?.reason ?? row.reason;
                const notes = [
                  step?.fallback_of
                    ? fill(w.fallbackOf, { name: capabilityName(t, step.fallback_of) })
                    : null,
                  step?.handed?.length ? fill(w.handed, { names: names(step.handed) }) : null,
                  step?.degraded?.length ? fill(w.degraded, { names: names(step.degraded) }) : null,
                  step?.reason === "upstream" && step.error
                    ? fill(w.waitedOn, { names: names(step.error.split(", ")) })
                    : null,
                ].filter(Boolean);
                return (
                  <li
                    key={row.name}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[0.8125rem]"
                    data-testid="analysis-step"
                    data-name={row.name}
                    data-status={step?.status ?? "running"}
                  >
                    <Icon
                      className={cn(
                        "size-4 shrink-0",
                        step ? undefined : "text-shell-nav-active motion-safe:animate-spin",
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
                          {(w.reasons as Record<string, string>)[reason] ?? reason}
                        </span>
                      ) : null}
                      {notes.length ? (
                        <span className="block text-xs text-shell-muted" data-testid="analysis-step-notes">
                          {notes.join(" · ")}
                        </span>
                      ) : null}
                      {step?.error && step.reason !== "upstream" ? (
                        <span className="block text-xs text-state-danger">
                          {fill(w.error, { error: step.error })}
                        </span>
                      ) : null}
                    </span>
                    <Pill tone={look?.tone ?? "violet"}>{w.statuses[step?.status ?? "running"]}</Pill>
                    {step && step.status !== "skipped" ? (
                      <span className="w-16 text-right text-xs tabular-nums text-shell-muted">
                        {step.duration_ms ? fill(w.ms, { ms: step.duration_ms }) : w.instant}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
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
      icon={<ScanSearch className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <ol className="space-y-1.5 text-[0.8125rem]" data-testid="analysis-previous">
        {analyses.data.map((analysis) => (
          <li key={analysis.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-brand-navy">
              {fill(w.number, { number: analysis.number })}
            </span>
            <Pill tone={RESULT_TONES[analysis.status]}>{w.statuses[analysis.status]}</Pill>
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
  const tone: TileTone = analysis && !live ? RESULT_TONES[analysis.status] : "violet";
  const again =
    may && (intention.status === "failed" || (!live && analysis?.status === "blocked"))
      ? w.again
      : may && waiting && !analysis
        ? w.now
        : null;
  return (
    <section
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4 sm:flex-row sm:items-center"
      data-testid="analysis-head"
      data-live={live ? "true" : "false"}
    >
      <IconTile icon={running ? LoaderCircle : ShieldCheck} tone={tone} className="size-11" />
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
export function SummarySaid({ intention, none }: { intention: IntentionDetail; none: string }) {
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
        summary ? "text-[0.9375rem] text-brand-navy" : "text-[0.875rem] text-shell-muted"
      }
      data-testid="intention-summary"
    >
      {summary ?? none}
    </p>
  );
}

/** The analysis answered in words by a model (LEKA-394): what it says,
 * each point and how much it rests on, who wrote it. */
function AnswerCard({ answer }: { answer: AnalysisAnswer }) {
  const t = useDictionary();
  const w = t.intentions.analysis.answer;
  return (
    <Card
      title={w.title}
      icon={<Sparkles className="size-4 text-shell-nav-active" aria-hidden="true" />}
    >
      <div className="flex flex-col gap-2" data-testid="analysis-answer">
        <p className="text-[0.9375rem] text-brand-navy">{answer.text}</p>
        {answer.points.length ? (
          <ul className="flex flex-col gap-1.5 text-[0.8125rem] text-brand-navy">
            {answer.points.map((point) => (
              <li key={point.text} className="flex flex-wrap items-baseline gap-2" data-testid="answer-point">
                <span className="min-w-0 flex-1">{point.text}</span>
                <Pill tone="neutral">{fill(w.rests, { count: String(point.cites.length) })}</Pill>
              </li>
            ))}
          </ul>
        ) : null}
        {answer.caveats.length ? (
          <div className="text-[0.8125rem]">
            <p className="font-semibold text-brand-navy">{w.caveats}</p>
            <ul className="list-disc pl-5 text-shell-muted">
              {answer.caveats.map((caveat) => (
                <li key={caveat}>{caveat}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="text-xs text-shell-muted">{fill(w.by, { model: modelTitle(answer.model) })}</p>
      </div>
    </Card>
  );
}

// ── the tabs ─────────────────────────────────────────────────────────────

function Loading() {
  return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
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

export function AnalysisTab({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.analysis;
  const links = useLinks();
  const { analysis, live } = useAnalysisOf(intention);
  const data = analysis.data;
  const shown = useMemo(() => (data ? intentionAnalysis(t, data, links) : null), [data, t, links]);
  if (analysis.isError) {
    return <ErrorState error={analysis.error} onRetry={() => void analysis.refetch()} />;
  }
  if (data === undefined) return <Loading />;
  if (data === null && !live) return <Nothing title={w.none} body={w.noneBody} />;
  return (
    <div className="space-y-4" data-testid="intention-analysis">
      <Head intention={intention} analysis={data} live={live} />
      {data?.status === "blocked" ? (
        <>
          <div
            role="status"
            className="flex items-start gap-3 rounded-xl bg-state-danger-soft px-4 py-3 text-[0.8125rem]"
            data-testid="analysis-blocked"
          >
            <AlertOctagon className="mt-0.5 size-4 shrink-0 text-state-danger" aria-hidden="true" />
            <div className="min-w-0 text-brand-navy">
              <p className="font-semibold">{w.blocked}</p>
              <p className="text-shell-muted">{w.blockedBody}</p>
            </div>
          </div>
          {intention.readiness ? <ReadinessPanel readiness={intention.readiness} /> : null}
        </>
      ) : data ? (
        <>
          {data.result?.answer ? <AnswerCard answer={data.result.answer} /> : null}
          <ReadsCard intentionId={intention.id} analysis={data} />
          <StepsCard analysis={data} />
          {data.status === "running" ? (
            <AnalysisState status="running" />
          ) : shown ? (
            <AnalysisView
              analysis={shown}
              // What LEKA proposes (LEKA-389), apart from what it found —
              // drawn when it proposes something.
              proposals={shown.recommendations.length > 0}
              level={2}
            />
          ) : null}
        </>
      ) : null}
      <PreviousCard intentionId={intention.id} />
    </div>
  );
}

export function EvidenceTab({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.analysis.evidence;
  const links = useLinks();
  const { analysis } = useAnalysisOf(intention);
  const result = analysis.data?.result ?? null;
  const items = useMemo(
    () => (result ? analysisEvidence(t, result, links) : []),
    [result, t, links],
  );
  if (analysis.isError) {
    return <ErrorState error={analysis.error} onRetry={() => void analysis.refetch()} />;
  }
  if (analysis.data === undefined) return <Loading />;
  return (
    <Card
      title={w.title}
      icon={<ShieldCheck className="size-4 text-shell-muted" aria-hidden="true" />}
      action={items.length ? <Pill tone="neutral">{items.length}</Pill> : undefined}
    >
      <div className="space-y-3" data-testid="intention-evidence">
        <p className="text-[0.8125rem] text-shell-muted">{result ? w.body : w.noAnalysis}</p>
        {result ? <EvidenceList items={items} /> : null}
      </div>
    </Card>
  );
}
