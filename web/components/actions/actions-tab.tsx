"use client";

import {
  CalendarClock,
  Check,
  CircleCheck,
  CircleDashed,
  CircleX,
  ListChecks,
  LoaderCircle,
  type LucideIcon,
  Play,
  RotateCw,
  ShieldCheck,
  Square,
  UserRound,
  Webhook,
} from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { ExpectedOutcome, ImpactBanner, VerificationCard } from "@/components/actions/outcome";
import { actionWord } from "@/components/decisions/decision-card";
import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { browserZone, type Plan, type PlanEvent, type PlanStep } from "@/lib/actions";
import { usePlanAction, usePlans } from "@/lib/actions-queries";
import { ApiError } from "@/lib/api";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { notify } from "@/lib/notify";
import type { Verification } from "@/lib/outcomes";
import { useVerifications } from "@/lib/outcomes-queries";
import { SPINNING } from "@/lib/motion";

/**
 * An intention's tab Actions (LEKA-391), as mockup 06: what an approved
 * decision became — each action, who runs it (an authorized system, or a
 * person), how it went step by step — preparation, execution, verification,
 * finalisation — what shows it, and everything that happened, in a log.
 * Who may approve prepares, runs or schedules it, confirms what waits on a
 * person, stops it, retries what failed; anyone else follows it. Read
 * again every few seconds while it runs.
 *
 * Its outcome (LEKA-392): what should be true once it ran, set before it
 * runs; then whether it came, read again while it is verified; and, as the
 * mockup ends, its whole story one click away.
 */

const PLAN_TONES: Record<Plan["status"], TileTone> = {
  planned: "violet",
  scheduled: "info",
  running: "violet",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
  blocked: "danger",
};
const STEP_LOOK: Record<PlanStep["status"], { icon: LucideIcon; tone: TileTone }> = {
  pending: { icon: CircleDashed, tone: "neutral" },
  running: { icon: LoaderCircle, tone: "violet" },
  awaiting: { icon: UserRound, tone: "warning" },
  succeeded: { icon: CircleCheck, tone: "success" },
  failed: { icon: CircleX, tone: "danger" },
  cancelled: { icon: Square, tone: "neutral" },
  skipped: { icon: CircleDashed, tone: "neutral" },
};

function errorSaid(t: Dictionary, error: string | null): string | null {
  if (!error) return null;
  const known = t.execution.errors as Record<string, string>;
  if (known[error]) return known[error];
  const http = /^http_(\d{3})$/.exec(error);
  return http ? fill(t.execution.errors.http, { status: http[1] }) : error;
}

function useAct(intentionId: string) {
  const t = useDictionary();
  const act = usePlanAction(intentionId);
  async function run(
    input: Parameters<typeof act.mutateAsync>[0],
    success?: string,
  ): Promise<boolean> {
    try {
      await act.mutateAsync(input);
      if (success) notify.success({ title: success });
      return true;
    } catch (error) {
      const refusal = error instanceof ApiError ? error.fieldErrors?.refusal : undefined;
      notify.error({
        title:
          refusal === "checks_failed"
            ? t.execution.refused
            : error instanceof ApiError
              ? error.message
              : String(error),
      });
      return false;
    }
  }
  return { run, pending: act.isPending };
}

