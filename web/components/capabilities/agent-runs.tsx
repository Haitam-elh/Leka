"use client";

import { Ban, Download, Play, Workflow } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { TileTone } from "@/components/environment/parts";
import {
  ACTIVE,
  type AgentRun,
  type AgentRunDetail,
  type AgentRunEvent,
  type RunInputs,
} from "@/lib/agent-runs";
import { useAgentRun, useAgentRunChange, useAgentRuns } from "@/lib/agent-runs-queries";
import { ApiError } from "@/lib/api";
import type { CapabilityDetail } from "@/lib/capabilities";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * An agent, run (LEKA-395): given what its contract takes, then followed —
 * queued, running, done or failed and why — what it delivered, every step
 * it took: its context, each tool it called and what came of it, what its
 * model calls cost. Its instructions stay on the server.
 */

const STATUS_TONE: Record<string, TileTone> = {
  queued: "neutral",
  running: "info",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
};

type Field = CapabilityDetail["inputs"][number];
type Values = Record<string, string | boolean>;

/** What the form holds, as the contract takes it: an empty optional left out. */
export function inputsOf(fields: Field[], values: Values): RunInputs {
  const said: RunInputs = {};
  for (const field of fields) {
    const value = values[field.name];
    if (field.type === "boolean") {
      if (value === true || field.required) said[field.name] = value === true;
      continue;
    }
    const text = typeof value === "string" ? value.trim() : "";
    if (!text) continue;
    said[field.name] = field.type === "number" && !Number.isNaN(Number(text)) ? Number(text) : text;
  }
  return said;
}

export function RunAgent({
  capability,
  intentionId,
}: {
  capability: CapabilityDetail;
  /** Run for an intention: its context is the agent's (LEKA-398). */
  intentionId?: string;
}) {
  const t = useDictionary();
  const w = t.agentRuns;
  const { start } = useAgentRunChange();
  const [values, setValues] = useState<Values>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setErrors({});
    try {
      await start.mutateAsync({
        key: capability.key,
        inputs: inputsOf(capability.inputs, values),
        intention_id: intentionId ?? null,
      });
      notify.success({ title: w.queued, description: w.queuedHint });
      setValues({});
    } catch (error) {
      if (error instanceof ApiError && error.fieldErrors) {
        setErrors(error.fieldErrors);
      }
      notify.error({ title: error instanceof ApiError ? error.message : w.failedToStart });
    }
  }

  return (
    <Card title={w.run} icon={<Play className="size-4 text-shell-muted" aria-hidden="true" />}>
      <form className="flex flex-col gap-3" onSubmit={(e) => void run(e)} data-testid="agent-run-form">
        {capability.inputs.map((field) => {
          const id = `agent-input-${field.name}`;
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
                    <span className="font-normal text-shell-muted">
                      {" · "}
                      {field.required ? t.catalogue.detail.required : t.catalogue.detail.optional}
                    </span>
                  </label>
                  {field.type === "choice" ? (
                    <select
                      id={id}
                      className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm"
                      value={String(values[field.name] ?? "")}
                      onChange={(e) => setValues((was) => ({ ...was, [field.name]: e.target.value }))}
                    >
                      <option value="">—</option>
                      {field.choices.map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      id={id}
                      type={field.type === "number" ? "number" : "text"}
                      placeholder={field.description}
                      aria-invalid={Boolean(error)}
                      value={String(values[field.name] ?? "")}
                      onChange={(e) => setValues((was) => ({ ...was, [field.name]: e.target.value }))}
                    />
                  )}
                </>
              )}
              {error ? (
                <p className="text-xs text-state-danger" role="alert">
                  {(w.inputErrors as Record<string, string>)[error] ?? error}
                </p>
              ) : null}
            </div>
          );
        })}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!capability.available || start.isPending}>
            <Play className="size-4" aria-hidden="true" />
            {start.isPending ? w.starting : w.start}
          </Button>
          <span className="text-xs text-shell-muted">
            {capability.available ? w.readOnly : w.cannotRun}
          </span>
        </div>
      </form>
    </Card>
  );
}

function statusSaid(w: Dictionary["agentRuns"], run: AgentRun): string {
  const said = (w.statuses as Record<string, string>)[run.status] ?? run.status;
  if (run.status !== "failed" || !run.error) return said;
  return `${said} · ${(w.errors as Record<string, string>)[run.error] ?? run.error}`;
}

