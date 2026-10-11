"use client";

import { useQuery } from "@tanstack/react-query";
import { Ban, ListOrdered, Play, RotateCcw, Workflow as WorkflowIcon } from "lucide-react";
import { useState } from "react";

import { inputsOf } from "@/components/capabilities/agent-runs";
import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import type { CapabilityDetail } from "@/lib/capabilities";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { intentions } from "@/lib/intentions/api";
import { notify } from "@/lib/notify";
import { RUNNING, type Workflow, type WorkflowRun, type WorkflowStep } from "@/lib/workflows";
import {
  useWorkflow,
  useWorkflowChange,
  useWorkflowRun,
  useWorkflowRuns,
} from "@/lib/workflows-queries";

/**
 * A workflow (LEKA-397), on its capability's sheet: its steps in order —
 * what each uses, what it runs after, on what condition, how often it is
 * tried, whether its failure stops the rest — run for an intention, and its
 * runs followed step by step: each step's state, why one was skipped or
 * failed, the run retried from where it failed, or cancelled.
 */

const RUN_TONE: Record<string, TileTone> = {
  queued: "neutral",
  running: "info",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
};
const STEP_TONE: Record<string, TileTone> = {
  pending: "neutral",
  running: "info",
  succeeded: "success",
  failed: "danger",
  skipped: "neutral",
  not_reached: "neutral",
};

type Said = Record<string, unknown>;

/** A condition, in words. */
export function whenSaid(t: Dictionary, when: Said | null | undefined): string {
  const w = t.workflows.when;
  if (!when) return w.always;
  if (Array.isArray(when.all)) return (when.all as Said[]).map((c) => whenSaid(t, c)).join(w.and);
  if (Array.isArray(when.any)) return (when.any as Said[]).map((c) => whenSaid(t, c)).join(w.or);
  if (when.not) return fill(w.not, { said: whenSaid(t, when.not as Said) });
  if (typeof when.step === "string" && typeof when.found === "string") {
    return fill(w.found, { step: when.step, code: when.found });
  }
  if (typeof when.step === "string") {
    const statuses = (Array.isArray(when.status) ? when.status : [when.status]).map(
      (s) => (t.workflows.stepStatuses as Record<string, string>)[String(s)] ?? String(s),
    );
    return fill(w.status, { step: when.step, status: statuses.join(w.or) });
  }
  return fill(w.input, { input: String(when.input), value: String(when.equals) });
}