/** "Préparation ✓ · Exécution ✓ · Vérification En vérification · Finalisation". */
function Stages({
  plan,
  step,
  verification,
}: {
  plan: Plan;
  step: PlanStep;
  verification: Verification | undefined;
}) {
  const t = useDictionary();
  const s = t.execution.stages;
  const prepared = plan.status !== "planned" && plan.status !== "scheduled";
  const executed = step.status === "succeeded";
  // What was done, verified (LEKA-392): achieved, it is final.
  const verified = verification?.status === "succeeded";
  const missed = verification?.status === "partial" || verification?.status === "failed";
  const stages: {
    key: string;
    label: string;
    done: boolean;
    current: boolean;
    failed?: boolean;
    note?: string;
  }[] = [
    { key: "preparation", label: s.preparation, done: prepared, current: !prepared },
    {
      key: "execution",
      label: s.execution,
      done: executed,
      current: prepared && !executed,
      note: t.execution.stepStatuses[step.status],
    },
    {
      key: "verification",
      label: s.verification,
      done: verified,
      current: verification?.status === "verifying",
      failed: missed,
      note: verification ? t.outcome.statuses[verification.status] : t.execution.later,
    },
    { key: "finalisation", label: s.finalisation, done: verified, current: false },
  ];
  return (
    <ol className="grid grid-cols-4 gap-2 text-center text-xs" data-testid="plan-stages">
      {stages.map((stage, index) => (
        <li key={stage.key} className="flex flex-col items-center gap-1">
          <span
            className={cn(
              "flex size-6 items-center justify-center rounded-full border text-[0.6875rem] font-semibold",
              stage.done
                ? "border-shell-nav-active bg-brand-violet-soft text-shell-nav-active"
                : stage.failed
                  ? "border-state-danger bg-state-danger-soft text-state-danger"
                  : stage.current
                    ? "border-shell-nav-active bg-shell-nav-active text-white"
                    : "border-shell-line text-shell-muted",
            )}
          >
            {stage.done ? (
              <Check className="size-3.5" aria-hidden="true" />
            ) : stage.failed ? (
              <CircleX className="size-3.5" aria-hidden="true" />
            ) : (
              index + 1
            )}
          </span>
          <span className="font-medium text-brand-navy">{stage.label}</span>
          {stage.note ? (
            <span className={stage.failed ? "text-state-danger" : "text-shell-muted"}>
              {stage.note}
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function Evidence({ step }: { step: PlanStep }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.execution.evidence;
  const evidence = step.evidence as {
    request?: { url?: string; signed_at?: number };
    response?: { status?: number; duration_ms?: number } | null;
    outcome?: { ref?: string | null; reason?: string | null };
    reported?: { note?: string; link?: string | null };
  };
  const lines: React.ReactNode[] = [];
  if (evidence.request?.url) {
    lines.push(
      <span key="sent">
        {fill(w.sent, { url: evidence.request.url })}
        {evidence.request.signed_at
          ? ` · ${fill(w.signed, {
              at: exactDate(locale, new Date(evidence.request.signed_at * 1000).toISOString()),
            })}`
          : ""}
      </span>,
    );
  }
  if (evidence.response?.status) {
    lines.push(
      <span key="answered">
        {fill(w.answered, {
          status: evidence.response.status,
          ms: evidence.response.duration_ms ?? 0,
        })}
      </span>,
    );
  }
  if (evidence.outcome?.ref) {
    lines.push(<span key="ref">{fill(w.ref, { ref: evidence.outcome.ref })}</span>);
  }
  if (evidence.outcome?.reason === "unconfirmed") {
    lines.push(<span key="unconfirmed">{w.unconfirmed}</span>);
  }
  if (evidence.reported?.note) {
    lines.push(
      <span key="reported">
        {fill(w.reported, { note: evidence.reported.note })}
        {evidence.reported.link && /^https?:\/\//i.test(evidence.reported.link) ? (
          <>
            {" · "}
            <a
              href={evidence.reported.link}
              target="_blank"
              rel="noreferrer"
              className="text-shell-nav-active hover:underline"
            >
              {w.open}
            </a>
          </>
        ) : null}
      </span>,
    );
  }
  if (!lines.length) return null;
  return (
    <ul className="space-y-0.5 text-xs text-shell-muted" data-testid="step-evidence">
      {lines.map((line, index) => (
        <li key={index}>{line}</li>
      ))}
    </ul>
  );
}

/** A person's word on a step that waits on them. */
function Report({ intentionId, step }: { intentionId: string; step: PlanStep }) {
  const t = useDictionary();
  const w = t.execution;
  const { run, pending } = useAct(intentionId);
  const [note, setNote] = useState("");
  const [link, setLink] = useState("");
  async function say(outcome: "succeeded" | "failed") {
    if (!note.trim()) {
      notify.error({ title: w.noteRequired });
      return;
    }
    await run({
      kind: "report",
      stepId: step.id,
      outcome,
      note: note.trim(),
      link: link.trim() || null,
    });
  }
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-state-warning/40 bg-state-warning-soft/40 p-3">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-shell-nav">{w.reportNote}</span>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={2}
          className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          data-testid="step-report-note"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-shell-nav">{w.reportLink}</span>
        <input
          value={link}
          onChange={(event) => setLink(event.target.value)}
          className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          data-testid="step-report-link"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={pending}
          onClick={() => void say("succeeded")}
          data-testid="step-done"
        >
          <Check className="size-4" aria-hidden="true" />
          {w.markDone}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={pending}
          className="border-state-danger/40 text-state-danger hover:bg-state-danger-soft"
          onClick={() => void say("failed")}
          data-testid="step-failed"
        >
          <CircleX className="size-4" aria-hidden="true" />
          {w.markFailed}
        </Button>
      </div>
    </div>
  );
}

function StepCard({
  plan,
  step,
  steward,
  verification,
}: {
  plan: Plan;
  step: PlanStep;
  steward: boolean;
  verification: Verification | undefined;
}) {
  const t = useDictionary();
  const w = t.execution;
  const look = STEP_LOOK[step.status];
  const Icon = look.icon;
  const targets = step.targets.map((target) => String(target.name)).join(", ");
  return (
    <li
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4"
      data-testid="plan-step"
      data-status={step.status}
      data-executor={step.executor}
    >
      <div className="flex flex-wrap items-start gap-3">
        <Icon
          className={cn(
            "mt-0.5 size-5 shrink-0",
            step.status === "running" && SPINNING,
            look.tone === "success" && "text-state-success",
            look.tone === "danger" && "text-state-danger",
            look.tone === "warning" && "text-state-warning",
            look.tone === "violet" && "text-shell-nav-active",
            look.tone === "neutral" && "text-shell-muted",
          )}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-brand-navy">
            {actionWord(t, step.action)} · {targets}
            {step.environment ? ` · ${step.environment}` : ""}
          </p>
          <p className="flex items-center gap-1 text-[0.8125rem] text-shell-muted">
            {step.executor === "webhook" ? (
              <Webhook className="size-3.5" aria-hidden="true" />
            ) : (
              <UserRound className="size-3.5" aria-hidden="true" />
            )}
            {step.executor === "webhook"
              ? fill(w.byWebhook, { name: step.endpoint_name ?? "-" })
              : w.byPerson}
          </p>
          {step.error ? (
            <p className="text-[0.8125rem] text-state-danger">{errorSaid(t, step.error)}</p>
          ) : null}
        </div>
        <Pill tone={look.tone} data-testid="step-status">
          {w.stepStatuses[step.status]}
        </Pill>
      </div>
      <Stages plan={plan} step={step} verification={verification} />
      <Evidence step={step} />
      {step.status === "awaiting" && plan.controls.includes("confirm_step") && steward ? (
        <Report intentionId={plan.intention_id} step={step} />
      ) : null}
    </li>
  );
}

function Checks({ plan }: { plan: Plan }) {
  const t = useDictionary();
  if (!plan.checks.length) return null;
  const said = t.execution.checks as Record<string, string>;
  // One line per kind of check: failed if any of its kind failed.
  const byCode = new Map<string, boolean>();
  for (const check of plan.checks) {
    byCode.set(check.code, (byCode.get(check.code) ?? true) && check.passed);
  }
  return (
    <div>
      <p className="mb-1.5 text-sm font-semibold text-brand-navy">{t.execution.checksTitle}</p>
      <ul className="space-y-1 text-[0.8125rem]" data-testid="plan-checks">
        {[...byCode].map(([code, passed]) => (
          <li
            key={code}
            className="flex items-center gap-2"
            data-check={code}
            data-passed={passed ? "true" : "false"}
          >
            {passed ? (
              <CircleCheck className="size-4 text-state-success" aria-hidden="true" />
            ) : (
              <CircleX className="size-4 text-state-danger" aria-hidden="true" />
            )}
            <span className={passed ? "text-brand-navy" : "font-medium text-state-danger"}>
              {said[code] ?? code}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Journal({ events }: { events: readonly PlanEvent[] }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const me = useCurrentUser();
  const w = t.execution;
  if (!events.length) return null;
  return (
    <Card
      title={w.journal}
      icon={<ListChecks className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <ol className="relative space-y-3 border-s border-shell-line ps-5" data-testid="plan-journal">
        {[...events].reverse().map((event) => (
          <li key={event.id} className="relative" data-kind={event.kind}>
            <span
              aria-hidden="true"
              className="absolute top-1.5 -start-[1.6rem] size-2.5 rounded-full border-2 border-white bg-brand-violet"
            />
            <p className="text-[0.875rem] font-medium text-brand-navy">
              {(w.events as Record<string, string>)[event.kind] ?? event.kind}
            </p>
            <p className="text-xs text-shell-muted">
              <time dateTime={event.at}>{exactDate(locale, event.at)}</time> ·{" "}
              {event.actor === "system" ? w.by.leka : event.by === me?.id ? w.by.you : w.by.someone}
            </p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** A local datetime input's value for an instant. */
function localInput(iso: string | null | undefined): string {
  const at = iso ? new Date(iso) : new Date(Date.now() + 60 * 60_000);
  const shifted = new Date(at.getTime() - at.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

function Controls({ plan, intention }: { plan: Plan; intention: IntentionDetail }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.execution;
  const confirm = useConfirm();
  const { run, pending } = useAct(plan.intention_id);
  const [at, setAt] = useState(localInput(plan.suggested_for));
  const windowed = plan.steps
    .flatMap((step) => step.constraints)
    .find((c) => c.kind === "window" && typeof c.value === "string");

  async function stop(scheduled: boolean) {
    const reason = await confirm({
      title: scheduled ? w.unscheduleTitle : w.cancelTitle,
      description: scheduled ? w.unscheduleBody : w.cancelBody,
      confirmLabel: scheduled ? w.unschedule : w.cancel,
      destructive: !scheduled,
      reasonLabel: w.reason,
    });
    if (reason === null) return;
    if (!reason.trim()) {
      notify.error({ title: w.reasonRequired });
      return;
    }
    await run({ kind: "cancel", reason: reason.trim() });
  }

  // What may be done with it now is the API's (LEKA-443): the rules its
  // routes apply — never a button they would refuse.
  const can = (control: Plan["controls"][number]) => plan.controls.includes(control);
  if (plan.status === "planned" && can("start")) {
    return (
      <div className="flex flex-col gap-3" data-testid="plan-controls">
        {plan.suggested_for && windowed ? (
          <p className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
            <CalendarClock className="size-4 text-shell-nav-active" aria-hidden="true" />
            {fill(w.suggested, {
              window: String(windowed.value),
              at: exactDate(locale, plan.suggested_for),
            })}
          </p>
        ) : null}
        <div className="flex flex-wrap items-end gap-2">
          <Button
            type="button"
            disabled={pending}
            data-testid="plan-start"
            onClick={async () => {
              const yes = await confirm({
                title: w.startTitle,
                description: w.startBody,
                confirmLabel: w.startNow,
                impact: plan.steps.map((step) =>
                  [
                    actionWord(t, step.action),
                    step.targets.map((target) => String(target.name)).join(", "),
                    step.environment,
                  ]
                    .filter(Boolean)
                    .join(" · "),
                ),
              });
              if (yes) await run({ kind: "start", timezone: browserZone() });
            }}
          >
            <Play className="size-4" aria-hidden="true" />
            {w.startNow}
          </Button>
          <label className="flex flex-col gap-1 text-xs text-shell-nav">
            {w.scheduleAt}
            <input
              type="datetime-local"
              value={at}
              onChange={(event) => setAt(event.target.value)}
              className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              data-testid="plan-schedule-at"
            />
          </label>
          <Button
            type="button"
            variant="outline"
            disabled={pending || !at}
            data-testid="plan-schedule"
            onClick={() =>
              void run({
                kind: "start",
                scheduled_for: new Date(at).toISOString(),
                timezone: browserZone(),
              })
            }
          >
            <CalendarClock className="size-4" aria-hidden="true" />
            {w.schedule}
          </Button>
        </div>
      </div>
    );
  }
  if (plan.status === "scheduled" && can("unschedule")) {
    return (
      <div className="flex flex-wrap items-center gap-3" data-testid="plan-controls">
        <p className="text-[0.8125rem] text-brand-navy">
          {fill(w.scheduledFor, {
            at: plan.scheduled_for ? exactDate(locale, plan.scheduled_for) : "-",
          })}
        </p>
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={() => void stop(true)}
          data-testid="plan-cancel"
        >
          {w.unschedule}
        </Button>
      </div>
    );
  }
  if (plan.status === "running" && can("stop")) {
    return (
      <div className="flex flex-wrap items-center gap-3" data-testid="plan-controls">
        <p className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
          <ShieldCheck className="size-4 text-shell-nav-active" aria-hidden="true" />
          {w.control}
        </p>
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          className="border-state-danger/40 text-state-danger hover:bg-state-danger-soft"
          onClick={() => void stop(false)}
          data-testid="plan-cancel"
        >
          <Square className="size-4" aria-hidden="true" />
          {w.cancel}
        </Button>
      </div>
    );
  }
  // Over — failed, stopped, or ran but what was expected did not come
  // (LEKA-392): a new plan of what did not succeed.
  if (can("plan")) {
    return (
      <div data-testid="plan-controls">
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          onClick={() => void run({ kind: "plan" })}
          data-testid="plan-retry"
        >
          <RotateCw className="size-4" aria-hidden="true" />
          {intention.status === "failed" ? w.retry : w.prepare}
        </Button>
      </div>
    );
  }
  return null;
}

function PlanView({
  plan,
  intention,
  steward,
}: {
  plan: Plan;
  intention: IntentionDetail;
  steward: boolean;
}) {
  const t = useDictionary();
  const w = t.execution;
  // Once it ran, whether it achieved what was expected (LEKA-392).
  const verifications = useVerifications(plan.intention_id, plan.status === "succeeded");
  const verification = verifications.data?.find((v) => v.plan_id === plan.id);
  // Mockup 06: the plan, its steps and what came of it on the left; its
  // journal on the right; what it changed, across, under both.
  return (
    <div className="flex flex-col gap-4" data-testid="plan" data-status={plan.status}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start">
        <div className="flex min-w-0 flex-col gap-4">
          <section className="flex flex-col gap-4 rounded-xl border border-shell-line bg-white p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[1.0625rem] font-semibold text-brand-navy">
                {fill(w.plan, { number: plan.number })}
              </h2>
              <Pill tone={PLAN_TONES[plan.status]} data-testid="plan-status">
                {/* Run is not done: until its outcome is verified, said so
                    (LEKA-443). */}
                {plan.status === "succeeded" && intention.journey.state === "to_verify"
                  ? w.succeededToVerify
                  : w.statuses[plan.status]}
              </Pill>
              {plan.started_at ? (
                <span className="text-xs text-shell-muted">{timeAgo(t, plan.started_at)}</span>
              ) : null}
            </div>
            {plan.status === "succeeded" ? (
              <p className="text-[0.875rem] text-brand-navy">{w.succeededBody}</p>
            ) : plan.status === "failed" || plan.status === "blocked" ? (
              <p className="text-[0.875rem] text-state-danger">
                {w.failedBody}
                {plan.error ? ` ${errorSaid(t, plan.error)}` : ""}
              </p>
            ) : null}
            <Checks plan={plan} />
            {steward ? (
              <Controls plan={plan} intention={intention} />
            ) : (
              <p className="text-[0.8125rem] text-shell-muted">{w.readOnly}</p>
            )}
          </section>
          {verification ? (
            <VerificationCard verification={verification} steward={steward} />
          ) : (
            <ExpectedOutcome plan={plan} steward={steward} />
          )}
          <ul className="flex flex-col gap-3" data-testid="plan-steps">
            {plan.steps.map((step) => (
              <StepCard
                key={step.id}
                plan={plan}
                step={step}
                steward={steward}
                verification={verification}
              />
            ))}
          </ul>
        </div>
        <aside className="min-w-0">
          <Journal events={plan.events} />
        </aside>
      </div>
      <ImpactBanner intentionId={plan.intention_id} />
    </div>
  );
}

export function ActionsTab({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.execution;
  const steward = usePermissions()?.includes("intention:approve") ?? false;
  const plans = usePlans(intention.id);
  const { run, pending } = useAct(intention.id);
  if (plans.isError) return <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />;
  if (!plans.data) {
    return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  }
  const [latest] = plans.data;
  if (latest) return <PlanView plan={latest} intention={intention} steward={steward} />;
  if (intention.journey.controls.includes("start_actions")) {
    return (
      <section
        className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-5"
        data-testid="plan-prepare"
      >
        <h2 className="text-[1.0625rem] font-semibold text-brand-navy">{w.title}</h2>
        <p className="text-[0.875rem] text-shell-muted">{w.prepareBody}</p>
        {steward ? (
          <div>
            <Button
              type="button"
              disabled={pending}
              onClick={() => void run({ kind: "plan" })}
              data-testid="plan-prepare-button"
            >
              <ListChecks className="size-4" aria-hidden="true" />
              {w.prepare}
            </Button>
          </div>
        ) : (
          <p className="text-[0.8125rem] text-shell-muted">{w.readOnly}</p>
        )}
      </section>
    );
  }
  // A question asks nothing to be done: LEKA answers it — not « once the
  // decision is approved », there is none to wait for.
  const understood = intention.understanding;
  const asking =
    understood !== null &&
    understood !== undefined &&
    understood.goal.code !== "act" &&
    !understood.actions.some((action) => action.changes_systems);
  if (asking) {
    return (
      <div
        className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem]"
        data-testid="plan-question"
      >
        <p className="font-semibold text-brand-navy">{w.questionTitle}</p>
        <p className="text-shell-muted">{w.questionBody}</p>
      </div>
    );
  }
  return (
    <div
      className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem]"
      data-testid="plan-none"
    >
      <p className="font-semibold text-brand-navy">{w.emptyTitle}</p>
      <p className="text-shell-muted">
        {intention.journey.state === "decision_required" ? w.waitingDecision : w.emptyBody}
      </p>
    </div>
  );
}