function stepSaid(w: Dictionary["agentRuns"], event: AgentRunEvent): string {
  const detail = event.detail as Record<string, unknown>;
  const template = (w.steps as Record<string, string>)[event.kind] ?? event.kind;
  return fill(template, {
    name: String(detail.name ?? ""),
    outcome: (w.outcomes as Record<string, string>)[String(detail.outcome)] ?? String(detail.outcome ?? ""),
    given: String(detail.given ?? 0),
    left: String(Number(detail.out_of_scope ?? 0) + Number(detail.beyond ?? 0)),
    why: (w.withheld as Record<string, string>)[String(detail.why)] ?? String(detail.why ?? ""),
    model: String(detail.model ?? ""),
    code: (w.errors as Record<string, string>)[String(detail.code)] ?? String(detail.code ?? ""),
  });
}

function download(run: AgentRunDetail) {
  const type = run.format === "json" ? "application/json" : "text/markdown";
  const url = URL.createObjectURL(new Blob([run.output ?? ""], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${run.key}-${run.id.slice(0, 8)}.${run.format === "json" ? "json" : "md"}`;
  link.click();
  URL.revokeObjectURL(url);
}

function RunDetail({ id }: { id: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.agentRuns;
  const { data } = useAgentRun(id);
  if (!data) return <div className="h-24 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  return (
    <div className="mt-2 flex flex-col gap-3 rounded-lg bg-shell-canvas p-3" data-testid="agent-run-detail">
      {data.output ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-shell-muted">{w.delivered}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => download(data)}>
              <Download className="size-3.5" aria-hidden="true" />
              {w.download}
            </Button>
          </div>
          <pre
            className="max-h-96 overflow-auto rounded-md bg-white p-3 text-xs whitespace-pre-wrap text-brand-navy"
            data-testid="agent-run-output"
          >
            {data.output}
          </pre>
          {data.pending.length ? (
            <p className="text-xs text-shell-muted">
              {fill(w.pending, { formats: data.pending.map((f) => f.toUpperCase()).join(", ") })}
            </p>
          ) : null}
        </div>
      ) : null}
      {data.reasons.length ? (
        <p className="text-xs text-state-warning">
          {data.reasons.map((r) => String((r as Record<string, unknown>).code)).join(", ")}
        </p>
      ) : null}
      <div>
        <p className="mb-1 text-xs font-semibold text-shell-muted">{w.stepsTitle}</p>
        <ol className="space-y-1 text-xs" data-testid="agent-run-steps">
          {data.events.map((event) => (
            <li key={`${event.seq}-${event.kind}-${event.at}`} className="text-brand-navy">
              {stepSaid(w, event)}{" "}
              <span className="text-shell-muted">· {exactDate(locale, event.at)}</span>
            </li>
          ))}
        </ol>
      </div>
      <p className="text-xs text-shell-muted" data-testid="agent-run-usage">
        {fill(w.usage, {
          calls: String(data.usage.calls),
          tokens: String(data.usage.tokens_in + data.usage.tokens_out),
        })}
        {data.usage.cost_usd !== null ? ` · ${data.usage.cost_usd.toFixed(4)} $` : ""}
      </p>
    </div>
  );
}

export function AgentRuns({ agentKey }: { agentKey: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.agentRuns;
  const { data } = useAgentRuns(agentKey);
  const { cancel } = useAgentRunChange();
  const [open, setOpen] = useState<string | null>(null);

  async function stop(run: AgentRun) {
    try {
      await cancel.mutateAsync(run.id);
      notify.success({ title: w.cancelled });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.cancelFailed });
    }
  }

  return (
    <Card title={w.title} icon={<Workflow className="size-4 text-shell-muted" aria-hidden="true" />}>
      {!data?.length ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="agent-runs">
          {data.map((run) => (
            <li key={run.id} className="rounded-lg border border-shell-line p-3" data-testid="agent-run">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={STATUS_TONE[run.status] ?? "neutral"} dot={ACTIVE.has(run.status)}>
                  {statusSaid(w, run)}
                </Pill>
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left text-[0.8125rem] text-brand-navy hover:underline"
                  aria-expanded={open === run.id}
                  onClick={() => setOpen(open === run.id ? null : run.id)}
                >
                  {Object.values(run.inputs).filter((v) => typeof v === "string").join(" · ") ||
                    run.title}
                </button>
                {ACTIVE.has(run.status) && run.mine ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void stop(run)}>
                    <Ban className="size-3.5" aria-hidden="true" />
                    {w.cancel}
                  </Button>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-shell-muted">
                {exactDate(locale, run.queued_at)}
                {run.mine ? ` · ${w.byYou}` : ""}
                {run.model ? ` · ${run.model}` : ""}
                {run.tool_calls ? ` · ${fill(w.toolCalls, { count: run.tool_calls })}` : ""}
              </p>
              {open === run.id ? <RunDetail id={run.id} /> : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