export function WorkflowSteps({ workflow }: { workflow: Workflow }) {
  const t = useDictionary();
  const w = t.workflows;
  return (
    <Card title={w.steps} icon={<ListOrdered className="size-4 text-shell-muted" aria-hidden="true" />}>
      <ol className="space-y-3 text-[0.8125rem]" data-testid="workflow-steps">
        {workflow.steps.map((step: WorkflowStep, n) => (
          <li key={step.id} data-step={step.id} className="flex flex-col">
            <span className="font-medium text-brand-navy">
              {n + 1}. {step.title ?? step.id}{" "}
              <span className="font-normal text-shell-muted">· {step.uses_title ?? step.uses}</span>
            </span>
            <span className="text-xs text-shell-muted">
              {[
                step.after.length ? fill(w.after, { steps: step.after.join(", ") }) : null,
                whenSaid(t, step.when as Said | null),
                step.attempts > 1 ? fill(w.attempts, { count: step.attempts }) : null,
                step.on_failure === "continue" ? w.continues : w.stops,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function useRecentIntentions(enabled: boolean) {
  return useQuery({
    queryKey: ["intentions", "recent-for-workflows"],
    queryFn: () => intentions.list({ limit: 20 }),
    enabled,
  });
}

export function RunWorkflow({
  capability,
  workflow,
  intentionId,
}: {
  capability: CapabilityDetail;
  workflow: Workflow;
  /** Run for this intention: its context is what LEKA's own steps read. */
  intentionId?: string;
}) {
  const t = useDictionary();
  const w = t.workflows;
  const { start } = useWorkflowChange();
  const needsIntention = workflow.steps.some((s) => s.uses_kind === "rules");
  const choosing = needsIntention && !intentionId;
  const recent = useRecentIntentions(choosing);
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [chosen, setChosen] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setErrors({});
    try {
      await start.mutateAsync({
        key: workflow.key,
        inputs: inputsOf(capability.inputs, values),
        intention_id: intentionId ?? (chosen || null),
      });
      notify.success({ title: w.queued });
      setValues({});
    } catch (error) {
      if (error instanceof ApiError && error.fieldErrors) setErrors(error.fieldErrors);
      notify.error({ title: error instanceof ApiError ? error.message : w.failedToStart });
    }
  }

  return (
    <Card title={w.run} icon={<Play className="size-4 text-shell-muted" aria-hidden="true" />}>
      <form className="flex flex-col gap-3" onSubmit={(e) => void run(e)} data-testid="workflow-run-form">
        {choosing ? (
          <div className="flex flex-col gap-1">
            <label htmlFor="workflow-intention" className="text-[0.8125rem] font-medium text-brand-navy">
              {w.intention}
            </label>
            <select
              id="workflow-intention"
              className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm"
              value={chosen}
              onChange={(e) => setChosen(e.target.value)}
            >
              <option value="">—</option>
              {(recent.data?.data ?? []).map((intention) => (
                <option key={intention.id} value={intention.id}>
                  {intention.title}
                </option>
              ))}
            </select>
            {errors.intention_id ? (
              <p className="text-xs text-state-danger" role="alert">
                {w.intentionRequired}
              </p>
            ) : null}
          </div>
        ) : null}
        {capability.inputs.map((field) => {
          const id = `workflow-input-${field.name}`;
          const error = errors[`inputs.${field.name}`];
          return (
            <div key={field.name} className="flex flex-col gap-1">
              {field.type === "boolean" ? (
                <label htmlFor={id} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
                  <Checkbox
                    id={id}
                    checked={values[field.name] === true}
                    onCheckedChange={(checked) =>
                      setValues((was) => ({ ...was, [field.name]: checked === true }))
                    }
                  />
                  {field.description || field.name}
                </label>
              ) : (
                <>
                  <label htmlFor={id} className="text-[0.8125rem] font-medium text-brand-navy">
                    {field.name}
                  </label>
                  <Input
                    id={id}
                    placeholder={field.description}
                    aria-invalid={Boolean(error)}
                    value={String(values[field.name] ?? "")}
                    onChange={(e) => setValues((was) => ({ ...was, [field.name]: e.target.value }))}
                  />
                </>
              )}
              {error ? (
                <p className="text-xs text-state-danger" role="alert">
                  {(t.agentRuns.inputErrors as Record<string, string>)[error] ?? error}
                </p>
              ) : null}
            </div>
          );
        })}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!workflow.available || start.isPending}>
            <Play className="size-4" aria-hidden="true" />
            {w.start}
          </Button>
          <span className="text-xs text-shell-muted">
            {workflow.available ? t.agentRuns.readOnly : t.agentRuns.cannotRun}
          </span>
        </div>
      </form>
    </Card>
  );
}

function runSaid(w: Dictionary["workflows"], run: WorkflowRun): string {
  const said = (w.statuses as Record<string, string>)[run.status] ?? run.status;
  if (run.status !== "failed") return said;
  if (run.failed_step) return `${said} · ${fill(w.failedAt, { step: run.failed_step })}`;
  return `${said} · ${(w.errors as Record<string, string>)[run.error ?? ""] ?? run.error ?? ""}`;
}

function RunDetail({ id }: { id: string }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.workflows;
  const { data } = useWorkflowRun(id);
  if (!data) return <div className="h-16 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg bg-shell-canvas p-3" data-testid="workflow-run-detail">
      <ol className="space-y-1 text-xs">
        {data.steps.map((step) => (
          <li key={step.step} className="flex flex-wrap items-center gap-2" data-step={step.step}>
            <Pill tone={STEP_TONE[step.status] ?? "neutral"}>
              {(w.stepStatuses as Record<string, string>)[step.status] ?? step.status}
            </Pill>
            <span className="text-brand-navy">{step.step}</span>
            {step.attempts > 1 ? (
              <span className="text-shell-muted">{fill(w.attempts, { count: step.attempts })}</span>
            ) : null}
            {step.reason ? (
              <span className="text-shell-muted">
                · {(w.reasons as Record<string, string>)[step.reason] ?? step.reason}
              </span>
            ) : null}
          </li>
        ))}
      </ol>
      <p className="text-xs text-shell-muted">
        {fill(w.events, { count: data.events.length })} · {exactDate(locale, data.queued_at)}
        {data.retries ? ` · ${fill(w.retried, { count: data.retries })}` : ""}
      </p>
    </div>
  );
}

export function WorkflowRuns({ workflowKey }: { workflowKey: string }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.workflows;
  const { data } = useWorkflowRuns(workflowKey);
  const { cancel, retry } = useWorkflowChange();
  const [open, setOpen] = useState<string | null>(null);

  async function act(kind: "cancel" | "retry", run: WorkflowRun) {
    try {
      await (kind === "cancel" ? cancel : retry).mutateAsync(run.id);
      notify.success({ title: kind === "cancel" ? w.cancelled : w.retrying });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failedToStart });
    }
  }

  return (
    <Card title={w.runs} icon={<WorkflowIcon className="size-4 text-shell-muted" aria-hidden="true" />}>
      {!data?.length ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="workflow-runs">
          {data.map((run) => (
            <li key={run.id} className="rounded-lg border border-shell-line p-3" data-testid="workflow-run">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={RUN_TONE[run.status] ?? "neutral"} dot={RUNNING.has(run.status)}>
                  {runSaid(w, run)}
                </Pill>
                <button
                  type="button"
                  className="min-w-0 flex-1 text-start text-[0.8125rem] text-brand-navy hover:underline"
                  aria-expanded={open === run.id}
                  onClick={() => setOpen(open === run.id ? null : run.id)}
                >
                  {exactDate(locale, run.queued_at)}
                  {run.mine ? ` · ${t.agentRuns.byYou}` : ""}
                </button>
                {run.retryable ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void act("retry", run)}>
                    <RotateCcw className="size-3.5" aria-hidden="true" />
                    {w.retry}
                  </Button>
                ) : null}
                {RUNNING.has(run.status) && run.mine ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void act("cancel", run)}>
                    <Ban className="size-3.5" aria-hidden="true" />
                    {t.agentRuns.cancel}
                  </Button>
                ) : null}
              </div>
              {open === run.id ? <RunDetail id={run.id} /> : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** A workflow's part of its capability's sheet. */
export function WorkflowPanel({
  capability,
  intentionId,
}: {
  capability: CapabilityDetail;
  intentionId?: string;
}) {
  const { data } = useWorkflow(capability.key);
  if (!data) return null;
  return (
    <>
      <WorkflowSteps workflow={data} />
      <RunWorkflow capability={capability} workflow={data} intentionId={intentionId} />
      {intentionId ? null : <WorkflowRuns workflowKey={capability.key} />}
    </>
  );
}
